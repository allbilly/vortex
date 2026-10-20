// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <vx_spawn2.h>
#include "../common.h"

__kernel void kernel_main(kernel_args* __UNIFORM__ args) {
  const uint32_t i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= args->count) {
    return;
  }
  const auto a = reinterpret_cast<const float*>(args->a);
  const auto b = reinterpret_cast<const float*>(args->b);
  auto c = reinterpret_cast<float*>(args->c);
  const uint32_t n = args->dims[1], k = args->dims[2];
  const uint32_t row = i / n, col = i % n;
  float sum = 0;
  for (uint32_t j = 0; j < k; ++j) {
    sum += a[row * k + j] * b[j * n + col];
  }
  c[i] = sum;
}
