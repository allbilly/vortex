// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <ypcb_ddr.h>
#include <ypcb_ddr_config.h>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>
#include "oracle.h"

using namespace vortex::ypcb;
namespace cfg = vortex::ypcb::ddr_config;

using namespace ypcb_test;

static void window_tests() {
  unsigned cases = 0;
  for (unsigned slip = 0; slip < 8; ++slip) {
    for (unsigned first = 0; first < 32; ++first) {
      for (unsigned last = first; last < 32; ++last) {
        ReadScan scan{};
        for (unsigned tap = first; tap <= last; ++tap) {
          scan[slip] |= 1u << tap;
        }
        ReadWindow window;
        const bool valid = select_read_window(scan, &window);
        require(valid == (last > first), "Isolated taps or adjacent passes were misclassified");
        if (valid) {
          require(window.bitslip == slip && window.first == first && window.last == last
                  && window.center == (first + last) / 2, "Read window center/extent differs");
        }
        ++cases;
      }
    }
  }
  ReadScan scan{};
  ReadWindow window;
  require(!select_read_window(scan, &window) && !select_read_window(scan, nullptr),
          "Empty scan or null output accepted");
  scan[1] = 0x00000ff0;
  scan[3] = 0x00ff0000;
  require(select_read_window(scan, &window) && window.bitslip == 1 && window.center == 7,
          "Equal windows did not choose the first candidate");
  scan[7] = 0xffffffff;
  require(select_read_window(scan, &window) && window.bitslip == 7 && window.center == 15,
          "Largest full-width window was not selected");
  std::printf("PASSED: %u read-window extent/center cases plus no-eye, isolated-tap, ties and full-width checks\n", cases);
}

int main() {
  window_tests();
  CsrOracle oracle;
  for (unsigned bank = 1; bank < 2; ++bank) {
    Ddr ddr(oracle, bank);
    DdrReport report;
    require(ddr.initialize(&report) == DdrResult::success && report.calibrated,
            "Host training algorithm failed on known CSR responses");
    auto& state = oracle.banks[bank];
    for (unsigned lane = 0; lane < 9; ++lane) {
      const auto& w = report.lanes[lane];
      require(w.bitslip == CsrOracle::slip(lane, bank) && w.first == CsrOracle::first(lane)
              && w.last == CsrOracle::last(lane) && w.center == (w.first + w.last) / 2,
              "One of nine lane windows differs");
      require(state.delay[lane] == w.center && state.bitslip[lane] == w.bitslip,
              "Selected center was not programmed");
    }
    require(report.probes == 6942 && state.reads == report.probes && state.writes == report.probes
            && state.activates == report.probes && state.precharges == report.probes,
            "Probe sequence/count differs");
    const std::vector<std::pair<uint32_t, uint32_t>> modes = {{2, 0x200}, {3, 0}, {1, 6}, {0, 0x920}};
    require(state.modes == modes, "DDR3-800 CL6/CWL5 mode register sequence differs");
    require(ddr.initialize(&report) == DdrResult::unsafe_state, "Live DDR was retrained");
  }
  for (int lane : {0, 8}) {
    CsrOracle failing;
    failing.broken_lane = lane;
    Ddr ddr(failing, 1);
    DdrReport report;
    require(ddr.initialize(&report) == DdrResult::training_failed && !report.calibrated
            && report.failed_lane == unsigned(lane) && report.cleanup_complete,
            "Failed lane was ignored or left initialized");
    require(failing.banks[1].registers[cfg::ddrctrl_init_done / 4] == 0
            && failing.banks[1].registers[cfg::ddrctrl_init_error / 4] == 1
            && failing.banks[1].registers[cfg::sdram_dfii_control / 4] == cfg::dfii_control_odt,
            "Failed calibration did not hold DDR reset");
  }
  CsrOracle unsafe;
  unsafe.forced_status = 1u << 9;
  Ddr blocked(unsafe, 1);
  DdrReport report;
  require(blocked.initialize(&report) == DdrResult::unsafe_state
          && unsafe.banks[1].modes.empty(), "Startup readiness guard was ignored");
  CsrOracle rejected;
  rejected.reject_ecc_enable = true;
  Ddr rejected_ddr(rejected, 1);
  require(rejected_ddr.initialize(&report) == DdrResult::io_error && !report.calibrated
          && report.cleanup_complete
          && rejected.banks[1].registers[cfg::ddrctrl_init_done / 4] == 0,
          "ECC-enable readback mismatch published initialization success");
  CsrOracle io;
  io.fail_once = 0x6000 + cfg::sdram_dfii_pi0_wrdata;
  Ddr io_ddr(io, 1);
  require(io_ddr.initialize(&report) == DdrResult::io_error && report.cleanup_complete,
          "CSR I/O failure was lost");
  require(io_ddr.initialize(&report) == DdrResult::unsafe_state, "Failed object retried initialization");
  CsrOracle timed;
  Ddr timeout(timed, 1, std::chrono::milliseconds(1));
  require(timeout.initialize(&report) == DdrResult::timeout && !report.calibrated
          && timed.banks[1].registers[cfg::ddrctrl_init_done / 4] == 0,
          "Deadline marked DDR initialized");
  CsrOracle lost;
  lost.persistent_error = true;
  Ddr lost_ddr(lost, 1);
  require(lost_ddr.initialize(&report) == DdrResult::io_error, "Startup I/O failure was lost");
  require(Ddr(lost, 0).initialize(&report) == DdrResult::invalid,
          "Inactive CH0 accessed hardware");
  require(Ddr(lost, 2).initialize(&report) == DdrResult::invalid,
          "Invalid DDR bank accessed hardware");
  std::puts("PASSED: host DDR algorithm with explicit synthetic CSR/data oracle, CH1, positive/negative edges, all nine lanes, ECC-lane failure, generated JEDEC sequence, CSR packing, ECC readback, handoff, errors and timeout; no physical PHY/calibration claim");
}
