import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--verilator', required=True)
parser.add_argument('--configs', default='')
parser.add_argument('--compile-only', action='store_true')
parser.add_argument('--rtl-source', type=Path)
parser.add_argument('--buffers', type=int, choices=(0, 1), nargs='+', default=[0, 1])
args = parser.parse_args()
build = args.build.resolve()
root = Path(re.search(r'^VORTEX_HOME[ \t]*\?=[ \t]*(.*)$', (build / 'config.mk').read_text(), re.M)[1])
source = root / 'hw/unittest/lmem_switch'
rtl = args.rtl_source or root / 'hw/rtl/mem/VX_lmem_switch.sv'
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
state = {'status': 'RUNNING', 'hardware_accessed': False, 'cases': [],
         'rtl_sha256': hashlib.sha256(rtl.read_bytes()).hexdigest()}
try:
    for buffering in args.buffers:
        for fast_global in (0, 1):
            model = output / f'buffer-{buffering}-global-{fast_global}'
            model.mkdir(exist_ok=True)
            command = [args.verilator, '--binary', '--timing', '--assert', '-j', '8',
                       '--timescale-override', '1ns/1ps', '--top-module', 'lmem_switch_tb',
                       '--Mdir', str(model), '-o', 'lmem-switch-test', '-DSIMULATION',
                       '-DVX_CFG_XLEN=32', '-DVX_CFG_XLEN_32', *shlex.split(args.configs),
                       '-GOUT_BUF=' + str(buffering), '-GFAST_GLOBAL=' + str(fast_global)]
            for directory in (build / 'hw', root / 'hw/rtl', root / 'hw/rtl/libs', root / 'hw/rtl/mem'):
                command += ['-I' + str(directory), '-y', str(directory)]
            command += [str(root / 'hw/rtl/VX_gpu_pkg.sv'), str(rtl), str(source / 'tb.sv')]
            with (model / 'compile.log').open('w') as log:
                subprocess.run(command, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
            case = {'out_buf': buffering, 'fast_global': fast_global, 'compiled': True}
            if not args.compile_only:
                result = subprocess.run([model / 'lmem-switch-test'], cwd=build, capture_output=True, text=True)
                (model / 'run.log').write_text(result.stdout + result.stderr)
                case['exit_code'] = result.returncode
                state['cases'].append(case)
                result.check_returncode()
                if 'PASS: 20 requests, 16 global and 16 local subsets exactly once' not in result.stdout:
                    raise ValueError('Incomplete split-request accounting')
            else:
                state['cases'].append(case)
    state['status'] = 'LMEM_SWITCH_COMPILE_PASS' if args.compile_only else 'LMEM_SWITCH_ASYMMETRIC_BACKPRESSURE_AND_METADATA_EXACTLY_ONCE_PASS'
except BaseException as error:
    state.update(status='FAIL', error=repr(error))
    raise
finally:
    (output / 'manifest.json').write_text(json.dumps(state, indent=2) + '\n')
print(json.dumps(state))
