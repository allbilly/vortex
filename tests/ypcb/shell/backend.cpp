// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_shell.h"
#include <common.h>
#include <callbacks.h>
#include <ypcb_host_memory.h>
#include <ypcb_startup.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <vector>

using namespace vortex;
using namespace vortex::ypcb;

namespace {
void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: shell simulation: %s\n", message);
    std::exit(1);
  }
}

struct Transfer {
  uint32_t address = 0;
  unsigned id = 0, remaining = 0;
  bool active = false, valid = false;
  std::array<uint32_t, 16> data{};
};

class Shell final : public Mmio {
public:
  Shell() : dut_(&context_) {
    jtag_mode_ = std::getenv("VORTEX_YPCB_TEST_JTAG") != nullptr;
    dut_.reset = 1;
    dut_.pcie_reset = 1;
    dut_.link_up = jtag_mode_ ? 0 : 1;
    dut_.tx_error = 0;
    dut_.pll_locked = 2;
    dut_.init_done = 0;
    dut_.init_error = 0;
    dut_.rx_valid = 0;
    dut_.rx_data = 0;
    dut_.rx_keep = 0;
    dut_.rx_last = 0;
    dut_.rx_user = 4;
    dut_.completer_id = 0x02a0;
    for (unsigned i = 0; i < 8; ++i) {
      tick();
    }
    dut_.reset = 0;
    dut_.pcie_reset = jtag_mode_ ? 1 : 0;
    for (unsigned i = 0; i < 8; ++i) {
      tick();
    }
  }

  ~Shell() override {
    dut_.final();
    std::fprintf(stderr,
        "Shell simulation: cycles=%llu MMIO reads=%llu writes=%llu DDR beats W=%llu/%llu R=%llu/%llu\n",
        static_cast<unsigned long long>(cycle_), static_cast<unsigned long long>(reads_),
        static_cast<unsigned long long>(writes_), static_cast<unsigned long long>(write_beats_[0]),
        static_cast<unsigned long long>(write_beats_[1]), static_cast<unsigned long long>(read_beats_[0]),
        static_cast<unsigned long long>(read_beats_[1]));
  }

  int prepare() {
    uint32_t value = 0;
    require(read32(0, &value) != 0, "unready AFU access succeeded");
    if (!jtag_mode_) {
      require(read32(0x3008, &value) == 0 && (value & 0x1000),
          "PCIe AXI error did not reach board status");
    }
    reset_model();
    require(read32(0x3000, &value) == 0 && value == 0x56595043, "startup signature");
    require(read32(0x9000, &value) != 0, "unmapped control access succeeded");
    reset_model();
    dut_.init_done = 2;
    Startup startup(*this, std::chrono::seconds(5));
    StartupReport report;
    require(startup.initialize(&report) == StartupResult::success, "startup scrub failed");
    require(write_beats_[0] == 0 && write_beats_[1] == 5,
        "reduced scrub did not cover only CH1");
    require(dut_.memory_ready == 2, "startup did not release CH1");
    std::fprintf(stderr, "Shell startup PASS: real readiness gate and five-beat scrub; DDR/PHY status and memory are oracles\n");
    return 0;
  }

