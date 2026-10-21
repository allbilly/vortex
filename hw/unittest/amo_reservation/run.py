import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--verilator', required=True)
parser.add_argument('--compile-only', action='store_true')
args = parser.parse_args()
build = args.build.resolve()
configuration = (build / 'config.mk').read_text()
root = Path(re.search(r'^VORTEX_HOME[ \t]*\?=[ \t]*(.*)$', configuration, re.M)[1])
source = root / 'hw/unittest/amo_reservation'
args.output.mkdir(parents=True, exist_ok=True)
output = args.output.resolve()
state = {'status': 'RUNNING', 'cases': [], 'hardware_accessed': False}
try:
    subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(root / 'sim/simx/amo'), str(source / 'oracle.cpp'), '-o', str(output / 'oracle')],
                   cwd=build, check=True)
    for threads, warps in [(4, 4), (8, 8), (16, 8)]:
        harts = threads * warps
        model = output / str(harts)
        model.mkdir(exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-j', '1',
                   '--timescale-override', '1ns/1ps', '--top-module', 'reservation_tb',
                   '--Mdir', str(model), '-o', 'reservation-test',
                   '-DSIMULATION', '-DVX_CFG_XLEN=32', '-DVX_CFG_XLEN_32',
                   '-DVX_CFG_NUM_THREADS=' + str(threads), '-DVX_CFG_NUM_WARPS=' + str(warps),
                   *['-I' + str(p) for p in [build / 'hw', build / 'sw', root / 'hw/rtl',
                                           root / 'hw/rtl/libs', root / 'hw/rtl/cache']],
                   '-y', str(root / 'hw/rtl/libs'), '-y', str(root / 'hw/rtl/cache'),
                   str(root / 'hw/rtl/VX_gpu_pkg.sv'), str(source / 'tb.sv')]
        with (model / 'compile.log').open('w') as log:
            subprocess.run(command, cwd=build, check=True, stdout=log, stderr=subprocess.STDOUT)
        if args.compile_only:
            state['cases'].append({'harts': harts, 'compiled': True})
            continue
        vectors = [(1, 0, 1, 0, 0)]
        vectors += [(1, h, 1, 0, 0) for h in range(1, harts)]
        vectors += [(2, 0, 1, 0, 1), (0, 0, 1, 0, 0)]
        # Abandoned holders expire; foreign failed SC must preserve the owner.
        vectors += [(1, 0, 1, 0, 0), (2, 1, 1, 0, 0), (0, 0, 1, 0, 1)]
        vectors += [(1, 1, 1, 0, 0)] * (harts - 1)
        vectors += [(0, 0, 1, 0, 1), (1, 1, 1, 0, 0), (0, 1, 1, 0, 1)]
        vectors += [(3, 1, 1, 1, 1), (0, 1, 1, 0, 1), (3, 1, 1, 0, 1), (0, 1, 1, 0, 0)]
        vectors += [(1, 0, 1, 0, 0), (1, 1, 5, 0, 0), (0, 0, 1, 0, 0), (0, 1, 5, 0, 1)]
        rng = random.Random(731)
        vectors += [(rng.randrange(4), rng.randrange(harts), rng.randrange(16), rng.randrange(5) == 0, -1)
                    for _ in range(2048)]
        vector_path = model / 'vectors.txt'
        vector_path.write_text(''.join(' '.join(str(int(x)) for x in row) + '\n' for row in vectors))
        results = {}
        for name, cmd in [('rtl', [model / 'reservation-test', '+vectors=' + str(vector_path)]),
                          ('simx', [output / 'oracle', vector_path, str(harts - 1)])]:
            result = subprocess.run(cmd, cwd=build, capture_output=True, text=True)
            (model / (name + '.log')).write_text(result.stdout + result.stderr)
            result.check_returncode()
            results[name] = [line for line in result.stdout.splitlines() if line.startswith('TRACE ')]
        assert len(results['rtl']) == len(vectors) and results['rtl'] == results['simx']
        state['cases'].append({'harts': harts, 'vectors': len(vectors),
                               'trace_sha256': hashlib.sha256('\n'.join(results['rtl']).encode()).hexdigest()})
    state['status'] = 'RESERVATION_COMPILE_PASS' if args.compile_only else 'BOUNDED_RESERVATION_RTL_SIMX_TRACE_AND_PROGRESS_PASS'
except BaseException as error:
    state.update(status='FAIL', error=repr(error))
    raise
finally:
    (output / 'manifest.json').write_text(json.dumps(state, indent=2) + '\n')
print(json.dumps(state))
