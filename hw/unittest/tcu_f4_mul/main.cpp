#include <algorithm>
#include <array>
#include <cinttypes>
#include <cstdio>
#include <random>
#include <type_traits>
#include <verilated.h>
#include "VVX_tcu_f4_mul_top.h"

constexpr unsigned kWords = NUM_REGS;
constexpr unsigned kLanes = 2 * kWords;

template <typename Port>
static void put_word(Port& port, unsigned index, uint32_t word) {
  if constexpr (std::is_integral_v<Port>) {
    uint64_t mask = uint64_t{0xffffffff} << (32 * index);
    port = (port & ~mask) | (uint64_t{word} << (32 * index));
  } else {
    port[index] = word;
  }
}

struct Frame {
  std::array<uint32_t, kWords> a, b;
  uint32_t mask;
  uint8_t format, scale_a, scale_b;
};

struct Expected {
  std::array<uint32_t, kLanes> significands{}, exponents{};
  uint32_t zero_mask = 0;
};

static Expected reference(const Frame& frame) {
  Expected result;
  if (frame.format != 10 && frame.format != 11) {
    return result;
  }
  unsigned growth = 0;
  while ((1u << growth) < kLanes + 1) {
    ++growth;
  }
  int bias = 127 + 2 - 25 + 27 + growth - 1 + 128;
  bool nv = frame.format == 11;
  for (unsigned lane = 0; lane < kLanes; ++lane) {
    std::array<unsigned, 4> exponents{}, products{};
    std::array<bool, 4> signs{};
    unsigned maximum = 0;
    for (unsigned term = 0; term < 4; ++term) {
      unsigned offset = (lane % 2) * 16 + term * 4;
      unsigned a = (frame.a[lane / 2] >> offset) & 15;
      unsigned b = (frame.b[lane / 2] >> offset) & 15;
      bool valid = ((frame.mask >> (lane * 4 + term)) & 1) && (a & 7) && (b & 7);
      signs[term] = ((a ^ b) & 8) != 0;
      unsigned am = (a & 6) ? (2 | (a & 1)) : 1;
      unsigned bm = (b & 6) ? (2 | (b & 1)) : 1;
      unsigned ae = (a & 4) ? ((a & 2) ? 2 : 1) : 0;
      unsigned be = (b & 4) ? ((b & 2) ? 2 : 1) : 0;
      int exponent;
      unsigned product = am * bm;
      if (nv) {
        exponent = 10 + ((frame.scale_a >> 3) & 15) + ((frame.scale_b >> 3) & 15) + ae + be;
        product *= (8 | (frame.scale_a & 7)) * (8 | (frame.scale_b & 7));
      } else {
        exponent = 20 + int(frame.scale_a) - 127 + int(frame.scale_b) - 127 + ae + be;
      }
      exponents[term] = valid ? (unsigned(exponent) & 63) : 0;
      products[term] = valid ? product : 0;
      maximum = std::max(maximum, exponents[term]);
    }
    int64_t sum = 0;
    for (unsigned term = 0; term < 4; ++term) {
      unsigned shift = maximum - exponents[term];
      unsigned magnitude = shift >= 24 ? 0 : ((products[term] << 11) >> shift);
      sum += signs[term] ? -int64_t(magnitude) : int64_t(magnitude);
    }
    uint32_t magnitude = uint32_t(sum < 0 ? -sum : sum);
    result.significands[lane] = (sum < 0 ? (1u << 24) : 0) | (magnitude & 0xffffff);
    result.exponents[lane] = (maximum + bias - (nv ? 22 : 12)) & 1023;
    result.zero_mask |= uint32_t(sum == 0) << lane;
  }
  return result;
}

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  VVX_tcu_f4_mul_top dut;
  std::mt19937 random(0x5eed);
  Expected held;
  bool initialized = false;
  uint64_t checks = 0;
  for (unsigned iteration = 0; iteration < 100000; ++iteration) {
    Frame frame;
    frame.format = iteration % 8 < 3 ? 10 : (iteration % 8 < 6 ? 11 : (random() & 15));
    frame.scale_a = random();
    frame.scale_b = random();
    frame.mask = random();
    for (unsigned word = 0; word < kWords; ++word) {
      frame.a[word] = random();
      frame.b[word] = random();
      if (iteration % 16 == 0) {
        frame.a[word] = 0xa2a2a2a2;
        frame.b[word] = 0x22222222;
        frame.mask = 0xffffffff;
      } else if (iteration % 16 == 1) {
        frame.a[word] = 0;
      }
      put_word(dut.a_row, word, frame.a[word]);
      put_word(dut.b_col, word, frame.b[word]);
    }
    bool enable = iteration == 0 || (random() & 3) != 0;
    dut.clk = 0;
    dut.enable = enable;
    dut.valid_in = (random() & 1);
    dut.req_id = iteration;
    dut.fmt_f = frame.format;
    dut.sf_a = frame.scale_a;
    dut.sf_b = frame.scale_b;
    dut.vld_mask = frame.mask;
    dut.eval();
    Expected current = reference(frame);
    dut.clk = 1;
    dut.eval();
    if (PROD_REG == 0 || enable) {
      held = current;
      initialized = true;
    }
    for (unsigned lane = 0; lane < kLanes; ++lane) {
      if (dut.exponent_words[lane] != current.exponents[lane]
          || (initialized && dut.result_words[lane] != held.significands[lane])) {
        std::fprintf(stderr, "iteration=%u lane=%u fmt=%u: sig=%08x/%08x exp=%u/%u\n",
                     iteration, lane, frame.format, dut.result_words[lane], held.significands[lane],
                     dut.exponent_words[lane], current.exponents[lane]);
        return 1;
      }
      ++checks;
    }
    if ((initialized && dut.sig_zero != held.zero_mask) || dut.exception_flags != 0) {
      std::fprintf(stderr, "iteration=%u: zero mask or exception mismatch\n", iteration);
      return 1;
    }
  }
  dut.final();
  std::printf("PASS: 100000 scaled FP4 frames, %" PRIu64 " lane checks, N=%u PROD_REG=%u\n",
              checks, kWords, unsigned(PROD_REG));
  return 0;
}
