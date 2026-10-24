#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_channel(path, channel):
    export = json.loads((path / 'selfcal-export.json').read_text())
    profile = export['profile']
    firmware = json.loads((path / 'selfcal_fw/manifest.json').read_text())
    lanes = 8 if channel == 0 else 9
    abi = 5 if channel == 0 else 4
    if (export['controller'] != 'WL7DDRPHY' or export['board_abi'] != abi
            or profile['board_abi'] != abi or profile['eligible_for_synthesis'] is not True
            or profile['physical_lanes'] != lanes
            or profile['ecc'] != (channel == 1) or profile['payload_bytes'] != 2147483648
            or profile['input_clock_hz'] != 50000000 or profile['controller_clock_hz'] != 100000000
            or profile['ddr_data_rate'] != 800000000 or profile['phase_uncertainty_ns'] != 1.3
            or firmware['physical_channel'] != channel or firmware['mailbox_channel'] != 0
            or firmware['ecc'] != (channel == 1) or firmware['memory_bytes'] != 16384):
        raise ValueError('Unexpected DDR800 channel profile: ' + str(path))
    payload = (path / 'selfcal_fw/firmware.bin').read_bytes()
    identity = {Path(name).name: value for name, value in firmware['inputs'].items()}
    identifier = int(hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:8], 16)
    if (not payload or len(payload) > 16384 or len(payload) % 4
            or len(payload) != firmware['bytes'] or len(identity) != len(firmware['inputs'])
            or firmware['firmware_id'] != identifier):
        raise ValueError('Invalid DDR calibration firmware bounds or identity')
    name = 'ypcb_ddr3_ch0.v' if channel == 0 else 'ypcb_ddr3.v'
    files = {path / 'gateware' / name: export['standalone_verilog_sha256'],
             path / 'phase-constraints.tcl': export['phase_constraints_sha256'],
             path / 'selfcal_fw/firmware.bin': firmware['sha256']}
    files.update({Path(name): value for name, value in firmware['inputs'].items()})
    files.update({Path(name): value for name, value in profile['source_sha256'].items()})
    if any(digest(name) != value for name, value in files.items()):
        raise ValueError('A frozen controller source or artifact changed: ' + str(path))
    return export, firmware, name


def scoped_constraints(text, channel):
    prefix = f'ddr_{channel}/'
    lines = text.splitlines()
    if len(lines) != 5 or sum(line.startswith('set_clock_uncertainty ') for line in lines) != 4:
        raise ValueError('Unexpected per-channel phase constraint scope')
    result = []
    for line in lines:
        line = line.replace('NAME =~ */ldmmcm1/', 'NAME =~ ' + prefix + 'ldmmcm1/')
        line = line.replace('NAME =~ *wlrst*', 'NAME =~ ' + prefix + '*wlrst*')
        line = line.replace('{REF_NAME == OSERDESE2 || REF_NAME == ISERDESE2}',
                            '{NAME =~ ' + prefix + '* && (REF_NAME == OSERDESE2 || REF_NAME == ISERDESE2)}')
        if prefix not in line or 'NAME =~ */' in line:
            raise ValueError('Unscoped controller constraint')
        result.append(line)
    return result


def main():
    parser = argparse.ArgumentParser(description='Assemble CH0 spare-lane raw and CH1 ECC DDR800 exports')
    parser.add_argument('--ch0', type=Path, required=True)
    parser.add_argument('--ch1', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError('Dual-channel export requires a fresh directory')
    parents = [args.ch0.resolve(), args.ch1.resolve()]
    inputs = [checked_channel(path, channel) for channel, path in enumerate(parents)]
    output.mkdir(parents=True)
    gateware = output / 'gateware'
    gateware.mkdir()
    sources, constraints, channels = [], [], []
    for channel, (path, (export, firmware, name)) in enumerate(zip(parents, inputs)):
        child = f'ch{channel}'
        shutil.copytree(path, output / child)
        sources.append((path / 'gateware' / name).read_text())
        constraints += scoped_constraints((path / 'phase-constraints.tcl').read_text(), channel)
        channels.append({'physical_channel': channel, 'directory': child,
                         'payload_bytes': 2147483648, 'physical_lanes': 8 if channel == 0 else 9,
                         'physical_data_lanes': [0, 1, 2, 3, 4, 5, 8, 7] if channel == 0 else list(range(8)),
                         'ecc': channel == 1, 'firmware_id': firmware['firmware_id'],
                         'firmware_sha256': firmware['sha256'],
                         'original_export': str(path / 'selfcal-export.json'),
                         'original_export_sha256': digest(path / 'selfcal-export.json')})
    text = '\n'.join(sources)
    modules = re.findall(r'^module\s+(\w+)', text, re.M)
    if len(modules) != len(set(modules)) or '$readmemh' in text:
        raise ValueError('Controller module collision or external initialization data')
    rtl = gateware / 'ypcb_ddr3.v'
    rtl.write_text(text)
    phase = output / 'phase-constraints.tcl'
    phase.write_text('\n'.join(constraints) + '\n')
    profile = {'board_abi': 5, 'input_clock_hz': 50000000, 'controller_clock_hz': 100000000,
               'ddr_data_rate': 800000000, 'payload_bytes': 4294967296,
               'phase_uncertainty_ns': 1.3, 'channels': channels,
               'eligible_for_synthesis': True, 'hardware_qualified': False,
               'source_sha256': {str(Path(__file__).resolve()): digest(Path(__file__).resolve())}}
    metadata = {'status': 'DUAL_DDR800_CONTROLLER_ASSEMBLED_PHYSICAL_QUALIFICATION_PENDING',
                'board_abi': 5, 'controller': 'WL7DDRPHY', 'profile': profile,
                'standalone_verilog_sha256': digest(rtl),
                'phase_constraints_sha256': digest(phase),
                'channel_exports': {'0': 'ch0', '1': 'ch1'},
                'CH1_controller_reused_unchanged': True,
                'new_source_commit_claimed': False, 'hardware_accessed': False}
    (output / 'selfcal-export.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print('YPCB_DUAL_DDR800_CONTROLLER_ASSEMBLED_PHYSICAL_QUALIFICATION_PENDING')


if __name__ == '__main__':
    main()
