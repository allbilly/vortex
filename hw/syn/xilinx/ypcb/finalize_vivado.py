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


def active_producers(original):
    original = original.resolve()
    found = []
    ancestors = {os.getpid()}
    parent = os.getppid()
    while parent > 1 and parent not in ancestors:
        ancestors.add(parent)
        try:
            parent = int(Path('/proc', str(parent), 'stat').read_text().rpartition(')')[2].split()[1])
        except OSError:
            break
    for process in Path('/proc').glob('[0-9]*'):
        if int(process.name) in ancestors:
            continue
        try:
            args = [item.decode() for item in (process / 'cmdline').read_bytes().split(b'\0') if item]
            if not {'vivado', 'build_vivado.py', 'finalize_vivado.py'} & {Path(item).name for item in args}:
                continue
            cwd = (process / 'cwd').resolve()
            for arg in args:
                if arg.startswith('-'):
                    if '=' not in arg:
                        continue
                    arg = arg.split('=', 1)[1]
                path = Path(arg)
                path = (path if path.is_absolute() else cwd / path).resolve()
                if path == original or original in path.parents:
                    found.append({'pid': int(process.name), 'command': args})
                    break
        except (OSError, UnicodeError):
            continue
    return found


def implementation_source(original, recover_abandoned):
    path = original / 'implement-exit.json'
    receipt = json.loads(path.read_text()) if path.is_file() else None
    result = {'original_implementation_exit_sha256': digest(path) if receipt is not None else None}
    if receipt is not None and receipt.get('timed_out') is not False:
        raise ValueError('Routed reuse requires an explicit implementation timeout disposition of false')
    if not recover_abandoned:
        if receipt is None or receipt.get('interrupted') != 0 or receipt.get('exit_code') not in (0, 1):
            raise ValueError('Routed reuse requires a completed, uninterrupted implementation')
        return result
    active = active_producers(original)
    if active:
        raise ValueError('Cannot recover an active routed producer: ' + str(active))
    progress = json.loads((original / 'progress.json').read_text())
    synthesis = json.loads((original / 'synthesize-exit.json').read_text())
    if (progress.get('stage') != 'implement' or synthesis.get('exit_code') != 0
            or synthesis.get('interrupted') != 0 or synthesis.get('timed_out') is not False):
        raise ValueError('Abandoned recovery requires the recorded implementation stage and successful synthesis')
    result['abandoned_producer_recovery'] = {
        'observed_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'original_exit_receipt': receipt, 'original_progress': progress,
        'original_progress_sha256': digest(original / 'progress.json'),
        'original_synthesis_exit_sha256': digest(original / 'synthesize-exit.json'),
        'active_producers': active,
        'qualification': 'Frozen inputs and original reports are verified; a fresh native checkpoint review and bitstream producer must succeed.',
    }
    return result


def prepare(original, output, recover_abandoned=False):
    board = Path(__file__).resolve().parent
    producer = implementation_source(original, recover_abandoned)
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
        'original_implementation_log_sha256': digest(original / 'implement.log'),
        'original_report_sha256': reports,
        'original_report_qualification_with_current_verifier': qualification,
        **producer,
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
    parser.add_argument('--recover-abandoned-run', action='store_true',
                        help='Recover a verified routed checkpoint after confirming its original producer is no longer active.')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('Timeout must be positive')
    original, output = args.run.resolve(), args.output.resolve()
    prepare(original, output, recover_abandoned=args.recover_abandoned_run)
    if args.recover_abandoned_run and active_producers(original):
        raise ValueError('The original producer became active during recovery')
    command = [args.vivado, '-mode', 'batch', '-nojournal', '-nolog', '-source',
               str(output / 'finalization/vivado_finalize.tcl'), '-tclargs', str(output)]
    started = time.monotonic()
    timed_out = False
    with (output / 'finalize.log').open('w') as log:
        child = subprocess.Popen(command, cwd=output, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        while child.poll() is None:
            timed_out = time.monotonic() - started >= args.timeout
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
    elapsed = time.monotonic() - started
    timed_out = timed_out or elapsed >= args.timeout
    receipt = {'command': command, 'exit_code': code, 'interrupted': interrupted, 'timed_out': timed_out,
               'elapsed_seconds': elapsed, 'timeout_seconds': args.timeout,
               'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (output / 'finalize-exit.json').write_text(json.dumps(receipt, indent=2) + '\n')
    progress = {'stage': 'complete' if code == 0 and not interrupted and not timed_out else 'failed',
                'running': False, 'exit_code': code, 'interrupted': interrupted,
                'timed_out': timed_out, 'hardware_programmed': False}
    (output / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
    if code != 0 or interrupted or timed_out:
        raise SystemExit('Routed finalization failed; inspect ' + str(output / 'finalize.log'))


if __name__ == '__main__':
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    main()
