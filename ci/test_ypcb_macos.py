from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from ypcb_macos import EXPECTED, validate_case, verify_runtime


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


class NumericalGateTests(unittest.TestCase):
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
