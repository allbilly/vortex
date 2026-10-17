// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "VVX_ypcb_pio.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#ifdef TEST_PIO_TRANSPORT
#include <ypcb_transport.h>
#include <algorithm>
#include <atomic>
#include <thread>
#include <vector>
#endif
#ifdef TEST_HOST_MEMORY
#include <ypcb_host_memory.h>
#include <cstring>
#endif

static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

class Test {
public:
  VVX_ypcb_pio dut;
  std::map<uint64_t, std::array<uint32_t, 16>> memory;
  unsigned cycle_count = 0, reads = 0, writes = 0;
  bool pause = false;
  unsigned response = 0;

  Test() {
    dut.s_awvalid = dut.s_wvalid = dut.s_arvalid = 0;
    dut.s_bready = dut.s_rready = 0;
    dut.memory_ready = 2;
    dut.reset = 1;
    for (unsigned cycle = 0; cycle < 4; ++cycle) {
      tick();
    }
    dut.reset = 0;
  }

  void drive() {
    dut.m_awready = !pause && !have_address && !write_response && cycle_count % 5 == 1;
    dut.m_wready = !pause && !have_data && !write_response && cycle_count % 7 == 2;
    dut.m_bvalid = write_response && cycle_count >= write_due;
    dut.m_bresp = write_status;
    dut.m_arready = !pause && !read_response && cycle_count % 3 == 1;
    dut.m_rvalid = read_response && cycle_count >= read_due;
    dut.m_rlast = 1;
    dut.m_rresp = read_status;
    for (unsigned word = 0; word < 16; ++word) {
      dut.m_rdata[word] = read_data[word];
    }
    dut.clk = 0;
    dut.eval();
  }

  void tick() {
    drive();
    if (dut.m_awvalid && dut.m_awready) {
      require((dut.m_awaddr & 63) == 0 && dut.m_awaddr < 0x80000000ull,
          "Invalid AXI write address");
      have_address = true;
      write_address = dut.m_awaddr;
    }
    if (dut.m_wvalid && dut.m_wready) {
      require(dut.m_wlast, "Missing WLAST");
      have_data = true;
      write_mask = dut.m_wstrb;
      for (unsigned word = 0; word < 16; ++word) {
        write_data[word] = dut.m_wdata[word];
      }
    }
    if (have_address && have_data && !write_response) {
      auto& line = memory[write_address];
      for (unsigned byte = 0; byte < 64; ++byte) {
        if ((write_mask >> byte) & 1) {
          const unsigned shift = (byte % 4) * 8;
          const uint32_t mask = 0xffu << shift;
          line[byte / 4] = (line[byte / 4] & ~mask) | (write_data[byte / 4] & mask);
        }
      }
      write_status = response;
      write_due = cycle_count + 8;
      write_response = true;
      ++writes;
    }
    if (dut.m_bvalid && dut.m_bready) {
      write_response = false;
      have_address = have_data = false;
    }
    if (dut.m_arvalid && dut.m_arready) {
      require((dut.m_araddr & 63) == 0 && dut.m_araddr < 0x80000000ull,
          "Invalid AXI read address");
      read_data = memory[dut.m_araddr];
      read_status = response;
      read_due = cycle_count + 8;
      read_response = true;
      ++reads;
    }
    if (dut.m_rvalid && dut.m_rready) {
      read_response = false;
    }
    dut.clk = 1;
    dut.eval();
    ++cycle_count;
  }

  unsigned write(unsigned address, uint32_t value, unsigned strobe = 15) {
    bool aw_done = false, w_done = false;
    const unsigned start = cycle_count;
    dut.s_bready = 0;
    for (unsigned wait = 0; wait < 200; ++wait) {
      dut.s_awaddr = address;
      dut.s_awvalid = !aw_done && (wait >= (start % 2 ? 4 : 0));
      dut.s_wdata = value;
      dut.s_wstrb = strobe;
      dut.s_wvalid = !w_done && (wait >= (start % 2 ? 0 : 4));
      drive();
      aw_done |= dut.s_awvalid && dut.s_awready;
      w_done |= dut.s_wvalid && dut.s_wready;
      const bool valid = dut.s_bvalid;
      const unsigned status = dut.s_bresp;
      tick();
      if (valid) {
        dut.s_awvalid = dut.s_wvalid = 0;
        for (unsigned hold = 0; hold < 3; ++hold) {
          drive();
          require(dut.s_bvalid && dut.s_bresp == status, "AXI-Lite BRESP changed under stall");
          tick();
        }
        dut.s_bready = 1;
        tick();
        dut.s_bready = 0;
        return status;
      }
    }
    require(false, "AXI-Lite write timed out");
    return 3;
  }

