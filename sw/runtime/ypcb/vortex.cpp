// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <common.h>
#include <ypcb_ddr.h>
#include <ypcb_startup.h>
#include <ypcb_host_memory.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <fcntl.h>
#include <fstream>
#include <memory>
#include <string>
#include <sys/file.h>
#include <sys/mman.h>
#include <thread>
#include <unistd.h>

using namespace vortex;
using namespace vortex::ypcb;

namespace {
constexpr size_t bar_size = 65536;

bool valid_bdf(const std::string& bdf) {
  if (bdf.size() != 12 || bdf[4] != ':' || bdf[7] != ':' || bdf[10] != '.') {
    return false;
  }
  for (unsigned i = 0; i < bdf.size(); ++i) {
    if (i != 4 && i != 7 && i != 10
        && !((bdf[i] >= '0' && bdf[i] <= '9') || (bdf[i] >= 'a' && bdf[i] <= 'f'))) {
      return false;
    }
  }
  return bdf[8] <= '1' && bdf[11] <= '7';
}

bool sysfs_hex(const std::string& path, uint64_t* value) {
  std::ifstream stream(path);
  return bool(stream >> std::hex >> *value);
}
}

class vx_device final : public Mmio {
public:
  ~vx_device() override {
    if (reset_available_ && quiesce_and_reset() != 0) {
      std::fprintf(stderr, "[VXDRV] YPCB AFU did not drain on close\n");
    }
    host_.reset();
    if (bar_ != MAP_FAILED) {
      munmap(bar_, bar_size);
    }
    if (enable_ >= 0) {
      if (enabled_ && pwrite(enable_, "0\n", 2, 0) != 2) {
        std::fprintf(stderr, "[VXDRV] Cannot release YPCB PCI enable reference\n");
      }
      close(enable_);
    }
    if (resource_ >= 0) {
      close(resource_);
    }
  }

  int init() {
    try {
      return initialize();
    } catch (const std::exception& error) {
      std::fprintf(stderr, "[VXDRV] YPCB setup: %s\n", error.what());
      return -1;
    }
  }

  int read32(uint32_t offset, uint32_t* value) override {
    if (bar_ == MAP_FAILED || value == nullptr || offset >= bar_size || (offset & 3)) {
      return -1;
    }
    std::atomic_thread_fence(std::memory_order_seq_cst);
    *value = *reinterpret_cast<volatile uint32_t*>(static_cast<uint8_t*>(bar_) + offset);
    std::atomic_thread_fence(std::memory_order_seq_cst);
    return 0;
  }

  int write32(uint32_t offset, uint32_t value) override {
    if (bar_ == MAP_FAILED || offset >= bar_size || (offset & 3)) {
      return -1;
    }
    std::atomic_thread_fence(std::memory_order_seq_cst);
    *reinterpret_cast<volatile uint32_t*>(static_cast<uint8_t*>(bar_) + offset) = value;
    std::atomic_thread_fence(std::memory_order_seq_cst);
    uint32_t status;
    // A read completion fences the posted PCIe write and exposes adapter errors.
    return read32(0x3008, &status) == 0 && status != 0xffffffff && !(status & 0x7800)
        ? 0 : -1;
  }

