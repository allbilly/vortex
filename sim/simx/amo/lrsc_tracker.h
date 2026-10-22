#pragma once

#include <cstdint>
#include <vector>

namespace vortex {

class LrscTracker {
public:
  explicit LrscTracker(uint32_t harts) : entries_(harts) {}

  bool matches(uint32_t hart, uint64_t address) const {
    const auto& entry = entries_.at(hart);
    return entry.valid && entry.address == address;
  }

  void reserve(uint32_t hart, uint64_t address) {
    entries_.at(hart) = {true, address};
  }

  void clear(uint32_t hart) {
    entries_.at(hart).valid = false;
  }

  void reset() {
    for (auto& entry : entries_) {
      entry.valid = false;
    }
  }

private:
  struct Entry {
    bool valid = false;
    uint64_t address = 0;
  };
  std::vector<Entry> entries_;
};

} // namespace vortex
