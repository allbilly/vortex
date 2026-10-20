// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <Vselfcal_top.h>
#include <verilated.h>
#include <ypcb_calibration_abi.h>
#include "../ddr/oracle.h"
#include "config.h"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <memory>

using namespace ypcb_test;

class Simulation {
public:
  CsrOracle oracle;
  Vselfcal_top dut;
  uint64_t cycles = 0;
  uint32_t state = 0;
  bool inject_error = false;
  bool pending = false;
  unsigned serviced = 0;

  Simulation() {
    dut.sys_clk = 0;
    dut.sys_rst = 1;
    dut.hold = 1;
    dut.wb_ack = dut.wb_err = dut.wb_dat_r = 0;
    dut.mem_adr = dut.mem_dat = dut.mem_we = dut.mbox_adr = 0;
    for (unsigned i = 0; i < 8; ++i) tick();
    dut.sys_rst = 0;
    for (unsigned i = 0; i < 8; ++i) tick();
    require(dut.status == 0x5ca10019u, "CPU status/hold/BRAM geometry differs");
  }

  void tick() {
    dut.sys_clk = 0;
    dut.wb_ack = dut.wb_err = 0;
    dut.eval();
    bool accepted = false;
    if (dut.wb_cyc && dut.wb_stb) {
      if (!pending) {
        address = dut.wb_adr;
        data = dut.wb_dat_w;
        write = dut.wb_we;
        select = dut.wb_sel;
        delay = (serviced * 13u + 5u) % 7u + 1u;
        pending = true;
      } else {
        require(address == dut.wb_adr && data == dut.wb_dat_w
                && write == dut.wb_we && select == dut.wb_sel,
                "CPU changed a backpressured bus request");
      }
      if (--delay == 0) {
        require(select == 15, "CSR access is not a whole word");
        uint32_t value = 0;
        if (inject_error) {
          dut.wb_err = 1;
        } else {
          const uint32_t offset = address * 4;
          int result;
          if (write) {
            result = oracle.write32(0x6000 + offset, data);
            if (offset == cfg_ddrctrl_selfcal_state) state = data;
          } else {
            result = oracle.read32(0x6000 + offset, &value);
          }
          require(result == 0, "Calibration CPU MMIO oracle failed");
          dut.wb_dat_r = value;
          dut.wb_ack = 1;
        }
        accepted = true;
        ++serviced;
      }
    } else {
      require(!pending, "CPU dropped a backpressured bus request");
    }
    dut.eval();
    dut.sys_clk = 1;
    dut.eval();
    ++cycles;
    if (accepted) pending = false;
    dut.sys_clk = 0;
    dut.eval();
  }

  uint32_t mailbox(unsigned index) {
    dut.mbox_adr = index;
    tick();
    tick();
    return dut.mbox_dat;
  }

  void hold() {
    dut.hold = 1;
    for (unsigned i = 0; i < 100 && !(dut.status & 1); ++i) tick();
    require((dut.status & 1) && !pending && !dut.wb_cyc,
            "Holding the CPU did not drain its bus request");
    for (unsigned i = 0; i < 8; ++i) tick();
  }

  void run(bool pause) {
    dut.hold = 0;
    bool paused = false;
    while (state != YPCB_CAL_READY && state != YPCB_CAL_FAILED && cycles < 500000000) {
      tick();
      if (pause && !paused && pending && serviced > 10) {
        hold();
        // Firmware starts again after a hold, so discard the interrupted initialization oracle.
        oracle = CsrOracle{};
        state = 0;
        dut.hold = 0;
        paused = true;
      }
    }
    require(state == YPCB_CAL_READY || state == YPCB_CAL_FAILED,
            "Calibration CPU did not finish within its cycle budget");
    require(!(dut.status & 32), "Calibration CPU reported a bus error");
  }

private:
  uint32_t address = 0, data = 0, select = 0;
  unsigned delay = 0;
  bool write = false;
};

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  auto sim = std::make_unique<Simulation>();
  sim->dut.mem_adr = 4095;
  sim->dut.mem_dat = 0xa53cc35a;
  sim->dut.mem_we = 1;
  sim->tick();
  sim->dut.mem_we = 0;
  sim->tick();
  sim->tick();
  require(sim->dut.mem_rdat == 0xa53cc35a, "Held CPU BRAM upload/readback differs");
  sim->run(true);
  require(sim->state == YPCB_CAL_READY && sim->mailbox(YPCB_CAL_MB_STATE) == YPCB_CAL_READY,
          "CPU firmware did not pass known PHY responses");
  require(sim->mailbox(YPCB_CAL_MB_MAGIC) == YPCB_CAL_MAGIC
          && sim->mailbox(YPCB_CAL_MB_PROBES) == 6942
          && sim->mailbox(YPCB_CAL_MB_FAILED_LANE) == 9,
          "CPU firmware result mailbox differs");
  const auto max_row = sim->mailbox(YPCB_CAL_MB_MAX_ROW_CYCLES);
  require(max_row > 0 && max_row <= 3510, "CPU exceeded physical open-row cycle budget");
  for (unsigned lane = 0; lane < 9; ++lane) {
    const uint32_t value = sim->mailbox(YPCB_CAL_MB_LANES + lane);
    require((value & 255) == CsrOracle::slip(lane, 1)
            && ((value >> 8) & 255) == CsrOracle::first(lane)
            && ((value >> 16) & 255) == CsrOracle::last(lane), "CPU trained the wrong eye");
  }
  std::printf("CPU PASS: %llu cycles, %u MMIO, 6942 probes, nine lanes, max row %u cycles\n",
              static_cast<unsigned long long>(sim->cycles), sim->serviced, max_row);

  sim = std::make_unique<Simulation>();
  sim->oracle.broken_lane = 0;
  sim->run(false);
  require(sim->state == YPCB_CAL_FAILED && sim->mailbox(YPCB_CAL_MB_ERROR) == 2
          && sim->mailbox(YPCB_CAL_MB_FAILED_LANE) == 0,
          "CPU ignored a failed physical lane");
  sim->hold();
  require(sim->oracle.banks[1].registers[cfg::ddrctrl_init_done / 4] == 0
          && sim->oracle.banks[1].registers[cfg::ddrctrl_init_error / 4] == 1,
          "CPU published memory readiness after failure");

  sim = std::make_unique<Simulation>();
  sim->inject_error = true;
  sim->dut.hold = 0;
  for (unsigned i = 0; i < 30000 && !(sim->dut.status & 32); ++i) sim->tick();
  require(sim->dut.status & 32, "CPU lost an actual Wishbone error");
  sim->hold();
  require(!(sim->dut.status & 32), "Held CPU did not clear sticky bus error");
  std::puts("PASSED: actual RV32I CPU, BRAM upload, reset/restart, bus stalls, error propagation, failure cleanup");
}
