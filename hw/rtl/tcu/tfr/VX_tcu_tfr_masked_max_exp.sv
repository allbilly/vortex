// Copyright © 2019-2023
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

`include "VX_define.vh"

// Precompute exponent order before exact-cancellation flags arrive.
module VX_tcu_tfr_masked_max_exp #(
    parameter N = 5,
    parameter WIDTH = 10,
    parameter DEPTH = 1
) (
    input wire clk,
    input wire enable,
    input wire [N-1:0][WIDTH-1:0] exponents,
    input wire [N-1:0] zero_mask,
    output wire [N-1:0] sel_exp
);
    `STATIC_ASSERT (N >= 2, ("At least two exponent candidates are required"))
    localparam PAIRS = N*(N-1)/2;
    wire [PAIRS-1:0] less_w, less_r;
    wire [N-1:0] nonzero_w, nonzero_r;
    for (genvar i = 0; i < N; ++i) begin : g_order
        assign nonzero_w[i] = |exponents[i];
        for (genvar j = i+1; j < N; ++j) begin : g_pair
            localparam INDEX = i*(2*N-i-1)/2 + j-i-1;
            assign less_w[INDEX] = exponents[i] < exponents[j];
        end
    end
    VX_pipe_register #(
        .DATAW (PAIRS + N),
        .DEPTH (DEPTH)
    ) pipe_order (
        .clk (clk),
        .reset (1'b0),
        .enable (enable),
        .data_in ({less_w, nonzero_w}),
        .data_out ({less_r, nonzero_r})
    );
    wire [N-1:0] active = nonzero_r & ~zero_mask;
    for (genvar i = 0; i < N; ++i) begin : g_select
        wire [N-1:0] wins;
        for (genvar j = 0; j < N; ++j) begin : g_competitor
            if (j < i) begin : g_preceding
                assign wins[j] = ~active[j] | less_r[j*(2*N-j-1)/2 + i-j-1];
            end else if (j > i) begin : g_following
                assign wins[j] = ~active[j] | ~less_r[i*(2*N-i-1)/2 + j-i-1];
            end else begin : g_self
                assign wins[j] = 1'b1;
            end
        end
        if (i == 0) begin : g_zero_fallback
            assign sel_exp[i] = (active[i] & (&wins)) | (~|active);
        end else begin : g_positive
            assign sel_exp[i] = active[i] & (&wins);
        end
    end
endmodule
