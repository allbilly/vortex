#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

interrupted = 0


def wl_controller(directory):
    export = json.loads((directory / 'selfcal-export.json').read_text())
    profile = export['profile']
    expected = {'board_abi': 4, 'input_clock_hz': 50000000, 'controller_clock_hz': 100000000,
                'ddr_data_rate': 800000000, 'physical_lanes': 9, 'payload_bytes': 2147483648,
                'ecc': True, 'phase_uncertainty_ns': 1.3, 'eligible_for_synthesis': True}
    if (export['board_abi'] != 4 or export['controller'] != 'WL7DDRPHY'
            or any(profile.get(k) != v for k, v in expected.items())):
        raise ValueError('Unexpected ABI4 CH1 WL controller profile')
    files = {'gateware/ypcb_ddr3.v': export['standalone_verilog_sha256'],
             'phase-constraints.tcl': export['phase_constraints_sha256']}
    firmware = json.loads((directory / 'selfcal_fw/manifest.json').read_text())
    payload = (directory / 'selfcal_fw/firmware.bin').read_bytes()
    if (firmware['memory_bytes'] != 16384 or firmware['bytes'] != len(payload)
            or not payload or len(payload) > 16384 or len(payload) % 4
            or not 0 < firmware['firmware_id'] < 2**32):
        raise ValueError('Invalid WL firmware bounds or identity')
    files['selfcal_fw/firmware.bin'] = firmware['sha256']
    for name, expected_hash in files.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError('WL controller input changed: ' + name)
    for name, expected_hash in firmware['inputs'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError('WL calibration source changed: ' + name)
    for name, expected_hash in profile['source_sha256'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected_hash:
            raise ValueError('WL controller source changed after export: ' + name)
    return {'board_abi': 4, 'controller': 'WL7DDRPHY', 'firmware_id': firmware['firmware_id'],
            'firmware_sha256': firmware['sha256'], 'profile': profile}


def interrupt(signum, frame):
    global interrupted
    interrupted = signum


def save(path, value):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        temporary = stream.name
    os.replace(temporary, path)


def run(command, directory, output, name, timeout):
    if timeout <= 0:
        raise ValueError('Stage timeout must be positive')
    started = time.monotonic()
    timed_out = False
    with (output / (name + '.log')).open('w') as log:
        child = subprocess.Popen([str(item) for item in command], cwd=directory,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while child.poll() is None:
            timed_out = time.monotonic() - started >= timeout
            if interrupted or timed_out:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                break
            save(output / 'progress.json', {'stage': name, 'pid': child.pid,
                 'elapsed_seconds': time.monotonic() - started, 'running': True})
            time.sleep(1)
        result = child.wait()
    elapsed = time.monotonic() - started
    timed_out = timed_out or elapsed >= timeout
    save(output / (name + '-exit.json'), {'command': [str(item) for item in command],
         'exit_code': result, 'interrupted': interrupted, 'timed_out': timed_out,
         'elapsed_seconds': elapsed, 'timeout_seconds': timeout})
    if result != 0 or interrupted or timed_out:
        save(output / 'progress.json', {'stage': name, 'running': False, 'exit_code': result,
             'interrupted': interrupted, 'timed_out': timed_out})
        raise RuntimeError(f'{name} failed; inspect {output / (name + ".log")}')


def reuse_synthesis(original, output, manifest):
    original = original.resolve()
    receipt = json.loads((original / 'synthesize-exit.json').read_text())
    if (receipt.get('exit_code') != 0 or receipt.get('interrupted') != 0
            or receipt.get('timed_out') is not False):
        raise ValueError('The reused synthesis must have a successful exit receipt')
    inputs = json.loads((original / 'inputs.json').read_text())['inputs']
    for name, digest in inputs.items():
        if hashlib.sha256((original / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Reused synthesis input changed: {name}')
    regenerated = {}
    date = rb'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
    banner = rb'(?m)^// (?:Date       : ' + date + rb'| Auto-Generated by LiteX on ' + date + rb'\.)\r?\n'
    for name in ('cdc/ypcb_axi_cdc.v', 'wb-cdc/ypcb_wb_cdc.v'):
        if name not in inputs or name not in manifest['inputs']:
            continue
        before, after = (original / name).read_bytes(), (output / name).read_bytes()
        if before != after and re.sub(banner, b'', before) == re.sub(banner, b'', after):
            regenerated[name] = {'regenerated_sha256': manifest['inputs'][name],
                                 'retained_sha256': inputs[name]}
            # Retain the exact compiled file after proving only wall-clock comments changed.
            shutil.copy2(original / name, output / name)
            manifest['inputs'][name] = inputs[name]
    suffixes = {'.sv', '.v', '.vh', '.xdc', '.mem', '.dat'}
    previous = {name: digest for name, digest in inputs.items() if Path(name).suffix in suffixes}
    current = {name: digest for name, digest in manifest['inputs'].items() if Path(name).suffix in suffixes}
    if previous != current:
        changed = sorted(name for name in previous.keys() | current.keys() if previous.get(name) != current.get(name))
        raise ValueError(f'HDL or pin constraints changed; synthesis cannot be reused: {changed[:10]}')
    for name in ('afu/sources.txt', 'afu/config.flags'):
        before = (original / name).read_text().replace(str(original), '<run>')
        after = (output / name).read_text().replace(str(output), '<run>')
        if before != after:
            raise ValueError(f'Synthesis sources or configuration changed: {name}')
    script = 'snapshot/hw/syn/xilinx/ypcb/vivado_board.tcl'
    delimiter = '\nopen_checkpoint [file join $output_dir synth.dcp]'
    before = (original / script).read_text().split(delimiter, 1)
    after = (output / script).read_text().split(delimiter, 1)
    if len(before) != 2 or len(after) != 2 or before[0] != after[0]:
        raise ValueError('Synthesis Tcl changed; a fresh synthesis is required')
    for name in ('synth.dcp', 'utilization-synth.rpt', 'drc-synth.rpt'):
        shutil.copy2(original / name, output / name)
        manifest['inputs'][name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    result = {'run': str(original), 'synth_dcp_sha256': manifest['inputs']['synth.dcp'],
              'verified_hardware_inputs': len(previous),
              'timestamp_only_regenerations': regenerated,
              'synthesis_exit_receipt_sha256': hashlib.sha256((original / 'synthesize-exit.json').read_bytes()).hexdigest(),
              'original_inputs_sha256': hashlib.sha256((original / 'inputs.json').read_bytes()).hexdigest()}
    save(output / 'reused-synthesis.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ddr', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--pin-audit', type=Path, required=True)
    parser.add_argument('--pcie-reference', type=Path, required=True)
    parser.add_argument('--litex-root', type=Path, required=True)
    parser.add_argument('--vivado', default='vivado')
    parser.add_argument('--stage', choices=('synthesize', 'all'), default='all')
    parser.add_argument('--reuse-synthesis', type=Path)
    parser.add_argument('--timeout', type=int, default=21600)
    parser.add_argument('--threads', type=int, choices=range(1, 9),
                        default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('Timeout must be positive')
    if args.reuse_synthesis and args.stage != 'all':
        raise ValueError('Reusing synthesis requires the implementation stage')
    build, output = args.build.resolve(), args.output.resolve()
    root = Path(__file__).resolve().parents[4]
    if output.exists():
        raise ValueError('Output must be a fresh directory')
    if (not (build / 'config.mk').is_file() or 'MEMORY_SIZE ?= 2147483648' not in (build / 'config.mk').read_text()
            or 'XLEN ?= 32' not in (build / 'config.mk').read_text()):
        raise ValueError('Configure an RV32 build with --memory-size=2147483648 first')
    controller = wl_controller(args.ddr.resolve())
    output.mkdir(parents=True)
    board = root / 'hw/syn/xilinx/ypcb'
    run(['make', '-C', build / 'hw/syn/xilinx/ypcb', 'sources', 'board-pcie',
         f'OUT_DIR={output / "afu"}', f'BOARD_OUT_DIR={output / "board"}',
         f'PCIE_REFERENCE={args.pcie_reference.resolve()}'], build, output, 'export', 600)
    run(['python3', board / 'gen_constraints.py', '--reference', args.reference.resolve(),
         '--package', args.package.resolve(), '--audit', args.pin_audit.resolve(),
         '--top', board / 'ypcb_top.sv', '--output', output / 'board/ypcb-reference.xdc'],
        build, output, 'pins', 120)
    environment = dict(os.environ)
    dependencies = [args.litex_root / item for item in ('migen', 'litex', 'litedram')]
    environment['PYTHONPATH'] = os.pathsep.join([*(str(p.resolve()) for p in dependencies), os.environ.get('PYTHONPATH', '')])
    for script, target in [('gen_cdc.py', 'cdc/ypcb_axi_cdc.v'), ('gen_wb_cdc.py', 'wb-cdc/ypcb_wb_cdc.v')]:
        subprocess.run(['python3', str(board / script), '--output', str(output / target)],
                       cwd=build, env=environment, check=True, timeout=120)
    snapshot = output / 'snapshot'
    for relative in ('hw/rtl', 'hw/syn/xilinx/ypcb'):
        shutil.copytree(root / relative, snapshot / relative)
    shutil.copytree(build / 'hw', snapshot / 'build/hw', ignore=shutil.ignore_patterns('syn', 'unittest'))
    shutil.copytree(args.ddr.resolve() / 'gateware', output / 'ddr/gateware')
    for name in ('csr.json', 'csr.csv', 'selfcal-export.json', 'phase-constraints.tcl', 'prototype.json'):
        shutil.copy2(args.ddr.resolve() / name, output / 'ddr' / name)
    shutil.copytree(args.ddr.resolve() / 'selfcal_fw', output / 'ddr/selfcal_fw')
    shutil.copytree(args.ddr.resolve() / 'software/include/generated', output / 'ddr/software/include/generated')
    filelist = output / 'afu/sources.txt'
    text = filelist.read_text().replace(str(build / 'hw'), str(snapshot / 'build/hw'))
    text = text.replace(str(root / 'hw'), str(snapshot / 'hw'))
    filelist.write_text(text)
    files = [p for p in output.rglob('*') if p.is_file() and p.suffix != '.log' and p.name != 'progress.json']
    manifest = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                'source_diff': subprocess.check_output(['git', 'diff', 'HEAD'], cwd=root, text=True),
                'inputs': {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                'scope': 'ABI4 CH1 2 GiB ECC, WL calibration, independent 125 MHz GPU clock, JTAG AXI and PCIe',
                'controller': controller, 'vivado_threads': args.threads}
    if args.reuse_synthesis:
        manifest['reused_synthesis'] = reuse_synthesis(args.reuse_synthesis, output, manifest)
    save(output / 'inputs.json', manifest)
    stages = ['synthesize'] if args.stage == 'synthesize' else ['synthesize', 'implement']
    if args.reuse_synthesis:
        stages = ['implement']
    for stage in stages:
        run([args.vivado, '-mode', 'batch', '-nojournal', '-nolog', '-source',
             snapshot / 'hw/syn/xilinx/ypcb/vivado_board.tcl', '-tclargs', snapshot,
             snapshot / 'build', output, output / 'ddr', output, output / 'board/pcie-patched', stage, args.threads],
            output, output, stage, args.timeout)
    save(output / 'progress.json', {'stage': 'complete', 'running': False,
         'hardware_programmed': False, 'physical_qualification_complete': False})


if __name__ == '__main__':
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    main()
