// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_afu_control.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>

static void require(bool value, const char* message) {
  if (!value) {
    std::fprintf(stderr, "FAILED: %s\n", message);
    std::exit(1);
  }
}

static unsigned checks = 0;

static void exercise(unsigned delay, unsigned response, unsigned strobe, unsigned loss) {
  VVX_ypcb_afu_control dut;
  dut.clk = 0;
  dut.reset = 1;
  dut.ready = 0;
  dut.eval();
  dut.clk = 1;
  dut.eval();
  dut.clk = 0;
  dut.reset = 0;
  bool aw = false, w = false, ar = false, b = false, r = false;
  bool target_aw = false, target_w = false, target_ar = false;
  unsigned target_writes = 0, target_reads = 0;
  unsigned write_wait = 0, read_wait = 0;
  bool lost = loss == 1;
  for (unsigned cycle = 0; cycle < 150; ++cycle) {
    if ((loss == 2 && target_aw) || (loss == 3 && target_w)
        || (loss == 4 && target_aw && target_w) || (loss == 5 && target_ar)) {
      lost = true;
    }
    dut.ready = !lost;
    dut.s_awvalid = !aw;
    dut.s_awaddr = 0x111c;
    dut.s_wvalid = !w && cycle >= delay % 3;
    dut.s_wdata = 0xabcd9573;
    dut.s_wstrb = strobe;
    dut.s_bready = cycle % 4 == 3;
    dut.s_arvalid = !ar && cycle >= (delay + 1) % 3;
    dut.s_araddr = 0x1128;
    dut.s_rready = cycle % 5 == 4;
    dut.m_awready = cycle % 4 == delay % 4;
    dut.m_wready = cycle % 5 == (delay + 2) % 5;
    dut.m_arready = cycle % 3 == delay % 3;
    dut.m_bvalid = target_aw && target_w && write_wait >= 5 && !lost;
    dut.m_bresp = response;
    dut.m_rvalid = target_ar && read_wait >= 5 && !lost;
    dut.m_rresp = response;
    dut.m_rdata = 0x89abcdef;
    dut.eval();
    if (dut.s_awvalid && dut.s_awready) {
      require(!aw, "Address accepted twice");
      aw = true;
    }
    if (dut.s_wvalid && dut.s_wready) {
      require(!w, "Payload accepted twice");
      w = true;
    }
    if (dut.s_arvalid && dut.s_arready) {
      require(!ar, "Read accepted twice");
      ar = true;
    }
    if (dut.m_awvalid && dut.m_awready) {
      require(!target_aw && !lost && dut.m_awaddr == 0x111c, "Target address differs");
      target_aw = true;
    }
    if (dut.m_wvalid && dut.m_wready) {
      require(!target_w && !lost && dut.m_wdata == 0xabcd9573
          && dut.m_wstrb == strobe, "Target payload/strobes differ");
      target_w = true;
    }
    if (dut.m_arvalid && dut.m_arready) {
      require(!target_ar && !lost && dut.m_araddr == 0x1128, "Target read differs");
      target_ar = true;
    }
    if (dut.m_bvalid && dut.m_bready) {
      ++target_writes;
    }
    if (dut.m_rvalid && dut.m_rready) {
      ++target_reads;
    }
    if (dut.s_bvalid && dut.s_bready) {
      require(!b && aw && w && dut.s_bresp == (loss ? 2 : response), "Write response differs");
      b = true;
    }
    if (dut.s_rvalid && dut.s_rready) {
      require(!r && ar, "Read response duplicated or unsolicited");
      const bool rejected = lost && target_reads == 0;
      require(dut.s_rresp == (rejected ? 2 : response)
          && dut.s_rdata == (rejected ? 0 : 0x89abcdef), "Read response differs");
      r = true;
    }
    if (lost) {
      require(!dut.m_awvalid && !dut.m_wvalid && !dut.m_arvalid
          && !dut.m_bready && !dut.m_rready, "Unready AFU still accessed");
    }
    dut.clk = 1;
    dut.eval();
    dut.clk = 0;
    if (target_aw && target_w) {
      ++write_wait;
    }
    if (target_ar) {
      ++read_wait;
    }
    if (b && r) {
      require(target_writes == (loss ? 0 : 1), "Wrong write target count");
      require(target_reads <= 1 && (loss || target_reads == 1), "Wrong read target count");
      ++checks;
      return;
    }
  }
  require(false, "Requests did not terminate within the bound");
}

int main() {
  for (unsigned delay = 0; delay < 12; ++delay) {
    for (unsigned response : {0u, 2u, 3u}) {
      for (unsigned strobe = 0; strobe < 16; ++strobe) {
        exercise(delay, response, strobe, 0);
      }
    }
    for (unsigned loss = 1; loss <= 5; ++loss) {
      exercise(delay, 0, 15, loss);
    }
  }
  std::printf("PASSED: AFU control readiness gate, %u concurrent read/write cases, independent channels/stalls, all strobes/responses, initial and in-flight readiness loss; target is a register oracle\n", checks);
}
