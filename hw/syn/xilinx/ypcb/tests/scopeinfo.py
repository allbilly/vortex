#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

SOURCE = '''module scope_leaf #(parameter WIDTH=5)(input [WIDTH-1:0] a, b,
    input enable, output [WIDTH-1:0] value);
  assign value = (a ^ b) & {WIDTH{enable}};
endmodule
module scope_middle #(parameter WIDTH=4)(input [WIDTH-1:0] a, b,
    input enable, output [WIDTH-1:0] value);
  scope_leaf #(.WIDTH(WIDTH)) leaf(a, b, enable, value);
endmodule
module scope_probe(input [2:0] a, b, input enable, output [2:0] value);
  scope_middle #(.WIDTH(3)) middle(a, b, enable, value);
endmodule
'''

TESTBENCH = '''module scope_tb;
  reg [2:0] a, b;
  reg enable;
  wire [2:0] value;
  integer i, j, k, count;
  scope_probe dut(a, b, enable, value);
  initial begin
    count = 0;
    for (k=0; k<2; k=k+1)
      for (i=0; i<8; i=i+1)
        for (j=0; j<8; j=j+1) begin
          enable=k; a=i; b=j; #1;
          if (value !== ((i ^ j) & (k ? 7 : 0)))
            $fatal(1, "Incorrect mapped value at a=%0d b=%0d enable=%0d", i, j, k);
          count=count+1;
        end
    $display("SCOPEINFO_FUNCTIONAL_PASS cases=%0d", count);
    $finish;
  end
endmodule
'''


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(data)
    return value.hexdigest()


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup(process):
    if group_alive(process.pid):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    deadline = time.monotonic() + 5
    while True:
        while True:
            try:
                child, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if not child:
                break
        if not group_alive(process.pid):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Native qualification group survived cleanup')
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        time.sleep(0.05)


