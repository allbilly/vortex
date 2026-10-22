#include <array>
#include <cstdint>
#include <cstdio>
#include <random>
#include <type_traits>
#include <unordered_map>
#include <verilated.h>
#include "lrsc_tracker.h"
#include "VVX_lsu_lrsc_top.h"

template <typename Port>
static void put_word(Port& port, unsigned word, uint32_t value) {
  if constexpr (std::is_integral_v<Port>) {
    uint64_t bits = port;
    bits = (bits & ~(uint64_t(0xffffffffu) << (word * 32))) | (uint64_t(value) << (word * 32));
    port = bits;
  } else {
    port[word] = value;
  }
}

template <typename Port>
static uint32_t get_word(const Port& port, unsigned word) {
  if constexpr (std::is_integral_v<Port>) {
    return uint64_t(port) >> (word * 32);
  } else {
    return port[word];
  }
}

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  VVX_lsu_lrsc_top dut;
  vortex::LrscTracker simx(TEST_THREADS * TEST_WARPS);
  std::unordered_map<unsigned, uint64_t> reference;
  std::mt19937 random(0x97531);
  std::array<uint64_t, TEST_LANES> addresses{};
  constexpr unsigned packets = TEST_THREADS / TEST_LANES;
  static_assert(TEST_LANES >= 1 && TEST_LANES <= 64);
  constexpr uint64_t all_lanes = ~uint64_t(0) >> (64 - TEST_LANES);
  constexpr uint64_t width_mask = TEST_XLEN == 32 ? 0xffffffffull : ~uint64_t(0);
  unsigned checks = 0;
  for (unsigned frame = 0; frame < 50000; ++frame) {
    unsigned operation = random() % 3;
    unsigned wid = random() % TEST_WARPS;
    unsigned pid = random() % packets;
    bool fire = random() % 4 != 0;
    uint64_t mask = ((uint64_t(random()) << 32) | random()) & all_lanes;
    bool reset = frame % 997 == 0;
    unsigned directed = frame % 64;
    if (directed < 16) {
      wid = (frame / 64) % TEST_WARPS;
      pid = (frame / 64) % packets;
      mask = all_lanes;
      fire = true;
      operation = (directed == 0 || directed == 1 || directed == 4 || directed == 7
                || directed == 8 || directed == 11 || directed == 12) ? 1 : 2;
      if (directed >= 15) {
        fire = false;
      }
    }
    for (unsigned lane = 0; lane < TEST_LANES; ++lane) {
      uint64_t address = (uint64_t(random()) << 32 | random()) & width_mask & ~uint64_t(3);
      if (directed < 16) {
        uint64_t a = 0x10000 + lane * 1024;
        uint64_t b = a + 128;
        switch (directed) {
        case 1: case 2: case 5: address = b; break;
        case 8: case 9: case 11: case 14: address = 0x7fff0000 + lane * 1024; break;
        case 12: case 13: address = b; break;
        default: address = a; break;
        }
      }
      addresses[lane] = address;
      put_word(dut.address_words, lane * 2, uint32_t(address));
      put_word(dut.address_words, lane * 2 + 1, uint32_t(address >> 32));
    }
    dut.clk = 0;
    dut.reset = reset;
    dut.fire = fire;
    dut.is_lr = operation == 1;
    dut.is_sc = operation == 2;
    dut.mask = mask;
    dut.wid = wid;
    dut.pid = pid;
    dut.eval();
    if (frame != 0) {
      for (unsigned lane = 0; lane < TEST_LANES; ++lane) {
        unsigned local_hart = wid * TEST_THREADS + pid * TEST_LANES + lane;
        auto found = reference.find(local_hart);
        bool allowed = found != reference.end() && found->second == addresses[lane];
        bool failed = operation == 2 && !allowed;
        bool hardware_failed = (uint64_t(dut.sc_fail) >> lane) & 1;
        unsigned expected_hart = TEST_WARPS * TEST_THREADS + local_hart;
        if (hardware_failed != failed || simx.matches(local_hart, addresses[lane]) != allowed
            || get_word(dut.hart_words, lane) != expected_hart) {
          std::fprintf(stderr, "frame=%u lane=%u hart=%u RTL_fail=%u expected_fail=%u\n",
                       frame, lane, local_hart, hardware_failed, failed);
          return 1;
        }
        if (frame < 16) {
          std::printf("TRACE frame=%u hart=%u op=%u fire=%u mask=%u addr=%llx rtl_fail=%u simx_fail=%u reference_fail=%u\n",
                      frame, expected_hart, operation, fire, unsigned((mask >> lane) & 1),
                      static_cast<unsigned long long>(addresses[lane]), hardware_failed,
                      operation == 2 && !simx.matches(local_hart, addresses[lane]), failed);
        }
        ++checks;
      }
    }
    dut.clk = 1;
    dut.eval();
    if (reset) {
      reference.clear();
      simx.reset();
    } else if (fire) {
      for (unsigned lane = 0; lane < TEST_LANES; ++lane) {
        if (!(mask & (uint64_t(1) << lane))) {
          continue;
        }
        unsigned hart = wid * TEST_THREADS + pid * TEST_LANES + lane;
        if (operation == 1) {
          reference[hart] = addresses[lane];
          simx.reserve(hart, addresses[lane]);
        } else if (operation == 2) {
          reference.erase(hart);
          simx.clear(hart);
        }
      }
    }
  }
  dut.final();
  std::printf("PASS: %u LR/SC RTL-SimX-oracle lane checks, threads=%u warps=%u lanes=%u XLEN=%u\n",
              checks, TEST_THREADS, TEST_WARPS, TEST_LANES, TEST_XLEN);
}
