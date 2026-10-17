// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`include "VX_platform.vh"

module VX_ypcb_shell #(
    parameter logic [63:0] SCRUB_BASE_ADDR = 64'd0,
    parameter logic [63:0] SCRUB_END_ADDR = 64'h100000000
) (
    input wire clk,
    input wire reset,
    input wire link_up,
    input wire tx_error,
    input wire [1:0] pll_locked,
    input wire [1:0] init_done,
    input wire [1:0] init_error,
    input wire rx_valid,
    output wire rx_ready,
    input wire [63:0] rx_data,
    input wire [7:0] rx_keep,
    input wire rx_last,
    input wire [21:0] rx_user,
    output wire tx_valid,
    input wire tx_ready,
    output wire [63:0] tx_data,
    output wire [7:0] tx_keep,
    output wire tx_last,
    input wire [15:0] completer_id,
    output wire busy,
    output wire [1:0] memory_ready,
    output wire [1:0] m_awvalid,
    input wire [1:0] m_awready,
    output wire [1:0][30:0] m_awaddr,
    output wire [1:0][7:0] m_awid,
    output wire [1:0][7:0] m_awlen,
    output wire [1:0] m_wvalid,
    input wire [1:0] m_wready,
    output wire [1:0][511:0] m_wdata,
    output wire [1:0][63:0] m_wstrb,
    output wire [1:0] m_wlast,
    input wire [1:0] m_bvalid,
    output wire [1:0] m_bready,
    input wire [1:0][7:0] m_bid,
    input wire [1:0][1:0] m_bresp,
    output wire [1:0] m_arvalid,
    input wire [1:0] m_arready,
    output wire [1:0][30:0] m_araddr,
    output wire [1:0][7:0] m_arid,
    output wire [1:0][7:0] m_arlen,
    input wire [1:0] m_rvalid,
    output wire [1:0] m_rready,
    input wire [1:0][511:0] m_rdata,
    input wire [1:0] m_rlast,
    input wire [1:0][7:0] m_rid,
    input wire [1:0][1:0] m_rresp,
    output wire [1:0] wb_cyc,
    output wire [1:0] wb_stb,
    output wire [1:0] wb_we,
    output wire [1:0][29:0] wb_adr,
    output wire [1:0][31:0] wb_dat_w,
    output wire [1:0][3:0] wb_sel,
    input wire [1:0] wb_ack,
    input wire [1:0] wb_err,
    input wire [1:0][31:0] wb_dat_r
);
    wire pcie_busy, memory_busy, scrub_busy, scrub_done, scrub_failed, scrub_start;
    wire afu_interrupt;
    `UNUSED_VAR (afu_interrupt)
    wire [3:0] pcie_error;
    reg hard_error;
    wire [3:0] transport_error = pcie_error | {hard_error, 3'b0};
    wire afu_ready = (&memory_ready) && link_up;
    assign busy = pcie_busy || memory_busy || scrub_busy;

    always @(posedge clk) begin
        if (reset) begin
            hard_error <= 0;
        end else if (tx_error) begin
            hard_error <= 1;
        end
    end

    wire [4:0] s_awvalid;
    wire [4:0] s_awready;
    wire [4:0][63:0] s_awaddr;
    wire [4:0][31:0] s_awid;
    wire [4:0][7:0] s_awlen;
    wire [4:0] s_wvalid;
    wire [4:0] s_wready;
    wire [4:0][511:0] s_wdata;
    wire [4:0][63:0] s_wstrb;
    wire [4:0] s_wlast;
    wire [4:0] s_bvalid;
    wire [4:0] s_bready;
    wire [4:0][31:0] s_bid;
    wire [4:0][1:0] s_bresp;
    wire [4:0] s_arvalid;
    wire [4:0] s_arready;
    wire [4:0][63:0] s_araddr;
    wire [4:0][31:0] s_arid;
    wire [4:0][7:0] s_arlen;
    wire [4:0] s_rvalid;
    wire [4:0] s_rready;
    wire [4:0][511:0] s_rdata;
    wire [4:0] s_rlast;
    wire [4:0][31:0] s_rid;
    wire [4:0][1:0] s_rresp;

    wire  ctrl_awvalid;
    wire  ctrl_awready;
    wire [15:0] ctrl_awaddr;
    wire  ctrl_wvalid;
    wire  ctrl_wready;
    wire [31:0] ctrl_wdata;
    wire [3:0] ctrl_wstrb;
    wire  ctrl_bvalid;
    wire  ctrl_bready;
    wire [1:0] ctrl_bresp;
    wire  ctrl_arvalid;
    wire  ctrl_arready;
    wire [15:0] ctrl_araddr;
    wire  ctrl_rvalid;
    wire  ctrl_rready;
    wire [31:0] ctrl_rdata;
    wire [1:0] ctrl_rresp;

    wire [4:0] route_awvalid;
    wire [4:0] route_awready;
    wire [4:0][15:0] route_awaddr;
    wire [4:0] route_wvalid;
    wire [4:0] route_wready;
    wire [4:0][31:0] route_wdata;
    wire [4:0][3:0] route_wstrb;
    wire [4:0] route_bvalid;
    wire [4:0] route_bready;
    wire [4:0][1:0] route_bresp;
    wire [4:0] route_arvalid;
    wire [4:0] route_arready;
    wire [4:0][15:0] route_araddr;
    wire [4:0] route_rvalid;
    wire [4:0] route_rready;
    wire [4:0][31:0] route_rdata;
    wire [4:0][1:0] route_rresp;

    wire  afu_awvalid;
    wire  afu_awready;
    wire [15:0] afu_awaddr;
    wire  afu_wvalid;
    wire  afu_wready;
    wire [31:0] afu_wdata;
    wire [3:0] afu_wstrb;
    wire  afu_bvalid;
    wire  afu_bready;
    wire [1:0] afu_bresp;
    wire  afu_arvalid;
    wire  afu_arready;
    wire [15:0] afu_araddr;
    wire  afu_rvalid;
    wire  afu_rready;
    wire [31:0] afu_rdata;
    wire [1:0] afu_rresp;

    VX_ypcb_pcie pcie (
        .clk          (clk),
        .reset        (reset),
        .completer_id (completer_id),
        .rx_valid     (rx_valid),
        .rx_ready     (rx_ready),
        .rx_data      (rx_data),
        .rx_keep      (rx_keep),
        .rx_last      (rx_last),
        .rx_user      (rx_user),
        .tx_valid     (tx_valid),
        .tx_ready     (tx_ready),
        .tx_data      (tx_data),
        .tx_keep      (tx_keep),
        .tx_last      (tx_last),
        .error_status (pcie_error),
        .busy         (pcie_busy),
        .m_awvalid    (ctrl_awvalid),
        .m_awready    (ctrl_awready),
        .m_awaddr     (ctrl_awaddr),
        .m_wvalid     (ctrl_wvalid),
        .m_wready     (ctrl_wready),
        .m_wdata      (ctrl_wdata),
        .m_wstrb      (ctrl_wstrb),
        .m_bvalid     (ctrl_bvalid),
        .m_bready     (ctrl_bready),
        .m_bresp      (ctrl_bresp),
        .m_arvalid    (ctrl_arvalid),
        .m_arready    (ctrl_arready),
        .m_araddr     (ctrl_araddr),
        .m_rvalid     (ctrl_rvalid),
        .m_rready     (ctrl_rready),
        .m_rdata      (ctrl_rdata),
        .m_rresp      (ctrl_rresp)
    );

    VX_ypcb_control control (
        .clk       (clk),
        .reset     (reset),
        .s_awvalid (ctrl_awvalid),
        .s_awready (ctrl_awready),
        .s_awaddr  (ctrl_awaddr),
        .s_wvalid  (ctrl_wvalid),
        .s_wready  (ctrl_wready),
        .s_wdata   (ctrl_wdata),
        .s_wstrb   (ctrl_wstrb),
        .s_bvalid  (ctrl_bvalid),
        .s_bready  (ctrl_bready),
        .s_bresp   (ctrl_bresp),
        .s_arvalid (ctrl_arvalid),
        .s_arready (ctrl_arready),
        .s_araddr  (ctrl_araddr),
        .s_rvalid  (ctrl_rvalid),
        .s_rready  (ctrl_rready),
        .s_rdata   (ctrl_rdata),
        .s_rresp   (ctrl_rresp),
        .m_awvalid (route_awvalid),
        .m_awready (route_awready),
        .m_awaddr  (route_awaddr),
        .m_wvalid  (route_wvalid),
        .m_wready  (route_wready),
        .m_wdata   (route_wdata),
        .m_wstrb   (route_wstrb),
        .m_bvalid  (route_bvalid),
        .m_bready  (route_bready),
        .m_bresp   (route_bresp),
        .m_arvalid (route_arvalid),
        .m_arready (route_arready),
        .m_araddr  (route_araddr),
        .m_rvalid  (route_rvalid),
        .m_rready  (route_rready),
        .m_rdata   (route_rdata),
        .m_rresp   (route_rresp)
    );

    VX_ypcb_afu_control afu_control (
        .clk       (clk),
        .reset     (reset),
        .ready     (afu_ready),
        .s_awvalid (route_awvalid[0]),
        .s_awready (route_awready[0]),
        .s_awaddr  (route_awaddr[0]),
        .s_wvalid  (route_wvalid[0]),
        .s_wready  (route_wready[0]),
        .s_wdata   (route_wdata[0]),
        .s_wstrb   (route_wstrb[0]),
        .s_bvalid  (route_bvalid[0]),
        .s_bready  (route_bready[0]),
        .s_bresp   (route_bresp[0]),
        .s_arvalid (route_arvalid[0]),
        .s_arready (route_arready[0]),
        .s_araddr  (route_araddr[0]),
        .s_rvalid  (route_rvalid[0]),
        .s_rready  (route_rready[0]),
        .s_rdata   (route_rdata[0]),
        .s_rresp   (route_rresp[0]),
        .m_awvalid (afu_awvalid),
        .m_awready (afu_awready),
        .m_awaddr  (afu_awaddr),
        .m_wvalid  (afu_wvalid),
        .m_wready  (afu_wready),
        .m_wdata   (afu_wdata),
        .m_wstrb   (afu_wstrb),
        .m_bvalid  (afu_bvalid),
        .m_bready  (afu_bready),
        .m_bresp   (afu_bresp),
        .m_arvalid (afu_arvalid),
        .m_arready (afu_arready),
        .m_araddr  (afu_araddr),
        .m_rvalid  (afu_rvalid),
        .m_rready  (afu_rready),
        .m_rdata   (afu_rdata),
        .m_rresp   (afu_rresp)
    );

    vortex_afu afu (
        .ap_clk              (clk),
        .ap_rst_n            (!reset && afu_ready),
        .m_axi_mem_0_awvalid (s_awvalid[0]),
        .m_axi_mem_0_awready (s_awready[0]),
        .m_axi_mem_0_awaddr  (s_awaddr[0]),
        .m_axi_mem_0_awid    (s_awid[0]),
        .m_axi_mem_0_awlen   (s_awlen[0]),
        .m_axi_mem_0_wvalid  (s_wvalid[0]),
        .m_axi_mem_0_wready  (s_wready[0]),
        .m_axi_mem_0_wdata   (s_wdata[0]),
        .m_axi_mem_0_wstrb   (s_wstrb[0]),
        .m_axi_mem_0_wlast   (s_wlast[0]),
        .m_axi_mem_0_bvalid  (s_bvalid[0]),
        .m_axi_mem_0_bready  (s_bready[0]),
        .m_axi_mem_0_bid     (s_bid[0]),
        .m_axi_mem_0_bresp   (s_bresp[0]),
        .m_axi_mem_0_arvalid (s_arvalid[0]),
        .m_axi_mem_0_arready (s_arready[0]),
        .m_axi_mem_0_araddr  (s_araddr[0]),
        .m_axi_mem_0_arid    (s_arid[0]),
        .m_axi_mem_0_arlen   (s_arlen[0]),
        .m_axi_mem_0_rvalid  (s_rvalid[0]),
        .m_axi_mem_0_rready  (s_rready[0]),
        .m_axi_mem_0_rdata   (s_rdata[0]),
        .m_axi_mem_0_rlast   (s_rlast[0]),
        .m_axi_mem_0_rid     (s_rid[0]),
        .m_axi_mem_0_rresp   (s_rresp[0]),
        .m_axi_mem_1_awvalid (s_awvalid[1]),
        .m_axi_mem_1_awready (s_awready[1]),
        .m_axi_mem_1_awaddr  (s_awaddr[1]),
        .m_axi_mem_1_awid    (s_awid[1]),
        .m_axi_mem_1_awlen   (s_awlen[1]),
        .m_axi_mem_1_wvalid  (s_wvalid[1]),
        .m_axi_mem_1_wready  (s_wready[1]),
        .m_axi_mem_1_wdata   (s_wdata[1]),
        .m_axi_mem_1_wstrb   (s_wstrb[1]),
        .m_axi_mem_1_wlast   (s_wlast[1]),
        .m_axi_mem_1_bvalid  (s_bvalid[1]),
        .m_axi_mem_1_bready  (s_bready[1]),
        .m_axi_mem_1_bid     (s_bid[1]),
        .m_axi_mem_1_bresp   (s_bresp[1]),
        .m_axi_mem_1_arvalid (s_arvalid[1]),
        .m_axi_mem_1_arready (s_arready[1]),
        .m_axi_mem_1_araddr  (s_araddr[1]),
        .m_axi_mem_1_arid    (s_arid[1]),
        .m_axi_mem_1_arlen   (s_arlen[1]),
        .m_axi_mem_1_rvalid  (s_rvalid[1]),
        .m_axi_mem_1_rready  (s_rready[1]),
        .m_axi_mem_1_rdata   (s_rdata[1]),
        .m_axi_mem_1_rlast   (s_rlast[1]),
        .m_axi_mem_1_rid     (s_rid[1]),
        .m_axi_mem_1_rresp   (s_rresp[1]),
        .m_axi_host_awvalid  (s_awvalid[2]),
        .m_axi_host_awready  (s_awready[2]),
        .m_axi_host_awaddr   (s_awaddr[2]),
        .m_axi_host_awid     (s_awid[2]),
        .m_axi_host_awlen    (s_awlen[2]),
        .m_axi_host_wvalid   (s_wvalid[2]),
        .m_axi_host_wready   (s_wready[2]),
        .m_axi_host_wdata    (s_wdata[2]),
        .m_axi_host_wstrb    (s_wstrb[2]),
        .m_axi_host_wlast    (s_wlast[2]),
        .m_axi_host_bvalid   (s_bvalid[2]),
        .m_axi_host_bready   (s_bready[2]),
        .m_axi_host_bid      (s_bid[2]),
        .m_axi_host_bresp    (s_bresp[2]),
        .m_axi_host_arvalid  (s_arvalid[2]),
        .m_axi_host_arready  (s_arready[2]),
        .m_axi_host_araddr   (s_araddr[2]),
        .m_axi_host_arid     (s_arid[2]),
        .m_axi_host_arlen    (s_arlen[2]),
        .m_axi_host_rvalid   (s_rvalid[2]),
        .m_axi_host_rready   (s_rready[2]),
        .m_axi_host_rdata    (s_rdata[2]),
        .m_axi_host_rlast    (s_rlast[2]),
        .m_axi_host_rid      (s_rid[2]),
        .m_axi_host_rresp    (s_rresp[2]),
        .s_axi_ctrl_awvalid  (afu_awvalid),
        .s_axi_ctrl_awready  (afu_awready),
        .s_axi_ctrl_awaddr   (afu_awaddr),
        .s_axi_ctrl_wvalid   (afu_wvalid),
        .s_axi_ctrl_wready   (afu_wready),
        .s_axi_ctrl_wdata    (afu_wdata),
        .s_axi_ctrl_wstrb    (afu_wstrb),
        .s_axi_ctrl_bvalid   (afu_bvalid),
        .s_axi_ctrl_bready   (afu_bready),
        .s_axi_ctrl_bresp    (afu_bresp),
        .s_axi_ctrl_arvalid  (afu_arvalid),
        .s_axi_ctrl_arready  (afu_arready),
        .s_axi_ctrl_araddr   (afu_araddr),
        .s_axi_ctrl_rvalid   (afu_rvalid),
        .s_axi_ctrl_rready   (afu_rready),
        .s_axi_ctrl_rdata    (afu_rdata),
        .s_axi_ctrl_rresp    (afu_rresp),
        .interrupt           (afu_interrupt)
    );

    VX_ypcb_pio pio (
        .clk          (clk),
        .reset        (reset),
        .memory_ready (memory_ready),
        .s_awvalid    (route_awvalid[1]),
        .s_awready    (route_awready[1]),
        .s_awaddr     (route_awaddr[1][11:0]),
        .s_wvalid     (route_wvalid[1]),
        .s_wready     (route_wready[1]),
        .s_wdata      (route_wdata[1]),
        .s_wstrb      (route_wstrb[1]),
        .s_bvalid     (route_bvalid[1]),
        .s_bready     (route_bready[1]),
        .s_bresp      (route_bresp[1]),
        .s_arvalid    (route_arvalid[1]),
        .s_arready    (route_arready[1]),
        .s_araddr     (route_araddr[1][11:0]),
        .s_rvalid     (route_rvalid[1]),
        .s_rready     (route_rready[1]),
        .s_rdata      (route_rdata[1]),
        .s_rresp      (route_rresp[1]),
        .m_awvalid    (s_awvalid[3]),
        .m_awready    (s_awready[3]),
        .m_awaddr     (s_awaddr[3]),
        .m_wvalid     (s_wvalid[3]),
        .m_wready     (s_wready[3]),
        .m_wdata      (s_wdata[3]),
        .m_wstrb      (s_wstrb[3]),
        .m_wlast      (s_wlast[3]),
        .m_bvalid     (s_bvalid[3]),
        .m_bready     (s_bready[3]),
        .m_bresp      (s_bresp[3]),
        .m_arvalid    (s_arvalid[3]),
        .m_arready    (s_arready[3]),
        .m_araddr     (s_araddr[3]),
        .m_rvalid     (s_rvalid[3]),
        .m_rready     (s_rready[3]),
        .m_rdata      (s_rdata[3]),
        .m_rlast      (s_rlast[3]),
        .m_rresp      (s_rresp[3])
    );

    assign s_awid[3] = '0;
    assign s_awlen[3] = '0;
    assign s_arid[3] = '0;
    assign s_arlen[3] = '0;
    `UNUSED_VAR ({s_bid[3], s_rid[3], route_awaddr[1][15:12], route_araddr[1][15:12]})

    VX_ypcb_startup startup (
        .clk               (clk),
        .reset             (reset),
        .pll_locked        (pll_locked),
        .init_done         (init_done),
        .init_error        (init_error),
        .link_up           (link_up),
        .pcie_error_status (transport_error),
        .scrub_busy        (scrub_busy),
        .scrub_done        (scrub_done),
        .scrub_failed      (scrub_failed),
        .scrub_start       (scrub_start),
        .memory_ready      (memory_ready),
        .s_awvalid         (route_awvalid[2]),
        .s_awready         (route_awready[2]),
        .s_awaddr          (route_awaddr[2][11:0]),
        .s_wvalid          (route_wvalid[2]),
        .s_wready          (route_wready[2]),
        .s_wdata           (route_wdata[2]),
        .s_wstrb           (route_wstrb[2]),
        .s_bvalid          (route_bvalid[2]),
        .s_bready          (route_bready[2]),
        .s_bresp           (route_bresp[2]),
        .s_arvalid         (route_arvalid[2]),
        .s_arready         (route_arready[2]),
        .s_araddr          (route_araddr[2][11:0]),
        .s_rvalid          (route_rvalid[2]),
        .s_rready          (route_rready[2]),
        .s_rdata           (route_rdata[2]),
        .s_rresp           (route_rresp[2])
    );

    VX_ypcb_scrub #(
        .BASE_ADDR (SCRUB_BASE_ADDR),
        .END_ADDR  (SCRUB_END_ADDR)
    ) scrub (
        .clk        (clk),
        .reset      (reset),
        .start      (scrub_start),
        .init_ready ((pll_locked & init_done & ~init_error)),
        .busy       (scrub_busy),
        .done       (scrub_done),
        .error      (scrub_failed),
        .m_awvalid  (s_awvalid[4]),
        .m_awready  (s_awready[4]),
        .m_awaddr   (s_awaddr[4]),
        .m_awlen    (s_awlen[4]),
        .m_wvalid   (s_wvalid[4]),
        .m_wready   (s_wready[4]),
        .m_wdata    (s_wdata[4]),
        .m_wstrb    (s_wstrb[4]),
        .m_wlast    (s_wlast[4]),
        .m_bvalid   (s_bvalid[4]),
        .m_bready   (s_bready[4]),
        .m_bresp    (s_bresp[4])
    );

    assign s_awid[4] = '0;
    assign s_arid[4] = '0;
    assign s_araddr[4] = '0;
    assign s_arlen[4] = '0;
    assign s_arvalid[4] = '0;
    assign s_rready[4] = '0;
    `UNUSED_VAR ({s_bid[4], s_arready[4], s_rvalid[4], s_rdata[4], s_rlast[4], s_rid[4], s_rresp[4], route_awaddr[2][15:12], route_araddr[2][15:12]})

    VX_ypcb_memory #(
        .NUM_INPUTS (5),
        .ID_WIDTH   (32)
    ) memory (
        .clk       (clk),
        .reset     (reset),
        .busy      (memory_busy),
        .s_awvalid (s_awvalid),
        .s_awready (s_awready),
        .s_awaddr  (s_awaddr),
        .s_awid    (s_awid),
        .s_awlen   (s_awlen),
        .s_wvalid  (s_wvalid),
        .s_wready  (s_wready),
        .s_wdata   (s_wdata),
        .s_wstrb   (s_wstrb),
        .s_wlast   (s_wlast),
        .s_bvalid  (s_bvalid),
        .s_bready  (s_bready),
        .s_bid     (s_bid),
        .s_bresp   (s_bresp),
        .s_arvalid (s_arvalid),
        .s_arready (s_arready),
        .s_araddr  (s_araddr),
        .s_arid    (s_arid),
        .s_arlen   (s_arlen),
        .s_rvalid  (s_rvalid),
        .s_rready  (s_rready),
        .s_rdata   (s_rdata),
        .s_rlast   (s_rlast),
        .s_rid     (s_rid),
        .s_rresp   (s_rresp),
        .m_awvalid (m_awvalid),
        .m_awready (m_awready),
        .m_awaddr  (m_awaddr),
        .m_awid    (m_awid),
        .m_awlen   (m_awlen),
        .m_wvalid  (m_wvalid),
        .m_wready  (m_wready),
        .m_wdata   (m_wdata),
        .m_wstrb   (m_wstrb),
        .m_wlast   (m_wlast),
        .m_bvalid  (m_bvalid),
        .m_bready  (m_bready),
        .m_bid     (m_bid),
        .m_bresp   (m_bresp),
        .m_arvalid (m_arvalid),
        .m_arready (m_arready),
        .m_araddr  (m_araddr),
        .m_arid    (m_arid),
        .m_arlen   (m_arlen),
        .m_rvalid  (m_rvalid),
        .m_rready  (m_rready),
        .m_rdata   (m_rdata),
        .m_rlast   (m_rlast),
        .m_rid     (m_rid),
        .m_rresp   (m_rresp)
    );

    for (genvar bank = 0; bank < 2; ++bank) begin : g_control
        VX_ypcb_ddr_control ddr_control (
            .clk       (clk),
            .reset     (reset),
            .s_awvalid (route_awvalid[bank + 3]),
            .s_awready (route_awready[bank + 3]),
            .s_awaddr  (route_awaddr[bank + 3][12:0]),
            .s_wvalid  (route_wvalid[bank + 3]),
            .s_wready  (route_wready[bank + 3]),
            .s_wdata   (route_wdata[bank + 3]),
            .s_wstrb   (route_wstrb[bank + 3]),
            .s_bvalid  (route_bvalid[bank + 3]),
            .s_bready  (route_bready[bank + 3]),
            .s_bresp   (route_bresp[bank + 3]),
            .s_arvalid (route_arvalid[bank + 3]),
            .s_arready (route_arready[bank + 3]),
            .s_araddr  (route_araddr[bank + 3][12:0]),
            .s_rvalid  (route_rvalid[bank + 3]),
            .s_rready  (route_rready[bank + 3]),
            .s_rdata   (route_rdata[bank + 3]),
            .s_rresp   (route_rresp[bank + 3]),
            .wb_cyc    (wb_cyc[bank]),
            .wb_stb    (wb_stb[bank]),
            .wb_we     (wb_we[bank]),
            .wb_adr    (wb_adr[bank]),
            .wb_dat_w  (wb_dat_w[bank]),
            .wb_sel    (wb_sel[bank]),
            .wb_ack    (wb_ack[bank]),
            .wb_err    (wb_err[bank]),
            .wb_dat_r  (wb_dat_r[bank])
        );

        `UNUSED_VAR ({route_awaddr[bank + 3][15:13], route_araddr[bank + 3][15:13]})
    end
endmodule
