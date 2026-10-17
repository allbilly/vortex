// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_pcie.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <map>
#include <vector>

static void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

struct Request {
    bool wide = false, write = false, digest = false;
    unsigned length = 1, first = 15, last = 0, type = 0;
    unsigned traffic_class = 0, attributes = 0;
    uint64_t address = 0xabc04024;
    uint32_t value = 0;
    uint16_t requester = 0x7a19;
    uint8_t tag = 0;

    std::vector<uint32_t> words() const {
        std::vector<uint32_t> result = {
            ((wide ? 1u : 0u) | (write ? 2u : 0u)) << 29 | type << 24
                | traffic_class << 20 | (attributes & 4) << 16
                | (attributes & 3) << 12 | (digest ? 1u << 15 : 0u) | (length & 1023),
            uint32_t(requester) << 16 | uint32_t(tag) << 8 | last << 4 | first
        };
        if (wide) {
            result.push_back(address >> 32);
        }
        result.push_back(uint32_t(address));
        if (write) {
            result.insert(result.end(), length, value);
        }
        if (digest) {
            result.push_back(0x19572a3c);
        }
        return result;
    }
};

struct Completion {
    std::vector<uint32_t> words;
};

class Test {
public:
    VVX_ypcb_pcie dut;
    std::map<uint16_t, uint32_t> memory;
    unsigned cycle = 0, reads = 0, writes = 0, completions = 0, packets = 0;
    unsigned stalled_headers = 0, stalled_tails = 0;
    unsigned axi_response = 0;
    bool stall_tx = false;
    std::deque<Completion> expected;

    Test() {
        dut.rx_valid = 0;
        dut.completer_id = 0x02a0;
        dut.reset = 1;
        for (unsigned i = 0; i < 4; ++i) {
            tick();
        }
        dut.reset = 0;
    }

    void drive() {
        dut.m_awready = !have_aw && !pending_b && cycle % 5 == 1;
        dut.m_wready = !have_w && !pending_b && cycle % 7 == 3;
        dut.m_bvalid = pending_b && cycle >= b_due;
        dut.m_bresp = b_response;
        dut.m_arready = !pending_r && cycle % 3 == 2;
        dut.m_rvalid = pending_r && cycle >= r_due;
        dut.m_rdata = r_data;
        dut.m_rresp = r_response;
        dut.tx_ready = !stall_tx && cycle % 11 < 7;
        dut.clk = 0;
        dut.eval();
    }

    void tick() {
        drive();
        if (!dut.reset) {
            check_stable(dut.m_awvalid, dut.m_awready, dut.m_awaddr, previous_aw, "AW changed under backpressure");
            check_stable(dut.m_wvalid, dut.m_wready, uint64_t(dut.m_wstrb) << 32 | dut.m_wdata,
                         previous_w, "W changed under backpressure");
            check_stable(dut.m_arvalid, dut.m_arready, dut.m_araddr, previous_ar, "AR changed under backpressure");
            std::array<uint64_t, 2> tx_now = {dut.tx_data, uint64_t(dut.tx_keep) << 1 | dut.tx_last};
            if (tx_stalled) {
                require(dut.tx_valid && tx_now == previous_tx, "Completion changed under backpressure");
            }
            tx_stalled = dut.tx_valid && !dut.tx_ready;
            previous_tx = tx_now;
            if (tx_stalled) {
                if (dut.tx_last) {
                    ++stalled_tails;
                } else {
                    ++stalled_headers;
                }
            }
        }
        if (dut.m_awvalid && dut.m_awready) {
            have_aw = true;
            write_address = dut.m_awaddr;
        }
        if (dut.m_wvalid && dut.m_wready) {
            have_w = true;
            w_value = dut.m_wdata;
            w_enable = dut.m_wstrb;
            require(w_enable != 0, "Zero-length write touched AXI-Lite");
        }
        if (have_aw && have_w && !pending_b) {
            pending_b = true;
            b_due = cycle + 13;
            b_response = axi_response;
            ++writes;
        }
        if (dut.m_bvalid && dut.m_bready) {
            if (b_response == 0) {
                auto& value = memory[write_address];
                for (unsigned byte = 0; byte < 4; ++byte) {
                    if ((w_enable >> byte) & 1) {
                        uint32_t mask = 0xffu << (byte * 8);
                        value = (value & ~mask) | (w_value & mask);
                    }
                }
            }
            pending_b = have_aw = have_w = false;
        }
        if (dut.m_arvalid && dut.m_arready) {
            require(!pending_b && !have_aw && !have_w, "Read passed an unfinished posted write");
            pending_r = true;
            r_data = memory[dut.m_araddr];
            r_response = axi_response;
            r_due = cycle + 9;
            ++reads;
        }
        if (dut.m_rvalid && dut.m_rready) {
            pending_r = false;
        }
        if (dut.tx_valid && dut.tx_ready) {
            require(!expected.empty(), "Unexpected Completion");
            require(dut.tx_keep == 0xff || (dut.tx_last && dut.tx_keep == 0x0f), "Invalid TX TKEEP");
            received.push_back(uint32_t(dut.tx_data));
            if (dut.tx_keep == 0xff) {
                received.push_back(dut.tx_data >> 32);
            }
            if (dut.tx_last) {
                if (received != expected.front().words) {
                    std::fprintf(stderr, "Completion %u at cycle %u\n", completions, cycle);
                    for (unsigned i = 0; i < received.size(); ++i) {
                        std::fprintf(stderr, "  DW%u: got=%08x expected=%08x\n", i, received[i],
                                     i < expected.front().words.size() ? expected.front().words[i] : 0);
                    }
                    require(false, "Completion content mismatch");
                }
                received.clear();
                expected.pop_front();
                ++completions;
            }
        }
        dut.clk = 1;
        dut.eval();
        ++cycle;
    }

