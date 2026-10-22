#include <vx_spawn2.h>
#include <vx_intrinsics.h>
#include "common.h"

static inline __attribute__((always_inline)) uint32_t progress(uint32_t* address,
    uint32_t iterations, uint32_t* attempts) {
  uint32_t completed = 0;
  for (uint32_t iteration = 0; iteration < iterations; ++iteration) {
    uint32_t status = 1;
    for (uint32_t retry = 0; retry < LRSC_MAX_ATTEMPTS && status; ++retry) {
      uint32_t value;
      asm volatile ("lr.w %0, (%2)\naddi %0, %0, 1\nsc.w %1, %0, (%2)"
                    : "=&r"(value), "=&r"(status) : "r"(address) : "memory");
      ++*attempts;
    }
    completed += status == 0;
  }
  return completed;
}

__kernel void kernel_main(kernel_arg_t* __UNIFORM__ arg) {
  const uint32_t task = blockIdx.x * blockDim.x + threadIdx.x;
  if (task >= arg->num_harts) return;
  auto global = reinterpret_cast<uint8_t*>(uintptr_t(arg->global_addr));
  auto local = reinterpret_cast<uint8_t*>(__local_mem());
  auto g0 = reinterpret_cast<uint32_t*>(global + task * LRSC_GLOBAL_STRIDE
      + (task % LRSC_GLOBAL_BANKS) * LRSC_GLOBAL_LINE);
  auto gs = reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(g0) + LRSC_GLOBAL_PERIOD);
  auto gd = reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(g0) + LRSC_GLOBAL_LINE);
  auto l0 = reinterpret_cast<uint32_t*>(local + threadIdx.x * LRSC_LOCAL_STRIDE
      + (threadIdx.x % VX_CFG_LMEM_NUM_BANKS) * (VX_CFG_XLEN / 8));
  auto ls = reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(l0) + LRSC_LOCAL_PERIOD);
  auto ld = reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(l0) + VX_CFG_XLEN / 8);
  const uint32_t initial = 0x11220000u + task;
  *g0 = *gs = *gd = *l0 = *ls = *ld = initial;
  asm volatile ("fence rw,rw" ::: "memory");
  result_t result = {};
  result.hart = uint32_t(vx_hart_id());
  if (!arg->cas_only) {
    for (uint32_t iteration = 0; iteration < arg->iterations; ++iteration) {
      for (uint32_t test = 0; test < LRSC_CASES; ++test) {
        if (!(case_mask() & (1u << test))) continue;
        uint32_t* first = g0;
        uint32_t* other = g0;
        switch (test) {
        case 1: first = other = l0; break;
        case 2: case 8: other = gs; break;
        case 3: case 9: other = gd; break;
        case 4: case 10: first = l0; other = ls; break;
        case 5: case 11: first = l0; other = ld; break;
        case 6: case 12: other = l0; break;
        case 7: case 13: first = l0; other = g0; break;
        default: break;
        }
        uint32_t old, first_status = 1, status;
        const uint32_t value = 0x33440000u + test;
        const uint32_t forbidden = 0x55660000u + test;
        if (test < 8) {
          asm volatile ("lr.w %0, (%3)\nsc.w %1, %5, (%4)\nsc.w %2, %6, (%3)"
                        : "=&r"(old), "=&r"(first_status), "=&r"(status)
                        : "r"(first), "r"(other), "r"(value), "r"(forbidden) : "memory");
        } else {
          uint32_t ignored;
          asm volatile ("lr.w %0, (%3)\nlr.w %1, (%4)\nsc.w %2, %5, (%3)"
                        : "=&r"(old), "=&r"(ignored), "=&r"(status)
                        : "r"(first), "r"(other), "r"(forbidden) : "memory");
        }
        const uint32_t expected = test < 2 && first_status == 0 ? value : old;
        result.seen |= 1u << test;
        result.forbidden_success |= uint32_t(status == 0) << test;
        result.failed_sc_write |= uint32_t(*first != expected) << test;
        if (test < 8) result.first_sc_failed |= uint32_t(first_status != 0) << test;
      }
    }
    result.global_progress = progress(g0, arg->iterations, &result.global_attempts);
    result.local_progress = progress(l0, arg->iterations, &result.local_attempts);
  }
#if VX_CFG_EXT_ZACAS_ENABLED
  for (uint32_t phase = 0; phase < 2; ++phase) {
    auto address = ((threadIdx.x + phase) & 1) ? ls : gs;
    const uint32_t initial_cas = 0x22440000u + task;
    const uint32_t desired = initial_cas + 1;
    *address = initial_cas;
    asm volatile ("fence rw,rw" ::: "memory");
    uint32_t observed = initial_cas;
    asm volatile ("amocas.w.aqrl %0, %2, (%1)" : "+&r"(observed)
                  : "r"(address), "r"(desired) : "memory");
    result.cas_errors |= uint32_t(observed != initial_cas || *address != desired) << (2 * phase);
    observed = initial_cas;
    const uint32_t forbidden = desired + 1;
    asm volatile ("amocas.w.aqrl %0, %2, (%1)" : "+&r"(observed)
                  : "r"(address), "r"(forbidden) : "memory");
    result.cas_errors |= uint32_t(observed != desired || *address != desired) << (2 * phase + 1);
    result.cas_seen |= 1u << phase;
  }
#endif
  auto results = reinterpret_cast<result_t*>(uintptr_t(arg->result_addr));
  results[task] = result;
}
