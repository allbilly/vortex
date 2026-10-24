// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <ypcb_wl_calibration.h>
#include <ypcb_wl_config.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>

using namespace vortex::ypcb;
namespace cfg = vortex::ypcb::wl_config;

namespace {

void require(bool condition, const std::string& message) {
  if (!condition) {
    std::fprintf(stderr, "CALIBRATION TEST FAIL: %s\n", message.c_str());
    std::exit(1);
  }
}

struct Write {
  uint32_t address;
  uint32_t value;
};

struct Channel {
  uint32_t physical = 0;
  uint32_t base = 0;
  uint32_t lanes = 0;
  uint32_t firmware_id = 0;
  uint32_t status_offset = 0;
  uint32_t state_offset = 0;
  uint32_t mailbox_address_offset = 0;
  uint32_t mailbox_data_offset = 0;
  uint32_t init_done_offset = 0;
  uint32_t init_error_offset = 0;
  uint32_t control_offset = 0;
  uint32_t ecc_offset = 0;
  uint32_t pointer = 0;
  uint32_t cpu_status = 0x5ca10018;
  uint32_t state = 130;
  uint32_t init_done = 1;
  uint32_t init_error = 0;
  uint32_t control = 1;
  uint32_t ecc_enable = 1;
  std::array<uint32_t, 128> mailbox{};
};

void fill_mailbox(Channel& channel) {
  channel.mailbox.fill(0);
  channel.mailbox[0] = cfg::mailbox_magic;
  channel.mailbox[1] = channel.firmware_id;
  channel.mailbox[2] = channel.state;
  channel.mailbox[4] = 123456;
  channel.mailbox[16] = (cfg::phase_stride << 24) | (3u << 16)
                      | (channel.state & 0xffffu & ~128u);
  channel.mailbox[17] = 11;
  channel.mailbox[18] = (113u << 16) | 3u;
  channel.mailbox[19] = (10u << 16) | 11u;
  channel.mailbox[20] = 12;
  channel.mailbox[37] = 0xffff0003u;
  for (uint32_t lane = 0; lane < channel.lanes; ++lane) {
    channel.mailbox[23 + lane] = (12u << 24) | (8u << 16) | 8u;
    channel.mailbox[40 + lane * 4] = (1u << 10) | (1u << 11) | (1u << 12);
  }
}

class MockMmio final : public Mmio {
public:
  uint32_t board_abi = cfg::board_abi;
  uint32_t board_status = cfg::memory_ready_mask | (cfg::memory_ready_mask << 2);
  uint32_t selected_channel = 1;
  unsigned h1_ecc_reads = 0;
  unsigned h1_ecc_reads_during_ch0 = 0;
  unsigned ch0_ecc_aperture_reads = 0;
  bool io_error = false;
  std::vector<uint32_t> reads;
  std::vector<Write> writes;
  Channel ch1;
#if YPCB_WL_DUAL_CHANNEL
  Channel ch0;
#endif

  MockMmio() {
    ch1.physical = 1;
    ch1.base = 0x6000;
    ch1.lanes = cfg::physical_lanes;
    ch1.firmware_id = cfg::calibration_firmware_id;
    ch1.status_offset = cfg::ddrctrl_selfcal_status;
    ch1.state_offset = cfg::ddrctrl_selfcal_state;
    ch1.mailbox_address_offset = cfg::ddrctrl_selfcal_mbox_adr;
    ch1.mailbox_data_offset = cfg::ddrctrl_selfcal_mbox_dat;
    ch1.init_done_offset = cfg::ddrctrl_init_done;
    ch1.init_error_offset = cfg::ddrctrl_init_error;
    ch1.control_offset = cfg::sdram_dfii_control;
    ch1.ecc_offset = cfg::ecc_axi_0_enable;
    fill_mailbox(ch1);
#if YPCB_WL_DUAL_CHANNEL
    ch0.physical = 0;
    ch0.base = 0x4000;
    ch0.lanes = cfg::ch0::physical_lanes;
    ch0.firmware_id = cfg::ch0::calibration_firmware_id;
    ch0.status_offset = cfg::ch0::ddrctrl_selfcal_status;
    ch0.state_offset = cfg::ch0::ddrctrl_selfcal_state;
    ch0.mailbox_address_offset = cfg::ch0::ddrctrl_selfcal_mbox_adr;
    ch0.mailbox_data_offset = cfg::ch0::ddrctrl_selfcal_mbox_dat;
    ch0.init_done_offset = cfg::ch0::ddrctrl_init_done;
    ch0.init_error_offset = cfg::ch0::ddrctrl_init_error;
    ch0.control_offset = cfg::ch0::sdram_dfii_control;
    ch0.ecc_offset = 0;
    fill_mailbox(ch0);
#endif
  }

