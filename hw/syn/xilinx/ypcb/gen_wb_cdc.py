#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import re
from pathlib import Path

from migen import ClockDomain, Module, Signal
from migen.genlib.resetsync import AsyncResetSynchronizer
from litex.build.generic_platform import Pins
from litex.build.xilinx import XilinxPlatform
from litex.soc.interconnect import wishbone


class Crossing(Module):
    def __init__(self, platform):
        self.clock_domains.cd_bus = ClockDomain("bus")
        self.clock_domains.cd_memory = ClockDomain("memory")
        common_reset = Signal()
        self.comb += [
            self.cd_bus.clk.eq(platform.request("bus_clk")),
            self.cd_memory.clk.eq(platform.request("memory_clk")),
            common_reset.eq(platform.request("bus_reset") | platform.request("memory_reset")),
        ]
        # Both FIFO pointers and transaction FSMs must reset together.
        self.specials += [
            AsyncResetSynchronizer(self.cd_bus, common_reset),
            AsyncResetSynchronizer(self.cd_memory, common_reset),
        ]
        source = wishbone.Interface(data_width=32, adr_width=30)
        target = wishbone.Interface(data_width=32, adr_width=30)
        platform.add_extension(source.get_ios("s_wb") + target.get_ios("m_wb"))
        self.comb += source.connect_to_pads(platform.request("s_wb"), mode="slave")
        self.comb += target.connect_to_pads(platform.request("m_wb"), mode="master")
        self.submodules.crossing = wishbone.ClockDomainCrossing(source, target, "bus", "memory")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    platform = XilinxPlatform("xc7k480tffg1156-2", [
        (name, 0, Pins(1)) for name in ("bus_clk", "bus_reset", "memory_clk", "memory_reset")
    ], toolchain="vivado")
    output = platform.get_verilog(Crossing(platform), name="ypcb_wb_cdc")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.write(str(args.output))
    header = args.output.read_text().split(");", 1)[0]
    ports = re.findall(r"^\s*(?:input|output)\s+wire\s+(\[[^\]]+\])?\s*(\w+)", header, re.M)
    args.output.with_name("wb_ports.vh").write_text("".join(
        f"logic {width} {name};\n" for width, name in ports))


if __name__ == "__main__":
    main()
