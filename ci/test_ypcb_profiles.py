import json
from pathlib import Path
import runpy
import shutil
import subprocess

import pytest


def test_configure_refreshes_inherited_profile_without_rebuilding_unchanged_headers(tmp_path, monkeypatch):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    source, build = tmp_path / 'source', tmp_path / 'build'
    source.mkdir()
    build.mkdir()
    for name in ('configure', 'VERSION', 'config.mk.in', 'VX_config.toml', 'VX_types.toml'):
        shutil.copy2(root / name, source / name)
    (source / 'ci').mkdir()
    shutil.copy2(root / 'ci/gen_config.py', source / 'ci/gen_config.py')
    (source / 'profiles').mkdir()
    parent = {'name': 'base', 'core': {'VX_CFG_TCU_INT8_ENABLE': False}, 'sources': 'fixture'}
    (source / 'profiles/base.json').write_text(json.dumps(parent))
    (source / 'profiles/child.json').write_text(json.dumps({'extends': 'base', 'sources': 'fixture'}))
    command = [str(source / 'configure'), '--profile=child', '--xlen=32', '--memory-size=2147483648',
               '--osversion=ubuntu/focal']
    subprocess.run(command, cwd=build, check=True, capture_output=True, text=True)
    headers = [build / 'sw/VX_config.h', build / 'hw/VX_config.vh']
    first = [path.stat().st_mtime_ns for path in headers]
    subprocess.run(command, cwd=build, check=True, capture_output=True, text=True)
    assert [path.stat().st_mtime_ns for path in headers] == first
    parent['core']['VX_CFG_TCU_INT8_ENABLE'] = True
    (source / 'profiles/base.json').write_text(json.dumps(parent))
    subprocess.run(command, cwd=build, check=True, capture_output=True, text=True)
    assert '\n#define VX_CFG_TCU_INT8_ENABLE\n' in headers[0].read_text()
    assert '\n`define VX_CFG_TCU_INT8_ENABLE\n' in headers[1].read_text()
    changed = [path.stat().st_mtime_ns for path in headers]
    assert changed != first
    subprocess.run(command, cwd=build, check=True, capture_output=True, text=True)
    assert [path.stat().st_mtime_ns for path in headers] == changed
    hooks = runpy.run_path(str(root / 'ci/conftest.py'))
    monkeypatch.chdir(build)
    hooks['_assert_config_current']()
    parent['core']['VX_CFG_TCU_INT8_ENABLE'] = False
    (source / 'profiles/base.json').write_text(json.dumps(parent))
    with pytest.raises(pytest.UsageError, match='build tree is stale'):
        hooks['_assert_config_current']()
    subprocess.run(command, cwd=build, check=True, capture_output=True, text=True)
    hooks['_assert_config_current']()
    retained = [path.read_bytes() for path in headers]
    (source / 'profiles/base.json').write_text('{')
    failed = subprocess.run(command, cwd=build, capture_output=True, text=True)
    assert failed.returncode != 0
    assert [path.read_bytes() for path in headers] == retained
