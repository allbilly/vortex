import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configured_source(build):
    config = (build / 'config.mk').read_text()
    match = re.search(r'^VORTEX_HOME[ \t]*\?=[ \t]*(.*)$', config, re.M)
    if match is None:
        raise ValueError('Configured build has no VORTEX_HOME binding')
    source = Path(match[1].strip()).resolve()
    if not (source / 'hw/syn/xilinx/ypcb/VX_ypcb_memory.sv').is_file():
        raise ValueError('Configured VORTEX_HOME does not contain VX_ypcb_memory.sv')
    return source


parser = argparse.ArgumentParser(description='Route AXI traffic through both YPCB channel modes')
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--verilator', type=Path, required=True)
parser.add_argument('--compile-only', action='store_true')
args = parser.parse_args()

build = args.build.resolve()
verilator = args.verilator.resolve()
source = configured_source(build)
test_dir = source / 'hw/unittest/ypcb_memory'
rtl = source / 'hw/syn/xilinx/ypcb/VX_ypcb_memory.sv'
testbench = test_dir / 'tb.sv'
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)

search_dirs = (
    build / 'hw',
    source / 'hw/rtl',
    source / 'hw/rtl/libs',
    source / 'hw/rtl/mem',
    source / 'hw/syn/xilinx/ypcb',
)
for directory in search_dirs:
    if not directory.is_dir():
        raise ValueError('Missing RTL search directory: ' + str(directory))

state = {
    'status': 'RUNNING',
    'hardware_accessed': False,
    'dual_channel_override': 1,
    'single_channel_override': 0,
    'source_revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip(),
    'rtl_sha256': sha(rtl),
    'testbench_sha256': sha(testbench),
    'cases': [],
}
model = output / 'model'
model.mkdir(parents=True, exist_ok=True)
command = [
    str(verilator), '--binary', '--timing', '--assert', '-j', '8',
    '--timescale-override', '1ns/1ps', '--top-module', 'ypcb_memory_tb',
    '--Mdir', str(model), '-o', 'ypcb-memory-test', '-DSIMULATION',
]
for directory in search_dirs:
    command += ['-I' + str(directory), '-y', str(directory)]
command += [str(rtl), str(testbench)]

try:
    with (output / 'compile.log').open('w') as log:
        subprocess.run(command, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
    state['compile_command'] = command
    state['compiled'] = True
    if args.compile_only:
        state['status'] = 'YPCB_MEMORY_DUAL_AND_SINGLE_CHANNEL_COMPILE_PASS'
    else:
        completed = subprocess.run([str(model / 'ypcb-memory-test')],
                                   cwd=build, capture_output=True, text=True)
        run_log = completed.stdout + completed.stderr
        (output / 'run.log').write_text(run_log)
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, completed.args, run_log)
        if 'PASS: YPCB memory dual-channel and legacy single-channel routing' not in run_log:
            raise ValueError('The testbench did not report both channel modes passing')
        state['run_exit_code'] = completed.returncode
        state['status'] = 'YPCB_MEMORY_DUAL_AND_SINGLE_CHANNEL_ROUTING_PASS'
except BaseException as error:
    state['status'] = 'FAIL'
    state['error'] = repr(error)
    raise
finally:
    (output / 'manifest.json').write_text(json.dumps(state, indent=2) + '\n')

print(json.dumps(state))
