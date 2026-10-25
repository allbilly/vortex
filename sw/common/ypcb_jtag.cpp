// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_jtag.h"
#include <array>
#include <charconv>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

namespace vortex::ypcb {
Jtag::~Jtag() {
  if (socket_ >= 0) {
    close(socket_);
  }
}
int Jtag::connect(unsigned port) {
  if (socket_ >= 0 || port == 0 || port > 65535) {
    return -1;
  }
#ifdef __APPLE__
  socket_ = socket(AF_INET, SOCK_STREAM, 0);
#else
  socket_ = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
#endif
  if (socket_ < 0) {
    return -1;
  }
#ifdef __APPLE__
  const int no_sigpipe = 1;
  if (fcntl(socket_, F_SETFD, FD_CLOEXEC) != 0
      || setsockopt(socket_, SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe, sizeof(no_sigpipe)) != 0) {
    return -1;
  }
#endif
  timeval timeout{30, 0};
  if (setsockopt(socket_, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0
      || setsockopt(socket_, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) != 0) {
    return -1;
  }
  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_port = htons(uint16_t(port));
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  return ::connect(socket_, reinterpret_cast<sockaddr*>(&address), sizeof(address));
}
int Jtag::transact(bool write, uint32_t offset, uint32_t* value) {
  if (value == nullptr || offset >= 65536 || (offset & 3)) {
    return -1;
  }
  std::array<char, 64> command{};
  int length = write ? std::snprintf(command.data(), command.size(), "W %04x %08x\n", offset, *value)
                     : std::snprintf(command.data(), command.size(), "R %04x\n", offset);
  if (length <= 0 || size_t(length) >= command.size()) {
    return -1;
  }
  return exchange(std::string(command.data(), size_t(length)), value, 1);
}

int Jtag::exchange(const std::string& command, uint32_t* values, size_t words) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (socket_ < 0 || poisoned_ || !values || words == 0 || words > 16) return -1;
  size_t sent = 0;
  while (sent < command.size()) {
#ifdef __APPLE__
    constexpr int send_flags = 0;
#else
    constexpr int send_flags = MSG_NOSIGNAL;
#endif
    const auto count = send(socket_, command.data() + sent, command.size() - sent, send_flags);
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count <= 0) {
      poisoned_ = true;
      return -1;
    }
    sent += size_t(count);
  }
  std::array<char, 256> response{};
  for (size_t used = 0; used + 1 < response.size(); ++used) {
    ssize_t count;
    do {
      count = recv(socket_, response.data() + used, 1, 0);
    } while (count < 0 && errno == EINTR);
    if (count != 1) {
      poisoned_ = true;
      return -1;
    }
    if (response[used] == '\n') {
      bool valid = used == 2 + 9 * words && response[0] == 'O' && response[1] == 'K';
      for (size_t i = 0; valid && i < words; ++i) {
        const auto start = response.data() + 3 + 9 * i;
        const auto converted = std::from_chars(start, start + 8, values[i], 16);
        valid = response[2 + 9 * i] == ' ' && converted.ec == std::errc{}
                && converted.ptr == start + 8;
      }
      if (!valid) {
        std::fprintf(stderr, "[VXDRV] Socket MMIO rejected: %s", response.data());
        poisoned_ = true;
        return -1;
      }
      return 0;
    }
  }
  poisoned_ = true;
  return -1;
}
int Jtag::read32(uint32_t offset, uint32_t* value) {
  return transact(false, offset, value);
}
int Jtag::write32(uint32_t offset, uint32_t value) {
  return transact(true, offset, &value);
}
int Jtag::read_words(uint32_t offset, uint32_t* values, size_t count) {
  if (!values || count == 0 || count > 16 || (offset & 3) || offset > 65536 - count * 4) return -1;
  std::array<char, 32> command{};
  std::snprintf(command.data(), command.size(), "BR %04x %02x\n", offset, unsigned(count));
  return exchange(command.data(), values, count);
}
int Jtag::write_words(uint32_t offset, const uint32_t* values, size_t count) {
  if (!values || count == 0 || count > 16 || (offset & 3) || offset > 65536 - count * 4) return -1;
  std::array<char, 32> part{};
  std::snprintf(part.data(), part.size(), "BW %04x %02x", offset, unsigned(count));
  std::string command = part.data();
  for (size_t i = 0; i < count; ++i) {
    std::snprintf(part.data(), part.size(), " %08x", values[i]);
    command += part.data();
  }
  uint32_t result;
  return exchange(command + '\n', &result, 1);
}
}
