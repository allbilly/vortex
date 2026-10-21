`include "VX_define.vh"
module scoreboard_progress_tb;
    import VX_gpu_pkg::*;
    reg clk = 0;
    always #1 clk = ~clk;
    reg reset = 1;
    logic [1:0] valid = 0;
    ibuffer_t [1:0] data;
    wire [1:0] ready;
    wire [NUM_EX_UNITS-1:0] release_fu;
    reg release_lsu = 0;
    int lsu_count = 0;
    int alu_count = 0;
    VX_ibuffer_if ibuffer[2]();
    VX_writeback_if writeback();
    VX_scoreboard_if issued();
    for(genvar w=0; w<2; ++w) begin
        assign ibuffer[w].valid = valid[w];
        assign ibuffer[w].data = data[w];
        assign ready[w] = ibuffer[w].ready;
    end
    assign writeback.valid = 0;
    assign writeback.data = '0;
    assign issued.ready = 1;
    for(genvar e=0; e<NUM_EX_UNITS; ++e) begin
        assign release_fu[e] = (e == EX_ALU) ? (issued.valid && issued.data.ex_type == EX_BITS'(EX_ALU))
                             : ((e == EX_LSU) ? release_lsu : 1'b0);
    end
    VX_scoreboard dut(.clk(clk), .reset(reset), .fu_release(release_fu),
                      .writeback_if(writeback), .ibuffer_if(ibuffer), .scoreboard_if(issued));
    always @(posedge clk) begin
        if (!reset && issued.valid) begin
            if (issued.data.ex_type == EX_BITS'(EX_LSU)) ++lsu_count;
            if (issued.data.ex_type == EX_BITS'(EX_ALU)) ++alu_count;
        end
    end
    task automatic send(input int wid, input int ex);
        @(negedge clk);
        data[wid] = '0;
        data[wid].ex_type = EX_BITS'(ex);
        data[wid].fu_lock = 1;
        data[wid].fu_unlock = 1;
        data[wid].tmask = '1;
        valid[wid] = 1;
        do @(posedge clk); while(!ready[wid]);
        @(negedge clk);
        valid[wid] = 0;
    endtask
    initial begin
        data = '0;
        repeat(4) @(negedge clk);
        reset = 0;
        for(int n=0; n<3; ++n) send(0, EX_LSU);
        repeat(8) @(negedge clk);
        send(1, EX_LSU);
        for(int n=0; n<128; ++n) send(0, EX_ALU);
        if ($test$plusargs("deadlock")) begin
            repeat(80) @(negedge clk);
            $fatal(1, "Quiescent watchdog failed to fire");
        end
        release_lsu = 1;
        repeat(3) @(negedge clk);
        release_lsu = 0;
        repeat(12) @(negedge clk);
        if(lsu_count != 4 || alu_count != 128) $fatal(1, "Missing issue progress: lsu=%0d alu=%0d",lsu_count,alu_count);
        $display("PASSED long-wait progress lsu=%0d alu=%0d",lsu_count,alu_count);
        $finish;
    end
endmodule
