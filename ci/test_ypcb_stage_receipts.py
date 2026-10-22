import json
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import time

import pytest


def board_tools():
    config = (Path.cwd() / 'config.mk').read_text()
    root = Path(config.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    return root / 'hw/syn/xilinx/ypcb'


@pytest.mark.parametrize('producer', ['build', 'finalize'])
@pytest.mark.parametrize('outcome', ['success', 'failed', 'interrupted', 'timed_out'])
def test_native_stage_exit_and_disposition(tmp_path, producer, outcome):
    output = tmp_path / 'output'
    child = tmp_path / 'child'
    child.write_text(
        '#!' + sys.executable + '\n'
        'from pathlib import Path\nimport signal, sys, time\n'
        'signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n'
        f'Path({str(tmp_path / "ready")!r}).write_text("ready")\n'
        + ('sys.exit(0)\n' if outcome == 'success' else
           'sys.exit(7)\n' if outcome == 'failed' else
           'while True: time.sleep(0.05)\n'))
    child.chmod(0o755)
    script = board_tools() / ('build_vivado.py' if producer == 'build' else 'finalize_vivado.py')
    wrapper = '''import pathlib, runpy, signal, sys
scope = runpy.run_path(sys.argv[1])
signal.signal(signal.SIGTERM, scope['interrupt'])
output, child, producer, timeout = pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])
if producer == 'build':
    output.mkdir()
    try:
        scope['run']([child], output, output, 'implement', timeout)
    except RuntimeError:
        raise SystemExit(1)
else:
    scope['main'].__globals__['prepare'] = lambda *args, **kwargs: output.mkdir()
    sys.argv = ['finalize', '--run', str(output.parent / 'original'), '--output', str(output),
                '--vivado', child, '--timeout', str(timeout)]
    scope['main']()
'''
    process = subprocess.Popen([sys.executable, '-c', wrapper, str(script), str(output),
                                str(child), producer, '1' if outcome == 'timed_out' else '30'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if outcome == 'interrupted':
            deadline = time.monotonic() + 10
            while not (tmp_path / 'ready').exists() and process.poll() is None:
                assert time.monotonic() < deadline, 'Child did not install its signal handler'
                time.sleep(0.01)
            process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=20)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
    assert process.returncode == (0 if outcome == 'success' else 1), stdout + stderr
    name = 'implement' if producer == 'build' else 'finalize'
    receipt = json.loads((output / (name + '-exit.json')).read_text())
    assert receipt['exit_code'] == (7 if outcome == 'failed' else 0)
    assert receipt['interrupted'] == (signal.SIGTERM if outcome == 'interrupted' else 0)
    assert receipt['timed_out'] is (outcome == 'timed_out')
    assert receipt['timeout_seconds'] == (1 if outcome == 'timed_out' else 30)
    assert receipt['elapsed_seconds'] >= 0
    assert (receipt['elapsed_seconds'] >= receipt['timeout_seconds']) is receipt['timed_out']
    consumer = runpy.run_path(str(board_tools().parents[3] / 'ci/ypcb_run_fpga.py'))['producer_receipt']
    inputs = {'routed_finalization': {}} if producer == 'finalize' else {}
    if outcome == 'success':
        assert consumer(output, inputs)['receipt'] == receipt
    else:
        with pytest.raises(ValueError, match='Image producer'):
            consumer(output, inputs)
    if outcome != 'success':
        progress = json.loads((output / 'progress.json').read_text())
        assert progress['running'] is False
        assert progress['exit_code'] == receipt['exit_code']
        assert progress['interrupted'] == receipt['interrupted']
        assert progress['timed_out'] is receipt['timed_out']


@pytest.mark.parametrize('timeout', [0, -1])
def test_stage_rejects_nonpositive_timeout_before_launch(tmp_path, timeout):
    run = runpy.run_path(str(board_tools() / 'build_vivado.py'))['run']
    with pytest.raises(ValueError, match='timeout must be positive'):
        run(['/nonexistent-child'], tmp_path, tmp_path, 'implement', timeout)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('timeout', [True, None, 0, 'false', 'missing'])
def test_reuse_rejects_incomplete_timeout_proof(tmp_path, timeout):
    build = runpy.run_path(str(board_tools() / 'build_vivado.py'))
    finalize = runpy.run_path(str(board_tools() / 'finalize_vivado.py'))
    receipt = {'exit_code': 0, 'interrupted': 0, 'timed_out': timeout}
    if timeout == 'missing':
        receipt.pop('timed_out')
    (tmp_path / 'synthesize-exit.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='successful exit receipt'):
        build['reuse_synthesis'](tmp_path, tmp_path / 'output', {})
    (tmp_path / 'implement-exit.json').write_text(json.dumps(receipt))
    for recovery in (False, True):
        with pytest.raises(ValueError, match='timeout disposition'):
            finalize['implementation_source'](tmp_path, recovery)
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('timeout', [True, None, 0, 'false', 'missing'])
def test_abandoned_recovery_requires_successful_synthesis_timeout_proof(tmp_path, monkeypatch, timeout):
    source = runpy.run_path(str(board_tools() / 'finalize_vivado.py'))['implementation_source']
    monkeypatch.setitem(source.__globals__, 'active_producers', lambda _: [])
    receipt = {'exit_code': 0, 'interrupted': 0, 'timed_out': timeout}
    if timeout == 'missing':
        receipt.pop('timed_out')
    (tmp_path / 'synthesize-exit.json').write_text(json.dumps(receipt))
    (tmp_path / 'progress.json').write_text(json.dumps({'stage': 'implement'}))
    with pytest.raises(ValueError, match='successful synthesis'):
        source(tmp_path, recover_abandoned=True)
    assert not (tmp_path / 'implement-exit.json').exists()


def test_completed_implementation_receipts_require_explicit_no_timeout(tmp_path):
    source = runpy.run_path(str(board_tools() / 'finalize_vivado.py'))['implementation_source']
    for code in (0, 1):
        receipt = {'exit_code': code, 'interrupted': 0, 'timed_out': False}
        (tmp_path / 'implement-exit.json').write_text(json.dumps(receipt))
        assert source(tmp_path, recover_abandoned=False)['original_implementation_exit_sha256']
