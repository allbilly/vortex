// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_host_memory.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <new>

namespace vortex::ypcb {
namespace {
constexpr uint32_t cp_base = 0x1000;
constexpr uint32_t sequence_register = 0x128;
}

HostMemory::HostMemory(Mmio& mmio, Pio& pio) : mmio_(mmio), pio_(pio) {
}

HostMemory::~HostMemory() {
  for (const auto& [address, region] : regions_) {
    allocator_.release(address);
  }
  for (const auto& [address, region] : unstamped_) {
    allocator_.release(address);
  }
  for (const auto& pending : pending_) {
    allocator_.release(pending.address);
  }
}

int HostMemory::read(uint32_t offset, uint32_t* value) {
  if (poisoned_ || value == nullptr || offset >= 0x1000 || (offset & 3)) {
    return -1;
  }
  if (mmio_.read32(cp_base + offset, value) != 0) {
    poisoned_ = true;
    return -1;
  }
  return 0;
}

int HostMemory::write(uint32_t offset, uint32_t value) {
  uint32_t fence;
  if (poisoned_ || offset >= 0x1000 || (offset & 3)) {
    return -1;
  }
  if (mmio_.write32(cp_base + offset, value) != 0
      || read(0x10, &fence) != 0 || fence == 0xffffffff) {
    poisoned_ = true;
    return -1;
  }
  return 0;
}

int HostMemory::initialize() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (initialized_ || poisoned_ || read(sequence_register, &last_seqnum_) != 0
      || last_seqnum_ == 0xffffffff) {
    return -1;
  }
  retired_ = last_seqnum_;
  tail_ = retired_ * 64;
  initialized_ = true;
  return 0;
}

bool HostMemory::owned(uint64_t address) const {
  return std::find(owner_addresses_.begin(), owner_addresses_.end(), address)
      != owner_addresses_.end();
}

int HostMemory::transfer(uint64_t address, Region& region, bool upload) {
  const auto result = upload ? pio_.write(address, region.data.get(), region.size)
                            : pio_.read(address, region.data.get(), region.size);
  if (result != Result::success) {
    std::fprintf(stderr, "[VXDRV] YPCB PIO %s failed: result=%u address=0x%llx bytes=%zu\n",
        upload ? "write" : "read", unsigned(result),
        static_cast<unsigned long long>(address), region.size);
    poisoned_ = true;
    return -1;
  }
  return 0;
}

void HostMemory::collect() {
  auto it = pending_.begin();
  while (it != pending_.end()) {
    if (it->watermark <= retired_) {
      allocator_.release(it->address);
      it = pending_.erase(it);
    } else {
      ++it;
    }
  }
}

int HostMemory::cp_reg_read(uint32_t offset, uint32_t* value) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!initialized_ || read(offset, value) != 0) {
    return -1;
  }
  if (offset == sequence_register) {
    const uint32_t advance = *value - last_seqnum_;
    if (*value == 0xffffffff || advance > 0x7fffffff
        || uint64_t(advance) > tail_ / 64 - retired_) {
      poisoned_ = true;
      return -1;
    }
    last_seqnum_ = *value;
    retired_ += advance;
    collect();
  }
  return 0;
}

int HostMemory::publish(uint64_t tail) {
  if (ring_log2_ < 6 || ring_log2_ > 28 || tail < tail_ || (tail & 63)) {
    return -1;
  }
  const uint64_t ring_size = uint64_t(1) << ring_log2_;
  if (tail / 64 - retired_ > ring_size / 64) {
    return -1;
  }
  auto ring = regions_.find(owner_addresses_[0]);
  auto head = regions_.find(owner_addresses_[1]);
  auto completion = regions_.find(owner_addresses_[2]);
  if (ring == regions_.end() || head == regions_.end() || completion == regions_.end()
      || ring == head || head == completion || ring == completion
      || ring->second.size < ring_size || head->second.size < 64
      || completion->second.size < 128 || (ring->first & (ring_size - 1))) {
    return -1;
  }
  if (!seeded_) {
    if (transfer(ring->first, ring->second, true) != 0
        || transfer(head->first, head->second, true) != 0
        || transfer(completion->first, completion->second, true) != 0) {
      return -1;
    }
    seeded_ = true;
  } else if (tail > tail_) {
    const uint64_t start = tail_ & (ring_size - 1);
    const uint64_t first = std::min(tail - tail_, ring_size - start);
    if (pio_.write(ring->first + start, ring->second.data.get() + start, first)
            != Result::success
        || (tail - tail_ > first && pio_.write(ring->first, ring->second.data.get(),
              tail - tail_ - first) != Result::success)) {
      poisoned_ = true;
      return -1;
    }
  }
  return 0;
}