  int read32(uint32_t offset, uint32_t* value) override {
    if (value == nullptr || offset >= 65536 || (offset & 3)) {
      return -1;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    return jtag_mode_ ? read_jtag(offset, value) : read_locked(offset, value);
  }

  int write32(uint32_t offset, uint32_t value) override {
    if (offset >= 65536 || (offset & 3)) {
      return -1;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (jtag_mode_) {
      return write_jtag(offset, value);
    }
    send({0x40000001, 0x7a19000f, 0xabc00000 | offset, value});
    ++writes_;
    uint32_t status = 0;
    return read_locked(0x3008, &status) == 0 && !(status & 0x7800) ? 0 : -1;
  }

  int reset_afu() {
    if (write32(0x111c, 0) || write32(0x1000, 0) || write32(0, 0x10)) {
      return -1;
    }
    for (unsigned i = 0; i < 10000; ++i) {
      uint32_t status = 0;
      if (read32(0, &status) || (status & 0x20)) {
        return -1;
      }
      if ((status & 0x14) == 4) {
        return 0;
      }
    }
    return -1;
  }

private:
  int read_jtag(uint32_t offset, uint32_t* value) {
    dut_.j_araddr = offset;
    dut_.j_arvalid = 1;
    for (unsigned wait = 0; wait < 10000; ++wait) {
      dut_.eval();
      const bool accepted = dut_.j_arready;
      tick();
      if (accepted) {
        dut_.j_arvalid = 0;
        break;
      }
      require(wait != 9999, "JTAG read address timed out");
    }
    for (unsigned wait = 0; wait < 10000; ++wait) {
      dut_.eval();
      if (dut_.j_rvalid) {
        *value = dut_.j_rdata;
        const unsigned response = dut_.j_rresp;
        dut_.j_rready = 1;
        tick();
        dut_.j_rready = 0;
        ++reads_;
        return response == 0 ? 0 : -1;
      }
      tick();
    }
    require(false, "JTAG read response timed out");
    return -1;
  }

  int write_jtag(uint32_t offset, uint32_t value) {
    dut_.j_awaddr = offset;
    dut_.j_awvalid = 1;
    dut_.j_wdata = value;
    dut_.j_wstrb = 15;
    dut_.j_wvalid = 1;
    for (unsigned wait = 0; wait < 10000; ++wait) {
      dut_.eval();
      const bool address = dut_.j_awvalid && dut_.j_awready;
      const bool data = dut_.j_wvalid && dut_.j_wready;
      tick();
      if (address) {
        dut_.j_awvalid = 0;
      }
      if (data) {
        dut_.j_wvalid = 0;
      }
      if (!dut_.j_awvalid && !dut_.j_wvalid) {
        break;
      }
      require(wait != 9999, "JTAG write request timed out");
    }
    for (unsigned wait = 0; wait < 10000; ++wait) {
      dut_.eval();
      if (dut_.j_bvalid) {
        const unsigned response = dut_.j_bresp;
        dut_.j_bready = 1;
        tick();
        dut_.j_bready = 0;
        ++writes_;
        return response == 0 ? 0 : -1;
      }
      tick();
    }
    require(false, "JTAG write response timed out");
    return -1;
  }

  bool jtag_mode_ = false;

  void reset_model() {
    require(completions_.empty() && receiving_.empty(), "reset with an unread completion");
    write_ = {};
    read_ = {};
    dut_.reset = 1;
    dut_.pcie_reset = 1;
    for (unsigned i = 0; i < 8; ++i) {
      tick();
    }
    dut_.reset = 0;
    dut_.pcie_reset = jtag_mode_ ? 1 : 0;
    for (unsigned i = 0; i < 8; ++i) {
      tick();
    }
  }

  void drive() {
    dut_.m_awready = dut_.m_wready = dut_.m_arready = 0;
    dut_.m_bvalid = dut_.m_rvalid = dut_.m_rlast = 0;
    dut_.m_bid = dut_.m_rid = dut_.m_bresp = dut_.m_rresp = 0;
    for (unsigned bank = 0; bank < 2; ++bank) {
      auto& wr = write_[bank];
      auto& rd = read_[bank];
      const unsigned bit = 1u << bank;
      if (!wr.active && !wr.valid && cycle_ % 5 != bank) {
        dut_.m_awready |= bit;
      }
      if (wr.active && cycle_ % 7 != bank) {
        dut_.m_wready |= bit;
      }
      if (wr.valid) {
        dut_.m_bvalid |= bit;
        dut_.m_bid |= wr.id << (bank * 8);
      }
      if (!rd.active && cycle_ % 3 != bank) {
        dut_.m_arready |= bit;
      }
      if (rd.active && !rd.valid && cycle_ % 4 != bank) {
        rd.valid = true;
        rd.data = memory_[bank][rd.address];
      }
      if (rd.valid) {
        dut_.m_rvalid |= bit;
        dut_.m_rlast |= unsigned(rd.remaining == 1) << bank;
        dut_.m_rid |= rd.id << (bank * 8);
        for (unsigned word = 0; word < 16; ++word) {
          dut_.m_rdata[bank * 16 + word] = rd.data[word];
        }
      }
    }
    dut_.wb_ack = dut_.wb_cyc & dut_.wb_stb;
    dut_.wb_err = 0;
    dut_.wb_dat_r = 0;
    dut_.tx_ready = cycle_ % 11 < 7;
    dut_.clk = 0;
    dut_.pcie_clk = 0;
    dut_.eval();
  }

  bool tick() {
    drive();
    const bool received = dut_.rx_valid && dut_.rx_ready;
    if (!dut_.reset) {
      for (unsigned bank = 0; bank < 2; ++bank) {
        const unsigned bit = 1u << bank;
        auto& wr = write_[bank];
        auto& rd = read_[bank];
        if ((dut_.m_bvalid & dut_.m_bready) & bit) {
          wr.valid = false;
        }
        if ((dut_.m_awvalid & dut_.m_awready) & bit) {
          wr.address = (dut_.m_awaddr >> (bank * 31)) & 0x7fffffff;
          wr.id = (dut_.m_awid >> (bank * 8)) & 255;
          wr.remaining = ((dut_.m_awlen >> (bank * 8)) & 255) + 1;
          require(!wr.active && !wr.valid && !(wr.address & 63), "invalid DDR AW");
          wr.active = true;
        }
        if ((dut_.m_wvalid & dut_.m_wready) & bit) {
          require(wr.active && wr.remaining, "DDR W without AW");
          require(bool(dut_.m_wlast & bit) == (wr.remaining == 1), "DDR WLAST");
          auto& line = memory_[bank][wr.address];
          for (unsigned byte = 0; byte < 64; ++byte) {
            if ((dut_.m_wstrb[bank * 2 + byte / 32] >> (byte % 32)) & 1) {
              const unsigned shift = (byte % 4) * 8;
              const uint32_t mask = 255u << shift;
              line[byte / 4] = (line[byte / 4] & ~mask)
                  | (dut_.m_wdata[bank * 16 + byte / 4] & mask);
            }
          }
          ++write_beats_[bank];
          wr.address += 64;
          if (--wr.remaining == 0) {
            wr.active = false;
            wr.valid = true;
          }
        }
        if ((dut_.m_rvalid & dut_.m_rready) & bit) {
          require(rd.active && rd.valid && rd.remaining, "unexpected DDR R");
          ++read_beats_[bank];
          rd.address += 64;
          rd.valid = false;
          if (--rd.remaining == 0) {
            rd.active = false;
          }
        }
        if ((dut_.m_arvalid & dut_.m_arready) & bit) {
          rd.address = (dut_.m_araddr >> (bank * 31)) & 0x7fffffff;
          rd.id = (dut_.m_arid >> (bank * 8)) & 255;
          rd.remaining = ((dut_.m_arlen >> (bank * 8)) & 255) + 1;
          require(!rd.active && !(rd.address & 63), "invalid DDR AR");
          rd.active = true;
        }
      }
      if (dut_.tx_valid && dut_.tx_ready) {
        require(dut_.tx_keep == 255 || (dut_.tx_last && dut_.tx_keep == 15), "completion TKEEP");
        receiving_.push_back(uint32_t(dut_.tx_data));
        if (dut_.tx_keep == 255) {
          receiving_.push_back(dut_.tx_data >> 32);
        }
        if (dut_.tx_last) {
          completions_.push_back(std::move(receiving_));
          receiving_.clear();
        }
      }
    }
    context_.timeInc(4);
    dut_.clk = 1;
    dut_.pcie_clk = jtag_mode_ ? 0 : 1;
    dut_.eval();
    context_.timeInc(4);
    ++cycle_;
    require(!context_.gotFinish(), "RTL stopped");
    return received;
  }

  void send(const std::vector<uint32_t>& words) {
    for (unsigned i = 0; i < words.size(); i += 2) {
      dut_.rx_data = words[i];
      if (i + 1 < words.size()) {
        dut_.rx_data |= uint64_t(words[i + 1]) << 32;
      }
      dut_.rx_keep = i + 1 < words.size() ? 255 : 15;
      dut_.rx_last = i + 2 >= words.size();
      dut_.rx_valid = 1;
      unsigned attempts = 0;
      while (!tick()) {
        require(++attempts < 10000, "TLP receive timeout");
      }
      dut_.rx_valid = 0;
    }
  }

  int read_locked(uint32_t offset, uint32_t* value) {
    require(completions_.empty() && receiving_.empty(), "unconsumed completion");
    const uint32_t request = 0x7a19000f | uint32_t(tag_) << 8;
    send({1, request, 0xabc00000 | offset});
    unsigned attempts = 0;
    while (completions_.empty()) {
      require(++attempts < 100000, "MMIO read timeout");
      tick();
    }
    auto completion = std::move(completions_.front());
    completions_.pop_front();
    ++reads_;
    require(completion.size() >= 3, "short completion");
    require((completion[1] >> 16) == 0x02a0 && (completion[2] >> 8) == (request >> 8),
        "completion requester/tag/completer mismatch");
    ++tag_;
    if ((completion[1] >> 13) & 7) {
      require(completion.size() == 3 && completion[0] == 0x0a000000, "error completion format");
      return -1;
    }
    require(completion.size() == 4 && completion[0] == 0x4a000001
        && (completion[1] & 0x1fff) == 4 && (completion[2] & 127) == (offset & 127),
        "successful completion format");
    *value = completion[3];
    return 0;
  }

  VerilatedContext context_;
  VVX_ypcb_shell dut_;
  std::mutex mutex_;
  std::array<Transfer, 2> write_{}, read_{};
  std::array<std::map<uint32_t, std::array<uint32_t, 16>>, 2> memory_;
  std::deque<std::vector<uint32_t>> completions_;
  std::vector<uint32_t> receiving_;
  std::array<uint64_t, 2> write_beats_{}, read_beats_{};
  uint64_t cycle_ = 0, reads_ = 0, writes_ = 0;
  uint8_t tag_ = 0;
};
}

class vx_device {
public:
  vx_device() : pio_(shell_, std::chrono::minutes(15)) {}

