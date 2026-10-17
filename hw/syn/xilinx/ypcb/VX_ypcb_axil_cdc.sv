// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module VX_ypcb_axil_cdc (
    input wire src_clk,
    input wire clk,
    input wire reset,
    input wire src_reset,
    input wire s_awvalid,
    output wire s_awready,
    input wire [15:0] s_awaddr,
    input wire s_wvalid,
    output wire s_wready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    output reg s_bvalid,
    input wire s_bready,
    output reg [1:0] s_bresp,
    input wire s_arvalid,
    output wire s_arready,
    input wire [15:0] s_araddr,
    output reg s_rvalid,
    input wire s_rready,
    output reg [31:0] s_rdata,
    output reg [1:0] s_rresp,
    output reg m_awvalid,
    input wire m_awready,
    output reg [15:0] m_awaddr,
    output reg m_wvalid,
    input wire m_wready,
    output reg [31:0] m_wdata,
    output reg [3:0] m_wstrb,
    input wire m_bvalid,
    output wire m_bready,
    input wire [1:0] m_bresp,
    output reg m_arvalid,
    input wire m_arready,
    output reg [15:0] m_araddr,
    input wire m_rvalid,
    output wire m_rready,
    input wire [31:0] m_rdata,
    input wire [1:0] m_rresp
);
    (* ASYNC_REG = "TRUE" *) reg [1:0] source_reset_sync;
    wire source_reset = source_reset_sync[1];
    always @(posedge src_clk or posedge reset) begin
        if (reset) begin
            source_reset_sync <= 2'b11;
        end else begin
            source_reset_sync <= {source_reset_sync[0], 1'b0};
        end
    end
    reg aw_pending, w_pending, ar_pending, inflight, prefer_read;
    reg [15:0] awaddr, araddr;
    reg [31:0] wdata;
    reg [3:0] wstrb;
    reg [52:0] request_data;
    reg request_toggle, response_toggle;
    reg [33:0] response_data;
    (* ASYNC_REG = "TRUE" *) reg [1:0] request_sync, response_sync;
    reg active, is_write;

    assign s_awready = !source_reset && !src_reset && !aw_pending;
    assign s_wready = !source_reset && !src_reset && !w_pending;
    assign s_arready = !source_reset && !src_reset && !ar_pending;
    assign m_bready = active && is_write && !m_awvalid && !m_wvalid;
    assign m_rready = active && !is_write && !m_arvalid;

    always @(posedge src_clk or posedge source_reset) begin
        if (source_reset) begin
            response_sync <= 0;
        end else begin
            response_sync <= {response_sync[0], response_toggle};
        end
    end

    always @(posedge src_clk or posedge source_reset) begin
        if (source_reset) begin
            aw_pending <= 0;
            w_pending <= 0;
            ar_pending <= 0;
            inflight <= 0;
            prefer_read <= 0;
            awaddr <= 0;
            araddr <= 0;
            wdata <= 0;
            wstrb <= 0;
            request_data <= 0;
            request_toggle <= 0;
            s_bvalid <= 0;
            s_bresp <= 0;
            s_rvalid <= 0;
            s_rdata <= 0;
            s_rresp <= 0;
        end else begin
            if (s_awvalid && s_awready) begin
                aw_pending <= 1;
                awaddr <= s_awaddr;
            end
            if (s_wvalid && s_wready) begin
                w_pending <= 1;
                wdata <= s_wdata;
                wstrb <= s_wstrb;
            end
            if (s_arvalid && s_arready) begin
                ar_pending <= 1;
                araddr <= s_araddr;
            end
            if (s_bvalid && s_bready) begin
                s_bvalid <= 0;
            end
            if (s_rvalid && s_rready) begin
                s_rvalid <= 0;
            end
            if (inflight && response_sync[1] == request_toggle) begin
                inflight <= 0;
                if (!src_reset) begin
                    if (request_data[52]) begin
                        s_bvalid <= 1;
                        s_bresp <= response_data[33:32];
                    end else begin
                        s_rvalid <= 1;
                        s_rdata <= response_data[31:0];
                        s_rresp <= response_data[33:32];
                    end
                end
            end
            if (src_reset) begin
                aw_pending <= 0;
                w_pending <= 0;
                ar_pending <= 0;
                s_bvalid <= 0;
                s_rvalid <= 0;
            end else if (!inflight && !s_bvalid && !s_rvalid) begin
                // Both write channels are captured before ownership crosses clocks.
                if (ar_pending && (prefer_read || !(aw_pending && w_pending))) begin
                    request_data <= {1'b0, araddr, 36'b0};
                    request_toggle <= !request_toggle;
                    inflight <= 1;
                    ar_pending <= 0;
                    prefer_read <= 0;
                end else if (aw_pending && w_pending) begin
                    request_data <= {1'b1, awaddr, wdata, wstrb};
                    request_toggle <= !request_toggle;
                    inflight <= 1;
                    aw_pending <= 0;
                    w_pending <= 0;
                    prefer_read <= 1;
                end
            end
        end
    end

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            request_sync <= 0;
        end else begin
            request_sync <= {request_sync[0], request_toggle};
        end
    end

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            active <= 0;
            is_write <= 0;
            response_toggle <= 0;
            response_data <= 0;
            m_awvalid <= 0;
            m_awaddr <= 0;
            m_wvalid <= 0;
            m_wdata <= 0;
            m_wstrb <= 0;
            m_arvalid <= 0;
            m_araddr <= 0;
        end else begin
            if (!active && request_sync[1] != response_toggle) begin
                active <= 1;
                is_write <= request_data[52];
                m_awaddr <= request_data[51:36];
                m_wdata <= request_data[35:4];
                m_wstrb <= request_data[3:0];
                m_araddr <= request_data[51:36];
                m_awvalid <= request_data[52];
                m_wvalid <= request_data[52];
                m_arvalid <= !request_data[52];
            end
            if (m_awvalid && m_awready) begin
                m_awvalid <= 0;
            end
            if (m_wvalid && m_wready) begin
                m_wvalid <= 0;
            end
            if (m_arvalid && m_arready) begin
                m_arvalid <= 0;
            end
            // A PCIe reset cannot cancel a transaction already owned by the GPU clock.
            if (m_bvalid && m_bready) begin
                response_data <= {m_bresp, 32'b0};
                response_toggle <= request_sync[1];
                active <= 0;
            end else if (m_rvalid && m_rready) begin
                response_data <= {m_rresp, m_rdata};
                response_toggle <= request_sync[1];
                active <= 0;
            end
        end
    end
endmodule
