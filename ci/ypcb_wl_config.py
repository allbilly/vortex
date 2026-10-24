#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


MAILBOX_MAGIC = 0x53435231
PHASE_PERIOD = 112
PHASE_STRIDE = 1
DDR_PAYLOAD_BYTES = 2147483648
DUAL_PAYLOAD_BYTES = 4294967296
FIRMWARE_BYTES = 16384
DFI_PHASES = 4


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text())


def bind_file(path, files, expected=None):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Missing controller input: ' + str(path))
    actual = digest(path)
    if expected is not None and actual != expected:
        raise ValueError('Controller input hash mismatch: ' + str(path))
    key = str(path)
    if key in files and files[key] != actual:
        raise ValueError('Controller input has conflicting hashes: ' + key)
    files[key] = actual
    return path


def bind_hash_map(entries, base, files, label):
    if not isinstance(entries, dict):
        raise ValueError('Invalid input hash map: ' + label)
    for name, expected in entries.items():
        path = Path(name)
        if not path.is_absolute():
            path = Path(base) / path
        bind_file(path, files, expected)


def find_exported_file(controller, name):
    path = Path(name)
    if path.is_absolute():
        return path
    candidates = [Path(controller) / path, Path(controller) / 'gateware' / path,
                  Path(controller) / 'software/include/generated' / path]
    matches = [candidate for candidate in candidates if candidate.is_file()]
    if len(matches) != 1:
        raise ValueError('Cannot uniquely locate exported controller file: ' + str(name))
    return matches[0]


def bind_controller_export(controller, export, export_path, files, rtl_relative):
    controller = Path(controller)
    bind_file(export_path, files)
    bind_file(controller / rtl_relative, files, export.get('standalone_verilog_sha256'))
    bind_file(controller / 'phase-constraints.tcl', files,
              export.get('phase_constraints_sha256'))
    bind_hash_map(export.get('external_sources', {}), controller, files,
                  'external sources in ' + str(export_path))
    profile = export.get('profile')
    if not isinstance(profile, dict):
        raise ValueError('Controller profile missing: ' + str(export_path))
    if not profile.get('source_sha256') or not export.get('initialization_files'):
        raise ValueError('Controller source/init bindings are missing: ' + str(export_path))
    bind_hash_map(profile['source_sha256'], controller, files,
                  'profile sources in ' + str(export_path))
    initializations = export.get('initialization_files', {})
    if not isinstance(initializations, dict):
        raise ValueError('Invalid initialization-file map: ' + str(export_path))
    for name, expected in initializations.items():
        bind_file(find_exported_file(controller, name), files, expected)


def validate_firmware(controller, channel, lanes, ecc, files):
    controller = Path(controller)
    manifest_path = controller / 'selfcal_fw/manifest.json'
    manifest = read_json(manifest_path)
    firmware_path = controller / 'selfcal_fw/firmware.bin'
    bind_file(manifest_path, files)
    bind_file(firmware_path, files, manifest.get('sha256'))
    expected = {
        'bytes': firmware_path.stat().st_size,
        'memory_bytes': FIRMWARE_BYTES,
        'mailbox_words': 128,
        'physical_channel': channel,
        'mailbox_channel': 0,
        'mailbox_magic': MAILBOX_MAGIC,
        'phase_period_steps': PHASE_PERIOD,
        'phase_stride': PHASE_STRIDE,
        'bist_mib_per_phase': 64,
        'ecc': ecc,
    }
    for name, value in expected.items():
        if manifest.get(name) != value:
            raise ValueError(f'Unexpected channel {channel} firmware field {name}')
    if 'physical_lanes' in manifest and manifest['physical_lanes'] is not None:
        if manifest['physical_lanes'] != lanes:
            raise ValueError(f'Unexpected channel {channel} firmware physical_lanes')
    inputs = manifest.get('inputs')
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError(f'Channel {channel} firmware input identity is missing')
    identity = {}
    for name, expected_hash in inputs.items():
        path = Path(name)
        if not path.is_absolute():
            path = controller / path
        path = bind_file(path, files, expected_hash)
        if path.name in identity:
            raise ValueError('Duplicate calibration input basename: ' + path.name)
        identity[path.name] = expected_hash
    firmware_id = int(hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:8], 16)
    if manifest.get('firmware_id') != firmware_id:
        raise ValueError(f'Channel {channel} firmware identity mismatch')
    return manifest


