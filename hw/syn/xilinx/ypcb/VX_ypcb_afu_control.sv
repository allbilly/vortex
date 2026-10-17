// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

module VX_ypcb_afu_control (
    input wire clk,
    input wire reset,
    input wire ready,
    input wire s_awvalid,
    output wire s_awready,
    input wire [15:0] s_awaddr,
    input wire s_wvalid,
    output wire s_wready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    output wire s_bvalid,
    input wire s_bready,
    output wire [1:0] s_bresp,
    input wire s_arvalid,
    output wire s_arready,
    input wire [15:0] s_araddr,
    output wire s_rvalid,
    input wire s_rready,
    output wire [31:0] s_rdata,
    output wire [1:0] s_rresp,

    output wire m_awvalid,
    input wire m_awready,
    output wire [15:0] m_awaddr,
    output wire m_wvalid,
    input wire m_wready,
    output wire [31:0] m_wdata,
    output wire [3:0] m_wstrb,
    input wire m_bvalid,
    output wire m_bready,
    input wire [1:0] m_bresp,
    output wire m_arvalid,
    input wire m_arready,
    output wire [15:0] m_araddr,
    input wire m_rvalid,
    output wire m_rready,
    input wire [31:0] m_rdata,
    input wire [1:0] m_rresp
);
    typedef enum logic [1:0] {COLLECT, SEND, WAIT_RESPONSE, RESPOND} state_t;
    state_t write_state, read_state;
    reg aw_pending, w_pending, aw_sent, w_sent;
    reg [15:0] write_address, read_address;
    reg [31:0] write_data, read_data;
    reg [3:0] write_strobe;
    reg [1:0] write_response, read_response;

    assign s_awready = write_state == COLLECT && !aw_pending;
    assign s_wready = write_state == COLLECT && !w_pending;
    assign s_bvalid = write_state == RESPOND;
    assign s_bresp = write_response;
    assign s_arready = read_state == COLLECT;
    assign s_rvalid = read_state == RESPOND;
    assign s_rdata = read_data;
    assign s_rresp = read_response;
    assign m_awvalid = write_state == SEND && ready && !aw_sent;
    assign m_awaddr = write_address;
    assign m_wvalid = write_state == SEND && ready && !w_sent;
    assign m_wdata = write_data;
    assign m_wstrb = write_strobe;
    assign m_bready = write_state == WAIT_RESPONSE && ready;
    assign m_arvalid = read_state == SEND && ready;
    assign m_araddr = read_address;
    assign m_rready = read_state == WAIT_RESPONSE && ready;

    always @(posedge clk) begin
        if (reset) begin
            write_state <= COLLECT;
            read_state <= COLLECT;
            aw_pending <= 0;
            w_pending <= 0;
            aw_sent <= 0;
            w_sent <= 0;
            write_address <= 0;
            read_address <= 0;
            write_data <= 0;
            write_strobe <= 0;
            read_data <= 0;
            write_response <= 0;
            read_response <= 0;
        end else begin
            if (s_awvalid && s_awready) begin
                aw_pending <= 1;
                write_address <= s_awaddr;
            end
            if (s_wvalid && s_wready) begin
                w_pending <= 1;
                write_data <= s_wdata;
                write_strobe <= s_wstrb;
            end
            case (write_state)
                COLLECT: begin
                    if (aw_pending && w_pending) begin
                        aw_pending <= 0;
                        w_pending <= 0;
                        aw_sent <= 0;
                        w_sent <= 0;
                        write_response <= 2'b10;
                        write_state <= ready ? SEND : RESPOND;
                    end
                end
                SEND: begin
                    if (!ready) begin
                        write_state <= RESPOND;
                    end else begin
                        if (m_awvalid && m_awready) begin
                            aw_sent <= 1;
                        end
                        if (m_wvalid && m_wready) begin
                            w_sent <= 1;
                        end
                        if ((aw_sent || m_awready) && (w_sent || m_wready)) begin
                            write_state <= WAIT_RESPONSE;
                        end
                    end
                end
                WAIT_RESPONSE: begin
                    // Readiness loss also resets the AFU, discarding its partial request.
                    if (!ready) begin
                        write_state <= RESPOND;
                    end else if (m_bvalid) begin
                        write_response <= m_bresp;
                        write_state <= RESPOND;
                    end
                end
                RESPOND: begin
                    if (s_bready) begin
                        write_state <= COLLECT;
                    end
                end
            endcase
            case (read_state)
                COLLECT: begin
                    if (s_arvalid && s_arready) begin
                        read_address <= s_araddr;
                        read_data <= 0;
                        read_response <= 2'b10;
                        read_state <= ready ? SEND : RESPOND;
                    end
                end
                SEND: begin
                    if (!ready) begin
                        read_state <= RESPOND;
                    end else if (m_arready) begin
                        read_state <= WAIT_RESPONSE;
                    end
                end
                WAIT_RESPONSE: begin
                    if (!ready) begin
                        read_state <= RESPOND;
                    end else if (m_rvalid) begin
                        read_data <= m_rdata;
                        read_response <= m_rresp;
                        read_state <= RESPOND;
                    end
                end
                RESPOND: begin
                    if (s_rready) begin
                        read_state <= COLLECT;
                    end
                end
            endcase
        end
    end
endmodule
