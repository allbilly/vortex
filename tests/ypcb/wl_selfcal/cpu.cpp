// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <Vselfcal_top.h>
#include <verilated.h>
#include "selfcal_cfg.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <memory>
#include <vector>

namespace {
using Read = uint32_t (*)(uint32_t);
using Write = void (*)(uint32_t, uint32_t);
Read read_csr;
Write write_csr, write_mailbox;
std::unique_ptr<VerilatedContext> context;
std::unique_ptr<Vselfcal_top> dut;
std::vector<uint8_t> firmware;
uint64_t cycles, row_start;
uint32_t terminal, serviced, max_row, phase0_command;
uint32_t address, data, select;
unsigned delay;
bool pending, writing, active_row;

void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "CPU FAIL: %s at cycle %llu\n", message,
                     static_cast<unsigned long long>(cycles));
        std::exit(1);
    }
}

void cycle() {
    dut->sys_clk = 0;
    dut->wb_ack = dut->wb_err = 0;
    dut->eval();
    bool accepted = false;
    if (dut->wb_cyc && dut->wb_stb) {
        if (!pending) {
            address = dut->wb_adr * 4;
            data = dut->wb_dat_w;
            select = dut->wb_sel;
            writing = dut->wb_we;
            delay = (serviced * 13u + 5u) % 7u + 1u;
            pending = true;
        } else {
            require(address == dut->wb_adr * 4 && data == dut->wb_dat_w
                    && select == dut->wb_sel && writing == bool(dut->wb_we),
                    "CPU changed a backpressured CSR access");
        }
        if (--delay == 0) {
            require(select == 15, "Partial CSR access");
            if (writing) {
                if (address == CH[0].pi_command[0]) phase0_command = data;
                if (address == CH[0].pi_command_issue[0] && data == 1) {
                    if (phase0_command == 9) {
                        require(!active_row, "Nested activate");
                        active_row = true;
                        row_start = cycles;
                    } else if (phase0_command == 11) {
                        require(active_row, "Precharge without activate");
                        const uint64_t span = cycles - row_start;
                        require(span <= 3510, "Open-row interval exceeded tRAS maximum");
                        if (span > max_row) max_row = span;
                        active_row = false;
                    }
                }
                write_csr(address, data);
                if (address == CSR_SELFCAL_STATE && (data & 128)) terminal = data;
            } else {
                dut->wb_dat_r = read_csr(address);
            }
            dut->wb_ack = 1;
            accepted = true;
            ++serviced;
        }
    } else {
        require(!pending, "CPU dropped a backpressured CSR access");
    }
    dut->eval();
    dut->sys_clk = 1;
    dut->eval();
    ++cycles;
    if (accepted) pending = false;
    dut->sys_clk = 0;
    dut->eval();
}
}

extern "C" {
void sim_firmware(const char* path) {
    std::ifstream file(path, std::ios::binary);
    require(file.good(), "Cannot read firmware");
    firmware.assign(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
    require(!firmware.empty() && firmware.size() <= 16384, "Invalid firmware size");
}

void selfcal_host_setup(Read read, Write write, Write mailbox) {
    dut.reset();
    context.reset();
    context = std::make_unique<VerilatedContext>();
    dut = std::make_unique<Vselfcal_top>(context.get());
    read_csr = read;
    write_csr = write;
    write_mailbox = mailbox;
    cycles = row_start = terminal = serviced = max_row = phase0_command = 0;
    pending = writing = active_row = false;
    dut->sys_clk = 0;
    dut->sys_rst = dut->hold = 1;
    dut->wb_ack = dut->wb_err = dut->wb_dat_r = 0;
    dut->mem_adr = dut->mem_dat = dut->mem_we = dut->mbox_adr = 0;
    for (unsigned i = 0; i < 16; ++i) cycle();
    dut->sys_rst = 0;
    for (unsigned i = 0; i < 16; ++i) cycle();
    require(dut->status == 0x5ca10019u, "Unexpected held CPU status");
    auto word = [](unsigned index) {
        uint32_t value = 0;
        for (unsigned byte = 0; byte < 4; ++byte) {
            if (index * 4 + byte < firmware.size()) {
                value |= uint32_t(firmware[index * 4 + byte]) << (byte * 8);
            }
        }
        return value;
    };
    for (unsigned index = 0; index < 4096; ++index) {
        dut->mem_adr = index;
        dut->mem_dat = word(index);
        dut->mem_we = 1;
        cycle();
        dut->mem_we = 0;
        cycle();
    }
    for (unsigned index = 0; index < 4096; ++index) {
        dut->mem_adr = index;
        cycle();
        cycle();
        require(dut->mem_rdat == word(index), "Firmware BRAM readback mismatch");
    }
}

uint64_t selfcal_host_now() {
    return cycles;
}

uint32_t ypcb_wl_calibrate() {
    dut->hold = 0;
    while (!terminal && cycles < 3000000000ull && !(dut->status & 32)) cycle();
    require(terminal != 0, "No terminal state within 30 seconds of modeled CPU time");
    require(!(dut->status & 32), "CPU bus fault");
    require(!active_row, "CPU finished with a DDR row left active");
    for (unsigned index = 0; index < 128; ++index) {
        dut->mbox_adr = index;
        cycle();
        cycle();
        write_mailbox(index, dut->mbox_dat);
    }
    std::printf("CPU PASS: %llu cycles, %u MMIO, max row %u cycles, state %u\n",
                static_cast<unsigned long long>(cycles), serviced, max_row, terminal);
    std::fflush(stdout);
    return terminal;
}
}
