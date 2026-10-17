// Copyright © 2019-2023
// Licensed under the Apache License, Version 2.0.

`include "VX_define.vh"

// ============================================================================
// VX_cp_dma — dual-port burst DMA engine for CMD_MEM_WRITE / CMD_MEM_READ /
// CMD_MEM_COPY. Owned by the DMA resource arbiter.
//
// Command encoding:
//   arg0 = dst address
//   arg1 = src address
//   arg2 = transfer size in bytes
//
// Dual port: XRT pins each kernel AXI master to exactly one memory resource
// (an HBM/DDR bank or HOST[0]), so the CP carries two masters — axi_host for
// host memory (the command ring lives there and it is one end of every
// upload/download) and axi_dev for device memory. The opcode selects the
// read-source and write-destination port:
//   CMD_MEM_WRITE : src = host,   dst = device   (upload)
//   CMD_MEM_READ  : src = device, dst = host     (download)
//   CMD_MEM_COPY  : src = device, dst = device   (device-local copy)
//
// Transfers are streamed in <=4 KB chunks; each chunk is one AXI INCR burst
// (up to MAX_BURST 512-bit beats) so no burst crosses a 4 KB address
// boundary. A chunk is read fully into buf_r, then written out — sequential,
// not pipelined.
//
// FSM:
//   S_IDLE   : grant -> latch op/dst/src/size                 -> S_SETUP
//   S_SETUP  : size 0 -> S_DONE; else size the chunk          -> S_REQ_AR
//   S_REQ_AR : drive AR on the read port; arready             -> S_READ
//   S_READ   : capture rdata beats into buf_r; last beat      -> S_REQ_AW
//   S_REQ_AW : drive AW on the write port; awready            -> S_WRITE
//   S_WRITE  : drive W beats from buf_r; last beat            -> S_WAIT_B
//   S_WAIT_B : bvalid -> host-direction: validate the chunk   -> S_FLUSH_AR
//              device-direction: advance chunk                -> S_SETUP
//   S_FLUSH_AR/S_FLUSH_R : host-direction only -- read back the last line of
//              the chunk just written and COMPARE it against the copy still
//              held in buf_r; mismatch re-issues the read     -> S_SETUP
//   S_DONE   : pulse `done` for one cycle                     -> S_IDLE
//
// WHY THE VALIDATING FLUSH EXISTS. On the V80's HBM host path, a write's
// BRESP does not mean the data is visible to another master: the response
// can be issued upstream of the memory controller while the beats are still
// in flight, and the host's QDMA reads (a different master, and the CP's
// completion writer a different AXI ID) have no ordering against them. The
// only proof of commitment is a read of the written address RETURNING THE
// WRITTEN DATA: HBM serializes per address, so a matching read-back means
// the write reached the controller, and every earlier write on this ID to
// the same destination is ordered before it. Each chunk lives inside one
// 4 KB page (see beats_to_4k), so its beats share one destination and the
// chunk's last line vouches for the whole chunk. A stale read-back simply
// retries -- the write is in flight and lands within microseconds. Only
// after every chunk has validated does `done` (and therefore the retire the
// host polls, and the completion line that follows it) fire.
// Device-direction writes don't need this: nothing reads them through a
// foreign port on the strength of Q_SEQNUM alone.
// ============================================================================

module VX_cp_dma
  import VX_cp_pkg::*;
#(
  parameter int ID_W = VX_CP_AXI_TID_WIDTH_C,
  parameter logic [ID_W-1:0] TID_PREFIX = '0
)(
  input  wire                       clk,
  input  wire                       reset,

  input  wire                       grant,
  input  cmd_t                      cmd,
  output logic                      done,

  // Host-memory AXI master (command-ring side / upload source / download dst).
  VX_mem_axi_if.master             axi_host,
  // Device-memory AXI master.
  VX_mem_axi_if.master             axi_dev
);

  localparam int MAX_BURST = 64;          // 64 x 64 B = 4 KB max per burst
  localparam int BIDX_W    = 6;           // beat index 0..63
  localparam int BCNT_W    = 7;           // chunk length 1..64

  typedef enum logic [3:0] {
    S_IDLE, S_SETUP, S_REQ_AR, S_READ, S_REQ_AW, S_WRITE, S_WAIT_B,
    S_FLUSH_AR, S_FLUSH_R, S_DONE
  } state_e;

  state_e               state;
  logic [7:0]           op_r;             // latched opcode (host/dev routing)
  logic [63:0]          dst_r, src_r;
  logic [63:0]          rem_bytes;
  logic [12:0]          chunk_bytes;
  logic [BCNT_W-1:0]    read_beats, write_beats;
  logic [5:0]           src_offset, dst_offset;
  logic [BIDX_W-1:0]    beat_idx;
  logic [CL_BITS-1:0]   buf_r [MAX_BURST];

  logic [12:0] next_chunk;
  always_comb begin
    logic [11:0] page_offset;
    logic [12:0] limit_bytes;
    page_offset = (src_r[11:0] > dst_r[11:0]) ? src_r[11:0] : dst_r[11:0];
    limit_bytes = 13'd4096 - {1'b0, page_offset};
    if (rem_bytes < 64'(limit_bytes)) begin
      next_chunk = 13'(rem_bytes);
    end else begin
      next_chunk = limit_bytes;
    end
  end

  // Read-source / write-destination port selection from the latched opcode.
  wire rd_from_host = (cp_opcode_e'(op_r) == CMD_MEM_WRITE);  // upload: read host
  wire wr_to_host   = (cp_opcode_e'(op_r) == CMD_MEM_READ);   // download: write host

  wire last_read_beat = (BCNT_W'({1'b0, beat_idx}) == (read_beats - BCNT_W'(1)));
  wire last_write_beat = (BCNT_W'({1'b0, beat_idx}) == (write_beats - BCNT_W'(1)));

  wire [12:0] source_byte = {1'b0, beat_idx, 6'b0} + 13'(src_offset) - 13'(dst_offset);
  wire [BCNT_W-1:0] lower_index = {1'b0, source_byte[11:6]};
  wire [BCNT_W-1:0] upper_index = source_byte[12] ? '0 : lower_index + BCNT_W'(1);
  wire [CL_BITS-1:0] lower_data = (!source_byte[12] && lower_index < read_beats)
      ? buf_r[BIDX_W'(lower_index)] : '0;
  wire [CL_BITS-1:0] upper_data = (upper_index < read_beats)
      ? buf_r[BIDX_W'(upper_index)] : '0;
  wire [CL_BITS-1:0] write_data = CL_BITS'({upper_data, lower_data} >> {source_byte[5:0], 3'b0});
  wire [CL_BYTES-1:0] write_strobe;
  for (genvar lane = 0; lane < CL_BYTES; ++lane) begin : g_write_strobe
    wire [12:0] byte_index = {1'b0, beat_idx, 6'b0} + 13'(lane);
    assign write_strobe[lane] = byte_index >= 13'(dst_offset)
                            && byte_index < (13'(dst_offset) + chunk_bytes);
  end
  wire [CL_BITS-1:0] flush_mask;
  for (genvar lane = 0; lane < CL_BYTES; ++lane) begin : g_flush_mask
    assign flush_mask[lane * 8 +: 8] = {8{write_strobe[lane]}};
  end

  // ---- Logical read channel ----
  wire               rd_arvalid = (state == S_REQ_AR);
  wire               rd_rready  = (state == S_READ);
  wire               rd_arready = rd_from_host ? axi_host.arready : axi_dev.arready;
  wire               rd_rvalid  = rd_from_host ? axi_host.rvalid  : axi_dev.rvalid;
  wire [CL_BITS-1:0] rd_rdata   = rd_from_host ? axi_host.rdata   : axi_dev.rdata;

  // ---- Logical write channel ----
  wire               wr_awvalid = (state == S_REQ_AW);
  wire               wr_wvalid  = (state == S_WRITE);
  wire               wr_bready  = (state == S_WAIT_B);
  wire               wr_awready = wr_to_host ? axi_host.awready : axi_dev.awready;
  wire               wr_wready  = wr_to_host ? axi_host.wready  : axi_dev.wready;
  wire               wr_bvalid  = wr_to_host ? axi_host.bvalid  : axi_dev.bvalid;

  // ---- FSM ----
  always_ff @(posedge clk) begin
    if (reset) begin
      state       <= S_IDLE;
      op_r        <= '0;
      dst_r       <= '0;
      src_r       <= '0;
      rem_bytes   <= '0;
      chunk_bytes <= '0;
      read_beats  <= '0;
      write_beats <= '0;
      src_offset  <= '0;
      dst_offset  <= '0;
      beat_idx    <= '0;
    end else begin
      case (state)
        S_IDLE: begin
          if (grant) begin
            op_r      <= cmd.hdr.opcode;
            dst_r     <= cmd.arg0;
            src_r     <= cmd.arg1;
            rem_bytes <= cmd.arg2;
            state     <= S_SETUP;
          end
        end
        S_SETUP: begin
          if (rem_bytes == 64'd0) begin
            // Every host-direction chunk validated inline (S_WAIT_B ->
            // S_FLUSH_*), so nothing is left to prove here.
            state <= S_DONE;
          end else begin
            chunk_bytes <= next_chunk;
            read_beats <= BCNT_W'((13'(src_r[5:0]) + next_chunk + 13'd63) >> 6);
            write_beats <= BCNT_W'((13'(dst_r[5:0]) + next_chunk + 13'd63) >> 6);
            src_offset <= src_r[5:0];
            dst_offset <= dst_r[5:0];
            beat_idx    <= '0;
            state       <= S_REQ_AR;
          end
        end
        S_REQ_AR: begin
          if (rd_arvalid && rd_arready) begin
            beat_idx <= '0;
            state    <= S_READ;
          end
        end
        S_READ: begin
          if (rd_rvalid && rd_rready) begin
            buf_r[beat_idx] <= rd_rdata;
            if (last_read_beat) begin
              beat_idx <= '0;
              state    <= S_REQ_AW;
            end else begin
              beat_idx <= beat_idx + BIDX_W'(1);
            end
          end
        end
        S_REQ_AW: begin
          if (wr_awvalid && wr_awready) begin
            beat_idx <= '0;
            state    <= S_WRITE;
          end
        end
        S_WRITE: begin
          if (wr_wvalid && wr_wready) begin
            if (last_write_beat) begin
              state <= S_WAIT_B;
            end else begin
              beat_idx <= beat_idx + BIDX_W'(1);
            end
          end
        end
        S_WAIT_B: begin
          if (wr_bvalid && wr_bready) begin
            src_r     <= src_r + 64'(chunk_bytes);
            dst_r     <= dst_r + 64'(chunk_bytes);
            rem_bytes <= rem_bytes - 64'(chunk_bytes);
            // Host-direction: prove this chunk committed before moving on.
            // The saved offsets keep the last write's data/mask stable after
            // the logical byte addresses advance.
            state     <= wr_to_host ? S_FLUSH_AR : S_SETUP;
          end
        end
        S_FLUSH_AR: begin
          if (axi_host.arvalid && axi_host.arready) begin
            state <= S_FLUSH_R;
          end
        end
        S_FLUSH_R: begin
          if (axi_host.rvalid && axi_host.rready) begin
            // Validate: the read-back must equal the line still held in
            // buf_r. Stale data means the write has not reached the memory
            // controller yet -- re-issue the read until it has.
            state <= (((axi_host.rdata ^ write_data) & flush_mask) == '0)
                       ? S_SETUP : S_FLUSH_AR;
          end
        end
        S_DONE: begin
          state <= S_IDLE;
        end
        default: state <= S_IDLE;
      endcase
    end
  end

  wire [7:0] read_burst_len = 8'(read_beats - BCNT_W'(1));
  wire [7:0] write_burst_len = 8'(write_beats - BCNT_W'(1));
  wire [63:0] flush_address = (dst_r - 64'd1) & ~64'd63;

  // The read-ready decode drives the clock enable of every bit of the stream
  // buffer feeding this engine -- 264 enables that the placer spreads well
  // away from this FSM. At 300 MHz that path is the design's critical one:
  // three logic levels carrying 0.267ns of logic behind 2.008ns of route.
  // Replicating the decode lets each copy enable a nearby group. Logically
  // identical to inlining these expressions; affects implementation only.
  (* MAX_FANOUT = 32 *) wire host_rready = (rd_rready & rd_from_host) || (state == S_FLUSH_R);
  (* MAX_FANOUT = 32 *) wire dev_rready  = rd_rready & ~rd_from_host;

  // ---- Drive both AXI masters; only the routed port asserts valid ----
  always_comb begin
    // ----- axi_host -----
    axi_host.arvalid = (rd_arvalid & rd_from_host) || (state == S_FLUSH_AR);
    axi_host.araddr  = (state == S_FLUSH_AR) ? flush_address : {src_r[63:6], 6'b0};
    axi_host.arid    = TID_PREFIX;
    axi_host.arlen   = (state == S_FLUSH_AR) ? 8'd0 : read_burst_len;
    axi_host.arsize  = 3'd6;                 // 64 bytes per beat
    axi_host.arburst = 2'b01;                // INCR
    axi_host.rready  = host_rready;

    axi_host.awvalid = wr_awvalid &  wr_to_host;
    axi_host.awaddr  = {dst_r[63:6], 6'b0};
    axi_host.awid    = TID_PREFIX;
    axi_host.awlen   = write_burst_len;
    axi_host.awsize  = 3'd6;
    axi_host.awburst = 2'b01;
    axi_host.wvalid  = wr_wvalid  &  wr_to_host;
    axi_host.wdata   = write_data;
    axi_host.wstrb   = write_strobe;
    axi_host.wlast   = last_write_beat;
    axi_host.bready  = wr_bready  &  wr_to_host;

    // ----- axi_dev -----
    axi_dev.arvalid  = rd_arvalid & ~rd_from_host;
    axi_dev.araddr   = {src_r[63:6], 6'b0};
    axi_dev.arid     = TID_PREFIX;
    axi_dev.arlen    = read_burst_len;
    axi_dev.arsize   = 3'd6;
    axi_dev.arburst  = 2'b01;
    axi_dev.rready   = dev_rready;

    axi_dev.awvalid  = wr_awvalid & ~wr_to_host;
    axi_dev.awaddr   = {dst_r[63:6], 6'b0};
    axi_dev.awid     = TID_PREFIX;
    axi_dev.awlen    = write_burst_len;
    axi_dev.awsize   = 3'd6;
    axi_dev.awburst  = 2'b01;
    axi_dev.wvalid   = wr_wvalid  & ~wr_to_host;
    axi_dev.wdata    = write_data;
    axi_dev.wstrb    = write_strobe;
    axi_dev.wlast    = last_write_beat;
    axi_dev.bready   = wr_bready  & ~wr_to_host;

    done = (state == S_DONE);
  end

  // Sanity / unused.
  `UNUSED_VAR (cmd.hdr.flags)
  `UNUSED_VAR (cmd.hdr.reserved)
  `UNUSED_VAR (cmd.profile_slot)
  `UNUSED_VAR (axi_host.bid)
  `UNUSED_VAR (axi_host.bresp)
  `UNUSED_VAR (axi_host.rid)
  `UNUSED_VAR (axi_host.rlast)
  `UNUSED_VAR (axi_host.rresp)
  `UNUSED_VAR (axi_dev.bid)
  `UNUSED_VAR (axi_dev.bresp)
  `UNUSED_VAR (axi_dev.rid)
  `UNUSED_VAR (axi_dev.rlast)
  `UNUSED_VAR (axi_dev.rresp)

endmodule : VX_cp_dma
