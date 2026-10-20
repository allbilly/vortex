#!/usr/bin/env python3
from common import Vortex, parser, positive, values, verify


def main():
    cli = parser("Float32 row-major matrix multiplication: C[M,N] = A[M,K] @ B[K,N]")
    cli.add_argument("-m", type=positive, default=5)
    cli.add_argument("-n", type=positive, default=7)
    cli.add_argument("-k", type=positive, default=3)
    options = cli.parse_args()
    m, n, k = options.m, options.n, options.k
    a, b = values(m * k), values(k * n, 9)
    expected = [sum(a[row * k + j] * b[j * n + col] for j in range(k))
                for row in range(m) for col in range(n)]
    with Vortex(options) as gpu:
        actual = gpu.run("gemm", a, b, m * n, dims=(m, n, k))
    verify(f"gemm {m}x{k} @ {k}x{n}", actual, expected, options.driver)


if __name__ == "__main__":
    main()