  int cp_reg_read(uint32_t offset, uint32_t* value) {
    return host_ ? host_->cp_reg_read(offset, value) : -1;
  }
  int cp_reg_write(uint32_t offset, uint32_t value) {
    return host_ ? host_->cp_reg_write(offset, value) : -1;
  }
  int host_mem_alloc(uint64_t size, void** pointer, uint64_t* address) {
    return host_ ? host_->allocate(size, pointer, address) : -1;
  }
  int host_mem_free(uint64_t address) {
    return host_ ? host_->release(address) : -1;
  }
  int host_mem_push(uint64_t address) {
    return host_ ? host_->push(address) : -1;
  }
  int host_mem_pull(uint64_t address) {
    return host_ ? host_->pull(address) : -1;
  }
  int host_mem_device_range(uint64_t* base, uint64_t* size) {
    *base = HostMemory::arena_base;
    *size = HostMemory::arena_size;
    return 0;
  }

private:
  int initialize() {
    const char* selected = std::getenv("VORTEX_YPCB_BDF");
    if (selected == nullptr || !valid_bdf(selected)) {
      std::fprintf(stderr, "[VXDRV] Set VORTEX_YPCB_BDF to the full lowercase PCI BDF\n");
      return -1;
    }
    const std::string directory = std::string("/sys/bus/pci/devices/") + selected;
    uint64_t vendor, device;
    if (!sysfs_hex(directory + "/vendor", &vendor) || vendor != 0x10ee
        || !sysfs_hex(directory + "/device", &device) || device != 0x0480
        || access((directory + "/driver").c_str(), F_OK) == 0) {
      std::fprintf(stderr, "[VXDRV] Selected PCI device is not an unbound YPCB endpoint (10ee:0480)\n");
      return -1;
    }
    uint64_t start, end, flags;
    std::ifstream resources(directory + "/resource");
    if (!(resources >> std::hex >> start >> end >> flags) || start == 0
        || end < start || end - start != bar_size - 1 || !(flags & 0x200)) {
      std::fprintf(stderr, "[VXDRV] YPCB BAR0 must be an assigned 64 KiB memory resource\n");
      return -1;
    }
    resource_ = open((directory + "/resource0").c_str(), O_RDWR | O_CLOEXEC);
    if (resource_ < 0 || flock(resource_, LOCK_EX | LOCK_NB) != 0) {
      std::fprintf(stderr, "[VXDRV] Cannot exclusively open YPCB BAR0\n");
      return -1;
    }
    enable_ = open((directory + "/enable").c_str(), O_WRONLY | O_CLOEXEC);
    if (enable_ < 0 || pwrite(enable_, "1\n", 2, 0) != 2) {
      std::fprintf(stderr, "[VXDRV] Cannot acquire YPCB PCI enable reference\n");
      return -1;
    }
    enabled_ = true;
    bar_ = mmap(nullptr, bar_size, PROT_READ | PROT_WRITE, MAP_SHARED, resource_, 0);
    uint32_t signature, version, status;
    if (read32(0x3000, &signature) != 0 || signature != 0x56595043
        || read32(0x3004, &version) != 0 || version != 1
        || read32(0x3008, &status) != 0 || status == 0xffffffff) {
      std::fprintf(stderr, "[VXDRV] YPCB startup signature/version is unavailable\n");
      return -1;
    }
    if (((status >> 16) & 7) == 0) {
      const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
      while ((status & 3) != 3) {
        if ((status & 0x7870) || std::chrono::steady_clock::now() >= deadline
            || read32(0x3008, &status) != 0) {
          std::fprintf(stderr, "[VXDRV] YPCB DDR PLLs did not become ready\n");
          return -1;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
      for (unsigned bank = 0; bank < 2; ++bank) {
        if (!(status & (4u << bank))) {
          Ddr ddr(*this, bank);
          DdrReport report;
          const DdrResult result = ddr.initialize(&report);
          if (result != DdrResult::success) {
            std::fprintf(stderr, "[VXDRV] YPCB DDR%u training failed: result=%u lane=%u cleanup=%u\n",
                bank, unsigned(result), report.failed_lane, unsigned(report.cleanup_complete));
            return -1;
          }
          for (unsigned lane = 0; lane < report.lanes.size(); ++lane) {
            const auto& window = report.lanes[lane];
            std::fprintf(stderr, "[VXDRV] DDR%u lane%u slip=%u taps=%u..%u center=%u\n",
                bank, lane, window.bitslip, window.first, window.last, window.center);
          }
          if (read32(0x3008, &status) != 0) {
            return -1;
          }
        }
      }
    }
    Startup startup(*this);
    StartupReport report;
    if (startup.initialize(&report) != StartupResult::success
        || pio_.initialize() != Result::success) {
      std::fprintf(stderr, "[VXDRV] YPCB ECC scrub/readiness failed\n");
      return -1;
    }
    reset_available_ = true;
    if (quiesce_and_reset() != 0) {
      std::fprintf(stderr, "[VXDRV] YPCB AFU could not drain and reset\n");
      reset_available_ = false;
      return -1;
    }
    uint32_t first, second;
    if (read32(0x1010, &first) != 0) {
      return -1;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if (read32(0x1010, &second) != 0 || first == second || second == 0xffffffff) {
      std::fprintf(stderr, "[VXDRV] YPCB CP cycle counter is not advancing\n");
      return -1;
    }
    host_ = std::make_unique<HostMemory>(*this, pio_);
    return host_->initialize();
  }

  int quiesce_and_reset() {
    if (write32(0x111c, 0) != 0 || write32(0x1000, 0) != 0
        || write32(0, 0x10) != 0) {
      return -1;
    }
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    while (std::chrono::steady_clock::now() < deadline) {
      uint32_t status;
      if (read32(0, &status) != 0 || status == 0xffffffff || (status & 0x20)) {
        return -1;
      }
      if ((status & 0x14) == 4) {
        return 0;
      }
      std::this_thread::sleep_for(std::chrono::microseconds(50));
    }
    return -1;
  }

  int resource_ = -1;
  int enable_ = -1;
  void* bar_ = MAP_FAILED;
  bool enabled_ = false;
  bool reset_available_ = false;
  Pio pio_{*this};
  std::unique_ptr<HostMemory> host_;
};

#include <callbacks.inc>
