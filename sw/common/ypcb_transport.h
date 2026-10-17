// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace vortex::ypcb {

class Mmio {
public:
  virtual ~Mmio() = default;
  virtual int read32(uint32_t offset, uint32_t* value) = 0;
  virtual int write32(uint32_t offset, uint32_t value) = 0;
};

enum class Result { success, invalid, io_error, busy, unready, memory_error, timeout, poisoned };

class Pio {
public:
  explicit Pio(Mmio& mmio, std::chrono::milliseconds timeout = std::chrono::seconds(30));
  Result initialize();
  Result read(uint64_t address, void* data, size_t size);
  Result write(uint64_t address, const void* data, size_t size);

private:
  Result transfer(uint64_t address, uint8_t* data, size_t size, bool write);
  Result read_register(uint32_t offset, uint32_t* value);
  Result write_register(uint32_t offset, uint32_t value);
  Result complete(std::chrono::steady_clock::time_point deadline);

  Mmio& mmio_;
  std::chrono::milliseconds timeout_;
  std::mutex mutex_;
  bool initialized_ = false;
  bool poisoned_ = false;
};

}
