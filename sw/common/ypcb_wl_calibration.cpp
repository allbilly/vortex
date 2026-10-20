// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_wl_calibration.h"
#include <ypcb_wl_config.h>
#include <thread>
#include <utility>

namespace vortex::ypcb {
namespace {
namespace cfg = wl_config;
constexpr uint32_t base = 0x6000;
constexpr uint32_t board_errors = (1u << 8) | (15u << 11);
}

WlCalibrationResult wait_wl_calibration(Mmio& mmio, WlCalibrationReport* report,
                                      std::chrono::milliseconds timeout) {
  if (!report || timeout.count() <= 0) return WlCalibrationResult::invalid;
  *report = {};
  const auto deadline = std::chrono::steady_clock::now() + timeout;
  uint32_t signature, version, board = 0, cpu, state;
  if (mmio.read32(0x3000, &signature) || mmio.read32(0x3004, &version)) {
    return WlCalibrationResult::io_error;
  }
  if (signature != 0x56595043 || version != cfg::board_abi) return WlCalibrationResult::unsafe_state;
  while (true) {
    if (std::chrono::steady_clock::now() >= deadline) return WlCalibrationResult::timeout;
    if (mmio.read32(0x3008, &board) || mmio.read32(base + cfg::ddrctrl_selfcal_status, &cpu)
        || mmio.read32(base + cfg::ddrctrl_selfcal_state, &state)) return WlCalibrationResult::io_error;
    if ((board & board_errors) || board == 0xffffffff || cpu != 0x5ca10018) {
      return WlCalibrationResult::unsafe_state;
    }
    if (state & 128) break;
    if (state != 0 && state != 1 && state != 2 && (state & 255) != 3) {
      return WlCalibrationResult::unsafe_state;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  std::array<uint32_t, 128> mailbox{};
  for (unsigned i = 0; i < mailbox.size(); ++i) {
    if (std::chrono::steady_clock::now() >= deadline) return WlCalibrationResult::timeout;
    if (mmio.write32(base + cfg::ddrctrl_selfcal_mbox_adr, i)
        || mmio.read32(base + cfg::ddrctrl_selfcal_mbox_dat, &mailbox[i])) return WlCalibrationResult::io_error;
  }
  report->firmware_id = mailbox[1];
  report->state = mailbox[2];
  report->error = (mailbox[16] >> 8) & 255;
  report->cycles_low32 = mailbox[4];
  if (mailbox[0] != cfg::mailbox_magic || mailbox[1] != cfg::calibration_firmware_id || mailbox[2] != state
      || report->error > 8 || (state != (128u | (report->error << 8) | 3u) && state != 130u)
      || mailbox[16] != ((cfg::phase_stride << 24) | (3u << 16) | (state & 0xffff & ~128u))) {
    return WlCalibrationResult::unsafe_state;
  }
  for (unsigned i = 5; i < 16; ++i) if (mailbox[i]) return WlCalibrationResult::unsafe_state;
  for (unsigned i = 76; i < 128; ++i) if (mailbox[i]) return WlCalibrationResult::unsafe_state;
  report->phase_start = int32_t(mailbox[39]);
  report->phase_steps = int32_t(mailbox[17]);
  report->phase_window = mailbox[18] & 0xffff;
  report->phase_points = mailbox[18] >> 16;
  report->selected_point = mailbox[19] & 0xffff;
  report->first_point = mailbox[19] >> 16;
  report->last_point = mailbox[20];
  report->write_slips = uint64_t(mailbox[22]) << 32 | mailbox[21];
  for (unsigned i = 0; i < 9; ++i) report->read_windows[i] = mailbox[23 + i];
  for (unsigned i = 0; i < 72; ++i) {
    const unsigned encoded = (mailbox[32 + i / 16] >> (2 * (i % 16))) & 3;
    if (encoded == 2) return WlCalibrationResult::unsafe_state;
    report->bit_offsets[i] = encoded == 3 ? -2 : encoded * 2;
  }
  for (unsigned i = 0; i < 36; ++i) report->phase_pass_maps[i] = mailbox[40 + i];
  uint32_t after, after_cpu;
  if (mmio.read32(base + cfg::ddrctrl_selfcal_state, &after)
      || mmio.read32(base + cfg::ddrctrl_selfcal_status, &after_cpu)) return WlCalibrationResult::io_error;
  if (after != state || after_cpu != cpu) return WlCalibrationResult::unsafe_state;
  if ((state & 3) == 3) return report->error ? WlCalibrationResult::failed : WlCalibrationResult::unsafe_state;
  if (report->error || !report->cycles_low32 || report->phase_points != 113 || !report->phase_window || report->phase_window > 112
      || report->selected_point >= 112 || report->first_point >= 112 || report->last_point >= 112
      || report->phase_start < -56 || report->phase_start >= 56
      || report->phase_steps < -56 || report->phase_steps >= 56
      || mailbox[22] & ~15u || mailbox[36] & 0xffff0000u
      || mailbox[37] != (0xffff0000u | report->phase_window)) return WlCalibrationResult::unsafe_state;
  const uint32_t length = (report->last_point + 112 - report->first_point) % 112 + 1;
  const int expected_phase = (report->phase_start + int(report->selected_point) + 168) % 112 - 56;
  if (length != report->phase_window || report->selected_point != (report->first_point + length / 2) % 112
      || report->phase_steps != expected_phase) return WlCalibrationResult::unsafe_state;
  for (unsigned lane = 0; lane < 9; ++lane) {
    const uint32_t value = report->read_windows[lane];
    const unsigned width = value & 255, slip = (value >> 8) & 255;
    const unsigned start = (value >> 16) & 255, tap = value >> 24;
    const unsigned write = (report->write_slips >> (lane * 4)) & 15;
    if (width < 3 || width > 32 || slip >= 8 || start + width > 32
        || tap != start + width / 2 || write > 6 || write & 1
        || report->phase_pass_maps[lane * 4 + 3] & 0xfffe0000u) return WlCalibrationResult::unsafe_state;
    for (unsigned bit = 0; bit < 8; ++bit) {
      const int framed = int(slip) + report->bit_offsets[lane * 8 + bit];
      if (framed < 0 || framed >= 8) return WlCalibrationResult::unsafe_state;
    }
    for (unsigned i = 0; i < length; ++i) {
      const unsigned point = (report->first_point + i) % 112;
      if (!((report->phase_pass_maps[lane * 4 + point / 32] >> (point % 32)) & 1)) {
        return WlCalibrationResult::unsafe_state;
      }
    }
  }
  for (const auto& item : {std::pair{cfg::ddrctrl_init_done, 1u}, {cfg::ddrctrl_init_error, 0u},
                           {cfg::ecc_axi_0_enable, 1u}, {cfg::sdram_dfii_control, 1u}}) {
    uint32_t value;
    if (mmio.read32(base + item.first, &value)) return WlCalibrationResult::io_error;
    if (value != item.second) return WlCalibrationResult::unsafe_state;
  }
  if (mmio.read32(0x3008, &board)) return WlCalibrationResult::io_error;
  return !(board & board_errors) && (board & 63) == 10
      ? WlCalibrationResult::success : WlCalibrationResult::unsafe_state;
}

}
