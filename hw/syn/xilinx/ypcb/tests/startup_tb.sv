// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module startup_tb;
    reg clk = 0;
    always #5 clk = ~clk;
    reg reset = 1;
    reg [1:0] pll_locked = 0, init_done = 0, init_error = 0;
    reg link_up = 1;
    reg [3:0] pcie_error_status = 4'h9;
    wire scrub_start, scrub_busy, scrub_failed, actual_done;
    reg stale_done = 0;
    wire scrub_done = actual_done | stale_done;
    wire [1:0] memory_ready;
    reg s_awvalid = 0, s_wvalid = 0, s_arvalid = 0;
    wire s_awready, s_wready, s_arready;
    reg [11:0] s_awaddr = 0, s_araddr = 0;
    reg [31:0] s_wdata = 0;
    reg [3:0] s_wstrb = 0;
    wire s_bvalid, s_rvalid;
    reg s_bready = 0, s_rready = 0;
    wire [1:0] s_bresp, s_rresp;
    wire [31:0] s_rdata;
    VX_ypcb_startup startup (.*);

    wire m_awvalid, m_wvalid, m_bready, m_wlast;
    wire [63:0] m_awaddr, m_wstrb;
    wire [7:0] m_awlen;
    wire [511:0] m_wdata;
    reg m_bvalid = 0;
    reg [1:0] m_bresp = 0;
    integer cycles = 0, beats = 0, bursts = 0, starts = 0, checks = 0;
    reg active = 0, pause_response = 0;
    wire m_awready = !active && !m_bvalid && cycles % 5 == 1;
    wire m_wready = active && cycles % 7 > 1;
    VX_ypcb_scrub #(.BASE_ADDR(64'd0), .END_ADDR(64'h180)) scrub (
        .clk(clk), .reset(reset), .start(scrub_start), .init_ready(init_done & pll_locked),
        .busy(scrub_busy), .done(actual_done), .error(scrub_failed),
        .m_awvalid(m_awvalid), .m_awready(m_awready), .m_awaddr(m_awaddr), .m_awlen(m_awlen),
        .m_wvalid(m_wvalid), .m_wready(m_wready), .m_wdata(m_wdata),
        .m_wstrb(m_wstrb), .m_wlast(m_wlast), .m_bvalid(m_bvalid && !pause_response),
        .m_bready(m_bready), .m_bresp(m_bresp)
    );

    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (reset) begin
            active <= 0;
            m_bvalid <= 0;
            beats <= 0;
            bursts <= 0;
            starts <= 0;
        end else begin
            if (scrub_start) begin
                starts <= starts + 1;
            end
            if (memory_ready && (!actual_done || scrub_failed)) begin
                $fatal(1, "Memory opened before complete successful scrub");
            end
            if (m_awvalid && m_awready) begin
                if (m_awaddr != 0 || m_awlen != 5 || active) begin
                    $fatal(1, "Startup scrub range/burst differs");
                end
                active <= 1;
            end
            if (m_wvalid && m_wready) begin
                if (!active || m_wdata != 0 || m_wstrb != '1 || m_wlast != (beats == 5)) begin
                    $fatal(1, "Startup scrub data/mask/last differs");
                end
                beats <= beats + 1;
                if (m_wlast) begin
                    active <= 0;
                    m_bvalid <= 1;
                end
            end
            if (m_bvalid && !pause_response && m_bready) begin
                m_bvalid <= 0;
                bursts <= bursts + 1;
            end
        end
    end

    task automatic write_register(input [11:0] address, input [31:0] data,
                                   input [3:0] mask, input [1:0] expected);
        begin
            fork
                begin
                    @(negedge clk);
                    s_awaddr = address;
                    s_awvalid = 1;
                    do begin
                        @(posedge clk);
                    end while (!s_awready);
                    @(negedge clk);
                    s_awvalid = 0;
                    s_awaddr = 12'hfff;
                end
                begin
                    repeat (3) begin
                        @(negedge clk);
                    end
                    s_wdata = data;
                    s_wstrb = mask;
                    s_wvalid = 1;
                    do begin
                        @(posedge clk);
                    end while (!s_wready);
                    @(negedge clk);
                    s_wvalid = 0;
                    s_wdata = ~data;
                    s_wstrb = ~mask;
                end
            join
            wait (s_bvalid);
            repeat (7) begin
                @(negedge clk);
                if (!s_bvalid || s_bresp != expected) begin
                    $fatal(1, "Startup write response/stall differs at %h", address);
                end
            end
            s_bready = 1;
            @(negedge clk);
            s_bready = 0;
            checks = checks + 1;
        end
    endtask

    task automatic read_register(input [11:0] address, input [31:0] data, mask,
                                  input [1:0] expected);
        begin
            @(negedge clk);
            s_arvalid = 1;
            s_araddr = address;
            do begin
                @(posedge clk);
            end while (!s_arready);
            @(negedge clk);
            s_arvalid = 0;
            s_araddr = 12'hfff;
            repeat (7) begin
                @(negedge clk);
                if (!s_rvalid || s_rresp != expected || (s_rdata & mask) != data) begin
                    $fatal(1, "Startup read response/data/stall differs at %h: %h", address, s_rdata);
                end
            end
            s_rready = 1;
            @(negedge clk);
            s_rready = 0;
            checks = checks + 1;
        end
    endtask

    task automatic board_reset;
        begin
            @(negedge clk);
            reset = 1;
            init_error = 0;
            stale_done = 0;
            pause_response = 0;
            repeat (5) begin
                @(negedge clk);
            end
            reset = 0;
        end
    endtask

    initial begin
        board_reset();
        read_register(12'h000, 32'h56595043, '1, 0);
        read_register(12'h004, 32'd2, '1, 0);
        read_register(12'h003, 0, '1, 3);
        read_register(12'h100, 0, '1, 3);
        write_register(12'h000, 0, 15, 2);
        write_register(12'h100, 0, 15, 3);
        write_register(12'h011, 1, 15, 3);
        for (integer mask = 0; mask < 16; ++mask) begin
            write_register(12'h010, 1, 4'(mask), mask % 2 == 0 ? 2'b00 : 2'b10);
        end
        if (starts || memory_ready) begin
            $fatal(1, "Uncalibrated/disabled command started scrub");
        end
        pll_locked = 2;
        init_done = 1;
        write_register(12'h010, 1, 15, 2);
        init_done = 2;
        stale_done = 1;
        pause_response = 1;
        write_register(12'h010, 32'hffffff01, 1, 0);
        wait (m_bvalid);
        if (memory_ready || starts != 1 || actual_done) begin
            $fatal(1, "Stale completion/unfinished response opened memory");
        end
        write_register(12'h010, 1, 15, 2);
        stale_done = 0;
        pause_response = 0;
        wait (memory_ready == 2);
        read_register(12'h008, 32'h0000cc8a, 32'h0000ffff, 0);
        write_register(12'h010, 1, 15, 0);
        if (starts != 1 || bursts != 1 || beats != 6) begin
            $fatal(1, "Ready command repeated destructive scrub");
        end
        @(negedge clk);
        init_error = 1;
        repeat (2) begin
            @(negedge clk);
        end
        if (memory_ready) begin
            $fatal(1, "DDR error left memory ready");
        end
        init_error = 0;
        write_register(12'h010, 1, 15, 2);
        read_register(12'h008, 32'h00040000, 32'h00070000, 0);
        board_reset();
        m_bresp = 2;
        write_register(12'h010, 1, 15, 0);
        wait (scrub_failed);
        repeat (3) begin
            @(negedge clk);
        end
        if (memory_ready) begin
            $fatal(1, "Failed scrub opened memory");
        end
        write_register(12'h010, 1, 15, 2);
        board_reset();
        m_bresp = 0;
        write_register(12'h010, 1, 15, 0);
        wait (memory_ready == 2);
        @(negedge clk);
        pll_locked = 1;
        repeat (2) begin
            @(negedge clk);
        end
        if (memory_ready) begin
            $fatal(1, "PLL loss left memory ready");
        end
        pll_locked = 2;
        write_register(12'h010, 1, 15, 2);
        $display("PASSED: startup with actual scrub RTL, %0d register checks, calibration gating, stale completion, B-response ordering, idempotence, byte masks, errors, PLL loss and reset recovery", checks);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "Startup timed out");
    end
endmodule
