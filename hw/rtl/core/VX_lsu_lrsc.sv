// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`include "VX_define.vh"

module VX_lsu_lrsc import VX_gpu_pkg::*; #(
    parameter CORE_ID = 0,
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
    input wire [NUM_LANES-1:0][`VX_CFG_XLEN-1:0] addr,
    output wire [NUM_LANES-1:0][HART_ID_WIDTH-1:0] hart_id,
    output wire [NUM_LANES-1:0] sc_fail
);
    `STATIC_ASSERT (`IS_DIVISBLE(`VX_CFG_NUM_THREADS, NUM_LANES), ("Invalid LSU lane geometry"))
    localparam PACKETS = `VX_CFG_NUM_THREADS / NUM_LANES;
    localparam ROWS = `VX_CFG_NUM_WARPS * PACKETS;
    localparam INDEX_WIDTH = `LOG2UP(ROWS);
    wire [INDEX_WIDTH-1:0] index = INDEX_WIDTH'(wid * PACKETS + pid);

    for (genvar i = 0; i < NUM_LANES; ++i) begin : g_lane
        wire [NT_WIDTH-1:0] tid = NT_WIDTH'(pid * NUM_LANES + i);
        reg [ROWS-1:0] reserved;
        reg [ROWS-1:0][`VX_CFG_XLEN-1:0] last_addr;
        assign hart_id[i] = HART_ID_WIDTH'((HART_ID_WIDTH'(CORE_ID) << (NW_BITS + NT_BITS))
                           | (HART_ID_WIDTH'(wid) << NT_BITS) | HART_ID_WIDTH'(tid));
        assign sc_fail[i] = is_sc && (!reserved[index] || last_addr[index] != addr[i]);
        always @(posedge clk) begin
            if (reset) begin
                reserved <= '0;
            end else if (fire && mask[i]) begin
                if (is_lr) begin
                    reserved[index] <= 1'b1;
                    last_addr[index] <= addr[i];
                end else if (is_sc) begin
                    reserved[index] <= 1'b0;
                end
            end
        end
    end
endmodule
