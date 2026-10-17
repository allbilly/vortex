// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_ddr_control.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

static bool error(unsigned address) {
  return (address / 4) % 19 == 0;
}

struct Events {
  bool aw, w, b, ar, r;
  unsigned bresp, rresp;
  uint32_t rdata;
};

class Test {
public:
  VVX_ypcb_ddr_control dut;
  unsigned cycles = 0, pairs = 0, writes = 0, reads = 0;
  unsigned write_address = 0, read_address = 0, write_strobe = 0;
  uint32_t write_value = 0, read_value = 0;
  bool pause = false;
  std::array<uint32_t, 2048> memory{};

  Test() {
    for (unsigned index = 0; index < memory.size(); ++index) {
      memory[index] = 0x12345678u ^ (index * 0x1020304u);
    }
    reset();
  }

  void reset() {
    active = false;
    b_stalled = r_stalled = false;
    dut.s_awvalid = dut.s_wvalid = dut.s_arvalid = 0;
    dut.s_awaddr = dut.s_araddr = dut.s_wdata = dut.s_wstrb = 0;
    dut.s_bready = dut.s_rready = 0;
    dut.wb_ack = dut.wb_err = dut.wb_dat_r = 0;
    dut.reset = 1;
    for (unsigned index = 0; index < 4; ++index) {
      tick();
    }
    dut.reset = 0;
  }

  Events tick() {
    dut.wb_ack = !pause && active && cycles >= due;
    // ERR without ACK and simultaneous ERR/ACK must both terminate with SLVERR.
    dut.wb_err = !pause && active && cycles >= due && held_error;
    if (held_error && (held_address % 2 == 0)) {
      dut.wb_ack = 0;
    }
    dut.wb_dat_r = held_read_data;
    dut.clk = 0;
    dut.eval();
    const Events events = {bool(dut.s_awvalid && dut.s_awready),
      bool(dut.s_wvalid && dut.s_wready), bool(dut.s_bvalid && dut.s_bready),
      bool(dut.s_arvalid && dut.s_arready), bool(dut.s_rvalid && dut.s_rready),
      dut.s_bresp, dut.s_rresp, dut.s_rdata};
    if (!dut.reset) {
      if (b_stalled) {
        require(dut.s_bvalid && dut.s_bresp == b_held, "B changed while stalled");
      }
      if (r_stalled) {
        require(dut.s_rvalid && dut.s_rresp == rresp_held && dut.s_rdata == rdata_held,
          "R changed while stalled");
      }
      b_stalled = dut.s_bvalid && !dut.s_bready;
      r_stalled = dut.s_rvalid && !dut.s_rready;
      b_held = dut.s_bresp;
      rresp_held = dut.s_rresp;
      rdata_held = dut.s_rdata;
      if (dut.wb_cyc) {
        require(dut.wb_stb && dut.wb_adr < memory.size() && dut.wb_sel == 15,
          "Wishbone cycle/select/address width differs");
        if (!active) {
          const unsigned expected = dut.wb_we ? write_address : read_address;
          require(expected % 4 == 0 && dut.wb_adr == expected / 4,
            "Byte-to-word address conversion differs");
          require(!dut.wb_we || (write_strobe == 15 && dut.wb_dat_w == write_value),
            "Rejected/partial write reached Wishbone or data differs");
          active = true;
          held_address = dut.wb_adr;
          held_write = dut.wb_we;
          held_data = dut.wb_dat_w;
          held_error = error(expected);
          held_read_data = memory[held_address];
          due = cycles + 3 + held_address % 7;
          if (held_write) {
            ++writes;
          } else {
            ++reads;
            read_value = held_error ? 0u : held_read_data;
          }
        } else {
          require(dut.wb_adr == held_address && dut.wb_we == held_write
            && dut.wb_dat_w == held_data, "Wishbone payload changed before termination");
        }
        if (dut.wb_ack || dut.wb_err) {
          if (held_write && !held_error) {
            memory[held_address] = held_data;
          }
          active = false;
        }
      } else {
        require(!active && !dut.wb_stb, "Wishbone cycle dropped before termination");
      }
    }
    dut.clk = 1;
    dut.eval();
    ++cycles;
    return events;
  }

