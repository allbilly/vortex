// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_control.h"
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

static int route(unsigned address) {
  if (address >= 0x8000 || address % 4 != 0) {
    return -1;
  }
  if (address < 0x2000) {
    return 0;
  }
  if (address < 0x3000) {
    return 1;
  }
  if (address < 0x4000) {
    return 2;
  }
  return address < 0x6000 ? 3 : 4;
}

static unsigned offset(unsigned address) {
  const std::array<unsigned, 5> bases = {0, 0x2000, 0x3000, 0x4000, 0x6000};
  return address - bases[route(address)];
}

template<size_t N>
static unsigned address_at(const VlWide<N>& value, unsigned index) {
  return (value[index / 2] >> ((index % 2) * 16)) & 0xffff;
}

static unsigned response(unsigned address) {
  return (address >> 2) % 4;
}

static uint32_t pattern(unsigned address) {
  return 0x9a000000u ^ (unsigned(route(address)) << 20) ^ (offset(address) * 0x10203u);
}

struct Target {
  bool address = false, data = false, bvalid = false, rvalid = false;
  unsigned b_due = 0, r_due = 0;
  unsigned awaddr = 0, araddr = 0, wstrb = 0;
  uint32_t wdata = 0;
  bool aw_stalled = false, w_stalled = false, ar_stalled = false;
  unsigned aw_held = 0, ar_held = 0, strobe_held = 0;
  uint32_t data_held = 0;
};

struct Events {
  bool aw, w, b, ar, r;
  unsigned bresp, rresp;
  uint32_t rdata;
};

class Test {
public:
  VVX_ypcb_control dut;
  unsigned cycles = 0, transactions = 0, target_writes = 0, target_reads = 0;
  std::array<unsigned, 5> writes{}, reads{};
  unsigned write_address = 0, read_address = 0, write_strobe = 0;
  uint32_t write_value = 0;
  bool pause = false;

  Test() {
    reset();
  }

  void reset() {
    targets = {};
    b_stalled = r_stalled = false;
    dut.s_awvalid = dut.s_wvalid = dut.s_arvalid = 0;
    dut.s_awaddr = dut.s_araddr = 0;
    dut.s_wdata = dut.s_wstrb = 0;
    dut.s_bready = dut.s_rready = 0;
    dut.reset = 1;
    for (unsigned index = 0; index < 4; ++index) {
      tick();
    }
    dut.reset = 0;
  }

