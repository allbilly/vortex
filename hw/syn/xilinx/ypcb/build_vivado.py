#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

interrupted = 0


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
    started = time.monotonic()
    with (output / (name + '.log')).open('w') as log:
        child = subprocess.Popen([str(item) for item in command], cwd=directory,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while child.poll() is None:
            if interrupted or time.monotonic() - started >= timeout:
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
    save(output / (name + '-exit.json'), {'command': [str(item) for item in command],
         'exit_code': result, 'interrupted': interrupted,
         'elapsed_seconds': time.monotonic() - started})
    if result != 0 or interrupted or time.monotonic() - started >= timeout:
        save(output / 'progress.json', {'stage': name, 'running': False, 'exit_code': result, 'interrupted': interrupted})
        raise RuntimeError(f'{name} failed; inspect {output / (name + ".log")}')


def reuse_synthesis(original, output, manifest):
    original = original.resolve()
    receipt = json.loads((original / 'synthesize-exit.json').read_text())
    if receipt['exit_code'] != 0 or receipt['interrupted']:
        raise ValueError('The reused synthesis must have a successful exit receipt')
    inputs = json.loads((original / 'inputs.json').read_text())['inputs']
    for name, digest in inputs.items():
        if hashlib.sha256((original / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Reused synthesis input changed: {name}')
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
    args = parser.parse_args()
    if args.reuse_synthesis and args.stage != 'all':
        raise ValueError('Reusing synthesis requires the implementation stage')
    build, output = args.build.resolve(), args.output.resolve()
    root = Path(__file__).resolve().parents[4]
    if output.exists():
        raise ValueError('Output must be a fresh directory')
    if not (build / 'config.mk').is_file() or 'MEMORY_SIZE ?= 2147483648' not in (build / 'config.mk').read_text():
        raise ValueError('Configure an RV32 build with --memory-size=2147483648 first')
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
    filelist = output / 'afu/sources.txt'
    text = filelist.read_text().replace(str(build / 'hw'), str(snapshot / 'build/hw'))
    text = text.replace(str(root / 'hw'), str(snapshot / 'hw'))
    filelist.write_text(text)
    files = [p for p in output.rglob('*') if p.is_file() and p.suffix not in ('.log', '.json')]
    manifest = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                'source_diff': subprocess.check_output(['git', 'diff', 'HEAD'], cwd=root, text=True),
                'inputs': {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                'scope': 'CH1 2 GiB, independent 125 MHz GPU clock, JTAG AXI and PCIe'}
    if args.reuse_synthesis:
        manifest['reused_synthesis'] = reuse_synthesis(args.reuse_synthesis, output, manifest)
    save(output / 'inputs.json', manifest)
    stages = ['synthesize'] if args.stage == 'synthesize' else ['synthesize', 'implement']
    if args.reuse_synthesis:
        stages = ['implement']
    for stage in stages:
        run([args.vivado, '-mode', 'batch', '-nojournal', '-nolog', '-source',
             snapshot / 'hw/syn/xilinx/ypcb/vivado_board.tcl', '-tclargs', snapshot,
             snapshot / 'build', output, output / 'ddr', output, output / 'board/pcie-patched', stage],
            output, output, stage, args.timeout)
    save(output / 'progress.json', {'stage': 'complete', 'running': False,
         'hardware_programmed': False, 'physical_qualification_complete': False})


if __name__ == '__main__':
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    main()
