// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_transport.h"
#include <algorithm>
#include <array>
#include <utility>

namespace vortex::ypcb {
namespace {
constexpr uint32_t pio_base = 0x2000;
constexpr uint32_t signature = 0x56595043;
constexpr uint64_t memory_size = 0x80000000ull;
constexpr size_t line_size = 64;
}

Pio::Pio(Mmio& mmio, std::chrono::milliseconds timeout)
  : mmio_(mmio)
  , timeout_(timeout) {
}

Result Pio::read_register(uint32_t offset, uint32_t* value) {
  if (mmio_.read32(pio_base + offset, value) != 0) {
    poisoned_ = true;
    return Result::io_error;
  }
  return Result::success;
}

Result Pio::write_register(uint32_t offset, uint32_t value) {
  if (mmio_.write32(pio_base + offset, value) != 0) {
    poisoned_ = true;
    return Result::io_error;
  }
  return Result::success;
}

Result Pio::initialize() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (poisoned_) {
    return Result::poisoned;
  }
  if (timeout_.count() <= 0) {
    return Result::invalid;
  }
  uint32_t value;
  auto result = read_register(0, &value);
  if (result != Result::success) {
    return result;
  }
  if (value != signature) {
    return Result::invalid;
  }
  result = read_register(4, &value);
  if (result != Result::success) {
    return result;
  }
  if (value & 1) {
    return Result::busy;
  }
  if ((value & 0x30) != 0x20) {
    return Result::unready;
  }
  initialized_ = true;
  return Result::success;
}

Result Pio::complete(std::chrono::steady_clock::time_point deadline) {
  while (std::chrono::steady_clock::now() < deadline) {
    uint32_t status;
    auto result = read_register(4, &status);
    if (result != Result::success) {
      return result;
    }
    if (!(status & 1) && (status & 2)) {
      uint32_t response;
      result = read_register(0x14, &response);
      if (result != Result::success) {
        return result;
      }
      return ((status & 4) || response != 0) ? Result::memory_error : Result::success;
    }
  }
  // A timed-out command can still own the data window and the AXI response.
  poisoned_ = true;
  return Result::timeout;
}

Result Pio::transfer(uint64_t address, uint8_t* data, size_t size, bool write) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (poisoned_) {
    return Result::poisoned;
  }
  if (!initialized_ || address > memory_size || size > memory_size - address
      || (size != 0 && data == nullptr)) {
    return Result::invalid;
  }
  if (size == 0) {
    return Result::success;
  }
  const auto deadline = std::chrono::steady_clock::now() + timeout_;
  while (size != 0) {
    uint32_t status;
    auto result = read_register(4, &status);
    if (result != Result::success) {
      return result;
    }
    if (status & 1) {
      return Result::busy;
    }
    if (!(status & 0x20u)) {
      return Result::unready;
    }
    const auto offset = size_t(address & (line_size - 1));
    const size_t count = std::min(size, line_size - offset);
    const uint64_t mask = count == line_size ? ~uint64_t(0) : ((uint64_t(1) << count) - 1) << offset;
    const std::array<std::pair<uint32_t, uint32_t>, 4> setup = {{
      {8, uint32_t(address & ~uint64_t(line_size - 1))}, {0xc, 0},
      {0x18, uint32_t(mask)}, {0x1c, uint32_t(mask >> 32)},
    }};
    for (const auto& setting : setup) {
      result = write_register(setting.first, setting.second);
      if (result != Result::success) {
        return result;
      }
    }
    if (write) {
      std::array<uint32_t, line_size / 4> words{};
      for (size_t byte = 0; byte < count; ++byte) {
        const size_t position = offset + byte;
        words[position / 4] |= uint32_t(data[byte]) << ((position % 4) * 8);
      }
      for (size_t word = 0; word < words.size(); ++word) {
        result = write_register(0x100 + uint32_t(word * 4), words[word]);
        if (result != Result::success) {
          return result;
        }
      }
    }
    if (std::chrono::steady_clock::now() >= deadline) {
      return Result::timeout;
    }
    result = write_register(0x10, write ? 2 : 1);
    if (result != Result::success) {
      return result;
    }
    result = complete(deadline);
    if (result != Result::success) {
      return result;
    }
    if (!write) {
      std::array<uint32_t, line_size / 4> words;
      for (size_t word = 0; word < words.size(); ++word) {
        result = read_register(0x100 + uint32_t(word * 4), &words[word]);
        if (result != Result::success) {
          return result;
        }
      }
      for (size_t byte = 0; byte < count; ++byte) {
        const size_t position = offset + byte;
        data[byte] = uint8_t(words[position / 4] >> ((position % 4) * 8));
      }
    }
    address += count;
    data += count;
    size -= count;
  }
  return Result::success;
}

Result Pio::read(uint64_t address, void* data, size_t size) {
  return transfer(address, static_cast<uint8_t*>(data), size, false);
}

Result Pio::write(uint64_t address, const void* data, size_t size) {
  return transfer(address, const_cast<uint8_t*>(static_cast<const uint8_t*>(data)), size, true);
}

}