def validate_csr(controller, channel, lanes, ecc, dfi_words, lane_words, files):
    controller = Path(controller)
    csr_path = controller / 'csr.json'
    csv_path = controller / 'csr.csv'
    csr = read_json(csr_path)
    bind_file(csr_path, files)
    bind_file(csv_path, files)
    constants = csr.get('constants', {})
    if (csr.get('cores', {}).get('ddrphy') != 'WL7DDRPHY'
            or csr.get('cores', {}).get('ddrctrl') != 'LiteDRAMCoreControl'
            or csr.get('cores', {}).get('sdram') != 'LiteDRAMCore'
            or constants.get('config_clock_frequency') != 100000000
            or constants.get('config_csr_data_width') != 32
            or constants.get('config_csr_alignment') != 32
            or constants.get('config_bus_data_width') != 32
            or constants.get('config_bus_address_width') != 32
            or 'config_csr_ordering_big' not in constants):
        raise ValueError(f'Unexpected channel {channel} WL PHY/CSR geometry')

    registers = csr.get('csr_registers')
    if not isinstance(registers, dict) or not registers:
        raise ValueError(f'Channel {channel} CSR register map is missing')
    csv_registers = {}
    with csv_path.open(newline='') as stream:
        for row in csv.reader(stream):
            if not row or row[0] != 'csr_register':
                continue
            if len(row) != 5:
                raise ValueError(f'Malformed channel {channel} CSR CSV row')
            name = row[1]
            if name in csv_registers:
                raise ValueError(f'Duplicate channel {channel} CSR register: ' + name)
            csv_registers[name] = {'addr': int(row[2], 0), 'size': int(row[3]), 'type': row[4]}
    if csv_registers != registers:
        raise ValueError(f'Channel {channel} CSR JSON/CSV disagreement')

    occupied = set()
    data_regs = set()
    for name, reg in registers.items():
        if re.fullmatch(r'sdram_dfii_pi[0-3]_(?:wrdata|rddata)', name):
            width = dfi_words
            data_regs.add(name)
        elif name == 'ddrctrl_bist_lane_bits':
            width = lane_words
        elif name == 'ddrctrl_bist_seed':
            width = 2
        else:
            width = 1
        address, size = reg.get('addr'), reg.get('size')
        if (not isinstance(address, int) or not isinstance(size, int)
                or reg.get('type') not in ('rw', 'ro')
                or address < 0 or address % 4 or size != width
                or address + size * 4 > 0x2000):
            raise ValueError('Invalid channel ' + str(channel) + ' CSR register: ' + name)
        words = set(range(address, address + size * 4, 4))
        if occupied & words:
            raise ValueError('Overlapping channel ' + str(channel) + ' CSR register: ' + name)
        occupied.update(words)
    expected_data_regs = {f'sdram_dfii_pi{phase}_{direction}data'
                          for phase in range(DFI_PHASES) for direction in ('wr', 'rd')}
    if data_regs != expected_data_regs:
        raise ValueError(f'Channel {channel} DFI data CSR register set is incomplete')

    ecc_names = {'ecc_axi_0_enable', 'ecc_axi_0_clear',
                 'ecc_axi_0_sec_errors', 'ecc_axi_0_ded_errors'}
    found_ecc = {name for name in registers if name.startswith('ecc_axi_0_')}
    if ecc:
        if (csr.get('cores', {}).get('ecc_axi_0') != 'LiteDRAMNativePortECC'
                or found_ecc != ecc_names
                or any(registers[name].get('size') != 1 for name in ecc_names)
                or csr.get('csr_bases', {}).get('ecc_axi_0') != 0x1000):
            raise ValueError('Channel 1 ECC CSR block is incomplete or invalid')
    elif 'ecc_axi_0' in csr.get('cores', {}) or found_ecc:
        raise ValueError('Non-ECC channel 0 must not expose ECC CSRs')
    return csr


