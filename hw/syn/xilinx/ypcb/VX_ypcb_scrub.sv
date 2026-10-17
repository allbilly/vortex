// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module VX_ypcb_scrub #(
    parameter logic [63:0] BASE_ADDR = 64'd0,
    parameter logic [63:0] END_ADDR = 64'h100000000
) (
    input wire clk,
    input wire reset,
    input wire start,
    input wire [1:0] init_ready,
    output wire busy,
    output wire done,
    output wire error,
    output wire m_awvalid,
    input wire m_awready,
    output wire [63:0] m_awaddr,
    output wire [7:0] m_awlen,
    output wire m_wvalid,
    input wire m_wready,
    output wire [511:0] m_wdata,
    output wire [63:0] m_wstrb,
    output wire m_wlast,
    input wire m_bvalid,
    output wire m_bready,
    input wire [1:0] m_bresp
);
    typedef enum logic [2:0] {IDLE, WAIT_READY, ADDR, DATA, RESPONSE, COMPLETE, FAILED} state_t;
    state_t state;
    reg [63:0] address;
    reg [5:0] beat;
    wire [63:0] remaining_beats = (END_ADDR - address) >> 6;
    wire [6:0] burst_beats = remaining_beats < 64 ? 7'(remaining_beats) : 7'd64;
    wire [6:0] page_beats = 7'd64 - {1'b0, address[11:6]};
    wire [6:0] chunk_beats = burst_beats < page_beats ? burst_beats : page_beats;

    assign busy = state != IDLE && state != COMPLETE && state != FAILED;
    assign done = state == COMPLETE;
    assign error = state == FAILED;
    assign m_awvalid = state == ADDR;
    assign m_awaddr = address;
    assign m_awlen = 8'(chunk_beats - 7'd1);
    assign m_wvalid = state == DATA;
    assign m_wdata = '0;
    assign m_wstrb = '1;
    assign m_wlast = {1'b0, beat} == chunk_beats - 7'd1;
    assign m_bready = state == RESPONSE;

    initial begin
        if (BASE_ADDR >= END_ADDR || END_ADDR > 64'h100000000
                || BASE_ADDR[5:0] != 0 || END_ADDR[5:0] != 0) begin
            $fatal(1, "Invalid ECC scrub address range");
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            address <= BASE_ADDR;
            beat <= '0;
        end else begin
            case (state)
                IDLE: begin
                    if (start) begin
                        state <= WAIT_READY;
                    end
                end
                WAIT_READY: begin
                    if (&init_ready) begin
                        state <= ADDR;
                    end
                end
                ADDR: begin
                    if (m_awvalid && m_awready) begin
                        beat <= '0;
                        state <= DATA;
                    end
                end
                DATA: begin
                    if (m_wvalid && m_wready) begin
                        if (m_wlast) begin
                            state <= RESPONSE;
                        end else begin
                            beat <= beat + 6'd1;
                        end
                    end
                end
                RESPONSE: begin
                    if (m_bvalid && m_bready) begin
                        if (m_bresp != 0) begin
                            state <= FAILED;
                        end else begin
                            address <= address + (64'(chunk_beats) << 6);
                            if (address + (64'(chunk_beats) << 6) == END_ADDR) begin
                                state <= COMPLETE;
                            end else begin
                                state <= ADDR;
                            end
                        end
                    end
                end
                default: begin end
            endcase
        end
    end
endmodule
