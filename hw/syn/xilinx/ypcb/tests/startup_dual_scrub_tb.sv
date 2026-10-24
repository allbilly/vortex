// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps

module startup_dual_scrub_tb;
    localparam logic [63:0] SCRUB_BASE = 64'h0000000080000f00;
    localparam logic [63:0] SCRUB_END = 64'h0000000080001180;

    reg clk;
    initial clk = 1'b0;
    always #5 clk = ~clk;

    reg reset = 1'b1;
    reg start = 1'b0;
    reg [1:0] init_ready = 2'b00;
    wire busy, done, error;
    wire m_awvalid;
    reg m_awready = 1'b0;
    wire [63:0] m_awaddr;
    wire [7:0] m_awlen;
    wire m_wvalid;
    reg m_wready = 1'b0;
    wire [511:0] m_wdata;
    wire [63:0] m_wstrb;
    wire m_wlast;
    reg m_bvalid = 1'b0;
    wire m_bready;
    reg [1:0] m_bresp = 2'b00;

    VX_ypcb_scrub #(
        .BASE_ADDR (SCRUB_BASE),
        .END_ADDR (SCRUB_END),
        .ADDRESS_LIMIT (64'h0000000100000000)
    ) dut (
        .clk (clk), .reset (reset), .start (start), .init_ready (init_ready),
        .busy (busy), .done (done), .error (error),
        .m_awvalid (m_awvalid), .m_awready (m_awready), .m_awaddr (m_awaddr), .m_awlen (m_awlen),
        .m_wvalid (m_wvalid), .m_wready (m_wready), .m_wdata (m_wdata),
        .m_wstrb (m_wstrb), .m_wlast (m_wlast),
        .m_bvalid (m_bvalid), .m_bready (m_bready), .m_bresp (m_bresp)
    );

    integer aw_count = 0;
    integer beat_count = 0;
    integer response_count = 0;

    task automatic require(input bit condition, input string message);
        if (!condition) $fatal(1, "%s", message);
    endtask

    task automatic reset_scrubber;
        begin
            @(negedge clk);
            reset = 1'b1;
            start = 1'b0;
            init_ready = 2'b00;
            m_awready = 1'b0;
            m_wready = 1'b0;
            m_bvalid = 1'b0;
            m_bresp = 2'b00;
            repeat (3) begin
                @(posedge clk); #1;
                require(!busy && !done && !error && !m_awvalid && !m_wvalid && !m_bready,
                        "Reset did not cancel scrub state");
            end
            @(negedge clk);
            reset = 1'b0;
            #1;
        end
    endtask

    task automatic start_scrub;
        integer wait_cycles;
        begin
            @(negedge clk);
            start = 1'b1;
            init_ready = 2'b01;
            repeat (4) begin
                @(posedge clk); #1;
                require(busy && !m_awvalid && !done && !error,
                        "Scrub started without CH1 initialization readiness");
            end
            @(negedge clk);
            init_ready = 2'b11;
            wait_cycles = 0;
            while (!m_awvalid && wait_cycles < 20) begin
                @(posedge clk); #1;
                wait_cycles = wait_cycles + 1;
            end
            require(m_awvalid && busy, "Scrub did not start after both channels became ready");
        end
    endtask

    task automatic accept_aw(input [63:0] expected_address, input [7:0] expected_len);
        begin
            require(m_awvalid && m_awaddr == expected_address && m_awlen == expected_len,
                    "Upper-channel address or page-bounded burst length differs");
            require(m_awaddr >= 64'h0000000080000000 && m_awaddr < 64'h0000000100000000,
                    "Scrub escaped the upper CH1 address window");
            require((64'(m_awaddr[11:0]) + (64'(m_awlen) + 64'd1) * 64'd64) <= 64'd4096,
                    "Scrub burst crossed a 4 KiB boundary");
            repeat (3) begin
                @(posedge clk); #1;
                require(m_awvalid && m_awaddr == expected_address && m_awlen == expected_len,
                        "AW changed while downstream DDR was backpressured");
            end
            @(negedge clk);
            m_awready = 1'b1;
            #1;
            require(m_awvalid, "AW valid dropped before handshake");
            @(posedge clk); #1;
            aw_count = aw_count + 1;
            @(negedge clk);
            m_awready = 1'b0;
        end
    endtask

    task automatic accept_w_beat(input integer beat, input integer last_beat);
        begin
            m_wready = 1'b0;
            #1;
            require(m_wvalid && m_wdata == 512'b0 && m_wstrb == 64'hffffffffffffffff
                    && m_wlast == (beat == last_beat), "Scrub W data, mask or last differs");
            repeat (2) begin
                @(posedge clk); #1;
                require(m_wvalid && m_wdata == 512'b0 && m_wstrb == 64'hffffffffffffffff
                        && m_wlast == (beat == last_beat), "W signals changed while backpressured");
            end
            @(negedge clk);
            m_wready = 1'b1;
            #1;
            require(m_wvalid, "W valid dropped before handshake");
            @(posedge clk); #1;
            beat_count = beat_count + 1;
            @(negedge clk);
            m_wready = 1'b0;
        end
    endtask

    task automatic accept_b(input [1:0] response);
        integer wait_cycles;
        begin
            m_bresp = response;
            m_bvalid = 1'b0;
            wait_cycles = 0;
            while (!m_bready && wait_cycles < 10) begin
                @(posedge clk); #1;
                wait_cycles = wait_cycles + 1;
            end
            require(m_bready, "Scrub did not wait for BRESP after WLAST");
            repeat (5) begin
                @(posedge clk); #1;
                require(m_bready && !done && !error, "Scrub did not tolerate delayed BRESP");
            end
            @(negedge clk);
            m_bvalid = 1'b1;
            #1;
            require(m_bready, "Scrub BRESP handshake was not ready");
            @(posedge clk); #1;
            response_count = response_count + 1;
            @(negedge clk);
            m_bvalid = 1'b0;
        end
    endtask

    task automatic run_success;
        begin
            start_scrub();
            accept_aw(SCRUB_BASE, 8'd3);
            for (integer beat = 0; beat < 4; ++beat) accept_w_beat(beat, 3);
            accept_b(2'b00);
            accept_aw(64'h0000000080001000, 8'd5);
            for (integer beat = 0; beat < 6; ++beat) accept_w_beat(beat, 5);
            accept_b(2'b00);
            repeat (2) begin
                @(posedge clk); #1;
                require(done && !busy && !error && !m_awvalid && !m_wvalid,
                        "Successful scrub did not stop cleanly at the upper range end");
            end
            require(aw_count == 2 && beat_count == 10 && response_count == 2,
                    "Upper CH1 scrub did not cover its bounded two-burst interval");
            repeat (4) begin
                @(posedge clk); #1;
                require(done && !busy && !error && !m_awvalid && !m_wvalid,
                        "Held start restarted a completed scrub");
            end
        end
    endtask

    initial begin
        reset_scrubber();
        run_success();

        reset_scrubber();
        aw_count = 0; beat_count = 0; response_count = 0;
        start_scrub();
        accept_aw(SCRUB_BASE, 8'd3);
        for (integer beat = 0; beat < 4; ++beat) accept_w_beat(beat, 3);
        accept_b(2'b10);
        repeat (3) begin
            @(posedge clk); #1;
            require(error && !done && !busy && !m_awvalid && !m_wvalid,
                    "BRESP error did not stop the upper-channel scrub");
        end
        require(aw_count == 1 && beat_count == 4 && response_count == 1,
                "Scrub issued further traffic after BRESP error");

        reset_scrubber();
        aw_count = 0; beat_count = 0; response_count = 0;
        start_scrub();
        accept_aw(SCRUB_BASE, 8'd3);
        accept_w_beat(0, 3);
        @(negedge clk);
        reset = 1'b1;
        start = 1'b0;
        init_ready = 2'b00;
        repeat (3) begin
            @(posedge clk); #1;
            require(!busy && !done && !error && !m_awvalid && !m_wvalid && !m_bready,
                    "Reset did not cancel a partially written CH1 scrub burst");
        end
        @(negedge clk);
        reset = 1'b0;
        #1;
        aw_count = 0; beat_count = 0; response_count = 0;
        run_success();

        $display("PASS: bounded upper-CH1 scrub sequence, 4 KiB split, backpressure, BRESP error and reset/restart");
        $finish;
    end

    initial begin
        #200000;
        $fatal(1, "Timed out in bounded upper-CH1 scrub test");
    end
endmodule
