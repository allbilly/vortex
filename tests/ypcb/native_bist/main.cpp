// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "protocol.h"
#include <ypcb_jtag.h>
#include <ypcb_wl_calibration.h>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fcntl.h>
#include <string>
#include <sys/file.h>
#include <unistd.h>

namespace {
volatile std::sig_atomic_t interrupted = 0;
void interrupt(int signal) { interrupted = signal; }
bool cancelled() { return interrupted != 0; }
void progress(unsigned channel, uint32_t mode) {
  std::printf("BIST START: CH%u mode=%u words=33554432\n", channel, mode);
  std::fflush(stdout);
}
}

int main() {
  static_assert(ypcb_bist::cfg::board_abi == 5 && ypcb_bist::cfg::payload_bytes == 0x100000000ull);
  std::signal(SIGINT, interrupt);
  std::signal(SIGTERM, interrupt);
  try {
    const auto path = std::string("/tmp/vortex-ypcb-") + std::to_string(getuid()) + ".lock";
    const int lease = open(path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (lease < 0 || flock(lease, LOCK_EX | LOCK_NB))
      throw std::runtime_error("Another YPCB runtime owns the device");
    const char* text = std::getenv("VORTEX_YPCB_JTAG_PORT");
    char* end = nullptr;
    const auto port = text ? std::strtoul(text, &end, 10) : 3124;
    if (!port || port > 65535 || (text && (end == text || *end)))
      throw std::runtime_error("Invalid JTAG port");
    vortex::ypcb::Jtag mmio;
    if (mmio.connect(unsigned(port))) throw std::runtime_error("Cannot connect to the JTAG bridge");
    for (unsigned channel = 0; channel < 2; ++channel) {
      vortex::ypcb::WlCalibrationReport report;
      const auto result = vortex::ypcb::wait_wl_calibration(
          mmio, &report, std::chrono::seconds(40), channel);
      std::fprintf(stderr, "BIST CALIBRATION: CH%u result=%u firmware=%08x error=%u state=%u phase=%d window=%u lanes=%u\n",
                   channel, unsigned(result), report.firmware_id, report.error, report.state,
                   report.phase_steps, report.phase_window, report.physical_lanes);
      if (result != vortex::ypcb::WlCalibrationResult::success)
        throw std::runtime_error("Both channel calibrations must pass before native BIST");
    }
    ypcb_bist::Session session(mmio, std::chrono::minutes(2), cancelled, progress);
    const auto results = session.run(1u << 25);
    std::signal(SIGINT, SIG_DFL);
    std::signal(SIGTERM, SIG_DFL);
    if (cancelled()) throw std::runtime_error("Native BIST interrupted before result publication");
    for (const auto& result : results) {
      std::printf("BIST PASS: CH%u mode=%u words=%u payload_bytes=2147483648 raw_bytes=%llu ticks=%u errors=0 lanes=%u\n",
                  result.channel, result.mode, result.words,
                  static_cast<unsigned long long>(uint64_t(result.words) * result.lanes * 8),
                  result.ticks, result.lanes);
    }
    std::puts("PASSED: full 4 GiB payload native BIST, 8 full-channel pattern passes; ECC initialization pending");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "FAILED: %s; interrupted=%d; reload SRAM after a destructive-test failure\n",
                 error.what(), int(interrupted));
    return 1;
  }
}
