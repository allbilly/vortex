`timescale 1ns/1ps

module ypcb_memory_case #(
    parameter bit DUAL_CHANNEL = 1'b0
) (
    input  wire clk,
    output reg  done = 1'b0
);
    localparam integer NUM_INPUTS = 2;
    localparam integer ID_WIDTH = 8;

    reg reset = 1'b1;

    reg [NUM_INPUTS-1:0] s_awvalid = '0;
    wire [NUM_INPUTS-1:0] s_awready;
    reg [NUM_INPUTS-1:0][63:0] s_awaddr = '0;
    reg [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_awid = '0;
    reg [NUM_INPUTS-1:0][7:0] s_awlen = '0;
    reg [NUM_INPUTS-1:0] s_wvalid = '0;
    wire [NUM_INPUTS-1:0] s_wready;
    reg [NUM_INPUTS-1:0][511:0] s_wdata = '0;
    reg [NUM_INPUTS-1:0][63:0] s_wstrb = '0;
    reg [NUM_INPUTS-1:0] s_wlast = '0;
    wire [NUM_INPUTS-1:0] s_bvalid;
    reg [NUM_INPUTS-1:0] s_bready = '0;
    wire [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_bid;
    wire [NUM_INPUTS-1:0][1:0] s_bresp;

    reg [NUM_INPUTS-1:0] s_arvalid = '0;
    wire [NUM_INPUTS-1:0] s_arready;
    reg [NUM_INPUTS-1:0][63:0] s_araddr = '0;
    reg [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_arid = '0;
    reg [NUM_INPUTS-1:0][7:0] s_arlen = '0;
    wire [NUM_INPUTS-1:0] s_rvalid;
    reg [NUM_INPUTS-1:0] s_rready = '0;
    wire [NUM_INPUTS-1:0][511:0] s_rdata;
    wire [NUM_INPUTS-1:0] s_rlast;
    wire [NUM_INPUTS-1:0][ID_WIDTH-1:0] s_rid;
    wire [NUM_INPUTS-1:0][1:0] s_rresp;

    wire [1:0] m_awvalid;
    reg [1:0] m_awready = '0;
    wire [1:0][30:0] m_awaddr;
    wire [1:0][7:0] m_awid;
    wire [1:0][7:0] m_awlen;
    wire [1:0] m_wvalid;
    reg [1:0] m_wready = '0;
    wire [1:0][511:0] m_wdata;
    wire [1:0][63:0] m_wstrb;
    wire [1:0] m_wlast;
    reg [1:0] m_bvalid = '0;
    wire [1:0] m_bready;
    reg [1:0][7:0] m_bid = '0;
    reg [1:0][1:0] m_bresp = '0;
    wire [1:0] m_arvalid;
    reg [1:0] m_arready = '0;
    wire [1:0][30:0] m_araddr;
    wire [1:0][7:0] m_arid;
    wire [1:0][7:0] m_arlen;
    reg [1:0] m_rvalid = '0;
    wire [1:0] m_rready;
    reg [1:0][511:0] m_rdata = '0;
    reg [1:0] m_rlast = '0;
    reg [1:0][7:0] m_rid = '0;
    reg [1:0][1:0] m_rresp = '0;
    wire busy;

    VX_ypcb_memory #(
        .NUM_INPUTS (NUM_INPUTS),
        .ID_WIDTH (ID_WIDTH),
        .DUAL_CHANNEL (DUAL_CHANNEL)
    ) dut (
        .clk (clk),
        .reset (reset),
        .busy (busy),
        .s_awvalid (s_awvalid), .s_awready (s_awready), .s_awaddr (s_awaddr),
        .s_awid (s_awid), .s_awlen (s_awlen), .s_wvalid (s_wvalid),
        .s_wready (s_wready), .s_wdata (s_wdata), .s_wstrb (s_wstrb),
        .s_wlast (s_wlast), .s_bvalid (s_bvalid), .s_bready (s_bready),
        .s_bid (s_bid), .s_bresp (s_bresp),
        .s_arvalid (s_arvalid), .s_arready (s_arready), .s_araddr (s_araddr),
        .s_arid (s_arid), .s_arlen (s_arlen), .s_rvalid (s_rvalid),
        .s_rready (s_rready), .s_rdata (s_rdata), .s_rlast (s_rlast),
        .s_rid (s_rid), .s_rresp (s_rresp),
        .m_awvalid (m_awvalid), .m_awready (m_awready), .m_awaddr (m_awaddr),
        .m_awid (m_awid), .m_awlen (m_awlen), .m_wvalid (m_wvalid),
        .m_wready (m_wready), .m_wdata (m_wdata), .m_wstrb (m_wstrb),
        .m_wlast (m_wlast), .m_bvalid (m_bvalid), .m_bready (m_bready),
        .m_bid (m_bid), .m_bresp (m_bresp),
        .m_arvalid (m_arvalid), .m_arready (m_arready), .m_araddr (m_araddr),
        .m_arid (m_arid), .m_arlen (m_arlen), .m_rvalid (m_rvalid),
        .m_rready (m_rready), .m_rdata (m_rdata), .m_rlast (m_rlast),
        .m_rid (m_rid), .m_rresp (m_rresp)
    );

    function automatic [63:0] host_address(input bit physical_bank, input [30:0] local_address);
        host_address = {32'b0, physical_bank, local_address};
    endfunction

    function automatic integer selected_bank(input [63:0] address);
        if (DUAL_CHANNEL)
            selected_bank = address[31] ? 1 : 0;
        else
            selected_bank = 1;
    endfunction

    function automatic bit address_valid(input [63:0] address, input [7:0] len);
        reg [8:0] final_beat;
        reg range_valid;
        begin
            range_valid = DUAL_CHANNEL ? (address[63:32] == 0) : (address[63:31] == 0);
            final_beat = {3'b0, address[11:6]} + {1'b0, len};
            address_valid = range_valid && (address[5:0] == 0) && (final_beat < 9'd64);
        end
    endfunction

    function automatic [511:0] data_pattern(input [7:0] id, input integer beat, input integer master, input integer bank);
        reg [63:0] lane;
        begin
            for (integer i = 0; i < 8; ++i) begin
                lane = 64'hd00d_cafe_0000_0000;
                lane[7:0] = id;
                lane[15:8] = beat[7:0];
                lane[23:16] = master[7:0];
                lane[31:24] = bank[7:0];
                lane[39:32] = i[7:0];
                data_pattern[i*64 +: 64] = lane;
            end
        end
    endfunction

    function automatic [63:0] strobe_pattern(input integer beat);
        case (beat)
            0: strobe_pattern = 64'h0000_0000_0000_00ff;
            1: strobe_pattern = 64'hf000_0000_0000_000f;
            default: strobe_pattern = 64'h1111_1111_1111_1111;
        endcase
    endfunction

    task automatic require(input bit condition, input string message);
        if (!condition)
            $fatal(1, "DUAL_CHANNEL=%0d: %s", DUAL_CHANNEL, message);
    endtask

    task automatic clear_bus;
        begin
            s_awvalid = '0; s_awaddr = '0; s_awid = '0; s_awlen = '0;
            s_wvalid = '0; s_wdata = '0; s_wstrb = '0; s_wlast = '0;
            s_bready = '0; s_arvalid = '0; s_araddr = '0; s_arid = '0;
            s_arlen = '0; s_rready = '0;
            m_awready = '0; m_wready = '0; m_bvalid = '0;
            m_bid[0] = 8'h35; m_bid[1] = 8'hca; m_bresp = '0;
            m_arready = '0; m_rvalid = '0; m_rdata = '0; m_rlast = '0;
            m_rid[0] = 8'h5a; m_rid[1] = 8'ha5; m_rresp = '0;
        end
    endtask

    task automatic accept_aw(
        input integer master,
        input [63:0] address,
        input [7:0] id,
        input [7:0] len,
        input bit valid_request,
        output integer bank
    );
        integer cycles;
        reg [1:0] bank_mask;
        begin
            bank = selected_bank(address);
            bank_mask = 2'b01 << bank;
            @(negedge clk);
            s_awvalid = '0;
            s_awvalid[master] = 1'b1;
            s_awaddr[master] = address;
            s_awid[master] = id;
            s_awlen[master] = len;
            m_awready = '0;
            #1;
            if (valid_request) begin
                cycles = 0;
                while (m_awvalid !== bank_mask && cycles < 12) begin
                    @(posedge clk);
                    cycles = cycles + 1;
                end
                require(m_awvalid === bank_mask, "valid AW was not presented to the selected bank");
                repeat (2) begin
                    @(posedge clk);
                    require(m_awvalid === bank_mask && !s_awready[master], "AW backpressure was not retained");
                    require(m_awaddr[bank] === address[30:0], "AW local address did not strip the bank bit");
                    require(m_awid[bank] === 8'b0 && m_awlen[bank] === len, "AW ID or length was not serialized");
                end
                @(negedge clk);
                m_awready[bank] = 1'b1;
                #1;
                @(posedge clk);
                require(s_awready[master] && m_awvalid === bank_mask, "AW did not handshake after bank ready");
            end else begin
                cycles = 0;
                while (!s_awready[master] && cycles < 12) begin
                    require(m_awvalid == 2'b00, "invalid AW escaped to a DDR bank");
                    @(posedge clk);
                    cycles = cycles + 1;
                end
                require(s_awready[master] && m_awvalid == 2'b00, "invalid AW did not terminate locally");
                @(posedge clk);
            end
            @(negedge clk);
            s_awvalid = '0;
            m_awready = '0;
            s_awaddr[master] = address ^ 64'h0000_0000_8000_0000;
            s_awid[master] = ~id;
        end
    endtask

    task automatic send_write_data(input integer master, input integer bank, input bit valid_request,
                                   input [7:0] id, input [7:0] len);
        reg [1:0] bank_mask;
        reg [511:0] expected_data;
        integer beat;
        begin
            bank_mask = 2'b01 << bank;
            for (beat = 0; beat <= int'(len); beat = beat + 1) begin
                expected_data = data_pattern(id, beat, master, bank);
                @(negedge clk);
                s_wvalid = '0;
                s_wvalid[master] = 1'b1;
                s_wdata[master] = expected_data;
                s_wstrb[master] = strobe_pattern(beat);
                s_wlast[master] = (beat == int'(len));
                m_wready = '0;
                #1;
                if (valid_request) begin
                    repeat (2) begin
                        @(posedge clk);
                        require(m_wvalid === bank_mask && !s_wready[master], "W channel did not retain downstream backpressure");
                        require(m_wdata[bank] === expected_data && m_wstrb[bank] === strobe_pattern(beat)
                                && m_wlast[bank] === (beat == int'(len)), "W data, byte mask or last marker was corrupted");
                    end
                    @(negedge clk);
                    m_wready[bank] = 1'b1;
                    #1;
                    @(posedge clk);
                    require(m_wvalid === bank_mask && s_wready[master], "W did not handshake at selected bank");
                end else begin
                    @(posedge clk);
                    require(m_wvalid == 2'b00 && s_wready[master], "invalid write data was forwarded or not consumed");
                end
                @(negedge clk);
                s_wvalid = '0;
                m_wready = '0;
            end
        end
    endtask

    task automatic finish_write(input integer master, input integer bank, input bit valid_request,
                                input [7:0] id);
        reg [1:0] bank_mask;
        reg [1:0] expected_resp;
        begin
            bank_mask = 2'b01 << bank;
            expected_resp = valid_request ? (bank == 0 ? 2'b00 : 2'b10) : 2'b11;
            @(negedge clk);
            m_bvalid = valid_request ? 2'b11 : 2'b00;
            m_bresp[0] = 2'b00;
            m_bresp[1] = 2'b10;
            s_bready = '0;
            #1;
            repeat (2) begin
                @(posedge clk);
                require(s_bvalid[master] && !s_bvalid[1-master], "B response returned to the wrong host");
                require(s_bid[master] === id && s_bresp[master] === expected_resp, "serialized B ID or selected-channel response was wrong");
                require(m_bready == 2'b00, "B response was not held under host backpressure");
            end
            @(negedge clk);
            s_bready[master] = 1'b1;
            #1;
            @(posedge clk);
            require(s_bvalid[master] && s_bid[master] === id && s_bresp[master] === expected_resp,
                    "B response changed before host handshake");
            if (valid_request)
                require(m_bready === bank_mask, "B ready was not returned to the transaction's latched bank");
            else
                require(m_bready == 2'b00, "locally rejected B response consumed a DDR response");
            @(negedge clk);
            s_bready = '0;
            m_bvalid = '0;
            #1;
            require(!s_bvalid[master], "B response remained valid after acceptance");
        end
    endtask

    task automatic write_transaction(input integer master, input [63:0] address,
                                     input [7:0] id, input [7:0] len, input bit expect_valid);
        integer bank;
        bit valid_request;
        begin
            valid_request = address_valid(address, len);
            if (valid_request != expect_valid)
                $fatal(1, "DUAL_CHANNEL=%0d: write vector address=%016h len=%0d valid=%0d expected=%0d",
                       DUAL_CHANNEL, address, len, valid_request, expect_valid);
            accept_aw(master, address, id, len, valid_request, bank);
            send_write_data(master, bank, valid_request, id, len);
            finish_write(master, bank, valid_request, id);
            @(posedge clk); #1;
            require(!busy, "write transaction did not drain");
        end
    endtask

    task automatic accept_ar(
        input integer master,
        input [63:0] address,
        input [7:0] id,
        input [7:0] len,
        input bit valid_request,
        output integer bank
    );
        integer cycles;
        reg [1:0] bank_mask;
        begin
            bank = selected_bank(address);
            bank_mask = 2'b01 << bank;
            @(negedge clk);
            s_arvalid = '0;
            s_arvalid[master] = 1'b1;
            s_araddr[master] = address;
            s_arid[master] = id;
            s_arlen[master] = len;
            m_arready = '0;
            #1;
            if (valid_request) begin
                cycles = 0;
                while (m_arvalid !== bank_mask && cycles < 12) begin
                    @(posedge clk);
                    cycles = cycles + 1;
                end
                require(m_arvalid === bank_mask, "valid AR was not presented to the selected bank");
                repeat (2) begin
                    @(posedge clk);
                    require(m_arvalid === bank_mask && !s_arready[master], "AR backpressure was not retained");
                    require(m_araddr[bank] === address[30:0], "AR local address did not strip the bank bit");
                    require(m_arid[bank] === 8'b0 && m_arlen[bank] === len, "AR ID or length was not serialized");
                end
                @(negedge clk);
                m_arready[bank] = 1'b1;
                #1;
                @(posedge clk);
                require(s_arready[master] && m_arvalid === bank_mask, "AR did not handshake after bank ready");
            end else begin
                cycles = 0;
                while (!s_arready[master] && cycles < 12) begin
                    require(m_arvalid == 2'b00, "invalid AR escaped to a DDR bank");
                    @(posedge clk);
                    cycles = cycles + 1;
                end
                require(s_arready[master] && m_arvalid == 2'b00, "invalid AR did not terminate locally");
                @(posedge clk);
            end
            @(negedge clk);
            s_arvalid = '0;
            m_arready = '0;
            s_araddr[master] = address ^ 64'h0000_0000_8000_0000;
            s_arid[master] = ~id;
        end
    endtask

    task automatic read_data(input integer master, input integer bank, input bit valid_request,
                             input [7:0] id, input [7:0] len);
        reg [1:0] bank_mask;
        reg [511:0] expected_data;
        reg [1:0] expected_resp;
        integer beat;
        begin
            bank_mask = 2'b01 << bank;
            expected_resp = valid_request ? (bank == 0 ? 2'b00 : 2'b10) : 2'b11;
            for (beat = 0; beat <= int'(len); beat = beat + 1) begin
                @(negedge clk);
                s_rready = '0;
                m_rvalid = valid_request ? 2'b11 : 2'b00;
                m_rdata[0] = data_pattern(id, beat, master, 0);
                m_rdata[1] = data_pattern(id, beat, master, 1);
                m_rlast = {2{beat == int'(len)}};
                m_rresp[0] = 2'b00;
                m_rresp[1] = 2'b10;
                m_rid[0] = 8'h43;
                m_rid[1] = 8'hb7;
                expected_data = valid_request ? m_rdata[bank] : 512'b0;
                #1;
                repeat (2) begin
                    @(posedge clk);
                    require(s_rvalid[master] && !s_rvalid[1-master], "R response returned to the wrong host");
                    require(s_rdata[master] === expected_data && s_rid[master] === id
                            && s_rresp[master] === expected_resp && s_rlast[master] === (beat == int'(len)),
                            "R data, serialized ID, response or last marker was wrong");
                    require(m_rready == 2'b00, "R response was not held under host backpressure");
                end
                @(negedge clk);
                s_rready[master] = 1'b1;
                #1;
                @(posedge clk);
                require(s_rvalid[master] && s_rdata[master] === expected_data && s_rid[master] === id
                        && s_rresp[master] === expected_resp && s_rlast[master] === (beat == int'(len)),
                        "R response changed before host handshake");
                if (valid_request)
                    require(m_rready === bank_mask, "R ready was not returned to the transaction's latched bank");
                else
                    require(m_rready == 2'b00, "locally rejected R response consumed a DDR response");
                @(negedge clk);
                s_rready = '0;
                m_rvalid = '0;
            end
        end
    endtask

    task automatic read_transaction(input integer master, input [63:0] address,
                                    input [7:0] id, input [7:0] len, input bit expect_valid);
        integer bank;
        bit valid_request;
        begin
            valid_request = address_valid(address, len);
            if (valid_request != expect_valid)
                $fatal(1, "DUAL_CHANNEL=%0d: read vector address=%016h len=%0d valid=%0d expected=%0d",
                       DUAL_CHANNEL, address, len, valid_request, expect_valid);
            accept_ar(master, address, id, len, valid_request, bank);
            read_data(master, bank, valid_request, id, len);
            @(posedge clk); #1;
            require(!busy, "read transaction did not drain");
        end
    endtask

    task automatic cancel_write;
        integer bank;
        begin
            accept_aw(0, host_address(DUAL_CHANNEL ? 1'b1 : 1'b0, 31'h0000_6000), 8'hc1, 8'd0, 1'b1, bank);
            @(negedge clk);
            reset = 1'b1;
            m_bvalid = 2'b11;
            m_rvalid = 2'b11;
            m_awready = 2'b11;
            m_wready = 2'b11;
            m_arready = 2'b11;
            #1;
            repeat (3) begin
                @(posedge clk); #1;
                require(!busy && s_bvalid == 0 && s_rvalid == 0
                        && m_awvalid == 0 && m_wvalid == 0 && m_bready == 0
                        && m_arvalid == 0 && m_rready == 0,
                        "reset did not cancel outstanding write and suppress stale responses");
            end
            @(negedge clk);
            reset = 1'b0;
            m_bvalid = '0;
            m_rvalid = '0;
            m_awready = '0;
            m_wready = '0;
            m_arready = '0;
            repeat (2) begin
                @(posedge clk); #1;
                require(s_bvalid == 0 && s_rvalid == 0 && !busy, "stale response survived write reset");
            end
        end
    endtask

    task automatic cancel_read;
        integer bank;
        begin
            accept_ar(1, host_address(DUAL_CHANNEL ? 1'b0 : 1'b0, 31'h0000_7000), 8'hc2, 8'd1, 1'b1, bank);
            @(negedge clk);
            reset = 1'b1;
            m_bvalid = 2'b11;
            m_rvalid = 2'b11;
            m_awready = 2'b11;
            m_wready = 2'b11;
            m_arready = 2'b11;
            #1;
            repeat (3) begin
                @(posedge clk); #1;
                require(!busy && s_bvalid == 0 && s_rvalid == 0
                        && m_awvalid == 0 && m_wvalid == 0 && m_bready == 0
                        && m_arvalid == 0 && m_rready == 0,
                        "reset did not cancel outstanding read and suppress stale responses");
            end
            @(negedge clk);
            reset = 1'b0;
            m_bvalid = '0;
            m_rvalid = '0;
            m_awready = '0;
            m_wready = '0;
            m_arready = '0;
            repeat (2) begin
                @(posedge clk); #1;
                require(s_bvalid == 0 && s_rvalid == 0 && !busy, "stale response survived read reset");
            end
        end
    endtask

    initial begin
        done = 1'b0;
        clear_bus();
        reset = 1'b1;
        repeat (4) @(posedge clk);
        @(negedge clk); reset = 1'b0;

        write_transaction(0, host_address(1'b0, 31'h0000_1200), 8'ha1, 8'd1, 1'b1);
        write_transaction(1, host_address(DUAL_CHANNEL ? 1'b1 : 1'b0, 31'h0000_3400), 8'hb2, 8'd0, 1'b1);
        read_transaction(1, host_address(DUAL_CHANNEL ? 1'b1 : 1'b0, 31'h0000_5600), 8'hc3, 8'd1, 1'b1);
        read_transaction(0, host_address(1'b0, 31'h0000_7800), 8'hd4, 8'd0, 1'b1);

        write_transaction(0, 64'h0000_0001_0000_4000, 8'he1, 8'd0, 1'b0);
        read_transaction(1, 64'h0000_0001_0000_8000, 8'he2, 8'd0, 1'b0);
        write_transaction(1, host_address(DUAL_CHANNEL ? 1'b1 : 1'b0, 31'h0000_2008), 8'he3, 8'd0, 1'b0);
        read_transaction(0, host_address(DUAL_CHANNEL ? 1'b1 : 1'b0, 31'h0000_2008), 8'he4, 8'd0, 1'b0);
        write_transaction(0, host_address(DUAL_CHANNEL ? 1'b0 : 1'b0, 31'h0000_2fc0), 8'he5, 8'd1, 1'b0);
        read_transaction(1, host_address(DUAL_CHANNEL ? 1'b0 : 1'b0, 31'h0000_2fc0), 8'he6, 8'd1, 1'b0);
        if (!DUAL_CHANNEL) begin
            write_transaction(1, host_address(1'b1, 31'h0000_4000), 8'he7, 8'd0, 1'b0);
            read_transaction(0, host_address(1'b1, 31'h0000_4000), 8'he8, 8'd0, 1'b0);
        end

        cancel_write();
        cancel_read();
        done = 1'b1;
        $display("PASS: DUAL_CHANNEL=%0d bank routing, 31-bit local addresses, AXI masks/IDs, invalid ranges, backpressure and reset cancellation", DUAL_CHANNEL);
    end
endmodule

module ypcb_memory_tb;
    reg clk = 1'b0;
    wire dual_done;
    wire single_done;
    always #5 clk = ~clk;

    ypcb_memory_case #(.DUAL_CHANNEL (1)) dual_channel_case (.clk(clk), .done(dual_done));
    ypcb_memory_case #(.DUAL_CHANNEL (0)) single_channel_case (.clk(clk), .done(single_done));

    initial begin
        wait (dual_done && single_done);
        $display("PASS: YPCB memory dual-channel and legacy single-channel routing");
        $finish;
    end

    initial begin
        #200000;
        $fatal(1, "Timed out waiting for YPCB memory routing cases");
    end
endmodule
