// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_scrub.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>

static void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

static void run(unsigned failed_response) {
    VVX_ypcb_scrub dut;
    dut.clk = 0;
    dut.reset = 1;
    dut.start = 0;
    dut.init_ready = 0;
    dut.m_awready = dut.m_wready = dut.m_bvalid = dut.m_bresp = 0;
    for (unsigned reset = 0; reset < 4; ++reset) {
        dut.clk = 0; dut.eval(); dut.clk = 1; dut.eval();
    }
    require(!dut.busy && !dut.done && !dut.error, "Scrub reset state differs");
    dut.reset = 0;
    dut.start = 1;
    unsigned burst = 0, beat = 0, beats = 0, total = 0;
    bool writing = false, response = false;
    unsigned response_due = 0;
    uint64_t expected_address = 0x3ffff000;
    for (unsigned cycle = 0; cycle < 10000; ++cycle) {
        dut.init_ready = cycle < 20 ? 1 : 2;
        dut.m_awready = !writing && !response && cycle % 5 == 1;
        dut.m_wready = writing && cycle % 7 > 1;
        dut.m_bvalid = response && cycle >= response_due;
        dut.m_bresp = burst == 2 ? failed_response : 0;
        dut.clk = 0; dut.eval();
        if (cycle < 20) {
            require(!dut.m_awvalid && !dut.m_wvalid, "Scrub started before CH1 PHY were ready");
        }
        if (dut.m_awvalid && dut.m_awready) {
            require(dut.m_awaddr == expected_address, "Scrub skipped or repeated a line");
            require((dut.m_awaddr & 4095) + (unsigned(dut.m_awlen) + 1) * 64 <= 4096,
                    "Scrub burst crosses 4 KiB");
            beats = unsigned(dut.m_awlen) + 1;
            writing = true;
            beat = 0;
            ++burst;
        }
        if (dut.m_wvalid && dut.m_wready) {
            require(writing && bool(dut.m_wlast) == (beat + 1 == beats), "Incorrect scrub WLAST");
            require(dut.m_wstrb == ~uint64_t(0), "Partial ECC initialization write");
            for (unsigned word = 0; word < 16; ++word) {
                require(dut.m_wdata[word] == 0, "Nonzero scrub data");
            }
            ++beat; ++total;
            if (beat == beats) {
                writing = false;
                response = true;
                response_due = cycle + 13;
            }
        }
        if (dut.m_bvalid && dut.m_bready) {
            response = false;
            expected_address += beats * 64;
        }
        dut.clk = 1; dut.eval();
        if (dut.done || dut.error) {
            require(!dut.busy && !dut.m_awvalid && !dut.m_wvalid, "Terminal scrub still issues traffic");
            require(bool(dut.error) == (failed_response != 0), "Scrub error status differs");
            if (!failed_response) {
                require(total == 197 && expected_address == 0x40002140 && burst == 4,
                        "Scrub coverage or final tail differs");
            } else {
                require(burst == 2 && total == 128, "Scrub did not stop after AXI error");
            }
            for (unsigned hold = 0; hold < 20; ++hold) {
                dut.clk = 0; dut.eval(); dut.clk = 1; dut.eval();
                require(!dut.m_awvalid && !dut.m_wvalid, "Scrub restarted while start remained high");
            }
            std::printf("Verified scrub: %u beats, %u bursts, response %u\n", total, burst, failed_response);
            return;
        }
    }
    require(false, "Scrub timed out");
}

int main() {
    run(0); run(2); run(3);
    std::puts("PASSED: ECC scrub, CH1 and 4 KiB boundaries, full byte enables, zero data, final tail, PHY readiness, backpressure and errors");
    return 0;
}
