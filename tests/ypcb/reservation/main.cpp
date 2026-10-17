// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <vortex.h>
#include <vortex2.h>
#include "ypcb_host_memory.h"
#include <array>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>

static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

static void range(uint64_t base, uint64_t size) {
  std::array<char, 32> b{}, s{};
  std::snprintf(b.data(), b.size(), "%llu", static_cast<unsigned long long>(base));
  std::snprintf(s.data(), s.size(), "%llu", static_cast<unsigned long long>(size));
  require(setenv("RESERVATION_TEST_BASE", b.data(), 1) == 0
      && setenv("RESERVATION_TEST_SIZE", s.data(), 1) == 0, "Set range failed");
}

int main() {
  constexpr auto arena_base = vortex::ypcb::HostMemory::arena_base;
  constexpr auto arena_size = vortex::ypcb::HostMemory::arena_size;
  vx_device_h device = nullptr;
  range(arena_base, arena_size);
  require(vx_device_open(0, &device) == VX_SUCCESS, "Open with DDR arena failed");
  void* library = dlopen("libvortex-reservation-test.so", RTLD_NOW | RTLD_NOLOAD);
  require(library != nullptr, "Delegating test backend not loaded");
  auto count = reinterpret_cast<unsigned (*)()>(dlsym(library, "reservation_cp_operations"));
  require(count != nullptr && count() > 0, "Real SimX command processor was not exercised");
  uint64_t free_bytes = 0, used_bytes = 0;
  require(vx_mem_info(device, &free_bytes, &used_bytes) == 0
      && used_bytes == arena_size && free_bytes == 0xffff0000 - arena_size,
      "DDR arena not counted as reserved");
  vx_buffer_h overlap = nullptr;
  require(vx_buffer_reserve(device, arena_base, 4096, VX_MEM_READ_WRITE, &overlap)
      == VX_ERR_INVALID_VALUE && overlap == nullptr, "User reserved command-memory arena");
  vx_buffer_h low = nullptr, high = nullptr;
  require(vx_buffer_reserve(device, 0x10000, arena_base - 0x10000, VX_MEM_READ_WRITE, &low)
      == VX_SUCCESS, "Reserve lower free span failed");
  require(vx_buffer_create(device, 4096, VX_MEM_READ_WRITE, &high) == VX_SUCCESS,
      "Allocate above arena failed");
  uint64_t address = 0;
  require(vx_buffer_address(high, &address) == VX_SUCCESS && address == arena_base + arena_size,
      "Allocator crossed the transport reservation");
  require(vx_buffer_release(low) == VX_SUCCESS && vx_buffer_release(high) == VX_SUCCESS,
      "Release user allocations failed");
  require(vx_mem_info(device, &free_bytes, &used_bytes) == 0 && used_bytes == arena_size,
      "User release removed the transport reservation");
  vx_buffer_h crossing = nullptr;
  require(vx_buffer_reserve(device, 0x7ffff000, 8192, VX_MEM_READ_WRITE, &crossing)
      == VX_SUCCESS, "Reserve across DDR bank boundary failed");
  require(vx_buffer_release(crossing) == VX_SUCCESS, "Release crossing buffer failed");
  require(vx_device_release(device) == VX_SUCCESS, "Close reserved device failed");

  const std::array<std::array<uint64_t, 2>, 8> invalid = {{{1, 0}, {0, 4096},
      {0xf000, 4096}, {arena_base + 1, 4096}, {arena_base, 4095},
      {0x100000000ull, 4096}, {0xfffff000, 8192}, {arena_base, ~uint64_t(0)}}};
  for (const auto& entry : invalid) {
    range(entry[0], entry[1]);
    const unsigned before = count();
    device = nullptr;
    require(vx_device_open(0, &device) == VX_ERR_INVALID_VALUE && device == nullptr,
        "Invalid transport reservation accepted");
    require(count() == before, "Invalid reservation touched command processor");
  }
  range(0, 0);
  require(setenv("RESERVATION_TEST_QUERY_ERROR", "1", 1) == 0, "Set query error failed");
  const unsigned before = count();
  require(vx_device_open(0, &device) == VX_ERR_INVALID_VALUE && device == nullptr
      && count() == before, "Failed range query reached CP setup");
  unsetenv("RESERVATION_TEST_QUERY_ERROR");
  require(vx_device_open(0, &device) == VX_SUCCESS, "Separate host address space rejected");
  require(vx_mem_info(device, &free_bytes, &used_bytes) == 0 && used_bytes == 0
      && free_bytes == 0xffff0000, "No-reservation backend lost device capacity");
  require(vx_device_release(device) == VX_SUCCESS, "Close unreserved device failed");
  dlclose(library);
  std::puts("PASSED: mandatory transport reservation, real allocator and SimX CP, arena exclusion, 9 invalid/query cases rejected before CP access");
}
