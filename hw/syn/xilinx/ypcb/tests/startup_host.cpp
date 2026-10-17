// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "Vstartup_host_top.h"
#include <ypcb_startup.h>
#include <verilated.h>
#include <cstdio>
#include <cstdlib>

using namespace vortex::ypcb;

static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

class RtlMmio : public Mmio {
public:
  VerilatedContext context;
  Vstartup_host_top dut{&context};
  unsigned cycles = 0, beats = 0, responses = 0, commands = 0;
  unsigned due = 0, remaining = 0;
  bool pending = false, hold_response = false, lose_pll = false;
  bool fail_read = false, fail_after_command = false;
  uint8_t response = 0;
  uint64_t address = 0;

  RtlMmio() {
    dut.pll_locked = 3;
    dut.init_done = 3;
    dut.link_up = 1;
    dut.reset = 1;
    for (unsigned i = 0; i < 5; ++i) {
      tick();
    }
    dut.reset = 0;
    tick();
  }

  struct Events {
    bool aw, w, b, ar, r;
    uint32_t data;
    unsigned bresp, rresp;
  };

  Events tick() {
    dut.m_awready = !pending && cycles % 5 == 1;
    dut.m_wready = pending && remaining != 0 && cycles % 7 >= 3;
    dut.m_bvalid = pending && remaining == 0 && cycles >= due && !hold_response;
    dut.m_bresp = response;
    dut.clk = 0;
    dut.eval();
    Events events{bool(dut.s_awvalid && dut.s_awready), bool(dut.s_wvalid && dut.s_wready),
                  bool(dut.s_bvalid && dut.s_bready), bool(dut.s_arvalid && dut.s_arready),
                  bool(dut.s_rvalid && dut.s_rready), dut.s_rdata, dut.s_bresp, dut.s_rresp};
    if (!dut.reset) {
      if (dut.memory_ready != 0) {
        require(responses == 2 && beats == 5 && !pending,
                "Memory became ready before the final scrub response");
      }
      if (dut.m_awvalid && dut.m_awready) {
        require(!pending, "Overlapping scrub bursts");
        require(dut.m_awaddr == (responses == 0 ? 0x7fffff80ull : 0x80000000ull),
                "Scrub bank-boundary address differs");
        require(dut.m_awlen == (responses == 0 ? 1 : 2), "Scrub burst length differs");
        address = dut.m_awaddr;
        remaining = dut.m_awlen + 1;
        pending = true;
      }
      if (dut.m_wvalid && dut.m_wready) {
        require(pending && remaining != 0 && dut.m_wstrb == ~uint64_t(0),
                "Scrub write lacks a burst or full byte enables");
        for (unsigned word = 0; word < 16; ++word) {
          require(dut.m_wdata[word] == 0, "Scrub data was not zero");
        }
        require(bool(dut.m_wlast) == (remaining == 1), "Scrub WLAST differs");
        --remaining;
        ++beats;
        address += 64;
        if (remaining == 0) {
          due = cycles + 40;
        }
      }
      if (dut.m_bvalid && dut.m_bready) {
        require(pending && remaining == 0, "Scrub response preceded its data");
        ++responses;
        pending = false;
      }
      if (lose_pll && beats != 0) {
        dut.pll_locked = 1;
      }
    }
    context.timeInc(5);
    dut.clk = 1;
    dut.eval();
    context.timeInc(5);
    ++cycles;
    return events;
  }

  int write32(uint32_t offset, uint32_t value) override {
    require(offset == 0x3010 && value == 1, "Host issued an unexpected startup write");
    ++commands;
    dut.s_awaddr = offset - 0x3000;
    dut.s_wdata = value;
    dut.s_wstrb = 15;
    dut.s_awvalid = 1;
    dut.s_wvalid = 0;
    dut.s_bready = 1;
    for (unsigned wait = 0; wait < 300; ++wait) {
      if (wait == 3) {
        dut.s_wvalid = 1;
      }
      const auto e = tick();
      if (e.aw) {
        dut.s_awvalid = 0;
      }
      if (e.w) {
        dut.s_wvalid = 0;
      }
      if (e.b) {
        dut.s_bready = 0;
        dut.eval();
        if (fail_after_command) {
          fail_read = true;
        }
        return e.bresp == 0 ? 0 : -1;
      }
    }
    require(false, "Startup write handshake timed out");
    return -1;
  }

  int read32(uint32_t offset, uint32_t* value) override {
    if (fail_read) {
      return -1;
    }
    require(offset >= 0x3000 && offset <= 0x3008 && offset % 4 == 0,
            "Host issued an unexpected startup read");
    dut.s_araddr = offset - 0x3000;
    dut.s_arvalid = 1;
    dut.s_rready = 1;
    for (unsigned wait = 0; wait < 300; ++wait) {
      const auto e = tick();
      if (e.ar) {
        dut.s_arvalid = 0;
      }
      if (e.r) {
        dut.s_rready = 0;
        dut.eval();
        *value = e.data;
        return e.rresp == 0 ? 0 : -1;
      }
    }
    require(false, "Startup read handshake timed out");
    return -1;
  }
};

int main() {
  StartupReport report;
  RtlMmio success;
  Startup startup(success);
  require(startup.initialize(&report) == StartupResult::success && report.scrub_started
          && !report.reused_ready && success.commands == 1 && success.responses == 2
          && success.beats == 5 && success.dut.memory_ready == 3,
          "Host startup failed with actual startup/scrub RTL");
  require(startup.initialize(&report) == StartupResult::success && report.reused_ready
          && !report.scrub_started && success.commands == 1,
          "Ready-board reuse restarted the destructive scrub");
  RtlMmio untrained;
  untrained.dut.init_done = 1;
  require(Startup(untrained).initialize(&report) == StartupResult::unsafe_state
          && untrained.commands == 0, "Untrained DDR started scrubbing");
  RtlMmio failed;
  failed.response = 2;
  require(Startup(failed).initialize(&report) == StartupResult::failed
          && failed.dut.memory_ready == 0 && failed.responses == 1,
          "Failed BRESP opened memory");
  RtlMmio dropped;
  dropped.lose_pll = true;
  require(Startup(dropped).initialize(&report) == StartupResult::failed
          && dropped.dut.memory_ready == 0, "PLL loss opened memory");
  RtlMmio stuck;
  stuck.hold_response = true;
  Startup bounded(stuck, std::chrono::milliseconds(10));
  require(bounded.initialize(&report) == StartupResult::timeout
          && stuck.dut.memory_ready == 0, "Missing final response opened memory");
  require(bounded.initialize(&report) == StartupResult::unsafe_state
          && stuck.commands == 1, "Timed-out scrub was restarted");
  RtlMmio lost;
  lost.fail_after_command = true;
  Startup uncertain(lost);
  require(uncertain.initialize(&report) == StartupResult::io_error,
          "MMIO failure after scrub command was ignored");
  require(uncertain.initialize(&report) == StartupResult::unsafe_state
          && lost.commands == 1, "Uncertain scrub was restarted");
  std::puts("PASSED: host startup against actual startup/scrub RTL, both-bank boundary, final BRESP ordering, ready reuse, untrained guard, AXI error, PLL loss, timeout and MMIO failure; reduced scrub range, no physical DDR claim");
}
