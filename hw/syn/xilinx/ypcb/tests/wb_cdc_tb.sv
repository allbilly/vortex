// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module wb_cdc_tb;
    parameter BUS_HALF = 5;
    parameter MEMORY_HALF = 7;
    parameter PHASE = 3;
    parameter RESET_MEMORY = 0;
    localparam COUNT = 64;
    localparam ABORT = 7;
    `include "wb_ports.vh"
    ypcb_wb_cdc dut (.*);

    initial bus_clk = 0;
    always #BUS_HALF bus_clk = ~bus_clk;
    initial begin
        memory_clk = 0;
        #PHASE;
        forever begin
            #MEMORY_HALF memory_clk = ~memory_clk;
        end
    end

    function automatic [29:0] address(input integer index);
        address = 30'h3c000000 ^ (30'(index) * 30'h1431);
    endfunction
    function automatic [31:0] pattern(input integer index);
        pattern = 32'h87654321 ^ (32'(index) * 32'h1234567);
    endfunction
    function automatic [31:0] result(input integer index);
        result = pattern(index) ^ 32'h5a5a5a5a;
    endfunction
    function automatic has_error(input integer index);
        has_error = index % 11 == 0;
    endfunction

    reg running = 0, active = 0;
    integer received = 0, terminated = 0, acknowledged = 0;
    integer memory_cycles = 0, response_due = 0;
    reg [29:0] held_address;
    reg [31:0] held_data;
    reg [3:0] held_select;
    reg held_write;
    wire terminate = running && active && memory_cycles >= response_due;
    assign m_wb_ack = terminate && !(has_error(terminated) && terminated % 2 == 0);
    assign m_wb_err = terminate && has_error(terminated);
    assign m_wb_dat_r = result(terminated);

    always @(posedge memory_clk) begin
        memory_cycles <= memory_cycles + 1;
        if (running) begin
            if (m_wb_cyc) begin
                if (!m_wb_stb || m_wb_cti != 0 || m_wb_bte != 0) begin
                    $fatal(1, "Wishbone classic cycle/attributes differ");
                end
                if (!active) begin
                    if (m_wb_adr != address(received) || m_wb_dat_w != pattern(received)
                            || m_wb_sel != 4'(received) || m_wb_we != (received % 2 == 0)) begin
                        $fatal(1, "Request payload/order differs at index %0d", received);
                    end
                    held_address <= m_wb_adr;
                    held_data <= m_wb_dat_w;
                    held_select <= m_wb_sel;
                    held_write <= m_wb_we;
                    active <= 1;
                    response_due <= memory_cycles + 20 + received % 7;
                    received <= received + 1;
                end else if (m_wb_adr != held_address || m_wb_dat_w != held_data
                        || m_wb_sel != held_select || m_wb_we != held_write) begin
                    $fatal(1, "Wishbone payload changed before termination");
                end
                if (m_wb_ack || m_wb_err) begin
                    active <= 0;
                    terminated <= terminated + 1;
                end
            end else if (active) begin
                $fatal(1, "Wishbone cycle dropped before termination");
            end
        end
    end

    task automatic request(input integer index);
        @(negedge bus_clk);
        s_wb_cyc = 1;
        s_wb_stb = 1;
        s_wb_we = index % 2 == 0;
        s_wb_adr = address(index);
        s_wb_dat_w = pattern(index);
        s_wb_sel = 4'(index);
        if (index == ABORT) begin
            wait (active && received == index + 1);
            @(negedge bus_clk);
            s_wb_cyc = 0;
            s_wb_stb = 0;
            repeat (4) begin
                @(negedge bus_clk);
                if (s_wb_ack || s_wb_err) begin
                    $fatal(1, "Aborted request was acknowledged");
                end
            end
        end else begin
            do begin
                @(posedge bus_clk);
            end while (!s_wb_ack && !s_wb_err);
            if (s_wb_err != has_error(index) || s_wb_ack == has_error(index)
                    || s_wb_dat_r != result(index)) begin
                $fatal(1, "Response payload/order differs at index %0d", index);
            end
            acknowledged = acknowledged + 1;
            @(negedge bus_clk);
            s_wb_cyc = 0;
            s_wb_stb = 0;
        end
    endtask

    initial begin
        bus_reset = 1;
        memory_reset = 1;
        s_wb_cyc = 0;
        s_wb_stb = 0;
        s_wb_we = 0;
        s_wb_adr = 0;
        s_wb_dat_w = 0;
        s_wb_sel = 0;
        s_wb_cti = 0;
        s_wb_bte = 0;
        repeat (10) begin
            @(negedge bus_clk);
        end
        bus_reset = 0;
        memory_reset = 0;
        repeat (10) begin
            @(negedge bus_clk);
        end
        s_wb_cyc = 1;
        s_wb_stb = 1;
        s_wb_adr = 30'h12345678;
        s_wb_dat_w = 32'hdeadbeef;
        s_wb_sel = 15;
        wait (m_wb_cyc);
        @(negedge bus_clk);
        s_wb_cyc = 0;
        s_wb_stb = 0;
        if (RESET_MEMORY) begin
            memory_reset = 1;
        end else begin
            bus_reset = 1;
        end
        repeat (10) begin
            @(negedge bus_clk);
        end
        bus_reset = 0;
        memory_reset = 0;
        repeat (10) begin
            @(negedge bus_clk);
        end
        if (m_wb_cyc || m_wb_stb || s_wb_ack || s_wb_err) begin
            $fatal(1, "Active request/response survived common reset");
        end
        running = 1;
        for (integer index = 0; index < COUNT; ++index) begin
            request(index);
        end
        repeat (20) begin
            @(negedge bus_clk);
        end
        if (received != COUNT || terminated != COUNT || acknowledged != COUNT - 1) begin
            $fatal(1, "Wishbone request/response count differs");
        end
        $display("PASSED: Wishbone CDC, %0d requests, %0d responses, 30-bit word addresses, masks, stalls, abort drain, clocks %0d/%0d, reset %0d",
            received, acknowledged, BUS_HALF * 2, MEMORY_HALF * 2, RESET_MEMORY);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "Wishbone CDC timed out");
    end
endmodule