    void expect(const Request& request, unsigned status, uint32_t data = 0) {
        unsigned low = 0, high = 0;
        if (request.first) {
            while (!(request.first & (1u << low))) {
                ++low;
            }
            for (unsigned i = 0; i < 4; ++i) {
                if (request.first & (1u << i)) {
                    high = i;
                }
            }
        }
        unsigned bytes = request.first ? high - low + 1 : 1;
        if (request.length != 1) {
            unsigned last = 0;
            for (unsigned i = 0; i < 4; ++i) {
                if (request.last & (1u << i)) {
                    last = i;
                }
            }
            bytes = request.length * 4 - low - (3 - last);
        }
        if (request.type == 12 || request.type == 13) {
            bytes = request.length * 4;
        } else if (request.type == 14) {
            bytes = request.length * 2;
        } else if (request.type != 0 && request.type != 1) {
            bytes = 4;
        }
        const unsigned kind = request.type == 1 ? 0x0b : 0x0a;
        const unsigned lower = request.type == 0 || request.type == 1
            ? uint32_t(request.address & 0x7c) | low : 0;
        Completion completion{{
            (status == 0 ? 0x40000001u : 0u) | kind << 24
                | request.traffic_class << 20 | (request.attributes & 4) << 16 | (request.attributes & 3) << 12,
            uint32_t(dut.completer_id) << 16 | status << 13 | (bytes & 4095),
            uint32_t(request.requester) << 16 | uint32_t(request.tag) << 8 | lower
        }};
        if (status == 0) {
            completion.words.push_back(request.first ? data : 0);
        }
        expected.push_back(completion);
    }

    void send(const std::vector<uint32_t>& words, unsigned user = 4, unsigned final_user = 4,
              int bad_keep_beat = -1, unsigned bad_keep = 0) {
        for (unsigned i = 0; i < words.size(); i += 2) {
            if ((i / 2) % 3 == 1) {
                tick();
            }
            dut.rx_data = uint64_t(words[i]) | (i + 1 < words.size() ? uint64_t(words[i + 1]) << 32 : 0);
            dut.rx_keep = i + 1 < words.size() ? 0xff : 0x0f;
            if (int(i / 2) == bad_keep_beat) {
                dut.rx_keep = bad_keep;
            }
            dut.rx_last = i + 2 >= words.size();
            dut.rx_user = dut.rx_last ? final_user : user;
            dut.rx_valid = 1;
            bool accepted = false;
            for (unsigned timeout = 0; timeout < 10000 && !accepted; ++timeout) {
                drive();
                accepted = dut.rx_ready;
                tick();
            }
            require(accepted, "RX timeout");
            dut.rx_valid = 0;
        }
        ++packets;
    }

