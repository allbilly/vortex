#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


CH0_PHYSICAL_LANES = (0, 1, 2, 3, 4, 5, 8, 7)


def generate(reference, package_path, audit_path, top, output, dual_channel=False):
    with package_path.open() as stream:
        package = {row['pin']: row for row in csv.DictReader(stream)}
    ports = {}
    used = set()
    inputs = [package_path, top, reference / 'constraints/ypcb003381p1.xdc', audit_path]
    audit = json.loads(audit_path.read_text())
    if audit['part'] != 'xc7k480tffg1156-2' or len(audit['channels']) != 2:
        raise ValueError('Pin audit does not cover the exact part and both channels')
    for source, digest in audit['inputs'].items():
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Pin audit input changed: {source}')

    def add(name, pin, standard=None):
        if name in ports or pin in used or pin not in package:
            raise ValueError(f'Duplicate or unknown port/pin: {name} {pin}')
        ports[name] = {'pin': pin, 'standard': standard, 'bank': package[pin]['bank']}
        used.add(pin)

    rename = {'addr': 'a', 'ck_p': 'clk_p', 'ck_n': 'clk_n'}
    scalars = {'cke', 'cs_n', 'odt', 'ck_p', 'ck_n'}
    banks = (0, 1) if dual_channel else (1,)
    exported_channels = {}
    for bank in banks:
        project = reference / f'ypcb003381p1/1.0/mig_{bank}.prj'
        inputs.append(project)
        tree = ET.parse(project)
        if tree.findtext('TargetFPGA') != 'xc7k480t-ffg1156/-2':
            raise ValueError('MIG reference does not match the selected FPGA')
        if tree.findtext('InternalVref') != '0':
            raise ValueError('MIG reference must retain the board external-VREF profile')
        channel_start = len(ports)
        physical_count = 0
        physical_widths = {'dq': set(), 'dqs_p': set(), 'dqs_n': set()}
        physical_to_logical_lane = {physical: logical
                                    for logical, physical in enumerate(CH0_PHYSICAL_LANES)}
        for pin in tree.iter('Pin'):
            if not pin.attrib['name'].startswith('ddr3_'):
                continue
            physical_count += 1
            match = re.fullmatch(r'ddr3_(\w+)(\[\d+\])?', pin.attrib['name'])
            if match is None:
                raise ValueError(f'Unsupported MIG pin: {pin.attrib}')
            signal, index = match.groups()
            if signal in scalars:
                if index != '[0]':
                    raise ValueError(f'Unexpected scalar width: {signal}{index}')
                index = ''
            physical_index = int(index[1:-1]) if index else 0
            if signal in physical_widths:
                physical_widths[signal].add(physical_index)
            port_index = physical_index
            if dual_channel and bank == 0 and signal == 'dq':
                physical_lane, bit_in_lane = divmod(physical_index, 8)
                logical_lane = physical_to_logical_lane.get(physical_lane)
                if logical_lane is None:
                    continue
                port_index = logical_lane * 8 + bit_in_lane
            elif dual_channel and bank == 0 and signal in ('dqs_p', 'dqs_n'):
                logical_lane = physical_to_logical_lane.get(physical_index)
                if logical_lane is None:
                    continue
                port_index = logical_lane
            port_suffix = f'[{port_index}]' if index else ''
            name = f'ddr{bank}_{rename.get(signal, signal)}{port_suffix}'
            standard = 'DIFF_SSTL15' if signal in ('ck_p', 'ck_n', 'dqs_p', 'dqs_n') else 'SSTL15'
            profile = audit['channels'][bank]['ports'][rename.get(signal, signal)]
            if (physical_index >= len(profile['pins'])
                    or profile['pins'][physical_index] != pin.attrib['PADName']
                    or profile['iostandard'] != standard):
                raise ValueError(f'MIG/pin-profile mismatch: {name}')
            if signal in ('dq', 'dqs_p', 'dqs_n') and profile['misc'] != ['IN_TERM=UNTUNED_SPLIT_40']:
                raise ValueError(f'Unexpected DDR termination profile: {name}')
            add(name, pin.attrib['PADName'], standard)
        if physical_count != 117:
            raise ValueError(f'Channel {bank} MIG reference must expose all 117 physical DDR pins')
        if (physical_widths['dq'] != set(range(72))
                or physical_widths['dqs_p'] != set(range(9))
                or physical_widths['dqs_n'] != set(range(9))):
            raise ValueError(f'Channel {bank} MIG reference has unexpected physical data/strobe widths')
        expected_count = 107 if dual_channel and bank == 0 else 117
        if len(ports) - channel_start != expected_count:
            raise ValueError(f'Channel {bank} exported {len(ports) - channel_start} DDR pins; expected {expected_count}')
        exported_channels[str(bank)] = {
            'physical_project': str(project),
            'physical_pin_count': physical_count,
            'exported_pin_count': expected_count,
        }

    board_xdc = inputs[2].read_text()
    gpio = {'SYS_CLK': 'SYS_CLK', 'SYS_RSTN': 'SYS_RSTN', 'pcie_perstn': 'pcie_perstn'}
    for name, original in gpio.items():
        pin = re.search(r'set_property PACKAGE_PIN (\w+) \[get_ports ' + original + r'\]', board_xdc)
        standard = re.search(r'set_property IOSTANDARD (\w+) \[get_ports ' + original + r'\]', board_xdc)
        if pin is None or standard is None or standard[1] != 'LVCMOS18':
            raise ValueError(f'Missing reviewed board GPIO: {original}')
        add(name, pin[1], standard[1])
    for name, pin in {'pcie_refclk_p': 'J8', 'pcie_refclk_n': 'J7', 'pci_exp_txp': 'F2',
                      'pci_exp_txn': 'F1', 'pci_exp_rxp': 'H6', 'pci_exp_rxn': 'H5'}.items():
        if 'MGT' not in package[pin]['pin_function']:
            raise ValueError(f'PCIe pin is not a transceiver pin: {pin}')
        add(name, pin)

    header = top.read_text().split(');', 1)[0]
    if not dual_channel:
        header = re.sub(r'`ifdef VX_CFG_YPCB_DUAL_CHANNEL_ENABLE\n.*?`endif', '', header, flags=re.S)
    declared = set()
    for width, name in re.findall(r'^\s*(?:input|output|inout)\s+wire\s*(\[\d+:0\])?\s+(\w+)', header, re.M):
        if width:
            declared.update(f'{name}[{i}]' for i in range(int(width[1:].split(':')[0]) + 1))
        else:
            declared.add(name)
    if declared != set(ports):
        raise ValueError(f'Top/pin mismatch: missing={sorted(declared - set(ports))}, extra={sorted(set(ports) - declared)}')

    lines = ['# Source-checked YPCB-00338-1P1 reference profile; physical supplies unverified.']
    for name, item in ports.items():
        lines.append(f'set_property PACKAGE_PIN {item["pin"]} [get_ports {{{name}}}]')
        if item['standard']:
            lines.append(f'set_property IOSTANDARD {item["standard"]} [get_ports {{{name}}}]')
        if name.startswith('ddr'):
            lines.append(f'set_property SLEW FAST [get_ports {{{name}}}]')
            if re.match(r'ddr[01]_(dq|dqs_p|dqs_n)\[', name):
                lines.append(f'set_property IN_TERM UNTUNED_SPLIT_40 [get_ports {{{name}}}]')
    for bank in sorted({item['bank'] for name, item in ports.items() if name.startswith('ddr')}):
        lines.append(f'reset_property INTERNAL_VREF [get_iobanks {bank}]')
    lines.extend(['create_clock -period 20.000 [get_ports SYS_CLK]',
                  'create_clock -period 10.000 [get_ports pcie_refclk_p]'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines) + '\n')
    manifest = {'status': 'SOURCE_PIN_COVERAGE_PASS_PHYSICAL_PROFILE_UNVERIFIED',
                'part': 'xc7k480tffg1156-2', 'top': str(top), 'pins': ports,
                'dual_channel': dual_channel,
                'channels': exported_channels,
                'ch0_physical_lane_order': list(CH0_PHYSICAL_LANES) if dual_channel else None,
                'unique_pins': len(ports), 'physical_supplies_verified': False,
                'reference_vref_mode': 'external',
                'timing_signoff': False,
                'inputs': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
                'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    output.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'PASS: all {len(ports)} top pins source-checked; physical supplies and timing unverified')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--top', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dual-channel', action='store_true',
                        help='export audited CH0 spare-lane 8x8-bit data plus unchanged 9-lane CH1')
    args = parser.parse_args()
    generate(args.reference, args.package, args.audit, args.top, args.output,
             dual_channel=args.dual_channel)


if __name__ == '__main__':
    main()