def validate_dfi_rtl(rtl_path, channel, lanes, dfi_bits, files):
    bind_file(rtl_path, files)
    text = Path(rtl_path).read_text(errors='strict')
    ports = text.split('\n// Hierarchy\n', 1)[0]
    dq_widths = [int(high) - int(low) + 1 for high, low in re.findall(
        r'(?m)^\s*inout\s+wire\s+\[(\d+):(\d+)\]\s+\w*dq\b', ports)]
    if dq_widths != [lanes * 8]:
        raise ValueError(f'Channel {channel} physical DQ bus does not match {lanes} byte lanes')
    phase_widths = {}
    for high, low, phase in re.findall(
            r'(?m)^\s*reg\s+\[(\d+):(\d+)\]\s+\w*phaseinjector([0-3])_wrdata_storage\s*=', text):
        phase_widths[int(phase)] = int(high) - int(low) + 1
    if phase_widths != {phase: dfi_bits for phase in range(DFI_PHASES)}:
        raise ValueError(f'Channel {channel} DFI width/phases must be four x {dfi_bits} bits')
    return {'physical_lanes': lanes, 'ddr_dq_bits': dq_widths[0],
            'dfi_data_bits_per_phase': dfi_bits, 'dfi_phases': DFI_PHASES}


def validate_controller(controller, channel, expected_abi, lanes, ecc, dfi_bits,
                        dfi_words, lane_words, files):
    controller = Path(controller)
    export_path = controller / 'selfcal-export.json'
    export = read_json(export_path)
    profile = export.get('profile')
    if not isinstance(profile, dict):
        raise ValueError(f'Channel {channel} controller profile is missing')
    payload = DDR_PAYLOAD_BYTES
    expected_profile = {
        'board_abi': expected_abi,
        'input_clock_hz': 50000000,
        'controller_clock_hz': 100000000,
        'ddr_data_rate': 800000000,
        'physical_lanes': lanes,
        'payload_bytes': payload,
        'ecc': ecc,
        'phase_uncertainty_ns': 1.3,
        'eligible_for_synthesis': True,
        'hardware_qualified': False,
        'hardware_accessed': False,
    }
    if export.get('board_abi') != expected_abi or export.get('controller') != 'WL7DDRPHY':
        raise ValueError(f'Unexpected channel {channel} controller ABI/type')
    for name, value in expected_profile.items():
        if profile.get(name) != value:
            raise ValueError(f'Unexpected channel {channel} profile field {name}')
    if profile.get('physical_channel') is not None and profile['physical_channel'] != channel:
        raise ValueError(f'Unexpected channel {channel} controller profile channel')
    if 'physical_data_lanes' in profile and len(profile['physical_data_lanes']) != lanes:
        raise ValueError(f'Unexpected channel {channel} data-lane count')

    rtl_relative = 'gateware/ypcb_ddr3_ch0.v' if channel == 0 else 'gateware/ypcb_ddr3.v'
    bind_controller_export(controller, export, export_path, files, rtl_relative)
    prototype_path = controller / 'prototype.json'
    prototype = read_json(prototype_path)
    bind_file(prototype_path, files)
    prototype_fields = {
        'board_abi': expected_abi,
        'input_clock_hz': 50000000,
        'controller_clock_hz': 100000000,
        'ddr_data_rate': 800000000,
        'physical_lanes': lanes,
        'payload_bytes': payload,
        'ecc': ecc,
        'phase_uncertainty_ns': 1.3,
        'eligible_for_synthesis': True,
        'hardware_qualified': False,
        'hardware_accessed': False,
    }
    for name, value in prototype_fields.items():
        if prototype.get(name) != value:
            raise ValueError(f'Unexpected channel {channel} prototype field {name}')
    if prototype.get('physical_channel') is not None and prototype['physical_channel'] != channel:
        raise ValueError(f'Unexpected channel {channel} prototype channel')
    proto_export = prototype.get('export', {})
    if (proto_export.get('standalone_verilog_sha256') != export.get('standalone_verilog_sha256')
            or proto_export.get('initialization_files') != export.get('initialization_files')):
        raise ValueError(f'Channel {channel} prototype/export disagreement')
    bind_hash_map(prototype.get('source_sha256', {}), controller, files,
                  'prototype sources for channel ' + str(channel))
    retained = None
    if channel == 1 and (controller / 'retained-compiled-rtl.json').is_file():
        retained_path = controller / 'retained-compiled-rtl.json'
        retained = read_json(retained_path)
        bind_file(retained_path, files)
        if (retained.get('status') != 'EXACT_COMPILED_RTL_RETAINED_AFTER_KNOWN_METADATA_COMPARISON'
                or retained.get('retained_sha256') != export.get('standalone_verilog_sha256')):
            raise ValueError('Retained CH1 compiled RTL binding is invalid')
        original_controller = Path(retained.get('original', ''))
        bind_file(original_controller / 'gateware/ypcb_ddr3.v', files,
                  retained.get('retained_sha256'))

    firmware = validate_firmware(controller, channel, lanes, ecc, files)
    if retained is not None and retained.get('firmware_sha256') != firmware.get('sha256'):
        raise ValueError('Retained CH1 firmware hash binding is invalid')
    csr = validate_csr(controller, channel, lanes, ecc, dfi_words, lane_words, files)
    rtl_path = controller / rtl_relative
    dfi = validate_dfi_rtl(rtl_path, channel, lanes, dfi_bits, files)
    return {'channel': channel, 'board_abi': expected_abi, 'firmware': firmware,
            'csr': csr, 'export': export, 'profile': profile, 'dfi': dfi,
            'rtl_path': rtl_path, 'controller_path': controller}