  uint32_t read(unsigned address, unsigned expected_status = 0) {
    dut.s_araddr = address;
    dut.s_arvalid = 1;
    dut.s_rready = 0;
    bool sent = false;
    for (unsigned wait = 0; wait < 200; ++wait) {
      drive();
      const bool address_fire = dut.s_arvalid && dut.s_arready;
      const bool valid = dut.s_rvalid;
      const uint32_t data = dut.s_rdata;
      const unsigned status = dut.s_rresp;
      tick();
      sent |= address_fire;
      dut.s_arvalid = !sent;
      if (valid) {
        require(status == expected_status, "Unexpected AXI-Lite RRESP");
        for (unsigned hold = 0; hold < 3; ++hold) {
          drive();
          require(dut.s_rvalid && dut.s_rdata == data && dut.s_rresp == status,
              "AXI-Lite read changed under stall");
          tick();
        }
        dut.s_rready = 1;
        tick();
        dut.s_rready = 0;
        return data;
      }
    }
    require(false, "AXI-Lite read timed out");
    return 0;
  }

  void wait(unsigned expected_status = 0) {
    for (unsigned attempt = 0; attempt < 200; ++attempt) {
      const uint32_t status = read(4);
      if (!(status & 1) && (status & 2)) {
        require(read(0x14) == expected_status, "Incorrect memory response");
        require(bool(status & 4) == (expected_status != 0), "Incorrect error status");
        return;
      }
    }
    require(false, "PIO operation timed out");
  }

private:
  bool have_address = false, have_data = false, write_response = false, read_response = false;
  uint64_t write_address = 0, write_mask = 0;
  unsigned write_due = 0, read_due = 0, write_status = 0, read_status = 0;
  std::array<uint32_t, 16> write_data{}, read_data{};
};

#ifdef TEST_PIO_TRANSPORT
class TestMmio : public vortex::ypcb::Mmio {
public:
  explicit TestMmio(Test& test) : test_(test) {}
  unsigned accesses = 0;
  bool fail = false;

  int read32(uint32_t offset, uint32_t* value) override {
    ++accesses;
    require(offset >= 0x2000 && offset < 0x3000 && offset % 4 == 0,
            "Host MMIO read escaped its aligned PIO window");
    if (fail) {
      return -1;
    }
    *value = test_.read(offset - 0x2000);
    return 0;
  }

  int write32(uint32_t offset, uint32_t value) override {
    ++accesses;
    require(offset >= 0x2000 && offset < 0x3000 && offset % 4 == 0,
            "Host MMIO write escaped its aligned PIO window");
    if (fail) {
      return -1;
    }
    return test_.write(offset - 0x2000, value);
  }

private:
  Test& test_;
};

