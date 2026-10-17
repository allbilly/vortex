// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <callbacks.h>
#include <cstdlib>
#include <dlfcn.h>

static callbacks_t simx;
static unsigned operations;

extern "C" unsigned reservation_cp_operations() {
  return operations;
}

extern "C" int vx_dev_init(callbacks_t* callbacks) {
  void* library = dlopen("libvortex-simx.so", RTLD_NOW | RTLD_LOCAL);
  if (library == nullptr || callbacks == nullptr) {
    return -1;
  }
  auto init = reinterpret_cast<int (*)(callbacks_t*)>(dlsym(library, "vx_dev_init"));
  if (init == nullptr || init(&simx) != 0) {
    return -1;
  }
  *callbacks = simx;
  callbacks->host_mem_device_range = [](void*, uint64_t* base, uint64_t* size) {
    const char* b = std::getenv("RESERVATION_TEST_BASE");
    const char* s = std::getenv("RESERVATION_TEST_SIZE");
    *base = b ? std::strtoull(b, nullptr, 0) : 0;
    *size = s ? std::strtoull(s, nullptr, 0) : 0;
    return std::getenv("RESERVATION_TEST_QUERY_ERROR") ? -1 : 0;
  };
  callbacks->cp_reg_read = [](void* context, uint32_t offset, uint32_t* value) {
    ++operations;
    return simx.cp_reg_read(context, offset, value);
  };
  callbacks->cp_reg_write = [](void* context, uint32_t offset, uint32_t value) {
    ++operations;
    return simx.cp_reg_write(context, offset, value);
  };
  return 0;
}