def bind_top_export(ddr, export, export_path, files):
    bind_file(export_path, files)
    profile = export.get('profile')
    if not isinstance(profile, dict):
        raise ValueError('Aggregate controller profile is missing')
    if not profile.get('source_sha256'):
        raise ValueError('Aggregate controller source binding is missing')
    bind_hash_map(profile['source_sha256'], ddr, files,
                  'aggregate controller sources')
    bind_file(Path(ddr) / 'gateware/ypcb_ddr3.v', files,
              export.get('standalone_verilog_sha256'))
    bind_file(Path(ddr) / 'phase-constraints.tcl', files,
              export.get('phase_constraints_sha256'))


def channel_summary(channel):
    return {'physical_channel': channel['channel'],
            'board_abi': channel['board_abi'],
            'firmware_id': channel['firmware']['firmware_id'],
            'firmware_sha256': channel['firmware']['sha256'],
            'physical_lanes': channel['dfi']['physical_lanes'],
            'ddr_dq_bits': channel['dfi']['ddr_dq_bits'],
            'dfi_data_bits_per_phase': channel['dfi']['dfi_data_bits_per_phase'],
            'ecc_enabled': channel['profile']['ecc'],
            'csr_count': len(channel['csr']['csr_registers'])}


def csr_lines(csr):
    lines = []
    for name, reg in sorted(csr['csr_registers'].items()):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError('Invalid CSR constant name: ' + name)
        lines.append(f'inline constexpr uint32_t {name} = 0x{reg["addr"]:x}u;')
    return lines


