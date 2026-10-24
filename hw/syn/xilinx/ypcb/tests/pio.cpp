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
#include <utility>
#include <vector>
#endif
#ifdef TEST_HOST_MEMORY
#include <ypcb_host_memory.h>
#include <cstring>
#endif

#ifdef TEST_PIO_DUAL_CHANNEL
static constexpr uint64_t pio_test_memory_limit = 0x100000000ull;
#else
static constexpr uint64_t pio_test_memory_limit = 0x80000000ull;
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
#ifdef TEST_PIO_DUAL_CHANNEL
    dut.memory_ready = 3;
#else
    dut.memory_ready = 2;
#endif
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
      require((dut.m_awaddr & 63) == 0 && dut.m_awaddr < pio_test_memory_limit,
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
      require((dut.m_araddr & 63) == 0 && dut.m_araddr < pio_test_memory_limit,
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
  std::chrono::milliseconds staging_delay{0};

  int read_words(uint32_t offset, uint32_t* values, size_t count) override {
    std::this_thread::sleep_for(staging_delay);
    return Mmio::read_words(offset, values, count);
  }

  int write_words(uint32_t offset, const uint32_t* values, size_t count) override {
    std::this_thread::sleep_for(staging_delay);
    return Mmio::write_words(offset, values, count);
  }

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
#ifdef TEST_PIO_DUAL_CHANNEL
  Pio pio(mmio, std::chrono::seconds(30), Pio::maximum_memory_size);
#else
  Pio pio(mmio);
#endif
  test.dut.memory_ready = 1;
  require(pio.initialize() == Result::unready, "Host accepted incomplete readiness");
#ifdef TEST_PIO_DUAL_CHANNEL
  test.dut.memory_ready = 3;
#else
  test.dut.memory_ready = 2;
#endif
  require(pio.initialize() == Result::success, "Host PIO initialization failed");
  unsigned transfers = 0;
#ifdef TEST_PIO_DUAL_CHANNEL
  for (uint64_t base : {0x10000ull, 0x3fffff80ull, 0x7fffff40ull,
                        0x80001000ull}) {
#else
  for (uint64_t base : {0x10000ull, 0x3fffff80ull, 0x7fffff40ull}) {
#endif
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
#ifdef TEST_PIO_DUAL_CHANNEL
  require(pio.read(Pio::maximum_memory_size, nullptr, 0) == Result::success
          && pio.write(Pio::maximum_memory_size, nullptr, 0) == Result::success,
          "4 GiB empty end-of-memory transfer failed");
  const std::array<uint8_t, 2> crossing_write{{0x3c, 0xc3}};
  std::array<uint8_t, 2> crossing_read{};
  require(pio.write(Pio::default_memory_size - 1, crossing_write.data(), crossing_write.size())
              == Result::success
          && pio.read(Pio::default_memory_size - 1, crossing_read.data(), crossing_read.size())
              == Result::success
          && crossing_read == crossing_write,
          "4 GiB host PIO transfer across the 2 GiB boundary failed");
  uint8_t high_byte = 0x9d, high_read = 0;
  require(pio.write(Pio::maximum_memory_size - 1, &high_byte, 1) == Result::success
          && pio.read(Pio::maximum_memory_size - 1, &high_read, 1) == Result::success
          && high_byte == high_read,
          "4 GiB host PIO final byte failed");
  const unsigned before = mmio.accesses;
  require(pio.read(Pio::maximum_memory_size - 1, &out, 2) == Result::invalid
          && pio.write(Pio::maximum_memory_size, nullptr, 1) == Result::invalid
          && pio.read(UINT64_MAX, &out, 1) == Result::invalid,
          "4 GiB host PIO crossing or overflow was accepted");
#else
  const unsigned before = mmio.accesses;
  require(pio.read(0x80000000ull, nullptr, 0) == Result::success
          && pio.write(0x80000000ull, nullptr, 0) == Result::success,
          "Empty end-of-memory transfer rejected");
  require(pio.read(0x7fffffff, &out, 2) == Result::invalid
          && pio.write(0x80000001ull, nullptr, 0) == Result::invalid
          && pio.write(1, nullptr, 1) == Result::invalid
          && pio.read(0xffffffffffffffffull, &out, 1) == Result::invalid,
          "Host range or pointer validation failed");
#endif
  require(mmio.accesses == before, "Empty/invalid transfer accessed MMIO");

#ifdef TEST_PIO_DUAL_CHANNEL
  test.dut.memory_ready = 2;
  require(pio.write(0x1000, &last, 1) == Result::unready
          && pio.write(0x80001000ull, &last, 1) == Result::success,
          "Dual-channel PIO did not select CH0 readiness by address bit 31");
  test.dut.memory_ready = 1;
  require(pio.write(0x1000, &last, 1) == Result::success
          && pio.write(0x80001000ull, &last, 1) == Result::unready,
          "Dual-channel PIO did not select CH1 readiness by address bit 31");
  test.dut.memory_ready = 3;
#else
  for (unsigned ready : {0u, 1u}) {
    test.dut.memory_ready = ready;
    require(pio.write(0x1000, &last, 1) == Result::unready,
            "Host accessed an unready channel");
  }
  test.dut.memory_ready = 2;
#endif
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
#ifdef TEST_PIO_DUAL_CHANNEL
  Pio slow_staging(mmio, std::chrono::milliseconds(100), Pio::maximum_memory_size);
#else
  Pio slow_staging(mmio, std::chrono::milliseconds(100));
#endif
  require(slow_staging.initialize() == Result::success, "Slow staging initialization failed");
  mmio.staging_delay = std::chrono::milliseconds(120);
  std::array<uint8_t, 65> staged{}, staged_read{};
  staged.fill(0xa7);
  require(slow_staging.write(0x70000, staged.data(), staged.size()) == Result::success
          && slow_staging.read(0x70000, staged_read.data(), staged_read.size()) == Result::success
          && staged == staged_read,
          "Host staging latency consumed the hardware command completion budget");
  mmio.staging_delay = std::chrono::milliseconds(0);
#ifdef TEST_PIO_DUAL_CHANNEL
  Pio faulted(mmio, std::chrono::seconds(30), Pio::maximum_memory_size);
#else
  Pio faulted(mmio);
#endif
  require(faulted.initialize() == Result::success, "Fault test initialization failed");
  mmio.fail = true;
  require(faulted.read(0x10000, &out, 1) == Result::io_error, "MMIO failure was lost");
  mmio.fail = false;
  require(faulted.read(0x10000, &out, 1) == Result::poisoned, "Faulted transport reused MMIO");
#ifdef TEST_PIO_DUAL_CHANNEL
  Pio bounded(mmio, std::chrono::milliseconds(100), Pio::maximum_memory_size);
#else
  Pio bounded(mmio, std::chrono::milliseconds(100));
#endif
  require(bounded.initialize() == Result::success, "Timeout test initialization failed");
  test.pause = true;
  require(bounded.read(0x10000, &out, 1) == Result::timeout, "Host transfer did not time out");
  require(bounded.read(0x10000, &out, 1) == Result::poisoned, "Timed-out transport reused staging");
  test.pause = false;
  test.wait();
  std::printf("PASSED: host PIO helper against RTL, %u byte-range transfers, 2 GiB address bounds, host/device guards, two threads, readiness/errors/timeouts\n",
              transfers + 42);
}

class BoundsMmio : public vortex::ypcb::Mmio {
public:
  unsigned accesses = 0;
  uint32_t ready_status = 0x20;
  std::vector<uint64_t> command_addresses;

  int read32(uint32_t offset, uint32_t* value) override {
    ++accesses;
    if (!value || offset < pio_base || offset >= pio_base + 0x1000 || (offset & 3)) {
      return -1;
    }
    switch (offset - pio_base) {
      case 0:
        *value = 0x56595043;
        return 0;
      case 4:
        *value = ready_status | 2;
        return 0;
      case 0x14:
        *value = 0;
        return 0;
      default:
        *value = 0;
        return 0;
    }
  }

  int write32(uint32_t offset, uint32_t value) override {
    ++accesses;
    if (offset < pio_base || offset >= pio_base + 0x1000 || (offset & 3)) {
      return -1;
    }
    switch (offset - pio_base) {
      case 8:
        address_ = value;
        break;
      case 0x18:
        mask_ = (mask_ & 0xffffffff00000000ull) | value;
        break;
      case 0x1c:
        mask_ = (mask_ & 0xffffffffull) | (uint64_t(value) << 32);
        break;
      case 0x10:
        command_addresses.push_back(address_);
        if (value == 1) {
          staging_ = memory_[address_];
        } else if (value == 2) {
          auto& line = memory_[address_];
          for (unsigned byte = 0; byte < 64; ++byte) {
            if ((mask_ >> byte) & 1) {
              const unsigned shift = (byte % 4) * 8;
              const uint32_t byte_mask = 0xffu << shift;
              line[byte / 4] = (line[byte / 4] & ~byte_mask)
                  | (staging_[byte / 4] & byte_mask);
            }
          }
        } else {
          return -1;
        }
        break;
      default:
        break;
    }
    return 0;
  }

  int read_words(uint32_t offset, uint32_t* values, size_t count) override {
    ++accesses;
    if (offset != pio_base + 0x100 || !values || count != staging_.size()) {
      return -1;
    }
    std::copy(staging_.begin(), staging_.end(), values);
    return 0;
  }

  int write_words(uint32_t offset, const uint32_t* values, size_t count) override {
    ++accesses;
    if (offset != pio_base + 0x100 || !values || count != staging_.size()) {
      return -1;
    }
    std::copy(values, values + count, staging_.begin());
    return 0;
  }

private:
  static constexpr uint32_t pio_base = 0x2000;
  uint32_t address_ = 0;
  uint64_t mask_ = ~uint64_t(0);
  std::array<uint32_t, 16> staging_{};
  std::map<uint64_t, std::array<uint32_t, 16>> memory_;
};

static void transport_capacity_test() {
  using namespace vortex::ypcb;
  BoundsMmio mmio;
  Pio legacy(mmio);
  require(legacy.initialize() == Result::success, "Default-capacity PIO init failed");
  uint8_t value = 0x36, output = 0;
  require(legacy.write(Pio::default_memory_size - 1, &value, 1) == Result::success
          && legacy.read(Pio::default_memory_size - 1, &output, 1) == Result::success
          && value == output,
          "Default 2 GiB final byte failed");
  const unsigned before_legacy_rejects = mmio.accesses;
  require(legacy.read(Pio::default_memory_size, nullptr, 0) == Result::success
          && legacy.read(Pio::default_memory_size, &output, 1) == Result::invalid
          && legacy.write(Pio::default_memory_size - 1, &value, 2) == Result::invalid
          && mmio.accesses == before_legacy_rejects,
          "Default 2 GiB end or cross-boundary bounds differ");

  Pio four_gib(mmio, std::chrono::seconds(30), Pio::maximum_memory_size);
  mmio.ready_status = 0x30;
  require(four_gib.initialize() == Result::success, "4 GiB PIO initialization failed");
  mmio.ready_status = 0x20;
  require(four_gib.read(0x1000, &output, 1) == Result::unready
          && four_gib.read(0x80001000ull, &output, 1) == Result::success,
          "4 GiB PIO did not select CH0 readiness from address bit 31");
  mmio.ready_status = 0x10;
  require(four_gib.read(0x1000, &output, 1) == Result::success
          && four_gib.read(0x80001000ull, &output, 1) == Result::unready,
          "4 GiB PIO did not select CH1 readiness from address bit 31");
  mmio.ready_status = 0x30;
  const std::array<uint8_t, 2> crossing{{0x3c, 0xc3}};
  std::array<uint8_t, 2> crossing_read{};
  const auto command_start = mmio.command_addresses.size();
  require(four_gib.write(Pio::default_memory_size - 1,
                         crossing.data(), crossing.size()) == Result::success
          && four_gib.read(Pio::default_memory_size - 1,
                           crossing_read.data(), crossing_read.size()) == Result::success
          && crossing == crossing_read,
          "4 GiB PIO transfer across 2 GiB boundary failed");
  require(mmio.command_addresses.size() == command_start + 4
          && mmio.command_addresses[command_start] == Pio::default_memory_size - 64
          && mmio.command_addresses[command_start + 1] == Pio::default_memory_size
          && mmio.command_addresses[command_start + 2] == Pio::default_memory_size - 64
          && mmio.command_addresses[command_start + 3] == Pio::default_memory_size,
          "4 GiB PIO did not issue both sides of the 2 GiB boundary");

  value = 0x9d;
  output = 0;
  const auto final_address = Pio::maximum_memory_size - 1;
  require(four_gib.write(final_address, &value, 1) == Result::success
          && four_gib.read(final_address, &output, 1) == Result::success
          && value == output
          && mmio.command_addresses[mmio.command_addresses.size() - 1]
              == Pio::maximum_memory_size - 64,
          "4 GiB PIO final byte/line failed");
  const unsigned before_four_gib_rejects = mmio.accesses;
  require(four_gib.read(Pio::maximum_memory_size, nullptr, 0) == Result::success
          && four_gib.read(Pio::maximum_memory_size, &output, 1) == Result::invalid
          && four_gib.write(final_address, &value, 2) == Result::invalid
          && four_gib.read(UINT64_MAX, &output, 1) == Result::invalid
          && four_gib.write(UINT64_MAX, nullptr, 0) == Result::invalid
          && mmio.accesses == before_four_gib_rejects,
          "4 GiB PIO end, crossing, overflow, or no-MMIO rejection differs");

  Pio invalid_capacity(mmio, std::chrono::seconds(30), 0xc0000000ull);
  const unsigned before_invalid_capacity = mmio.accesses;
  require(invalid_capacity.initialize() == Result::invalid
          && invalid_capacity.read(0, &output, 1) == Result::invalid
          && mmio.accesses == before_invalid_capacity,
          "Unsupported capacity was not rejected before MMIO");
  std::puts("PASSED: default 2 GiB and explicit 4 GiB PIO bounds, 2 GiB crossing, final line/byte and invalid-capacity rejection");
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

static void command_strobes() {
  for (unsigned strobe = 0; strobe < 16; ++strobe) {
    for (unsigned opcode : {1u, 2u}) {
      Test command;
      require(command.write(8, 0x1000) == 0, "Command address setup failed");
      require(command.write(0x10, 0xa5a5a500u | opcode, strobe) == 0,
          "Upper bytes changed the PIO command");
      if (strobe & 1) {
        command.wait();
      }
      require(command.reads == unsigned((strobe & 1) && opcode == 1)
          && command.writes == unsigned((strobe & 1) && opcode == 2),
          "Command byte enables changed the memory operation count");
    }
  }
  for (unsigned strobe = 0; strobe < 16; strobe += 2) {
    for (unsigned opcode : {1u, 2u}) {
      Test command;
      command.pause = true;
      require(command.write(0x10, opcode) == 0, "Initial busy command failed");
      const uint32_t status = command.read(4);
      require(command.write(0x10, 0xffffff03u, strobe) == 0,
          "Disabled command byte was rejected while busy");
      require(command.read(4) == status && command.reads == 0 && command.writes == 0,
          "Disabled command byte altered an active operation");
      command.pause = false;
      command.wait();
      require(command.reads == unsigned(opcode == 1) && command.writes == unsigned(opcode == 2),
          "Ignored command changed the active memory operation");
    }
  }
  for (unsigned opcode : {0u, 3u, 255u}) {
    Test command;
    require(command.write(0x10, 0xaabbcc00u | opcode, 15) == 2,
        "Invalid low command byte was accepted");
    require(command.reads == 0 && command.writes == 0,
        "Rejected command reached memory");
  }
  std::puts("PASSED: PIO command byte, all 16 strobes, upper-byte independence, busy no-ops and invalid opcodes");
}

int main() {
  command_strobes();
  Test test;
#ifdef TEST_PIO_DUAL_CHANNEL
  test.dut.memory_ready = 3;
#endif
  require(test.read(0) == 0x56595043, "Signature differs");
#ifdef TEST_PIO_DUAL_CHANNEL
  require(test.read(4) == 0x30, "Dual-channel reset status differs");
#else
  require(test.read(4) == 0x20, "Reset status differs");
#endif
  require(test.write(0x100, 0x12345678) == 0, "Data write failed");
  require(test.write(0x100, 0xaabbccdd, 5) == 0, "Masked register write failed");
  require(test.read(0x100) == 0x12bb56dd, "Register byte enables differ");
  require(test.write(0x102, 0) == 3, "Unaligned register write accepted");
  require(test.write(0x200, 0) == 3, "Unknown register write accepted");
  test.read(0x102, 3);
  test.read(0x200, 3);

#ifdef TEST_PIO_DUAL_CHANNEL
  const std::array<uint64_t, 6> addresses = {
      0x1000, 0x3fffffc0, 0x40001000, 0x7fffefc0, 0x80001000, 0xffffffc0};
#else
  const std::array<uint64_t, 4> addresses = {0x1000, 0x3fffffc0, 0x40001000, 0x7fffefc0};
#endif
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
#ifdef TEST_PIO_DUAL_CHANNEL
  for (const auto& channel : {std::pair<unsigned, uint32_t>{2, 0x1000}, {1, 0x80001000}}) {
    test.dut.memory_ready = channel.first;
    require(test.write(8, channel.second) == 0
        && test.write(0x10, 1) == 2, "Unready selected channel command was not rejected");
    test.wait(2);
  }
  require(test.reads + test.writes == issued, "Unready selected channel issued AXI traffic");
  test.dut.memory_ready = 1;
  require(test.write(8, 0x1000) == 0 && test.write(0x10, 1) == 0,
      "Ready CH0 command was rejected");
  test.wait();
  test.dut.memory_ready = 2;
  require(test.write(8, 0x80001000) == 0 && test.write(0x10, 1) == 0,
      "Ready CH1 command was rejected");
  test.wait();
  require(test.reads + test.writes == issued + 2,
      "Ready channel selection did not issue exactly two reads");
  test.dut.memory_ready = 3;
#else
  for (unsigned ready : {0u, 1u}) {
    test.dut.memory_ready = ready;
    require(test.write(8, 0x1000) == 0
        && test.write(0x10, 1) == 2, "Unready channel command accepted");
    test.wait(2);
  }
  require(test.reads + test.writes == issued, "Rejected command issued AXI traffic");
  test.dut.memory_ready = 2;
#endif
  for (unsigned response : {2u, 3u}) {
    test.response = response;
    require(test.write(0x10, 1) == 0, "Error read command rejected");
    test.wait(response);
    require(test.write(0x10, 2) == 0, "Error write command rejected");
    test.wait(response);
  }
#ifdef TEST_PIO_DUAL_CHANNEL
  std::printf("PASSED: dual-channel PIO, %u writes, %u reads, 4 GiB address bounds and CH0/CH1 readiness selection\n",
#else
  std::printf("PASSED: PIO, %u writes, %u reads, 2 GiB address bounds, byte masks, guards, independent AXI-Lite channels, stalls and error responses\n",
#endif
        test.writes, test.reads);
#ifdef TEST_PIO_TRANSPORT
    host_test(test);
    transport_capacity_test();
#endif
#ifdef TEST_PIO_DUAL_CHANNEL
  const unsigned before_upper_guard = test.reads + test.writes;
  require(test.write(8, 0x1000) == 0 && test.write(0xc, 1) == 0
      && test.write(0x10, 1) == 2,
      "Dual-channel upper-address guard command failed");
  test.wait(3);
  require(test.reads + test.writes == before_upper_guard,
      "Dual-channel upper-address rejection issued AXI traffic");
#endif
#ifdef TEST_HOST_MEMORY
    memory_host_test();
#endif
  return 0;
}
