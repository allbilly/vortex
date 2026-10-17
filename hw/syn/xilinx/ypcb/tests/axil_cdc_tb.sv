`timescale 1ns/1ps
module axil_cdc_tb;
    reg src_clk = 0, clk = 0, reset = 1, src_reset = 0;
    always #7 src_clk = !src_clk;
    always #5 clk = !clk;
    reg s_awvalid = 0, s_wvalid = 0, s_arvalid = 0;
    wire s_awready, s_wready, s_arready;
    reg [15:0] s_awaddr = 0, s_araddr = 0;
    reg [31:0] s_wdata = 0;
    reg [3:0] s_wstrb = 0;
    wire s_bvalid, s_rvalid;
    reg s_bready = 0, s_rready = 0;
    wire [1:0] s_bresp, s_rresp;
    wire [31:0] s_rdata;
    wire m_awvalid, m_wvalid, m_arvalid, m_bready, m_rready;
    wire [15:0] m_awaddr, m_araddr;
    wire [31:0] m_wdata;
    wire [3:0] m_wstrb;
    reg m_awready = 0, m_wready = 0, m_arready = 0;
    reg m_bvalid = 0, m_rvalid = 0;
    reg [1:0] m_bresp = 0, m_rresp = 0;
    reg [31:0] m_rdata = 0;
    VX_ypcb_axil_cdc dut (.*);
    reg aw_seen = 0, w_seen = 0;
    reg [15:0] address;
    reg [31:0] value, memory [0:15];
    integer cycles = 0, writes = 0, reads = 0;
    always @(negedge clk) begin
        m_awready = !aw_seen && !m_bvalid && cycles % 3 != 0;
        m_wready = !w_seen && !m_bvalid && cycles % 5 != 0;
        m_arready = !m_rvalid && cycles % 4 != 0;
    end
    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (reset) begin
            aw_seen <= 0; w_seen <= 0; m_bvalid <= 0; m_rvalid <= 0;
        end else begin
            if (m_awvalid && m_awready) begin
                address <= m_awaddr; aw_seen <= 1;
            end
            if (m_wvalid && m_wready) begin
                if (m_wstrb !== 4'hf) begin
                    $fatal(1, "write strobe changed");
                end
                value <= m_wdata; w_seen <= 1;
            end
            if (aw_seen && w_seen && !m_bvalid) begin
                memory[address[5:2]] <= value;
                m_bresp <= address[15] ? 2'b10 : 0;
                m_bvalid <= 1; aw_seen <= 0; w_seen <= 0;
                writes <= writes + 1;
            end
            if (m_bvalid && m_bready) begin
                m_bvalid <= 0;
            end
            if (m_arvalid && m_arready) begin
                m_rdata <= memory[m_araddr[5:2]];
                m_rresp <= m_araddr[15] ? 2'b11 : 0;
                m_rvalid <= 1; reads <= reads + 1;
            end
            if (m_rvalid && m_rready) begin
                m_rvalid <= 0;
            end
        end
    end
    task automatic write_word(input [15:0] addr, input [31:0] data);
        fork
            begin
                @(negedge src_clk); s_awaddr = addr; s_awvalid = 1;
                do @(posedge src_clk); while (!s_awready);
                @(negedge src_clk); s_awvalid = 0;
            end
            begin
                repeat (5) @(negedge src_clk);
                s_wdata = data; s_wstrb = 15; s_wvalid = 1;
                do @(posedge src_clk); while (!s_wready);
                @(negedge src_clk); s_wvalid = 0;
            end
        join
        wait (s_bvalid);
        if (s_bresp !== (addr[15] ? 2'b10 : 2'b00)) begin
            $fatal(1, "write response changed");
        end
        repeat (3) @(negedge src_clk);
        if (!s_bvalid) begin
            $fatal(1, "write response lost under backpressure");
        end
        s_bready = 1; @(negedge src_clk); s_bready = 0;
    endtask
    task automatic read_word(input [15:0] addr, input [31:0] expected);
        @(negedge src_clk); s_araddr = addr; s_arvalid = 1;
        do @(posedge src_clk); while (!s_arready);
        @(negedge src_clk); s_arvalid = 0;
        wait (s_rvalid);
        if (s_rdata !== expected || s_rresp !== (addr[15] ? 2'b11 : 2'b00)) begin
            $fatal(1, "read data or response changed");
        end
        repeat (3) @(negedge src_clk);
        if (!s_rvalid) begin
            $fatal(1, "read response lost under backpressure");
        end
        s_rready = 1; @(negedge src_clk); s_rready = 0;
    endtask
    initial begin
        #200000;
        $fatal(1, "CDC test timeout");
    end
    initial begin
        repeat (4) @(negedge src_clk); reset = 0;
        for (integer i = 0; i < 16; i = i + 1) begin
            write_word(16'(i * 4), 32'h12340000 + 32'(i));
            read_word(16'(i * 4), 32'h12340000 + 32'(i));
        end
        write_word(16'h8000, 32'hdeadbeef);
        read_word(16'h8000, 32'hdeadbeef);
        // Reset the source after a complete request crossed; the destination drains it.
        @(negedge src_clk);
        s_awaddr = 16'h4; s_awvalid = 1;
        s_wdata = 32'habcdef01; s_wstrb = 15; s_wvalid = 1;
        do @(posedge src_clk); while (!(s_awready && s_wready));
        @(negedge src_clk); s_awvalid = 0; s_wvalid = 0;
        wait (m_awvalid);
        @(negedge src_clk); src_reset = 1;
        repeat (20) @(negedge src_clk);
        src_reset = 0;
        read_word(16'h4, 32'habcdef01);
        if (writes != 18 || reads != 18) begin
            $fatal(1, "lost or duplicated transaction");
        end
        $display("PASS: asynchronous AXI-Lite CDC, split AW/W, backpressure, errors, source reset and exactly-once execution");
        $finish;
    end
endmodule
