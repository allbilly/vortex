#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
from pathlib import Path
import sys

from migen.fhdl import verilog
from litex.build.xilinx import XilinxPlatform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selfcal import CalibrationCpu, MEM_BYTES
from gen_ddr import standalone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.firmware.read_bytes()
    if len(data) > MEM_BYTES:
        raise ValueError('Firmware exceeds BRAM')
    data += bytes(MEM_BYTES - len(data))
    words = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, MEM_BYTES, 4)]
    platform = XilinxPlatform('', io=[], toolchain='vivado')
    cpu = CalibrationCpu(platform, firmware=words)
    cpu.status.finalize(32, 'big')
    cpu.submodules += cpu.status
    ports = {'hold': cpu.hold.storage, 'status': cpu.status.status,
             'mbox_adr': cpu.mbox_adr.storage, 'mbox_dat': cpu.mbox_dat.status,
             'mem_adr': cpu.mem_adr.storage, 'mem_dat': cpu.mem_dat.storage,
             'mem_we': cpu.mem_dat.re, 'mem_rdat': cpu.mem_rdat.status}
    for name in ('adr', 'dat_w', 'dat_r', 'sel', 'we', 'cyc', 'stb', 'ack', 'err'):
        ports['wb_' + name] = getattr(cpu.bus, name)
    for name, signal in ports.items():
        signal.name_override = name
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = verilog.convert(cpu, ios=set(ports.values()), name='selfcal_top')
    args.output.write_text(result.main_source)
    for name, content in result.data_files.items():
        (args.output.parent / name).write_text(content)
    standalone(args.output, platform.sources)


if __name__ == '__main__':
    main()
