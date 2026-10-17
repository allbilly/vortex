import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("driver,stamp_name", [
    ("simx", "simx_config.stamp"),
    ("xrtsim", "xrtsim_config.stamp"),
])
def test_simulator_stamp_uses_canonical_destination(tmp_path, driver, stamp_name):
    build = Path.cwd()
    assert (build / "config.mk").is_file(), "Run from a configured build directory"
    (tmp_path / "alias").mkdir()
    destination = tmp_path / "objects"
    equivalent = tmp_path / "alias/../objects"
    stamp = destination / stamp_name
    before = None
    for index, (output, configs) in enumerate((
            (destination, ""), (equivalent, ""),
            (equivalent, "-DVX_CFG_NUM_THREADS=8"),
            (destination, "-DVX_CFG_NUM_THREADS=8"))):
        result = subprocess.run(
            ["make", "-C", str(build / "sim" / driver), f"DESTDIR={output}",
             f"CONFIGS={configs}", str(stamp)], text=True,
            capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        current = (stamp.read_text(), stamp.stat().st_mtime_ns)
        if before is not None:
            if index == 2:
                assert current[0] != before[0]
                assert current[1] != before[1]
            else:
                assert current == before
        before = current


def test_simx_stamp_reuses_objects_across_equivalent_paths(tmp_path):
    build = Path.cwd()
    assert (build / "config.mk").is_file(), "Run from a configured build directory"
    (tmp_path / "alias").mkdir()
    destination = tmp_path / "objects"
    equivalent = tmp_path / "alias/../objects"
    env = dict(os.environ, CCACHE_DISABLE="1")
    common = tmp_path / "common"
    common.mkdir()
    source = Path((build / "config.mk").read_text().split("VORTEX_HOME ?= ", 1)[1].splitlines()[0])
    for name in ("util.cpp", "util.h", "bitmanip.h"):
        shutil.copy2(source / "sw/common" / name, common / name)

    def compile_object(output, configs=""):
        result = subprocess.run(
            ["make", "-C", str(build / "sim/simx"), f"DESTDIR={output}",
             f"CONFIGS={configs}", f"SW_COMMON_DIR={common}",
             str(destination / "obj/common/util.o")],
            env=env, text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr

    compile_object(destination)
    obj = destination / "obj/common/util.o"
    stamp = destination / "simx_config.stamp"
    before = (obj.stat().st_mtime_ns, stamp.stat().st_mtime_ns)
    compile_object(equivalent)
    assert (obj.stat().st_mtime_ns, stamp.stat().st_mtime_ns) == before
    assert (destination / "obj/common/util.d").is_file()

    (common / "util.h").touch()
    compile_object(equivalent)
    assert obj.stat().st_mtime_ns != before[0]
    assert stamp.stat().st_mtime_ns == before[1]
    before = (obj.stat().st_mtime_ns, stamp.stat().st_mtime_ns)

    compile_object(destination, "-DVX_CFG_NUM_THREADS=8")
    assert obj.stat().st_mtime_ns != before[0]
    assert stamp.stat().st_mtime_ns != before[1]
