import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def fixture(tmp_path, finder='normal', empty=False):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    work = tmp_path / 'tests/ypcb/shell'
    work.mkdir(parents=True)
    rtl = tmp_path / 'rtl'
    rtl.mkdir()
    source = rtl / 'VX_dependency.sv'
    if not empty:
        source.write_text('module VX_dependency; endmodule\n')
    tmp_path.joinpath('config.mk').write_text(
        f'VORTEX_HOME ?= {root}\nSW_COMMON_DIR ?= {root / "sw/common"}\nXLEN ?= 32\nCONFIGS :=\n')
    tmp_path.joinpath('hw').mkdir()
    tmp_path.joinpath('hw/VX_config.vh').write_text('')
    tmp_path.joinpath('ci').mkdir()
    tmp_path.joinpath('ci/gen_config.py').write_text('')
    src = tmp_path / 'source'
    src.mkdir()
    src.joinpath('Makefile').write_text('')
    fake = tmp_path / 'verilator.py'
    fake.write_text('import pathlib,sys\n'
                    'pathlib.Path(sys.argv[sys.argv.index("-o")+1]).write_text("model")\n'
                    'with pathlib.Path("invocations").open("a") as output: output.write("built\\n")\n')
    commands = tmp_path / 'commands'
    commands.mkdir()
    for name in ('find', 'cmp', 'mv', 'rm'):
        commands.joinpath(name).symlink_to(shutil.which(name))
    commands.joinpath('python3').symlink_to(sys.executable)
    if finder == 'failure':
        commands.joinpath('find').unlink()
        commands.joinpath('find').write_text(f'#!/bin/sh\nprintf "%s\\n" "{source}"\nexit 1\n')
        commands.joinpath('find').chmod(0o755)
    environment = dict(os.environ, PATH=str(commands))
    command = [shutil.which('make'), '-f', str(root / 'tests/ypcb/shell/Makefile'), 'all',
               f'RTL_DIR={rtl}', f'SRC_DIR={src}', 'SRCS=', 'HEADERS=', 'RTL_PKGS=',
               'RTL_FLAGS=', 'CXXFLAGS=', 'BOARD_CONFIGS=', 'BOARD_XCONFIGS=',
               f'VERILATOR={sys.executable} {fake}']
    assert shutil.which('rg', path=environment['PATH']) is None
    return command, work, source, environment


def run(command, work, environment):
    return subprocess.run(command, cwd=work, env=environment, text=True, capture_output=True)


def test_rtl_change_rebuilds_model_without_ripgrep(tmp_path):
    command, work, source, environment = fixture(tmp_path)
    result = run(command, work, environment)
    assert result.returncode == 0, result.stderr
    assert work.joinpath('invocations').read_text().splitlines() == ['built']
    result = run(command, work, environment)
    assert result.returncode == 0, result.stderr
    assert work.joinpath('invocations').read_text().splitlines() == ['built']
    time.sleep(0.02)
    source.write_text('module VX_dependency; wire changed; endmodule\n')
    result = run(command, work, environment)
    assert result.returncode == 0, result.stderr
    assert work.joinpath('invocations').read_text().splitlines() == ['built', 'built']


def test_failed_rtl_discovery_stops_before_building(tmp_path):
    command, work, _, environment = fixture(tmp_path, finder='failure')
    result = run(command, work, environment)
    assert result.returncode != 0
    assert not work.joinpath('invocations').exists()


def test_empty_rtl_discovery_stops_before_building(tmp_path):
    command, work, _, environment = fixture(tmp_path, empty=True)
    result = run(command, work, environment)
    assert result.returncode != 0
    assert not work.joinpath('invocations').exists()
