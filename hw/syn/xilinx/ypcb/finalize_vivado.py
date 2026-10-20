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
import sys
import time

interrupted = 0


def interrupt(number, frame):
    global interrupted
    interrupted = number


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(original, output):
    board = Path(__file__).resolve().parent
    receipt = json.loads((original / 'implement-exit.json').read_text())
    if receipt['interrupted'] or receipt['exit_code'] not in (0, 1):
        raise ValueError('Routed reuse requires a completed, uninterrupted implementation')
    inputs = json.loads((original / 'inputs.json').read_text())
    for name, expected in inputs['inputs'].items():
        if digest(original / name) != expected:
            raise ValueError('Frozen implementation input changed: ' + name)
    report_names = ('timing-summary.rpt', 'bus-skew.rpt', 'route-status.rpt',
                    'check-timing-routed.rpt', 'drc-routed.rpt')
    reports = {name: digest(original / name) for name in report_names}
    result = subprocess.run([sys.executable, str(board / 'verify_vivado_reports.py'), str(original)],
                            capture_output=True, text=True, check=True)
    qualification = json.loads(result.stdout)
    if reports != {name: digest(original / name) for name in report_names}:
        raise ValueError('Routed reports changed during qualification')
    routed = original / 'routed.dcp'
    routed_hash = digest(routed)
    output.mkdir(parents=True, exist_ok=False)
    for name, expected in inputs['inputs'].items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original / name, target)
        if digest(target) != expected:
            raise ValueError('Implementation input changed while copying: ' + name)
    shutil.copy2(routed, output / 'routed.dcp')
    if digest(output / 'routed.dcp') != routed_hash or digest(routed) != routed_hash:
        raise ValueError('Routed checkpoint changed while copying')
    inputs['inputs']['routed.dcp'] = routed_hash
    for name in ('finalize_vivado.py', 'vivado_finalize.tcl', 'verify_vivado_reports.py'):
        target = output / 'finalization' / name
        target.parent.mkdir(exist_ok=True)
        expected = digest(board / name)
        shutil.copy2(board / name, target)
        if digest(target) != expected or digest(board / name) != expected:
            raise ValueError('Finalization tool changed while copying: ' + name)
        inputs['inputs'][str(target.relative_to(output))] = expected
    inputs['routed_finalization'] = {
        'run': str(original), 'routed_dcp_sha256': routed_hash,
        'original_inputs_sha256': digest(original / 'inputs.json'),
        'original_implementation_exit_sha256': digest(original / 'implement-exit.json'),
        'original_implementation_log_sha256': digest(original / 'implement.log'),
        'original_report_sha256': reports,
        'original_report_qualification_with_current_verifier': qualification,
    }
    inputs['finalization_source_revision'] = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=board, text=True).strip()
    (output / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    return inputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vivado', default='vivado')
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('Timeout must be positive')
    original, output = args.run.resolve(), args.output.resolve()
    prepare(original, output)
    command = [args.vivado, '-mode', 'batch', '-nojournal', '-nolog', '-source',
               str(output / 'finalization/vivado_finalize.tcl'), '-tclargs', str(output)]
    started = time.monotonic()
    timed_out = False
    with (output / 'finalize.log').open('w') as log:
        child = subprocess.Popen(command, cwd=output, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        while child.poll() is None:
            timed_out = time.monotonic() - started > args.timeout
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
            progress = {'stage': 'finalize', 'pid': child.pid, 'running': True,
                        'elapsed_seconds': time.monotonic() - started}
            temporary = output / 'progress.tmp.json'
            temporary.write_text(json.dumps(progress, indent=2) + '\n')
            temporary.replace(output / 'progress.json')
            time.sleep(1)
        code = child.wait()
    receipt = {'command': command, 'exit_code': code, 'interrupted': interrupted, 'timed_out': timed_out,
               'elapsed_seconds': time.monotonic() - started,
               'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (output / 'finalize-exit.json').write_text(json.dumps(receipt, indent=2) + '\n')
    progress = {'stage': 'complete' if code == 0 and not interrupted and not timed_out else 'failed',
                'running': False, 'exit_code': code, 'hardware_programmed': False}
    (output / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
    if code != 0 or interrupted or timed_out:
        raise SystemExit('Routed finalization failed; inspect ' + str(output / 'finalize.log'))


if __name__ == '__main__':
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    main()