  void select(uint32_t channel) {
    selected_channel = channel;
    reads.clear();
    writes.clear();
    h1_ecc_reads = 0;
    h1_ecc_reads_during_ch0 = 0;
    ch0_ecc_aperture_reads = 0;
  }

  Channel* selected() {
    if (selected_channel == 1) return &ch1;
#if YPCB_WL_DUAL_CHANNEL
    if (selected_channel == 0) return &ch0;
#endif
    return nullptr;
  }

  int read32(uint32_t address, uint32_t* value) override {
    reads.push_back(address);
    if (io_error) return -1;
    if (address == 0x3000) { *value = 0x56595043; return 0; }
    if (address == 0x3004) { *value = board_abi; return 0; }
    if (address == 0x3008) { *value = board_status; return 0; }

    if (selected_channel == 0 && address == 0x6000 + cfg::ecc_axi_0_enable) {
      ++h1_ecc_reads;
      ++h1_ecc_reads_during_ch0;
      *value = ch1.ecc_enable;
      return 0;
    }
#if YPCB_WL_DUAL_CHANNEL
    if (selected_channel == 0 && address == 0x4000 + cfg::ecc_axi_0_enable) {
      ++ch0_ecc_aperture_reads;
      *value = 0;
      return 0;
    }
#endif

    Channel* channel = selected();
    if (!channel) return -1;
    if (address == channel->base + channel->status_offset) { *value = channel->cpu_status; return 0; }
    if (address == channel->base + channel->state_offset) { *value = channel->state; return 0; }
    if (address == channel->base + channel->mailbox_data_offset) {
      if (channel->pointer >= channel->mailbox.size()) return -1;
      *value = channel->mailbox[channel->pointer];
      return 0;
    }
    if (address == channel->base + channel->init_done_offset) { *value = channel->init_done; return 0; }
    if (address == channel->base + channel->init_error_offset) { *value = channel->init_error; return 0; }
    if (address == channel->base + channel->control_offset) { *value = channel->control; return 0; }
    if (channel->physical == 1 && address == channel->base + channel->ecc_offset) {
      ++h1_ecc_reads;
      *value = channel->ecc_enable;
      return 0;
    }
    return -1;
  }

