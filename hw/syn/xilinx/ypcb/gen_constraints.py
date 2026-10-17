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


def generate(reference, package_path, audit_path, top, output):
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
    for bank in range(2):
        project = reference / f'ypcb003381p1/1.0/mig_{bank}.prj'
        inputs.append(project)
        tree = ET.parse(project)
        if tree.findtext('TargetFPGA') != 'xc7k480t-ffg1156/-2':
            raise ValueError('MIG reference does not match the selected FPGA')
        if tree.findtext('InternalVref') != '0':
            raise ValueError('MIG reference must retain the board external-VREF profile')
        for pin in tree.iter('Pin'):
            if not pin.attrib['name'].startswith('ddr3_'):
                continue
            match = re.fullmatch(r'ddr3_(\w+)(\[\d+\])?', pin.attrib['name'])
            if match is None:
                raise ValueError(f'Unsupported MIG pin: {pin.attrib}')
            signal, index = match.groups()
            if signal in scalars:
                if index != '[0]':
                    raise ValueError(f'Unexpected scalar width: {signal}{index}')
                index = ''
            name = f'ddr{bank}_{rename.get(signal, signal)}{index or ""}'
            standard = 'DIFF_SSTL15' if signal in ('ck_p', 'ck_n', 'dqs_p', 'dqs_n') else 'SSTL15'
            profile = audit['channels'][bank]['ports'][rename.get(signal, signal)]
            number = int(match[2][1:-1]) if match[2] else 0
            if profile['pins'][number] != pin.attrib['PADName'] or profile['iostandard'] != standard:
                raise ValueError(f'MIG/pin-profile mismatch: {name}')
            if signal in ('dq', 'dqs_p', 'dqs_n') and profile['misc'] != ['IN_TERM=UNTUNED_SPLIT_40']:
                raise ValueError(f'Unexpected DDR termination profile: {name}')
            add(name, pin.attrib['PADName'], standard)
        if len(ports) != (bank + 1) * 117:
            raise ValueError('Each board channel must expose all 117 DDR pins')

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
    args = parser.parse_args()
    generate(args.reference, args.package, args.audit, args.top, args.output)


if __name__ == '__main__':
    main()