  ~vx_device() {
    if (host_) {
      require(shell_.reset_afu() == 0, "AFU close did not drain/reset");
      host_.reset();
    }
  }

  int init() {
    if (shell_.prepare() || pio_.initialize() != Result::success || shell_.reset_afu()) {
      return -1;
    }
    host_ = std::make_unique<HostMemory>(shell_, pio_);
    return host_->initialize();
  }

  int cp_reg_read(uint32_t offset, uint32_t* value) { return host_->cp_reg_read(offset, value); }
  int cp_reg_write(uint32_t offset, uint32_t value) { return host_->cp_reg_write(offset, value); }
  int host_mem_alloc(uint64_t size, void** pointer, uint64_t* address) {
    return host_->allocate(size, pointer, address);
  }
  int host_mem_free(uint64_t address) { return host_->release(address); }
  int host_mem_push(uint64_t address) { return host_->push(address); }
  int host_mem_pull(uint64_t address) { return host_->pull(address); }
  int host_mem_device_range(uint64_t* base, uint64_t* size) {
    *base = HostMemory::arena_base;
    *size = HostMemory::arena_size;
    return 0;
  }

private:
  Shell shell_;
  Pio pio_;
  std::unique_ptr<HostMemory> host_;
};

#include <callbacks.inc>