def qualify(yosys, iverilog, vvp, output):
    output.mkdir(parents=True, exist_ok=False)
    library = yosys.parent.parent / 'share/yosys/xilinx/cells_sim.v'
    inputs = {str(path): digest(path) for path in
              (yosys, yosys.with_name('yosys-abc'), iverilog, vvp, library,
               Path(__file__).resolve(), Path(sys.executable).resolve())}
    if os.environ.get('LD_PRELOAD'):
        preload = Path(os.environ['LD_PRELOAD']).resolve()
        inputs[str(preload)] = digest(preload)
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'Cannot enable child subreaper')
    source, bench = output / 'scope.v', output / 'scope_tb.v'
    source.write_text(SOURCE)
    bench.write_text(TESTBENCH)
    inputs.update({str(path): digest(path) for path in (source, bench)})
    record = output / 'result.json'
    result = {'status': 'NATIVE_SCOPEINFO_EXPORT_QUALIFICATION_RUNNING', 'inputs': inputs,
              'cases': [], 'physical_verified': False,
              'scope': 'Nested parameter-specialized hierarchy, metadata-only normalization, strict unmapped-hardware rejection, byte-identical native metadata-free JSON and exhaustive mapped combinational behavior.'}

    def save():
        record.write_text(json.dumps(result, indent=2) + '\n')

    def interrupted(signum, frame):
        raise InterruptedError('Qualification interrupted by signal ' + str(signum))

    def run(name, command, expected):
        log = output / (name + '.log')
        case = {'name': name, 'command': command, 'expected_returncode': expected,
                'status': 'RUNNING', 'timeout_seconds': 120}
        result['cases'].append(case)
        save()
        with log.open('wb') as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                process.wait(timeout=120)
            finally:
                cleanup(process)
        case.update(returncode=process.returncode, owned_group_absent_after_cleanup=True,
                    log_sha256=digest(log))
        if process.returncode != expected:
            raise ValueError(name + ' returned unexpected status; inspect ' + str(log))
        case['status'] = 'PASS'
        save()
        return log.read_text()

    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    save()
    try:
        imported = f'read_verilog {source}; hierarchy -top scope_probe; proc; flatten; '
        synthesis = imported + 'synth_xilinx -family xc7 -top scope_probe -noiopad -noclkbuf; '
        assertion = 'select -assert-none scope_probe/t:$*; '
        raw, expected, normalized = (output / name for name in ('raw.json', 'backend-clean.json', 'normalized.json'))
        mapped = output / 'mapped.v'
        original = run('original_metadata_rejection', [str(yosys), '-p', synthesis + assertion], 1)
        if 'ERROR: Assertion failed: selection is not empty: scope_probe/t:$*' not in original:
            raise ValueError('Original gate did not reject the preserved scope metadata')
        run('metadata_normalization', [str(yosys), '-p', synthesis + f'write_json {raw}; '
            f'write_json -noscopeinfo {expected}; delete t:$scopeinfo; check -assert; '
            + assertion + f'write_json {normalized}; write_verilog -noattr {mapped}'], 0)
        before, after = (json.loads(path.read_text())['modules']['scope_probe'] for path in (raw, normalized))
        metadata = {name: cell for name, cell in before['cells'].items() if cell['type'] == '$scopeinfo'}
        if len(metadata) != 2 or any(cell['connections'] for cell in metadata.values()):
            raise ValueError('Nested scope metadata differs from the expected no-connection representation')
        hardware = {name: cell for name, cell in before['cells'].items() if name not in metadata}
        if after['cells'] != hardware or any(cell['type'].startswith('$') for cell in after['cells'].values()):
            raise ValueError('Normalization changed hardware cells or left internal cells')
        if any(before[key] != after[key] for key in ('ports', 'netnames', 'attributes')):
            raise ValueError('Normalization changed module wiring or attributes')
        if expected.read_bytes() != normalized.read_bytes():
            raise ValueError('Normalization differs from the native metadata-free backend')
        rejected = run('unmapped_hardware_rejection', [str(yosys), '-p', imported
            + 'delete t:$scopeinfo; check -assert; ' + assertion], 1)
        if 'ERROR: Assertion failed: selection is not empty: scope_probe/t:$*' not in rejected:
            raise ValueError('Unmapped hardware did not fail the strict gate')
        simulation = output / 'simulation.vvp'
        run('mapped_compile', [str(iverilog), '-g2012', '-s', 'scope_tb', '-o', str(simulation),
                              str(library), str(mapped), str(bench)], 0)
        functional = run('mapped_functional', [str(vvp), str(simulation)], 0)
        if 'SCOPEINFO_FUNCTIONAL_PASS cases=128' not in functional:
            raise ValueError('Mapped exhaustive functional evidence missing')
        result['inputs_unchanged'] = all(digest(Path(path)) == value for path, value in inputs.items())
        if not result['inputs_unchanged']:
            raise ValueError('Qualification input changed')
        result.update(status='NATIVE_SCOPEINFO_METADATA_NORMALIZATION_AND_STRICT_HARDWARE_GATE_FUNCTIONAL_PASS',
                      metadata_cells_removed=2, functional_cases=128, native_backend_byte_identical=True,
                      artifacts={str(path): {'bytes': path.stat().st_size, 'sha256': digest(path)}
                                 for path in (raw, expected, normalized, mapped, simulation)})
    except Exception as error:
        result.update(status='INTERRUPTED' if isinstance(error, InterruptedError) else
                      'TIMEOUT' if isinstance(error, subprocess.TimeoutExpired) else 'FAIL', failure=str(error))
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        save()
    print(result['status'])
    if result['status'] != 'NATIVE_SCOPEINFO_METADATA_NORMALIZATION_AND_STRICT_HARDWARE_GATE_FUNCTIONAL_PASS':
        print(result.get('failure', ''), file=sys.stderr)
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    for name in ('yosys', 'iverilog', 'vvp', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    selected = []
    for name in ('yosys', 'iverilog', 'vvp'):
        path = shutil.which(str(getattr(args, name)))
        if path is None:
            parser.error('Executable not found: ' + str(getattr(args, name)))
        selected.append(Path(path).resolve())
    qualify(*selected, args.output.resolve())


if __name__ == '__main__':
    main()
