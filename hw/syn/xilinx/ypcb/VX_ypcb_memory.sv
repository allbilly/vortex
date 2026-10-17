`include "VX_platform.vh"

module VX_ypcb_memory #(
    parameter NUM_INPUTS = 4,
    parameter ID_WIDTH = 32
) (
    input wire clk,
    input wire reset,
    output wire busy,

    input wire [NUM_INPUTS-1:0] s_awvalid,
    output wire [NUM_INPUTS-1:0] s_awready,
    input wire [NUM_INPUTS-1:0][63:0] s_awaddr,
    input wire [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_awid,
    input wire [NUM_INPUTS-1:0][7:0] s_awlen,
    input wire [NUM_INPUTS-1:0] s_wvalid,
    output wire [NUM_INPUTS-1:0] s_wready,
    input wire [NUM_INPUTS-1:0][511:0] s_wdata,
    input wire [NUM_INPUTS-1:0][63:0] s_wstrb,
    input wire [NUM_INPUTS-1:0] s_wlast,
    output wire [NUM_INPUTS-1:0] s_bvalid,
    input wire [NUM_INPUTS-1:0] s_bready,
    output wire [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_bid,
    output wire [NUM_INPUTS-1:0][1:0] s_bresp,

    input wire [NUM_INPUTS-1:0] s_arvalid,
    output wire [NUM_INPUTS-1:0] s_arready,
    input wire [NUM_INPUTS-1:0][63:0] s_araddr,
    input wire [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_arid,
    input wire [NUM_INPUTS-1:0][7:0] s_arlen,
    output wire [NUM_INPUTS-1:0] s_rvalid,
    input wire [NUM_INPUTS-1:0] s_rready,
    output wire [NUM_INPUTS-1:0][511:0] s_rdata,
    output wire [NUM_INPUTS-1:0] s_rlast,
    output wire [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_rid,
    output wire [NUM_INPUTS-1:0][1:0] s_rresp,

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
    input wire [1:0][1:0] m_rresp
);
    wire c_awvalid, c_awready, c_wvalid, c_wready, c_wlast;
    wire [63:0] c_awaddr, c_wstrb;
    wire [ID_WIDTH-1:0] c_awid, c_bid;
    wire [7:0] c_awlen;
    wire [511:0] c_wdata;
    wire c_bvalid, c_bready;
    wire [1:0] c_bresp;
    wire c_arvalid, c_arready, c_rvalid, c_rready, c_rlast;
    wire [63:0] c_araddr;
    wire [ID_WIDTH-1:0] c_arid, c_rid;
    wire [7:0] c_arlen;
    wire [511:0] c_rdata;
    wire [1:0] c_rresp;

    VX_mm_axi_arb #(
        .NUM_INPUTS (NUM_INPUTS),
        .ADDR_WIDTH (64),
        .DATA_WIDTH (512),
        .ID_WIDTH (ID_WIDTH),
        .ARBITER ("R")
    ) arb (
        .clk (clk), .reset (reset),
        .s_awvalid (s_awvalid), .s_awready (s_awready),
        .s_awaddr (s_awaddr), .s_awid (s_awid), .s_awlen (s_awlen),
        .s_wvalid (s_wvalid), .s_wready (s_wready),
        .s_wdata (s_wdata), .s_wstrb (s_wstrb), .s_wlast (s_wlast),
        .s_bvalid (s_bvalid), .s_bready (s_bready),
        .s_bid (s_bid), .s_bresp (s_bresp),
        .s_arvalid (s_arvalid), .s_arready (s_arready),
        .s_araddr (s_araddr), .s_arid (s_arid), .s_arlen (s_arlen),
        .s_rvalid (s_rvalid), .s_rready (s_rready), .s_rdata (s_rdata),
        .s_rlast (s_rlast), .s_rid (s_rid), .s_rresp (s_rresp),
        .m_awvalid (c_awvalid), .m_awready (c_awready),
        .m_awaddr (c_awaddr), .m_awid (c_awid), .m_awlen (c_awlen),
        .m_wvalid (c_wvalid), .m_wready (c_wready),
        .m_wdata (c_wdata), .m_wstrb (c_wstrb), .m_wlast (c_wlast),
        .m_bvalid (c_bvalid), .m_bready (c_bready),
        .m_bid (c_bid), .m_bresp (c_bresp),
        .m_arvalid (c_arvalid), .m_arready (c_arready),
        .m_araddr (c_araddr), .m_arid (c_arid), .m_arlen (c_arlen),
        .m_rvalid (c_rvalid), .m_rready (c_rready), .m_rdata (c_rdata),
        .m_rlast (c_rlast), .m_rid (c_rid), .m_rresp (c_rresp)
    );

    function automatic burst_valid(input [11:0] offset, input [7:0] len);
        // Both controllers use full 64-byte beats and AXI's 4 KiB burst limit.
        burst_valid = offset[5:0] == 0
                   && ({3'b0, offset[11:6]} + {1'b0, len}) < 9'd64;
    endfunction

    reg wr_active, wr_bank, wr_error, wr_done;
    reg [ID_WIDTH-1:0] wr_id;
    reg rd_active, rd_bank, rd_error;
    reg [ID_WIDTH-1:0] rd_id;
    reg [7:0] rd_remaining;
    assign busy = wr_active || rd_active || (|s_awvalid) || (|s_wvalid) || (|s_arvalid);
    wire aw_ok = c_awaddr[63:32] == 0 && burst_valid(c_awaddr[11:0], c_awlen);
    wire ar_ok = c_araddr[63:32] == 0 && burst_valid(c_araddr[11:0], c_arlen);

    assign c_awready = !wr_active && (!aw_ok || m_awready[c_awaddr[31]]);
    assign c_wready = wr_active && !wr_done && (wr_error || m_wready[wr_bank]);
    assign c_bvalid = wr_active && (wr_error ? wr_done : m_bvalid[wr_bank]);
    assign c_bid = wr_id;
    assign c_bresp = wr_error ? 2'b11 : m_bresp[wr_bank];

    assign c_arready = !rd_active && (!ar_ok || m_arready[c_araddr[31]]);
    assign c_rvalid = rd_active && (rd_error || m_rvalid[rd_bank]);
    assign c_rdata = rd_error ? '0 : m_rdata[rd_bank];
    assign c_rid = rd_id;
    assign c_rlast = rd_error ? rd_remaining == 0 : m_rlast[rd_bank];
    assign c_rresp = rd_error ? 2'b11 : m_rresp[rd_bank];

    // Serialization retains the original ID while each DDR core sees ID zero.
    for (genvar bank = 0; bank < 2; ++bank) begin : g_ddr
        assign m_awvalid[bank] = c_awvalid && !wr_active && aw_ok && c_awaddr[31] == 1'(bank);
        assign m_awaddr[bank] = c_awaddr[30:0];
        assign m_awid[bank] = '0;
        assign m_awlen[bank] = c_awlen;
        assign m_wvalid[bank] = c_wvalid && wr_active && !wr_done && !wr_error && wr_bank == 1'(bank);
        assign m_wdata[bank] = c_wdata;
        assign m_wstrb[bank] = c_wstrb;
        assign m_wlast[bank] = c_wlast;
        assign m_bready[bank] = c_bready && wr_active && !wr_error && wr_bank == 1'(bank);
        assign m_arvalid[bank] = c_arvalid && !rd_active && ar_ok && c_araddr[31] == 1'(bank);
        assign m_araddr[bank] = c_araddr[30:0];
        assign m_arid[bank] = '0;
        assign m_arlen[bank] = c_arlen;
        assign m_rready[bank] = c_rready && rd_active && !rd_error && rd_bank == 1'(bank);
    end
    `UNUSED_VAR (m_bid)
    `UNUSED_VAR (m_rid)

    always @(posedge clk) begin
        if (reset) begin
            wr_active <= 0;
            wr_bank <= 0;
            wr_error <= 0;
            wr_done <= 0;
            wr_id <= '0;
            rd_active <= 0;
            rd_bank <= 0;
            rd_error <= 0;
            rd_id <= '0;
            rd_remaining <= '0;
        end else begin
            if (c_awvalid && c_awready) begin
                wr_active <= 1;
                wr_bank <= c_awaddr[31];
                wr_error <= !aw_ok;
                wr_done <= 0;
                wr_id <= c_awid;
            end
            if (c_wvalid && c_wready && c_wlast) begin
                wr_done <= 1;
            end
            if (c_bvalid && c_bready) begin
                wr_active <= 0;
            end
            if (c_arvalid && c_arready) begin
                rd_active <= 1;
                rd_bank <= c_araddr[31];
                rd_error <= !ar_ok;
                rd_id <= c_arid;
                rd_remaining <= c_arlen;
            end
            if (c_rvalid && c_rready) begin
                rd_remaining <= rd_remaining - 8'd1;
                if (c_rlast) begin
                    rd_active <= 0;
                end
            end
        end
    end
endmodule
