#include <array>
#include <cstdint>
#include <cstdio>
#include <verilated.h>
#include "VVX_tcu_tfr_masked_max_exp.h"

static uint32_t rng_state = 0x63a5f18du;

static uint32_t next_random() {
  rng_state ^= rng_state << 13;
  rng_state ^= rng_state >> 17;
  rng_state ^= rng_state << 5;
  return rng_state;
}

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  VVX_tcu_tfr_masked_max_exp dut;
  constexpr uint32_t value_mask = (1u << TEST_WIDTH) - 1;
  constexpr uint32_t lane_mask = (1u << TEST_N) - 1;
  static_assert(TEST_DEPTH == 0 || TEST_DEPTH == 1);
  std::array<uint32_t, TEST_N> current{}, held{};
  for (unsigned frame = 0; frame < 100000; ++frame) {
    for (unsigned i = 0; i < TEST_N; ++i) {
      current[i] = (next_random() & 3u) ? next_random() & value_mask : 0;
      if ((frame & 63u) == 0) {
        current[i] = 0;
      } else if ((frame & 63u) == 1) {
        current[i] = value_mask;
      } else if ((frame & 63u) == 2) {
        current[i] = i;
      } else if ((frame & 63u) == 3) {
        current[i] = TEST_N - i;
      }
    }
#if TEST_N * TEST_WIDTH > 64
    for (unsigned word = 0; word < (TEST_N * TEST_WIDTH + 31) / 32; ++word) {
      dut.exponents[word] = 0;
    }
    for (unsigned i = 0; i < TEST_N; ++i) {
      for (unsigned bit = 0; bit < TEST_WIDTH; ++bit) {
        if (current[i] & (1u << bit)) {
          unsigned offset = i * TEST_WIDTH + bit;
          dut.exponents[offset / 32] |= 1u << (offset % 32);
        }
      }
    }
#else
    uint64_t packed = 0;
    for (unsigned i = 0; i < TEST_N; ++i) {
      packed |= uint64_t(current[i]) << (i * TEST_WIDTH);
    }
    dut.exponents = packed;
#endif
    uint32_t zeros = next_random() & lane_mask;
    if ((frame & 31u) == 0) {
      zeros = lane_mask;
    } else if ((frame & 31u) == 1) {
      zeros = 0;
    }
    dut.zero_mask = zeros;
    dut.enable = frame == 0 || (next_random() % 4 != 0);
    dut.clk = 0;
    dut.eval();
    dut.clk = 1;
    dut.eval();
    if (TEST_DEPTH == 0 || dut.enable) {
      held = current;
    }
    uint32_t best_value = (zeros & 1u) ? 0 : held[0];
    unsigned best_index = 0;
    for (unsigned i = 1; i < TEST_N; ++i) {
      uint32_t value = (zeros & (1u << i)) ? 0 : held[i];
      if (value > best_value) {
        best_value = value;
        best_index = i;
      }
    }
    uint32_t expected = 1u << best_index;
    if (uint32_t(dut.sel_exp) != expected) {
      std::fprintf(stderr, "frame=%u actual=%x expected=%x mask=%x\n",
                   frame, unsigned(dut.sel_exp), expected, zeros);
      return 1;
    }
  }
  dut.final();
  std::printf("PASS: 100000 masked exponent frames N=%u WIDTH=%u DEPTH=%u\n",
              TEST_N, TEST_WIDTH, TEST_DEPTH);
}