  Events tick() {
    dut.m_awready = dut.m_wready = dut.m_arready = 0;
    dut.m_bvalid = dut.m_rvalid = dut.m_bresp = dut.m_rresp = 0;
    for (unsigned index = 0; index < 5; ++index) {
      auto& target = targets[index];
      dut.m_awready |= unsigned(!pause && !target.address && !target.bvalid
        && cycles % 7 == index) << index;
      dut.m_wready |= unsigned(!pause && !target.data && !target.bvalid
        && cycles % 9 == (index + 3) % 9) << index;
      dut.m_arready |= unsigned(!pause && !target.rvalid
        && cycles % 5 == index) << index;
      dut.m_bvalid |= unsigned(target.bvalid && cycles >= target.b_due) << index;
      dut.m_rvalid |= unsigned(target.rvalid && cycles >= target.r_due) << index;
      dut.m_bresp |= response(target.awaddr) << (index * 2);
      dut.m_rresp |= response(target.araddr) << (index * 2);
      dut.m_rdata[index] = target.rvalid ? pattern(target.araddr) : 0;
    }
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
      require(!(dut.m_awvalid & (dut.m_awvalid - 1)), "AW selected multiple targets");
      require(!(dut.m_wvalid & (dut.m_wvalid - 1)), "W selected multiple targets");
      require(!(dut.m_arvalid & (dut.m_arvalid - 1)), "AR selected multiple targets");
      for (unsigned index = 0; index < 5; ++index) {
        auto& target = targets[index];
        const unsigned awaddr = address_at(dut.m_awaddr, index);
        const unsigned araddr = address_at(dut.m_araddr, index);
        const unsigned strobe = (dut.m_wstrb >> (4 * index)) & 15;
        if (target.aw_stalled) {
          require(((dut.m_awvalid >> index) & 1) && awaddr == target.aw_held,
            "Downstream AW changed while stalled");
        }
        if (target.w_stalled) {
          require(((dut.m_wvalid >> index) & 1) && dut.m_wdata[index] == target.data_held
            && strobe == target.strobe_held, "Downstream W changed while stalled");
        }
        if (target.ar_stalled) {
          require(((dut.m_arvalid >> index) & 1) && araddr == target.ar_held,
            "Downstream AR changed while stalled");
        }
        target.aw_stalled = ((dut.m_awvalid & ~dut.m_awready) >> index) & 1;
        target.w_stalled = ((dut.m_wvalid & ~dut.m_wready) >> index) & 1;
        target.ar_stalled = ((dut.m_arvalid & ~dut.m_arready) >> index) & 1;
        target.aw_held = awaddr;
        target.ar_held = araddr;
        target.data_held = dut.m_wdata[index];
        target.strobe_held = strobe;
        if (((dut.m_awvalid & dut.m_awready) >> index) & 1) {
          require(route(write_address) == int(index) && awaddr == offset(write_address),
            "Write target/address differs");
          require(!target.address, "Duplicate write address");
          target.address = true;
          target.awaddr = write_address;
        }
        if (((dut.m_wvalid & dut.m_wready) >> index) & 1) {
          require(route(write_address) == int(index) && dut.m_wdata[index] == write_value
            && strobe == write_strobe, "Write data/strobe/target differs");
          require(!target.data, "Duplicate write data");
          target.data = true;
        }
        if (((dut.m_bvalid & dut.m_bready) >> index) & 1) {
          require(target.address && target.data, "B accepted before AW and W");
          target.address = target.data = target.bvalid = false;
          ++target_writes;
          ++writes[index];
        }
        if (target.address && target.data && !target.bvalid) {
          target.bvalid = true;
          target.b_due = cycles + 5 + index;
        }
        if (((dut.m_arvalid & dut.m_arready) >> index) & 1) {
          require(route(read_address) == int(index) && araddr == offset(read_address),
            "Read target/address differs");
          require(!target.rvalid, "Duplicate read address");
          target.rvalid = true;
          target.araddr = read_address;
          target.r_due = cycles + 11 - index;
        }
        if (((dut.m_rvalid & dut.m_rready) >> index) & 1) {
          target.rvalid = false;
          ++target_reads;
          ++reads[index];
        }
      }
    }
    dut.clk = 1;
    dut.eval();
    ++cycles;
    return events;
  }

  void exchange(unsigned wa, unsigned ra, unsigned sequence) {
    write_address = wa;
    read_address = ra;
    write_strobe = sequence % 16;
    write_value = 0x01020304u * sequence ^ 0x87654321u;
    bool aw_done = false, w_done = false, ar_done = false, b_done = false, r_done = false;
    const unsigned old_writes = target_writes, old_reads = target_reads;
    for (unsigned wait = 0; wait < 300; ++wait) {
      dut.s_awvalid = !aw_done && wait >= sequence % 3 * 4;
      dut.s_wvalid = !w_done && wait >= (2 - sequence % 3) * 4;
      dut.s_arvalid = !ar_done && wait >= sequence % 5;
      dut.s_awaddr = aw_done ? 0xffff : wa;
      dut.s_araddr = ar_done ? 0xffff : ra;
      dut.s_wdata = w_done ? ~write_value : write_value;
      dut.s_wstrb = w_done ? (write_strobe ^ 15) : write_strobe;
      dut.s_bready = wait >= 40 && wait % 7 == 2;
      dut.s_rready = wait >= 45 && wait % 9 == 3;
      const auto events = tick();
      aw_done |= events.aw;
      w_done |= events.w;
      ar_done |= events.ar;
      if (events.b) {
        require(!b_done && aw_done && w_done, "Missing/duplicate upstream write request");
        require(events.bresp == (route(wa) < 0 ? 3u : response(wa)), "B response differs");
        b_done = true;
      }
      if (events.r) {
        require(!r_done && ar_done, "Missing/duplicate upstream read request");
        require(events.rresp == (route(ra) < 0 ? 3u : response(ra)), "R response differs");
        require(events.rdata == (route(ra) < 0 ? 0u : pattern(ra)), "R payload differs");
        r_done = true;
      }
      if (b_done && r_done) {
        require(target_writes - old_writes == unsigned(route(wa) >= 0),
          "Rejected/valid write had unexpected target side effects");
        require(target_reads - old_reads == unsigned(route(ra) >= 0),
          "Rejected/valid read had unexpected target side effects");
        dut.s_awvalid = dut.s_wvalid = dut.s_arvalid = 0;
        ++transactions;
        return;
      }
    }
    require(false, "Control transaction timed out");
  }

private:
  std::array<Target, 5> targets{};
  bool b_stalled = false, r_stalled = false;
  unsigned b_held = 0, rresp_held = 0;
  uint32_t rdata_held = 0;
};

int main() {
  Test test;
  for (unsigned address = 0; address < 0x10000; address += 4) {
    test.exchange(address, (address * 13 + 0x18d0) & 0xffff, address / 4);
  }
  for (unsigned address = 1; address < 0x10000; address += 17) {
    test.exchange(address, (address * 7 + 2) & 0xffff, address);
  }
  for (unsigned index = 0; index < 5; ++index) {
    require(test.writes[index] > 500 && test.reads[index] > 500, "Target was not exercised");
  }
  test.pause = true;
  test.write_address = 0x4000;
  test.dut.s_awaddr = 0x4000;
  test.dut.s_awvalid = 1;
  while (!test.tick().aw) {}
  test.dut.s_awvalid = 0;
  for (unsigned wait = 0; wait < 10; ++wait) {
    test.tick();
  }
  test.reset();
  test.dut.s_araddr = 0x6000;
  test.dut.s_arvalid = 1;
  while (!test.tick().ar) {}
  test.dut.s_arvalid = 0;
  for (unsigned wait = 0; wait < 10; ++wait) {
    test.tick();
  }
  test.reset();
  test.pause = false;
  test.exchange(0x58d0, 0x78d0, 0x777);
  std::printf("PASSED: control router, %u concurrent read/write pairs, %u target writes, %u target reads, five windows, every DWORD, all strobes/responses, stalls and reset\n",
    test.transactions, test.target_writes, test.target_reads);
}
