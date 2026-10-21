`include "VX_define.vh"

module VX_tcu_f4_mul_top import VX_tcu_pkg::*; #(
    parameter N = 2,
    parameter PROD_REG = 1,
    parameter DSP_ENABLE = 1,
    parameter TCK = 2 * N
) (
    input wire clk,
    input wire enable,
    input wire valid_in,
    input wire [31:0] req_id,
    input wire [8*N-1:0] vld_mask,
    input wire [3:0] fmt_f,
    input wire [N-1:0][31:0] a_row,
    input wire [N-1:0][31:0] b_col,
    input wire [7:0] sf_a,
    input wire [7:0] sf_b,
    output wire [TCK-1:0][31:0] result_words,
    output wire [TCK-1:0][31:0] exponent_words,
    output wire [TCK-1:0] sig_zero,
    output wire [TCK-1:0][2:0] exception_flags
);
    `STATIC_ASSERT (TCU_MAX_INPUTS >= 8*N, ("FP4 mask does not cover the selected word count"))
    wire [TCK-1:0][24:0] result_sig;
    wire [TCK-1:0][9:0] result_exp;
    fedp_excep_t [TCK-1:0] exceptions;
    VX_tcu_tfr_mul_f4 #(
        .N (N),
        .W (25),
        .WA (27 + $clog2(TCK+1)),
        .EXP_W (10),
        .DSP_ENABLE (DSP_ENABLE),
        .PROD_REG (PROD_REG)
    ) dut (
        .clk (clk),
        .enable (enable),
        .valid_in (valid_in),
        .req_id (req_id),
        .vld_mask (TCU_MAX_INPUTS'(vld_mask)),
        .fmt_f (fmt_f),
        .a_row (a_row),
        .b_col (b_col),
        .sf_a (sf_a),
        .sf_b (sf_b),
        .result_sig (result_sig),
        .result_exp (result_exp),
        .exceptions (exceptions),
        .sig_zero (sig_zero)
    );
    for (genvar lane = 0; lane < TCK; ++lane) begin : g_words
        assign result_words[lane] = 32'(result_sig[lane]);
        assign exponent_words[lane] = 32'(result_exp[lane]);
        assign exception_flags[lane] = exceptions[lane];
    end
endmodule