def render_header(board_abi, dual, memory_ready_mask, payload_bytes, ch1, ch0=None):
    firmware = ch1['firmware']
    header = [
        '#pragma once', '#include <cstdint>', '',
        f'#define YPCB_WL_DUAL_CHANNEL {1 if dual else 0}', '',
        'namespace vortex::ypcb::wl_config {',
        f'inline constexpr uint32_t board_abi = {board_abi}u;',
        'inline constexpr uint32_t physical_channel = 1u;',
        f'inline constexpr uint32_t calibration_firmware_id = 0x{firmware["firmware_id"]:08x}u;',
        f'inline constexpr uint32_t memory_ready_mask = {memory_ready_mask}u;',
        f'inline constexpr uint64_t payload_bytes = {payload_bytes}ull;',
        'inline constexpr uint32_t physical_lanes = 9u;',
        'inline constexpr bool ecc_enabled = true;',
        f'inline constexpr uint32_t mailbox_magic = 0x{firmware["mailbox_magic"]:08x}u;',
        'inline constexpr uint32_t sys_clock_hz = 100000000u;',
        f'inline constexpr uint32_t phase_period = {firmware["phase_period_steps"]}u;',
        f'inline constexpr uint32_t phase_stride = {firmware["phase_stride"]}u;',
        *csr_lines(ch1['csr']), '}', ''
    ]
    if dual:
        if ch0 is None:
            raise ValueError('Dual-channel header requires a CH0 controller')
        fw0 = ch0['firmware']
        header += [
            'namespace vortex::ypcb::wl_config::ch0 {',
            'inline constexpr uint32_t board_abi = 5u;',
            'inline constexpr uint32_t physical_channel = 0u;',
            f'inline constexpr uint32_t calibration_firmware_id = 0x{fw0["firmware_id"]:08x}u;',
            'inline constexpr uint32_t physical_lanes = 8u;',
            'inline constexpr bool ecc_enabled = false;',
            *csr_lines(ch0['csr']), '}', ''
        ]
    return '\n'.join(header)


def validate_abi4(ddr, export, export_path, files):
    if export.get('channel_exports') is not None:
        raise ValueError('ABI4 must use the single-controller input shape')
    profile = export.get('profile', {})
    channel = validate_controller(ddr, 1, 4, 9, True, 144, 5, 3, files)
    if profile.get('payload_bytes') != DDR_PAYLOAD_BYTES:
        raise ValueError('ABI4 CH1 export must advertise exactly 2 GiB payload')
    bind_top_export(ddr, export, export_path, files)
    return channel, {
        'board_abi': 4, 'dual_channel': False,
        'memory_ready_mask': 2, 'payload_bytes': DDR_PAYLOAD_BYTES,
        'channels': {'1': channel_summary(channel)},
    }


