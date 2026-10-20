// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once
#include "ypcb_transport.h"
#include <string>

namespace vortex::ypcb {
class Jtag final : public Mmio {
public:
  ~Jtag() override;
  int connect(unsigned port);
  int read32(uint32_t offset, uint32_t* value) override;
  int write32(uint32_t offset, uint32_t value) override;
  int read_words(uint32_t offset, uint32_t* values, size_t count) override;
  int write_words(uint32_t offset, const uint32_t* values, size_t count) override;
private:
  int transact(bool write, uint32_t offset, uint32_t* value);
  int exchange(const std::string& command, uint32_t* values, size_t count);
  int socket_ = -1;
  bool poisoned_ = false;
  std::mutex mutex_;
};
}
