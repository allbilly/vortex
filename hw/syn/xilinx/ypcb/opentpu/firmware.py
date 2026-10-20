#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import hashlib
import json
from pathlib import Path
import random
import re
import subprocess

HERE = Path(__file__).resolve().parent
BOARD = HERE.parent
MEMORY_BYTES = 16384


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def header(directory):
    csr = json.loads((directory / 'csr.json').read_text())
    phy = (directory / 'software/include/generated/sdram_phy.h').read_text()
    if (csr['cores']['ddrphy'] != 'WL7DDRPHY'
            or csr['cores']['ecc_axi_0'] != 'LiteDRAMNativePortECC'
            or csr['constants']['config_clock_frequency'] != 100000000
            or csr['constants']['config_csr_data_width'] != 32
            or 'config_csr_ordering_big' not in csr['constants']):
        raise ValueError('Unexpected CH1 WL controller metadata')
    definitions = {name: int(value, 0) for name, value in
                   re.findall(r'^#define (\w+) (0x[0-9a-fA-F]+|[0-9]+)\s*$', phy, re.M)}
    expected = {'SDRAM_PHY_DATABITS': 72, 'SDRAM_PHY_DFI_DATABITS': 144,
                'SDRAM_PHY_PHASES': 4, 'SDRAM_PHY_MODULES': 9, 'SDRAM_PHY_DELAYS': 32,
                'SDRAM_PHY_BITSLIPS': 8, 'SDRAM_PHY_CL': 6, 'SDRAM_PHY_CWL': 5}
    if any(definitions.get(name) != value for name, value in expected.items()):
        raise ValueError('Unexpected CH1 DDR800 geometry')
    registers = csr['csr_registers']
    occupied = set()
    for name, reg in registers.items():
        width = (5 if name.endswith(('_wrdata', '_rddata')) else
                 2 if name == 'ddrctrl_bist_seed' else
                 3 if name == 'ddrctrl_bist_lane_bits' else 1)
        address = reg['addr']
        words = set(range(address, address + 4 * reg['size'], 4))
        if address % 4 or address < 0 or address + 4 * reg['size'] > 0x2000 \
                or reg['size'] != width or words & occupied:
            raise ValueError('Invalid WL CSR layout: ' + name)
        occupied.update(words)

    def address(name, width=1):
        reg = registers[name]
        if reg['size'] != width:
            raise ValueError('Unexpected CSR width: ' + name)
        return f"0x{reg['addr']:x}u"

    body = re.search(r'static inline void init_sequence\(void\)\s*\{([^{}]*)\}', phy, re.S)
    if body is None:
        raise ValueError('Missing generated JEDEC initialization')
    body = re.sub(r'/\*.*?\*/', '', body[1], flags=re.S).strip()
    sequence, row, bank = [], 0, 0
    while body:
        call = re.match(r'(\w+)\(([^();]+)\);\s*', body)
        if call is None:
            raise ValueError('Unsupported JEDEC initialization statement')
        function, expression = call.group(1, 2)
        value = 0
        for token in expression.split('|'):
            token = token.strip()
            if token in definitions:
                value |= definitions[token]
            elif re.fullmatch(r'0x[0-9a-fA-F]+|[0-9]+', token):
                value |= int(token, 0)
            else:
                raise ValueError('Unsupported JEDEC value: ' + token)
        if function == 'sdram_dfii_pi0_address_write':
            row = value
        elif function == 'sdram_dfii_pi0_baddress_write':
            bank = value
        elif function in ('sdram_dfii_control_write', 'command_p0'):
            sequence.append([row, bank, value, 2000, int(function == 'sdram_dfii_control_write')])
        elif function == 'cdelay' and sequence and value > 0:
            sequence[-1][3] = max(value * 4, 2000)
        else:
            raise ValueError('Unsupported JEDEC call: ' + function)
        body = body[call.end():].strip()
    if len(sequence) != 7:
        raise ValueError('Unexpected DDR3 initialization sequence')
    lines = ['#pragma once', '#include <stdint.h>',
             '#define SYS_HZ 100000000u', '#define NCH 1', '#define NM 9', '#define NPH 4',
             '#define NDELAYS 32', '#define NBITSLIPS 8', '#define PERIOD 112', '#define WRAP 112',
             '#define MIN_WINDOW 3', '#define N_SEEDS 3', '#define SCAN_SEEDS 1',
             '#define PAT_WORDS 5', '#define WAIT_1MS 100000u', '#define WAIT_1S 100000000u',
             '#define WAIT_60S 6000000000ull', '#define BIST_MIB 64',
             '#define BIST_SEED0 0x0123456789ABCDEFull',
             f"#define RDPHASE {definitions['SDRAM_PHY_RDPHASE']}",
             f"#define WRPHASE {definitions['SDRAM_PHY_WRPHASE']}",
             '#define N_INIT 7']
    for macro, name in {'CSR_SELFCAL_STATE': 'ddrctrl_selfcal_state',
                        'CSR_INIT_DONE': 'ddrctrl_init_done', 'CSR_INIT_ERROR': 'ddrctrl_init_error',
                        'CSR_ECC_ENABLE': 'ecc_axi_0_enable', 'CSR_DFII_CONTROL': 'sdram_dfii_control',
                        'CSR_DLY_SEL': 'ddrphy_dly_sel'}.items():
        lines.append(f'#define {macro} {address(name)}')
    lines.append('static const struct { uint32_t a, ba, cmd, wait, control; } INIT_SEQ[N_INIT] = {')
    lines.extend('    {' + ', '.join(str(v) for v in operation) + '},' for operation in sequence)
    lines += ['};', 'static const uint32_t PAT[N_SEEDS][NPH][PAT_WORDS] = {']
    for seed in (42, 84, 36):
        rng = random.Random(seed)
        patterns = [rng.getrandbits(144) for _ in range(4)]
        lines.append('    {' + ', '.join('{' + ', '.join(f'0x{(v >> (32 * (4 - i))) & 0xffffffff:08x}u'
                                                     for i in range(5)) + '}' for v in patterns) + '},')
    lines += ['};', 'struct ch_csr {',
              '    uint32_t rst, dly_sel, rdly_dq_rst, rdly_dq_inc, rdly_dq_bitslip_rst, rdly_dq_bitslip;',
              '    uint32_t wdly_dq_bitslip_rst, wdly_dq_bitslip, rdphase, wrphase, dly_sel_bits;',
              '    uint32_t dfii_control, pi_command[NPH], pi_command_issue[NPH], pi_address[NPH];',
              '    uint32_t pi_baddress[NPH], pi_wrdata[NPH], pi_rddata[NPH];',
              '    uint32_t bist_start, bist_mode, bist_base, bist_length, bist_seed, bist_done;',
              '    uint32_t bist_lane_errors[NM];',
              '    uint32_t dqs_shift, dqs_busy, dqs_steps;',
              '    uint32_t mmcm_reset, mmcm_locked, drp_adr, drp_dat_w, drp_dat_r, drp_read, drp_write, drp_drdy;',
              '    uint32_t cal_ready;', '    uint8_t per_bit, has_bist, has_ready, wl_groups, groups[NM];',
              '};', 'static const struct ch_csr CH[NCH] = {{']
    names = ['ddrphy_' + n for n in ('rst', 'dly_sel', 'rdly_dq_rst', 'rdly_dq_inc',
             'rdly_dq_bitslip_rst', 'rdly_dq_bitslip', 'wdly_dq_bitslip_rst', 'wdly_dq_bitslip',
             'rdphase', 'wrphase', 'dly_sel_bits')]
    lines.append('    ' + ', '.join(address(n) for n in names) + ',')
    lines.append('    ' + address('sdram_dfii_control') + ',')
    for suffix in ('command', 'command_issue', 'address', 'baddress', 'wrdata', 'rddata'):
        lines.append('    {' + ', '.join(address(f'sdram_dfii_pi{p}_{suffix}',
                                               5 if suffix in ('wrdata', 'rddata') else 1)
                                          for p in range(4)) + '},')
    for group in (['ddrctrl_bist_' + n for n in ('start', 'mode', 'base', 'length', 'seed', 'done')],
                  ['ddrctrl_phase_dqs_' + n for n in ('shift', 'busy', 'steps')],
                  ['ddrctrl_write_clocks_' + n for n in ('mmcm_reset', 'mmcm_locked', 'drp_adr',
                   'drp_dat_w', 'drp_dat_r', 'drp_read', 'drp_write', 'drp_drdy')]):
        lines.append('    ' + ', '.join(address(n, 2 if n == 'ddrctrl_bist_seed' else 1) for n in group) + ',')
        if group[0] == 'ddrctrl_bist_start':
            lines.append('    {' + ', '.join(address(f'ddrctrl_bist_lane{m}_errors') for m in range(9)) + '},')
    lines += ['    0xffffffffu,', '    1, 1, 0, 1, {0, 0, 0, 0, 0, 0, 0, 0, 0}', '}};', '']
    return '\n'.join(lines)


