import importlib.util
import contextlib
import io
import json
import struct
from pathlib import Path
import subprocess
import sys

import pytest


def tensor_runner():
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    spec = importlib.util.spec_from_file_location('ypcb_tensor_runner', root / 'ci/ypcb_run_fpga.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tensor_preflight_rejects_scalar_build_before_hardware(tmp_path):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    build = tmp_path / 'build'
    build.mkdir()
    (build / 'config.mk').write_text(f'VORTEX_HOME ?= {root}\nXLEN ?= 32\nMEMORY_SIZE ?= 2147483648\n')
    output = tmp_path / 'output'
    result = subprocess.run([sys.executable, str(root / 'ci/ypcb_run_fpga.py'),
        '--build', str(build), '--image-run', str(tmp_path / 'missing-image'), '--output', str(output),
        '--vivado-bin', str(tmp_path / 'missing-vivado'), '--crc-checker', str(tmp_path / 'missing-crc'),
        '--hardware-lease', str(tmp_path / 'hardware.lock'), '--stage', 'tensor-kernels'],
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    receipt = json.loads((output / 'manifest.json').read_text())
    assert 'configured ypcb_tcu profile' in receipt['error']
    assert receipt['hardware_accessed'] is False
    assert not (tmp_path / 'hardware.lock').exists()


@pytest.mark.parametrize('missing', ['', 'VX_CFG_EXT_TCU_ENABLE', 'VX_CFG_TCU_INT8_ENABLE',
                                      'VX_CFG_TCU_FP16_ENABLE', 'VX_CFG_NUM_THREADS=8', 'VX_CFG_TCU_TYPE_TFR'])
def test_tensor_image_requires_both_formats(tmp_path, missing):
    flags = ['VX_CFG_EXT_TCU_ENABLE', 'VX_CFG_TCU_TYPE=TFR', 'VX_CFG_TCU_FP16_ENABLE',
             'VX_CFG_TCU_INT8_ENABLE', 'VX_CFG_NUM_THREADS=8', 'VX_CFG_TCU_LATENCY=5', 'VX_CFG_TCU_USE_DSP=1',
             'VX_CFG_TCU_TYPE_TFR']
    directory = tmp_path / 'afu'
    directory.mkdir()
    (directory / 'config.flags').write_text(' '.join('-D' + flag for flag in flags if flag != missing))
    module = tensor_runner()
    if missing:
        with pytest.raises(ValueError, match='frozen dual-format'):
            module.tensor_configuration(tmp_path)
    else:
        assert len(module.tensor_configuration(tmp_path)) == len(flags)


@pytest.mark.parametrize('dtype,source,target', [('fp16', 'fp16 (id=2)', 'fp32 (id=0)'),
                                               ('int8', 'i8 (id=17)', 'i32 (id=16)')])
@pytest.mark.parametrize('failure', ['', 'wrong_format', 'missing_iteration', 'zero_counters', 'no_pass'])
def test_tensor_repeated_numerical_and_retirement_evidence(dtype, source, target, failure):
    log = f'input data type: {source}\noutput data type: {target}\n'
    log += '[iter 0] match (0 errors)\nPERF: instrs=30, cycles=40\n'
    log += '[iter 1] match (0 errors)\nPERF: instrs=30, cycles=40\n'
    log += 'cleanup\nPERF: instrs=30, cycles=40\nPASSED!\n'
    if failure == 'wrong_format':
        log = log.replace(source, 'invalid')
    elif failure == 'missing_iteration':
        log = log.replace('[iter 1] match (0 errors)', '[iter 1] MISMATCH (1 errors)')
    elif failure == 'zero_counters':
        log = log.replace('instrs=30', 'instrs=0')
    elif failure == 'no_pass':
        log = log.replace('PASSED!', '')
    module = tensor_runner()
    if failure:
        with pytest.raises(ValueError, match='Tensor kernel'):
            module.tensor_checks(log, dtype, 'fp32' if dtype == 'fp16' else 'int32')
    else:
        result = module.tensor_checks(log, dtype, 'fp32' if dtype == 'fp16' else 'int32')
        assert result['verified_iterations'] == 2
        assert result['instructions'] == 30


@pytest.mark.parametrize('failure_kind', ['missing_report', 'missing_checks', 'failed_timing', 'producer_not_finished'])
def test_preflight_rejects_before_hardware(tmp_path, failure_kind):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    build, image, output = tmp_path / 'build', tmp_path / 'image', tmp_path / 'output'
    build.mkdir()
    image.mkdir()
    (build / 'config.mk').write_text(f'VORTEX_HOME ?= {root}\nXLEN ?= 32\nMEMORY_SIZE ?= 2147483648\n')
    if failure_kind != 'missing_report':
        checks = {}
        if failure_kind in ('failed_timing', 'producer_not_finished'):
            checks = dict.fromkeys(('setup', 'hold', 'pulse', 'gray_skew', 'route', 'internal_coverage', 'drc'), True)
        if failure_kind == 'failed_timing':
            checks['setup'] = False
        (image / 'report-qualification.json').write_text(json.dumps({
            'status': 'INTERNAL_TIMING_ROUTE_AND_GRAY_SKEW_PASS', 'checks': checks}))
    if failure_kind == 'producer_not_finished':
        (image / 'inputs.json').write_text(json.dumps({'inputs': {}}))
    result = subprocess.run([sys.executable, str(root / 'ci/ypcb_run_fpga.py'),
        '--image-run', str(image), '--build', str(build), '--output', str(output),
        '--vivado-bin', str(tmp_path / 'missing-vivado'),
        '--hardware-lease', str(tmp_path / 'hardware.lock'),
        '--crc-checker', str(tmp_path / 'missing-crc-checker')],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    record = json.loads((output / 'manifest.json').read_text())
    expected = 'FileNotFoundError' if failure_kind == 'missing_report' else 'Exact image has not passed its routed report gates'
    if failure_kind == 'producer_not_finished':
        expected = 'Image producer is not complete'
    assert expected in record['error']
    assert record['hardware_accessed'] is False
    assert record['programming_performed'] is False
    assert record['flash_written'] is False
    assert record['owned_children_exit_codes'] == []
    assert not (tmp_path / 'hardware.lock').exists()


@pytest.mark.parametrize('finalized', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'missing', 'failed', 'interrupted', 'timed_out',
                                     'missing_timeout', 'invalid_timeout', 'wrong_flow'])
def test_image_producer_exit_receipt(tmp_path, finalized, outcome):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    spec = importlib.util.spec_from_file_location('ypcb_fpga_runner', root / 'ci/ypcb_run_fpga.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs = {'routed_finalization': {}} if finalized else {}
    name = 'finalize-exit.json' if finalized else 'implement-exit.json'
    record = {'exit_code': 0, 'interrupted': 0, 'timed_out': False}
    if outcome == 'failed': record['exit_code'] = 1
    if outcome == 'interrupted': record['interrupted'] = 15
    if outcome == 'timed_out': record['timed_out'] = True
    if outcome == 'missing_timeout': record.pop('timed_out')
    if outcome == 'invalid_timeout': record['timed_out'] = 0
    if outcome == 'wrong_flow':
        name = 'implement-exit.json' if finalized else 'finalize-exit.json'
    if outcome != 'missing':
        (tmp_path / name).write_text(json.dumps(record))
    if outcome == 'success':
        result = module.producer_receipt(tmp_path, inputs)
        assert result['file'] == name
        assert result['receipt'] == record
        assert result['sha256'] == module.digest(tmp_path / name)
    else:
        with pytest.raises(ValueError, match='Image producer'):
            module.producer_receipt(tmp_path, inputs)


@pytest.mark.parametrize('start,end,payload,valid', [
    (0x40000000, 0x40001000, b'\x13\0\0\0', True),
    (0x40000000, 0x50000000, b'\x13\0\0\0', True),
    (0x80000000, 0x80001000, b'\x13\0\0\0', False),
    (0x40000000, 0x50000001, b'\x13\0\0\0', False),
    (0x40000000, 0x40000000, b'\x13\0\0\0', False),
    (0x40000000, 0x3fffffff, b'\x13\0\0\0', False),
    (0x40000000, 0x40001000, b'', False),
    (None, None, b'\0' * 15, False),
])
def test_kernel_address_region(tmp_path, start, end, payload, valid):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    spec = importlib.util.spec_from_file_location('ypcb_fpga_runner', root / 'ci/ypcb_run_fpga.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'kernel.vxbin'
    path.write_bytes((struct.pack('<QQ', start, end) if start is not None else b'') + payload)
    if valid:
        assert module.kernel_layout(path) == {'start': start, 'end': end}
    else:
        with pytest.raises(ValueError, match='Kernel image'):
            module.kernel_layout(path)


@pytest.mark.parametrize('name,labels', [
    ('simple_add', ['simple_add']),
    ('elementwise', ['add', 'sub', 'mul', 'div', 'min', 'max', 'relu']),
    ('gemm', ['gemm 5x3 @ 3x7']),
    ('conv', ['conv output=3x3x5']),
    ('pooling', ['pooling max output=2x2x3', 'pooling avg output=2x2x3', 'pooling min output=2x2x3']),
])
@pytest.mark.parametrize('change', ['none', 'missing', 'duplicate', 'backend', 'empty', 'nonfinite'])
def test_basic_example_evidence(name, labels, change):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    loaded = []
    for key, path in [('runner', root / 'ci/ypcb_run_fpga.py'), ('common', root / 'examples/common.py')]:
        spec = importlib.util.spec_from_file_location('ypcb_evidence_' + key, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append(module)
    runner, common = loaded
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        for label in labels:
            common.verify(label, [1.0, -2.0], [1.0, -2.0], 'ypcb')
    log = output.getvalue()
    if change == 'missing':
        log = '\n'.join(log.splitlines()[2:])
    elif change == 'duplicate':
        log += log.splitlines()[0] + '\n'
    elif change == 'backend':
        log = log.replace('driver=ypcb', 'driver=simx')
    elif change == 'empty':
        log = log.replace('elements=2', 'elements=0')
    elif change == 'nonfinite':
        log = log.replace('max_abs_error=0', 'max_abs_error=nan')
    if change == 'none':
        result = runner.example_checks(name, log)
        assert [item['name'] for item in result] == labels
    else:
        with pytest.raises(ValueError):
            runner.example_checks(name, log)
