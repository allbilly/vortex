// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <vortex.h>
#include <vortex2.h>
#include <VX_config.h>
#include <VX_types.h>
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
  uint64_t capacity = 0;
  require(vx_device_query(device, VX_CAPS_GLOBAL_MEM_SIZE, &capacity) == VX_SUCCESS,
      "Query memory capacity failed");
  uint64_t free_bytes = 0, used_bytes = 0;
  uint64_t warp_slots = 1;
  while (warp_slots < VX_CFG_NUM_WARPS) warp_slots <<= 1;
  const uint64_t stack_bytes = uint64_t(VX_CFG_NUM_CORES) * warp_slots
      * VX_CFG_NUM_THREADS * (uint64_t(1) << VX_MEM_STACK_LOG2_SIZE);
  const uint64_t stack_bottom = VX_MEM_STACK_BASE_ADDR - stack_bytes;
  uint64_t system_reserved = VX_MEM_GLOBAL_SIZE - stack_bottom;
#if VX_CFG_EXT_OM_ENABLED
  system_reserved += VX_MEM_OM_END_ADDR - VX_MEM_OM_BASE_ADDR;
#endif
  require(vx_mem_info(device, &free_bytes, &used_bytes) == 0
      && used_bytes == arena_size + system_reserved
      && free_bytes == capacity - VX_MEM_USER_BASE_ADDR - used_bytes,
      "Host arena and architectural top reservations not counted");
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
  require(vx_mem_info(device, &free_bytes, &used_bytes) == 0
      && used_bytes == arena_size + system_reserved,
      "User release changed reserved memory accounting");
  vx_buffer_h last_page = nullptr;
  require(vx_buffer_reserve(device, stack_bottom - 4096, 4096,
                            VX_MEM_READ_WRITE, &last_page) == VX_SUCCESS,
      "Last page below stack reservation was not allocatable");
  uint64_t last_page_address = 0;
  require(vx_buffer_address(last_page, &last_page_address) == VX_SUCCESS
      && last_page_address == stack_bottom - 4096,
      "Last valid page address changed");
  require(vx_buffer_release(last_page) == VX_SUCCESS, "Release last valid page failed");
  const std::array<std::array<uint64_t, 2>, 4> protected_ranges = {{
      {stack_bottom, 4096},
      {VX_MEM_LMEM_BASE_ADDR, 4096},
      {VX_MEM_GLOBAL_SIZE - 4096, 4096},
      {stack_bottom - 4096, 8192}
  }};
  for (const auto& entry : protected_ranges) {
    vx_buffer_h protected_buffer = nullptr;
    require(vx_buffer_reserve(device, entry[0], entry[1], VX_MEM_READ_WRITE,
                              &protected_buffer) == VX_ERR_INVALID_VALUE
        && protected_buffer == nullptr,
        "Stack/local-memory/top reservation was exposed to users");
  }
  vx_buffer_h crossing = nullptr;
  require(vx_buffer_reserve(device, capacity - 4096, 8192, VX_MEM_READ_WRITE, &crossing)
      == VX_ERR_INVALID_VALUE && crossing == nullptr, "Reservation crossed physical memory end");
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
  require(vx_mem_info(device, &free_bytes, &used_bytes) == 0
      && used_bytes == system_reserved
      && free_bytes == capacity - VX_MEM_USER_BASE_ADDR - system_reserved,
      "No-host-arena backend lost architectural reservations or capacity");
  vx_buffer_h no_arena_last_page = nullptr;
  require(vx_buffer_reserve(device, stack_bottom - 4096, 4096,
                            VX_MEM_READ_WRITE, &no_arena_last_page) == VX_SUCCESS,
      "No-host-arena allocator missed last valid page");
  require(vx_buffer_release(no_arena_last_page) == VX_SUCCESS,
      "No-host-arena last page release failed");
  vx_buffer_h no_arena_stack = nullptr;
  require(vx_buffer_reserve(device, stack_bottom, 4096, VX_MEM_READ_WRITE,
                            &no_arena_stack) == VX_ERR_INVALID_VALUE
      && no_arena_stack == nullptr,
      "No-host-arena allocator exposed stack reservation");
  require(vx_device_release(device) == VX_SUCCESS, "Close unreserved device failed");
  dlclose(library);
  std::puts("PASSED: host arena and stack/LMEM/top reservations, last valid page, both host-range modes, and invalid/query rejection before CP access");
}
