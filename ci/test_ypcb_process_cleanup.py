import ast
import copy
import fcntl
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import uuid

import pytest


def runner_path():
    config = (Path.cwd() / 'config.mk').read_text()
    root = Path(config.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    return root / 'ci/ypcb_run_fpga.py'


@pytest.mark.parametrize('ignore_term,sanitize', [(False, False), (True, False), (False, True)])
def test_double_fork_daemon_cleanup_preserves_foreign_process(tmp_path, ignore_term, sanitize):
    daemon = tmp_path / 'daemon.py'
    daemon.write_text('''import os, signal, sys, time
from pathlib import Path
if sys.argv[2] != 'sanitized':
    if os.fork():
        sys.exit(0)
    os.setsid()
    if os.fork():
        os._exit(0)
    os.setsid()
    if sys.argv[2] == 'sanitize':
        os.execve(sys.executable, [sys.executable, __file__, sys.argv[1], 'sanitized'], {})
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
Path(sys.argv[1]).write_text(str(os.getpid()))
while True:
    time.sleep(.01)
''')
    if ignore_term:
        daemon.write_text(daemon.read_text().replace('lambda *_: sys.exit(0)', 'signal.SIG_IGN'))
    harness = '''import json, os, runpy, signal, subprocess, sys, time, uuid
from pathlib import Path
scope = runpy.run_path(sys.argv[1])
unrelated = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(7)'])
deadline = time.monotonic() + 10
while Path('/proc', str(unrelated.pid), 'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z':
    assert time.monotonic() < deadline
    time.sleep(.01)
scope['enable_subreaper']()
base = Path(sys.argv[2])
tokens = [uuid.uuid4().hex, uuid.uuid4().hex]
roots = []
identities = []
try:
    for name, token in zip(('owned', 'foreign'), tokens):
        ready = base / (name + '.pid')
        child = subprocess.Popen([sys.executable, str(base / 'daemon.py'), str(ready),
            'sanitize' if name == 'owned' and sys.argv[4] == '1' else 'inherit'],
            env=dict(os.environ, VORTEX_YPCB_RUN_TOKEN=token), start_new_session=True)
        roots.append(child)
        assert child.wait(timeout=10) == 0
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(.01)
        identities.append(scope['process_identity'](int(ready.read_text())))
    foreign = identities[1]
    wrong = dict(foreign, start_ticks=foreign['start_ticks'] + 1)
    assert scope['signal_owned_process'](wrong, signal.SIGTERM, tokens[1]) is False
    assert scope['signal_owned_process'](foreign, signal.SIGTERM, tokens[0]) is False
    assert scope['process_identity'](foreign['pid']) == foreign
    report = scope['cleanup_owned_processes'](tokens[0], [roots[0]], term_timeout=1, kill_timeout=2)
    assert report['status'] == 'PASS' and report['remaining'] == []
    assert report['direct_children_alive'] == []
    assert scope['process_identity'](identities[0]['pid']) is None
    assert scope['process_identity'](foreign['pid']) == foreign
    assert foreign['pid'] not in [item['pid'] for item in report['owned_processes']]
    assert any(item['pid'] == identities[0]['pid'] and item['exit_code'] == int(sys.argv[3])
               for item in report['reaped_descendants'])
    (base / 'cleanup-report.json').write_text(json.dumps(report))
finally:
    for token, child in zip(tokens, roots):
        scope['cleanup_owned_processes'](token, [child], term_timeout=1, kill_timeout=2)
assert unrelated.wait(timeout=5) == 7, 'An unrelated zombie was reaped by ownership cleanup'
try:
    pending = os.waitpid(-1, os.WNOHANG)
except ChildProcessError:
    pending = None
assert pending is None, ('An adopted child or zombie remains', pending)
'''
    result = subprocess.run([sys.executable, '-c', harness, str(runner_path()), str(tmp_path),
                             '-9' if ignore_term else '0', str(int(sanitize))],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'cleanup-report.json').read_text())
    assert report['status'] == 'PASS'
    assert report['remaining'] == []


