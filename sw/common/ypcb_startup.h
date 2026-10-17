// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once

#include "ypcb_transport.h"

namespace vortex::ypcb {

enum class StartupResult { success, invalid, unsafe_state, io_error, timeout, failed };

struct StartupReport {
  uint32_t initial_status = 0;
  uint32_t final_status = 0;
  unsigned polls = 0;
  bool scrub_started = false;
  bool reused_ready = false;
};

class Startup {
public:
  Startup(Mmio& mmio, std::chrono::milliseconds timeout = std::chrono::minutes(10));
  StartupResult initialize(StartupReport* report);

private:
  Mmio& mmio_;
  std::chrono::milliseconds timeout_;
  std::mutex mutex_;
  bool poisoned_ = false;
};

}
