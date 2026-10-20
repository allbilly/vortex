#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import statistics
import subprocess
import tempfile
import time

interrupted = 0


def interrupt(number, frame):
    global interrupted
    interrupted = number


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop(child):
    if child.poll() is not None:
        return child.returncode
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return child.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image-run', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vivado-bin', type=Path, required=True)
    parser.add_argument('--hardware-lease', type=Path, required=True)
    parser.add_argument('--crc-checker', type=Path, required=True)
    parser.add_argument('--stage', choices=('probe', 'kernels'), default='probe')
    parser.add_argument('--tck-hz', type=int, choices=(3000000, 6000000), default=3000000)
    parser.add_argument('--server-port', type=int, default=3122)
    parser.add_argument('--jtag-port', type=int, default=3124)
    args = parser.parse_args()
    if (not 0 < args.server_port < 65536 or not 0 < args.jtag_port < 65536
            or args.server_port == args.jtag_port):
        parser.error('Hardware server and JTAG MMIO ports must be distinct valid TCP ports')
    image, build, output = args.image_run.resolve(), args.build.resolve(), args.output.resolve()
    vivado = args.vivado_bin.resolve()
    output.mkdir(parents=True, exist_ok=False)
    state = {'status': 'PREFLIGHT', 'stage': args.stage, 'hardware_accessed': False,
             'programming_attempted': False, 'programming_performed': False, 'flash_written': False,
             'image_run': str(image), 'tck_hz': args.tck_hz, 'steps': {}}
    children = []
    lease = None
    bridge = None
    bridge_ready = False

    def save():
        state['utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with tempfile.NamedTemporaryFile('w', dir=output, delete=False) as stream:
            json.dump(state, stream, indent=2)
            stream.write('\n')
            temporary = stream.name
        os.replace(temporary, output / 'manifest.json')

    def launch(name, command, cwd, environment=None):
        with (output / (name + '.log')).open('w') as log:
            child = subprocess.Popen([str(x) for x in command], cwd=cwd,
                                     env=environment, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        children.append(child)
        state[name + '_pid'] = child.pid
        save()
        return child

    def step(name, command, cwd, timeout=600, environment=None, atomic=False):
        if interrupted:
            raise InterruptedError('Interrupted before ' + name)
        child = launch(name, command, cwd, environment)
        started = time.monotonic()
        while child.poll() is None:
            if time.monotonic() - started > timeout or (interrupted and not atomic):
                stop(child)
                break
            time.sleep(0.1)
        code = child.wait()
        state['steps'][name] = {'command': [str(x) for x in command], 'exit_code': code,
                                'elapsed_seconds': time.monotonic() - started}
        save()
        if code != 0 or interrupted or time.monotonic() - started > timeout:
            raise RuntimeError(name + ' failed; inspect ' + str(output / (name + '.log')))
        return (output / (name + '.log')).read_text()

    def port_free(port):
        with socket.socket() as sock:
            return sock.connect_ex(('127.0.0.1', port)) != 0

    def read_words(offsets, timeout=30):
        values, durations = [], []
        with socket.create_connection(('127.0.0.1', args.jtag_port), timeout=timeout) as connection:
            with connection.makefile('rb') as stream:
                for offset in offsets:
                    started = time.monotonic()
                    connection.sendall(f'R {offset:04x}\n'.encode())
                    line = stream.readline(64)
                    if not re.fullmatch(rb'OK [0-9a-fA-F]{8}\n', line):
                        raise RuntimeError('JTAG MMIO response: ' + repr(line))
                    values.append(int(line[3:11], 16))
                    durations.append(time.monotonic() - started)
        return values, durations

    try:
        save()
        configuration = (build / 'config.mk').read_text()
        if 'MEMORY_SIZE ?= 2147483648' not in configuration or 'XLEN ?= 32' not in configuration:
            raise ValueError('FPGA examples require the configured RV32, 2 GiB YPCB build')
        root = Path(configuration.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0]).resolve()
        qualification = json.loads((image / 'report-qualification.json').read_text())
        required = {'setup', 'hold', 'pulse', 'gray_skew', 'route', 'internal_coverage', 'drc'}
        if (qualification['status'] != 'INTERNAL_TIMING_ROUTE_AND_GRAY_SKEW_PASS'
                or not required.issubset(qualification['checks']) or not all(qualification['checks'].values())):
            raise ValueError('Exact image has not passed its routed report gates')
        inputs = json.loads((image / 'inputs.json').read_text())
        for name, expected in inputs['inputs'].items():
            if digest(image / name) != expected:
                raise ValueError('Frozen image input changed: ' + name)
        bit = image / 'vortex_ypcb.bit'
        state['bitstream_sha256'] = digest(bit)
        state['qualification'] = qualification
        state['source_revision'] = inputs['source_revision']
        state['crc_checker_sha256'] = digest(args.crc_checker.resolve())
        state['host_tools'] = {name: digest(root / name) for name in (
            'hw/syn/xilinx/ypcb/program_sram.tcl', 'hw/syn/xilinx/ypcb/jtag_server.tcl')}
        board = output / 'tools'
        board.mkdir()
        for name, expected in state['host_tools'].items():
            target = board / Path(name).name
            shutil.copy2(root / name, target)
            if digest(target) != expected:
                raise ValueError('Hardware tool changed while snapshotting: ' + name)
        crc = json.loads(step('crc', [args.crc_checker.resolve(), bit], output, timeout=120))
        if crc['status'] != 'ALL_PRESENT_CRC_CHECKPOINTS_MATCH' or crc['known_answer_vectors'] != 4:
            raise ValueError('Bitstream integrity check did not pass')
        state['crc'] = crc
        if args.stage == 'kernels':
            artifacts = ['sw/runtime/libvortex.so', 'sw/runtime/libvortex-ypcb.so',
                         'tests/ypcb/memory_map/memory_map', 'tests/regression/demo/demo',
                         'tests/regression/demo/kernel.vxbin', 'tests/regression/sgemm/sgemm',
                         'tests/regression/sgemm/kernel.vxbin', 'config.mk', 'sw/VX_types.h']
            state['runtime_artifacts'] = {name: digest(build / name) for name in artifacts}
            host = output / 'host'
            for name, expected in state['runtime_artifacts'].items():
                target = host / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(build / name, target)
                if digest(target) != expected:
                    raise ValueError('Runtime artifact changed while snapshotting: ' + name)
            header = build / 'sw/ypcb/ypcb_ddr_config.h'
            metadata = json.loads(header.with_suffix('.json').read_text())
            if digest(header) != metadata['output_sha256']:
                raise ValueError('Runtime DDR configuration header changed')
            for name, expected in metadata['inputs'].items():
                if digest(Path(name)) != expected:
                    raise ValueError('Runtime DDR configuration input changed: ' + name)
            csr_file = next(Path(name) for name in metadata['inputs'] if Path(name).name == 'csr.json')
            if digest(csr_file.parent / 'gateware/ypcb_ddr3.v') != inputs['inputs']['ddr/gateware/ypcb_ddr3.v']:
                raise ValueError('Runtime DDR configuration does not match the compiled controller')
            registers = json.loads(csr_file.read_text())['csr_registers']
            ecc_names = ('enable', 'sec_errors', 'ded_errors')
            ecc_offsets = [0x6000 + registers['ecc_axi_0_' + name]['addr'] for name in ecc_names]
            if any(offset % 4 or not 0x6000 <= offset < 0x8000 for offset in ecc_offsets):
                raise ValueError('ECC status registers escape the CH1 CSR window')
            state['ddr_configuration_header_sha256'] = digest(header)
        args.hardware_lease.parent.mkdir(parents=True, exist_ok=True)
        lease = args.hardware_lease.open('a+')
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in ('hw_server', 'cs_server', 'openFPGALoader', 'xsdb', 'fxload'):
            if subprocess.run(['pgrep', '-x', name], stdout=subprocess.DEVNULL).returncode != 1:
                raise RuntimeError('Existing hardware owner: ' + name)
        if not port_free(args.server_port) or not port_free(args.jtag_port):
            raise RuntimeError('Hardware server or JTAG MMIO port already owned')
        cables = [line for line in subprocess.check_output(['lsusb'], text=True).splitlines() if 'ID 03fd:' in line]
        if len(cables) != 1 or '03fd:0008' not in cables[0]:
            raise RuntimeError('Expected one initialized YPCB JTAG cable')
        state['usb'] = cables
        selected = output / 'program.bit'
        shutil.copy2(bit, selected)
        if digest(selected) != state['bitstream_sha256']:
            raise ValueError('Selected bitstream copy changed')
        server = launch('hw-server', [vivado / 'hw_server', '-s', f'tcp::{args.server_port}'], output)
        deadline = time.monotonic() + 30
        while port_free(args.server_port):
            if server.poll() is not None or interrupted or time.monotonic() > deadline:
                raise RuntimeError('Hardware server did not start')
            time.sleep(0.1)
        state['hardware_accessed'] = True
        save()
        url = f'localhost:{args.server_port}'
        state.update(status='PROGRAMMING_SRAM', programming_attempted=True)
        save()
        step('program', [vivado / 'vivado', '-mode', 'batch', '-nojournal', '-nolog',
             '-source', board / 'program_sram.tcl', '-tclargs', selected,
             output / 'program-status.txt', url, args.tck_hz], output, atomic=True)
        if (output / 'program-status.txt').read_text().strip() != 'INIT=1 DONE=1 IDCODE=23751093':
            raise ValueError('Fresh SRAM programming status missing')
        if digest(selected) != state['bitstream_sha256'] or digest(bit) != state['bitstream_sha256']:
            raise ValueError('Bitstream changed during programming')
        state['programming_performed'] = True
        bridge = launch('bridge', [vivado / 'vivado', '-mode', 'batch', '-nojournal', '-nolog',
                        '-source', board / 'jtag_server.tcl', '-tclargs', url,
                        args.jtag_port, args.tck_hz], output)
        deadline = time.monotonic() + 180
        while not re.search(r'^YPCB_JTAG_MMIO_READY port=' + str(args.jtag_port) + r'$', (output / 'bridge.log').read_text(), re.M):
            if bridge.poll() is not None or interrupted or time.monotonic() > deadline:
                raise RuntimeError('Native JTAG AXI bridge did not become ready')
            time.sleep(0.2)
        bridge_ready = True
        values, durations = read_words([0x3000, 0x3004, 0x3008] + [0x3000] * 32)
        if values[0] != 0x56595043 or values[1] != 3 or any(value != 0x56595043 for value in values[3:]):
            raise ValueError('FPGA does not consistently expose the CH1 ABI 3 image')
        state['initial_status'] = values[2]
        samples = durations[3:]
        state['mmio_probe'] = {'reads': len(samples), 'median_seconds': statistics.median(samples),
                               'min_seconds': min(samples), 'max_seconds': max(samples)}
        state['status'] = 'SRAM_AND_JTAG_MMIO_PASS_DDR_KERNELS_NOT_TESTED'
        save()
        if args.stage == 'kernels':
            environment = dict(os.environ, VORTEX_DRIVER='ypcb', VORTEX_YPCB_INTERFACE='jtag',
                               VORTEX_YPCB_JTAG_PORT=str(args.jtag_port), VORTEX_CP_POLL_TIMEOUT_S='120',
                               LD_LIBRARY_PATH=str(host / 'sw/runtime') + ':' + os.environ.get('LD_LIBRARY_PATH', ''))
            for name, relative, arguments in (
                ('memory', 'tests/ypcb/memory_map', ['memory_map']),
                ('demo', 'tests/regression/demo', ['demo', '-n64']),
                ('sgemm', 'tests/regression/sgemm', ['sgemm', '-n16']),
            ):
                directory = host / relative
                log = step(name, [directory / arguments[0], *arguments[1:]], directory,
                           timeout=1200, environment=environment)
                if 'PASSED' not in log:
                    raise ValueError(name + ' did not verify its results')
                ecc, _ = read_words(ecc_offsets)
                state[name + '_ecc'] = dict(zip(ecc_names, ecc))
                save()
                if ecc != [1, 0, 0]:
                    raise ValueError(name + ' did not retain enabled, clean CH1 ECC')
                if name != 'memory':
                    counters = re.search(r'PERF: instrs=(\d+), cycles=(\d+)', log)
                    if counters is None or min(map(int, counters.groups())) <= 0:
                        raise ValueError(name + ' has no retired-instruction/cycle evidence')
                    state[name + '_counters'] = dict(zip(('instructions', 'cycles'), map(int, counters.groups())))
            state['status'] = 'FPGA_MEMORY_DEMO_AND_SGEMM_PASS'
    except BaseException as error:
        state.update(status='FAIL', error=repr(error), interrupted=interrupted)
        if bridge_ready and bridge is not None and bridge.poll() is None:
            try:
                offsets = [0x3000, 0x3004, 0x3008] + (ecc_offsets if args.stage == 'kernels' else [])
                values, _ = read_words(offsets, timeout=3)
                state['failure_register_snapshot'] = dict(zip(map(hex, offsets), values))
            except BaseException as snapshot_error:
                state['failure_snapshot_error'] = repr(snapshot_error)
        raise
    finally:
        state['owned_children_exit_codes'] = [stop(child) for child in reversed(children)]
        if lease is not None:
            lease.close()
        save()
    print(json.dumps(state, indent=2))


if __name__ == '__main__':
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    main()
