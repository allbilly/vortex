#!/usr/bin/env python3
from common import Vortex, nonnegative, parser, positive, spatial_shape, values, verify


def main():
    cli = parser("Float32 2D cross-correlation: CHW input, OIHW weights, CHW output; batch=1")
    cli.add_argument("--channels", type=positive, default=2)
    cli.add_argument("--height", type=positive, default=5)
    cli.add_argument("--width", type=positive, default=7)
    cli.add_argument("--out-channels", type=positive, default=3)
    cli.add_argument("--kernel", type=positive, default=3)
    cli.add_argument("--stride", type=positive, default=1)
    cli.add_argument("--padding", type=nonnegative, default=1)
    options = cli.parse_args()
    c, h, w, oc, k, stride, pad = (options.channels, options.height, options.width,
                                  options.out_channels, options.kernel, options.stride, options.padding)
    oh, ow = spatial_shape(cli, h, w, k, stride, pad)
    a, weights = values(c * h * w), values(oc * c * k * k, 3)
    expected = []
    for out_channel in range(oc):
        for y in range(oh):
            for x in range(ow):
                total = 0.0
                for channel in range(c):
                    for ky in range(k):
                        for kx in range(k):
                            iy, ix = y * stride + ky - pad, x * stride + kx - pad
                            if 0 <= iy < h and 0 <= ix < w:
                                total += a[(channel * h + iy) * w + ix] * weights[
                                    ((out_channel * c + channel) * k + ky) * k + kx]
                expected.append(total)
    with Vortex(options) as gpu:
        actual = gpu.run("conv", a, weights, oc * oh * ow, dims=(c, h, w, oc, k, k, stride, pad))
    verify(f"conv output={oc}x{oh}x{ow}", actual, expected, options.driver)


if __name__ == "__main__":
    main()
