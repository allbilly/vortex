import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_from_build(build):
    config = (build / 'config.mk').read_text()
    match = re.search(r'^VORTEX_HOME[ \t]*\?=[ \t]*(.*)$', config, re.M)
    if match is None:
        raise ValueError('Generated build has no VORTEX_HOME')
    return Path(match[1].strip()).resolve()


parser = argparse.ArgumentParser(description='Check ABI4/ABI5 YPCB calibration report gates with generated headers')
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--dual-header', type=Path, required=True,
                    help='Directory containing the generated ABI5 ypcb_wl_config.h')
parser.add_argument('--legacy-header', type=Path, required=True,
                    help='Directory containing the generated ABI4 ypcb_wl_config.h')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--cxx', default='g++')
args = parser.parse_args()

build = args.build.resolve()
source = source_from_build(build)
test = source / 'tests/ypcb/wl_selfcal/channel_matrix.cpp'
implementation = source / 'sw/common/ypcb_wl_calibration.cpp'
headers = {
    'ABI4': args.legacy_header.resolve(),
    'ABI5': args.dual_header.resolve(),
}
expected = {
    'ABI4': ('#define YPCB_WL_DUAL_CHANNEL 0', 'board_abi = 4u', 'memory_ready_mask = 2u', 'payload_bytes = 2147483648ull'),
    'ABI5': ('#define YPCB_WL_DUAL_CHANNEL 1', 'board_abi = 5u', 'memory_ready_mask = 3u', 'payload_bytes = 4294967296ull'),
}
for mode, directory in headers.items():
    header = directory / 'ypcb_wl_config.h'
    if not header.is_file():
        raise ValueError(f'Missing generated {mode} header: {header}')
    text = header.read_text()
    if not all(token in text for token in expected[mode]):
        raise ValueError(f'Generated header does not describe the requested {mode} configuration')

output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
state = {'status': 'RUNNING', 'hardware_accessed': False, 'source_revision':
         subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip(),
         'test_source_sha256': sha(test), 'implementation_sha256': sha(implementation), 'modes': {}}
try:
    for mode in ('ABI4', 'ABI5'):
        model = output / mode.lower()
        model.mkdir(parents=True, exist_ok=True)
        header = headers[mode] / 'ypcb_wl_config.h'
        command = [args.cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
                   '-I' + str(headers[mode]), '-I' + str(source / 'sw/common'),
                   str(test), str(implementation), '-o', str(model / 'channel-report-test')]
        with (model / 'compile.log').open('w') as log:
            subprocess.run(command, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([str(model / 'channel-report-test')], cwd=build,
                                capture_output=True, text=True)
        run_log = result.stdout + result.stderr
        (model / 'run.log').write_text(run_log)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, result.args, run_log)
        marker = 'PASS: ABI4' if mode == 'ABI4' else 'PASS: ABI5'
        if marker not in run_log:
            raise ValueError(f'{mode} hostmock did not report success')
        state['modes'][mode] = {'header_path': str(header), 'header_sha256': sha(header),
                                'command': command, 'exit_code': result.returncode,
                                'output': run_log.strip()}
    state['status'] = 'YPCB_WL_CALIBRATION_ABI4_AND_ABI5_HOSTMOCK_PASS'
except BaseException as error:
    state['status'] = 'FAIL'
    state['error'] = repr(error)
    raise
finally:
    (output / 'manifest.json').write_text(json.dumps(state, indent=2) + '\n')

print(json.dumps(state))
