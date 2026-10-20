#!/usr/bin/env python3
from common import Vortex, parser, positive, values, verify

OPS = {"add": (0, lambda x, y: x + y), "sub": (1, lambda x, y: x - y),
       "mul": (2, lambda x, y: x * y), "div": (3, lambda x, y: x / y),
       "min": (4, min), "max": (5, max), "relu": (6, lambda x, y: max(x, 0))}


def main():
    cli = parser("Float32 elementwise arithmetic and ReLU")
    cli.add_argument("-n", type=positive, default=37)
    cli.add_argument("--op", choices=["all", *OPS], default="all")
    options = cli.parse_args()
    a = values(options.n)
    b = [(-1 if i % 2 else 1) * (i % 13 + 1) / 8 for i in range(options.n)]
    with Vortex(options) as gpu:
        for name in OPS if options.op == "all" else [options.op]:
            code, reference = OPS[name]
            expected = [reference(x, y) for x, y in zip(a, b)]
            actual = gpu.run("elementwise", a, b, options.n, op=code)
            verify(name, actual, expected, options.driver)


if __name__ == "__main__":
    main()