static void host_test(Test& test) {
  using namespace vortex::ypcb;
  test.response = 0;
  TestMmio mmio(test);
  Pio pio(mmio);
  test.dut.memory_ready = 1;
  require(pio.initialize() == Result::unready, "Host accepted incomplete readiness");
  test.dut.memory_ready = 2;
  require(pio.initialize() == Result::success, "Host PIO initialization failed");
  unsigned transfers = 0;
  for (uint64_t base : {0x10000ull, 0x3fffff80ull, 0x7fffff40ull}) {
    for (unsigned offset = 0; offset < 64; ++offset) {
      for (unsigned size : {0u, 1u, 3u, 31u, 64u, 65u, 129u}) {
        for (unsigned line = 0; line < 3; ++line) {
          test.memory[base + line * 64].fill(0xa5a5a5a5);
        }
        std::vector<uint8_t> payload(size);
        std::vector<uint8_t> expected(192, 0xa5);
        for (unsigned byte = 0; byte < size; ++byte) {
          payload[byte] = uint8_t(byte * 37 + offset * 13 + size);
          expected[offset + byte] = payload[byte];
        }
        const auto original = payload;
        require(pio.write(base + offset, payload.data(), size) == Result::success,
                "Host upload failed");
        require(payload == original, "Host upload changed its source");
        for (unsigned byte = 0; byte < expected.size(); ++byte) {
          const auto& line = test.memory[base + (byte / 64) * 64];
          require(uint8_t(line[(byte % 64) / 4] >> ((byte % 4) * 8)) == expected[byte],
                  "Host upload changed bytes or device guards");
        }
        std::vector<uint8_t> output(size + 16, 0x5a);
        require(pio.read(base + offset, output.data() + 8, size) == Result::success,
                "Host download failed");
        require(std::equal(payload.begin(), payload.end(), output.begin() + 8),
                "Host download bytes differ");
        for (unsigned guard = 0; guard < 8; ++guard) {
          require(output[guard] == 0x5a && output[size + 8 + guard] == 0x5a,
                  "Host download changed host guards");
        }
        transfers += 2;
      }
    }
  }
  uint8_t last = 0x47, out = 0;
  require(pio.write(0x7fffffff, &last, 1) == Result::success
          && pio.read(0x7fffffff, &out, 1) == Result::success && last == out,
          "Final address byte differs");
  const unsigned before = mmio.accesses;
  require(pio.read(0x80000000ull, nullptr, 0) == Result::success
          && pio.write(0x80000000ull, nullptr, 0) == Result::success,
          "Empty end-of-memory transfer rejected");
  require(pio.read(0x7fffffff, &out, 2) == Result::invalid
          && pio.write(0x80000001ull, nullptr, 0) == Result::invalid
          && pio.write(1, nullptr, 1) == Result::invalid
          && pio.read(0xffffffffffffffffull, &out, 1) == Result::invalid,
          "Host range or pointer validation failed");
  require(mmio.accesses == before, "Empty/invalid transfer accessed MMIO");
  for (unsigned ready : {0u, 1u}) {
    test.dut.memory_ready = ready;
    require(pio.write(0x1000, &last, 1) == Result::unready,
            "Host accessed an unready channel");
  }
  test.dut.memory_ready = 2;
  for (unsigned response : {2u, 3u}) {
    test.response = response;
    require(pio.read(0x10000, &out, 1) == Result::memory_error,
            "Host lost a memory read error");
    require(pio.write(0x10000, &last, 1) == Result::memory_error,
            "Host lost a memory write error");
  }
  test.response = 0;
  std::atomic<bool> failed{false};
  auto worker = [&](unsigned id) {
    std::array<uint8_t, 97> source, destination;
    source.fill(uint8_t(0x69 + id));
    for (unsigned repeat = 0; repeat < 10; ++repeat) {
      if (pio.write(0x20000 + id * 0x1000 + 3, source.data(), source.size()) != Result::success
          || pio.read(0x20000 + id * 0x1000 + 3, destination.data(), destination.size()) != Result::success
          || source != destination) {
        failed = true;
      }
    }
  };
  std::thread first(worker, 0), second(worker, 1);
  first.join();
  second.join();
  require(!failed, "Concurrent host transfers shared the staging window");
  Pio faulted(mmio);
  require(faulted.initialize() == Result::success, "Fault test initialization failed");
  mmio.fail = true;
  require(faulted.read(0x10000, &out, 1) == Result::io_error, "MMIO failure was lost");
  mmio.fail = false;
  require(faulted.read(0x10000, &out, 1) == Result::poisoned, "Faulted transport reused MMIO");
  Pio bounded(mmio, std::chrono::milliseconds(100));
  require(bounded.initialize() == Result::success, "Timeout test initialization failed");
  test.pause = true;
  require(bounded.read(0x10000, &out, 1) == Result::timeout, "Host transfer did not time out");
  require(bounded.read(0x10000, &out, 1) == Result::poisoned, "Timed-out transport reused staging");
  test.pause = false;
  test.wait();
  std::printf("PASSED: host PIO helper against RTL, %u byte-range transfers, two-bank boundary, final 4 GiB byte, host/device guards, two threads, readiness/errors/timeouts\n",
              transfers + 42);
}
#endif

#ifdef TEST_HOST_MEMORY
class HostMmio : public vortex::ypcb::Mmio {
public:
  explicit HostMmio(Test& test) : pio_(test) {}
  std::map<uint32_t, uint32_t> registers;
  unsigned doorbells = 0, accesses = 0;
  bool fail_doorbell = false;

  int read32(uint32_t offset, uint32_t* value) override {
    ++accesses;
    if (offset >= 0x2000) {
      return pio_.read32(offset, value);
    }
    require(offset >= 0x1000 && offset < 0x2000 && !(offset & 3), "Invalid CP read");
    *value = offset == 0x1010 ? accesses : registers[offset];
    return 0;
  }
  int write32(uint32_t offset, uint32_t value) override {
    ++accesses;
    if (offset >= 0x2000) {
      return pio_.write32(offset, value);
    }
    require(offset >= 0x1000 && offset < 0x2000 && !(offset & 3), "Invalid CP write");
    registers[offset] = value;
    if (offset == 0x1124) {
      ++doorbells;
      if (fail_doorbell) {
        return -1;
      }
    }
    return 0;
  }

private:
  TestMmio pio_;
};

