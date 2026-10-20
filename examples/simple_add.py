#!/usr/bin/env python3
from common import Vortex, parser, positive, values, verify


def main():
    cli = parser("Float32 vector addition: C[i] = A[i] + B[i]")
    cli.add_argument("-n", type=positive, default=37)
    options = cli.parse_args()
    a, b = values(options.n), values(options.n, 5)
    expected = [x + y for x, y in zip(a, b)]
    with Vortex(options) as gpu:
        actual = gpu.run("simple_add", a, b, options.n)
    verify("simple_add", actual, expected, options.driver)


if __name__ == "__main__":
    main()
