// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_memory.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>

static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "%s\n", message);
    std::exit(1);
  }
}

struct Transfer {
  uint64_t address;
  uint32_t local;
  unsigned bank;
  unsigned length;
  bool error;
  uint32_t id;
  bool address_sent = false;
  unsigned beat = 0;
  unsigned response = 0;
};

struct Slave {
  bool active = false;
  bool valid = false;
  Transfer transfer{};
  unsigned beat = 0;
};

static uint32_t pattern(const Transfer& transfer, unsigned beat, unsigned word) {
  return transfer.id ^ (beat * 0x10203u) ^ (word * 0x1010101u);
}

template<size_t N>
static void set_address(VlWide<N>& port, unsigned source, uint64_t address) {
  port[2 * source] = uint32_t(address);
  port[2 * source + 1] = uint32_t(address >> 32);
}

int main() {
  VVX_ypcb_memory dut;
  std::array<std::deque<Transfer>, TEST_NUM_INPUTS> writes, reads;
  const std::array<Transfer, 8> cases = {{
    {0x00000000, 0x00000000, 0, 0, false, 0},
    {0x7ffff000, 0x7ffff000, 0, 63, false, 0},
    {0x80000000, 0x00000000, 1, 3, false, 0},
    {0xfffff000, 0x7ffff000, 1, 63, false, 0},
    {0x100000000ull, 0, 0, 3, true, 0},
    {0x80000004, 0, 0, 0, true, 0},
    {0x7fffffc0, 0, 0, 1, true, 0},
    {0x80000000, 0, 0, 255, true, 0},
  }};
  for (unsigned source = 0; source < TEST_NUM_INPUTS; ++source) {
    for (unsigned index = 0; index < cases.size(); ++index) {
      auto transfer = cases[index];
      if (index == 2) {
        transfer.response = 2;
      }
      transfer.id = 0xa5000000u | (source << 16) | index;
      writes[source].push_back(transfer);
      transfer.id ^= 0x10000000u;
      reads[source].push_back(transfer);
    }
  }
  std::array<Slave, 2> write_slaves{}, read_slaves{};
  dut.s_awvalid = dut.s_wvalid = dut.s_arvalid = 0;
  dut.s_bready = dut.s_rready = 0;
  dut.m_awready = dut.m_wready = dut.m_arready = 0;
  dut.m_bvalid = dut.m_rvalid = 0;
  dut.m_bid = dut.m_bresp = dut.m_rid = dut.m_rresp = dut.m_rlast = 0;
  dut.reset = 1;
  for (unsigned cycle = 0; cycle < 4; ++cycle) {
    dut.clk = 0; dut.eval();
    dut.clk = 1; dut.eval();
  }
  dut.reset = 0;
  unsigned completed_writes = 0, completed_reads = 0;
  unsigned ddr_writes = 0, ddr_reads = 0;
  for (unsigned cycle = 0; cycle < 20000; ++cycle) {
    dut.s_awvalid = dut.s_wvalid = dut.s_wlast = dut.s_arvalid = 0;
    dut.s_awlen = dut.s_arlen = 0;
    dut.s_bready = (cycle % 5 == 0) ? 0 : ((1u << TEST_NUM_INPUTS) - 1);
    dut.s_rready = (cycle % 7 < 2) ? 0 : ((1u << TEST_NUM_INPUTS) - 1);
    for (unsigned source = 0; source < TEST_NUM_INPUTS; ++source) {
      if (!writes[source].empty()) {
        const auto& transfer = writes[source].front();
        set_address(dut.s_awaddr, source, transfer.address);
        dut.s_awid[source] = transfer.id;
        dut.s_awlen |= uint64_t(transfer.length) << (8 * source);
        dut.s_awvalid |= unsigned(!transfer.address_sent) << source;
        dut.s_wvalid |= unsigned(transfer.beat <= transfer.length) << source;
        dut.s_wlast |= unsigned(transfer.beat == transfer.length) << source;
        for (unsigned word = 0; word < 16; ++word) {
          dut.s_wdata[source * 16 + word] = pattern(transfer, transfer.beat, word);
        }
        dut.s_wstrb[source * 2] = 0x5a5a5a5au;
        dut.s_wstrb[source * 2 + 1] = 0xa5a5a5a5u;
      }
      if (!reads[source].empty()) {
        const auto& transfer = reads[source].front();
        set_address(dut.s_araddr, source, transfer.address);
        dut.s_arid[source] = transfer.id;
        dut.s_arlen |= uint64_t(transfer.length) << (8 * source);
        dut.s_arvalid |= unsigned(!transfer.address_sent) << source;
      }
    }
    dut.m_awready = (cycle % 3 == 0) ? 0 : 3;
    dut.m_wready = (cycle % 5 < 2) ? 0 : 3;
    dut.m_arready = (cycle % 4 == 0) ? 0 : 3;
    dut.m_bvalid = dut.m_rvalid = dut.m_rlast = 0;
    dut.m_bresp = dut.m_rresp = 0;
    for (unsigned bank = 0; bank < 2; ++bank) {
      auto& wr = write_slaves[bank];
      dut.m_bvalid |= unsigned(wr.valid) << bank;
      dut.m_bresp |= wr.transfer.response << (2 * bank);
      auto& rd = read_slaves[bank];
      dut.m_rresp |= rd.transfer.response << (2 * bank);
      if (rd.active && (rd.valid || cycle % 3 != 0)) {
        rd.valid = true;
        dut.m_rvalid |= 1u << bank;
        dut.m_rlast |= unsigned(rd.beat == rd.transfer.length) << bank;
        for (unsigned word = 0; word < 16; ++word) {
          dut.m_rdata[bank * 16 + word] = pattern(rd.transfer, rd.beat, word);
        }
      }
    }
    dut.clk = 0;
    dut.eval();
    const unsigned awfire = dut.s_awvalid & dut.s_awready;
    const unsigned arfire = dut.s_arvalid & dut.s_arready;
    const unsigned wfire = dut.s_wvalid & dut.s_wready;
    const unsigned bfire = dut.s_bvalid & dut.s_bready;
    const unsigned rfire = dut.s_rvalid & dut.s_rready;
    require(!(awfire & (awfire - 1)), "Multiple write addresses escaped serialization");
    require(!(arfire & (arfire - 1)), "Multiple read addresses escaped serialization");
    for (unsigned source = 0; source < TEST_NUM_INPUTS; ++source) {
      if ((awfire >> source) & 1) {
        auto& transfer = writes[source].front();
        transfer.address_sent = true;
        const unsigned fire = dut.m_awvalid & dut.m_awready;
        require(fire == (transfer.error ? 0u : 1u << transfer.bank), "Write bank decode failed");
        if (!transfer.error) {
          const unsigned bank = transfer.bank;
          require(((dut.m_awaddr >> (31 * bank)) & 0x7fffffffu) == transfer.local, "Write address changed");
          require(((dut.m_awlen >> (8 * bank)) & 255) == transfer.length, "Write burst changed");
          require(dut.m_awid == 0, "DDR write ID remapping failed");
          require(!write_slaves[bank].active, "Overlapping DDR writes");
          write_slaves[bank] = {true, false, transfer, 0};
          ++ddr_writes;
        }
      }
      if ((arfire >> source) & 1) {
        auto& transfer = reads[source].front();
        transfer.address_sent = true;
        const unsigned fire = dut.m_arvalid & dut.m_arready;
        require(fire == (transfer.error ? 0u : 1u << transfer.bank), "Read bank decode failed");
        if (!transfer.error) {
          const unsigned bank = transfer.bank;
          require(((dut.m_araddr >> (31 * bank)) & 0x7fffffffu) == transfer.local, "Read address changed");
          require(((dut.m_arlen >> (8 * bank)) & 255) == transfer.length, "Read burst changed");
          require(dut.m_arid == 0, "DDR read ID remapping failed");
          require(!read_slaves[bank].active, "Overlapping DDR reads");
          read_slaves[bank] = {true, false, transfer, 0};
          ++ddr_reads;
        }
      }
      if ((wfire >> source) & 1) {
        auto& transfer = writes[source].front();
        require(transfer.address_sent, "Write data preceded accepted address");
        require((dut.m_wvalid & dut.m_wready) == (transfer.error ? 0u : 1u << transfer.bank), "Write data misrouted");
        if (!transfer.error) {
          const unsigned bank = transfer.bank;
          for (unsigned word = 0; word < 16; ++word) {
            require(dut.m_wdata[bank * 16 + word] == pattern(transfer, transfer.beat, word), "Write payload changed");
          }
          require(dut.m_wstrb[bank * 2] == 0x5a5a5a5au && dut.m_wstrb[bank * 2 + 1] == 0xa5a5a5a5u, "Write byte enables changed");
          require(((dut.m_wlast >> bank) & 1) == unsigned(transfer.beat == transfer.length), "Write last changed");
          if (transfer.beat == transfer.length) {
            write_slaves[bank].valid = true;
          }
        }
        ++transfer.beat;
      }
      if ((bfire >> source) & 1) {
        const auto& transfer = writes[source].front();
        require(transfer.beat == transfer.length + 1, "Write retired before all data beats");
        require(dut.s_bid[source] == transfer.id, "Write ID was truncated or misrouted");
        require(((dut.s_bresp >> (2 * source)) & 3) == (transfer.error ? 3u : transfer.response), "Write response changed");
        if (!transfer.error) {
          write_slaves[transfer.bank] = {};
        }
        writes[source].pop_front();
        ++completed_writes;
      }
      if ((rfire >> source) & 1) {
        auto& transfer = reads[source].front();
        require(dut.s_rid[source] == transfer.id, "Read ID was truncated or misrouted");
        require(((dut.s_rresp >> (2 * source)) & 3) == (transfer.error ? 3u : transfer.response), "Read response changed");
        const bool last = transfer.beat == transfer.length;
        require(((dut.s_rlast >> source) & 1) == unsigned(last), "Read burst length changed");
        for (unsigned word = 0; word < 16; ++word) {
          require(dut.s_rdata[source * 16 + word] == (transfer.error ? 0u : pattern(transfer, transfer.beat, word)), "Read payload changed");
        }
        if (!transfer.error) {
          auto& slave = read_slaves[transfer.bank];
          slave.valid = false;
          ++slave.beat;
          if (last) {
            slave = {};
          }
        }
        ++transfer.beat;
        if (last) {
          reads[source].pop_front();
          ++completed_reads;
        }
      }
    }
    dut.clk = 1;
    dut.eval();
    if (completed_writes == 8 * TEST_NUM_INPUTS && completed_reads == 8 * TEST_NUM_INPUTS) {
      require(ddr_writes == 4 * TEST_NUM_INPUTS && ddr_reads == 4 * TEST_NUM_INPUTS, "Incorrect DDR transaction count");
      std::printf("PASSED: %u writes, %u reads, %u contending masters, 2 DDR channels, full IDs, byte enables, backpressure and DECERR\n",
        completed_writes, completed_reads, TEST_NUM_INPUTS);
      return 0;
    }
  }
  require(false, "Memory bridge timed out");
}
