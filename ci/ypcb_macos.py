#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
from collections import Counter
import ctypes
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import time

from ypcb_chestnut import ChestnutPcie, MmioServer

EXPECTED = 'd6ad50f70469d6cf3d25f8ca0f8dee1875988b0ac07bec0fa88b8cd0ff06dfb3'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_runtime(root, checkout):
    root = root.resolve()
    checkout = checkout.resolve()
    expected_manifest = (root / 'runtime.sha256').read_text().split()
    if len(expected_manifest) != 2 or expected_manifest[1] != 'runtime.json' or sha(root / 'runtime.json') != expected_manifest[0]:
        raise ValueError('Runtime metadata checksum mismatch')
    data = json.loads((root / 'runtime.json').read_text())
    if (data['schema'] != 1 or data['bitstream_sha256'] != EXPECTED
            or data['profile'] != 'ypcb_blackwell_like_4gb' or data['board_abi'] != 5
            or data['payload_bytes'] != 4294967296 or data['CH0_ECC'] is not False
            or data['CH1_ECC'] is not True or len(data['cases']) != 54
            or len(data['kernel_layouts']) != 40 or not data['files']):
        raise ValueError('Runtime does not select the qualified 4 GiB Vortex image')
    for name, expected in data['files'].items():
        relative = Path(name)
        path = root / relative
        if (relative.is_absolute() or '..' in relative.parts or not path.is_file()
                or not path.resolve().is_relative_to(root) or sha(path) != expected):
            raise ValueError('Runtime file missing, changed or outside the assets: ' + name)
    for name, expected in data['source_hashes'].items():
        relative = Path(name)
        path = checkout / relative
        if (relative.is_absolute() or '..' in relative.parts or not path.is_file()
                or not path.resolve().is_relative_to(checkout) or sha(path) != expected):
            raise ValueError('Git checkout source is missing or changed: ' + name)
    for name, layout in data['kernel_layouts'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or 'kernels/' + name not in data['files']:
            raise ValueError('Unsafe GPU kernel path: ' + name)
        binary = (root / 'kernels' / name).read_bytes()
        if (len(binary) <= 16 or struct.unpack('<QQ', binary[:16]) != (layout['start'], layout['end'])
                or layout['start'] != 0x40000000 or not layout['start'] < layout['end'] <= 0x50000000):
            raise ValueError('GPU kernel memory window mismatch: ' + name)
    if (len({case['name'] for case in data['cases']}) != 54
            or Counter(case['kind'] for case in data['cases']) != {
                'memory': 1, 'demo': 1, 'sgemm': 1, 'raw': 1,
                'example': 5, 'study': 21, 'format': 22, 'lrsc': 2}):
        raise ValueError('Application case scope is incomplete or duplicated')
    for name, target in data['targets'].items():
        for value in [name, target['directory'], target['executable'], *target['sources']]:
            path = Path(value)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe host build path: ' + value)
        if any(name not in data['source_hashes'] for name in target['sources']):
            raise ValueError('Host target source is outside the verified file map')
    if (set(data['runtime_sources']) != {'stub', 'ypcb'}
            or data['softfloat_specialization'] != 'RISCV'
            or '-DTHREAD_LOCAL=_Thread_local' not in data['softfloat_options']):
        raise ValueError('Native runtime/SoftFloat configuration mismatch')
    for names in data['runtime_sources'].values():
        if not names or any(Path(name).is_absolute() or '..' in Path(name).parts
                            or name not in data['source_hashes'] for name in names):
            raise ValueError('Runtime source is outside the verified file map')
    return data


def verify_softfloat(checkout, data):
    path = checkout / 'third_party/softfloat'
    if not (path / 'source/include/softfloat.h').is_file():
        raise ValueError('Initialize the pinned dependency: git submodule update --init third_party/softfloat')
    revision = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    if revision != data['softfloat_revision'] or dirty:
        raise ValueError('SoftFloat must match the clean pinned Git submodule revision')


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def command(args, cwd, log, timeout=1800, environment=None):
    started = time.monotonic()
    timed_out = False
    interruption = None
    with log.open('wb') as stream:
        child = subprocess.Popen(list(map(str, args)), cwd=cwd, env=environment,
                                 stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        try:
            code = child.wait(timeout=timeout)
        except BaseException as error:
            timed_out = isinstance(error, subprocess.TimeoutExpired)
            interruption = repr(error)
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            code = child.returncode
    result = {'command': list(map(str, args)), 'cwd': str(cwd), 'exit_code': code,
              'actual_exit_available': True, 'timed_out': timed_out,
              'interruption': interruption, 'elapsed_seconds': time.monotonic() - started,
              'log': str(log), 'log_sha256': sha(log)}
    save(log.with_suffix('.receipt.json'), result)
    if code != 0 or timed_out or interruption:
        raise RuntimeError(f'Command failed; inspect {log}')
    return log.read_text()


def build_native(checkout, assets, data, destination):
    print(f'Building native Vortex host code for {platform.system()} {platform.machine()}', flush=True)
    destination.mkdir(parents=True, exist_ok=True)
    host = destination / 'host'
    host.mkdir(exist_ok=True)
    source = checkout
    generated = assets / 'generated/sw'
    runtime = host / 'sw/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    cxx = shlex.split(os.environ.get('CXX', 'c++'))
    cc = shlex.split(os.environ.get('CC', 'cc'))
    darwin = platform.system() == 'Darwin'
    if darwin:
        if platform.machine() not in ('arm64', 'x86_64'):
            raise ValueError('Unsupported native macOS architecture')
        cxx += ['-arch', platform.machine(), '-mmacosx-version-min=12.0']
        cc += ['-arch', platform.machine(), '-mmacosx-version-min=12.0']
    includes = [source / 'sw/runtime/include', source / 'sw/runtime/common',
                source / 'sw/common', source / 'sw/kernel/include', generated, generated / 'ypcb']
    flags = ['-std=c++17', '-O2', '-DNDEBUG', '-Wall', '-Wextra', '-Werror', '-fPIC',
             *data['cflags'], *['-I' + str(path) for path in includes]]
    libraries = ['-dynamiclib', '-pthread'] if darwin else ['-shared', '-pthread']
    stub = [source / name for name in data['runtime_sources']['stub']]
    stub_link = ['-Wl,-install_name,@rpath/libvortex.so'] if darwin else [
        '-ldl', '-Wl,-soname,libvortex.so', '-Wl,-rpath,$ORIGIN']
    command(cxx + flags + list(map(str, stub)) + libraries + stub_link +
            ['-o', str(runtime / 'libvortex.so')], destination, destination / 'build-stub.log')
    backend_link = ['-Wl,-install_name,@rpath/libvortex-ypcb.so'] if darwin else ['-Wl,-z,defs']
    command(cxx + flags + [str(source / name) for name in data['runtime_sources']['ypcb']] + libraries +
            backend_link + ['-o', str(runtime / 'libvortex-ypcb.so')], destination,
            destination / 'build-ypcb.log')
    soft = destination / 'softfloat'
    soft.mkdir(exist_ok=True)
    for name in ['Makefile', 'platform.h']:
        shutil.copyfile(checkout / 'third_party/softfloat/build/Linux-x86_64-GCC' / name, soft / name)
    shutil.copytree(checkout / 'third_party/softfloat/source', soft / 'source', dirs_exist_ok=True)
    soft_command = (' '.join(map(shlex.quote, cc)) +
                    ' -c -Werror-implicit-function-declaration -DSOFTFLOAT_FAST_INT64 '
                    '$(SOFTFLOAT_OPTS) $(C_INCLUDES) -O2 -fPIC -o $@')
    command(['make', '-j' + str(os.cpu_count() or 1),
             'SOURCE_DIR=source', 'SPECIALIZE_TYPE=' + data['softfloat_specialization'],
             'SOFTFLOAT_OPTS=' + ' '.join(data['softfloat_options']), 'COMPILE_C=' + soft_command],
            soft, destination / 'build-softfloat.log')
    shutil.copytree(assets / 'kernels', host, dirs_exist_ok=True)
    shutil.copytree(checkout / 'examples', host / 'examples', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.o', '*.a', '*.so'))
    (host / 'config.mk').write_text('XLEN ?= 32\nMEMORY_SIZE ?= 4294967296\n'
                                  'PROFILE ?= ypcb_blackwell_like_4gb\n')
    built = {}
    for name, record in data['targets'].items():
        binary = host / record['directory'] / record['executable']
        binary.parent.mkdir(parents=True, exist_ok=True)
        sources = [source / path for path in record['sources']]
        key = (tuple(record['sources']), tuple(record['flags']))
        if key in built:
            shutil.copyfile(built[key], binary)
            continue
        print('Building host program: ' + name, flush=True)
        extra = record['flags'] + ['-I' + str(sources[0].parent)]
        links = []
        if record['softfloat']:
            extra.append('-I' + str(checkout / 'third_party/softfloat/source/include'))
            links.append(str(soft / 'softfloat.a'))
        uses_runtime = 'native_bist' not in name and not name.endswith('/raw-memory')
        if uses_runtime:
            links += ['-L' + str(runtime), '-lvortex']
            relative = os.path.relpath(runtime, binary.parent)
            links += ['-Wl,-rpath,' + ('@loader_path/' if darwin else '$ORIGIN/') + relative]
        command(cxx + flags + extra + list(map(str, sources)) + links + ['-pthread', '-o', str(binary)],
                destination, destination / ('build-' + name.replace('/', '_') + '.log'))
        built[key] = binary
    result = {'status': 'NATIVE_HOST_RUNTIME_AND_APPS_BUILT', 'platform': platform.platform(),
              'system': platform.system(), 'machine': platform.machine(),
              'runtime_sha256': sha(assets / 'runtime.json'), 'host': str(host),
              'outputs': {str(p.relative_to(host)): sha(p) for p in host.rglob('*') if p.is_file()},
              'physical_PCIe_tested': False}
    ctypes.CDLL(str(runtime / 'libvortex.so'), mode=ctypes.RTLD_GLOBAL)
    ctypes.CDLL(str(runtime / 'libvortex-ypcb.so'), mode=ctypes.RTLD_GLOBAL)
    if darwin and any((runtime / name).read_bytes()[:4] != bytes.fromhex('cffaedfe')
                      for name in ['libvortex.so', 'libvortex-ypcb.so']):
        raise ValueError('Native macOS runtime must contain Mach-O libraries')
    save(destination / 'build.json', result)
    return host


def validate_case(case, text, assets, flags):
    from ypcb_mac_checks import format_checks, lrsc_checks, study_checks
    if re.search(r'^(?:FAILED|FAIL[!:]|ERROR:|Error:)|%Error|Assertion failed|YPCB AFU did not drain on close', text, re.M):
        raise ValueError('Application reported a failure: ' + case['name'])
    kind = case['kind']
    if kind == 'format':
        return format_checks(text, case['reference'])
    if kind == 'lrsc':
        return lrsc_checks(text, case['reference'])
    if kind == 'study':
        record = case['reference']
        reference = assets / record['reference_log']
        if sha(reference) != record['reference_log_sha256']:
            raise ValueError('Reference log changed')
        configs = record['resolved_reference_configs'].replace(
            '-DVX_PROFILE=ypcb_blackwell_like', '-DVX_PROFILE=ypcb_blackwell_like_4gb').replace(
            '-DVX_CFG_MEM_ADDR_WIDTH=31', '-DVX_CFG_MEM_ADDR_WIDTH=32').replace(
            '-DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=31', '-DVX_CFG_PLATFORM_MEMORY_ADDR_WIDTH=32')
        configured = {**record, 'configs': configs,
                      'gpu_counters': [{}] * record['expected_counter_rows']}
        return study_checks(case['study'], text, configured, reference.read_text(), flags)
    if kind == 'example':
        expected = {'simple_add': 1, 'elementwise': 7, 'gemm': 1, 'conv': 1, 'pooling': 3}
        rows = re.findall(r'^PASS [^:\n]+: driver=ypcb, float32 elements=(\d+), max_abs_error=(\S+)$', text, re.M)
        if len(rows) != expected[case['example']] or any(
                int(count) <= 0 or not math.isfinite(float(error)) or float(error) < 0 for count, error in rows):
            raise ValueError('Basic example numerical checks are incomplete')
        return {'numerical_groups': len(rows)}
    if 'PASSED' not in text:
        raise ValueError('Numerical success marker absent: ' + case['name'])
    if kind == 'memory':
        addresses = re.findall(r'^Verified 8192 bytes at (0x[0-9a-f]{8})$', text, re.M)
        if addresses != ['0x00100000', '0x40100000', '0x7ff6d000', '0x7ff5e000',
                         '0x7ffff000', '0x80100000', '0xfff6d000']:
            raise ValueError('The 4 GiB memory regions are incomplete')
    elif kind == 'raw':
        if ('Verified 27 independent lines covering physical address bits 6..31' not in text
                or 'PASSED: raw CH0/CH1 4 GiB, final byte, cross-channel partial writes and no aliases' not in text):
            raise ValueError('Raw final-byte/boundary/alias probes are incomplete')
    else:
        counters = re.findall(r'^PERF: instrs=(\d+), cycles=(\d+)', text, re.M)
        if not counters or any(min(map(int, row)) <= 0 for row in counters):
            raise ValueError('GPU retirement evidence is incomplete')
    return {'numerical_marker': 'PASSED'}


def main():
    parser = argparse.ArgumentParser(description='Run the flashed Vortex image through Mac/Chestnut')
    parser.add_argument('stage', choices=['preflight', 'build', 'identity', 'memory', 'quick', 'full'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--native', type=Path)
    parser.add_argument('--cold-boot', action='store_true', help='Attest the FPGA card was physically power-cycled')
    args = parser.parse_args()
    checkout = next((path for path in Path(__file__).resolve().parents
                     if (path / '.git').exists() and (path / 'VX_config.toml').is_file()), None)
    if checkout is None:
        raise ValueError('Run the Mac workflow from a Vortex Git checkout')
    assets = checkout / 'runtime/ypcb4g'
    args.out.mkdir(parents=True, exist_ok=False)
    out = args.out.resolve()
    result = {'status': 'PREPARED', 'stage': args.stage, 'bitstream_sha256': EXPECTED,
              'host_platform': platform.platform(), 'host_machine': platform.machine(),
              'runtime_sha256': None, 'cases': {},
              'physical_interface': 'PCIe via Chestnut', 'hardware_accessed': False,
              'physical_PCIe_tested': False, 'physical_PCIe_qualified': False,
              'cold_power_cycle_attested': args.cold_boot, 'cold_boot_verified': False,
              'FPGA_programmed': False, 'flash_written': False,
              'live_bitstream_sha256_verified': False}
    transport = server = None
    runtime_started = False
    failure = None
    try:
        data = verify_runtime(assets, checkout)
        verify_softfloat(checkout, data)
        result['runtime_sha256'] = sha(assets / 'runtime.json')
        result['git_revision'] = subprocess.check_output(
            ['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        if args.stage == 'preflight':
            result['status'] = 'RUNTIME_PREFLIGHT_PASS_NO_DEVICE_OPENED'
        elif args.stage == 'build':
            result['host'] = str(build_native(checkout, assets, data, out / 'native'))
            result['status'] = 'NATIVE_HOST_BUILD_PASS_NO_DEVICE_OPENED'
        else:
            if platform.system() != 'Darwin':
                raise RuntimeError('Physical Chestnut qualification must run on the selected macOS host')
            if args.stage != 'identity':
                if args.native is None:
                    host = build_native(checkout, assets, data, out / 'native')
                else:
                    native = args.native.expanduser().resolve()
                    built = json.loads((native / 'build.json').read_text())
                    if (built['system'] != 'Darwin' or built['machine'] != platform.machine()
                            or built['runtime_sha256'] != result['runtime_sha256']):
                        raise ValueError('Native build does not match this Mac and assets')
                    host = native / 'host'
                    if any(sha(host / name) != value for name, value in built['outputs'].items()):
                        raise ValueError('Native build output changed')
            result['hardware_access_attempted'] = True
            save(out / 'manifest.json', result)
            transport = ChestnutPcie()
            result.update(hardware_accessed=True, identity=transport.identity,
                          physical_PCIe_tested=True)
            if args.stage == 'identity':
                result['status'] = 'PCIE_IDENTITY_PASS_MEMORY_AND_KERNELS_NOT_TESTED'
            else:
                server = MmioServer(transport)
                port = server.start()
                environment = dict(os.environ, VORTEX_DRIVER='ypcb', VORTEX_YPCB_INTERFACE='chestnut',
                                   VORTEX_YPCB_CHESTNUT_PORT=str(port), VORTEX_YPCB_JTAG_PORT=str(port),
                                   VORTEX_CP_POLL_TIMEOUT_S='120', PYTHONUNBUFFERED='1',
                                   DYLD_LIBRARY_PATH=str(host / 'sw/runtime'),
                                   LD_LIBRARY_PATH=str(host / 'sw/runtime'))
                if args.cold_boot:
                    binary = host / 'tests/ypcb/native_bist/native_bist'
                    text = command([binary], binary.parent, out / 'native-bist.log', environment=environment)
                    rows = re.findall(r'^BIST PASS: CH([01]) mode=([0-3]) words=(\d+) payload_bytes=(\d+) '
                                      r'raw_bytes=(\d+) ticks=(\d+) errors=(\d+) lanes=(\d+)$', text, re.M)
                    if (len(rows) != 8 or [(int(v[0]), int(v[1])) for v in rows] !=
                            [(channel, mode) for channel in [0, 1] for mode in range(4)]
                            or any(int(v[2]) != 33554432 or int(v[3]) != 2147483648
                                   or int(v[4]) != 33554432 * (8 if v[0] == '0' else 9) * 8
                                   or int(v[5]) < 33554432 or int(v[6]) != 0
                                   or int(v[7]) != (8 if v[0] == '0' else 9) for v in rows)):
                        raise ValueError('Cold-boot full 4 GiB BIST did not pass')
                    result['native_BIST_passes'] = 8
                quick = {'memory', 'raw-memory', 'demo', 'sgemm', 'format-fp16-square', 'format-int8-square'}
                selected = [case for case in data['cases'] if args.stage == 'full'
                            or args.stage == 'memory' and case['kind'] in ('memory', 'raw')
                            or args.stage == 'quick' and (case['name'] in quick or case['kind'] == 'example')]
                if not selected:
                    raise ValueError('No application cases selected')
                result['expected_cases'] = [case['name'] for case in selected]
                for case in selected:
                    runtime_started = True
                    result['status'] = 'RUNNING_' + case['name']
                    save(out / 'manifest.json', result)
                    print('Running via Chestnut: ' + case['name'], flush=True)
                    if case['kind'] == 'example':
                        cwd = host
                        argv = [sys.executable, host / ('examples/' + case['example'] + '.py'),
                                '--build', host, '--driver', 'ypcb']
                    else:
                        record = data['targets'][case['target']]
                        cwd = host / record['directory']
                        argv = [cwd / record['executable'], *case['arguments']]
                    text = command(argv, cwd, out / (case['name'] + '.log'), environment=environment)
                    checked = validate_case(case, text, assets, set(data['cflags']))
                    ecc = [transport.read32(offset) for offset in data['ecc_offsets']]
                    if ecc != [1, 0, 0]:
                        raise ValueError('CH1 ECC is not enabled and clean after ' + case['name'])
                    result['cases'][case['name']] = {'numerical': checked, 'CH1_ECC': ecc}
                    if server.last_error is not None:
                        raise RuntimeError('Chestnut MMIO server reported: ' + server.last_error)
                    print('PASS ' + case['name'], flush=True)
                if len(result['cases']) != len(selected):
                    raise ValueError('Not every selected case completed')
                result.update(status='MAC_CHESTNUT_' + args.stage.upper() + '_PASS',
                              physical_PCIe_qualified=args.stage == 'full',
                              cold_boot_verified=args.cold_boot)
    except BaseException as error:
        failure = error
        result.update(status='FAIL', error=repr(error))
        if result.get('hardware_access_attempted') and not result['hardware_accessed']:
            result['hardware_accessed'] = None
            result['hardware_access_detail'] = 'Setup failed; USB/configuration access may have occurred'
    finally:
        cleanup_errors = []
        if server is not None:
            try:
                server.close()
            except BaseException as error:
                cleanup_errors.append(repr(error))
        if transport is not None:
            if runtime_started:
                try:
                    transport.quiesce()
                except BaseException as error:
                    cleanup_errors.append(repr(error))
            try:
                transport.close()
            except BaseException as error:
                cleanup_errors.append(repr(error))
        result['cleanup'] = {'status': 'PASS' if not cleanup_errors else 'FAIL', 'errors': cleanup_errors}
        if cleanup_errors:
            result.update(status='FAIL', physical_PCIe_qualified=False, cold_boot_verified=False)
            failure = RuntimeError('Cleanup failed')
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save(out / 'manifest.json', result)
    print(json.dumps({'status': result['status'], 'out': str(out), 'error': str(failure) if failure else None}))
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
