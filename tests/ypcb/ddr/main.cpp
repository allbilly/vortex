// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <ypcb_ddr.h>
#include <ypcb_ddr_config.h>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>

using namespace vortex::ypcb;
namespace cfg = vortex::ypcb::ddr_config;

static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

class CsrOracle : public Mmio {
public:
  struct State {
    std::array<uint32_t, 2048> registers{};
    std::array<unsigned, 9> delay{}, bitslip{};
    std::array<std::array<uint32_t, 5>, 4> memory{}, capture{};
    std::vector<std::pair<uint32_t, uint32_t>> modes;
    unsigned reads = 0, writes = 0, activates = 0, precharges = 0;
    bool active = false;
  };
  std::array<State, 2> banks;
  unsigned accesses = 0;
  unsigned forced_status = 0;
  int broken_lane = -1;
  bool no_windows = false;
  bool persistent_error = false;
  bool reject_ecc_enable = false;
  uint32_t fail_once = 0;

  static unsigned first(unsigned lane) {
    return 2 + lane * 2;
  }
  static unsigned last(unsigned lane) {
    return first(lane) + 3 + lane % 5;
  }
  static unsigned slip(unsigned lane, unsigned bank) {
    return (lane * 3 + bank) % 8;
  }

  int read32(uint32_t offset, uint32_t* value) override {
    ++accesses;
    if (persistent_error) {
      return -1;
    }
    if (offset == 0x3000) {
      *value = 0x56595043;
      return 0;
    }
    if (offset == 0x3004) {
      *value = 2;
      return 0;
    }
    if (offset == 0x3008) {
      *value = 0x8002 | forced_status;
      for (unsigned bank = 1; bank < 2; ++bank) {
        *value |= banks[bank].registers[cfg::ddrctrl_init_done / 4] << (2 + bank);
        *value |= banks[bank].registers[cfg::ddrctrl_init_error / 4] << (4 + bank);
      }
      return 0;
    }
    require(offset >= 0x4000 && offset < 0x8000 && offset % 4 == 0,
            "DDR read escaped its aligned BAR windows");
    const unsigned bank = (offset - 0x4000) / 0x2000;
    const uint32_t local = (offset - 0x4000) % 0x2000;
    for (unsigned phase = 0; phase < 4; ++phase) {
      if (local >= cfg::phases[phase].rddata && local < cfg::phases[phase].rddata + 20) {
        *value = banks[bank].capture[phase][(local - cfg::phases[phase].rddata) / 4];
        return 0;
      }
    }
    *value = banks[bank].registers[local / 4];
    return 0;
  }

  int write32(uint32_t offset, uint32_t value) override {
    ++accesses;
    if (persistent_error || offset == fail_once) {
      fail_once = 0;
      return -1;
    }
    require(offset >= 0x4000 && offset < 0x8000 && offset % 4 == 0,
            "DDR write escaped its aligned BAR windows");
    const unsigned bank = (offset - 0x4000) / 0x2000;
    const uint32_t local = (offset - 0x4000) % 0x2000;
    auto& state = banks[bank];
    const uint32_t selected = state.registers[cfg::ddrphy_dly_sel / 4];
    if (local == cfg::ecc_axi_0_enable && value == 1 && reject_ecc_enable) {
      return 0;
    }
    state.registers[local / 4] = value;
    for (unsigned lane = 0; lane < 9; ++lane) {
      if (!((selected >> lane) & 1)) {
        continue;
      }
      if (local == cfg::ddrphy_rdly_dq_rst) {
        state.delay[lane] = 0;
      } else if (local == cfg::ddrphy_rdly_dq_inc) {
        state.delay[lane] = (state.delay[lane] + 1) % 32;
      } else if (local == cfg::ddrphy_rdly_dq_bitslip_rst) {
        state.bitslip[lane] = 0;
      } else if (local == cfg::ddrphy_rdly_dq_bitslip) {
        state.bitslip[lane] = (state.bitslip[lane] + 1) % 8;
      }
    }
    for (unsigned phase = 0; phase < 4; ++phase) {
      if (local == cfg::phases[phase].issue && value == 1) {
        execute(bank, phase);
      }
    }
    if (local == cfg::ddrctrl_init_done && value == 1) {
      require(!state.active && state.registers[cfg::sdram_dfii_control / 4] == 1
              && state.registers[cfg::ecc_axi_0_enable / 4] == 1,
              "Initialization was published before controller/ECC handoff");
    }
    return 0;
  }

private:
  void execute(unsigned bank, unsigned phase) {
    auto& state = banks[bank];
    const auto& ports = cfg::phases[phase];
    const uint32_t command = state.registers[ports.command / 4];
    if (command == 15) {
      require(phase == 0, "Mode register used the wrong phase");
      state.modes.emplace_back(state.registers[ports.bank / 4], state.registers[ports.address / 4]);
    } else if (command == 9) {
      require(!state.active && phase == 0 && state.registers[ports.address / 4] == 0
              && state.registers[ports.bank / 4] == 0, "Probe activated an unexpected row/bank");
      state.active = true;
      ++state.activates;
    } else if (command == 23) {
      require(state.active && phase == 3 && state.registers[ports.address / 4] == 0
              && state.registers[ports.bank / 4] == 0, "Probe write used the wrong phase/column");
      for (unsigned p = 0; p < 4; ++p) {
        for (unsigned word = 0; word < 5; ++word) {
          state.memory[p][word] = state.registers[(cfg::phases[p].wrdata / 4) + word];
        }
        require((state.memory[p][0] & 0xffff0000u) == 0, "144-bit CSR padding differs");
      }
      ++state.writes;
    } else if (command == 37) {
      require(state.active && phase == 3, "Probe read used the wrong phase");
      state.capture = state.memory;
      for (unsigned lane = 0; lane < 9; ++lane) {
        const bool passes = !no_windows && int(lane) != broken_lane
          && state.bitslip[lane] == slip(lane, bank)
          && state.delay[lane] >= first(lane) && state.delay[lane] <= last(lane);
        if (!passes) {
          const unsigned byte = lane + (bank == 0 ? 0 : 9);
          for (unsigned p = 0; p < 4; ++p) {
            state.capture[p][4 - byte / 4] ^= 1u << ((byte % 4) * 8);
          }
        }
      }
      ++state.reads;
    } else if (command == 11) {
      require(state.active && phase == 0 && state.registers[ports.address / 4] == 0,
              "Probe precharge differed");
      state.active = false;
      ++state.precharges;
    } else {
      require(command == 3 && phase == 0 && state.registers[ports.address / 4] == 0x400,
              "Unexpected generated initialization command");
    }
  }
};

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
