// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once
#include <stdint.h>

struct kernel_args {
  uint64_t a;
  uint64_t b;
  uint64_t c;
  uint32_t count;
  uint32_t op;
  uint32_t dims[8];
};

static_assert(sizeof(kernel_args) == 64, "Python/kernel argument layout differs");