  void exchange(unsigned wa, unsigned ra, unsigned mask, unsigned sequence) {
    write_address = wa;
    read_address = ra;
    write_strobe = mask;
    write_value = sequence * 0x01020304u ^ 0x87654321u;
    read_value = 0;
    bool aw_done = false, w_done = false, ar_done = false, b_done = false, r_done = false;
    const unsigned old_writes = writes, old_reads = reads;
    const auto old_memory = memory;
    unsigned expected_b = 0;
    if (wa % 4 != 0) {
      expected_b = 3;
    } else if (mask != 0 && (mask != 15 || error(wa))) {
      expected_b = 2;
    }
    const unsigned expected_r = ra % 4 != 0 ? 3 : error(ra) ? 2 : 0;
    for (unsigned wait = 0; wait < 300; ++wait) {
      dut.s_awvalid = !aw_done && wait >= sequence % 3 * 3;
      dut.s_wvalid = !w_done && wait >= (2 - sequence % 3) * 3;
      dut.s_arvalid = !ar_done && wait >= sequence % 5;
      dut.s_awaddr = aw_done ? 0x1fff : wa;
      dut.s_araddr = ar_done ? 0x1fff : ra;
      dut.s_wdata = w_done ? ~write_value : write_value;
      dut.s_wstrb = w_done ? (mask ^ 15) : mask;
      dut.s_bready = wait >= 40 && wait % 7 == 2;
      dut.s_rready = wait >= 45 && wait % 9 == 3;
      const auto events = tick();
      aw_done |= events.aw;
      w_done |= events.w;
      ar_done |= events.ar;
      if (events.b) {
        require(!b_done && aw_done && w_done, "B preceded request or repeated");
        require(events.bresp == expected_b, "Write response differs");
        b_done = true;
      }
      if (events.r) {
        require(!r_done && ar_done, "R preceded request or repeated");
        require(events.rresp == expected_r && events.rdata == read_value,
          "Read response/data differs");
        r_done = true;
      }
      if (b_done && r_done) {
        require(writes - old_writes == unsigned(wa % 4 == 0 && mask == 15),
          "Wishbone write count differs");
        require(reads - old_reads == unsigned(ra % 4 == 0), "Wishbone read count differs");
        for (unsigned word = 0; word < memory.size(); ++word) {
          const uint32_t expected = wa % 4 == 0 && mask == 15 && !error(wa)
            && word == wa / 4 ? write_value : old_memory[word];
          require(memory[word] == expected, "Rejected/partial write changed CSR storage");
        }
        dut.s_awvalid = dut.s_wvalid = dut.s_arvalid = 0;
        ++pairs;
        return;
      }
    }
    require(false, "DDR control timed out");
  }

private:
  bool active = false, held_write = false, held_error = false;
  unsigned held_address = 0, due = 0;
  uint32_t held_data = 0, held_read_data = 0;
  bool b_stalled = false, r_stalled = false;
  unsigned b_held = 0, rresp_held = 0;
  uint32_t rdata_held = 0;
};

int main() {
  Test test;
  unsigned sequence = 0;
  for (unsigned address = 0; address < 0x2000; address += 4) {
    test.exchange(address, (address * 13 + 0x18d0) & 0x1fff, 15, ++sequence);
  }
  for (unsigned mask = 0; mask < 16; ++mask) {
    for (unsigned address = 0; address < 0x2000; address += 124) {
      test.exchange(address, (address + 0x801) & 0x1fff, mask, ++sequence);
    }
  }
  for (unsigned address = 1; address < 0x2000; address += 3) {
    test.exchange(address, (address * 7 + 2) & 0x1fff, 15, ++sequence);
  }
  test.pause = true;
  test.read_address = 0x18d0;
  test.dut.s_araddr = 0x18d0;
  test.dut.s_arvalid = 1;
  while (!test.tick().ar) {}
  test.dut.s_arvalid = 0;
  for (unsigned wait = 0; wait < 20; ++wait) {
    test.tick();
  }
  test.reset();
  test.pause = false;
  test.exchange(0x18d0, 0x18d0, 15, ++sequence);
  test.exchange(0x1ffc, 0x1ffc, 15, ++sequence);
  std::printf("PASSED: DDR control, %u concurrent pairs, %u Wishbone writes, %u Wishbone reads, 8 KiB, all byte masks, stalls, ERR/ACK priority and active-cycle reset\n",
    test.pairs, test.writes, test.reads);
}
