// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <float.h>
#include <vx_spawn2.h>
#include "../common.h"

__kernel void kernel_main(kernel_args* __UNIFORM__ args) {
  const uint32_t i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= args->count) {
    return;
  }
  const auto input = reinterpret_cast<const float*>(args->a);
  auto output = reinterpret_cast<float*>(args->c);
  const uint32_t h = args->dims[1], w = args->dims[2];
  const uint32_t kh = args->dims[3], kw = args->dims[4];
  const uint32_t stride = args->dims[5], pad = args->dims[6];
  const uint32_t oh = (h + 2 * pad - kh) / stride + 1;
  const uint32_t ow = (w + 2 * pad - kw) / stride + 1;
  const uint32_t channel = i / (oh * ow), y = (i / ow) % oh, x = i % ow;
  float value = args->op == 0 ? -FLT_MAX : (args->op == 2 ? FLT_MAX : 0);
  uint32_t samples = 0;
  for (uint32_t ky = 0; ky < kh; ++ky) {
    const int iy = int(y * stride + ky) - int(pad);
    for (uint32_t kx = 0; kx < kw; ++kx) {
      const int ix = int(x * stride + kx) - int(pad);
      if (iy >= 0 && iy < int(h) && ix >= 0 && ix < int(w)) {
        const float sample = input[(channel * h + iy) * w + ix];
        if (args->op == 0) {
          value = sample > value ? sample : value;
        } else if (args->op == 2) {
          value = sample < value ? sample : value;
        } else {
          value += sample;
        }
        ++samples;
      }
    }
  }
  output[i] = args->op == 1 ? value / samples : value;
}
