import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


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
@pytest.mark.parametrize('outcome', ['success', 'missing', 'failed', 'interrupted', 'timed_out', 'wrong_flow'])
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