def validate_abi5(ddr, export, export_path, files):
    ddr = Path(ddr)
    if (export.get('controller') != 'WL7DDRPHY'
            or export.get('CH1_controller_reused_unchanged') is not True
            or export.get('hardware_accessed') is not False):
        raise ValueError('ABI5 aggregate controller binding is invalid')
    if export.get('channel_exports') != {'0': 'ch0', '1': 'ch1'}:
        raise ValueError('ABI5 requires exactly CH0 and CH1 controller exports')
    profile = export.get('profile', {})
    root_expected = {'board_abi': 5, 'input_clock_hz': 50000000,
                     'controller_clock_hz': 100000000, 'ddr_data_rate': 800000000,
                     'payload_bytes': DUAL_PAYLOAD_BYTES,
                     'phase_uncertainty_ns': 1.3, 'eligible_for_synthesis': True,
                     'hardware_qualified': False}
    for name, value in root_expected.items():
        if profile.get(name) != value:
            raise ValueError('Unexpected ABI5 aggregate profile field ' + name)
    channels = profile.get('channels')
    if not isinstance(channels, list) or len(channels) != 2:
        raise ValueError('ABI5 aggregate must list exactly two channels')
    by_channel = {item.get('physical_channel'): item for item in channels if isinstance(item, dict)}
    if set(by_channel) != {0, 1}:
        raise ValueError('ABI5 channel map must contain physical channels 0 and 1')
    bind_top_export(ddr, export, export_path, files)

    outputs = {}
    for number, subdir, abi, lanes, ecc, dfi_bits, data_words, lane_words in (
            (0, 'ch0', 5, 8, False, 128, 4, 2),
            (1, 'ch1', 4, 9, True, 144, 5, 3)):
        item = by_channel[number]
        expected = {'directory': subdir, 'physical_channel': number,
                    'payload_bytes': DDR_PAYLOAD_BYTES, 'physical_lanes': lanes, 'ecc': ecc}
        for name, value in expected.items():
            if item.get(name) != value:
                raise ValueError(f'Invalid aggregate channel {number} field {name}')
        data_lanes = item.get('physical_data_lanes')
        if (not isinstance(data_lanes, list) or len(data_lanes) != 8
                or len(set(data_lanes)) != 8 or any(not isinstance(x, int) or x < 0 or x >= 9 for x in data_lanes)):
            raise ValueError(f'Invalid channel {number} physical data-lane map')
        controller = ddr / subdir
        channel = validate_controller(controller, number, abi, lanes, ecc,
                                      dfi_bits, data_words, lane_words, files)
        if item.get('firmware_id') != channel['firmware']['firmware_id']:
            raise ValueError(f'Aggregate channel {number} firmware ID mismatch')
        if item.get('firmware_sha256') != channel['firmware']['sha256']:
            raise ValueError(f'Aggregate channel {number} firmware hash mismatch')
        if (channel['profile'].get('physical_data_lanes') is not None
                and channel['profile']['physical_data_lanes'] != data_lanes):
            raise ValueError(f'Channel {number} physical data-lane map mismatch')
        original_export = item.get('original_export')
        original_hash = item.get('original_export_sha256')
        if not original_export or not original_hash:
            raise ValueError(f'Aggregate channel {number} lacks its original export binding')
        original_path = bind_file(original_export, files, original_hash)
        original = read_json(original_path)
        if original.get('board_abi') != abi:
            raise ValueError(f'Aggregate channel {number} original export ABI mismatch')
        if (original.get('standalone_verilog_sha256')
                != channel['export'].get('standalone_verilog_sha256')):
            raise ValueError(f'Aggregate channel {number} original RTL hash mismatch')
        if number == 1:
            retained_path = controller / 'retained-compiled-rtl.json'
            retained = read_json(retained_path)
            bind_file(retained_path, files)
            if (retained.get('status') != 'EXACT_COMPILED_RTL_RETAINED_AFTER_KNOWN_METADATA_COMPARISON'
                    or retained.get('retained_sha256') != channel['export'].get('standalone_verilog_sha256')
                    or retained.get('firmware_sha256') != channel['firmware']['sha256']):
                raise ValueError('Retained CH1 compiled RTL/firmware identity mismatch')
            original_rtl = Path(retained['original']) / 'gateware/ypcb_ddr3.v'
            bind_file(original_rtl, files, retained.get('retained_sha256'))
        outputs[number] = channel

    total = sum(channel['profile']['payload_bytes'] for channel in outputs.values())
    if total != DUAL_PAYLOAD_BYTES:
        raise ValueError('ABI5 payload total is not exactly 4 GiB')
    return outputs[1], outputs[0], {
        'board_abi': 5, 'dual_channel': True,
        'memory_ready_mask': 3, 'payload_bytes': total,
        'channels': {str(number): channel_summary(outputs[number]) for number in (0, 1)},
    }


def generate(ddr, output):
    ddr = Path(ddr).resolve()
    output = Path(output).resolve()
    export_path = ddr / 'selfcal-export.json'
    export = read_json(export_path)
    files = {}
    bind_file(Path(__file__).resolve(), files)
    abi = export.get('board_abi')
    ch0 = None
    if abi == 4:
        ch1, metadata = validate_abi4(ddr, export, export_path, files)
    elif abi == 5:
        ch1, ch0, metadata = validate_abi5(ddr, export, export_path, files)
    else:
        raise ValueError('Unsupported YPCB DDR controller ABI: ' + repr(abi))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_header(metadata['board_abi'], metadata['dual_channel'],
                                    metadata['memory_ready_mask'], metadata['payload_bytes'],
                                    ch1, ch0))
    metadata.update({
        'controller_path': str(ddr),
        'controller_export_sha256': digest(export_path),
        'controller_inputs_sha256': dict(sorted(files.items())),
        'output_path': str(output),
        'output_sha256': digest(output),
        'hardware_accessed': False,
        'physical_qualification_claimed': False,
    })
    metadata_path = output.with_suffix('.json')
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ddr', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.ddr.resolve(), args.output.resolve())
    print(json.dumps({'board_abi': result['board_abi'],
                      'dual_channel': result['dual_channel'],
                      'payload_bytes': result['payload_bytes'],
                      'memory_ready_mask': result['memory_ready_mask'],
                      'channels': result['channels'],
                      'output_path': result['output_path'],
                      'output_sha256': result['output_sha256']}))
