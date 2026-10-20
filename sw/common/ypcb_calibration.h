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
};

CalibrationResult wait_calibration(Mmio& mmio, CalibrationReport* report,
                                  std::chrono::milliseconds timeout = std::chrono::seconds(40));

}
