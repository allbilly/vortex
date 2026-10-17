// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_ddr.h"
#include <ypcb_ddr_config.h>
#include <thread>
#include <utility>

namespace vortex::ypcb {
namespace cfg = ddr_config;
namespace {
constexpr unsigned phase_bytes = 18;
constexpr unsigned phase_words = 5;
constexpr uint32_t software_control = cfg::dfii_control_cke | cfg::dfii_control_odt | cfg::dfii_control_reset_n;
constexpr uint32_t activate = cfg::dfii_command_ras | cfg::dfii_command_cs;
constexpr uint32_t precharge = activate | cfg::dfii_command_we;
constexpr uint32_t read_command = cfg::dfii_command_cas | cfg::dfii_command_cs | cfg::dfii_command_rddata;
constexpr uint32_t write_command = cfg::dfii_command_cas | cfg::dfii_command_we | cfg::dfii_command_cs | cfg::dfii_command_wrdata;
constexpr std::array<uint32_t, 3> seeds = {42, 84, 36};
static_assert(cfg::sdram_phy_modules == 9 && cfg::sdram_phy_dfi_databits == phase_bytes * 8);
static_assert(cfg::sdram_phy_rdphase < 4 && cfg::sdram_phy_wrphase < 4);
}

bool select_read_window(const ReadScan& scan, ReadWindow* window) {
  if (window == nullptr) {
    return false;
  }
  unsigned best_length = 1;
  ReadWindow best;
  for (unsigned bitslip = 0; bitslip < scan.size(); ++bitslip) {
    unsigned length = 0;
    for (unsigned tap = 0; tap <= 32; ++tap) {
      if (tap < 32 && ((scan[bitslip] >> tap) & 1)) {
        ++length;
      } else {
        if (length > best_length) {
          best_length = length;
          best = {bitslip, tap - length, tap - 1, (tap - length + tap - 1) / 2};
        }
        length = 0;
      }
    }
  }
  if (best_length < 2) {
    return false;
  }
  *window = best;
  return true;
}

Ddr::Ddr(Mmio& mmio, unsigned bank, std::chrono::milliseconds timeout)
  : mmio_(mmio)
  , bank_(bank)
  , base_(0x4000 + bank * 0x2000)
  , timeout_(timeout) {
}

DdrResult Ddr::write(uint32_t offset, uint32_t value) {
  if (std::chrono::steady_clock::now() >= deadline_) {
    return DdrResult::timeout;
  }
  return mmio_.write32(base_ + offset, value) == 0 ? DdrResult::success : DdrResult::io_error;
}

DdrResult Ddr::read(uint32_t offset, uint32_t* value) {
  if (std::chrono::steady_clock::now() >= deadline_) {
    return DdrResult::timeout;
  }
  return mmio_.read32(base_ + offset, value) == 0 ? DdrResult::success : DdrResult::io_error;
}

DdrResult Ddr::wait(unsigned cycles) {
  const auto duration = std::chrono::nanoseconds((uint64_t(cycles) * 1000000000ull + cfg::sys_clock_hz - 1) / cfg::sys_clock_hz);
  const auto end = std::chrono::steady_clock::now() + duration;
  if (end >= deadline_) {
    return DdrResult::timeout;
  }
  if (duration >= std::chrono::microseconds(50)) {
    std::this_thread::sleep_until(end);
  }
  // Short DFII waits must not become scheduler-sized pauses with an open row.
  while (std::chrono::steady_clock::now() < end) {
  }
  return std::chrono::steady_clock::now() < deadline_ ? DdrResult::success : DdrResult::timeout;
}

DdrResult Ddr::command(unsigned phase, uint32_t value) {
  auto result = write(cfg::phases[phase].command, value);
  if (result != DdrResult::success) {
    return result;
  }
  result = write(cfg::phases[phase].issue, 1);
  if (result != DdrResult::success) {
    return result;
  }
  uint32_t fence;
  return read(cfg::sdram_dfii_control, &fence);
}

DdrResult Ddr::configure_lane(unsigned lane, unsigned bitslip, unsigned delay) {
  const std::array<std::pair<uint32_t, uint32_t>, 3> reset = {{
    {cfg::ddrphy_dly_sel, 1u << lane}, {cfg::ddrphy_rdly_dq_rst, 1},
    {cfg::ddrphy_rdly_dq_bitslip_rst, 1},
  }};
  for (const auto& reg : reset) {
    auto result = write(reg.first, reg.second);
    if (result != DdrResult::success) {
      return result;
    }
  }
  for (unsigned pulse = 0; pulse < bitslip; ++pulse) {
    auto result = write(cfg::ddrphy_rdly_dq_bitslip, 1);
    if (result != DdrResult::success) {
      return result;
    }
  }
  for (unsigned pulse = 0; pulse < delay; ++pulse) {
    auto result = write(cfg::ddrphy_rdly_dq_inc, 1);
    if (result != DdrResult::success) {
      return result;
    }
  }
  return write(cfg::ddrphy_dly_sel, 0);
}

DdrResult Ddr::probe(uint32_t seed, std::array<unsigned, 9>* errors) {
  for (const auto& phase : cfg::phases) {
    auto result = write(phase.address, 0);
    if (result != DdrResult::success) {
      return result;
    }
    result = write(phase.bank, 0);
    if (result != DdrResult::success) {
      return result;
    }
  }
  std::array<std::array<uint8_t, phase_bytes>, 4> expected;
  for (unsigned phase = 0; phase < expected.size(); ++phase) {
    std::array<uint32_t, phase_words> words{};
    for (unsigned byte = 0; byte < phase_bytes; ++byte) {
      seed ^= seed << 13;
      seed ^= seed >> 17;
      seed ^= seed << 5;
      expected[phase][byte] = uint8_t(seed);
      words[byte / 4] |= uint32_t(expected[phase][byte]) << ((byte % 4) * 8);
    }
    for (unsigned word = 0; word < phase_words; ++word) {
      auto result = write(cfg::phases[phase].wrdata + (phase_words - 1 - word) * 4, words[word]);
      if (result != DdrResult::success) {
        return result;
      }
    }
  }
  auto result = command(0, activate);
  if (result != DdrResult::success) {
    return result;
  }
  result = wait(15);
  if (result != DdrResult::success) {
    return result;
  }
  result = command(cfg::sdram_phy_wrphase, write_command);
  if (result != DdrResult::success) {
    return result;
  }
  result = wait(15);
  if (result != DdrResult::success) {
    return result;
  }
  result = command(cfg::sdram_phy_rdphase, read_command);
  if (result != DdrResult::success) {
    return result;
  }
  result = wait(15);
  if (result != DdrResult::success) {
    return result;
  }
  result = command(0, precharge);
  if (result != DdrResult::success) {
    return result;
  }
  result = wait(15);
  if (result != DdrResult::success) {
    return result;
  }
  errors->fill(0);
  for (unsigned phase = 0; phase < expected.size(); ++phase) {
    std::array<uint32_t, phase_words> words;
    for (unsigned word = 0; word < phase_words; ++word) {
      result = read(cfg::phases[phase].rddata + (phase_words - 1 - word) * 4, &words[word]);
      if (result != DdrResult::success) {
        return result;
      }
    }
    for (unsigned byte = 0; byte < phase_bytes; ++byte) {
      const uint8_t actual = uint8_t(words[byte / 4] >> ((byte % 4) * 8));
      (*errors)[byte % 9] += unsigned(__builtin_popcount(unsigned(actual ^ expected[phase][byte])));
    }
  }
  return DdrResult::success;
}

DdrResult Ddr::finish_failure(DdrResult result, DdrReport* report) {
  bool cleaned = mmio_.write32(base_ + cfg::ddrctrl_init_done, 0) == 0;
  cleaned &= mmio_.write32(base_ + cfg::ddrctrl_init_error, 1) == 0;
  cleaned &= mmio_.write32(base_ + cfg::ddrphy_dly_sel, 0) == 0;
  cleaned &= mmio_.write32(base_ + cfg::ddrphy_rst, 0) == 0;
  cleaned &= mmio_.write32(base_ + cfg::sdram_dfii_control, cfg::dfii_control_odt) == 0;
  uint32_t done, error, control;
  cleaned &= mmio_.read32(base_ + cfg::ddrctrl_init_done, &done) == 0;
  cleaned &= mmio_.read32(base_ + cfg::ddrctrl_init_error, &error) == 0;
  cleaned &= mmio_.read32(base_ + cfg::sdram_dfii_control, &control) == 0;
  report->cleanup_complete = cleaned && done == 0 && error == 1 && control == cfg::dfii_control_odt;
  return report->cleanup_complete ? result : DdrResult::io_error;
}

DdrResult Ddr::train(DdrReport* report) {
  for (unsigned lane = 0; lane < 9; ++lane) {
    report->failed_lane = lane;
    for (unsigned bitslip = 0; bitslip < 8; ++bitslip) {
      auto result = configure_lane(lane, bitslip, 0);
      if (result != DdrResult::success) {
        return result;
      }
      for (unsigned tap = 0; tap < 32; ++tap) {
        bool passed = true;
        for (uint32_t seed : seeds) {
          std::array<unsigned, 9> errors;
          result = probe(seed, &errors);
          if (result != DdrResult::success) {
            return result;
          }
          ++report->probes;
          passed &= errors[lane] == 0;
        }
        if (passed) {
          report->scans[lane][bitslip] |= 1u << tap;
        }
        result = write(cfg::ddrphy_dly_sel, 1u << lane);
        if (result != DdrResult::success) {
          return result;
        }
        result = write(cfg::ddrphy_rdly_dq_inc, 1);
        if (result != DdrResult::success) {
          return result;
        }
        result = write(cfg::ddrphy_dly_sel, 0);
        if (result != DdrResult::success) {
          return result;
        }
      }
    }
    auto& window = report->lanes[lane];
    if (!select_read_window(report->scans[lane], &window)) {
      return DdrResult::training_failed;
    }
    auto result = configure_lane(lane, window.bitslip, window.center);
    if (result != DdrResult::success) {
      return result;
    }
    for (uint32_t seed : seeds) {
      std::array<unsigned, 9> errors;
      result = probe(seed, &errors);
      if (result != DdrResult::success) {
        return result;
      }
      ++report->probes;
      if (errors[lane] != 0) {
        return DdrResult::training_failed;
      }
    }
  }
  for (uint32_t seed : seeds) {
    std::array<unsigned, 9> errors;
    auto result = probe(seed, &errors);
    if (result != DdrResult::success) {
      return result;
    }
    ++report->probes;
    for (unsigned lane = 0; lane < errors.size(); ++lane) {
      if (errors[lane] != 0) {
        report->failed_lane = lane;
        return DdrResult::training_failed;
      }
    }
  }
  report->failed_lane = 9;
  return DdrResult::success;
}

DdrResult Ddr::initialize(DdrReport* report) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (report == nullptr || bank_ >= 2 || timeout_.count() <= 0) {
    return DdrResult::invalid;
  }
  *report = {};
  deadline_ = std::chrono::steady_clock::now() + timeout_;
  uint32_t signature, version, status, done, error;
  if (attempted_) {
    return DdrResult::unsafe_state;
  }
  if (mmio_.read32(0x3000, &signature) != 0 || mmio_.read32(0x3004, &version) != 0
      || mmio_.read32(0x3008, &status) != 0) {
    return DdrResult::io_error;
  }
  if (signature != 0x56595043 || version != 1 || (status & (0x7ffu << 4)) != 0 || (status >> 16) != 0
      || !(status & (1u << bank_))) {
    return DdrResult::unsafe_state;
  }
  auto result = read(cfg::ddrctrl_init_done, &done);
  if (result != DdrResult::success) {
    return result;
  }
  result = read(cfg::ddrctrl_init_error, &error);
  if (result != DdrResult::success) {
    return result;
  }
  if (done != 0 || error != 0) {
    return DdrResult::unsafe_state;
  }
  attempted_ = true;
  const std::array<std::pair<uint32_t, uint32_t>, 8> setup = {{
    {cfg::ddrctrl_init_done, 0}, {cfg::ddrctrl_init_error, 0},
    {cfg::sdram_dfii_control, cfg::dfii_control_odt}, {cfg::ddrphy_rst, 1},
    {cfg::ddrphy_rdphase, cfg::sdram_phy_rdphase}, {cfg::ddrphy_wrphase, cfg::sdram_phy_wrphase},
    {cfg::sdram_dfii_pi0_address, 0}, {cfg::sdram_dfii_pi0_baddress, 0},
  }};
  for (const auto& reg : setup) {
    result = write(reg.first, reg.second);
    if (result != DdrResult::success) {
      return finish_failure(result, report);
    }
  }
  result = wait(1000);
  if (result == DdrResult::success) {
    result = write(cfg::ddrphy_rst, 0);
  }
  uint32_t fence;
  if (result == DdrResult::success) {
    result = read(cfg::sdram_dfii_control, &fence);
  }
  if (result == DdrResult::success) {
    result = wait((uint64_t(cfg::sys_clock_hz) * 200 + 999999) / 1000000);
  }
  for (const auto& op : cfg::initialization) {
    if (result != DdrResult::success) {
      break;
    }
    if (op.kind == cfg::Kind::wait) {
      result = read(cfg::sdram_dfii_control, &fence);
      if (result == DdrResult::success) {
        result = wait(op.value);
      }
    } else {
      result = write(op.offset, op.value);
    }
  }
  if (result == DdrResult::success) {
    result = write(cfg::sdram_dfii_control, software_control);
  }
  for (unsigned lane = 0; result == DdrResult::success && lane < 9; ++lane) {
    result = configure_lane(lane, 0, 0);
  }
  if (result == DdrResult::success) {
    result = train(report);
  }
  if (result == DdrResult::success) {
    result = write(cfg::ecc_axi_0_enable, 1);
  }
  if (result == DdrResult::success) {
    result = read(cfg::ecc_axi_0_enable, &fence);
    if (result == DdrResult::success && fence != 1) {
      result = DdrResult::io_error;
    }
  }
  if (result == DdrResult::success) {
    result = write(cfg::sdram_dfii_control, cfg::dfii_control_sel);
  }
  if (result == DdrResult::success) {
    result = read(cfg::sdram_dfii_control, &fence);
    if (result == DdrResult::success && fence != cfg::dfii_control_sel) {
      result = DdrResult::io_error;
    }
  }
  if (result == DdrResult::success) {
    result = write(cfg::ddrctrl_init_done, 1);
  }
  if (result == DdrResult::success) {
    result = read(cfg::ddrctrl_init_done, &done);
    if (result == DdrResult::success && done != 1) {
      result = DdrResult::io_error;
    }
  }
  if (result != DdrResult::success) {
    return finish_failure(result, report);
  }
  report->calibrated = true;
  return DdrResult::success;
}

}
