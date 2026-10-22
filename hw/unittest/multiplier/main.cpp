// Copyright © 2026
// Licensed under the Apache License, Version 2.0.

#include <boost/multiprecision/cpp_int.hpp>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <iostream>
#include <random>
#include <verilated.h>
#include "VVX_multiplier.h"

using boost::multiprecision::cpp_int;

static cpp_int mask_bits(unsigned width) {
  return (cpp_int(1) << width) - 1;
}

template<unsigned Width, typename T>
static void set_port(T& port, const cpp_int& value) {
  if constexpr (Width <= 32) {
    port = value.convert_to<uint32_t>();
  } else if constexpr (Width <= 64) {
    port = value.convert_to<uint64_t>();
  } else {
    for (unsigned i = 0; i < (Width + 31) / 32; ++i) {
      cpp_int word = (value >> (32 * i)) & 0xffffffffu;
      port[i] = word.convert_to<uint32_t>();
    }
  }
}

template<unsigned Width, typename T>
static cpp_int get_port(const T& port) {
  if constexpr (Width <= 64) {
    return cpp_int(port) & mask_bits(Width);
  } else {
    cpp_int value = 0;
    for (unsigned i = 0; i < (Width + 31) / 32; ++i) {
      value |= cpp_int(port[i]) << (32 * i);
    }
    return value & mask_bits(Width);
  }
}

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  VVX_multiplier dut;
  std::mt19937 rng(0x9417c2a9u);
  auto random_bits = [&](unsigned width) {
    cpp_int value = 0;
    for (unsigned i = 0; i < width; i += 32) {
      value |= cpp_int(rng()) << i;
    }
    return cpp_int(value & mask_bits(width));
  };
  auto clock = [&]() {
    dut.clk = 0;
    dut.eval();
    dut.clk = 1;
    dut.eval();
  };
  dut.enable = 1;
  set_port<TEST_A>(dut.dataa, 0);
  set_port<TEST_B>(dut.datab, 0);
  for (unsigned i = 0; i < TEST_LAT + 2; ++i) {
    clock();
  }
  std::deque<cpp_int> history(TEST_LAT, 0);
  for (unsigned frame = 0; frame < 100000; ++frame) {
    cpp_int a = random_bits(TEST_A);
    cpp_int b = random_bits(TEST_B);
    switch (frame % 64) {
    case 0: a = 0; b = 0; break;
    case 1: a = mask_bits(TEST_A); b = mask_bits(TEST_B); break;
    case 2: a = 1; b = mask_bits(TEST_B); break;
    case 3: a = cpp_int(1) << (TEST_A - 1); b = 1; break;
    case 4: a = cpp_int(1) << (TEST_A - 1); b = cpp_int(1) << (TEST_B - 1); break;
    case 5: a = (cpp_int(1) << (TEST_A - 1)) - 1; b = mask_bits(TEST_B); break;
    case 6: a = cpp_int(1) << ((frame / 64) % TEST_A); break;
    case 7: b = cpp_int(1) << ((frame / 64) % TEST_B); break;
    default: break;
    }
    cpp_int signed_a = a;
    cpp_int signed_b = b;
    if (TEST_SIGNED && ((a >> (TEST_A - 1)) & 1) != 0) {
      signed_a -= cpp_int(1) << TEST_A;
    }
    if (TEST_SIGNED && ((b >> (TEST_B - 1)) & 1) != 0) {
      signed_b -= cpp_int(1) << TEST_B;
    }
    cpp_int product = (signed_a * signed_b) & mask_bits(TEST_R);
    dut.enable = (rng() % 4) != 0;
    set_port<TEST_A>(dut.dataa, a);
    set_port<TEST_B>(dut.datab, b);
    clock();
    cpp_int expected = product;
    if constexpr (TEST_LAT > 0) {
      if (dut.enable) {
        history.pop_front();
        history.push_back(product);
      }
      expected = history.front();
    }
    cpp_int actual = get_port<TEST_R>(dut.result);
    if (actual != expected) {
      std::cerr << "frame=" << frame << " actual=" << actual << " expected=" << expected << '\n';
      return 1;
    }
  }
  dut.final();
  std::printf("PASS: 100000 multiplier frames A=%d B=%d R=%d SIGNED=%d LATENCY=%d\n",
              TEST_A, TEST_B, TEST_R, TEST_SIGNED, TEST_LAT);
}
