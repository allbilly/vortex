// Copyright © 2019-2023
// Licensed under the Apache License, Version 2.0.

#include "vl_simulator.h"
#include "VVX_cp_dma_top.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static uint64_t timestamp = 0;
static bool trace_en = false;
double sc_time_stamp() { return timestamp; }
bool sim_trace_enabled() { return trace_en; }
void sim_trace_enable(bool enable) { trace_en = enable; }

static void expect(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

struct Port {
    CData &awvalid, &awready;
    QData &awaddr;
    CData &awid, &awlen, &wvalid, &wready;
    VlWide<16>& wdata;
    QData& wstrb;
    CData &wlast, &bvalid, &bready, &bid, &bresp;
    CData &arvalid, &arready;
    QData& araddr;
    CData &arid, &arlen, &rvalid, &rready;
    VlWide<16>& rdata;
    CData &rid, &rlast, &rresp;
};

#define PORT(top, prefix) Port{ \
    top->prefix##_awvalid, top->prefix##_awready, top->prefix##_awaddr, \
    top->prefix##_awid, top->prefix##_awlen, top->prefix##_wvalid, \
    top->prefix##_wready, top->prefix##_wdata, top->prefix##_wstrb, \
    top->prefix##_wlast, top->prefix##_bvalid, top->prefix##_bready, \
    top->prefix##_bid, top->prefix##_bresp, top->prefix##_arvalid, \
    top->prefix##_arready, top->prefix##_araddr, top->prefix##_arid, \
    top->prefix##_arlen, top->prefix##_rvalid, top->prefix##_rready, \
    top->prefix##_rdata, top->prefix##_rid, top->prefix##_rlast, top->prefix##_rresp}

struct AxiSlave {
    struct PendingWrite {
        uint64_t address, strobe;
        std::array<uint32_t, 16> data;
    };

    static constexpr uint64_t BASE = 0x1000;
    static constexpr unsigned SIZE = 65536;
    std::array<uint8_t, SIZE> memory{};
    bool reading = false, writing = false, response = false;
    uint64_t read_address = 0, write_address = 0;
    unsigned read_left = 0, write_left = 0, cycle_count = 0;
    uint8_t read_id = 0, write_id = 0;
    unsigned read_requests = 0, write_requests = 0;
    unsigned visibility_delay = 0, pending_delay = 0, stale_readbacks = 0;
    std::vector<PendingWrite> pending_writes;
    std::array<uint32_t, 16> read_data{};
    bool read_from_pending = false;

    void store(const PendingWrite& write) {
        for (unsigned byte = 0; byte < 64; ++byte) {
            if ((write.strobe >> byte) & 1) {
                memory.at(write.address - BASE + byte) =
                    uint8_t(write.data[byte / 4] >> ((byte % 4) * 8));
            }
        }
    }

    void capture_read() {
        read_from_pending = false;
        for (const auto& write : pending_writes) {
            read_from_pending |= write.address == read_address;
        }
        for (unsigned word = 0; word < 16; ++word) {
            uint32_t value = 0;
            for (unsigned byte = 0; byte < 4; ++byte) {
                value |= uint32_t(memory.at(read_address - BASE + word * 4 + byte)) << (byte * 8);
            }
            read_data[word] = value;
        }
    }

    void drive(Port port) {
        port.arready = !reading && cycle_count % 3 != 0;
        port.rvalid = reading;
        port.rid = read_id;
        port.rlast = read_left == 1;
        port.rresp = 0;
        if (reading) {
            for (unsigned word = 0; word < 16; ++word) {
                port.rdata[word] = read_data[word];
            }
        }
        port.awready = !writing && !response && pending_writes.empty() && cycle_count % 5 != 0;
        port.wready = writing && cycle_count % 7 < 5;
        port.bvalid = response;
        port.bid = write_id;
        port.bresp = 0;
    }

    void step(Port port) {
        if (port.arvalid && port.arready) {
            expect((port.araddr & 63) == 0, "Unaligned full-width read address");
            expect((port.araddr & 4095) + (unsigned(port.arlen) + 1) * 64 <= 4096,
                   "Read burst crosses 4 KiB");
            reading = true;
            read_address = port.araddr;
            read_left = unsigned(port.arlen) + 1;
            read_id = port.arid;
            ++read_requests;
            capture_read();
        } else if (port.rvalid && port.rready) {
            stale_readbacks += read_from_pending;
            read_address += 64;
            --read_left;
            reading = read_left != 0;
            if (reading) {
                capture_read();
            }
        }
        if (port.awvalid && port.awready) {
            expect((port.awaddr & 63) == 0, "Unaligned full-width write address");
            expect((port.awaddr & 4095) + (unsigned(port.awlen) + 1) * 64 <= 4096,
                   "Write burst crosses 4 KiB");
            writing = true;
            write_address = port.awaddr;
            write_left = unsigned(port.awlen) + 1;
            write_id = port.awid;
            ++write_requests;
        }
        if (port.wvalid && port.wready) {
            expect(bool(port.wlast) == (write_left == 1), "Incorrect WLAST");
            PendingWrite write{write_address, port.wstrb, {}};
            for (unsigned word = 0; word < 16; ++word) {
                write.data[word] = port.wdata[word];
            }
            if (visibility_delay != 0) {
                pending_writes.push_back(write);
            } else {
                store(write);
            }
            write_address += 64;
            --write_left;
            if (write_left == 0) {
                writing = false;
                response = true;
                pending_delay = visibility_delay;
            }
        }
        if (port.bvalid && port.bready) {
            response = false;
        }
        if (pending_delay != 0 && --pending_delay == 0) {
            for (const auto& write : pending_writes) {
                store(write);
            }
            pending_writes.clear();
        }
        ++cycle_count;
    }
};

static void cycle(vl_simulator<VVX_cp_dma_top>& sim, AxiSlave& host,
                  AxiSlave& device, uint64_t& tick) {
    auto* top = sim.operator->();
    host.drive(PORT(top, h));
    device.drive(PORT(top, d));
    top->eval();
    host.drive(PORT(top, h));
    device.drive(PORT(top, d));
    top->eval();
    host.step(PORT(top, h));
    device.step(PORT(top, d));
    tick = sim.step(tick, 2);
    host.drive(PORT(top, h));
    device.drive(PORT(top, d));
    top->eval();
}

static void transfer(vl_simulator<VVX_cp_dma_top>& sim, AxiSlave& host,
                     AxiSlave& device, uint64_t& tick, uint8_t opcode,
                     uint64_t source, uint64_t destination, unsigned size) {
    for (unsigned byte = 0; byte < AxiSlave::SIZE; ++byte) {
        host.memory[byte] = uint8_t(byte * 17 + byte / 64 + 0x27);
        device.memory[byte] = uint8_t(byte * 23 + byte / 32 + 0x91);
    }
    auto expected_host = host.memory;
    auto expected_device = device.memory;
    const auto& input = opcode == 1 ? host.memory : device.memory;
    auto& output = opcode == 2 ? expected_host : expected_device;
    std::memcpy(output.data() + destination - AxiSlave::BASE,
                input.data() + source - AxiSlave::BASE, size);

    sim->grant = 0;
    for (unsigned idle = 0; idle < 2; ++idle) {
        cycle(sim, host, device, tick);
    }
    for (unsigned word = 0; word < 9; ++word) {
        sim->cmd_packed[word] = 0;
    }
    sim->cmd_packed[2] = size;
    sim->cmd_packed[4] = uint32_t(source);
    sim->cmd_packed[5] = uint32_t(source >> 32);
    sim->cmd_packed[6] = uint32_t(destination);
    sim->cmd_packed[7] = uint32_t(destination >> 32);
    sim->cmd_packed[8] = opcode;
    const unsigned prior_requests = host.read_requests + device.read_requests
                                 + host.write_requests + device.write_requests;
    const unsigned prior_stale = host.stale_readbacks;
    sim->grant = 1;
    cycle(sim, host, device, tick);
    cycle(sim, host, device, tick);
    sim->grant = 0;
    bool done = sim->done;
    for (unsigned wait = 0; wait < 6000 && !done; ++wait) {
        cycle(sim, host, device, tick);
        done = sim->done;
    }
    expect(done, "DMA timed out");
    expect(host.pending_writes.empty(), "DMA completed before posted host writes became visible");
    if (host.memory != expected_host || device.memory != expected_device) {
        std::fprintf(stderr, "opcode=%u src=0x%llx dst=0x%llx bytes=%u\n",
                     unsigned(opcode), static_cast<unsigned long long>(source),
                     static_cast<unsigned long long>(destination), size);
        expect(false, "Copied data or untouched guard bytes differ");
    }
    if (size == 0) {
        expect(prior_requests == host.read_requests + device.read_requests
             + host.write_requests + device.write_requests, "Zero-size DMA issued traffic");
    } else if (opcode == 2 && host.visibility_delay != 0) {
        expect(host.stale_readbacks > prior_stale, "Posted-write case did not exercise stale read-back");
    }
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    vl_simulator<VVX_cp_dma_top> sim;
    AxiSlave host, device;
    uint64_t tick = 0;
    sim->grant = 0;
    for (unsigned word = 0; word < 9; ++word) {
        sim->cmd_packed[word] = 0;
    }
    tick = sim.reset(tick);
    const std::array<unsigned, 6> lengths = {1, 13, 63, 64, 65, 4097};
    const std::array<unsigned, 4> destination_offsets = {0, 1, 31, 63};
    unsigned cases = 0;
    for (uint8_t opcode = 1; opcode <= 3; ++opcode) {
        transfer(sim, host, device, tick, opcode, 0x2000, 0x6000, 0);
        transfer(sim, host, device, tick, opcode, 0x2000, 0x6000, 64);
        transfer(sim, host, device, tick, opcode, 0x2000, 0x6000, 8192);
        cases += 3;
        for (unsigned source_offset = 0; source_offset < 64; ++source_offset) {
            for (unsigned index = 0; index < destination_offsets.size(); ++index) {
                transfer(sim, host, device, tick, opcode, 0x2fc0 + source_offset,
                         0x6fc0 + destination_offsets[index],
                         lengths[(source_offset + index) % lengths.size()]);
                ++cases;
            }
        }
    }
    host.visibility_delay = 35;
    transfer(sim, host, device, tick, 2, 0x2000, 0x6000, 0);
    ++cases;
    const std::array<unsigned, 3> posted_lengths = {13, 65, 4097};
    for (unsigned source_offset : {0u, 17u, 63u}) {
        for (unsigned index = 0; index < 3; ++index) {
            transfer(sim, host, device, tick, 2, 0x2fc0 + source_offset,
                     0x6fc0 + destination_offsets[index + 1], posted_lengths[index]);
            ++cases;
        }
    }
    std::printf("PASSED: %u DMA cases, upload/download/copy, byte offsets, tails, guards, 4 KiB splits, backpressure and posted writes (%u stale read-backs)\n",
                cases, host.stale_readbacks);
    return 0;
}
