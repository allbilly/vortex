// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`include "VX_platform.vh"

module ypcb_top (
    input wire SYS_CLK,
    input wire SYS_RSTN,
    input wire pcie_perstn,
    input wire pcie_refclk_p,
    input wire pcie_refclk_n,
    input wire pci_exp_rxp,
    input wire pci_exp_rxn,
    output wire pci_exp_txp,
    output wire pci_exp_txn,
    output wire [14:0] ddr1_a,
    output wire [2:0] ddr1_ba,
    output wire  ddr1_cas_n,
    output wire  ddr1_cke,
    output wire  ddr1_clk_n,
    output wire  ddr1_clk_p,
    output wire  ddr1_cs_n,
    inout wire [71:0] ddr1_dq,
    inout wire [8:0] ddr1_dqs_n,
    inout wire [8:0] ddr1_dqs_p,
    output wire  ddr1_odt,
    output wire  ddr1_ras_n,
    output wire  ddr1_reset_n,
    output wire  ddr1_we_n
);
    wire clock_50, clock_50_raw, clock_feedback, clock_feedback_raw;
    wire board_locked, pcie_refclk, bus_clk, pcie_clk, pcie_reset, link_up, shell_busy;
    wire clock_125_raw, pcie_link_up;
    (* ASYNC_REG = "TRUE" *) reg [1:0] link_sync;
    wire [1:0] memory_clk, memory_reset, pll_locked, init_done, init_error;
    wire [1:0] memory_ready;
    wire reset_async = !SYS_RSTN || !board_locked;
    (* ASYNC_REG = "TRUE" *) reg [1:0] reset_sync = 2'b11;
    always @(posedge bus_clk or posedge reset_async) begin
        if (reset_async) begin
            reset_sync <= 2'b11;
        end else begin
            reset_sync <= {reset_sync[0], 1'b0};
        end
    end
    wire reset = reset_sync[1];
    always @(posedge bus_clk) begin
        if (reset) begin
            link_sync <= 0;
        end else begin
            link_sync <= {link_sync[0], pcie_link_up};
        end
    end
    assign link_up = link_sync[1];


    IBUF board_clock (
        .I (SYS_CLK),
        .O (clock_50_raw)
    );
    BUFG board_clock_50 (.I(clock_50_raw), .O(clock_50));
    BUFG board_feedback (
        .I (clock_feedback_raw),
        .O (clock_feedback)
    );
    BUFG board_clock_125 (.I(clock_125_raw), .O(bus_clk));
    PLLE2_BASE #(
        .CLKIN1_PERIOD  (20.0),
        .CLKFBOUT_MULT  (20),
        .DIVCLK_DIVIDE  (1),
        .CLKOUT0_DIVIDE (5),
        .CLKOUT1_DIVIDE (8)
    ) board_pll (
        .CLKIN1   (clock_50),
        .CLKFBIN  (clock_feedback),
        .CLKFBOUT (clock_feedback_raw),
        .CLKOUT0  (),
        .CLKOUT1  (clock_125_raw),
        .CLKOUT2  (),
        .CLKOUT3  (),
        .CLKOUT4  (),
        .CLKOUT5  (),
        .LOCKED   (board_locked),
        .PWRDWN   (1'b0),
        .RST      (!SYS_RSTN)
    );
    IBUFDS_GTE2 pcie_reference (
        .I     (pcie_refclk_p),
        .IB    (pcie_refclk_n),
        .CEB   (1'b0),
        .O     (pcie_refclk),
        .ODIV2 ()
    );

    wire rx_valid, rx_ready, rx_last, tx_valid, tx_ready, tx_last, tx_error;
    wire [63:0] rx_data, tx_data;
    wire tx_error_raw;
    reg tx_error_latched;
    (* ASYNC_REG = "TRUE" *) reg [1:0] tx_error_sync;
    always @(posedge pcie_clk or posedge reset_async) begin
        if (reset_async) begin
            tx_error_latched <= 0;
        end else if (tx_error_raw) begin
            tx_error_latched <= 1;
        end
    end
    always @(posedge bus_clk) begin
        if (reset) begin
            tx_error_sync <= 0;
        end else begin
            tx_error_sync <= {tx_error_sync[0], tx_error_latched};
        end
    end
    assign tx_error = tx_error_sync[1];
    wire [7:0] rx_keep, tx_keep;
    wire [21:0] rx_user;
    wire [7:0] bus_number;
    wire [4:0] device_number;
    wire [2:0] function_number;
    wire turnoff_requested;

    pcie_7x #(
        .PCIE_GT_DEVICE               ("GTX"),
        .PCIE_USE_MODE                ("3.0"),
        .CFG_VEND_ID                  (16'h10ee),
        .CFG_DEV_ID                   (16'h0480),
        .BAR0                         (32'hffff0000),
        .C_DATA_WIDTH                 (64),
        .LINK_CAP_MAX_LINK_SPEED      (4'h2),
        .LINK_CTRL2_TARGET_LINK_SPEED (4'h2),
        .USER_CLK_FREQ                (2),
        .MSI_CAP_ON                   ("FALSE"),
        .MSIX_CAP_ON                  ("FALSE"),
        .CMD_INTX_IMPLEMENTED         ("FALSE"),
        .INTERRUPT_PIN                (8'h00)
    ) pcie (
        .pci_exp_txn                  (pci_exp_txn),
        .pci_exp_txp                  (pci_exp_txp),
        .pci_exp_rxn                  (pci_exp_rxn),
        .pci_exp_rxp                  (pci_exp_rxp),
        .pipe_mmcm_rst_n              (SYS_RSTN && pcie_perstn),
        .pipe_mmcm_lock               (),
        .user_clk_out                 (pcie_clk),
        .user_reset_out               (pcie_reset),
        .user_lnk_up                  (pcie_link_up),
        .tx_cfg_gnt                   (1'b1),
        .rx_np_ok                     (1'b1),
        .rx_np_req                    (1'b1),
        .cfg_turnoff_ok               (1'b0),
        .cfg_trn_pending              (1'b1),
        .cfg_pm_halt_aspm_l0s         (1'b1),
        .cfg_pm_halt_aspm_l1          (1'b1),
        .cfg_pm_force_state_en        (1'b0),
        .cfg_pm_force_state           (2'b0),
        .cfg_dsn                      (64'b0),
        .cfg_pm_wake                  (1'b0),
        .s_axis_tx_tdata              (tx_data),
        .s_axis_tx_tvalid             (tx_valid),
        .s_axis_tx_tready             (tx_ready),
        .s_axis_tx_tkeep              (tx_keep),
        .s_axis_tx_tlast              (tx_last),
        .s_axis_tx_tuser              (4'b0),
        .m_axis_rx_tdata              (rx_data),
        .m_axis_rx_tvalid             (rx_valid),
        .m_axis_rx_tready             (rx_ready),
        .m_axis_rx_tkeep              (rx_keep),
        .m_axis_rx_tlast              (rx_last),
        .m_axis_rx_tuser              (rx_user),
        .tx_err_drop                  (tx_error_raw),
        .tx_cfg_req                   (),
        .tx_buf_av                    (),
        .cfg_status                   (),
        .cfg_command                  (),
        .cfg_dstatus                  (),
        .cfg_dcommand                 (),
        .cfg_lstatus                  (),
        .cfg_lcommand                 (),
        .cfg_dcommand2                (),
        .cfg_pcie_link_state          (),
        .cfg_to_turnoff               (turnoff_requested),
        .cfg_bus_number               (bus_number),
        .cfg_device_number            (device_number),
        .cfg_function_number          (function_number),
        .cfg_pmcsr_pme_en             (),
        .cfg_pmcsr_powerstate         (),
        .cfg_pmcsr_pme_status         (),
        .cfg_received_func_lvl_rst    (),
        .cfg_interrupt                (1'b0),
        .cfg_interrupt_rdy            (),
        .cfg_interrupt_assert         (1'b0),
        .cfg_interrupt_di             (8'b0),
        .cfg_interrupt_do             (),
        .cfg_interrupt_mmenable       (),
        .cfg_interrupt_msienable      (),
        .cfg_interrupt_msixenable     (),
        .cfg_interrupt_msixfm         (),
        .cfg_interrupt_stat           (1'b0),
        .cfg_pciecap_interrupt_msgnum (5'b0),
        .sys_clk                      (pcie_refclk),
        .sys_rst_n                    (SYS_RSTN && pcie_perstn),
        .gt_reset_fsm                 (),
        .pl_ltssm_state               (),
        .pipe_pclk_in                 (1'b0),
        .pipe_dclk_in                 (1'b0),
        .pipe_oobclk_in               (1'b0),
        .pipe_userclk1_in             (1'b0),
        .pipe_userclk2_in             (1'b0),
        .pipe_mmcm_lock_in            (1'b0),
        .pipe_rxusrclk_in             (1'b0),
        .pipe_rxoutclk_in             (1'b0),
        .pipe_pclk_sel_out            (),
        .pipe_txoutclk_out            ()
    );

    wire [1:0] m_awvalid;
    wire [1:0] m_awready;
    wire [1:0][30:0] m_awaddr;
    wire [1:0][7:0] m_awid;
    wire [1:0][7:0] m_awlen;
    wire [1:0] m_wvalid;
    wire [1:0] m_wready;
    wire [1:0][511:0] m_wdata;
    wire [1:0][63:0] m_wstrb;
    wire [1:0] m_wlast;
    wire [1:0] m_bvalid;
    wire [1:0] m_bready;
    wire [1:0][7:0] m_bid;
    wire [1:0][1:0] m_bresp;
    wire [1:0] m_arvalid;
    wire [1:0] m_arready;
    wire [1:0][30:0] m_araddr;
    wire [1:0][7:0] m_arid;
    wire [1:0][7:0] m_arlen;
    wire [1:0] m_rvalid;
    wire [1:0] m_rready;
    wire [1:0][511:0] m_rdata;
    wire [1:0] m_rlast;
    wire [1:0][7:0] m_rid;
    wire [1:0][1:0] m_rresp;
    wire [1:0] wb_cyc;
    wire [1:0] wb_stb;
    wire [1:0] wb_we;
    wire [1:0][29:0] wb_adr;
    wire [1:0][31:0] wb_dat_w;
    wire [1:0][3:0] wb_sel;
    wire [1:0] wb_ack;
    wire [1:0] wb_err;
    wire [1:0][31:0] wb_dat_r;

    wire [1:0][30:0] ddr_axi_araddr;
    wire [1:0][1:0] ddr_axi_arburst;
    wire [1:0][3:0] ddr_axi_arcache;
    wire [1:0][7:0] ddr_axi_arid;
    wire [1:0][7:0] ddr_axi_arlen;
    wire [1:0] ddr_axi_arlock;
    wire [1:0][2:0] ddr_axi_arprot;
    wire [1:0][3:0] ddr_axi_arqos;
    wire [1:0] ddr_axi_arready;
    wire [1:0][3:0] ddr_axi_arregion;
    wire [1:0][2:0] ddr_axi_arsize;
    wire [1:0] ddr_axi_aruser;
    wire [1:0] ddr_axi_arvalid;
    wire [1:0][30:0] ddr_axi_awaddr;
    wire [1:0][1:0] ddr_axi_awburst;
    wire [1:0][3:0] ddr_axi_awcache;
    wire [1:0][7:0] ddr_axi_awid;
    wire [1:0][7:0] ddr_axi_awlen;
    wire [1:0] ddr_axi_awlock;
    wire [1:0][2:0] ddr_axi_awprot;
    wire [1:0][3:0] ddr_axi_awqos;
    wire [1:0] ddr_axi_awready;
    wire [1:0][3:0] ddr_axi_awregion;
    wire [1:0][2:0] ddr_axi_awsize;
    wire [1:0] ddr_axi_awuser;
    wire [1:0] ddr_axi_awvalid;
    wire [1:0][7:0] ddr_axi_bid;
    wire [1:0] ddr_axi_bready;
    wire [1:0][1:0] ddr_axi_bresp;
    wire [1:0] ddr_axi_bvalid;
    wire [1:0][511:0] ddr_axi_rdata;
    wire [1:0][7:0] ddr_axi_rid;
    wire [1:0] ddr_axi_rlast;
    wire [1:0] ddr_axi_rready;
    wire [1:0][1:0] ddr_axi_rresp;
    wire [1:0] ddr_axi_rvalid;
    wire [1:0][511:0] ddr_axi_wdata;
    wire [1:0] ddr_axi_wlast;
    wire [1:0] ddr_axi_wready;
    wire [1:0][63:0] ddr_axi_wstrb;
    wire [1:0] ddr_axi_wuser;
    wire [1:0] ddr_axi_wvalid;

    wire [1:0] ddr_wb_ack;
    wire [1:0][29:0] ddr_wb_adr;
    wire [1:0][1:0] ddr_wb_bte;
    wire [1:0][2:0] ddr_wb_cti;
    wire [1:0] ddr_wb_cyc;
    wire [1:0][31:0] ddr_wb_dat_r;
    wire [1:0][31:0] ddr_wb_dat_w;
    wire [1:0] ddr_wb_err;
    wire [1:0][3:0] ddr_wb_sel;
    wire [1:0] ddr_wb_stb;
    wire [1:0] ddr_wb_we;

    (* ASYNC_REG = "TRUE" *) reg [5:0] status_meta, status_sync;
    always @(posedge bus_clk) begin
        if (reset) begin
            status_meta <= 0;
            status_sync <= 0;
        end else begin
            status_meta <= {pll_locked, init_done, init_error};
            status_sync <= status_meta;
        end
    end

    wire j_awvalid;
    wire j_awready;
    wire [15:0] j_awaddr;
    wire j_wvalid;
    wire j_wready;
    wire [31:0] j_wdata;
    wire [3:0] j_wstrb;
    wire j_bvalid;
    wire j_bready;
    wire [1:0] j_bresp;
    wire j_arvalid;
    wire j_arready;
    wire [15:0] j_araddr;
    wire j_rvalid;
    wire j_rready;
    wire [31:0] j_rdata;
    wire [1:0] j_rresp;
    reg jtag_error;
    always @(posedge bus_clk) begin
        if (reset) begin
            jtag_error <= 0;
        end else if ((j_bvalid && j_bready && (|j_bresp))
                || (j_rvalid && j_rready && (|j_rresp))) begin
            jtag_error <= 1;
        end
    end
    wire [31:0] j_awaddr_full, j_araddr_full;
    assign j_awaddr = (|j_awaddr_full[31:16]) ? 16'hf000 : j_awaddr_full[15:0];
    assign j_araddr = (|j_araddr_full[31:16]) ? 16'hf000 : j_araddr_full[15:0];
    ypcb_jtag_axi jtag (
        .aclk (bus_clk),
        .aresetn (!reset),
        .m_axi_awvalid (j_awvalid),
        .m_axi_awready (j_awready),
        .m_axi_awaddr (j_awaddr_full),
        .m_axi_wvalid (j_wvalid),
        .m_axi_wready (j_wready),
        .m_axi_wdata (j_wdata),
        .m_axi_wstrb (j_wstrb),
        .m_axi_bvalid (j_bvalid),
        .m_axi_bready (j_bready),
        .m_axi_bresp (j_bresp),
        .m_axi_arvalid (j_arvalid),
        .m_axi_arready (j_arready),
        .m_axi_araddr (j_araddr_full),
        .m_axi_rvalid (j_rvalid),
        .m_axi_rready (j_rready),
        .m_axi_rdata (j_rdata),
        .m_axi_rresp (j_rresp),
        `UNUSED_PIN (m_axi_awprot),
        `UNUSED_PIN (m_axi_arprot)
    );

    VX_ypcb_shell shell (
        .pcie_clk (pcie_clk),
        .pcie_reset (pcie_reset),
        .j_awvalid (j_awvalid),
        .j_awready (j_awready),
        .j_awaddr (j_awaddr),
        .j_wvalid (j_wvalid),
        .j_wready (j_wready),
        .j_wdata (j_wdata),
        .j_wstrb (j_wstrb),
        .j_bvalid (j_bvalid),
        .j_bready (j_bready),
        .j_bresp (j_bresp),
        .j_arvalid (j_arvalid),
        .j_arready (j_arready),
        .j_araddr (j_araddr),
        .j_rvalid (j_rvalid),
        .j_rready (j_rready),
        .j_rdata (j_rdata),
        .j_rresp (j_rresp),

        .clk          (bus_clk),
        .reset        (reset),
        .link_up      (link_up),
        .tx_error     (tx_error || jtag_error),
        .pll_locked   (status_sync[5:4]),
        .init_done    (status_sync[3:2]),
        .init_error   (status_sync[1:0]),
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
        .completer_id ({bus_number, device_number, function_number}),
        .busy         (shell_busy),
        .memory_ready (memory_ready),
        .m_awvalid    (m_awvalid),
        .m_awready    (m_awready),
        .m_awaddr     (m_awaddr),
        .m_awid       (m_awid),
        .m_awlen      (m_awlen),
        .m_wvalid     (m_wvalid),
        .m_wready     (m_wready),
        .m_wdata      (m_wdata),
        .m_wstrb      (m_wstrb),
        .m_wlast      (m_wlast),
        .m_bvalid     (m_bvalid),
        .m_bready     (m_bready),
        .m_bid        (m_bid),
        .m_bresp      (m_bresp),
        .m_arvalid    (m_arvalid),
        .m_arready    (m_arready),
        .m_araddr     (m_araddr),
        .m_arid       (m_arid),
        .m_arlen      (m_arlen),
        .m_rvalid     (m_rvalid),
        .m_rready     (m_rready),
        .m_rdata      (m_rdata),
        .m_rlast      (m_rlast),
        .m_rid        (m_rid),
        .m_rresp      (m_rresp),
        .wb_cyc       (wb_cyc),
        .wb_stb       (wb_stb),
        .wb_we        (wb_we),
        .wb_adr       (wb_adr),
        .wb_dat_w     (wb_dat_w),
        .wb_sel       (wb_sel),
        .wb_ack       (wb_ack),
        .wb_err       (wb_err),
        .wb_dat_r     (wb_dat_r)
    );

    assign memory_clk[0] = 1'b0;
    assign memory_reset[0] = 1'b1;
    assign pll_locked[0] = 1'b0;
    assign init_done[0] = 1'b0;
    assign init_error[0] = 1'b0;
    assign m_awready[0] = 1'b0;
    assign m_wready[0] = 1'b0;
    assign m_bvalid[0] = 1'b0;
    assign m_bid[0] = '0;
    assign m_bresp[0] = '0;
    assign m_arready[0] = 1'b0;
    assign m_rvalid[0] = 1'b0;
    assign m_rdata[0] = '0;
    assign m_rlast[0] = 1'b0;
    assign m_rid[0] = '0;
    assign m_rresp[0] = '0;
    assign wb_ack[0] = wb_cyc[0] && wb_stb[0];
    assign wb_err[0] = wb_cyc[0] && wb_stb[0];
    assign wb_dat_r[0] = '0;

    wire crossing_reset_1 = reset_async || memory_reset[1];
    ypcb_axi_cdc axi_crossing_1 (
        .bus_clk        (bus_clk),
        .bus_reset      (crossing_reset_1),
        .m_axi_araddr   (ddr_axi_araddr[1]),
        .m_axi_arburst  (ddr_axi_arburst[1]),
        .m_axi_arcache  (ddr_axi_arcache[1]),
        .m_axi_arid     (ddr_axi_arid[1]),
        .m_axi_arlen    (ddr_axi_arlen[1]),
        .m_axi_arlock   (ddr_axi_arlock[1]),
        .m_axi_arprot   (ddr_axi_arprot[1]),
        .m_axi_arqos    (ddr_axi_arqos[1]),
        .m_axi_arready  (ddr_axi_arready[1]),
        .m_axi_arregion (ddr_axi_arregion[1]),
        .m_axi_arsize   (ddr_axi_arsize[1]),
        .m_axi_aruser   (ddr_axi_aruser[1]),
        .m_axi_arvalid  (ddr_axi_arvalid[1]),
        .m_axi_awaddr   (ddr_axi_awaddr[1]),
        .m_axi_awburst  (ddr_axi_awburst[1]),
        .m_axi_awcache  (ddr_axi_awcache[1]),
        .m_axi_awid     (ddr_axi_awid[1]),
        .m_axi_awlen    (ddr_axi_awlen[1]),
        .m_axi_awlock   (ddr_axi_awlock[1]),
        .m_axi_awprot   (ddr_axi_awprot[1]),
        .m_axi_awqos    (ddr_axi_awqos[1]),
        .m_axi_awready  (ddr_axi_awready[1]),
        .m_axi_awregion (ddr_axi_awregion[1]),
        .m_axi_awsize   (ddr_axi_awsize[1]),
        .m_axi_awuser   (ddr_axi_awuser[1]),
        .m_axi_awvalid  (ddr_axi_awvalid[1]),
        .m_axi_bid      (ddr_axi_bid[1]),
        .m_axi_bready   (ddr_axi_bready[1]),
        .m_axi_bresp    (ddr_axi_bresp[1]),
        .m_axi_buser    (1'b0),
        .m_axi_bvalid   (ddr_axi_bvalid[1]),
        .m_axi_rdata    (ddr_axi_rdata[1]),
        .m_axi_rid      (ddr_axi_rid[1]),
        .m_axi_rlast    (ddr_axi_rlast[1]),
        .m_axi_rready   (ddr_axi_rready[1]),
        .m_axi_rresp    (ddr_axi_rresp[1]),
        .m_axi_ruser    (1'b0),
        .m_axi_rvalid   (ddr_axi_rvalid[1]),
        .m_axi_wdata    (ddr_axi_wdata[1]),
        .m_axi_wlast    (ddr_axi_wlast[1]),
        .m_axi_wready   (ddr_axi_wready[1]),
        .m_axi_wstrb    (ddr_axi_wstrb[1]),
        .m_axi_wuser    (ddr_axi_wuser[1]),
        .m_axi_wvalid   (ddr_axi_wvalid[1]),
        .memory_clk     (memory_clk[1]),
        .memory_reset   (crossing_reset_1),
        .s_axi_araddr   (m_araddr[1]),
        .s_axi_arburst  (2'b01),
        .s_axi_arcache  (4'd0),
        .s_axi_arid     (m_arid[1]),
        .s_axi_arlen    (m_arlen[1]),
        .s_axi_arlock   ('0),
        .s_axi_arprot   (3'd0),
        .s_axi_arqos    (4'd0),
        .s_axi_arready  (m_arready[1]),
        .s_axi_arregion (4'd0),
        .s_axi_arsize   (3'd6),
        .s_axi_aruser   ('0),
        .s_axi_arvalid  (m_arvalid[1]),
        .s_axi_awaddr   (m_awaddr[1]),
        .s_axi_awburst  (2'b01),
        .s_axi_awcache  (4'd0),
        .s_axi_awid     (m_awid[1]),
        .s_axi_awlen    (m_awlen[1]),
        .s_axi_awlock   ('0),
        .s_axi_awprot   (3'd0),
        .s_axi_awqos    (4'd0),
        .s_axi_awready  (m_awready[1]),
        .s_axi_awregion (4'd0),
        .s_axi_awsize   (3'd6),
        .s_axi_awuser   ('0),
        .s_axi_awvalid  (m_awvalid[1]),
        .s_axi_bid      (m_bid[1]),
        .s_axi_bready   (m_bready[1]),
        .s_axi_bresp    (m_bresp[1]),
        .s_axi_buser    (),
        .s_axi_bvalid   (m_bvalid[1]),
        .s_axi_rdata    (m_rdata[1]),
        .s_axi_rid      (m_rid[1]),
        .s_axi_rlast    (m_rlast[1]),
        .s_axi_rready   (m_rready[1]),
        .s_axi_rresp    (m_rresp[1]),
        .s_axi_ruser    (),
        .s_axi_rvalid   (m_rvalid[1]),
        .s_axi_wdata    (m_wdata[1]),
        .s_axi_wlast    (m_wlast[1]),
        .s_axi_wready   (m_wready[1]),
        .s_axi_wstrb    (m_wstrb[1]),
        .s_axi_wuser    ('0),
        .s_axi_wvalid   (m_wvalid[1])
    );

    ypcb_wb_cdc csr_crossing_1 (
        .bus_clk      (bus_clk),
        .bus_reset    (crossing_reset_1),
        .m_wb_ack     (ddr_wb_ack[1]),
        .m_wb_adr     (ddr_wb_adr[1]),
        .m_wb_bte     (ddr_wb_bte[1]),
        .m_wb_cti     (ddr_wb_cti[1]),
        .m_wb_cyc     (ddr_wb_cyc[1]),
        .m_wb_dat_r   (ddr_wb_dat_r[1]),
        .m_wb_dat_w   (ddr_wb_dat_w[1]),
        .m_wb_err     (ddr_wb_err[1]),
        .m_wb_sel     (ddr_wb_sel[1]),
        .m_wb_stb     (ddr_wb_stb[1]),
        .m_wb_we      (ddr_wb_we[1]),
        .memory_clk   (memory_clk[1]),
        .memory_reset (crossing_reset_1),
        .s_wb_ack     (wb_ack[1]),
        .s_wb_adr     (wb_adr[1]),
        .s_wb_bte     (2'd0),
        .s_wb_cti     (3'd0),
        .s_wb_cyc     (wb_cyc[1]),
        .s_wb_dat_r   (wb_dat_r[1]),
        .s_wb_dat_w   (wb_dat_w[1]),
        .s_wb_err     (wb_err[1]),
        .s_wb_sel     (wb_sel[1]),
        .s_wb_stb     (wb_stb[1]),
        .s_wb_we      (wb_we[1])
    );

    ypcb_ddr3 ddr_1 (
        .clk                     (clock_50),
        .ddram_a                 (ddr1_a),
        .ddram_ba                (ddr1_ba),
        .ddram_cas_n             (ddr1_cas_n),
        .ddram_cke               (ddr1_cke),
        .ddram_clk_n             (ddr1_clk_n),
        .ddram_clk_p             (ddr1_clk_p),
        .ddram_cs_n              (ddr1_cs_n),
        .ddram_dm                (),
        .ddram_dq                (ddr1_dq),
        .ddram_dqs_n             (ddr1_dqs_n),
        .ddram_dqs_p             (ddr1_dqs_p),
        .ddram_odt               (ddr1_odt),
        .ddram_ras_n             (ddr1_ras_n),
        .ddram_reset_n           (ddr1_reset_n),
        .ddram_we_n              (ddr1_we_n),
        .init_done               (init_done[1]),
        .init_error              (init_error[1]),
        .pll_locked              (pll_locked[1]),
        .rst                     (reset_async),
        .user_clk                (memory_clk[1]),
        .user_port_axi_0_araddr  (ddr_axi_araddr[1]),
        .user_port_axi_0_arburst (ddr_axi_arburst[1]),
        .user_port_axi_0_arid    (ddr_axi_arid[1]),
        .user_port_axi_0_arlen   (ddr_axi_arlen[1]),
        .user_port_axi_0_arready (ddr_axi_arready[1]),
        .user_port_axi_0_arsize  (ddr_axi_arsize[1]),
        .user_port_axi_0_arvalid (ddr_axi_arvalid[1]),
        .user_port_axi_0_awaddr  (ddr_axi_awaddr[1]),
        .user_port_axi_0_awburst (ddr_axi_awburst[1]),
        .user_port_axi_0_awid    (ddr_axi_awid[1]),
        .user_port_axi_0_awlen   (ddr_axi_awlen[1]),
        .user_port_axi_0_awready (ddr_axi_awready[1]),
        .user_port_axi_0_awsize  (ddr_axi_awsize[1]),
        .user_port_axi_0_awvalid (ddr_axi_awvalid[1]),
        .user_port_axi_0_bid     (ddr_axi_bid[1]),
        .user_port_axi_0_bready  (ddr_axi_bready[1]),
        .user_port_axi_0_bresp   (ddr_axi_bresp[1]),
        .user_port_axi_0_bvalid  (ddr_axi_bvalid[1]),
        .user_port_axi_0_rdata   (ddr_axi_rdata[1]),
        .user_port_axi_0_rid     (ddr_axi_rid[1]),
        .user_port_axi_0_rlast   (ddr_axi_rlast[1]),
        .user_port_axi_0_rready  (ddr_axi_rready[1]),
        .user_port_axi_0_rresp   (ddr_axi_rresp[1]),
        .user_port_axi_0_rvalid  (ddr_axi_rvalid[1]),
        .user_port_axi_0_wdata   (ddr_axi_wdata[1]),
        .user_port_axi_0_wlast   (ddr_axi_wlast[1]),
        .user_port_axi_0_wready  (ddr_axi_wready[1]),
        .user_port_axi_0_wstrb   (ddr_axi_wstrb[1]),
        .user_port_axi_0_wvalid  (ddr_axi_wvalid[1]),
        .user_rst                (memory_reset[1]),
        .wb_ctrl_ack             (ddr_wb_ack[1]),
        .wb_ctrl_adr             (ddr_wb_adr[1]),
        .wb_ctrl_bte             (ddr_wb_bte[1]),
        .wb_ctrl_cti             (ddr_wb_cti[1]),
        .wb_ctrl_cyc             (ddr_wb_cyc[1]),
        .wb_ctrl_dat_r           (ddr_wb_dat_r[1]),
        .wb_ctrl_dat_w           (ddr_wb_dat_w[1]),
        .wb_ctrl_err             (ddr_wb_err[1]),
        .wb_ctrl_sel             (ddr_wb_sel[1]),
        .wb_ctrl_stb             (ddr_wb_stb[1]),
        .wb_ctrl_we              (ddr_wb_we[1])
    );

    `UNUSED_VAR ({turnoff_requested, j_awaddr_full[31:16], j_araddr_full[31:16]})
    `UNUSED_VAR ({ddr_axi_arcache, ddr_axi_arlock, ddr_axi_arprot, ddr_axi_arqos, ddr_axi_arregion, ddr_axi_aruser, ddr_axi_awcache, ddr_axi_awlock, ddr_axi_awprot, ddr_axi_awqos, ddr_axi_awregion, ddr_axi_awuser, ddr_axi_wuser})
endmodule
