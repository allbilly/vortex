#pragma once
#include <stdint.h>

#if defined(VX_CFG_L3_ENABLE)
#define LRSC_GLOBAL_BANKS VX_CFG_L3_NUM_BANKS
#define LRSC_GLOBAL_LINE VX_CFG_L3_LINE_SIZE
#elif defined(VX_CFG_L2_ENABLE)
#define LRSC_GLOBAL_BANKS VX_CFG_L2_NUM_BANKS
#define LRSC_GLOBAL_LINE VX_CFG_L2_LINE_SIZE
#else
#define LRSC_GLOBAL_BANKS VX_CFG_DCACHE_NUM_BANKS
#define LRSC_GLOBAL_LINE VX_CFG_DCACHE_LINE_SIZE
#endif

#define LRSC_GLOBAL_PERIOD (LRSC_GLOBAL_BANKS * LRSC_GLOBAL_LINE)
#define LRSC_LOCAL_PERIOD (VX_CFG_LMEM_NUM_BANKS * (VX_CFG_XLEN / 8))
#define LRSC_GLOBAL_STRIDE (4 * LRSC_GLOBAL_PERIOD)
#define LRSC_LOCAL_STRIDE (4 * LRSC_LOCAL_PERIOD)
#define LRSC_CASES 14
#define LRSC_MAX_ATTEMPTS 8192

struct kernel_arg_t {
  uint64_t global_addr;
  uint64_t result_addr;
  uint32_t num_harts;
  uint32_t iterations;
  uint32_t cas_only;
};

struct result_t {
  uint32_t seen;
  uint32_t forbidden_success;
  uint32_t failed_sc_write;
  uint32_t first_sc_failed;
  uint32_t global_progress;
  uint32_t local_progress;
  uint32_t global_attempts;
  uint32_t local_attempts;
  uint32_t hart;
  uint32_t cas_seen;
  uint32_t cas_errors;
};

static inline uint32_t case_mask() {
  uint32_t mask = (1u << LRSC_CASES) - 1;
  if (LRSC_GLOBAL_BANKS == 1) mask &= ~((1u << 3) | (1u << 9));
  if (VX_CFG_LMEM_NUM_BANKS == 1) mask &= ~((1u << 5) | (1u << 11));
  return mask;
}
