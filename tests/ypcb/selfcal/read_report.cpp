// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <ypcb_calibration.h>
#include <ypcb_jtag.h>
#include <cstdio>
#include <cstdlib>

int main(int argc, char** argv) {
  if (argc != 2) {
    return 2;
  }
  char* end = nullptr;
  const auto port = std::strtoul(argv[1], &end, 10);
  if (!end || *end || port == 0 || port > 65535) {
    return 2;
  }
  vortex::ypcb::Jtag mmio;
  if (mmio.connect(unsigned(port))) {
    return 3;
  }
  vortex::ypcb::CalibrationReport report;
  const auto result = vortex::ypcb::wait_calibration(mmio, &report);
  if (result != vortex::ypcb::CalibrationResult::success
      && result != vortex::ypcb::CalibrationResult::failed) {
    std::fprintf(stderr, "Calibration report was not valid: result=%u\n", unsigned(result));
    return 4;
  }
  std::printf("{\"result\":%u,\"firmware_id\":%u,\"state\":%u,\"error\":%u,\"failed_lane\":%u,"
              "\"probes\":%u,\"max_row_cycles\":%u,\"cycles\":%llu,\"write_slips\":%u,\"has_bit_diagnostics\":%s,"
              "\"diagnostic_lane\":%u,\"valid_bits\":%u,\"bit_windows\":[",
              unsigned(result), report.firmware_id, report.state, report.error, report.failed_lane,
              report.probes, report.max_row_cycles, static_cast<unsigned long long>(report.cycles), report.write_slips,
              report.has_bit_diagnostics ? "true" : "false", report.diagnostic_lane, report.diagnostic_valid_bits);
  for (unsigned bit = 0; bit < 8; ++bit) {
    std::printf("%s%u", bit ? "," : "", report.bit_windows[bit]);
  }
  std::puts("]}");
}
