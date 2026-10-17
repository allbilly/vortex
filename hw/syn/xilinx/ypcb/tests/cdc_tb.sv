// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module cdc_tb;
    parameter BUS_HALF = 5;
    parameter MEMORY_HALF = 7;
    parameter PHASE = 3;
    parameter RESET_MEMORY = 0;
    localparam COUNT = 48;
    `include "ports.vh"
    ypcb_axi_cdc dut (.*);

    initial bus_clk = 0;
    always #BUS_HALF bus_clk = ~bus_clk;
    initial begin
        memory_clk = 0;
        #PHASE;
        forever #MEMORY_HALF memory_clk = ~memory_clk;
    end

    function automatic integer length(input integer index);
        length = index % 3 == 0 ? 63 : index % 3 == 1 ? 3 : 0;
    endfunction
    function automatic [7:0] identifier(input integer index);
        identifier = 8'h40 + 8'(index);
    endfunction
    function automatic [30:0] address(input integer index);
        address = 31'h10000 + 31'(index * 4096);
    endfunction
    function automatic [31:0] pattern(input integer index, beat, word_idx);
        pattern = 32'(index) * 32'h1010101 ^ 32'(beat) * 32'h10203 ^ 32'(word_idx) * 32'habcdef;
    endfunction
    function automatic [63:0] mask(input integer index, beat);
        mask = 64'h1234567887654321 ^ (64'(index) << 32) ^ 64'(beat);
    endfunction
    function automatic [1:0] response(input integer index);
        response = index % 11 == 0 ? 2'b10 : 2'b00;
    endfunction

    reg running = 0;
    reg writing = 0, reading = 0, b_pending = 0;
    integer aw_seen = 0, w_seen = 0, w_beat = 0, ar_seen = 0, r_beat = 0;
    integer b_received = 0, r_received = 0, r_received_beat = 0;
    integer bus_cycles = 0, memory_cycles = 0;
    assign m_axi_awready = running && !writing && !b_pending && memory_cycles % 3 != 0;
    assign m_axi_wready = running && writing && memory_cycles % 7 > 1;
    assign m_axi_bvalid = running && b_pending;
    assign m_axi_bid = identifier(w_seen);
    assign m_axi_bresp = response(w_seen);
    assign m_axi_buser = 1;
    assign m_axi_arready = running && !reading && memory_cycles % 5 != 0;
    assign m_axi_rvalid = running && reading;
    assign m_axi_rid = identifier(ar_seen);
    assign m_axi_rlast = r_beat == length(ar_seen);
    assign m_axi_rresp = response(ar_seen);
    assign m_axi_ruser = 1;
    for (genvar word_idx = 0; word_idx < 16; ++word_idx) begin : g_read_data
        assign m_axi_rdata[word_idx * 32 +: 32] = pattern(ar_seen, r_beat, word_idx) ^ 32'h5a5a5a5a;
    end
    assign s_axi_bready = running && bus_cycles % 7 > 1;
    assign s_axi_rready = running && bus_cycles % 5 > 1;

    always @(posedge memory_clk) begin
        memory_cycles <= memory_cycles + 1;
        if (running) begin
            if (m_axi_awvalid && m_axi_awready) begin
                if (m_axi_awaddr != address(aw_seen) || m_axi_awid != identifier(aw_seen)
                        || m_axi_awlen != length(aw_seen)) $fatal(1, "AW payload/order differs");
                if (m_axi_awsize != 6 || m_axi_awburst != 1 || m_axi_awprot != 3
                        || m_axi_awcache != 10 || m_axi_awqos != 5 || m_axi_awregion != 9
                        || m_axi_awuser != 1 || m_axi_awlock != 0) $fatal(1, "AW attributes differ");
                writing <= 1;
                aw_seen <= aw_seen + 1;
            end
            if (m_axi_wvalid && m_axi_wready) begin
                if (m_axi_wlast != (w_beat == length(w_seen)) || m_axi_wstrb != mask(w_seen, w_beat)
                        || m_axi_wuser != 1) $fatal(1, "W mask/last differs");
                for (integer word_idx = 0; word_idx < 16; ++word_idx) begin
                    if (m_axi_wdata[word_idx * 32 +: 32] != pattern(w_seen, w_beat, word_idx))
                        $fatal(1, "W data differs");
                end
                if (m_axi_wlast) begin
                    writing <= 0;
                    b_pending <= 1;
                    w_beat <= 0;
                end else w_beat <= w_beat + 1;
            end
            if (m_axi_bvalid && m_axi_bready) begin
                b_pending <= 0;
                w_seen <= w_seen + 1;
            end
            if (m_axi_arvalid && m_axi_arready) begin
                if (m_axi_araddr != address(ar_seen) || m_axi_arid != identifier(ar_seen)
                        || m_axi_arlen != length(ar_seen)) $fatal(1, "AR payload/order differs");
                if (m_axi_arsize != 6 || m_axi_arburst != 1 || m_axi_arprot != 3
                        || m_axi_arcache != 10 || m_axi_arqos != 5 || m_axi_arregion != 9
                        || m_axi_aruser != 1 || m_axi_arlock != 0) $fatal(1, "AR attributes differ");
                reading <= 1;
                r_beat <= 0;
            end
            if (m_axi_rvalid && m_axi_rready) begin
                if (m_axi_rlast) begin
                    reading <= 0;
                    ar_seen <= ar_seen + 1;
                    r_beat <= 0;
                end else r_beat <= r_beat + 1;
            end
        end
    end
    always @(posedge bus_clk) begin
        bus_cycles <= bus_cycles + 1;
        if (running && s_axi_bvalid && s_axi_bready) begin
            if (s_axi_bid != identifier(b_received) || s_axi_bresp != response(b_received)
                    || s_axi_buser != 1) $fatal(1, "B response/ID differs");
            b_received <= b_received + 1;
        end
        if (running && s_axi_rvalid && s_axi_rready) begin
            if (s_axi_rid != identifier(r_received) || s_axi_rresp != response(r_received)
                    || s_axi_rlast != (r_received_beat == length(r_received)) || s_axi_ruser != 1)
                $fatal(1, "R response/ID/last differs");
            for (integer word_idx = 0; word_idx < 16; ++word_idx) begin
                if (s_axi_rdata[word_idx * 32 +: 32]
                        != (pattern(r_received, r_received_beat, word_idx) ^ 32'h5a5a5a5a))
                    $fatal(1, "R data differs");
            end
            if (s_axi_rlast) begin
                r_received <= r_received + 1;
                r_received_beat <= 0;
            end else r_received_beat <= r_received_beat + 1;
        end
    end

    initial begin
        bus_reset = 1;
        memory_reset = 1;
        s_axi_awvalid = 0; s_axi_arvalid = 0; s_axi_wvalid = 0;
        s_axi_awaddr = 0; s_axi_awid = 0; s_axi_awlen = 0;
        s_axi_araddr = 0; s_axi_arid = 0; s_axi_arlen = 0;
        s_axi_wdata = 0; s_axi_wstrb = 0; s_axi_wlast = 0;
        s_axi_awburst = 1; s_axi_arburst = 1;
        s_axi_awsize = 6; s_axi_arsize = 6;
        s_axi_awlock = 0; s_axi_arlock = 0;
        s_axi_awprot = 3; s_axi_arprot = 3;
        s_axi_awcache = 10; s_axi_arcache = 10;
        s_axi_awqos = 5; s_axi_arqos = 5;
        s_axi_awregion = 9; s_axi_arregion = 9;
        s_axi_awuser = 1; s_axi_aruser = 1; s_axi_wuser = 1;
        repeat (10) @(negedge bus_clk);
        bus_reset = 0; memory_reset = 0;
        repeat (10) @(negedge bus_clk);
        s_axi_awvalid = 1; s_axi_arvalid = 1;
        s_axi_awaddr = 31'h70000; s_axi_araddr = 31'h70000;
        s_axi_awid = 8'hee; s_axi_arid = 8'hee;
        repeat (10) @(negedge bus_clk);
        s_axi_awvalid = 0; s_axi_arvalid = 0;
        if (RESET_MEMORY) memory_reset = 1;
        else bus_reset = 1;
        repeat (10) @(negedge bus_clk);
        bus_reset = 0; memory_reset = 0;
        repeat (10) @(negedge bus_clk);
        if (m_axi_awvalid || m_axi_arvalid) $fatal(1, "Queued requests survived reset");
        running = 1;
        fork
            begin
                for (integer index = 0; index < COUNT; ++index) begin
                    @(negedge bus_clk);
                    s_axi_awvalid = 1; s_axi_awaddr = address(index);
                    s_axi_awid = identifier(index); s_axi_awlen = 8'(length(index));
                    do @(posedge bus_clk); while (!s_axi_awready);
                end
                @(negedge bus_clk); s_axi_awvalid = 0;
            end
            begin
                for (integer index = 0; index < COUNT; ++index) begin
                    for (integer beat_idx = 0; beat_idx <= length(index); ++beat_idx) begin
                        @(negedge bus_clk);
                        s_axi_wvalid = 1; s_axi_wlast = beat_idx == length(index);
                        s_axi_wstrb = mask(index, beat_idx);
                        for (integer word_idx = 0; word_idx < 16; ++word_idx)
                            s_axi_wdata[word_idx * 32 +: 32] = pattern(index, beat_idx, word_idx);
                        do @(posedge bus_clk); while (!s_axi_wready);
                    end
                end
                @(negedge bus_clk); s_axi_wvalid = 0;
            end
            begin
                for (integer index = 0; index < COUNT; ++index) begin
                    @(negedge bus_clk);
                    s_axi_arvalid = 1; s_axi_araddr = address(index);
                    s_axi_arid = identifier(index); s_axi_arlen = 8'(length(index));
                    do @(posedge bus_clk); while (!s_axi_arready);
                end
                @(negedge bus_clk); s_axi_arvalid = 0;
            end
            begin
                wait (b_received == COUNT && r_received == COUNT);
                repeat (10) @(negedge bus_clk);
                if (aw_seen != COUNT || w_seen != COUNT || ar_seen != COUNT)
                    $fatal(1, "Missing transaction");
                $display("PASSED: CDC, 48 writes, 48 reads, clocks %0d/%0d, phase %0d, reset %0d, bursts, IDs, masks, attributes and backpressure",
                         BUS_HALF * 2, MEMORY_HALF * 2, PHASE, RESET_MEMORY);
                $finish;
            end
        join
    end
    initial begin
        #2000000;
        $fatal(1, "CDC timed out");
    end
endmodule
