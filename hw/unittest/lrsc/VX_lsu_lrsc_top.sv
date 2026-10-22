`include "VX_define.vh"

module VX_lsu_lrsc_top import VX_gpu_pkg::*; #(
    parameter NUM_LANES = `VX_CFG_NUM_LSU_LANES,
    localparam PID_WIDTH = `LOG2UP(`VX_CFG_NUM_THREADS / NUM_LANES)
) (
    input wire clk,
    input wire reset,
    input wire fire,
    input wire is_lr,
    input wire is_sc,
    input wire [NUM_LANES-1:0] mask,
    input wire [NW_WIDTH-1:0] wid,
    input wire [PID_WIDTH-1:0] pid,
    input wire [NUM_LANES-1:0][63:0] address_words,
    output wire [NUM_LANES-1:0][31:0] hart_words,
    output wire [NUM_LANES-1:0] sc_fail
);
    wire [NUM_LANES-1:0][`VX_CFG_XLEN-1:0] addresses;
    wire [NUM_LANES-1:0][HART_ID_WIDTH-1:0] hart_ids;
    `UNUSED_VAR (address_words)
    for (genvar i = 0; i < NUM_LANES; ++i) begin : g_lane
        assign addresses[i] = `VX_CFG_XLEN'(address_words[i]);
        assign hart_words[i] = 32'(hart_ids[i]);
    end
    VX_lsu_lrsc #(.CORE_ID(1), .NUM_LANES(NUM_LANES)) dut (
        .clk(clk), .reset(reset), .fire(fire), .is_lr(is_lr), .is_sc(is_sc),
        .mask(mask), .wid(wid), .pid(pid), .addr(addresses), .hart_id(hart_ids), .sc_fail(sc_fail)
    );
endmodule
