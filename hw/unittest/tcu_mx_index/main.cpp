#include <array>
#include <cinttypes>
#include <cstdio>
#include <random>
#include <verilated.h>
#include "VVX_tcu_mx_index_top.h"

static uint32_t data_width(uint32_t format) {
  switch (format) {
  case 0: case 1: case 16:
    return 32;
  case 2: case 3:
    return 16;
  case 4: case 5: case 8: case 9: case 17: case 18:
    return 8;
  case 10: case 11: case 19: case 20:
    return 4;
  default:
    return 0;
  }
}

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  VVX_tcu_mx_index_top dut;
  std::mt19937 random(0x5eed);
  uint64_t cases = 0;
  const std::array<uint32_t, 10> corners = {
    0, 1, 7, 15, 31, 0x1fffffff, 0x3fffffff, 0x7fffffff, 0xfffffffe, 0xffffffff
  };
  auto check = [&](uint32_t format, uint32_t words, uint32_t element) {
    uint32_t width = data_width(format);
    uint32_t block = (format == 11) ? 16 : ((format >= 8 && format <= 10) ? 32 : 1);
    uint32_t elements = width ? words * (32 / width) : 0;
    uint32_t blocks = (elements + block - 1) / block;
    uint32_t index = element / block;
    dut.fmt = format;
    dut.tile_k_words = words;
    dut.element_index = element;
    dut.eval();
    if (dut.scale_blocks != blocks || dut.block_index != index
        || (width != 0 && dut.elements_per_word != 32 / width)) {
      std::fprintf(stderr, "format=%u words=%08x element=%08x: blocks=%08x/%08x index=%08x/%08x\n",
                   format, words, element, dut.scale_blocks, blocks, dut.block_index, index);
      return false;
    }
    ++cases;
    return true;
  };
  for (uint32_t format = 0; format < 32; ++format) {
    for (uint32_t words = 0; words <= 256; ++words) {
      if (!check(format, words, ~words)) {
        return 1;
      }
    }
    for (uint32_t words : corners) {
      if (!check(format, words, words)) {
        return 1;
      }
    }
    for (uint32_t trial = 0; trial < 4096; ++trial) {
      if (!check(format, random(), random())) {
        return 1;
      }
    }
  }
  dut.final();
  std::printf("PASS: %" PRIu64 " MX indexing cases across all 32 format codes\n", cases);
  return 0;
}
