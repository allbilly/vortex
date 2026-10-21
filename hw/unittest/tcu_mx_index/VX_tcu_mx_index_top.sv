`include "VX_define.vh"

module VX_tcu_mx_index_top import VX_tcu_pkg::*; (
    input wire [TCU_FMT_WIDTH-1:0] fmt,
    input wire [31:0] tile_k_words,
    input wire [31:0] element_index,
    output wire [31:0] scale_blocks,
    output wire [31:0] block_index,
    output wire [3:0] elements_per_word
);
    assign scale_blocks = mx_scale_blocks_k_words(fmt, tile_k_words);
    assign block_index = mx_scale_block_index(fmt, element_index);
    assign elements_per_word = 4'(tcu_fmt_elts_per_word(fmt));
endmodule
