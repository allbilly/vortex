import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--verilator', required=True)
parser.add_argument('--rtl-source', type=Path)
parser.add_argument('--widths', type=int, nargs='+', default=[31, 32, 48])
parser.add_argument('--compile-only', action='store_true')
args = parser.parse_args()
build = args.build.resolve()
configuration = (build / 'config.mk').read_text()
root = Path(configuration.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
profile = re.search(r'^PROFILE[ \t]*\?=[ \t]*(.*)$', configuration, re.M)[1].strip()
xlen = int(re.search(r'^XLEN[ \t]*\?=[ \t]*(\d+)', configuration, re.M)[1])
source = args.rtl_source or root / 'hw/rtl/dxa/VX_dxa_setup.sv'
command = ['python3', str(build / 'ci/gen_config.py'), '--config=' + str(root / 'VX_config.toml'),
           '--merge-configs', '--cflags=' + os.environ.get('CONFIGS', '') + ' -DVX_CFG_EXT_DXA_ENABLE']
if profile:
    command.append('--profile=' + profile)
flags = shlex.split(subprocess.check_output(command, cwd=build, text=True))
flags = [flag for flag in flags if not flag.startswith('-DVX_CFG_MEM_ADDR_WIDTH=')]
args.output.mkdir(parents=True, exist_ok=True)
record = {'status': 'RUNNING', 'rtl_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'testbench_sha256': hashlib.sha256((root / 'hw/unittest/dxa_setup/tb.sv').read_bytes()).hexdigest(),
          'config_flags': flags, 'widths': {}, 'hardware_accessed': False}
try:
    for width in args.widths:
        if width < 1 or width > 64:
            raise ValueError('Memory address width must be between 1 and 64')
        model = args.output.resolve() / ('width-' + str(width))
        model.mkdir(exist_ok=True)
        record.update(active_width=width, active_stage='compile')
        compile_command = [args.verilator, '--binary', '--timing', '--assert', '--timescale-override', '1ns/1ps',
                           '-j', '1', '--top-module', 'dxa_setup_tb', '--Mdir', str(model),
                           '-o', 'dxa-setup-test', *flags, '-DSIMULATION',
                           '-DVX_CFG_XLEN=' + str(xlen), '-DVX_CFG_XLEN_' + str(xlen),
                           '-DVX_CFG_MEM_ADDR_WIDTH=' + str(width),
                           '-I' + str(build / 'hw'), '-I' + str(build / 'sw'),
                           '-I' + str(root / 'hw/rtl'), '-I' + str(root / 'hw/rtl/libs'),
                           '-y', str(root / 'hw/rtl/libs'),
                           str(root / 'hw/rtl/VX_gpu_pkg.sv'), str(root / 'hw/rtl/dxa/VX_dxa_pkg.sv'),
                           str(source), str(root / 'hw/unittest/dxa_setup/tb.sv')]
        with (model / 'compile.log').open('w') as log:
            subprocess.run(compile_command, cwd=build, check=True, stdout=log, stderr=subprocess.STDOUT)
        if args.compile_only:
            record['widths'][str(width)] = {'compiled': True}
            continue
        record['active_stage'] = 'run'
        result = subprocess.run([model / 'dxa-setup-test'], cwd=build, text=True, capture_output=True)
        (model / 'run.log').write_text(result.stdout + result.stderr)
        result.check_returncode()
        traces = [line for line in result.stdout.splitlines() if line.startswith('TRACE ')]
        identifiers = [int(re.search(r'^TRACE id=(\d+) ', line)[1]) for line in traces]
        if identifiers != list(range(160)) or 'PASSED cases=160' not in result.stdout:
            raise ValueError('Incomplete DXA address/timing test')
        record['widths'][str(width)] = {'cases': len(traces), 'trace_sha256': hashlib.sha256('\n'.join(traces).encode()).hexdigest()}
    record.update(status='DXA_SETUP_COMPILE_PASS' if args.compile_only else 'DXA_ADDRESS_WRAP_DELTA_AND_SETUP_LATENCY_PASS',
                  active_width=None, active_stage=None)
except BaseException as error:
    record.update(status='FAIL', error=repr(error), failed_exit_code=getattr(error, 'returncode', None))
    raise
finally:
    (args.output / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
