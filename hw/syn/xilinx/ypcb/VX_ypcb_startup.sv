// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
`include "VX_platform.vh"

module VX_ypcb_startup (
    input wire clk,
    input wire reset,
    input wire [1:0] pll_locked,
    input wire [1:0] init_done,
    input wire [1:0] init_error,
    input wire link_up,
    input wire [3:0] pcie_error_status,
    input wire scrub_busy,
    input wire scrub_done,
    input wire scrub_failed,
    output reg scrub_start,
    output reg [1:0] memory_ready,

    input wire s_awvalid,
    output reg s_awready,
    input wire [11:0] s_awaddr,
    input wire s_wvalid,
    output reg s_wready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    output reg s_bvalid,
    input wire s_bready,
    output reg [1:0] s_bresp,
    input wire s_arvalid,
    output reg s_arready,
    input wire [11:0] s_araddr,
    output reg s_rvalid,
    input wire s_rready,
    output reg [31:0] s_rdata,
    output reg [1:0] s_rresp
);
    typedef enum logic [2:0] {WAIT_INIT, START, ACTIVE, READY, FAILED} state_t;
    state_t state;
    reg aw_pending, w_pending, busy_seen;
    reg [11:0] write_address;
    reg [7:0] write_command;
    reg command_enabled;
    wire calibrated = pll_locked == 2'b10 && init_done == 2'b10 && init_error == 0;
    wire write_fire = aw_pending && w_pending && !s_bvalid;
    wire request_start = write_fire && write_address == 12'h010 && command_enabled
        && write_command == 8'd1 && state == WAIT_INIT && calibrated && !scrub_failed;
    wire [31:0] status = {13'b0, state, link_up, pcie_error_status, memory_ready,
        scrub_failed, scrub_done, scrub_busy, init_error, init_done, pll_locked};

    always @(posedge clk) begin
        if (reset) begin
            state <= WAIT_INIT;
            busy_seen <= 0;
            scrub_start <= 0;
            memory_ready <= 0;
        end else if (|init_error || scrub_failed || (state != WAIT_INIT && !calibrated)) begin
            state <= FAILED;
            scrub_start <= 0;
            memory_ready <= 0;
        end else begin
            case (state)
                WAIT_INIT: begin
                    if (request_start) begin
                        scrub_start <= 1;
                        state <= START;
                    end
                end
                START: begin
                    scrub_start <= 0;
                    busy_seen <= scrub_busy;
                    state <= ACTIVE;
                end
                ACTIVE: begin
                    if (scrub_busy) begin
                        busy_seen <= 1;
                    end
                    // A previous completion must not open memory before the new scrub starts.
                    if (busy_seen && scrub_done && !scrub_busy) begin
                        memory_ready <= 2'b10;
                        state <= READY;
                    end
                end
                READY: begin
                    memory_ready <= 2'b10;
                end
                FAILED: begin
                    memory_ready <= 0;
                end
                default: begin
                    state <= FAILED;
                    memory_ready <= 0;
                end
            endcase
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            aw_pending <= 0;
            w_pending <= 0;
            write_address <= 0;
            write_command <= 0;
            command_enabled <= 0;
            s_awready <= 1;
            s_wready <= 1;
            s_bvalid <= 0;
            s_bresp <= 0;
            s_arready <= 1;
            s_rvalid <= 0;
            s_rdata <= 0;
            s_rresp <= 0;
        end else begin
            if (s_awvalid && s_awready) begin
                aw_pending <= 1;
                write_address <= s_awaddr;
                s_awready <= 0;
            end
            if (s_wvalid && s_wready) begin
                w_pending <= 1;
                write_command <= s_wdata[7:0];
                command_enabled <= s_wstrb[0];
                s_wready <= 0;
            end
            if (s_bvalid && s_bready) begin
                s_bvalid <= 0;
                s_awready <= 1;
                s_wready <= 1;
            end
            if (write_fire) begin
                aw_pending <= 0;
                w_pending <= 0;
                s_bvalid <= 1;
                s_bresp <= 0;
                if (write_address[1:0] != 0) begin
                    s_bresp <= 2'b11;
                end else begin
                    case (write_address)
                        12'h010: begin
                            if (command_enabled && (write_command != 1
                                    || (state != WAIT_INIT && state != READY)
                                    || !calibrated || scrub_failed)) begin
                                s_bresp <= 2'b10;
                            end
                        end
                        12'h000, 12'h004, 12'h008: s_bresp <= 2'b10;
                        default: s_bresp <= 2'b11;
                    endcase
                end
            end
            if (s_rvalid && s_rready) begin
                s_rvalid <= 0;
                s_arready <= 1;
            end
            if (s_arvalid && s_arready) begin
                s_rvalid <= 1;
                s_arready <= 0;
                s_rdata <= 0;
                s_rresp <= 0;
                case (s_araddr)
                    12'h000: s_rdata <= 32'h56595043;
                    12'h004: s_rdata <= 32'd2;
                    12'h008: s_rdata <= status;
                    12'h010: s_rdata <= 0;
                    default: s_rresp <= 2'b11;
                endcase
            end
        end
    end

    `UNUSED_VAR ({s_wdata[31:8], s_wstrb[3:1]})
endmodule
