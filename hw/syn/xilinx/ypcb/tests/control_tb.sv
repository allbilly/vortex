// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module control_tb #(parameter SWEEP_END = 65536);
    reg clk = 0;
    always #5 clk = ~clk;
    reg reset = 1;
    reg s_awvalid = 0, s_wvalid = 0, s_arvalid = 0;
    wire s_awready, s_wready, s_arready;
    reg [15:0] s_awaddr = 0, s_araddr = 0;
    reg [31:0] s_wdata = 0;
    reg [3:0] s_wstrb = 0;
    wire s_bvalid, s_rvalid;
    reg s_bready = 0, s_rready = 0;
    wire [1:0] s_bresp, s_rresp;
    wire [31:0] s_rdata;
    wire [4:0] m_awvalid, m_wvalid, m_arvalid, m_bready, m_rready;
    wire [4:0] m_awready, m_wready, m_arready;
    wire [4:0][15:0] m_awaddr, m_araddr;
    wire [4:0][31:0] m_wdata;
    wire [4:0][3:0] m_wstrb;
    reg [4:0] m_bvalid = 0, m_rvalid = 0;
    reg [4:0][1:0] m_bresp = 0, m_rresp = 0;
    reg [4:0][31:0] m_rdata = 0;
    reg [4:0] aw_pending = 0, w_pending = 0;
    reg [4:0][15:0] held_address = 0;
    wire [4:0] write_transfers = m_bvalid & m_bready;
    wire [4:0] read_transfers = m_arvalid & m_arready;
    integer cycles = 0, writes = 0, reads = 0, pairs = 0;
    integer expected_wa = 0, expected_ra = 0, expected_sequence = 0;
    VX_ypcb_control dut (.*);

    function automatic integer route(input integer address);
        if (address >= 16'h8000 || address % 4 != 0) begin
            route = -1;
        end else if (address < 16'h2000) begin
            route = 0;
        end else if (address < 16'h3000) begin
            route = 1;
        end else if (address < 16'h4000) begin
            route = 2;
        end else begin
            route = address < 16'h6000 ? 3 : 4;
        end
    endfunction
    function automatic [15:0] offset(input integer address);
        case (route(address))
            0: offset = 16'(address);
            1: offset = 16'(address - 16'h2000);
            2: offset = 16'(address - 16'h3000);
            3: offset = 16'(address - 16'h4000);
            4: offset = 16'(address - 16'h6000);
            default: offset = 0;
        endcase
    endfunction
    function automatic [31:0] pattern(input integer address);
        pattern = 32'h9a000000 ^ (32'(route(address)) << 20) ^ (32'(offset(address)) * 32'h10203);
    endfunction
    function automatic [1:0] response(input integer address);
        response = 2'(address / 4);
    endfunction
    function automatic [31:0] value(input integer sequence_id);
        value = 32'h87654321 ^ (32'(sequence_id) * 32'h1020304);
    endfunction

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (!reset) begin
            writes <= writes + $countones(write_transfers);
            reads <= reads + $countones(read_transfers);
        end
    end
    for (genvar index = 0; index < 5; ++index) begin : g_targets
        assign m_awready[index] = !aw_pending[index] && !m_bvalid[index] && cycles % 7 == index;
        assign m_wready[index] = !w_pending[index] && !m_bvalid[index] && cycles % 9 == index + 3;
        assign m_arready[index] = !m_rvalid[index] && cycles % 5 == index;
        always @(posedge clk) begin
            if (reset) begin
                aw_pending[index] <= 0;
                w_pending[index] <= 0;
                m_bvalid[index] <= 0;
                m_rvalid[index] <= 0;
            end else begin
                if (m_awvalid[index] && m_awready[index]) begin
                    if (route(expected_wa) != index || m_awaddr[index] != offset(expected_wa)) begin
                        $fatal(1, "Mapped write address/target differs");
                    end
                    held_address[index] <= m_awaddr[index];
                    aw_pending[index] <= 1;
                end
                if (m_wvalid[index] && m_wready[index]) begin
                    if (route(expected_wa) != index || m_wdata[index] != value(expected_sequence)
                            || m_wstrb[index] != 4'(expected_sequence)) begin
                        $fatal(1, "Mapped write data/strobe/target differs");
                    end
                    w_pending[index] <= 1;
                end
                if (aw_pending[index] && w_pending[index] && !m_bvalid[index]) begin
                    m_bvalid[index] <= 1;
                    m_bresp[index] <= response(int'(held_address[index]));
                end
                if (m_bvalid[index] && m_bready[index]) begin
                    m_bvalid[index] <= 0;
                    aw_pending[index] <= 0;
                    w_pending[index] <= 0;
                end
                if (m_arvalid[index] && m_arready[index]) begin
                    if (route(expected_ra) != index || m_araddr[index] != offset(expected_ra)) begin
                        $fatal(1, "Mapped read address/target differs");
                    end
                    m_rvalid[index] <= 1;
                    m_rdata[index] <= pattern(expected_ra);
                    m_rresp[index] <= response(expected_ra);
                end
                if (m_rvalid[index] && m_rready[index]) begin
                    m_rvalid[index] <= 0;
                end
            end
        end
    end

    task automatic exchange(input integer wa, ra, sequence_id);
        integer before_writes, before_reads, start_cycle;
        begin
            expected_wa = wa;
            expected_ra = ra;
            expected_sequence = sequence_id;
            before_writes = writes;
            before_reads = reads;
            start_cycle = cycles;
            fork
                begin
                    repeat (sequence_id % 3 * 4) begin
                        @(negedge clk);
                    end
                    @(negedge clk);
                    s_awvalid = 1;
                    s_awaddr = 16'(wa);
                    do begin
                        @(posedge clk);
                        if (cycles - start_cycle > 200) begin
                            $fatal(1, "Write address handshake timed out");
                        end
                    end while (!s_awready);
                    @(negedge clk);
                    s_awvalid = 0;
                    s_awaddr = 16'hffff;
                end
                begin
                    repeat ((2 - sequence_id % 3) * 4) begin
                        @(negedge clk);
                    end
                    @(negedge clk);
                    s_wvalid = 1;
                    s_wdata = value(sequence_id);
                    s_wstrb = 4'(sequence_id);
                    do begin
                        @(posedge clk);
                        if (cycles - start_cycle > 200) begin
                            $fatal(1, "Write data handshake timed out");
                        end
                    end while (!s_wready);
                    @(negedge clk);
                    s_wvalid = 0;
                    s_wdata = ~value(sequence_id);
                    s_wstrb = ~4'(sequence_id);
                end
                begin
                    @(negedge clk);
                    s_arvalid = 1;
                    s_araddr = 16'(ra);
                    do begin
                        @(posedge clk);
                        if (cycles - start_cycle > 200) begin
                            $fatal(1, "Read address handshake timed out");
                        end
                    end while (!s_arready);
                    @(negedge clk);
                    s_arvalid = 0;
                    s_araddr = 16'hffff;
                end
                begin
                    repeat (40) begin
                        @(negedge clk);
                    end
                    s_bready = 1;
                    do begin
                        @(posedge clk);
                        if (cycles - start_cycle > 200) begin
                            $fatal(1, "Write response timed out at wa=%h", wa);
                        end
                    end while (!s_bvalid);
                    if (s_bresp != (route(wa) < 0 ? 2'b11 : response(wa))) begin
                        $fatal(1, "Mapped write response differs");
                    end
                    @(negedge clk);
                    s_bready = 0;
                end
                begin
                    repeat (45) begin
                        @(negedge clk);
                    end
                    s_rready = 1;
                    do begin
                        @(posedge clk);
                        if (cycles - start_cycle > 200) begin
                            $fatal(1, "Read response timed out at ra=%h", ra);
                        end
                    end while (!s_rvalid);
                    if (s_rresp != (route(ra) < 0 ? 2'b11 : response(ra))
                            || s_rdata != (route(ra) < 0 ? 32'b0 : pattern(ra))) begin
                        $fatal(1, "Mapped read response/data differs");
                    end
                    @(negedge clk);
                    s_rready = 0;
                end
            join
            if (writes - before_writes != int'(route(wa) >= 0)
                    || reads - before_reads != int'(route(ra) >= 0)) begin
                $fatal(1, "Transaction count differs: wa=%h ra=%h writes=%0d expected=%0d reads=%0d expected=%0d",
                    wa, ra, writes - before_writes, int'(route(wa) >= 0),
                    reads - before_reads, int'(route(ra) >= 0));
            end
            pairs = pairs + 1;
            if (pairs % 1024 == 0) begin
                $display("Control progress: %0d pairs at cycle %0d", pairs, cycles);
            end
        end
    endtask

    initial begin
        repeat (5) begin
            @(negedge clk);
        end
        reset = 0;
        for (integer address = 0; address < SWEEP_END; address += 4) begin
            exchange(address, (address * 13 + 16'h18d0) & 65535, address / 4);
        end
        for (integer address = 1; address < SWEEP_END; address += 17) begin
            exchange(address, (address * 7 + 2) & 65535, address);
        end
        $display("PASSED: control router, %0d concurrent pairs, %0d writes, %0d reads, DWORD/windows/strobes/responses, independent channels and stalls",
            pairs, writes, reads);
        $finish;
    end
    initial begin
        #20000000;
        $fatal(1, "Mapped control timed out");
    end
endmodule
