// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once

#include "ypcb_transport.h"
#include "mem_alloc.h"
#include <array>
#include <cstdlib>
#include <map>
#include <memory>
#include <vector>

namespace vortex::ypcb {

class HostMemory {
public:
  static constexpr uint64_t arena_base = 0x60000000;
  static constexpr uint64_t arena_size = 0x10000000;

  HostMemory(Mmio& mmio, Pio& pio);
  ~HostMemory();
  int initialize();
  int cp_reg_read(uint32_t offset, uint32_t* value);
  int cp_reg_write(uint32_t offset, uint32_t value);
  int allocate(uint64_t size, void** pointer, uint64_t* address);
  int release(uint64_t address);
  int push(uint64_t address);
  int pull(uint64_t address);

private:
  struct Free {
    void operator()(uint8_t* pointer) const { std::free(pointer); }
  };
  struct Region {
    std::unique_ptr<uint8_t, Free> data;
    uint64_t size;
  };
  struct Pending {
    uint64_t address;
    uint64_t watermark;
    Region region;
  };

  int read(uint32_t offset, uint32_t* value);
  int write(uint32_t offset, uint32_t value);
  int transfer(uint64_t address, Region& region, bool upload);
  int publish(uint64_t tail);
  void collect();
  bool owned(uint64_t address) const;

  Mmio& mmio_;
  Pio& pio_;
  MemoryAllocator allocator_{arena_base, arena_size, 4096, 64};
  std::mutex mutex_;
  std::map<uint64_t, Region> regions_;
  std::map<uint64_t, Region> unstamped_;
  std::vector<Pending> pending_;
  std::array<uint64_t, 3> owner_addresses_{};
  uint32_t tail_low_ = 0;
  uint32_t ring_log2_ = 0;
  uint32_t last_seqnum_ = 0;
  uint64_t retired_ = 0;
  uint64_t tail_ = 0;
  bool initialized_ = false;
  bool seeded_ = false;
  bool poisoned_ = false;
};

}
