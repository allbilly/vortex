from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest

from ypcb_macos import EXPECTED, command, validate_case, verify_runtime


def write_metadata(root, metadata):
    path = root / 'runtime.json'
    path.write_text(json.dumps(metadata))
    (root / 'runtime.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  runtime.json\n')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.checkout = Path(self.temporary.name) / 'Git checkout with spaces'
        self.root = self.checkout / 'runtime/ypcb4g'
        self.root.mkdir(parents=True)
        files, layouts = {}, {}
        for index in range(40):
            name = f'tests/kernel{index}/kernel.vxbin'
            path = self.root / 'kernels' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(struct.pack('<QQ', 0x40000000, 0x40000004) + b'\x13\x00\x00\x00')
            layouts[name] = {'start': 0x40000000, 'end': 0x40000004}
            files[str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        cases = []
        for kind, count in {'memory': 1, 'demo': 1, 'sgemm': 1, 'raw': 1,
                            'example': 5, 'study': 21, 'format': 22, 'lrsc': 2}.items():
            cases += [{'name': f'{kind}-{index}', 'kind': kind} for index in range(count)]
        sources = {}
        for name in ['stub.cpp', 'backend.cpp']:
            path = self.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// Offline runtime-verifier fixture\n')
            sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.data = {'schema': 1, 'profile': 'ypcb_blackwell_like_4gb',
                     'bitstream_sha256': EXPECTED, 'board_abi': 5, 'payload_bytes': 4294967296,
                     'CH0_ECC': False, 'CH1_ECC': True, 'files': files,
                     'kernel_layouts': layouts, 'cases': cases, 'targets': {}, 'source_hashes': sources,
                     'runtime_sources': {'stub': ['stub.cpp'], 'ypcb': ['backend.cpp']},
                     'softfloat_specialization': 'RISCV',
                     'softfloat_options': ['-DTHREAD_LOCAL=_Thread_local']}
        write_metadata(self.root, self.data)

    def tearDown(self):
        self.temporary.cleanup()

    def test_relocated_checkout_with_spaces(self):
        relocated = Path(self.temporary.name) / 'another location' / 'checkout'
        shutil.copytree(self.checkout, relocated)
        self.assertEqual(verify_runtime(relocated / 'runtime/ypcb4g', relocated)['payload_bytes'], 4294967296)

    def test_changed_payload_rejected(self):
        path = self.root / next(iter(self.data['files']))
        path.write_bytes(path.read_bytes() + b'x')
        with self.assertRaisesRegex(ValueError, 'changed'):
            verify_runtime(self.root, self.checkout)

    def test_changed_git_source_rejected(self):
        (self.checkout / 'stub.cpp').write_text('// changed\n')
        with self.assertRaisesRegex(ValueError, 'Git checkout source'):
            verify_runtime(self.root, self.checkout)

    def test_runtime_assets_without_checkout_sources_rejected(self):
        isolated = Path(self.temporary.name) / 'assets-only'
        shutil.copytree(self.root, isolated)
        with self.assertRaisesRegex(ValueError, 'Git checkout source'):
            verify_runtime(isolated, isolated)

    def test_changed_metadata_rejected(self):
        (self.root / 'runtime.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify_runtime(self.root, self.checkout)

    def test_wrong_image_rejected(self):
        self.data['bitstream_sha256'] = '0' * 64
        write_metadata(self.root, self.data)
        with self.assertRaisesRegex(ValueError, 'qualified 4 GiB'):
            verify_runtime(self.root, self.checkout)

    def test_missing_case_and_duplicate_case_rejected(self):
        original = copy.deepcopy(self.data)
        self.data['cases'].pop()
        write_metadata(self.root, self.data)
        with self.assertRaises(ValueError):
            verify_runtime(self.root, self.checkout)
        self.data = original
        self.data['cases'][-1] = self.data['cases'][0]
        write_metadata(self.root, self.data)
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            verify_runtime(self.root, self.checkout)

    def test_symlink_escape_rejected(self):
        name = next(iter(self.data['files']))
        path = self.root / name
        outside = Path(self.temporary.name) / 'outside.vxbin'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'outside'):
            verify_runtime(self.root, self.checkout)

    def test_parent_path_in_build_target_rejected(self):
        self.data['targets']['bad'] = {'directory': '../outside', 'executable': 'app', 'sources': []}
        write_metadata(self.root, self.data)
        with self.assertRaisesRegex(ValueError, 'Unsafe host build path'):
            verify_runtime(self.root, self.checkout)

    def test_kernel_outside_memory_window_rejected(self):
        name = next(iter(self.data['kernel_layouts']))
        self.data['kernel_layouts'][name]['end'] = 0x50000004
        write_metadata(self.root, self.data)
        with self.assertRaisesRegex(ValueError, 'memory window'):
            verify_runtime(self.root, self.checkout)


class CommandLifecycleTests(unittest.TestCase):
    def check_sigterm_cleanup(self, during_spawn):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app').write_text('#!' + sys.executable + '\n' + '''
import os
from pathlib import Path
import signal
import socket
import sys
import time

def stop(number, frame):
    Path('stopping').touch()
    while not Path('release').exists():
        time.sleep(0.01)
    sys.exit(0)

signal.signal(signal.SIGTERM, stop)
with socket.create_connection(('127.0.0.1', int(os.environ['VORTEX_YPCB_CHESTNUT_PORT']))) as client:
    client.sendall(b'R 3000\\n')
    assert client.recv(128) == b'OK 56595043\\n'
    Path('ready').touch()
    signal.pause()
''')
            (root / 'app').chmod(0o755)
            harness = root / 'coordinator.py'
            harness.write_text('''
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import patch

import ypcb_macos as workflow
from test_ypcb_chestnut import FakeUsb

root = Path.cwd()
usb = FakeUsb()
request = usb.pcie_request
def emulate_drain(kind, address, value=None):
    result = request(kind, address, value)
    if kind == 0x40 and address == 0x10000000 and value == 0x10:
        usb.memory[0] = 4
    return result
usb.pcie_request = emulate_drain
card = workflow.ChestnutPcie(usb=usb, lock_path=root / 'device.lock')
servers = []
def server(transport):
    instance = original_server(transport)
    servers.append(instance)
    return instance
original_server = workflow.MmioServer
original_popen = subprocess.Popen
during_spawn = sys.argv[1] == 'spawn'
def spawn(*args, **kwargs):
    child = original_popen(*args, **kwargs)
    (root / 'child.pid').write_text(str(child.pid))
    if during_spawn:
        os.kill(os.getpid(), signal.SIGTERM)
    return child
data = {'cases': [{'name': 'memory', 'kind': 'memory', 'target': 'app', 'arguments': []}],
        'targets': {'app': {'directory': '.', 'executable': 'app'}}, 'cflags': [], 'ecc_offsets': []}
try:
    with patch.multiple(workflow, verify_runtime=lambda *args: data, verify_softfloat=lambda *args: None,
                        build_native=lambda *args: root, ChestnutPcie=lambda: card, MmioServer=server), \
         patch.object(workflow.platform, 'system', return_value='Darwin'), \
         patch.object(workflow.subprocess, 'check_output', return_value='offline-test'), \
         patch.object(workflow.subprocess, 'Popen', side_effect=spawn), \
         patch.object(sys, 'argv', ['ypcb_macos.py', 'memory', '--out', str(root / 'result')]), \
         workflow.interrupt_handlers(workflow.interrupt):
        code = workflow.main()
finally:
    (root / 'cleanup.json').write_text(json.dumps({
        'usb_closed': usb.closed, 'configuration_restored': usb.config == usb.original,
        'lock_released': card.lock is None,
        'server_stopped': all(not item.thread.is_alive() for item in servers),
        'quiesced': (0x40, 0, 0x10) in usb.calls}))
sys.exit(code)
''')
            environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent))
            with (root / 'coordinator.log').open('wb') as log:
                coordinator = subprocess.Popen([sys.executable, harness, 'spawn' if during_spawn else 'wait'],
                                               cwd=root, env=environment, stdout=log,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    def wait_for(name):
                        deadline = time.monotonic() + 10
                        while not (root / name).exists():
                            self.assertIsNone(coordinator.poll(), (root / 'coordinator.log').read_text())
                            self.assertLess(time.monotonic(), deadline, name + ' did not appear')
                            time.sleep(0.01)

                    if not during_spawn:
                        wait_for('ready')
                        coordinator.terminate()
                        wait_for('stopping')
                        coordinator.terminate()
                        (root / 'release').touch()
                    self.assertEqual(coordinator.wait(timeout=15), 1,
                                     (root / 'coordinator.log').read_text())
                    receipt = json.loads((root / 'result/memory.receipt.json').read_text())
                    self.assertIn('SIGTERM', receipt['interruption'])
                    self.assertFalse(receipt['timed_out'])
                    self.assertTrue(receipt['actual_exit_available'])
                    self.assertIsInstance(receipt['exit_code'], int)
                    manifest = json.loads((root / 'result/manifest.json').read_text())
                    self.assertEqual(manifest['status'], 'FAIL')
                    self.assertEqual(manifest['cleanup']['status'], 'PASS')
                    self.assertFalse(manifest['physical_PCIe_qualified'])
                    self.assertTrue(all(json.loads((root / 'cleanup.json').read_text()).values()))
                    with self.assertRaises(ProcessLookupError):
                        os.kill(int((root / 'child.pid').read_text()), 0)
                finally:
                    if coordinator.poll() is None:
                        coordinator.kill()
                        coordinator.wait(timeout=5)
                    if (root / 'child.pid').exists():
                        pid = int((root / 'child.pid').read_text())
                        try:
                            if os.getpgid(pid) == pid:
                                os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_sigterm_drains_child_and_restores_pcie_even_if_repeated(self):
        self.check_sigterm_cleanup(during_spawn=False)

    def test_sigterm_during_spawn_retains_child_for_cleanup(self):
        self.check_sigterm_cleanup(during_spawn=True)

    def test_timeout_remains_failure_when_child_handles_termination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'Command failed'):
                command([sys.executable, '-c',
                         'import signal, sys; signal.signal(signal.SIGTERM, lambda *args: sys.exit(0)); '
                         'print("ready", flush=True); signal.pause()'], root, root / 'child.log', timeout=1)
            receipt = json.loads((root / 'child.receipt.json').read_text())
            self.assertTrue(receipt['timed_out'])
            self.assertIn('TimeoutExpired', receipt['interruption'])
            self.assertEqual(receipt['exit_code'], 0)
            self.assertEqual((root / 'child.log').read_text(), 'ready\n')


class NumericalGateTests(unittest.TestCase):
    labels = {'simple_add': ['simple_add'],
              'elementwise': ['add', 'sub', 'mul', 'div', 'min', 'max', 'relu'],
              'gemm': ['gemm 5x3 @ 3x7'], 'conv': ['conv output=1x3x5x2'],
              'pooling': ['pooling max output=1x3x5x2', 'pooling avg output=1x3x5x2',
                          'pooling min output=1x3x5x2']}

    @staticmethod
    def example_log(labels, count=37, error='0'):
        return ''.join(f'PASS {name}: driver=ypcb, float32 elements={count}, max_abs_error={error}\n'
                       for name in labels)

    def test_every_basic_example_requires_named_operations(self):
        for example, labels in self.labels.items():
            case = {'name': 'example-' + example, 'kind': 'example', 'example': example}
            with self.subTest(example=example):
                result = validate_case(case, self.example_log(labels), Path('.'), set())
                self.assertEqual(result['operations'], labels)
                self.assertEqual(result['numerical_groups'], len(labels))
            for changed in [labels[:-1], labels + [labels[0]], labels[:-1] + ['unexpected']]:
                with self.subTest(example=example, labels=changed), self.assertRaises(ValueError):
                    validate_case(case, self.example_log(changed), Path('.'), set())
            if len(labels) > 1:
                for changed in [[labels[0]] * len(labels), labels[:-1] + [labels[0]]]:
                    with self.subTest(example=example, labels=changed), self.assertRaises(ValueError):
                        validate_case(case, self.example_log(changed), Path('.'), set())

    def test_invalid_numerical_evidence_rejected(self):
        case = {'name': 'example-simple_add', 'kind': 'example', 'example': 'simple_add'}
        for count, error in [(0, '0'), (37, 'nan'), (37, 'inf'), (37, '-0.001'), (37, 'invalid')]:
            with self.subTest(count=count, error=error), self.assertRaises(ValueError):
                validate_case(case, self.example_log(['simple_add'], count, error), Path('.'), set())

    def test_empty_and_incomplete_examples_rejected(self):
        case = {'name': 'example-elementwise', 'kind': 'example', 'example': 'elementwise'}
        for text in ['', 'PASSED!',
                     'PASS add: driver=ypcb, float32 elements=37, max_abs_error=0\n']:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                validate_case(case, text, Path('.'), set())

    def test_nonfinite_example_error_rejected(self):
        case = {'name': 'example-simple_add', 'kind': 'example', 'example': 'simple_add'}
        with self.assertRaises(ValueError):
            validate_case(case, 'PASS simple_add: driver=ypcb, float32 elements=37, max_abs_error=nan\n',
                          Path('.'), set())

    def test_missing_4gib_regions_rejected(self):
        with self.assertRaisesRegex(ValueError, 'memory regions'):
            validate_case({'name': 'memory', 'kind': 'memory'},
                          'Verified 8192 bytes at 0x00100000\nPASSED!', Path('.'), set())

    def test_GPU_pass_without_retirement_rejected(self):
        with self.assertRaisesRegex(ValueError, 'retirement'):
            validate_case({'name': 'demo', 'kind': 'demo'}, 'PASSED!', Path('.'), set())

    def test_close_failure_is_not_a_numerical_pass(self):
        with self.assertRaisesRegex(ValueError, 'failure'):
            validate_case({'name': 'demo', 'kind': 'demo'},
                          'PERF: instrs=1, cycles=2\nPASSED!\n[VXDRV] YPCB AFU did not drain on close',
                          Path('.'), set())


if __name__ == '__main__':
    unittest.main()
