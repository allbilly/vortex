// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once

#include "ypcb_transport.h"
#include <array>

namespace vortex::ypcb {

struct ReadWindow {
  unsigned bitslip = 0;
  unsigned first = 0;
  unsigned last = 0;
  unsigned center = 0;
};

using ReadScan = std::array<uint32_t, 8>;
bool select_read_window(const ReadScan& scan, ReadWindow* window);

enum class DdrResult { success, invalid, unsafe_state, io_error, timeout, training_failed };

struct DdrReport {
  std::array<ReadWindow, 9> lanes{};
  std::array<ReadScan, 9> scans{};
  uint64_t probes = 0;
  unsigned failed_lane = 9;
  bool calibrated = false;
  bool cleanup_complete = false;
};

class Ddr {
public:
  Ddr(Mmio& mmio, unsigned bank, std::chrono::milliseconds timeout = std::chrono::minutes(5));
  DdrResult initialize(DdrReport* report);

private:
  DdrResult write(uint32_t offset, uint32_t value);
  DdrResult read(uint32_t offset, uint32_t* value);
  DdrResult wait(unsigned cycles);
  DdrResult command(unsigned phase, uint32_t value);
  DdrResult configure_lane(unsigned lane, unsigned bitslip, unsigned delay);
  DdrResult probe(uint32_t seed, std::array<unsigned, 9>* errors);
  DdrResult finish_failure(DdrResult result, DdrReport* report);
  DdrResult train(DdrReport* report);

  Mmio& mmio_;
  unsigned bank_;
  uint32_t base_;
  std::chrono::milliseconds timeout_;
  std::chrono::steady_clock::time_point deadline_;
  std::mutex mutex_;
  bool attempted_ = false;
};

}
