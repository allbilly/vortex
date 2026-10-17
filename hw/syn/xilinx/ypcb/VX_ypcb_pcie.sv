// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

`include "VX_platform.vh"

module VX_ypcb_pcie (
    input wire clk,
    input wire reset,
    input wire [15:0] completer_id,

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
    output reg [3:0] error_status,
    output wire busy,

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
    typedef enum logic [3:0] {
        HEADER, BODY, EXECUTE, WRITE, WRITE_RESP,
        READ_ADDR, READ_DATA, TX_FIRST, TX_LAST
    } state_t;
    state_t state;
    assign busy = state != HEADER || rx_valid;
    reg [5:0][31:0] packet;
    reg [10:0] word_count;
    reg bar_hit, packet_malformed, packet_corrupt;
    reg aw_sent, w_sent;
    reg [15:0] address;
    reg [31:0] write_data, read_data;
    reg [3:0] byte_enable;
    reg [15:0] request_id, response_id;
    reg [7:0] tag;
    reg [2:0] traffic_class, attributes, completion_status;
    reg [11:0] byte_count;
    reg [6:0] lower_address;
    reg completion_data, completion_locked;

    wire [2:0] format = packet[0][31:29];
    wire [4:0] request_type = packet[0][28:24];
    wire [10:0] length_words = packet[0][9:0] == 0 ? 11'd1024 : {1'b0, packet[0][9:0]};
    wire [10:0] header_words = format[0] ? 11'd4 : 11'd3;
    wire [10:0] expected_words = header_words + (format[1] ? length_words : 11'd0)
        + {10'b0, packet[0][15]};
    wire memory_request = request_type == 0 || request_type == 1;
    wire memory_read = memory_request && !format[1];
    wire nonposted = memory_read || request_type == 2 || request_type == 4
        || request_type == 5 || request_type == 12 || request_type == 13 || request_type == 14;
    wire [31:0] request_address = format[0] ? packet[3] : packet[2];
    wire [3:0] first_enable = packet[1][3:0];
    wire [3:0] last_enable = packet[1][7:4];
    wire [1:0] first_byte = first_enable[0] ? 2'd0 : first_enable[1] ? 2'd1
        : first_enable[2] ? 2'd2 : first_enable[3] ? 2'd3 : 2'd0;
    wire [1:0] last_byte = first_enable[3] ? 2'd3 : first_enable[2] ? 2'd2
        : first_enable[1] ? 2'd1 : 2'd0;
    wire [1:0] final_byte = last_enable[3] ? 2'd3 : last_enable[2] ? 2'd2
        : last_enable[1] ? 2'd1 : 2'd0;
    wire invalid_enables = memory_request && !packet[0][16]
        && (length_words == 1 ? last_enable != 0 : first_enable == 0 || last_enable == 0);
    wire supported = request_type == 0 && length_words == 1 && bar_hit
        && packet[0][17:16] == 0 && packet[0][11:10] == 0
        && request_address[1:0] == 0 && (!format[0] || packet[2] == 0);

    reg [11:0] requested_bytes;
    always @(*) begin
        if (memory_read) begin
            if (length_words == 1) begin
                // Noncontiguous byte enables count the span, including holes.
                requested_bytes = first_enable == 0 ? 12'd1
                    : 12'd1 + {10'b0, last_byte} - {10'b0, first_byte};
            end else begin
                requested_bytes = {length_words[9:0], 2'b0} - 12'd3
                    - {10'b0, first_byte} + {10'b0, final_byte};
            end
        end else if (request_type == 12 || request_type == 13) begin
            requested_bytes = {length_words[9:0], 2'b0};
        end else if (request_type == 14) begin
            requested_bytes = {1'b0, length_words[9:0], 1'b0};
        end else begin
            requested_bytes = 12'd4;
        end
    end

    assign rx_ready = state == HEADER || state == BODY;
    assign m_awvalid = state == WRITE && !aw_sent;
    assign m_awaddr = address;
    assign m_wvalid = state == WRITE && !w_sent;
    assign m_wdata = write_data;
    assign m_wstrb = byte_enable;
    assign m_bready = state == WRITE_RESP;
    assign m_arvalid = state == READ_ADDR;
    assign m_araddr = address;
    assign m_rready = state == READ_DATA;
    assign tx_valid = state == TX_FIRST || state == TX_LAST;
    assign tx_last = state == TX_LAST;
    assign tx_keep = state == TX_FIRST || completion_data ? 8'hff : 8'h0f;
    wire [31:0] completion_dw0 = {completion_data ? 3'b010 : 3'b000,
        completion_locked ? 5'b01011 : 5'b01010, 1'b0, traffic_class,
        1'b0, attributes[2], 4'b0, attributes[1:0], 2'b0, 9'b0, completion_data};
    wire [31:0] completion_dw1 = {response_id, completion_status, 1'b0, byte_count};
    wire [31:0] completion_dw2 = {request_id, tag, 1'b0, lower_address};
    assign tx_data = state == TX_FIRST ? {completion_dw1, completion_dw0}
        : {read_data, completion_dw2};

    always @(posedge clk) begin
        if (reset) begin
            state <= HEADER;
            packet <= '0;
            word_count <= '0;
            bar_hit <= 0;
            packet_malformed <= 0;
            packet_corrupt <= 0;
            aw_sent <= 0;
            w_sent <= 0;
            address <= '0;
            write_data <= '0;
            read_data <= '0;
            byte_enable <= '0;
            request_id <= '0;
            response_id <= '0;
            tag <= '0;
            traffic_class <= '0;
            attributes <= '0;
            completion_status <= '0;
            byte_count <= '0;
            lower_address <= '0;
            completion_data <= 0;
            completion_locked <= 0;
            error_status <= '0;
        end else begin
            case (state)
                HEADER: begin
                    if (rx_valid) begin
                        packet[0] <= rx_data[31:0];
                        packet[1] <= rx_data[63:32];
                        packet[5:2] <= '0;
                        word_count <= rx_keep == 8'hff ? 11'd2 : 11'd1;
                        bar_hit <= rx_user[2];
                        packet_malformed <= rx_keep != 8'hff;
                        packet_corrupt <= |rx_user[1:0];
                        state <= rx_last ? EXECUTE : BODY;
                    end
                end
                BODY: begin
                    if (rx_valid) begin
                        case (word_count)
                            11'd2: packet[3:2] <= rx_data;
                            11'd4: packet[5:4] <= rx_data;
                            default: begin end
                        endcase
                        if (word_count < 11'd2046) begin
                            word_count <= word_count + (rx_keep == 8'hff ? 11'd2 : 11'd1);
                        end else begin
                            packet_malformed <= 1;
                        end
                        if ((rx_keep != 8'hff && rx_keep != 8'h0f) || (!rx_last && rx_keep != 8'hff)) begin
                            packet_malformed <= 1;
                        end
                        packet_corrupt <= packet_corrupt || |rx_user[1:0];
                        if (rx_last) begin
                            state <= EXECUTE;
                        end
                    end
                end
                EXECUTE: begin
                    request_id <= packet[1][31:16];
                    response_id <= completer_id;
                    tag <= packet[1][15:8];
                    traffic_class <= packet[0][22:20];
                    attributes <= {packet[0][18], packet[0][13:12]};
                    byte_count <= requested_bytes;
                    lower_address <= memory_read ? {request_address[6:2], first_byte} : 7'd0;
                    completion_locked <= request_type == 1;
                    completion_status <= 0;
                    completion_data <= 0;
                    read_data <= 0;
                    aw_sent <= 0;
                    w_sent <= 0;
                    address <= {request_address[15:2], 2'b0};
                    byte_enable <= first_enable;
                    write_data <= format[0] ? packet[4] : packet[3];
                    state <= HEADER;
                    // No register access is issued until the entire TLP is validated.
                    if (packet_corrupt || packet[0][14]) begin
                        error_status[3] <= 1;
                    end else if (format[2] || packet_malformed || word_count != expected_words || invalid_enables) begin
                        error_status[2] <= 1;
                    end else if (supported) begin
                        if (format[1]) begin
                            if (first_enable != 0) begin
                                state <= WRITE;
                            end
                        end else if (first_enable == 0) begin
                            completion_data <= 1;
                            state <= TX_FIRST;
                        end else begin
                            state <= READ_ADDR;
                        end
                    end else if (nonposted) begin
                        completion_status <= request_type == 0 && bar_hit ? 3'b100 : 3'b001;
                        if (request_type == 0 && bar_hit) begin
                            error_status[1] <= 1;
                        end else begin
                            error_status[0] <= 1;
                        end
                        state <= TX_FIRST;
                    end else begin
                        error_status[0] <= 1;
                    end
                end
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
                    if (m_bvalid) begin
                        if (m_bresp != 0) begin
                            if (m_bresp == 3) begin
                                error_status[0] <= 1;
                            end else begin
                                error_status[1] <= 1;
                            end
                        end
                        state <= HEADER;
                    end
                end
                READ_ADDR: begin
                    if (m_arready) begin
                        state <= READ_DATA;
                    end
                end
                READ_DATA: begin
                    if (m_rvalid) begin
                        read_data <= m_rresp == 0 ? m_rdata : 0;
                        completion_data <= m_rresp == 0;
                        completion_status <= m_rresp == 0 ? 3'b000 : m_rresp == 3 ? 3'b001 : 3'b100;
                        if (m_rresp != 0) begin
                            if (m_rresp == 3) begin
                                error_status[0] <= 1;
                            end else begin
                                error_status[1] <= 1;
                            end
                        end
                        state <= TX_FIRST;
                    end
                end
                TX_FIRST: begin
                    if (tx_ready) begin
                        state <= TX_LAST;
                    end
                end
                TX_LAST: begin
                    if (tx_ready) begin
                        state <= HEADER;
                    end
                end
                default: state <= HEADER;
            endcase
        end
    end

    // The hard block validates BAR0; the register window uses its 16-bit offset.
    `UNUSED_VAR ({request_address[31:16], packet[5], packet[0][23], packet[0][19], rx_user[21:3]})
endmodule