  int write32(uint32_t address, uint32_t value) override {
    writes.push_back({address, value});
    if (io_error) return -1;
    Channel* channel = selected();
    if (!channel || address != channel->base + channel->mailbox_address_offset || value >= 128) return -1;
    channel->pointer = value;
    return 0;
  }
};

void check_success(uint32_t physical_channel) {
  MockMmio mmio;
  mmio.select(physical_channel);
  WlCalibrationReport report;
  const auto result = wait_wl_calibration(mmio, &report, std::chrono::milliseconds(50), physical_channel);
  const uint32_t expected_lanes = physical_channel == 0 ? 8 : 9;
  const uint32_t expected_firmware = physical_channel == 0
#if YPCB_WL_DUAL_CHANNEL
      ? cfg::ch0::calibration_firmware_id
#else
      ? 0
#endif
      : cfg::calibration_firmware_id;
  require(result == WlCalibrationResult::success, "Generated channel config rejected valid calibration mailbox");
  require(report.physical_channel == physical_channel && report.physical_lanes == expected_lanes,
          "Calibration report used the wrong physical channel or lane count");
  require(report.firmware_id == expected_firmware && report.write_slips == 0
          && report.phase_points == 113 && report.phase_window == 3,
          "Calibration report fields differ from generated-header fixture");
  require(mmio.writes.size() == 128, "Mailbox was not read through all 128 words");
  const auto* channel = physical_channel == 1 ? &mmio.ch1 :
#if YPCB_WL_DUAL_CHANNEL
      &mmio.ch0;
#else
      nullptr;
#endif
  require(channel != nullptr, "Requested channel is not generated by this ABI header");
  for (unsigned i = 0; i < mmio.writes.size(); ++i) {
    require(mmio.writes[i].address == channel->base + channel->mailbox_address_offset
            && mmio.writes[i].value == i, "Mailbox index crossed into the wrong channel");
  }
  for (unsigned lane = 0; lane < expected_lanes; ++lane) {
    require(report.read_windows[lane] == ((12u << 24) | (8u << 16) | 8u),
            "Read-window lane decoding differs");
  }
  if (physical_channel == 0) {
    require(mmio.h1_ecc_reads_during_ch0 == 0 && mmio.ch0_ecc_aperture_reads == 0,
            "CH0 calibration touched an ECC CSR");
    require(std::none_of(mmio.reads.begin(), mmio.reads.end(), [](uint32_t address) {
      return address >= 0x6000 && address < 0x8000;
    }), "CH0 calibration read a CH1-only CSR window");
    require(mmio.h1_ecc_reads == 0, "CH0 calibration counted a CH1 ECC CSR read");
  } else {
    require(mmio.h1_ecc_reads == 1, "CH1 calibration did not verify its ECC enable CSR exactly once");
  }
}

#if YPCB_WL_DUAL_CHANNEL
void reject_mailbox(uint32_t physical_channel, unsigned word, uint32_t value, const char* message) {
  MockMmio mmio;
  mmio.select(physical_channel);
  if (physical_channel == 0) {
#if YPCB_WL_DUAL_CHANNEL
    mmio.ch0.mailbox[word] = value;
#else
    require(false, "CH0 mailbox mutation requested in ABI4 build");
#endif
  } else {
    mmio.ch1.mailbox[word] = value;
  }
  WlCalibrationReport report;
  require(wait_wl_calibration(mmio, &report, std::chrono::milliseconds(50), physical_channel)
          == WlCalibrationResult::unsafe_state, message);
}
#endif

void reject_wrong_firmware(uint32_t physical_channel) {
  MockMmio mmio;
  mmio.select(physical_channel);
  if (physical_channel == 1) {
    mmio.ch1.mailbox[1] ^= 1u;
  } else {
#if YPCB_WL_DUAL_CHANNEL
    mmio.ch0.mailbox[1] = cfg::calibration_firmware_id;
#else
    require(false, "CH0 firmware mutation requested in ABI4 build");
#endif
  }
  WlCalibrationReport report;
  require(wait_wl_calibration(mmio, &report, std::chrono::milliseconds(50), physical_channel)
          == WlCalibrationResult::unsafe_state, "Wrong channel firmware ID was accepted");
}

} // namespace

int main() {
  WlCalibrationReport report;
#if YPCB_WL_DUAL_CHANNEL
  static_assert(cfg::board_abi == 5 && cfg::memory_ready_mask == 3 && cfg::payload_bytes == 4294967296ull);
  static_assert(cfg::ch0::board_abi == 5 && cfg::ch0::physical_lanes == 8 && !cfg::ch0::ecc_enabled);
  check_success(0);
  check_success(1);
  reject_wrong_firmware(0);
  reject_wrong_firmware(1);
  reject_mailbox(0, 31, 1, "CH0 report with unused lane 8 data was accepted");
  reject_mailbox(0, 36, 1, "CH0 report with an extra offset word was accepted");
  reject_mailbox(0, 72, 1, "CH0 report with an extra phase-map word was accepted");
  reject_mailbox(0, 22, 1, "CH0 report with a high write-slip nibble was accepted");
  reject_mailbox(1, 22, 16, "CH1 report with write slips beyond its nine lanes was accepted");
#else
  static_assert(cfg::board_abi == 4 && cfg::memory_ready_mask == 2 && cfg::payload_bytes == 2147483648ull);
  static_assert(cfg::physical_lanes == 9 && cfg::ecc_enabled);
  check_success(1);
  MockMmio unsupported;
  unsupported.select(0);
  require(wait_wl_calibration(unsupported, &report, std::chrono::milliseconds(50), 0)
          == WlCalibrationResult::invalid && unsupported.reads.empty() && unsupported.writes.empty(),
          "ABI4 header admitted CH0 access");
  reject_wrong_firmware(1);
#endif

  MockMmio wrong_abi;
  wrong_abi.select(1);
  wrong_abi.board_abi = cfg::board_abi == 4 ? 5 : 4;
  require(wait_wl_calibration(wrong_abi, &report, std::chrono::milliseconds(50), 1)
          == WlCalibrationResult::unsafe_state, "Calibration accepted a mismatched board ABI");
  std::puts(YPCB_WL_DUAL_CHANNEL
      ? "PASS: ABI5 CH0/CH1 generated calibration configs and CH0 ECC/report bounds"
      : "PASS: ABI4 CH1 generated calibration config and unsupported CH0 guard");
  return 0;
}
