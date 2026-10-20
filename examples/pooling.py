#!/usr/bin/env python3
from common import Vortex, nonnegative, parser, positive, spatial_shape, values, verify

OPS = {"max": (0, max), "avg": (1, lambda xs: sum(xs) / len(xs)), "min": (2, min)}


def main():
    cli = parser("Float32 CHW pooling; padding is excluded from each reduction")
    cli.add_argument("--channels", type=positive, default=2)
    cli.add_argument("--height", type=positive, default=5)
    cli.add_argument("--width", type=positive, default=7)
    cli.add_argument("--kernel", type=positive, default=2)
    cli.add_argument("--stride", type=positive, default=2)
    cli.add_argument("--padding", type=nonnegative, default=0)
    cli.add_argument("--op", choices=["all", *OPS], default="all")
    options = cli.parse_args()
    c, h, w, k, stride, pad = (options.channels, options.height, options.width,
                              options.kernel, options.stride, options.padding)
    oh, ow = spatial_shape(cli, h, w, k, stride, pad)
    a = values(c * h * w)
    windows = []
    for channel in range(c):
        for y in range(oh):
            for x in range(ow):
                window = []
                for ky in range(k):
                    for kx in range(k):
                        iy, ix = y * stride + ky - pad, x * stride + kx - pad
                        if 0 <= iy < h and 0 <= ix < w:
                            window.append(a[(channel * h + iy) * w + ix])
                windows.append(window)
    with Vortex(options) as gpu:
        for name in OPS if options.op == "all" else [options.op]:
            code, reference = OPS[name]
            actual = gpu.run("pooling", a, [0.0], c * oh * ow, op=code, dims=(c, h, w, k, k, stride, pad))
            verify(f"pooling {name} output={c}x{oh}x{ow}", actual,
                   [reference(window) for window in windows], options.driver)


if __name__ == "__main__":
    main()