def build(soc, output, compiler):
    directory = output / 'selfcal_fw'
    directory.mkdir(exist_ok=True)
    configuration = directory / 'selfcal_cfg.h'
    configuration.write_text(header(output))
    sources = [HERE / 'selfcal_fw' / name for name in ('cal.c', 'cal.h', 'hw.h', 'main.c', 'arith.c')]
    sources += [BOARD / 'selfcal_fw' / name for name in ('crt0.S', 'link.ld', 'memory.c')]
    sources += [configuration, Path(__file__)]
    inputs = {str(p): digest(p) for p in sources}
    identity = {p.name: inputs[str(p)] for p in sources}
    identifier = int(hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:8], 16)
    command = [str(compiler), '-march=rv32i', '-mabi=ilp32', '-O2', '-ffreestanding', '-nostdlib',
               '-msmall-data-limit=0', '-mno-relax', '-fno-builtin', '-fno-stack-protector',
               '-fno-tree-loop-distribute-patterns', '-Wall', '-Wextra', '-Werror',
               f'-DFW_ID=0x{identifier:08x}u', '-I' + str(directory),
               '-I' + str(HERE / 'selfcal_fw'), str(BOARD / 'selfcal_fw/crt0.S'),
               str(HERE / 'selfcal_fw/cal.c'), str(HERE / 'selfcal_fw/main.c'),
               str(HERE / 'selfcal_fw/arith.c'),
               str(BOARD / 'selfcal_fw/memory.c'), '-Wl,-T,' + str(BOARD / 'selfcal_fw/link.ld'),
               '-Wl,--no-relax', '-Wl,-Map,' + str(directory / 'firmware.map'),
               '-o', str(directory / 'firmware.elf')]
    subprocess.run(command, check=True)
    prefix = compiler.name.removesuffix('gcc')
    if prefix == compiler.name:
        raise ValueError('Expected the pinned RISC-V GNU compiler')
    subprocess.run([str(compiler.with_name(prefix + 'objcopy')), '-O', 'binary',
                    str(directory / 'firmware.elf'), str(directory / 'firmware.bin')], check=True)
    payload = (directory / 'firmware.bin').read_bytes()
    if not payload or len(payload) > MEMORY_BYTES:
        raise ValueError('WL firmware exceeds calibration BRAM')
    payload = payload.ljust(MEMORY_BYTES, b'\0')
    soc.ddrctrl.selfcal.set_firmware([int.from_bytes(payload[i:i + 4], 'little')
                                    for i in range(0, MEMORY_BYTES, 4)])
    metadata = {'firmware_id': identifier, 'bytes': (directory / 'firmware.bin').stat().st_size,
                'memory_bytes': MEMORY_BYTES, 'mailbox_words': 128, 'physical_channel': 1,
                'mailbox_channel': 0, 'mailbox_magic': 0x53435231, 'phase_period_steps': 112,
                'phase_stride': 1, 'bist_mib_per_phase': 64, 'ecc': True,
                'sha256': digest(directory / 'firmware.bin'), 'inputs': inputs, 'command': command}
    (directory / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
