// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once

#include "ypcb_transport.h"
#include <array>

namespace vortex::ypcb {

enum class CalibrationResult { success, invalid, io_error, unsafe_state, timeout, failed };

struct CalibrationReport {
  uint32_t firmware_id = 0;
  uint32_t state = 0;
  uint32_t error = 0;
  uint32_t failed_lane = 9;
  uint32_t probes = 0;
  uint32_t max_row_cycles = 0;
  uint64_t cycles = 0;
  std::array<uint32_t, 9> lanes{};
  std::array<uint32_t, 72> scans{};
  bool has_bit_diagnostics = false;
  uint32_t diagnostic_lane = 9;
  uint32_t diagnostic_valid_bits = 0;
  uint32_t diagnostic_error_or = 0;
  uint32_t diagnostic_error_and = 0;
  uint32_t diagnostic_taps = 0;
  std::array<uint32_t, 8> bit_windows{};
  std::array<uint32_t, 8> bit_counts{};
  std::array<uint32_t, 8> bit_masks{};
};

CalibrationResult wait_calibration(Mmio& mmio, CalibrationReport* report,
                                  std::chrono::milliseconds timeout = std::chrono::seconds(40));

}