    void settle() {
        for (unsigned timeout = 0; timeout < 10000; ++timeout) {
            tick();
            drive();
            if (dut.rx_ready && expected.empty() && !pending_b && !pending_r) {
                return;
            }
        }
        require(false, "Transaction timeout");
    }

private:
    struct Held {
        bool stalled = false;
        uint64_t data = 0;
    } previous_aw, previous_w, previous_ar;
    bool have_aw = false, have_w = false, pending_b = false, pending_r = false;
    bool tx_stalled = false;
    uint16_t write_address = 0;
    uint32_t w_value = 0, r_data = 0;
    unsigned w_enable = 0, b_response = 0, r_response = 0, b_due = 0, r_due = 0;
    std::array<uint64_t, 2> previous_tx{};
    std::vector<uint32_t> received;

    static void check_stable(bool valid, bool ready, uint64_t data, Held& previous, const char* message) {
        if (previous.stalled) {
            require(valid && data == previous.data, message);
        }
        previous = {valid && !ready, data};
    }
};

int main() {
    Test test;
    for (unsigned wide = 0; wide < 2; ++wide) {
        for (unsigned digest = 0; digest < 2; ++digest) {
            for (unsigned enable = 0; enable < 16; ++enable) {
                Request write;
                write.wide = wide;
                write.digest = digest;
                write.write = true;
                write.first = enable;
                write.value = 0x1284c739u ^ (enable * 0x13131313u);
                const uint16_t offset = write.address;
                test.memory[offset] = 0xaacc5577;
                uint32_t value = test.memory[offset];
                for (unsigned byte = 0; byte < 4; ++byte) {
                    if (enable & (1u << byte)) {
                        uint32_t mask = 0xffu << (byte * 8);
                        value = (value & ~mask) | (write.value & mask);
                    }
                }
                unsigned writes = test.writes, reads = test.reads;
                test.send(write.words());
                Request read = write;
                read.write = false;
                read.traffic_class = enable % 8;
                read.attributes = enable % 8;
                read.tag = uint8_t(enable + wide * 64 + digest * 32);
                test.expect(read, 0, value);
                test.send(read.words());
                test.settle();
                require(test.memory[offset] == value, "Byte-enable write corrupted untouched bytes");
                require(test.writes == writes + (enable != 0) && test.reads == reads + (enable != 0),
                        "Incorrect register access count");
            }
        }
    }
    require(test.dut.error_status == 0, "Valid TLP set error status");

    for (unsigned wide = 0; wide < 2; ++wide) {
        for (unsigned traffic_class = 0; traffic_class < 8; ++traffic_class) {
            for (unsigned attributes = 0; attributes < 8; ++attributes) {
                for (unsigned enable = 0; enable < 16; ++enable) {
                    Request read;
                    read.wide = wide;
                    read.traffic_class = traffic_class;
                    read.attributes = attributes;
                    read.first = enable;
                    read.tag = uint8_t(traffic_class * 32 + attributes * 4 + enable);
                    read.requester = uint16_t(0x8000 + traffic_class * 64 + attributes * 8 + enable);
                    read.digest = (traffic_class ^ attributes ^ enable) & 1;
                    test.expect(read, 0, test.memory[uint16_t(read.address)]);
                    test.send(read.words());
                }
            }
        }
    }
    test.settle();
    for (uint32_t offset : {0u, 4u, 0x1000u, 0x1ffcu, 0x2000u, 0x7ffcu, 0xfffcu}) {
        Request write;
        write.address = 0xabc00000 + offset;
        write.write = true;
        write.value = 0xd038761a ^ offset;
        test.send(write.words());
        Request read = write;
        read.write = false;
        test.expect(read, 0, write.value);
        test.send(read.words());
    }
    test.settle();
    require(test.stalled_headers != 0 && test.stalled_tails != 0, "TX backpressure missed a Completion beat");
    require(test.dut.error_status == 0, "Valid address or attribute set error status");

    for (unsigned status = 1; status < 4; ++status) {
        Request read;
        read.first = 5;
        test.axi_response = status;
        test.expect(read, status == 3 ? 1 : 4);
        test.send(read.words());
        test.settle();
        read.write = true;
        test.send(read.words());
        test.settle();
    }
    test.axi_response = 0;
    require((test.dut.error_status & 3) == 3, "AXI errors were not reported");

    const unsigned old_reads = test.reads, old_writes = test.writes;
    for (unsigned length : {2u, 3u, 16u, 1024u}) {
        Request read;
        read.length = length;
        read.last = 15;
        test.expect(read, 4);
        test.send(read.words());
        test.settle();
        read.write = true;
        test.send(read.words());
        test.settle();
    }
    for (unsigned type : {1u, 2u, 4u, 5u}) {
        Request read;
        read.type = type;
        test.expect(read, 1);
        test.send(read.words());
        test.settle();
    }
    Request read;
    read.type = 2;
    read.write = true;
    test.expect(read, 1);
    test.send(read.words());
    test.settle();
    for (unsigned type : {12u, 13u, 14u}) {
        Request atomic;
        atomic.type = type;
        atomic.write = true;
        atomic.length = type == 14 ? 4 : 2;
        test.expect(atomic, 1);
        test.send(atomic.words());
        test.settle();
    }
    read = Request{};
    read.wide = true;
    read.address |= uint64_t(1) << 32;
    test.expect(read, 4);
    test.send(read.words());
    test.settle();
    read = Request{};
    test.expect(read, 1);
    test.send(read.words(), 0, 0);
    test.settle();
    read.address |= 1;
    test.expect(read, 4);
    test.send(read.words());
    test.settle();

    read = Request{};
    auto words = read.words();
    words.pop_back();
    test.send(words);
    test.settle();
    words = read.words();
    words.push_back(0xdeadbeef);
    test.send(words);
    test.settle();
    read.last = 1;
    test.send(read.words());
    test.settle();
    read = Request{};
    words = read.words();
    words[0] |= 1u << 14;
    test.send(words);
    test.settle();
    test.send(read.words(), 4, 5);
    test.settle();
    test.send(read.words(), 4, 6);
    test.settle();
    read.write = true;
    words = read.words();
    words.push_back(0);
    test.send(words);
    test.settle();
    read = Request{};
    test.send(read.words(), 4, 4, 0, 0x0f);
    test.settle();
    test.send(read.words(), 4, 4, 1, 0xf0);
    test.settle();
    read.write = true;
    read.wide = true;
    test.send(read.words(), 4, 4, 1, 0x0f);
    test.settle();
    words = read.words();
    words[0] |= 1u << 31;
    test.send(words);
    test.settle();
    words = read.words();
    words.resize(2052, 0);
    test.send(words);
    test.settle();
    require(test.reads == old_reads && test.writes == old_writes,
            "Rejected packet touched AXI-Lite");
    require(test.dut.error_status == 15, "Packet errors were not reported");

    read = Request{};
    test.stall_tx = true;
    test.expect(read, 0, test.memory[uint16_t(read.address)]);
    test.send(read.words());
    for (unsigned i = 0; i < 100; ++i) {
        test.tick();
    }
    require(test.dut.tx_valid && !test.dut.rx_ready, "Completion stall did not hold request ordering");
    test.dut.completer_id = 0x04b0;
    test.stall_tx = false;
    test.settle();

    test.dut.rx_data = 1;
    test.dut.rx_keep = 0xff;
    test.dut.rx_last = 0;
    test.dut.rx_user = 4;
    test.dut.rx_valid = 1;
    test.tick();
    test.dut.rx_valid = 0;
    test.dut.reset = 1;
    test.tick();
    test.dut.reset = 0;
    test.expect(read, 0, test.memory[uint16_t(read.address)]);
    test.send(read.words());
    test.settle();
    require(test.dut.error_status == 0, "Reset did not clear parser and errors");
    std::printf("PASS: %u TLPs, %u Completions, %u AXI-Lite writes, %u reads\n",
                test.packets, test.completions, test.writes, test.reads);
}