static void memory_host_test() {
  using namespace vortex::ypcb;
  Test test;
  HostMmio mmio(test);
  mmio.registers[0x1128] = 63;
  Pio pio(mmio);
  require(pio.initialize() == Result::success, "Host-memory PIO initialization failed");
  HostMemory host(mmio, pio);
  require(host.initialize() == 0, "Host-memory initialization failed");
  std::array<void*, 3> owners;
  std::array<uint64_t, 3> addresses;
  for (unsigned index = 0; index < owners.size(); ++index) {
    require(host.allocate(index == 1 ? 64 : 128, &owners[index], &addresses[index]) == 0,
        "Owner allocation failed");
    require(host.cp_reg_write(0x100 + index * 8, uint32_t(addresses[index])) == 0
        && host.cp_reg_write(0x104 + index * 8, uint32_t(addresses[index] >> 32)) == 0,
        "Owner register setup failed");
  }
  require(host.cp_reg_write(0x118, 7) == 0, "Ring size setup failed");
  std::memset(static_cast<uint8_t*>(owners[0]) + 64, 0x31, 64);
  void* upload;
  uint64_t upload_address;
  require(host.allocate(128, &upload, &upload_address) == 0, "Upload allocation failed");
  std::memset(upload, 0x59, 128);
  require(host.push(upload_address) == 0 && host.release(upload_address) == 0,
      "Batch staging publication/park failed");
  void* unfinished;
  uint64_t unfinished_address;
  require(host.allocate(128, &unfinished, &unfinished_address) == 0
      && unfinished_address != upload_address, "Unpublished batch address reused");
  std::memset(unfinished, 0xc7, 128);
  require(host.cp_reg_write(0x120, 4096) == 0 && mmio.doorbells == 0,
      "Low tail half rang doorbell");
  require(test.memory[addresses[0] + 64][0] == 0, "Ring published before tail commit");
  require(host.cp_reg_write(0x124, 0) == 0 && mmio.doorbells == 1,
      "First tail commit failed");
  require(test.memory[addresses[0] + 64][0] == 0x31313131
      && test.memory[upload_address][0] == 0x59595959
      && test.memory[unfinished_address][0] == 0,
      "Doorbell lost published bytes or uploaded another owner's shadow");
  uint32_t seqnum;
  require(host.cp_reg_read(0x128, &seqnum) == 0 && seqnum == 63,
      "Unretired sequence changed");
  void* blocked;
  uint64_t blocked_address;
  require(host.allocate(128, &blocked, &blocked_address) == 0
      && blocked_address != upload_address, "Live staging address reused before retirement");
  mmio.registers[0x1128] = 64;
  require(host.cp_reg_read(0x128, &seqnum) == 0, "Retirement poll failed");
  void* recycled;
  uint64_t recycled_address;
  require(host.allocate(128, &recycled, &recycled_address) == 0
      && recycled_address == upload_address, "Retired staging address was not reclaimed");
  test.memory[addresses[1]][0] = 0x12345678;
  test.memory[addresses[2]][0] = 0x87654321;
  std::memset(owners[0], 0x42, 64);
  require(host.cp_reg_write(0x120, 4160) == 0 && host.cp_reg_write(0x124, 0) == 0,
      "Wrapped ring publication failed");
  require(test.memory[addresses[0]][0] == 0x42424242
      && test.memory[addresses[0] + 64][0] == 0x31313131
      && test.memory[addresses[1]][0] == 0x12345678
      && test.memory[addresses[2]][0] == 0x87654321,
      "Later doorbell overwrote CP-owned metadata or wrong ring slot");
  require(static_cast<uint8_t*>(unfinished)[0] == 0xc7,
      "Polling overwrote an unfinished upload shadow");
  test.memory[unfinished_address].fill(0x85858585);
  require(host.pull(unfinished_address) == 0 && static_cast<uint8_t*>(unfinished)[0] == 0x85,
      "Explicit single-region download did not refresh its owner");
  require(host.push(addresses[0]) != 0 && host.pull(addresses[2]) != 0,
      "Generic sync clobbered CP-owned regions");
  const unsigned issued = mmio.doorbells;
  require(host.cp_reg_write(0x120, 4352) == 0 && host.cp_reg_write(0x124, 0) != 0
      && mmio.doorbells == issued, "Ring overrun was committed");
  require(host.cp_reg_write(0x120, 4224) == 0, "Tail restore failed");
  mmio.fail_doorbell = true;
  require(host.cp_reg_write(0x124, 0) != 0, "Uncertain doorbell accepted");
  const unsigned before = mmio.accesses;
  require(host.allocate(64, &blocked, &blocked_address) != 0
      && host.cp_reg_read(0x128, &seqnum) != 0 && mmio.accesses == before,
      "Uncertain doorbell allowed transport reuse");
  std::puts("PASSED: DDR host shadows through actual PIO RTL, ring wrap/atomic publication, single-owner sync, batch lifetime/retirement and uncertain-doorbell poison; CP register oracle is synthetic");
}
#endif

