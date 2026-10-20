// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <ypcb_wl_calibration.h>
#include <ypcb_wl_config.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <fstream>

using namespace vortex::ypcb;
namespace cfg = vortex::ypcb::wl_config;

namespace {
void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "REPORT FAIL: %s\n", message);
    std::exit(1);
  }
}

class Device : public Mmio {
public:
  std::array<uint32_t, 128> mailbox{};
  uint32_t version = 4, status = 10, cpu = 0x5ca10018;
  uint32_t ecc = 1, done = 1, error = 0, control = 1;
  uint32_t pointer = 0;
  bool io_error = false, change_state = false;
  unsigned state_reads = 0;

  int read32(uint32_t address, uint32_t* value) override {
    if (io_error) return -1;
    if (address == 0x3000) *value = 0x56595043;
    else if (address == 0x3004) *value = version;
    else if (address == 0x3008) *value = status;
    else if (address == 0x6000 + cfg::ddrctrl_selfcal_status) *value = cpu;
    else if (address == 0x6000 + cfg::ddrctrl_selfcal_state) {
      *value = mailbox[2] ^ (change_state && state_reads++ ? 1 : 0);
    } else if (address == 0x6000 + cfg::ddrctrl_selfcal_mbox_dat) *value = mailbox[pointer];
    else if (address == 0x6000 + cfg::ecc_axi_0_enable) *value = ecc;
    else if (address == 0x6000 + cfg::ddrctrl_init_done) *value = done;
    else if (address == 0x6000 + cfg::ddrctrl_init_error) *value = error;
    else if (address == 0x6000 + cfg::sdram_dfii_control) *value = control;
    else require(false, "Reader escaped its CSR surface");
    return 0;
  }

  int write32(uint32_t address, uint32_t value) override {
    if (io_error) return -1;
    require(address == 0x6000 + cfg::ddrctrl_selfcal_mbox_adr && value < 128,
            "Reader attempted calibration or escaped its mailbox");
    pointer = value;
    return 0;
  }
};
}

int main(int argc, char** argv) {
  require(argc == 2, "Expected actual firmware mailbox fixture");
  std::ifstream input(argv[1]);
  require(input.good(), "Cannot read mailbox fixture");
  Device device;
  char punctuation;
  input >> punctuation;
  require(punctuation == '[', "Invalid mailbox fixture");
  for (unsigned i = 0; i < 128; ++i) {
    input >> device.mailbox[i] >> punctuation;
    require(input.good() && punctuation == (i == 127 ? ']' : ','), "Invalid mailbox word");
  }
  require(device.mailbox[1] == 0, "Expected host oracle firmware identity");
  device.mailbox[1] = cfg::calibration_firmware_id;
  WlCalibrationReport report;
  require(wait_wl_calibration(device, &report) == WlCalibrationResult::success,
          "Runtime rejected the actual successful calibration mailbox");
  require(report.bit_offsets[8 * 8] == -2 && report.bit_offsets[8 * 8 + 5] == 2,
          "Runtime lost ECC lane bit corrections");
  unsigned cases = 1;
  auto reject = [&](Device changed) {
    require(wait_wl_calibration(changed, &report) == WlCalibrationResult::unsafe_state,
            "Runtime admitted a malformed or unsafe report");
    ++cases;
  };
  for (const auto& mutation : std::array<std::pair<unsigned, uint32_t>, 21>{{
       {0, 0}, {1, 0}, {4, 0}, {16, 2}, {18, 0}, {18, 113u << 16 | 113u},
       {19, 112}, {20, 112}, {21, 1}, {22, 16}, {23, 0}, {23, 3u | 8u << 8},
       {23, 3u | 31u << 16}, {32, 2}, {36, 0x10000}, {37, 0},
       {39, 56}, {17, 56}, {5, 1}, {80, 1}, {43, 1u << 17}}}) {
    auto changed = device;
    changed.mailbox[mutation.first] = mutation.second;
    reject(changed);
  }
  auto changed = device; changed.version = 3; reject(changed);
  changed = device; changed.cpu |= 1; reject(changed);
  changed = device; changed.cpu |= 32; reject(changed);
  changed = device; changed.status |= 1u << 8; reject(changed);
  changed = device; changed.status |= 1u << 11; reject(changed);
  changed = device; changed.ecc = 0; reject(changed);
  changed = device; changed.done = 0; reject(changed);
  changed = device; changed.error = 1; reject(changed);
  changed = device; changed.control = 14; reject(changed);
  changed = device; changed.change_state = true; reject(changed);
  changed = device;
  changed.mailbox[2] = 131;
  changed.mailbox[16] = 1 << 24 | 3 << 16 | 3;
  reject(changed);
  changed = device;
  changed.mailbox[2] = 128 | 3 | 5 << 8;
  changed.mailbox[16] = 1 << 24 | 3 << 16 | 5 << 8 | 3;
  require(wait_wl_calibration(changed, &report) == WlCalibrationResult::failed,
          "Runtime ignored failed clock-phase training");
  changed = device; changed.io_error = true;
  require(wait_wl_calibration(changed, &report) == WlCalibrationResult::io_error, "Lost I/O error");
  changed = device; changed.mailbox[2] = 1;
  require(wait_wl_calibration(changed, &report, std::chrono::milliseconds(1)) == WlCalibrationResult::timeout,
          "Lost calibration deadline");
  std::printf("REPORT PASS: actual firmware mailbox and %u admission cases\n", cases + 3);
}
