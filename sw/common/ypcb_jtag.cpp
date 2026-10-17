// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "ypcb_jtag.h"
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
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
  socket_ = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if (socket_ < 0) {
    return -1;
  }
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
  std::lock_guard<std::mutex> lock(mutex_);
  if (socket_ < 0 || poisoned_ || value == nullptr || offset >= 65536 || (offset & 3)) {
    return -1;
  }
  std::array<char, 64> command{};
  int length = write ? std::snprintf(command.data(), command.size(), "W %04x %08x\n", offset, *value)
                     : std::snprintf(command.data(), command.size(), "R %04x\n", offset);
  if (length <= 0 || size_t(length) >= command.size()) {
    return -1;
  }
  size_t sent = 0;
  while (sent < size_t(length)) {
    const auto count = send(socket_, command.data() + sent, size_t(length) - sent, MSG_NOSIGNAL);
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count <= 0) {
      poisoned_ = true;
      return -1;
    }
    sent += size_t(count);
  }
  std::array<char, 64> response{};
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
      unsigned result;
      int consumed = 0;
      if (std::sscanf(response.data(), "OK %8x%n", &result, &consumed) != 1
          || consumed != int(used) || consumed != 11) {
        std::fprintf(stderr, "[VXDRV] JTAG MMIO rejected: %s", response.data());
        poisoned_ = true;
        return -1;
      }
      *value = result;
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
}
