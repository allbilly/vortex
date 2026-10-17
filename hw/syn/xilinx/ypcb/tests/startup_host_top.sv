// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module startup_host_top (
    input wire clk,
    input wire reset,
    input wire [1:0] pll_locked,
    input wire [1:0] init_done,
    input wire [1:0] init_error,
    input wire link_up,
    input wire [3:0] pcie_error_status,
    output wire [1:0] memory_ready,
    output wire scrub_busy,
    output wire scrub_done,
    output wire scrub_failed,
    input wire s_awvalid,
    output wire s_awready,
    input wire [11:0] s_awaddr,
    input wire s_wvalid,
    output wire s_wready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    output wire s_bvalid,
    input wire s_bready,
    output wire [1:0] s_bresp,
    input wire s_arvalid,
    output wire s_arready,
    input wire [11:0] s_araddr,
    output wire s_rvalid,
    input wire s_rready,
    output wire [31:0] s_rdata,
    output wire [1:0] s_rresp,
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
    wire scrub_start;
    VX_ypcb_startup startup (.*);
    VX_ypcb_scrub #(
        .BASE_ADDR (64'h7fffff80),
        .END_ADDR (64'h800000c0)
    ) scrub (
        .clk (clk), .reset (reset), .start (scrub_start),
        .init_ready (pll_locked & init_done & ~init_error),
        .busy (scrub_busy), .done (scrub_done), .error (scrub_failed),
        .m_awvalid (m_awvalid), .m_awready (m_awready),
        .m_awaddr (m_awaddr), .m_awlen (m_awlen),
        .m_wvalid (m_wvalid), .m_wready (m_wready),
        .m_wdata (m_wdata), .m_wstrb (m_wstrb), .m_wlast (m_wlast),
        .m_bvalid (m_bvalid), .m_bready (m_bready), .m_bresp (m_bresp)
    );
endmodule