int HostMemory::cp_reg_write(uint32_t offset, uint32_t value) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!initialized_ || poisoned_) {
    return -1;
  }
  if (offset >= 0x100 && offset <= 0x114 && (offset & 3) == 0 && seeded_) {
    return -1;
  }
  if (offset == 0x118 && (seeded_ || value < 6 || value > 28)) {
    return -1;
  }
  if (offset == 0x124) {
    const uint64_t tail = (uint64_t(value) << 32) | tail_low_;
    if (publish(tail) != 0) {
      return -1;
    }
    // Once publication starts, an uncertain doorbell must never allow reuse.
    if (write(offset, value) != 0) {
      return -1;
    }
    tail_ = tail;
    try {
      pending_.reserve(pending_.size() + unstamped_.size());
    } catch (const std::bad_alloc&) {
      poisoned_ = true;
      return -1;
    }
    for (auto& [address, region] : unstamped_) {
      pending_.push_back(Pending{address, tail / 64, std::move(region)});
    }
    unstamped_.clear();
    collect();
    return 0;
  }
  if (write(offset, value) != 0) {
    return -1;
  }
  if (offset >= 0x100 && offset <= 0x114 && (offset & 3) == 0) {
    const unsigned index = (offset - 0x100) / 8;
    const unsigned shift = (offset & 4) * 8;
    owner_addresses_[index] = (owner_addresses_[index] & ~(uint64_t(0xffffffff) << shift))
                           | (uint64_t(value) << shift);
  } else if (offset == 0x118) {
    ring_log2_ = value;
  } else if (offset == 0x120) {
    tail_low_ = value;
  }
  return 0;
}

int HostMemory::allocate(uint64_t size, void** pointer, uint64_t* address) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!initialized_ || poisoned_ || pointer == nullptr || address == nullptr
      || size == 0 || size > arena_size) {
    return -1;
  }
  const uint64_t aligned = (size + 63) & ~uint64_t(63);
  Region region{std::unique_ptr<uint8_t, Free>(
      static_cast<uint8_t*>(std::aligned_alloc(64, aligned))), aligned};
  if (!region.data || allocator_.allocate(aligned, address) != 0) {
    return -1;
  }
  std::memset(region.data.get(), 0, aligned);
  *pointer = region.data.get();
  try {
    regions_.emplace(*address, std::move(region));
  } catch (const std::bad_alloc&) {
    allocator_.release(*address);
    *pointer = nullptr;
    return -1;
  }
  return 0;
}

int HostMemory::release(uint64_t address) {
  std::lock_guard<std::mutex> lock(mutex_);
  auto it = regions_.find(address);
  if (!initialized_ || poisoned_ || it == regions_.end()) {
    return -1;
  }
  // A batch may still hold unpublished descriptors that name this allocation.
  unstamped_.insert(regions_.extract(it));
  return 0;
}

int HostMemory::push(uint64_t address) {
  std::lock_guard<std::mutex> lock(mutex_);
  auto it = regions_.find(address);
  if (!initialized_ || poisoned_ || it == regions_.end() || owned(address)) {
    return -1;
  }
  return transfer(address, it->second, true);
}

int HostMemory::pull(uint64_t address) {
  std::lock_guard<std::mutex> lock(mutex_);
  auto it = regions_.find(address);
  if (!initialized_ || poisoned_ || it == regions_.end() || owned(address)) {
    return -1;
  }
  return transfer(address, it->second, false);
}

}
