#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import re
from pathlib import Path

from migen import ClockDomain, Module
from litex.build.generic_platform import Pins
from litex.build.xilinx import XilinxPlatform
from litex.soc.interconnect import stream
from litex.soc.interconnect.axi import AXIInterface


class Crossing(Module):
    def __init__(self, platform):
        self.clock_domains.cd_bus = ClockDomain("bus")
        self.clock_domains.cd_memory = ClockDomain("memory")
        self.comb += [
            self.cd_bus.clk.eq(platform.request("bus_clk")),
            self.cd_bus.rst.eq(platform.request("bus_reset")),
            self.cd_memory.clk.eq(platform.request("memory_clk")),
            self.cd_memory.rst.eq(platform.request("memory_reset")),
        ]
        source = AXIInterface(data_width=512, address_width=31, id_width=8)
        target = AXIInterface(data_width=512, address_width=31, id_width=8)
        platform.add_extension(source.get_ios("s_axi") + target.get_ios("m_axi"))
        self.comb += source.connect_to_pads(platform.request("s_axi"), mode="slave")
        self.comb += target.connect_to_pads(platform.request("m_axi"), mode="master")
        for name in ("aw", "w", "b", "ar", "r"):
            upstream, downstream = getattr(source, name), getattr(target, name)
            from_domain, to_domain = "bus", "memory"
            if name in ("b", "r"):
                upstream, downstream = downstream, upstream
                from_domain, to_domain = to_domain, from_domain
            fifo = stream.ClockDomainCrossing(upstream.description, from_domain,
                                              to_domain, depth=4, with_common_rst=True)
            self.submodules += fifo
            self.comb += [upstream.connect(fifo.sink), fifo.source.connect(downstream)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    platform = XilinxPlatform("xc7k480tffg1156-2", [
        (name, 0, Pins(1)) for name in ("bus_clk", "bus_reset", "memory_clk", "memory_reset")
    ], toolchain="vivado")
    output = platform.get_verilog(Crossing(platform), name="ypcb_axi_cdc")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.write(str(args.output))
    header = args.output.read_text().split(");", 1)[0]
    ports = re.findall(r"^\s*(?:input|output)\s+wire\s+(\[[^\]]+\])?\s*(\w+)", header, re.M)
    args.output.with_name("ports.vh").write_text("".join(
        f"logic {width} {name};\n" for width, name in ports))


if __name__ == "__main__":
    main()