def test_direct_child_with_sanitized_exec_environment_is_stopped(tmp_path):
    scope = runpy.run_path(str(runner_path()))
    token = uuid.uuid4().hex
    ready = tmp_path / 'ready'
    child_code = ('import signal,sys,time\nfrom pathlib import Path\n'
                  'signal.signal(signal.SIGTERM, lambda *_:sys.exit(0))\n'
                  f'Path({str(ready)!r}).write_text("ready")\n'
                  'while True:time.sleep(.01)\n')
    launcher = f'import os,sys; os.execve(sys.executable, [sys.executable,"-c",{child_code!r}], {{}})'
    child = subprocess.Popen([sys.executable, '-c', launcher],
                             env=dict(os.environ, VORTEX_YPCB_RUN_TOKEN=token), start_new_session=True)
    child.ypcb_identity = scope['process_identity'](child.pid)
    try:
        import time
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert scope['has_ownership_marker'](child.pid, token) is False
        report = scope['cleanup_owned_processes'](token, [child], term_timeout=1, kill_timeout=2)
        assert report['status'] == 'PASS' and report['remaining'] == []
        assert report['direct_children_alive'] == [] and child.returncode == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


def test_launch_overrides_inherited_and_supplied_ownership_markers(tmp_path, monkeypatch):
    tree = ast.parse(runner_path().read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    launch = copy.deepcopy(next(node for node in main.body
                                if isinstance(node, ast.FunctionDef) and node.name == 'launch'))
    token = uuid.uuid4().hex
    context = {'os': os, 'subprocess': subprocess, 'run_token': token, 'output': tmp_path,
               'ownership_variable': 'VORTEX_YPCB_RUN_TOKEN', 'children': [], 'state': {}, 'save': lambda: None,
               'process_identity': runpy.run_path(str(runner_path()))['process_identity']}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[launch], type_ignores=[])), str(runner_path()), 'exec'), context)
    monkeypatch.setenv('VORTEX_YPCB_RUN_TOKEN', 'foreign-inherited-marker')
    supplied = dict(os.environ, VORTEX_YPCB_RUN_TOKEN='foreign-supplied-marker')
    for name, environment in (('inherited', None), ('supplied', supplied)):
        child = context['launch'](name, [sys.executable, '-c',
            'import os; print(os.environ["VORTEX_YPCB_RUN_TOKEN"])'], tmp_path, environment)
        assert child.wait(timeout=10) == 0
        assert (tmp_path / (name + '.log')).read_text().strip() == token
    assert supplied['VORTEX_YPCB_RUN_TOKEN'] == 'foreign-supplied-marker'


@pytest.mark.parametrize('failure', ['raises', 'remaining'])
def test_cleanup_failure_releases_lease_and_records_failure(tmp_path, monkeypatch, failure):
    finish = runpy.run_path(str(runner_path()))['finish_owned_run']

    def fail(*args):
        if failure == 'raises':
            raise OSError('fixture cleanup error')
        return {'status': 'FAIL', 'remaining': [{'pid': 123, 'start_ticks': 456}]}

    monkeypatch.setitem(finish.__globals__, 'cleanup_owned_processes', fail)
    path = tmp_path / 'hardware.lock'
    lease = path.open('a+')
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state, saved = {'status': 'KERNEL_SUITE_PASS'}, []
    with pytest.raises(RuntimeError, match='owner cleanup failed'):
        finish(uuid.uuid4().hex, [], lease, state, lambda: saved.append(dict(state)))
    assert lease.closed
    assert state['status'] == 'FAIL' and state['owned_children_exit_codes'] == []
    assert saved and saved[-1] == state
    with path.open('a+') as replacement:
        fcntl.flock(replacement, fcntl.LOCK_EX | fcntl.LOCK_NB)