int main() {
  Test test;
  require(test.read(0) == 0x56595043, "Signature differs");
  require(test.read(4) == 0x20, "Reset status differs");
  require(test.write(0x100, 0x12345678) == 0, "Data write failed");
  require(test.write(0x100, 0xaabbccdd, 5) == 0, "Masked register write failed");
  require(test.read(0x100) == 0x12bb56dd, "Register byte enables differ");
  require(test.write(0x102, 0) == 3, "Unaligned register write accepted");
  require(test.write(0x200, 0) == 3, "Unknown register write accepted");
  test.read(0x102, 3);
  test.read(0x200, 3);

  const std::array<uint64_t, 4> addresses = {0x1000, 0x3fffffc0, 0x40001000, 0x7fffefc0};
  const std::array<uint64_t, 3> masks = {~uint64_t(0), 0, 0x8123456789abcdefull};
  for (uint64_t address : addresses) {
    auto& line = test.memory[address];
    line.fill(0x5a5a5a5a);
    auto expected = line;
    require(test.write(8, uint32_t(address)) == 0, "Address write failed");
    for (uint64_t mask : masks) {
      for (unsigned word = 0; word < 16; ++word) {
        const uint32_t value = uint32_t(address) ^ (word * 0x1020304u) ^ uint32_t(mask);
        require(test.write(0x100 + word * 4, value) == 0, "Payload write failed");
        for (unsigned byte = 0; byte < 4; ++byte) {
          if ((mask >> (word * 4 + byte)) & 1) {
            const uint32_t byte_mask = 0xffu << (byte * 8);
            expected[word] = (expected[word] & ~byte_mask) | (value & byte_mask);
          }
        }
      }
      require(test.write(0x18, uint32_t(mask)) == 0, "Mask low write failed");
      require(test.write(0x1c, uint32_t(mask >> 32)) == 0, "Mask high write failed");
      test.pause = true;
      require(test.write(0x10, 2) == 0, "Memory write command rejected");
      require(test.read(4) & 1, "Busy bit missing");
      require(test.write(8, 0x4000) == 2, "Busy address changed");
      require(test.write(0x100, 0) == 2, "Busy payload changed");
      require(test.write(0x10, 1) == 2, "Concurrent command accepted");
      test.pause = false;
      test.wait();
      require(line == expected, "Memory bytes or guards differ");
      require(test.write(0x10, 1) == 0, "Memory read command rejected");
      test.wait();
      for (unsigned word = 0; word < 16; ++word) {
        require(test.read(0x100 + word * 4) == expected[word], "Read data differs");
      }
    }
  }
  const unsigned issued = test.reads + test.writes;
  require(test.write(8, 0x1004) == 0 && test.write(0x10, 1) == 2, "Unaligned command accepted");
  test.wait(3);
  require(test.write(8, 0x1000) == 0 && test.write(0xc, 1) == 0
      && test.write(0x10, 2) == 2, "Out-of-range command accepted");
  test.wait(3);
  require(test.write(0xc, 0) == 0, "High address clear failed");
  for (unsigned ready : {0u, 1u}) {
    test.dut.memory_ready = ready;
    require(test.write(8, 0x1000) == 0
        && test.write(0x10, 1) == 2, "Unready channel command accepted");
    test.wait(2);
  }
  require(test.reads + test.writes == issued, "Rejected command issued AXI traffic");
  test.dut.memory_ready = 2;
  for (unsigned response : {2u, 3u}) {
    test.response = response;
    require(test.write(0x10, 1) == 0, "Error read command rejected");
    test.wait(response);
    require(test.write(0x10, 2) == 0, "Error write command rejected");
    test.wait(response);
  }
  std::printf("PASSED: PIO, %u writes, %u reads, both banks, byte masks, guards, independent AXI-Lite channels, stalls and error responses\n",
        test.writes, test.reads);
#ifdef TEST_PIO_TRANSPORT
    host_test(test);
#endif
#ifdef TEST_HOST_MEMORY
    memory_host_test();
#endif
  return 0;
}
