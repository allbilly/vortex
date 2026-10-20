#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml
from litex.build.xilinx import XilinxPlatform
from litex.soc.integration.builder import Builder
from litedram.gen import LiteDRAMCore
from litedram import modules, phy

from selfcal import CalibrationCpu, MEM_BYTES

BOARD = Path(__file__).resolve().parent
ROOT = BOARD.parents[3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def firmware(soc, output, compiler):
    directory = output / 'selfcal_fw'
    directory.mkdir(exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / 'ci/ypcb_ddr_config.py'), '--ddr', str(output),
                    '--output', str(directory / 'config.h'), '--c-header'], check=True)
    sources = [BOARD / 'selfcal_fw' / name for name in
               ('calibrate.c', 'calibrate.h', 'memory.c', 'crt0.S', 'link.ld', 'io.h')]
    sources += [ROOT / 'sw/common/ypcb_calibration_abi.h', directory / 'config.h']
    hashes = {str(path): digest(path) for path in sources}
    identity = {path.name: hashes[str(path)] for path in sources}
    identifier = int(hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:8], 16)
    command = [str(compiler), '-march=rv32i', '-mabi=ilp32', '-std=c11', '-O2', '-ffreestanding',
               '-nostdlib', '-msmall-data-limit=0', '-mno-relax', '-fno-builtin', '-fno-stack-protector',
               '-fno-tree-loop-distribute-patterns', '-fdata-sections', '-ffunction-sections',
               '-Wall', '-Wextra', '-Werror', '-DFW_ID=0x%xu' % identifier,
               '-I' + str(directory), '-I' + str(ROOT / 'sw/common'),
               str(BOARD / 'selfcal_fw/crt0.S'), str(BOARD / 'selfcal_fw/calibrate.c'),
               str(BOARD / 'selfcal_fw/memory.c'),
               '-Wl,-T,' + str(BOARD / 'selfcal_fw/link.ld'), '-Wl,--gc-sections,--no-relax',
               '-Wl,-Map,' + str(directory / 'firmware.map'), '-o', str(directory / 'firmware.elf')]
    subprocess.run(command, check=True)
    prefix = compiler.name.removesuffix('gcc')
    if prefix == compiler.name:
        raise ValueError('Calibration firmware requires the pinned RISC-V GNU compiler')
    objcopy = compiler.with_name(prefix + 'objcopy')
    subprocess.run([str(objcopy), '-O', 'binary', str(directory / 'firmware.elf'),
                    str(directory / 'firmware.bin')], check=True)
    data = (directory / 'firmware.bin').read_bytes()
    if len(data) > MEM_BYTES:
        raise ValueError('Calibration firmware exceeds its BRAM')
    padded = data + bytes(MEM_BYTES - len(data))
    soc.ddrctrl.selfcal.set_firmware([int.from_bytes(padded[index:index + 4], 'little')
                                    for index in range(0, MEM_BYTES, 4)])
    metadata = {'firmware_id': identifier, 'bytes': len(data), 'memory_bytes': MEM_BYTES,
                'sha256': hashlib.sha256(data).hexdigest(), 'inputs': hashes, 'command': command,
                'compiler_version': subprocess.check_output([str(compiler), '--version'], text=True).splitlines()[0]}
    (directory / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')


class CalibrationBuilder(Builder):
    def __init__(self, soc, output, compiler):
        super().__init__(soc, output_dir=str(output), compile_software=False, compile_gateware=False,
                         csr_json=str(output / 'csr.json'), csr_csv=str(output / 'csr.csv'))
        self.calibration_output = output
        self.calibration_compiler = compiler

    def _generate_csr_map(self):
        super()._generate_csr_map()
        firmware(self.soc, self.calibration_output, self.calibration_compiler)


def standalone(path, sources):
    text = path.read_text()
    initializations = {}

    def inline(match):
        name, memory = match.group(1, 2)
        source = path.parent / name
        values = source.read_text().split()
        initializations[name] = digest(source)
        return '\n'.join(f"{memory}[{index}] = 'h{value};" for index, value in enumerate(values))

    text = re.sub(r'\$readmemh\("([^"]+)",\s*([A-Za-z0-9_]+)\);', inline, text)
    external = {}
    for filename, *_ in sorted(sources):
        source = Path(filename)
        if source.resolve() == path.resolve():
            continue
        if source.suffix != '.v':
            raise ValueError('Unsupported calibration CPU source: ' + str(source))
        body = source.read_text()
        names = re.findall(r'^module\s+([A-Za-z_][A-Za-z0-9_]*)', body, re.M)
        if not names:
            raise ValueError('Missing external CPU modules: ' + str(source))
        pattern = r'\b(' + '|'.join(re.escape(name) for name in names) + r')\b'
        rename = lambda match: 'ypcb_selfcal_' + match[1]
        text = re.sub(pattern, rename, text)
        text += '\n' + re.sub(pattern, rename, body)
        external[str(source)] = digest(source)
    if '$readmemh' in text:
        raise ValueError('Standalone calibration export still has external initialization data')
    path.write_text(text)
    return {'initialization_files': initializations, 'external_sources': external,
            'standalone_verilog_sha256': digest(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cc', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Controller export requires a fresh output directory')
    if importlib.metadata.version('pythondata-cpu-vexriscv') != '1.0.1.post407':
        raise ValueError('Unexpected calibration CPU RTL package version')
    config = yaml.safe_load(args.config.read_text())
    for name, value in list(config.items()):
        if isinstance(value, str) and value in ('False', 'True', 'None'):
            config[name] = {'False': False, 'True': True, 'None': None}[value]
        if 'clk_freq' in name:
            config[name] = float(config[name])
    config['sdram_module'] = getattr(modules, config['sdram_module'])
    config['sdram_phy'] = getattr(phy, config['sdram_phy'])
    if config['cpu'] is not None or config['sys_clk_freq'] != 100e6:
        raise ValueError('CH1 calibration export preserves the external control port at 100 MHz')
    platform = XilinxPlatform('', io=[], toolchain='vivado')
    soc = LiteDRAMCore(platform, config, integrated_rom_size=0)
    soc.ddrctrl.selfcal = CalibrationCpu(platform)
    soc.bus.add_master(name='selfcal', master=soc.ddrctrl.selfcal.bus)
    builder = CalibrationBuilder(soc, output, args.cc.resolve())
    builder.build(build_name='ypcb_ddr3')
    path = output / 'gateware/ypcb_ddr3.v'
    metadata = standalone(path, platform.sources)
    metadata['cpu_rtl_package'] = 'pythondata-cpu-vexriscv==1.0.1.post407'
    metadata['configuration_sha256'] = digest(args.config)
    (output / 'selfcal-export.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('YPCB_CH1_LOCAL_CALIBRATION_CONTROLLER_EXPORTED')


if __name__ == '__main__':
    main()
