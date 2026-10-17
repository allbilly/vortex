// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

module VX_ypcb_ddr_control (
    input wire clk,
    input wire reset,

    input wire s_awvalid,
    output reg s_awready,
    input wire [12:0] s_awaddr,
    input wire s_wvalid,
    output reg s_wready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    output reg s_bvalid,
    input wire s_bready,
    output reg [1:0] s_bresp,
    input wire s_arvalid,
    output reg s_arready,
    input wire [12:0] s_araddr,
    output reg s_rvalid,
    input wire s_rready,
    output reg [31:0] s_rdata,
    output reg [1:0] s_rresp,

    output reg wb_cyc,
    output reg wb_stb,
    output reg wb_we,
    output reg [29:0] wb_adr,
    output reg [31:0] wb_dat_w,
    output reg [3:0] wb_sel,
    input wire wb_ack,
    input wire wb_err,
    input wire [31:0] wb_dat_r
);
    reg aw_pending, w_pending, ar_pending;
    reg [12:0] write_address, read_address;
    reg [31:0] write_data;
    reg [3:0] write_strobe;
    reg prefer_read;
    wire write_available = aw_pending && w_pending && !s_bvalid;
    wire read_available = ar_pending && !s_rvalid;
    wire choose_read = read_available && (!write_available || prefer_read);

    always @(posedge clk) begin
        if (reset) begin
            aw_pending <= 0;
            w_pending <= 0;
            ar_pending <= 0;
            write_address <= '0;
            read_address <= '0;
            write_data <= '0;
            write_strobe <= '0;
            prefer_read <= 0;
            s_awready <= 1;
            s_wready <= 1;
            s_bvalid <= 0;
            s_bresp <= '0;
            s_arready <= 1;
            s_rvalid <= 0;
            s_rdata <= '0;
            s_rresp <= '0;
            wb_cyc <= 0;
            wb_stb <= 0;
            wb_we <= 0;
            wb_adr <= '0;
            wb_dat_w <= '0;
            wb_sel <= '0;
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
            if (s_arvalid && s_arready) begin
                ar_pending <= 1;
                read_address <= s_araddr;
                s_arready <= 0;
            end
            if (s_bvalid && s_bready) begin
                s_bvalid <= 0;
                s_awready <= 1;
                s_wready <= 1;
            end
            if (s_rvalid && s_rready) begin
                s_rvalid <= 0;
                s_arready <= 1;
            end
            if (wb_cyc) begin
                if (wb_ack || wb_err) begin
                    wb_cyc <= 0;
                    wb_stb <= 0;
                    if (wb_we) begin
                        s_bvalid <= 1;
                        s_bresp <= wb_err ? 2'b10 : 2'b00;
                    end else begin
                        s_rvalid <= 1;
                        s_rdata <= wb_err ? 32'b0 : wb_dat_r;
                        s_rresp <= wb_err ? 2'b10 : 2'b00;
                    end
                end
            end else if (choose_read) begin
                ar_pending <= 0;
                prefer_read <= 0;
                if (read_address[1:0] != 0) begin
                    s_rvalid <= 1;
                    s_rdata <= '0;
                    s_rresp <= 2'b11;
                end else begin
                    wb_cyc <= 1;
                    wb_stb <= 1;
                    wb_we <= 0;
                    wb_adr <= {19'b0, read_address[12:2]};
                    wb_dat_w <= '0;
                    wb_sel <= 4'b1111;
                end
            end else if (write_available) begin
                aw_pending <= 0;
                w_pending <= 0;
                prefer_read <= 1;
                if (write_address[1:0] != 0) begin
                    s_bvalid <= 1;
                    s_bresp <= 2'b11;
                end else if (write_strobe == 0) begin
                    s_bvalid <= 1;
                    s_bresp <= 2'b00;
                end else if (write_strobe != 4'b1111) begin
                    // LiteX's 32-bit CSR bridge treats every nonzero select as a full-word write.
                    s_bvalid <= 1;
                    s_bresp <= 2'b10;
                end else begin
                    wb_cyc <= 1;
                    wb_stb <= 1;
                    wb_we <= 1;
                    wb_adr <= {19'b0, write_address[12:2]};
                    wb_dat_w <= write_data;
                    wb_sel <= write_strobe;
                end
            end
        end
    end
endmodule
