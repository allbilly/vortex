// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once

#include "ypcb_transport.h"
#include <array>

namespace vortex::ypcb {

enum class WlCalibrationResult { success, invalid, io_error, unsafe_state, timeout, failed };

struct WlCalibrationReport {
  uint32_t firmware_id = 0;
  uint32_t state = 0;
  uint32_t error = 0;
  uint32_t cycles_low32 = 0;
  int32_t phase_start = 0;
  int32_t phase_steps = 0;
  uint32_t phase_window = 0;
  uint32_t phase_points = 0;
  uint32_t selected_point = 0;
  uint32_t first_point = 0;
  uint32_t last_point = 0;
  uint64_t write_slips = 0;
  std::array<uint32_t, 9> read_windows{};
  std::array<int8_t, 72> bit_offsets{};
  std::array<uint32_t, 36> phase_pass_maps{};
};

WlCalibrationResult wait_wl_calibration(Mmio& mmio, WlCalibrationReport* report,
                                      std::chrono::milliseconds timeout = std::chrono::seconds(40));

}
