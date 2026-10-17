// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once
#include "ypcb_transport.h"

namespace vortex::ypcb {
class Jtag final : public Mmio {
public:
  ~Jtag() override;
  int connect(unsigned port);
  int read32(uint32_t offset, uint32_t* value) override;
  int write32(uint32_t offset, uint32_t value) override;
private:
  int transact(bool write, uint32_t offset, uint32_t* value);
  int socket_ = -1;
  bool poisoned_ = false;
  std::mutex mutex_;
};
}
