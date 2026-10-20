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
  const float x = a[i], y = b[i];
  switch (args->op) {
  case 0: c[i] = x + y; break;
  case 1: c[i] = x - y; break;
  case 2: c[i] = x * y; break;
  case 3: c[i] = x / y; break;
  case 4: c[i] = x < y ? x : y; break;
  case 5: c[i] = x > y ? x : y; break;
  case 6: c[i] = x > 0 ? x : 0; break;
  }
}
