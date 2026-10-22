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
    reg b_pending = 0, r_pending = 0, hold_response = 0;
    reg [15:0] address;
    reg [31:0] value, memory [0:15];
    integer cycles = 0, writes = 0, reads = 0;
    integer write_completions = 0, read_completions = 0, reset_cases = 0;
    always @(negedge clk) begin
        m_awready = !aw_seen && !b_pending && !m_bvalid && cycles % 3 != 0;
        m_wready = !w_seen && !b_pending && !m_bvalid && cycles % 5 != 0;
        m_arready = !r_pending && !m_rvalid && cycles % 4 != 0;
    end
    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (reset) begin
            aw_seen <= 0; w_seen <= 0; m_bvalid <= 0; m_rvalid <= 0;
            b_pending <= 0; r_pending <= 0;
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
            if (aw_seen && w_seen && !b_pending && !m_bvalid) begin
                memory[address[5:2]] <= value;
                m_bresp <= address[15] ? 2'b10 : 0;
                b_pending <= 1; aw_seen <= 0; w_seen <= 0;
                writes <= writes + 1;
            end
            if (b_pending && !hold_response) begin
                m_bvalid <= 1; b_pending <= 0;
            end
            if (m_bvalid && m_bready) begin
                m_bvalid <= 0;
                write_completions <= write_completions + 1;
            end
            if (m_arvalid && m_arready) begin
                m_rdata <= memory[m_araddr[5:2]];
                m_rresp <= m_araddr[15] ? 2'b11 : 0;
                r_pending <= 1; reads <= reads + 1;
            end
            if (r_pending && !hold_response) begin
                m_rvalid <= 1; r_pending <= 0;
            end
            if (m_rvalid && m_rready) begin
                m_rvalid <= 0;
                read_completions <= read_completions + 1;
            end
        end
    end
    task automatic send_write(input [15:0] addr, input [31:0] data);
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
    endtask
    task automatic receive_write(input [15:0] addr);
        wait (s_bvalid);
        if (s_bresp !== (addr[15] ? 2'b10 : 2'b00)) begin
            $fatal(1, "write response changed");
        end
        repeat (3) begin
            @(negedge src_clk);
            if (!s_bvalid || s_bresp !== (addr[15] ? 2'b10 : 2'b00)) begin
                $fatal(1, "write response changed under backpressure");
            end
        end
        s_bready = 1; @(negedge src_clk); s_bready = 0;
    endtask
    task automatic write_word(input [15:0] addr, input [31:0] data);
        send_write(addr, data);
        receive_write(addr);
    endtask
    task automatic send_read(input [15:0] addr);
        @(negedge src_clk); s_araddr = addr; s_arvalid = 1;
        do @(posedge src_clk); while (!s_arready);
        @(negedge src_clk); s_arvalid = 0;
    endtask
    task automatic receive_read(input [15:0] addr, input [31:0] expected);
        wait (s_rvalid);
        if (s_rdata !== expected || s_rresp !== (addr[15] ? 2'b11 : 2'b00)) begin
            $fatal(1, "read data or response changed");
        end
        repeat (3) begin
            @(negedge src_clk);
            if (!s_rvalid || s_rdata !== expected || s_rresp !== (addr[15] ? 2'b11 : 2'b00)) begin
                $fatal(1, "read response changed under backpressure");
            end
        end
        s_rready = 1; @(negedge src_clk); s_rready = 0;
    endtask
    task automatic read_word(input [15:0] addr, input [31:0] expected);
        send_read(addr);
        receive_read(addr, expected);
    endtask
    task automatic source_reset_pulse;
        src_reset = 1;
        repeat (3) begin
            @(negedge src_clk);
            if (s_awready || s_wready || s_arready || s_bvalid || s_rvalid) begin
                $fatal(1, "source accepted traffic or retained a response during reset");
            end
        end
        src_reset = 0;
    endtask
    task automatic reset_transaction(input bit write_request, input integer phase);
        integer prior_writes, prior_reads, prior_completed;
        prior_writes = writes;
        prior_reads = reads;
        prior_completed = write_request ? write_completions : read_completions;
        hold_response = (phase == 1);
        if (write_request) begin
            send_write(16'h8004, 32'habcdef01);
        end else begin
            send_read(16'h8000);
        end
        case (phase)
            0: begin end
            1: begin
                wait (write_request ? writes == prior_writes + 1 : reads == prior_reads + 1);
            end
            2: begin
                wait (write_request ? write_completions == prior_completed + 1 : read_completions == prior_completed + 1);
                @(negedge src_clk);
                if (s_bvalid || s_rvalid) $fatal(1, "response reached the source before the in-transit reset");
            end
            3: begin
                wait (write_request ? s_bvalid : s_rvalid);
                @(negedge src_clk);
            end
            default: $fatal(1, "invalid reset phase");
        endcase
        source_reset_pulse();
        if (write_request) begin
            send_write(16'h8, 32'h76543210);
        end else begin
            send_read(16'hc);
        end
        if (phase == 1) begin
            repeat (8) begin
                @(negedge src_clk);
                if (s_bvalid || s_rvalid || writes != prior_writes + int'(write_request)
                    || reads != prior_reads + int'(!write_request)) begin
                    $fatal(1, "cancelled request leaked a response or a second request crossed before drain");
                end
            end
            hold_response = 0;
        end
        if (write_request) begin
            receive_write(16'h8);
            if (memory[2] !== 32'h76543210) $fatal(1, "post-reset write data changed");
            if (phase != 0 && memory[1] !== 32'habcdef01) $fatal(1, "cancelled destination write did not drain");
        end else begin
            receive_read(16'hc, 32'h12340003);
        end
        repeat (5) @(negedge src_clk);
        if (s_bvalid || s_rvalid
            || writes != prior_writes + int'(write_request) * ((phase == 0) ? 1 : 2)
            || reads != prior_reads + int'(!write_request) * ((phase == 0) ? 1 : 2)
            || write_completions != writes || read_completions != reads) begin
            $fatal(1, "lost, stale, or duplicated transaction after reset: write=%0d phase=%0d", write_request, phase);
        end
        reset_cases = reset_cases + 1;
        $display("TRACE reset write=%0d phase=%0d writes=%0d reads=%0d", write_request, phase, writes, reads);
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
        for (integer phase = 0; phase < 4; phase = phase + 1) begin
            reset_transaction(1'b0, phase);
            reset_transaction(1'b1, phase);
        end
        if (writes != 24 || reads != 24 || reset_cases != 8) $fatal(1, "incomplete reset coverage");
        $display("PASS: asynchronous AXI-Lite CDC, split AW/W, backpressure, errors, eight read/write reset phases, delayed completions and exactly-once execution");
        $finish;
    end
endmodule
