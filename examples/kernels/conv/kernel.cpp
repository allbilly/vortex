// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <vx_spawn2.h>
#include "../common.h"

__kernel void kernel_main(kernel_args* __UNIFORM__ args) {
  const uint32_t i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= args->count) {
    return;
  }
  const auto input = reinterpret_cast<const float*>(args->a);
  const auto weights = reinterpret_cast<const float*>(args->b);
  auto output = reinterpret_cast<float*>(args->c);
  const uint32_t channels = args->dims[0], h = args->dims[1], w = args->dims[2];
  const uint32_t kh = args->dims[4], kw = args->dims[5];
  const uint32_t stride = args->dims[6], pad = args->dims[7];
  const uint32_t oh = (h + 2 * pad - kh) / stride + 1;
  const uint32_t ow = (w + 2 * pad - kw) / stride + 1;
  const uint32_t oc = i / (oh * ow), y = (i / ow) % oh, x = i % ow;
  float sum = 0;
  for (uint32_t ic = 0; ic < channels; ++ic) {
    for (uint32_t ky = 0; ky < kh; ++ky) {
      const int iy = int(y * stride + ky) - int(pad);
      for (uint32_t kx = 0; kx < kw; ++kx) {
        const int ix = int(x * stride + kx) - int(pad);
        if (iy >= 0 && iy < int(h) && ix >= 0 && ix < int(w)) {
          sum += input[(ic * h + iy) * w + ix]
               * weights[((oc * channels + ic) * kh + ky) * kw + kx];
        }
      }
    }
  }
  output[i] = sum;
}
