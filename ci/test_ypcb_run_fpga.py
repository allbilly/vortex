import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('failure_kind', ['missing_report', 'missing_checks', 'failed_timing'])
def test_preflight_rejects_before_hardware(tmp_path, failure_kind):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    build, image, output = tmp_path / 'build', tmp_path / 'image', tmp_path / 'output'
    build.mkdir()
    image.mkdir()
    (build / 'config.mk').write_text(f'VORTEX_HOME ?= {root}\nXLEN ?= 32\nMEMORY_SIZE ?= 2147483648\n')
    if failure_kind != 'missing_report':
        checks = {}
        if failure_kind == 'failed_timing':
            checks = dict.fromkeys(('setup', 'hold', 'pulse', 'gray_skew', 'route', 'internal_coverage', 'drc'), True)
            checks['setup'] = False
        (image / 'report-qualification.json').write_text(json.dumps({
            'status': 'INTERNAL_TIMING_ROUTE_AND_GRAY_SKEW_PASS', 'checks': checks}))
    result = subprocess.run([sys.executable, str(root / 'ci/ypcb_run_fpga.py'),
        '--image-run', str(image), '--build', str(build), '--output', str(output),
        '--vivado-bin', str(tmp_path / 'missing-vivado'),
        '--hardware-lease', str(tmp_path / 'hardware.lock'),
        '--crc-checker', str(tmp_path / 'missing-crc-checker')],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    record = json.loads((output / 'manifest.json').read_text())
    expected = 'FileNotFoundError' if failure_kind == 'missing_report' else 'Exact image has not passed its routed report gates'
    assert expected in record['error']
    assert record['hardware_accessed'] is False
    assert record['programming_performed'] is False
    assert record['flash_written'] is False
    assert record['owned_children_exit_codes'] == []
    assert not (tmp_path / 'hardware.lock').exists()
