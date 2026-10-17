// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`timescale 1ns/1ps
module VX_ypcb_control (
    input wire clk,
    input wire reset,

    input wire s_awvalid,
    output reg s_awready,
    input wire [15:0] s_awaddr,
    input wire s_wvalid,
    output reg s_wready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    output reg s_bvalid,
    input wire s_bready,
    output reg [1:0] s_bresp,
    input wire s_arvalid,
    output reg s_arready,
    input wire [15:0] s_araddr,
    output reg s_rvalid,
    input wire s_rready,
    output reg [31:0] s_rdata,
    output reg [1:0] s_rresp,

    output reg [4:0] m_awvalid,
    input wire [4:0] m_awready,
    output wire [4:0][15:0] m_awaddr,
    output reg [4:0] m_wvalid,
    input wire [4:0] m_wready,
    output wire [4:0][31:0] m_wdata,
    output wire [4:0][3:0] m_wstrb,
    input wire [4:0] m_bvalid,
    output reg [4:0] m_bready,
    input wire [4:0][1:0] m_bresp,
    output reg [4:0] m_arvalid,
    input wire [4:0] m_arready,
    output wire [4:0][15:0] m_araddr,
    input wire [4:0] m_rvalid,
    output reg [4:0] m_rready,
    input wire [4:0][31:0] m_rdata,
    input wire [4:0][1:0] m_rresp
);
    typedef enum logic [1:0] {COLLECT, SEND, WAIT_TARGET, RESPOND} state_t;
    state_t write_state, read_state;
    reg aw_pending, w_pending;
    reg [15:0] write_address;
    reg [31:0] write_data;
    reg [3:0] write_strobe;
    reg [2:0] write_route, read_route;
    reg [15:0] target_write_address, target_read_address;
    reg [31:0] target_write_data;
    reg [3:0] target_write_strobe;
    assign m_awaddr = {5{target_write_address}};
    assign m_wdata = {5{target_write_data}};
    assign m_wstrb = {5{target_write_strobe}};
    assign m_araddr = {5{target_read_address}};

    function automatic [2:0] decode(input [3:0] window, input word_aligned);
        if (window[3] || !word_aligned) begin
            decode = 3'd7;
        end else if (window[2]) begin
            decode = window[1] ? 3'd4 : 3'd3;
        end else if (!window[1]) begin
            decode = 3'd0;
        end else begin
            decode = window[0] ? 3'd2 : 3'd1;
        end
    endfunction

    function automatic [15:0] local_address(input [14:0] address);
        if (address[14] || !address[13]) begin
            local_address = {3'b0, address[12:0]};
        end else begin
            local_address = {4'b0, address[11:0]};
        end
    endfunction

    wire write_launch = write_state == COLLECT && aw_pending && w_pending
        && decode(write_address[15:12], write_address[1:0] == 0) != 3'd7;
    wire read_launch = read_state == COLLECT && s_arvalid && s_arready
        && decode(s_araddr[15:12], s_araddr[1:0] == 0) != 3'd7;

    always @(posedge clk) begin
        if (reset) begin
            target_write_address <= '0;
            target_write_data <= '0;
            target_write_strobe <= '0;
            target_read_address <= '0;
        end else begin
            if (write_launch) begin
                target_write_address <= local_address(write_address[14:0]);
                target_write_data <= write_data;
                target_write_strobe <= write_strobe;
            end
            if (read_launch) begin
                target_read_address <= local_address(s_araddr[14:0]);
            end
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            write_state <= COLLECT;
            read_state <= COLLECT;
            aw_pending <= 0;
            w_pending <= 0;
            write_address <= '0;
            write_data <= '0;
            write_strobe <= '0;
            write_route <= '0;
            read_route <= '0;
            s_awready <= 1;
            s_wready <= 1;
            s_bvalid <= 0;
            s_bresp <= '0;
            s_arready <= 1;
            s_rvalid <= 0;
            s_rdata <= '0;
            s_rresp <= '0;
            m_awvalid <= '0;
            m_wvalid <= '0;
            m_bready <= '0;
            m_arvalid <= '0;
            m_rready <= '0;
        end else begin
            if (s_awvalid && s_awready) begin
                aw_pending <= 1;
                write_address <= s_awaddr;
                s_awready <= 0;
            end
            if (s_wvalid && s_wready) begin
                w_pending <= 1;
                write_data <= s_wdata;
                write_strobe <= s_wstrb;
                s_wready <= 0;
            end
            case (write_state)
                COLLECT: begin
                    if (aw_pending && w_pending) begin
                        aw_pending <= 0;
                        w_pending <= 0;
                        write_route <= decode(write_address[15:12], write_address[1:0] == 0);
                        if (decode(write_address[15:12], write_address[1:0] == 0) == 3'd7) begin
                            s_bvalid <= 1;
                            s_bresp <= 2'b11;
                            write_state <= RESPOND;
                        end else begin
                            m_awvalid <= 5'b00001 << decode(write_address[15:12], write_address[1:0] == 0);
                            m_wvalid <= 5'b00001 << decode(write_address[15:12], write_address[1:0] == 0);
                            write_state <= SEND;
                        end
                    end
                end
                SEND: begin
                    m_awvalid <= m_awvalid & ~m_awready;
                    m_wvalid <= m_wvalid & ~m_wready;
                    if (!(|(m_awvalid & ~m_awready)) && !(|(m_wvalid & ~m_wready))) begin
                        m_bready <= 5'b00001 << write_route;
                        write_state <= WAIT_TARGET;
                    end
                end
                WAIT_TARGET: begin
                    if (|(m_bvalid & m_bready)) begin
                        s_bvalid <= 1;
                        s_bresp <= m_bresp[write_route];
                        m_bready <= '0;
                        write_state <= RESPOND;
                    end
                end
                RESPOND: begin
                    if (s_bready) begin
                        s_bvalid <= 0;
                        s_awready <= 1;
                        s_wready <= 1;
                        write_state <= COLLECT;
                    end
                end
            endcase
            case (read_state)
                COLLECT: begin
                    if (s_arvalid && s_arready) begin
                        s_arready <= 0;
                        read_route <= decode(s_araddr[15:12], s_araddr[1:0] == 0);
                        if (decode(s_araddr[15:12], s_araddr[1:0] == 0) == 3'd7) begin
                            s_rvalid <= 1;
                            s_rresp <= 2'b11;
                            s_rdata <= '0;
                            read_state <= RESPOND;
                        end else begin
                            m_arvalid <= 5'b00001 << decode(s_araddr[15:12], s_araddr[1:0] == 0);
                            read_state <= SEND;
                        end
                    end
                end
                SEND: begin
                    m_arvalid <= m_arvalid & ~m_arready;
                    if (!(|(m_arvalid & ~m_arready))) begin
                        m_rready <= 5'b00001 << read_route;
                        read_state <= WAIT_TARGET;
                    end
                end
                WAIT_TARGET: begin
                    if (|(m_rvalid & m_rready)) begin
                        s_rvalid <= 1;
                        s_rresp <= m_rresp[read_route];
                        s_rdata <= m_rdata[read_route];
                        m_rready <= '0;
                        read_state <= RESPOND;
                    end
                end
                RESPOND: begin
                    if (s_rready) begin
                        s_rvalid <= 0;
                        s_arready <= 1;
                        read_state <= COLLECT;
                    end
                end
            endcase
        end
    end
endmodule
