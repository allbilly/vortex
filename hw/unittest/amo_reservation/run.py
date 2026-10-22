import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shlex
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--verilator', required=True)
parser.add_argument('--compile-only', action='store_true')
parser.add_argument('--cflags', default='-DVX_CFG_XLEN=32 -DVX_CFG_XLEN_32')
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
                    '-DNDEBUG', *shlex.split(args.cflags),
                    *['-I' + str(p) for p in [root / 'sim/simx/amo', root / 'sim/simx', root / 'sim/common', root / 'sw/common', build / 'sw']],
                    str(source / 'oracle.cpp'), str(root / 'sim/simx/amo/amo_unit.cpp'), '-o', str(output / 'oracle')],
                   cwd=build, check=True)
    geometries = [(4, 4, 4, 4, False, 0, 0), (8, 8, 4, 6, False, 0, 0),
                  (16, 8, 4, 7, False, 0, 0), (8, 8, 8, 6, True, 6, 0),
                  (8, 8, 8, 6, True, 7, 1), (8, 8, 8, 6, True, 6, 3)]
    for threads, warps, entries, credit_bits, global_cache, line_bits, bank_bits in geometries:
        harts = threads * warps
        credits = (1 << credit_bits) - 1
        model = output / f'{harts}-slots{entries}-global{int(global_cache)}-L{line_bits}-B{bank_bits}'
        model.mkdir(exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-j', '1',
                   '-GNUM_RES_ENTRIES=' + str(entries), '-GHOLD_CREDIT_BITS=' + str(credit_bits),
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
            state['cases'].append({'harts': harts, 'slots': entries, 'global': global_cache, 'line_bits': line_bits, 'bank_bits': bank_bits, 'compiled': True})
            continue
        vectors = [(1, 0, 1, 0, 0)]
        vectors += [(1, h, 1, 0, 0) for h in range(1, credits + 1)]
        vectors += [(2, 0, 1, 0, 1), (0, 0, 1, 0, 0)]
        # Abandoned holders expire; foreign failed SC must preserve the owner.
        vectors += [(1, 0, 1, 0, 0), (2, 1, 1, 0, 0), (0, 0, 1, 0, 1)]
        vectors += [(1, 1, 1, 0, 0)] * credits
        vectors += [(0, 0, 1, 0, 1), (1, 1, 1, 0, 0), (0, 1, 1, 0, 1)]
        vectors += [(3, 1, 1, 1, 1), (0, 1, 1, 0, 1), (3, 1, 1, 0, 1), (0, 1, 1, 0, 0)]
        alias = 1 + entries
        vectors += [(1, 0, 1, 0, 0), (1, 1, alias, 0, 0),
                    (0, 0, 1, 0, 1), (0, 1, alias, 0, 0),
                    (2, 0, 1, 0, 1), (1, 1, alias, 0, 0), (2, 1, alias, 0, 1)]
        # A same-hart LR replaces even a held different-tag entry.
        vectors += [(1, 0, 1, 0, 0), (1, 0, alias, 0, 0),
                    (0, 0, 1, 0, 0), (2, 0, alias, 0, 1)]
        # Keep the former 8192-retry false-alias schedule unchanged.
        progress_start = len(vectors)
        vectors += [(1, 0, 1, 0, 0), (1, 1, alias, 0, 0)]
        vectors += [(2, 0, 1, 0, -1), (1, 0, 1, 0, -1),
                    (2, 1, alias, 0, -1), (1, 1, alias, 0, -1)] * 8192
        progress_end = len(vectors)
        rng = random.Random(731)
        vectors += [(rng.randrange(4), rng.randrange(harts), rng.randrange(16), rng.randrange(5) == 0, -1)
                    for _ in range(2048)]
        vector_path = model / 'vectors.txt'
        vector_path.write_text(''.join(' '.join(str(int(x)) for x in row) + '\n' for row in vectors))
        results = {}
        for name, cmd in [('rtl', [model / 'reservation-test', '+vectors=' + str(vector_path)]),
                          ('simx', [output / 'oracle', vector_path, str(credits), str(entries), str(int(global_cache)), str(line_bits), str(bank_bits)])]:
            result = subprocess.run(cmd, cwd=build, capture_output=True, text=True)
            (model / (name + '.log')).write_text(result.stdout + result.stderr)
            result.check_returncode()
            results[name] = [line for line in result.stdout.splitlines() if line.startswith('TRACE ')]
        assert len(results['rtl']) == len(vectors) and results['rtl'] == results['simx']
        progress = [row.split() for row in results['rtl'][progress_start:progress_end]]
        successes = sum(row[2] == '2' and row[6] == '1' for row in progress)
        assert successes > 0, 'Fair false-alias schedule made no SC progress'
        state['cases'].append({'harts': harts, 'slots': entries, 'hold_credits': credits,
                               'global': global_cache, 'line_bits': line_bits, 'bank_bits': bank_bits,
                               'false_alias_sc_successes': successes, 'vectors': len(vectors),
                               'trace_sha256': hashlib.sha256('\n'.join(results['rtl']).encode()).hexdigest()})
    state['status'] = 'RESERVATION_COMPILE_PASS' if args.compile_only else 'BOUNDED_RESERVATION_RTL_SIMX_TRACE_AND_PROGRESS_PASS'
except BaseException as error:
    state.update(status='FAIL', error=repr(error))
    raise
finally:
    (output / 'manifest.json').write_text(json.dumps(state, indent=2) + '\n')
print(json.dumps(state))
