// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once

#include <ypcb_transport.h>
#include <ypcb_wl_config.h>
#include <array>
#include <chrono>
#include <stdexcept>
#include <thread>

namespace ypcb_bist {
namespace cfg = vortex::ypcb::wl_config;
using vortex::ypcb::Mmio;

struct Channel {
  uint32_t base, lanes, init_done, init_error, start, mode, address, length, seed;
  uint32_t done, ticks, beats, errors, lane_errors, lane_bits, lane_words;
};

inline constexpr std::array<Channel, 2> channels{{
    {0x4000, 8, cfg::ch0::ddrctrl_init_done, cfg::ch0::ddrctrl_init_error,
     cfg::ch0::ddrctrl_bist_start, cfg::ch0::ddrctrl_bist_mode,
     cfg::ch0::ddrctrl_bist_base, cfg::ch0::ddrctrl_bist_length,
     cfg::ch0::ddrctrl_bist_seed, cfg::ch0::ddrctrl_bist_done,
     cfg::ch0::ddrctrl_bist_ticks, cfg::ch0::ddrctrl_bist_beats,
     cfg::ch0::ddrctrl_bist_errors, cfg::ch0::ddrctrl_bist_lane0_errors,
     cfg::ch0::ddrctrl_bist_lane_bits, 2},
    {0x6000, 9, cfg::ddrctrl_init_done, cfg::ddrctrl_init_error,
     cfg::ddrctrl_bist_start, cfg::ddrctrl_bist_mode,
     cfg::ddrctrl_bist_base, cfg::ddrctrl_bist_length, cfg::ddrctrl_bist_seed,
     cfg::ddrctrl_bist_done, cfg::ddrctrl_bist_ticks, cfg::ddrctrl_bist_beats,
     cfg::ddrctrl_bist_errors, cfg::ddrctrl_bist_lane0_errors,
     cfg::ddrctrl_bist_lane_bits, 3}
}};

struct Pass {
  uint32_t channel, mode, words, ticks, lanes;
};

class Session {
public:
  explicit Session(Mmio& mmio, std::chrono::milliseconds timeout = std::chrono::minutes(2),
                   bool (*cancelled)() = nullptr, void (*progress)(unsigned, uint32_t) = nullptr)
      : mmio_(mmio), timeout_(timeout), cancelled_(cancelled), progress_(progress) {}

  std::array<Pass, 8> run(uint32_t words) {
    if (!words || words > (1u << 25) || timeout_.count() <= 0)
      throw std::runtime_error("Invalid native BIST length or timeout");
    if (read(0x3000) != 0x56595043 || read(0x3004) != 5)
      throw std::runtime_error("Native BIST requires the dual-channel ABI5 image");
    wait_status(3);
    check_ecc();
    bool held = false;
    std::array<Pass, 8> results{};
    try {
      // Clearing INIT_DONE before destructive traffic also blocks startup after an interrupted test.
      held = true;
      for (const auto& channel : channels) write(channel.base + channel.init_done, 0);
      wait_status(0);
      unsigned index = 0;
      for (unsigned number = 0; number < channels.size(); ++number) {
        const auto& channel = channels[number];
        for (uint32_t mode = 0; mode < 4; ++mode) {
          if (progress_) progress_(number, mode);
          if (read(channel.base + channel.done) != 1)
            throw std::runtime_error("Native BIST is already active");
          write(channel.base + channel.mode, mode);
          write(channel.base + channel.address, 0);
          write(channel.base + channel.length, words);
          write(channel.base + channel.seed, 0x01234567);
          write(channel.base + channel.seed + 4, 0x89abcdef);
          if (read(channel.base + channel.mode) != mode
              || read(channel.base + channel.address) != 0
              || read(channel.base + channel.length) != words
              || read(channel.base + channel.seed) != 0x01234567
              || read(channel.base + channel.seed + 4) != 0x89abcdef)
            throw std::runtime_error("Native BIST configuration did not latch");
          write(channel.base + channel.start, 1);
          const auto deadline = std::chrono::steady_clock::now() + timeout_;
          bool busy_seen = false;
          while (true) {
            const auto done = read(channel.base + channel.done);
            if (done == 0) busy_seen = true;
            else if (done == 1) {
              if (!busy_seen) throw std::runtime_error("Native BIST busy transition was not observed");
              break;
            } else throw std::runtime_error("Invalid native BIST done status");
            if (std::chrono::steady_clock::now() >= deadline)
              throw std::runtime_error("Native BIST timed out");
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
          }
          const auto beats = read(channel.base + channel.beats);
          const auto ticks = read(channel.base + channel.ticks);
          if (beats != words || ticks < words || read(channel.base + channel.errors) != 0)
            throw std::runtime_error("Incomplete native BIST coverage or memory errors");
          for (unsigned lane = 0; lane < channel.lanes; ++lane) {
            if (read(channel.base + channel.lane_errors + lane * 4) != 0)
              throw std::runtime_error("Native BIST lane errors");
          }
          for (unsigned word = 0; word < channel.lane_words; ++word) {
            if (read(channel.base + channel.lane_bits + word * 4) != 0)
              throw std::runtime_error("Native BIST bit errors");
          }
          check_ecc();
          wait_status(0);
          results[index++] = {number, mode, words, ticks, channel.lanes};
        }
      }
      for (const auto& channel : channels) write(channel.base + channel.init_done, 1);
      wait_status(3);
      return results;
    } catch (...) {
      if (held) {
        for (const auto& channel : channels) {
          (void)mmio_.write32(channel.base + channel.init_done, 0);
          (void)mmio_.write32(channel.base + channel.init_error, 1);
        }
      }
      throw;
    }
  }

private:
  uint32_t read(uint32_t address) {
    if (cancelled_ && cancelled_()) throw std::runtime_error("Native BIST interrupted");
    uint32_t value;
    if (mmio_.read32(address, &value)) throw std::runtime_error("Native BIST MMIO read failed");
    return value;
  }

  void write(uint32_t address, uint32_t value) {
    if (cancelled_ && cancelled_()) throw std::runtime_error("Native BIST interrupted");
    if (mmio_.write32(address, value)) throw std::runtime_error("Native BIST MMIO write failed");
  }

  void wait_status(unsigned init_done) {
    const auto deadline = std::chrono::steady_clock::now() + timeout_;
    while (true) {
      const auto status = read(0x3008);
      if ((status & 0x7ff3) != 3 || status >> 16 != 0)
        throw std::runtime_error("Native BIST requires idle startup and both PLLs");
      if (((status >> 2) & 3) == init_done) return;
      if (std::chrono::steady_clock::now() >= deadline)
        throw std::runtime_error("Native BIST readiness handshake timed out");
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
  }

  void check_ecc() {
    if (read(0x6000 + cfg::ecc_axi_0_enable) != 1
        || read(0x6000 + cfg::ecc_axi_0_sec_errors) != 0
        || read(0x6000 + cfg::ecc_axi_0_ded_errors) != 0)
      throw std::runtime_error("CH1 ECC state changed during native BIST");
  }

  Mmio& mmio_;
  std::chrono::milliseconds timeout_;
  bool (*cancelled_)();
  void (*progress_)(unsigned, uint32_t);
};
}
