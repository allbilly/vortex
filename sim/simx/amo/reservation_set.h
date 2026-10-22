#pragma once

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <vector>

namespace vortex {

class ReservationSet {
public:
  ReservationSet(uint32_t size, uint32_t credits)
      : credits_(credits) {
    assert(size >= 2);
    uint32_t depth = 2;
    while (depth < size) {
      depth <<= 1;
    }
    entries_.resize(depth);
  }

  bool check(uint32_t hart, uint64_t word) const {
    const auto& entry = entries_[word & (entries_.size() - 1)];
    return entry.valid && entry.word == word && entry.hart == hart;
  }

  void reserve(uint32_t hart, uint64_t word) {
    auto& entry = entries_[word & (entries_.size() - 1)];
    if (entry.valid && entry.hart != hart && entry.credits) {
      --entry.credits;
      return;
    }
    entry = {true, hart, word, credits_};
  }

  void clear(uint32_t hart, uint64_t word) {
    if (check(hart, word)) {
      invalidate(word);
    }
  }

  void invalidate(uint64_t word) {
    auto& entry = entries_[word & (entries_.size() - 1)];
    if (entry.valid && entry.word == word) {
      entry = {};
    }
  }

  void reset() {
    std::fill(entries_.begin(), entries_.end(), Entry{});
  }

private:
  struct Entry {
    bool valid = false;
    uint32_t hart = 0;
    uint64_t word = 0;
    uint32_t credits = 0;
  };

  uint32_t credits_;
  std::vector<Entry> entries_;
};

} // namespace vortex
