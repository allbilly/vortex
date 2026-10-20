#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(ddr, output):
    csr_file = ddr / 'csr.json'
    firmware_file = ddr / 'selfcal_fw/manifest.json'
    csr = json.loads(csr_file.read_text())
    firmware = json.loads(firmware_file.read_text())
    expected = {'memory_bytes': 16384, 'mailbox_words': 128, 'physical_channel': 1,
                'mailbox_channel': 0, 'mailbox_magic': 0x53435231,
                'phase_period_steps': 112, 'phase_stride': 1, 'bist_mib_per_phase': 64, 'ecc': True}
    if (any(firmware.get(k) != v for k, v in expected.items())
            or csr['cores']['ddrphy'] != 'WL7DDRPHY'
            or csr['cores']['ecc_axi_0'] != 'LiteDRAMNativePortECC'
            or csr['constants']['config_clock_frequency'] != 100000000
            or csr['constants']['config_csr_data_width'] != 32
            or csr['constants']['config_csr_alignment'] != 32
            or 'config_csr_ordering_big' not in csr['constants']):
        raise ValueError('Unexpected CH1 WL calibration profile')
    if digest(ddr / 'selfcal_fw/firmware.bin') != firmware['sha256']:
        raise ValueError('Calibration firmware changed')
    identity = {}
    for name, expected_hash in firmware['inputs'].items():
        path = Path(name)
        if digest(path) != expected_hash or path.name in identity:
            raise ValueError('Calibration firmware input changed: ' + name)
        identity[path.name] = expected_hash
    identifier = int(hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:8], 16)
    if identifier != firmware['firmware_id']:
        raise ValueError('Calibration identity does not match its inputs')
    occupied = set()
    lines = ['#pragma once', '#include <cstdint>', '', 'namespace vortex::ypcb::wl_config {',
             'inline constexpr uint32_t board_abi = 4;',
             f'inline constexpr uint32_t calibration_firmware_id = 0x{identifier:08x}u;',
             'inline constexpr uint32_t mailbox_magic = 0x53435231u;',
             'inline constexpr uint32_t sys_clock_hz = 100000000;',
             'inline constexpr uint32_t phase_period = 112;',
             'inline constexpr uint32_t phase_stride = 1;']
    for name, reg in sorted(csr['csr_registers'].items()):
        address, size = reg['addr'], reg['size']
        width = (5 if name.endswith(('_wrdata', '_rddata')) else
                 2 if name == 'ddrctrl_bist_seed' else
                 3 if name == 'ddrctrl_bist_lane_bits' else 1)
        words = set(range(address, address + size * 4, 4))
        if (address % 4 or address < 0 or size != width or address + size * 4 > 0x2000
                or occupied & words):
            raise ValueError('Invalid WL CSR register: ' + name)
        occupied.update(words)
        lines.append(f'inline constexpr uint32_t {name} = 0x{address:x}u;')
    lines += ['}', '']
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines))
    files = [csr_file, firmware_file, ddr / 'selfcal_fw/firmware.bin',
             ddr / 'software/include/generated/sdram_phy.h', ddr / 'gateware/ypcb_ddr3.v']
    output.with_suffix('.json').write_text(json.dumps(
        {'inputs': {str(p.resolve()): digest(p) for p in files}, 'output_sha256': digest(output),
         'board_abi': 4, 'physical_channel': 1, 'payload_bytes': 2147483648, 'ecc': True}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ddr', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    generate(args.ddr.resolve(), args.output.resolve())
