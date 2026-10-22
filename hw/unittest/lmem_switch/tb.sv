`timescale 1ns/1ps
`include "VX_define.vh"

module lmem_switch_tb import VX_gpu_pkg::*; #(
    parameter OUT_BUF = 1,
    parameter FAST_GLOBAL = 1
);
    reg clk = 0;
    always #5 clk = ~clk;
    reg reset = 1;
    VX_lsu_mem_if #(.NUM_LANES(2), .DATA_SIZE(LSU_WORD_SIZE), .ADDR_WIDTH(LSU_ADDR_WIDTH), .TAG_WIDTH(LSU_TAG_WIDTH)) incoming();
    VX_lsu_mem_if #(.NUM_LANES(2), .DATA_SIZE(LSU_WORD_SIZE), .ADDR_WIDTH(LSU_ADDR_WIDTH), .TAG_WIDTH(LSU_TAG_WIDTH)) global_out();
    VX_lsu_mem_if #(.NUM_LANES(2), .DATA_SIZE(LSU_WORD_SIZE), .ADDR_WIDTH(LSU_ADDR_WIDTH), .TAG_WIDTH(LSU_TAG_WIDTH)) local_out();
    VX_lmem_switch #(.GLOBAL_OUT_BUF(OUT_BUF), .LOCAL_OUT_BUF(OUT_BUF), .RSP_OUT_BUF(1)) dut (
        .clk(clk), .reset(reset), .lsu_in_if(incoming), .global_out_if(global_out), .local_out_if(local_out)
    );
    int cycles = 0, issued = 0, global_count = 0, local_count = 0;
    int next_global = 0, next_local = 0, drain = 0;
    assign incoming.rsp_ready = 1;
    assign global_out.rsp_valid = 0;
    assign global_out.rsp_data = '0;
    assign local_out.rsp_valid = 0;
    assign local_out.rsp_data = '0;

    function automatic bit wants_global(input int tag);
        return tag < 12 || tag % 2 == 0;
    endfunction
    function automatic bit wants_local(input int tag);
        return tag < 12 || tag % 2 == 1;
    endfunction
    function automatic logic [MEM_ATTR_WIDTH-1:0] attribute(input bit is_local, input int tag);
        mem_bus_attr_t value;
        value = '0;
        value.is_addr_local = is_local;
        value.amo.amo_valid = 1;
        value.amo.amo_op = AMO_OP_CAS;
        value.amo.hart_id = HART_ID_WIDTH'(is_local);
        value.amo.sc_fail = tag[0];
    `ifdef VX_CFG_EXT_ZACAS_ENABLE
        value.amo.amo_cmp = `VX_CFG_XLEN'(tag * 7 + int'(is_local) + 3);
    `endif
        return value;
    endfunction

    always @(negedge clk) begin
        incoming.req_valid = !reset && issued < 20;
        incoming.req_data = '0;
        incoming.req_data.mask = {wants_local(issued), wants_global(issued)};
        incoming.req_data.tag = LSU_TAG_WIDTH'(issued);
        for (int lane = 0; lane < 2; ++lane) begin
            incoming.req_data.addr[lane] = LSU_ADDR_WIDTH'(32'h1000 + issued * 16 + lane);
            incoming.req_data.data[lane] = `VX_CFG_XLEN'(32'h12340000 + issued * 4 + lane);
            incoming.req_data.byteen[lane] = '1;
            incoming.req_data.user[lane] = attribute(lane == 1, issued);
        end
        global_out.req_ready = !reset && ((cycles < 20) ? (FAST_GLOBAL != 0) : (cycles % 3 != 0));
        local_out.req_ready = !reset && ((cycles < 20) ? (FAST_GLOBAL == 0) : (cycles % 4 != 0));
    end

    always @(posedge clk) begin
        if (!reset) begin
            cycles = cycles + 1;
            if (incoming.req_valid && incoming.req_ready) issued = issued + 1;
            if (global_out.req_valid && global_out.req_ready) begin
                if (global_out.req_data.tag !== LSU_TAG_WIDTH'(next_global)
                    || global_out.req_data.mask !== 2'b01
                    || global_out.req_data.user[0] !== attribute(0, next_global)
                    || global_out.req_data.data[0] !== `VX_CFG_XLEN'(32'h12340000 + next_global * 4)) begin
                    $fatal(1, "Duplicate, reordered or corrupted global subset: expected tag=%0d actual=%0d", next_global, global_out.req_data.tag);
                end
                global_count = global_count + 1;
                do next_global = next_global + 1; while (next_global < 20 && !wants_global(next_global));
            end
            if (local_out.req_valid && local_out.req_ready) begin
                if (local_out.req_data.tag !== LSU_TAG_WIDTH'(next_local)
                    || local_out.req_data.mask !== 2'b10
                    || local_out.req_data.user[1] !== attribute(1, next_local)
                    || local_out.req_data.data[1] !== `VX_CFG_XLEN'(32'h12340001 + next_local * 4)) begin
                    $fatal(1, "Duplicate, reordered or corrupted local subset: expected tag=%0d actual=%0d", next_local, local_out.req_data.tag);
                end
                local_count = local_count + 1;
                do next_local = next_local + 1; while (next_local < 20 && !wants_local(next_local));
            end
            if (issued == 20 && global_count == 16 && local_count == 16) drain = drain + 1;
            if (drain == 8) begin
                $display("PASS: 20 requests, 16 global and 16 local subsets exactly once, OUT_BUF=%0d FAST_GLOBAL=%0d", OUT_BUF, FAST_GLOBAL);
                $finish;
            end
            if (cycles > 400) $fatal(1, "Missing split request or response progress");
        end
    end
    initial begin
        repeat (4) @(posedge clk);
        @(negedge clk); reset = 0;
    end
endmodule
