import os
from pathlib import Path
import subprocess
import sys


def test_dispatcher_rebuilds_for_flags_and_headers(tmp_path):
    build = Path.cwd()
    assert (build / "config.mk").is_file(), "Run from a configured build directory"
    (tmp_path / "alias").mkdir()
    destination = tmp_path / "output"
    equivalent = tmp_path / "alias/../output"
    source = tmp_path / "probe.cpp"
    header = tmp_path / "probe.h"
    header.write_text("#define CLOCK_BIAS 0\n")
    source.write_text('#include <VX_config.h>\n#include "probe.h"\n'
                      'extern "C" unsigned clock_probe() {\n'
                      '  return VX_CFG_PLATFORM_CLOCK_RATE + CLOCK_BIAS;\n}\n')
    library = destination / "libvortex.so"
    stamp = destination / "stub_config.stamp"
    env = dict(os.environ, CCACHE_DISABLE="1")

    def compile_probe(output, clock):
        command = ["make", "-C", str(build / "sw/runtime/stub")]
        if os.environ.get("RUNTIME_STAMP_MAKEFILE"):
            command += ["-f", os.environ["RUNTIME_STAMP_MAKEFILE"]]
        command += [f"DESTDIR={output}", f"SRCS={source}", f"RT_HDRS={header}",
                    f"CONFIGS=-DVX_CFG_PLATFORM_CLOCK_RATE={clock}", "all"]
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        probe = subprocess.run(
            [sys.executable, "-c", "import ctypes, sys; "
             "library = ctypes.CDLL(sys.argv[1]); print(library.clock_probe())", str(library)],
            text=True, capture_output=True, timeout=30)
        assert probe.returncode == 0, probe.stdout + probe.stderr
        return int(probe.stdout)

    assert compile_probe(destination, 125) == 125
    before = library.stat().st_mtime_ns
    assert compile_probe(equivalent, 125) == 125
    assert library.stat().st_mtime_ns == before

    assert compile_probe(equivalent, 200) == 200
    assert library.stat().st_mtime_ns != before
    assert "-Wl,-rpath,'$ORIGIN'" in stamp.read_text()
    stamp_before = (stamp.read_text(), stamp.stat().st_mtime_ns)
    before = library.stat().st_mtime_ns
    header.write_text("#define CLOCK_BIAS 1\n")
    assert compile_probe(destination, 200) == 201
    assert library.stat().st_mtime_ns != before
    assert (stamp.read_text(), stamp.stat().st_mtime_ns) == stamp_before

    assert compile_probe(equivalent, 125) == 126
