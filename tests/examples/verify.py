import ctypes as ct
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))
import common


def main():
    options = common.parser("Check Python/C ABI and known Vortex operation results").parse_args()
    binary = options.build.resolve() / "tests/examples/abi-check"
    layouts = subprocess.check_output([str(binary)], text=True)
    for line in layouts.splitlines():
        name, *sizes = line.split()
        structure = getattr(common, name)
        expected = [ct.sizeof(structure), *[getattr(structure, n).offset for n, *_ in structure._fields_]]
        if list(map(int, sizes)) != expected:
            raise RuntimeError(f"Python/C ABI mismatch for {name}")
    print("PASS: Python argument and runtime structure sizes/offsets match actual C++ headers")

    with common.Vortex(options) as gpu:
        def check(name, a, b, expected, *, op=0, dims=()):
            result = gpu.run(name, a, b, len(expected), op=op, dims=dims)
            common.verify(name, result, expected, options.driver)

        check("simple_add", [1, -2, 0], [4, 5, -3], [5, 3, -3])
        check("elementwise", [-3, 0, 5], [1, 1, 1], [0, 0, 5], op=6)
        check("gemm", [1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12],
              [58, 64, 139, 154], dims=(2, 2, 3))
        check("conv", list(range(1, 10)), [1, 0, 0, -1], [-4] * 4,
              dims=(1, 3, 3, 1, 2, 2, 1, 0))
        check("conv", [1, 2, 3, 4, 10, 20, 30, 40], [1, 2, 3, 4],
              [21, 42, 63, 84, 43, 86, 129, 172], dims=(2, 2, 2, 2, 1, 1, 1, 0))
        image = list(range(1, 10))
        for op, expected in [(0, [5, 6, 8, 9]), (1, [3, 4, 6, 7]), (2, [1, 2, 4, 5])]:
            check("pooling", image, [0], expected, op=op, dims=(1, 3, 3, 2, 2, 1, 0))
        check("pooling", image, [0], [3, 4, 6, 7], op=1, dims=(1, 3, 3, 3, 3, 2, 1))
        check("pooling", list(range(-9, 0)), [0], [-5, -4, -2, -1],
              dims=(1, 3, 3, 3, 3, 2, 1))
    try:
        common.verify("unwritten-output", [float("nan")], [0.0], options.driver)
    except RuntimeError:
        print("PASS: unwritten output sentinel is rejected")
    else:
        raise RuntimeError("Unwritten output was accepted")


if __name__ == "__main__":
    main()
