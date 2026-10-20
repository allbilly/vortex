// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_calibration.h"
#include "ypcb_calibration_abi.h"
#include <ypcb_ddr_config.h>
#include <thread>
#include <utility>

namespace vortex::ypcb {
namespace {
namespace cfg = ddr_config;
constexpr uint32_t base = 0x6000;
constexpr uint32_t board_errors = (3u << 4) | (1u << 8) | (15u << 11);
}

CalibrationResult wait_calibration(Mmio& mmio, CalibrationReport* report,
                                  std::chrono::milliseconds timeout) {
  if (report == nullptr || timeout.count() <= 0) return CalibrationResult::invalid;
  *report = {};
  const auto deadline = std::chrono::steady_clock::now() + timeout;
  uint32_t signature, version, board = 0;
  if (mmio.read32(0x3000, &signature) || mmio.read32(0x3004, &version)) {
    return CalibrationResult::io_error;
  }
  if (signature != 0x56595043 || version != 3) return CalibrationResult::unsafe_state;
  while (true) {
    if (std::chrono::steady_clock::now() >= deadline) return CalibrationResult::timeout;
    if (mmio.read32(0x3008, &board)) return CalibrationResult::io_error;
    // Calibration failure is reported through its mailbox before interpreting init_error.
    if ((board & (board_errors & ~(3u << 4))) || board == 0xffffffff) {
      return CalibrationResult::unsafe_state;
    }
    if ((board & 3) == 2) {
      uint32_t cpu;
      if (mmio.read32(base + cfg::ddrctrl_selfcal_status, &cpu)
          || mmio.read32(base + cfg::ddrctrl_selfcal_state, &report->state)) {
        return CalibrationResult::io_error;
      }
      if (cpu != 0x5ca10018) return CalibrationResult::unsafe_state;
      if (report->state == YPCB_CAL_READY || report->state == YPCB_CAL_FAILED) break;
      if (report->state > YPCB_CAL_FAILED) return CalibrationResult::unsafe_state;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  auto mailbox = [&](uint32_t index, uint32_t* value) {
    return std::chrono::steady_clock::now() < deadline
      && mmio.write32(base + cfg::ddrctrl_selfcal_mbox_adr, index) == 0
      && mmio.read32(base + cfg::ddrctrl_selfcal_mbox_dat, value) == 0;
  };
  std::array<uint32_t, 16> header{};
  for (unsigned i = 0; i < header.size(); ++i) {
    if (!mailbox(i, &header[i])) return CalibrationResult::io_error;
  }
  report->firmware_id = header[YPCB_CAL_MB_FIRMWARE];
  report->error = header[YPCB_CAL_MB_ERROR];
  report->failed_lane = header[YPCB_CAL_MB_FAILED_LANE];
  report->probes = header[YPCB_CAL_MB_PROBES];
  report->max_row_cycles = header[YPCB_CAL_MB_MAX_ROW_CYCLES];
  report->cycles = (uint64_t(header[YPCB_CAL_MB_CYCLES_HIGH]) << 32) | header[YPCB_CAL_MB_CYCLES_LOW];
  report->write_slips = header[YPCB_CAL_MB_WRITE_SLIPS];
  if (report->write_slips & ~0x06db6db6u) return CalibrationResult::unsafe_state;
  if (header[YPCB_CAL_MB_MAGIC] != YPCB_CAL_MAGIC || header[YPCB_CAL_MB_STATE] != report->state
      || report->firmware_id != cfg::calibration_firmware_id) return CalibrationResult::unsafe_state;
  for (unsigned i = 0; i < report->lanes.size(); ++i) {
    if (!mailbox(YPCB_CAL_MB_LANES + i, &report->lanes[i])) return CalibrationResult::io_error;
  }
  for (unsigned i = 0; i < report->scans.size(); ++i) {
    if (!mailbox(YPCB_CAL_MB_SCANS + i, &report->scans[i])) return CalibrationResult::io_error;
  }
  const uint32_t diagnostic_magic = header[YPCB_CAL_MB_DIAG_MAGIC];
  if (diagnostic_magic != 0 && diagnostic_magic != YPCB_CAL_DIAG_MAGIC) {
    return CalibrationResult::unsafe_state;
  }
  if (diagnostic_magic == YPCB_CAL_DIAG_MAGIC) {
    report->has_bit_diagnostics = true;
    report->diagnostic_lane = header[YPCB_CAL_MB_DIAG_LANE];
    report->diagnostic_valid_bits = header[YPCB_CAL_MB_DIAG_VALID_BITS];
    report->diagnostic_error_or = header[YPCB_CAL_MB_DIAG_ERROR_OR];
    report->diagnostic_error_and = header[YPCB_CAL_MB_DIAG_ERROR_AND];
    report->diagnostic_taps = header[YPCB_CAL_MB_DIAG_TAPS];
    if (report->state != YPCB_CAL_FAILED || report->error != 2
        || report->diagnostic_lane != report->failed_lane || report->diagnostic_lane >= 9
        || report->diagnostic_valid_bits > 255 || report->diagnostic_error_or > 255
        || report->diagnostic_error_and > 255 || report->diagnostic_taps != 256) {
      return CalibrationResult::unsafe_state;
    }
    for (unsigned bit = 0; bit < 8; ++bit) {
      if (!mailbox(YPCB_CAL_MB_BIT_WINDOWS + bit, &report->bit_windows[bit])
          || !mailbox(YPCB_CAL_MB_BIT_COUNTS + bit, &report->bit_counts[bit])
          || !mailbox(YPCB_CAL_MB_BIT_MASKS + bit, &report->bit_masks[bit])) {
        return CalibrationResult::io_error;
      }
      const uint32_t value = report->bit_windows[bit], count = report->bit_counts[bit];
      if (count > 256) return CalibrationResult::unsafe_state;
      if ((report->diagnostic_valid_bits >> bit) & 1) {
        const unsigned slip = value & 255, first = (value >> 8) & 255;
        const unsigned last = (value >> 16) & 255, center = value >> 24;
        if (slip >= 8 || first >= last || last >= 32 || center != (first + last) / 2
            || count < last - first + 1) return CalibrationResult::unsafe_state;
        const uint32_t mask = uint32_t((uint64_t(1) << (last - first + 1)) - 1) << first;
        if ((report->bit_masks[bit] & mask) != mask) return CalibrationResult::unsafe_state;
      } else if (value || report->bit_masks[bit]) {
        return CalibrationResult::unsafe_state;
      }
    }
  }
  if (report->state == YPCB_CAL_FAILED) return CalibrationResult::failed;
  if (report->error || report->failed_lane != 9 || report->probes != YPCB_CAL_PROBES
      || report->max_row_cycles == 0 || report->max_row_cycles > (uint64_t(cfg::sys_clock_hz) * 351 / 10000000)
      || report->cycles == 0 || report->cycles > 30ull * cfg::sys_clock_hz) {
    return CalibrationResult::unsafe_state;
  }
  for (unsigned lane = 0; lane < report->lanes.size(); ++lane) {
    const uint32_t value = report->lanes[lane];
    const unsigned slip = value & 255, first = (value >> 8) & 255;
    const unsigned last = (value >> 16) & 255, center = value >> 24;
    if (slip >= 8 || first >= last || last >= 32 || center != (first + last) / 2) {
      return CalibrationResult::unsafe_state;
    }
    const uint32_t mask = uint32_t((uint64_t(1) << (last - first + 1)) - 1) << first;
    if ((report->scans[lane * 8 + slip] & mask) != mask) return CalibrationResult::unsafe_state;
  }
  for (const auto& item : {std::pair{cfg::ddrctrl_init_done, 1u}, {cfg::ddrctrl_init_error, 0u},
                           {cfg::ecc_axi_0_enable, 1u}, {cfg::sdram_dfii_control, cfg::dfii_control_sel}}) {
    uint32_t value;
    if (mmio.read32(base + item.first, &value)) return CalibrationResult::io_error;
    if (value != item.second) return CalibrationResult::unsafe_state;
  }
  if (mmio.read32(0x3008, &board)) return CalibrationResult::io_error;
  return (board & board_errors) == 0 && (board & 15) == 10
      ? CalibrationResult::success : CalibrationResult::unsafe_state;
}

}
