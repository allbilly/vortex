// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

interface VX_ypcb_frontend_if;
    logic [7:0] data;
    modport master (output data);
    modport slave (input data);
endinterface

module VX_ypcb_frontend_source #(parameter MASK = 8'h00) (
    VX_ypcb_frontend_if.master link,
    input wire [7:0] value
);
    assign link.data = value ^ MASK;
endmodule

module VX_ypcb_frontend_forward (VX_ypcb_frontend_if.slave src, VX_ypcb_frontend_if.master dst);
    assign dst.data = {src.data[7:4], src.data[3:0]};
endmodule

module VX_ypcb_frontend_middle #(parameter MASK = 8'h00) (
    VX_ypcb_frontend_if.master outgoing,
    input wire [7:0] value
);
    VX_ypcb_frontend_if internal_bus();
    VX_ypcb_frontend_source #(.MASK(MASK)) source (.link(internal_bus), .value(value));
    VX_ypcb_frontend_forward forwarder (.src(internal_bus), .dst(outgoing));
endmodule

module VX_ypcb_frontend_wrapped #(parameter MASK = 8'h00) (
    input wire [7:0] value,
    output wire [7:0] result
);
    VX_ypcb_frontend_if bus();
    VX_ypcb_frontend_middle #(.MASK(MASK)) middle (.outgoing(bus), .value(value));
    assign result = bus.data;
endmodule

module VX_ypcb_frontend_test (input wire [7:0] value, output wire correct);
    wire [7:0] first, second;
    VX_ypcb_frontend_wrapped #(.MASK(8'h5a)) a (.value(value), .result(first));
    VX_ypcb_frontend_wrapped #(.MASK(8'hc3)) b (.value(value), .result(second));
    assign correct = first == (value ^ 8'h5a) && second == (value ^ 8'hc3);
endmodule
