// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <ypcb_ddr.h>
#include <ypcb_calibration.h>
#include <ypcb_calibration_abi.h>
#include <calibrate.h>
#include "../ddr/oracle.h"

using namespace vortex::ypcb;
using namespace ypcb_test;

namespace {
CsrOracle* active;
uint64_t ticks;
uint32_t extra_row_cycles;
bool expire;
std::array<uint32_t, 128> mailbox;

class CompletionOracle : public CsrOracle {
public:
  std::array<uint32_t, 128> result{};
  uint32_t cpu_status = 0x5ca10018;
  uint32_t version = 3;
  unsigned pointer = 0, writes = 0;

  int read32(uint32_t offset, uint32_t* value) override {
    if (offset == 0x3004) *value = version;
    else if (offset == 0x6000 + cfg::ddrctrl_selfcal_status) *value = cpu_status;
    else if (offset == 0x6000 + cfg::ddrctrl_selfcal_state) *value = result[YPCB_CAL_MB_STATE];
    else if (offset == 0x6000 + cfg::ddrctrl_selfcal_mbox_dat) *value = result[pointer];
    else return CsrOracle::read32(offset, value);
    return 0;
  }

  int write32(uint32_t offset, uint32_t value) override {
    require(offset == 0x6000 + cfg::ddrctrl_selfcal_mbox_adr && value < result.size(),
            "Runtime attempted host-driven DDR training");
    pointer = value;
    ++writes;
    return 0;
  }
};

void access_time() {
  ticks += 8;
  if (active->banks[1].active) {
    ticks += extra_row_cycles;
  }
  if (expire) {
    ticks += 4000000000ull;
  }
}

uint32_t run(CsrOracle& oracle, uint32_t row_cycles = 0, bool timeout = false) {
  active = &oracle;
  ticks = 0;
  extra_row_cycles = row_cycles;
  expire = timeout;
  mailbox.fill(0);
  return ypcb_calibrate();
}
}

extern "C" uint32_t cal_read(uint32_t offset) {
  access_time();
  uint32_t value;
  require(active->read32(0x6000 + offset, &value) == 0, "Firmware read failed");
  return value;
}

extern "C" void cal_write(uint32_t offset, uint32_t value) {
  access_time();
  require(active->write32(0x6000 + offset, value) == 0, "Firmware write failed");
}

extern "C" uint64_t cal_now() {
  return ticks;
}

extern "C" void cal_wait(uint32_t cycles) {
  ticks += cycles;
}

extern "C" void cal_mailbox(uint32_t index, uint32_t value) {
  require(index < mailbox.size(), "Firmware mailbox out of bounds");
  mailbox[index] = value;
}

