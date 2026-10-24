// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include <ypcb_jtag.h>
#include <ypcb_wl_config.h>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fcntl.h>
#include <string>
#include <sys/file.h>
#include <unistd.h>
#include <vector>

using namespace vortex::ypcb;

static void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

int main() {
  static_assert(wl_config::board_abi == 5 && wl_config::payload_bytes == 0x100000000ull);
  const auto lock_path = std::string("/tmp/vortex-ypcb-") + std::to_string(getuid()) + ".lock";
  const int lease = open(lock_path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
  require(lease >= 0 && flock(lease, LOCK_EX | LOCK_NB) == 0, "Another YPCB runtime owns the device");
  const char* port_text = std::getenv("VORTEX_YPCB_JTAG_PORT");
  char* end = nullptr;
  const unsigned long port = port_text ? std::strtoul(port_text, &end, 10) : 3124;
  require(port > 0 && port < 65536 && (!port_text || (end != port_text && *end == '\0')),
          "Invalid JTAG port");
  Jtag mmio;
  require(mmio.connect(unsigned(port)) == 0, "Cannot connect to the JTAG MMIO bridge");
  uint32_t signature = 0, version = 0, status = 0, control = 0;
  require(mmio.read32(0x3000, &signature) == 0 && signature == 0x56595043
      && mmio.read32(0x3004, &version) == 0 && version == wl_config::board_abi
      && mmio.read32(0x3008, &status) == 0 && (status & 0x7fff) == 0x68f
      && status >> 16 == 3, "Both calibrated memory channels must already be ready");
  // The final physical DRAM pages are outside the application heap; probe them with the AFU drained.
  require(mmio.read32(0, &control) == 0 && control != 0xffffffff
      && (control & 0x34) == 4, "AFU must be quiesced and held in reset before the raw probe");
  Pio pio(mmio, std::chrono::seconds(30), wl_config::payload_bytes);
  require(pio.initialize() == Result::success, "PIO did not observe both ready channels");
  constexpr std::array<uint64_t, 5> addresses{
      0x00100000, 0x7ff00000, 0x80100000, 0xffffe000, 0x7ffff000};
  std::array<std::vector<uint8_t>, addresses.size()> expected;
  for (size_t region = 0; region < addresses.size(); ++region) {
    expected[region].resize(8192);
    for (size_t byte = 0; byte < expected[region].size(); ++byte) {
      expected[region][byte] = uint8_t(region * 71 + byte * 19 + byte / 64);
    }
    require(pio.write(addresses[region], expected[region].data(), expected[region].size())
        == Result::success, "Raw DDR write failed");
  }
  const std::array<uint8_t, 13> patch{
      0x91, 0x27, 0xf4, 0x63, 0x08, 0xbb, 0x51, 0x3c, 0xae, 0x79, 0x12, 0xe0, 0x45};
  require(pio.write(0x7ffffffd, patch.data(), patch.size()) == Result::success,
          "Partial write across the physical channel boundary failed");
  for (size_t byte = 0; byte < patch.size(); ++byte) expected[4][4093 + byte] = patch[byte];
  require(pio.write(0xfffffff3, patch.data(), patch.size()) == Result::success,
          "Partial write through the final byte of 4 GiB failed");
  for (size_t byte = 0; byte < patch.size(); ++byte) expected[3][8179 + byte] = patch[byte];
  for (size_t region = 0; region < addresses.size(); ++region) {
    std::vector<uint8_t> actual(expected[region].size());
    require(pio.read(addresses[region], actual.data(), actual.size()) == Result::success,
            "Raw DDR read failed");
    require(actual == expected[region], "Raw DDR data differs or physical channels alias");
    std::printf("Verified raw 8192 bytes at 0x%08llx\n",
                static_cast<unsigned long long>(addresses[region]));
  }
  std::array<uint64_t, 27> line_addresses{};
  line_addresses[0] = 0x01010000;
  for (unsigned bit = 6; bit < 32; ++bit) line_addresses[bit - 5] = line_addresses[0] ^ (uint64_t(1) << bit);
  std::array<std::array<uint8_t, 64>, line_addresses.size()> line_data{};
  for (size_t line = 0; line < line_addresses.size(); ++line) {
    for (size_t byte = 0; byte < line_data[line].size(); ++byte) {
      line_data[line][byte] = uint8_t(line * 73 + byte * 11);
    }
    require(pio.write(line_addresses[line], line_data[line].data(), line_data[line].size())
        == Result::success, "Address-line pattern write failed");
  }
  for (size_t line = 0; line < line_addresses.size(); ++line) {
    std::array<uint8_t, 64> actual{};
    require(pio.read(line_addresses[line], actual.data(), actual.size()) == Result::success
        && actual == line_data[line], "A physical address line aliases another location");
  }
  std::puts("Verified 27 independent lines covering physical address bits 6..31");
  uint8_t value = 0;
  require(pio.read(wl_config::payload_bytes, &value, 1) == Result::invalid
      && pio.write(wl_config::payload_bytes - 1, patch.data(), 2) == Result::invalid,
      "PIO accepted a range beyond the physical 4 GiB aperture");
  require(mmio.read32(0x3008, &status) == 0 && (status & 0x7fff) == 0x68f
      && status >> 16 == 3, "Memory readiness changed during the raw probe");
  std::puts("PASSED: raw CH0/CH1 4 GiB, final byte, cross-channel partial writes and no aliases");
  close(lease);
}
