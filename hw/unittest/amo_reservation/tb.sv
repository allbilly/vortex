`include "VX_define.vh"
module reservation_tb #(
    parameter NUM_RES_ENTRIES = 4,
    parameter HOLD_CREDIT_BITS = `LOG2UP(`VX_CFG_NUM_WARPS * `VX_CFG_NUM_THREADS)
);
    import VX_gpu_pkg::*;
    reg clk = 0;
    always #1 clk = ~clk;
    reg reset = 1;
    reg reserve = 0;
    reg clear = 0;
    reg invalidate = 0;
    reg stall = 0;
    reg [HART_ID_WIDTH-1:0] hart = 0;
    reg [15:0] address = 0;
    wire matched;
    VX_amo_unit #(
        .NUM_RES_ENTRIES(NUM_RES_ENTRIES),
        .HOLD_CREDIT_BITS(HOLD_CREDIT_BITS),
        .LINE_ADDR_BITS(16), .DATA_WIDTH(32)
    ) dut (
        .clk(clk), .reset(reset), .pipe_stall(stall),
        .compute_op(AMO_OP_LR), .compute_unsigned(1'b0), .compute_width(2'd2),
        .compute_old(64'b0), .compute_rhs(64'b0), .compute_cmp(64'b0),
        .compute_new_word(), .compute_ret_word(),
        .res_reserve(reserve), .res_clear(clear), .res_invalidate(invalidate),
        .res_hart_id(hart), .res_line_addr(address), .res_line_addr_n(address),
        .res_check(matched)
    );
    initial begin
        string filename;
        int fd, count, op, hid, word_addr, blocked, expected, scanned;
        count = 0;
        if (!$value$plusargs("vectors=%s", filename)) $fatal(1, "Missing vectors");
        fd = $fopen(filename, "r");
        if (fd == 0) $fatal(1, "Cannot open vectors");
        repeat(4) @(negedge clk);
        reset = 0;
        while (!$feof(fd)) begin
            scanned = $fscanf(fd, "%d %d %d %d %d\n", op, hid, word_addr, blocked, expected);
            if (scanned != 5) $fatal(1, "Malformed vector");
            address = 16'(word_addr);
            @(negedge clk);
            hart = HART_ID_WIDTH'(hid);
            stall = 1'(blocked);
            reserve = (op == 1);
            clear = (op == 2);
            invalidate = (op == 3);
            #0.1;
            if (expected >= 0 && matched != 1'(expected))
                $fatal(1, "Reservation contract failed vector=%0d op=%0d hart=%0d expected=%0d actual=%0d", count, op, hid, expected, matched);
            $display("TRACE %0d %0d %0d %0d %0d %0d", count, op, hid, word_addr, blocked, matched);
            @(negedge clk);
            reserve = 0;
            clear = 0;
            invalidate = 0;
            stall = 0;
            ++count;
        end
        $fclose(fd);
        $display("PASSED vectors=%0d", count);
        $finish;
    end
endmodule