int main() {
  unsigned cases = 0;
  for (unsigned slip = 0; slip < 8; ++slip) {
    for (unsigned first = 0; first < 32; ++first) {
      for (unsigned last = first; last < 32; ++last) {
        ReadScan scan{};
        for (unsigned tap = first; tap <= last; ++tap) {
          scan[slip] |= 1u << tap;
        }
        ReadWindow reference;
        window actual{};
        const bool expected = select_read_window(scan, &reference);
        require(bool(ypcb_cal_select_window(scan.data(), &actual)) == expected, "Firmware window acceptance differs");
        if (expected) {
          require(actual.slip == reference.bitslip && actual.first == reference.first
                  && actual.last == reference.last && actual.center == reference.center,
                  "Firmware window differs from native oracle");
        }
        ++cases;
      }
    }
  }
  CsrOracle oracle;
  require(run(oracle) == 0, "Firmware failed known PHY responses");
  require(mailbox[YPCB_CAL_MB_MAGIC] == YPCB_CAL_MAGIC
          && mailbox[YPCB_CAL_MB_STATE] == YPCB_CAL_READY
          && mailbox[YPCB_CAL_MB_PROBES] == 6942
          && mailbox[YPCB_CAL_MB_FAILED_LANE] == 9, "Firmware completion report differs");
  for (unsigned lane = 0; lane < 9; ++lane) {
    const auto value = mailbox[YPCB_CAL_MB_LANES + lane];
    require((value & 255) == CsrOracle::slip(lane, 1)
            && ((value >> 8) & 255) == CsrOracle::first(lane)
            && ((value >> 16) & 255) == CsrOracle::last(lane)
            && (value >> 24) == (CsrOracle::first(lane) + CsrOracle::last(lane)) / 2,
            "Firmware lane report differs");
  }
  CompletionOracle completion;
  completion.banks = oracle.banks;
  completion.result = mailbox;
  completion.result[YPCB_CAL_MB_FIRMWARE] = cfg::calibration_firmware_id;
  CalibrationReport report;
  require(wait_calibration(completion, &report) == CalibrationResult::success,
          "Runtime rejected a valid local calibration");
  require(report.probes == 6942 && completion.writes == 97 && !report.has_bit_diagnostics,
          "Runtime did not read the complete local calibration report");
  auto reject = [&](CompletionOracle changed, const char* message) {
    require(wait_calibration(changed, &report) == CalibrationResult::unsafe_state, message);
  };
  auto changed = completion;
  changed.version = 2;
  reject(changed, "Runtime accepted a host-calibrated ABI 2 image");
  changed = completion;
  changed.cpu_status |= 1;
  reject(changed, "Runtime accepted a held calibration CPU");
  changed = completion;
  changed.cpu_status |= 32;
  reject(changed, "Runtime accepted a calibration CPU bus fault");
  changed = completion;
  changed.result[YPCB_CAL_MB_FIRMWARE] ^= 1;
  reject(changed, "Runtime accepted mismatched firmware");
  changed = completion;
  changed.result[YPCB_CAL_MB_DIAG_MAGIC] = 1;
  reject(changed, "Runtime accepted invalid bit diagnostic magic");
  changed = completion;
  changed.result[YPCB_CAL_MB_MAX_ROW_CYCLES] = 3511;
  reject(changed, "Runtime accepted excessive open-row timing");
  changed = completion;
  changed.banks[1].registers[cfg::ecc_axi_0_enable / 4] = 0;
  reject(changed, "Runtime accepted disabled ECC");
  changed = completion;
  changed.result[YPCB_CAL_MB_STATE] = YPCB_CAL_FAILED;
  changed.result[YPCB_CAL_MB_ERROR] = 2;
  require(wait_calibration(changed, &report) == CalibrationResult::failed,
          "Runtime ignored failed local calibration");
  changed = completion;
  changed.result[YPCB_CAL_MB_STATE] = YPCB_CAL_RUNNING;
  require(wait_calibration(changed, &report, std::chrono::milliseconds(1)) == CalibrationResult::timeout,
          "Runtime ignored local calibration timeout");
  for (int lane : {0, 8}) {
    CsrOracle bad;
    bad.broken_lane = lane;
    require(run(bad) == 2 && mailbox[YPCB_CAL_MB_FAILED_LANE] == unsigned(lane), "Firmware ignored a failed lane");
    require(bad.banks[1].registers[cfg::ddrctrl_init_done / 4] == 0
            && bad.banks[1].registers[cfg::ddrctrl_init_error / 4] == 1
            && bad.banks[1].registers[cfg::sdram_dfii_control / 4] == cfg::dfii_control_odt,
            "Firmware failure cleanup differs");
  }
  unsigned diagnostic_cases = 0;
  CompletionOracle diagnostic_completion;
  for (unsigned lane : {0u, 8u}) {
    for (unsigned bit = 0; bit < 8; ++bit) {
      for (int offset : {-2, 2}) {
        CsrOracle shifted;
        shifted.read_bit_offset[lane][bit] = offset;
        require(run(shifted) == 2 && mailbox[YPCB_CAL_MB_FAILED_LANE] == lane,
                "Firmware accepted a byte with inconsistent bit framing");
        require(mailbox[YPCB_CAL_MB_DIAG_MAGIC] == YPCB_CAL_DIAG_MAGIC
                && mailbox[YPCB_CAL_MB_DIAG_LANE] == lane
                && mailbox[YPCB_CAL_MB_DIAG_VALID_BITS] == 255
                && mailbox[YPCB_CAL_MB_DIAG_ERROR_AND] == 0
                && mailbox[YPCB_CAL_MB_DIAG_TAPS] == 256,
                "Firmware lost individual read eyes");
        for (unsigned dq = 0; dq < 8; ++dq) {
          const uint32_t w = mailbox[YPCB_CAL_MB_BIT_WINDOWS + dq];
          const unsigned framing = unsigned(int(CsrOracle::slip(lane, 1)) + (dq == bit ? offset : 0)) & 7;
          const unsigned first = CsrOracle::first(lane), last = CsrOracle::last(lane);
          const uint32_t mask = uint32_t((uint64_t(1) << (last - first + 1)) - 1) << first;
          require((w & 255) == framing && ((w >> 8) & 255) == first
                  && ((w >> 16) & 255) == last
                  && mailbox[YPCB_CAL_MB_BIT_COUNTS + dq] == last - first + 1
                  && mailbox[YPCB_CAL_MB_BIT_MASKS + dq] == mask,
                  "Firmware reported the wrong per-bit eye or data packing");
        }
        diagnostic_completion = CompletionOracle{};
        diagnostic_completion.banks = shifted.banks;
        diagnostic_completion.result = mailbox;
        diagnostic_completion.result[YPCB_CAL_MB_FIRMWARE] = cfg::calibration_firmware_id;
        require(wait_calibration(diagnostic_completion, &report) == CalibrationResult::failed
                && report.has_bit_diagnostics && report.diagnostic_lane == lane
                && report.diagnostic_valid_bits == 255 && diagnostic_completion.writes == 121,
                "Runtime lost bit diagnostics or accepted failed training");
        require(shifted.banks[1].registers[cfg::ddrctrl_init_done / 4] == 0
                && shifted.banks[1].registers[cfg::ddrctrl_init_error / 4] == 1,
                "Diagnostic scan published memory readiness");
        ++diagnostic_cases;
      }
    }
  }
  for (unsigned bit = 0; bit < 8; ++bit) {
    CsrOracle bad;
    bad.unreadable_bits[8] = 1u << bit;
    require(run(bad) == 2 && mailbox[YPCB_CAL_MB_DIAG_VALID_BITS] == (255u ^ (1u << bit))
            && mailbox[YPCB_CAL_MB_DIAG_ERROR_AND] == (1u << bit)
            && mailbox[YPCB_CAL_MB_BIT_COUNTS + bit] == 0
            && mailbox[YPCB_CAL_MB_BIT_WINDOWS + bit] == 0,
            "Unusable bit was reported as a framing-only problem");
    ++diagnostic_cases;
  }
  changed = diagnostic_completion;
  changed.result[YPCB_CAL_MB_DIAG_LANE] = 9;
  reject(changed, "Runtime accepted an out-of-range diagnostic lane");
  changed = diagnostic_completion;
  changed.result[YPCB_CAL_MB_DIAG_TAPS] = 255;
  reject(changed, "Runtime accepted an incomplete bit scan");
  changed = diagnostic_completion;
  changed.result[YPCB_CAL_MB_BIT_MASKS] = 0;
  reject(changed, "Runtime accepted a claimed eye without passing taps");
  changed = diagnostic_completion;
  changed.result[YPCB_CAL_MB_BIT_COUNTS] = 257;
  reject(changed, "Runtime accepted an excessive passing-tap count");
  changed = diagnostic_completion;
  changed.result[YPCB_CAL_MB_STATE] = YPCB_CAL_READY;
  reject(changed, "Runtime accepted readiness with failure diagnostics");
  require(run(oracle) == 0 && mailbox[YPCB_CAL_MB_DIAG_MAGIC] == 0,
          "Firmware restart retained stale failure diagnostics");
  CsrOracle rejected;
  rejected.reject_ecc_enable = true;
  require(run(rejected) == 3, "Firmware ignored ECC readback failure");
  CsrOracle timed;
  require(run(timed, 0, true) == 1, "Firmware ignored deadline");
  CsrOracle slow;
  require(run(slow, 1000) == 4, "Firmware ignored open-row timing budget");
  std::printf("PASSED: firmware matches %u window cases and CH1 training, 6942 probes, all nine lanes, ECC, cleanup, timeout and row timing oracle\n", cases);
  std::printf("PASSED: %u per-bit framing/unreadable-bit diagnostic cases, runtime bounds and failure admission\n", diagnostic_cases);
}
