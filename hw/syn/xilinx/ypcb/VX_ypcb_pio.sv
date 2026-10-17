// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`include "VX_platform.vh"

module VX_ypcb_pio (
    input wire clk,
    input wire reset,
    input wire [1:0] memory_ready,

    input wire s_awvalid,
    output wire s_awready,
    input wire [11:0] s_awaddr,
    input wire s_wvalid,
    output wire s_wready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    output reg s_bvalid,
    input wire s_bready,
    output reg [1:0] s_bresp,
    input wire s_arvalid,
    output wire s_arready,
    input wire [11:0] s_araddr,
    output reg s_rvalid,
    input wire s_rready,
    output reg [31:0] s_rdata,
    output reg [1:0] s_rresp,

    output wire m_awvalid,
    input wire m_awready,
    output wire [63:0] m_awaddr,
    output wire m_wvalid,
    input wire m_wready,
    output wire [511:0] m_wdata,
    output wire [63:0] m_wstrb,
    output wire m_wlast,
    input wire m_bvalid,
    output wire m_bready,
    input wire [1:0] m_bresp,
    output wire m_arvalid,
    input wire m_arready,
    output wire [63:0] m_araddr,
    input wire m_rvalid,
    output wire m_rready,
    input wire [511:0] m_rdata,
    input wire m_rlast,
    input wire [1:0] m_rresp
);
    typedef enum logic [2:0] {IDLE, WRITE, WRITE_RESP, READ_ADDR, READ_DATA} state_t;
    state_t state;
    reg aw_pending, w_pending;
    reg [11:0] write_address;
    reg [31:0] write_value;
    reg [3:0] write_enable;
    reg [63:0] address, byte_enable;
    reg [511:0] data;
    reg aw_sent, w_sent, done;
    reg [1:0] result;
    wire busy = state != IDLE;
    wire write_fire = aw_pending && w_pending && !s_bvalid;

    assign s_awready = !aw_pending && !s_bvalid;
    assign s_wready = !w_pending && !s_bvalid;
    assign s_arready = !s_rvalid;
    assign m_awvalid = state == WRITE && !aw_sent;
    assign m_awaddr = address;
    assign m_wvalid = state == WRITE && !w_sent;
    assign m_wdata = data;
    assign m_wstrb = byte_enable;
    assign m_wlast = 1'b1;
    assign m_bready = state == WRITE_RESP;
    assign m_arvalid = state == READ_ADDR;
    assign m_araddr = address;
    assign m_rready = state == READ_DATA;

    wire [31:0] register_mask;
    for (genvar byte_idx = 0; byte_idx < 4; ++byte_idx) begin : g_register_mask
        assign register_mask[byte_idx * 8 +: 8] = {8{write_enable[byte_idx]}};
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            aw_pending <= 0;
            w_pending <= 0;
            write_address <= '0;
            write_value <= '0;
            write_enable <= '0;
            address <= '0;
            byte_enable <= '1;
            data <= '0;
            aw_sent <= 0;
            w_sent <= 0;
            done <= 0;
            result <= '0;
            s_bvalid <= 0;
            s_bresp <= '0;
            s_rvalid <= 0;
            s_rdata <= '0;
            s_rresp <= '0;
        end else begin
            if (s_awvalid && s_awready) begin
                aw_pending <= 1;
                write_address <= s_awaddr;
            end
            if (s_wvalid && s_wready) begin
                w_pending <= 1;
                write_value <= s_wdata;
                write_enable <= s_wstrb;
            end
            if (s_bvalid && s_bready) begin
                s_bvalid <= 0;
            end
            if (s_rvalid && s_rready) begin
                s_rvalid <= 0;
            end
            if (write_fire) begin
                aw_pending <= 0;
                w_pending <= 0;
                s_bvalid <= 1;
                s_bresp <= 2'b00;
                if (write_address[1:0] != 0) begin
                    s_bresp <= 2'b11;
                end else if (busy) begin
                    s_bresp <= 2'b10;
                end else begin
                    case (write_address)
                        12'h008: address[31:0] <= (address[31:0] & ~register_mask) | (write_value & register_mask);
                        12'h00c: address[63:32] <= (address[63:32] & ~register_mask) | (write_value & register_mask);
                        12'h018: byte_enable[31:0] <= (byte_enable[31:0] & ~register_mask) | (write_value & register_mask);
                        12'h01c: byte_enable[63:32] <= (byte_enable[63:32] & ~register_mask) | (write_value & register_mask);
                        12'h010: begin
                            if (write_enable[0]) begin
                                if (write_value == 1 || write_value == 2) begin
                                    done <= 0;
                                    result <= 2'b00;
                                    if (address[63:32] != 0 || address[5:0] != 0) begin
                                        done <= 1;
                                        result <= 2'b11;
                                        s_bresp <= 2'b10;
                                    end else if (!memory_ready[address[31]]) begin
                                        done <= 1;
                                        result <= 2'b10;
                                        s_bresp <= 2'b10;
                                    end else begin
                                        aw_sent <= 0;
                                        w_sent <= 0;
                                        state <= write_value == 1 ? READ_ADDR : WRITE;
                                    end
                                end else begin
                                    s_bresp <= 2'b10;
                                end
                            end
                        end
                        default: begin
                            if (write_address >= 12'h100 && write_address < 12'h140) begin
                                for (int word_idx = 0; word_idx < 16; ++word_idx) begin
                                    if (write_address[5:2] == 4'(word_idx)) begin
                                        data[word_idx * 32 +: 32] <= (data[word_idx * 32 +: 32] & ~register_mask)
                                            | (write_value & register_mask);
                                    end
                                end
                            end else begin
                                s_bresp <= 2'b11;
                            end
                        end
                    endcase
                end
            end
            if (s_arvalid && s_arready) begin
                s_rvalid <= 1;
                s_rresp <= 2'b00;
                s_rdata <= '0;
                if (s_araddr[1:0] != 0) begin
                    s_rresp <= 2'b11;
                end else begin
                    case (s_araddr)
                        12'h000: s_rdata <= 32'h56595043;
                        12'h004: s_rdata <= {26'b0, memory_ready, 1'b0, result != 0, done, busy};
                        12'h008: s_rdata <= address[31:0];
                        12'h00c: s_rdata <= address[63:32];
                        12'h010: s_rdata <= '0;
                        12'h014: s_rdata <= {30'b0, result};
                        12'h018: s_rdata <= byte_enable[31:0];
                        12'h01c: s_rdata <= byte_enable[63:32];
                        default: begin
                            if (s_araddr >= 12'h100 && s_araddr < 12'h140) begin
                                s_rdata <= data[s_araddr[5:2] * 32 +: 32];
                            end else begin
                                s_rresp <= 2'b11;
                            end
                        end
                    endcase
                end
            end
            case (state)
                WRITE: begin
                    if (m_awvalid && m_awready) begin
                        aw_sent <= 1;
                    end
                    if (m_wvalid && m_wready) begin
                        w_sent <= 1;
                    end
                    if ((aw_sent || m_awready) && (w_sent || m_wready)) begin
                        state <= WRITE_RESP;
                    end
                end
                WRITE_RESP: begin
                    if (m_bvalid && m_bready) begin
                        done <= 1;
                        result <= m_bresp;
                        state <= IDLE;
                    end
                end
                READ_ADDR: begin
                    if (m_arvalid && m_arready) begin
                        state <= READ_DATA;
                    end
                end
                READ_DATA: begin
                    if (m_rvalid && m_rready) begin
                        data <= m_rdata;
                        done <= 1;
                        result <= m_rlast ? m_rresp : 2'b10;
                        state <= IDLE;
                    end
                end
                default: begin end
            endcase
        end
    end
endmodule
