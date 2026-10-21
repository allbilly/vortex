`timescale 1ns/1ps
`include "VX_define.vh"

module dxa_setup_tb;
    import VX_gpu_pkg::*;
    import VX_dxa_pkg::*;

    reg clk = 0;
    always #1 clk = ~clk;
    reg reset;
    reg req_valid;
    wire req_ready;
    reg transfer_done;
    dxa_req_data_t req_data;
    dxa_desc_t desc_data;
    wire pipeline_start;
    dxa_setup_params_t params;

    VX_dxa_setup dut (
        .clk(clk),
        .reset(reset),
        .req_valid(req_valid),
        .req_ready(req_ready),
        .req_data(req_data),
        .desc_data(desc_data),
        .transfer_done(transfer_done),
        .transfer_active(),
        .pipeline_start(pipeline_start),
        .setup_params(params),
        .active_core_id(),
        .active_uuid(),
        .active_wid(),
        .active_bar_addr(),
        .active_notify_smem_done(),
        .active_is_multicast(),
        .active_cta_mask(),
        .active_smem_stride()
    );

    task automatic check_case(input int id, input int rank, input int esize, input int pattern);
        logic [3:0][31:0] strides;
        logic [31:0] offset;
        logic [31:0] expected_delta;
        longint unsigned address;
        longint unsigned product;
        longint unsigned left_operand;
        longint unsigned right_operand;
        int latency;
        int tile;

        @(negedge clk);
        reset = 1;
        req_valid = 0;
        transfer_done = 0;
        repeat (4) @(posedge clk);
        @(negedge clk);
        reset = 0;
        req_data = '0;
        desc_data = '0;
        req_data.cta_mask = 1;
        req_data.uuid = UUID_WIDTH'(id);
        for (int dim = 0; dim < 5; ++dim)
            req_data.coords[dim] = (32'h9e3779b9 * 32'(id + dim)) ^ (32'h85ebca6b * 32'(pattern + dim));
        case (pattern)
            0: req_data.coords[0] = 0;
            1: req_data.coords[0] = 32'h7fffffff;
            2: req_data.coords[0] = 32'h80000000;
            3: req_data.coords[0] = 32'hffffffff;
            default: begin end
        endcase
        desc_data.meta = (32'(rank) << DXA_DESC_META_DIM_LSB)
                       | (32'(esize) << DXA_DESC_META_ELEMSZ_LSB);
        desc_data.base_addr = `VX_CFG_MEM_ADDR_WIDTH'(64'h1234ffffff00 + 64'(id));
        desc_data.tile01 = {16'd3, 16'd8};
        desc_data.tile23 = {16'd7, 16'd5};
        desc_data.tile4 = 2;
        desc_data.size0 = '1;
        desc_data.size1 = '1;
        desc_data.size2 = '1;
        desc_data.size3 = '1;
        desc_data.size4 = '1;
        for (int dim = 0; dim < 4; ++dim)
            strides[dim] = (32'h80000005 + 32'(dim) * 32'h43219877) ^ (32'(pattern) * 32'h9e3779b9);
        desc_data.stride0 = strides[0];
        desc_data.stride1 = strides[1];
        desc_data.stride2 = strides[2];
        desc_data.stride3 = strides[3];

        address = 64'(desc_data.base_addr);
        offset = req_data.coords[0] << esize;
        address += 64'(offset);
        for (int dim = 1; dim < rank; ++dim) begin
            left_operand = 64'(req_data.coords[dim]);
            right_operand = 64'(strides[dim-1]);
            product = left_operand * right_operand;
            address += 64'(32'(product));
        end

        req_valid = 1;
        @(posedge clk);
        if (!req_ready) $fatal(1, "setup request was not accepted");
        #1ps;
        @(negedge clk);
        req_valid = 0;
        latency = 0;
        while (!pipeline_start) begin
            @(posedge clk);
            #1ps;
            ++latency;
            if (latency > 20) $fatal(1, "setup timed out");
        end
        if (latency != (2 * ((rank < 2) ? 2 : rank) + 1))
            $fatal(1, "setup latency changed: rank=%0d cycles=%0d", rank, latency);
        if (params.initial_gmem_base !== `VX_CFG_MEM_ADDR_WIDTH'(address))
            $fatal(1, "address mismatch: rank=%0d size=%0d actual=%h expected=%h", rank, esize,
                   params.initial_gmem_base, `VX_CFG_MEM_ADDR_WIDTH'(address));
        if (params.row_len_bytes !== (32'd8 << esize))
            $fatal(1, "row length changed");
        for (int dim = 0; dim < 4; ++dim) begin
            expected_delta = (rank >= dim + 2) ? strides[dim] : 0;
            if (dim > 0 && rank >= dim + 2) begin
                tile = (dim == 1) ? 3 : ((dim == 2) ? 5 : 7);
                expected_delta -= 32'(tile - 1) * strides[dim-1];
            end
            if (params.delta[dim] !== expected_delta)
                $fatal(1, "delta mismatch: rank=%0d dim=%0d actual=%h expected=%h", rank, dim,
                       params.delta[dim], expected_delta);
        end
        $display("TRACE id=%0d rank=%0d esize=%0d cycles=%0d base=%h delta=%h", id, rank, esize,
                 latency, params.initial_gmem_base, params.delta);
    endtask

    initial begin
        reset = 1;
        req_valid = 0;
        transfer_done = 0;
        req_data = '0;
        desc_data = '0;
        for (int rank = 1; rank <= 5; ++rank)
            for (int esize = 0; esize < 4; ++esize)
                for (int pattern = 0; pattern < 8; ++pattern)
                    check_case((rank - 1) * 32 + esize * 8 + pattern, rank, esize, pattern);
        $display("PASSED cases=160");
        $finish;
    end
endmodule
