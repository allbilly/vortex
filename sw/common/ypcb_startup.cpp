// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_startup.h"
#include <thread>

namespace vortex::ypcb {
namespace {
constexpr uint32_t status_errors = (3u << 4) | (1u << 8) | (15u << 11);
constexpr uint32_t required_status = 10u;

bool ready(uint32_t status) {
  return (status & 0x7ff) == (10u | (1u << 7) | (2u << 9)) && (status >> 16) == 3;
}
}

Startup::Startup(Mmio& mmio, std::chrono::milliseconds timeout)
  : mmio_(mmio), timeout_(timeout) {
}

StartupResult Startup::initialize(StartupReport* report) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (report == nullptr || timeout_.count() <= 0) {
    return StartupResult::invalid;
  }
  *report = {};
  if (poisoned_) {
    return StartupResult::unsafe_state;
  }
  const auto deadline = std::chrono::steady_clock::now() + timeout_;
  uint32_t signature, version, status;
  if (mmio_.read32(0x3000, &signature) != 0 || mmio_.read32(0x3004, &version) != 0
      || mmio_.read32(0x3008, &status) != 0) {
    return StartupResult::io_error;
  }
  report->initial_status = report->final_status = status;
  if (signature != 0x56595043 || version != 2 || (status & status_errors) != 0
      || (status & required_status) != required_status) {
    return StartupResult::unsafe_state;
  }
  if (ready(status)) {
    report->reused_ready = true;
    return StartupResult::success;
  }
  if ((status >> 16) != 0 || (status & ((1u << 6) | (3u << 9))) != 0) {
    return StartupResult::unsafe_state;
  }
  if (std::chrono::steady_clock::now() >= deadline) {
    return StartupResult::timeout;
  }
  // An uncertain scrub remains owned by the board until a coordinated reset.
  poisoned_ = true;
  if (mmio_.write32(0x3010, 1) != 0) {
    return StartupResult::io_error;
  }
  report->scrub_started = true;
  while (std::chrono::steady_clock::now() < deadline) {
    if (mmio_.read32(0x3008, &status) != 0) {
      return StartupResult::io_error;
    }
    ++report->polls;
    report->final_status = status;
    if ((status & status_errors) != 0 || (status & required_status) != required_status
        || (status >> 16) >= 4) {
      return StartupResult::failed;
    }
    if (ready(status)) {
      poisoned_ = false;
      return StartupResult::success;
    }
    if ((status & (3u << 9)) != 0) {
      return StartupResult::failed;
    }
    std::this_thread::sleep_for(std::chrono::microseconds(50));
  }
  return StartupResult::timeout;
}

}
