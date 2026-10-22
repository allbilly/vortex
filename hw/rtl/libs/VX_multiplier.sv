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

`include "VX_platform.vh"

`TRACING_OFF
module VX_multiplier #(
    parameter A_WIDTH = 1,
    parameter B_WIDTH = A_WIDTH,
    parameter R_WIDTH = A_WIDTH + B_WIDTH,
    parameter SIGNED  = 0,
    parameter LATENCY = 0,
    parameter PARTIAL_REG = 0
) (
    input wire clk,
    input wire enable,
    input wire [A_WIDTH-1:0]  dataa,
    input wire [B_WIDTH-1:0]  datab,
    output wire [R_WIDTH-1:0] result
);
    wire [R_WIDTH-1:0] prod_w;

    `STATIC_ASSERT (!PARTIAL_REG || (LATENCY >= 2 && A_WIDTH >= 2 && B_WIDTH >= 2), ("Partial products require two stages and nontrivial operands"))
    if (PARTIAL_REG != 0) begin : g_partial
        localparam AL = A_WIDTH / 2;
        localparam AH = A_WIDTH - AL;
        localparam BL = B_WIDTH / 2;
        localparam BH = B_WIDTH - BL;
        localparam W00 = AL + BL + 2;
        localparam W01 = AL + BH + 2;
        localparam W10 = AH + BL + 2;
        localparam W11 = AH + BH + 2;
        wire signed [AL:0] a_lo = {1'b0, dataa[AL-1:0]};
        wire signed [AH:0] a_hi = {(SIGNED != 0) && dataa[A_WIDTH-1], dataa[A_WIDTH-1:AL]};
        wire signed [BL:0] b_lo = {1'b0, datab[BL-1:0]};
        wire signed [BH:0] b_hi = {(SIGNED != 0) && datab[B_WIDTH-1], datab[B_WIDTH-1:BL]};
`ifdef VIVADO
        (* use_dsp = "yes" *)
`endif
        wire signed [W00-1:0] p00 = a_lo * b_lo;
`ifdef VIVADO
        (* use_dsp = "yes" *)
`endif
        wire signed [W01-1:0] p01 = a_lo * b_hi;
`ifdef VIVADO
        (* use_dsp = "yes" *)
`endif
        wire signed [W10-1:0] p10 = a_hi * b_lo;
`ifdef VIVADO
        (* use_dsp = "yes" *)
`endif
        wire signed [W11-1:0] p11 = a_hi * b_hi;
        reg signed [W00-1:0] q00;
        reg signed [W01-1:0] q01;
        reg signed [W10-1:0] q10;
        reg signed [W11-1:0] q11;
        always_ff @(posedge clk) begin
            if (enable) begin
                q00 <= p00;
                q01 <= p01;
                q10 <= p10;
                q11 <= p11;
            end
        end
        // Result-width truncation can discard entire partial products.
        `UNUSED_VAR ({q00, q01, q10, q11})
        wire [3:0][R_WIDTH-1:0] terms;
        assign terms[0] = R_WIDTH'(q00);
        assign terms[1] = R_WIDTH'(q01) << BL;
        assign terms[2] = R_WIDTH'(q10) << AL;
        assign terms[3] = R_WIDTH'(q11) << (AL + BL);
        wire [R_WIDTH-1:0] sum, carry;
        wire [R_WIDTH-1:0] sum_first = terms[0] ^ terms[1] ^ terms[2];
        wire [R_WIDTH-1:0] carry_first = ((terms[0] & terms[1])
                                      | (terms[0] & terms[2])
                                      | (terms[1] & terms[2])) << 1;
        assign sum = sum_first ^ carry_first ^ terms[3];
        assign carry = ((sum_first & carry_first) | (sum_first & terms[3])
                      | (carry_first & terms[3])) << 1;
        assign prod_w = sum + carry;
    end else begin : g_full
        if (SIGNED != 0) begin : g_prod_s
            assign prod_w = R_WIDTH'($signed(dataa) * $signed(datab));
        end else begin : g_prod_u
            assign prod_w = R_WIDTH'(dataa * datab);
        end
    end

    VX_pipe_register #(
        .DATAW (R_WIDTH),
        .DEPTH (LATENCY - ((PARTIAL_REG != 0) ? 1 : 0))
    ) pipe_reg (
        .clk     (clk),
        .enable  (enable),
        .reset   (1'b0),
        .data_in (prod_w),
        .data_out(result)
    );

endmodule
`TRACING_ON
