// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#include "protocol.h"
#include <cassert>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

enum class Fault {
  none,
  startup_busy,
  preexisting_bist,
  total_errors,
  lane_errors,
  bit_errors,
  incomplete_beats,
  no_busy_transition,
  timeout,
  cancel,
};

class MockMmio;
MockMmio* cancel_target = nullptr;
bool cancelled();

class MockMmio final : public ypcb_bist::Mmio {
public:
  explicit MockMmio(Fault fault = Fault::none, uint32_t abi = 5,
                    unsigned fault_channel = 0, uint32_t fault_mode = 0,
                    unsigned fault_lane = 0, unsigned fault_word = 0)
      : fault_(fault), abi_(abi), fault_channel_(fault_channel),
        fault_mode_(fault_mode), fault_lane_(fault_lane), fault_word_(fault_word) {
    init_done_.fill(1);
    init_error_.fill(0);
    regs_[0x6000 + ypcb_bist::cfg::ecc_axi_0_enable] = 1;
    regs_[0x6000 + ypcb_bist::cfg::ecc_axi_0_sec_errors] = 0;
    regs_[0x6000 + ypcb_bist::cfg::ecc_axi_0_ded_errors] = 0;
  }

  int read32(uint32_t address, uint32_t* value) override {
    if (!value) return -1;
    if (address == 0x3000) {
      *value = 0x56595043;
      return 0;
    }
    if (address == 0x3004) {
      *value = abi_;
      return 0;
    }
    if (address == 0x3008) {
      *value = 3 | (uint32_t(init_done_[0]) << 2) | (uint32_t(init_done_[1]) << 3)
             | (fault_ == Fault::startup_busy ? (1u << 8) : 0);
      status_init_done_history.push_back((*value >> 2) & 3);
      return 0;
    }
    for (unsigned index = 0; index < ypcb_bist::channels.size(); ++index) {
      const auto& channel = ypcb_bist::channels[index];
      const uint32_t offset = address - channel.base;
      if (address == channel.base + channel.init_done) {
        *value = init_done_[index];
        return 0;
      }
      if (address == channel.base + channel.init_error) {
        *value = init_error_[index];
        return 0;
      }
      if (address == channel.base + channel.done) {
        *value = read_done(index);
        return 0;
      }
      if (address == channel.base + channel.beats) {
        *value = fault_for(index, current_mode_) && fault_ == Fault::incomplete_beats
               ? words_ - 1 : words_;
        return 0;
      }
      if (address == channel.base + channel.ticks) {
        *value = words_ + 3;
        return 0;
      }
      if (address == channel.base + channel.errors) {
        *value = fault_for(index, current_mode_) && fault_ == Fault::total_errors ? 1 : 0;
        return 0;
      }
      const uint32_t lane_errors = channel.base + channel.lane_errors;
      if (address >= lane_errors && address < lane_errors + channel.lanes * 4) {
        const unsigned lane = (address - lane_errors) / 4;
        *value = fault_for(index, current_mode_) && fault_ == Fault::lane_errors
               && lane == fault_lane_ ? 1 : 0;
        if (*value) {
          fault_seen_ = true;
          fault_address_ = address;
        }
        return 0;
      }
      const uint32_t lane_bits = channel.base + channel.lane_bits;
      if (address >= lane_bits && address < lane_bits + channel.lane_words * 4) {
        const unsigned word = (address - lane_bits) / 4;
        *value = fault_for(index, current_mode_) && fault_ == Fault::bit_errors
               && word == fault_word_ ? 1 : 0;
        if (*value) {
          fault_seen_ = true;
          fault_address_ = address;
        }
        return 0;
      }
      if (address >= channel.base && offset < 0x2000) {
        auto it = regs_.find(address);
        *value = it == regs_.end() ? 0 : it->second;
        return 0;
      }
    }
    auto it = regs_.find(address);
    *value = it == regs_.end() ? 0 : it->second;
    return 0;
  }

  int write32(uint32_t address, uint32_t value) override {
    writes.emplace_back(address, value);
    if (address == 0x6000 + ypcb_bist::channels[1].init_done) {
      init_done_[1] = value;
      init_done_writes[1].push_back(value);
      return 0;
    }
    if (address == ypcb_bist::channels[0].base + ypcb_bist::channels[0].init_done) {
      init_done_[0] = value;
      init_done_writes[0].push_back(value);
      return 0;
    }
    if (address == ypcb_bist::channels[1].base + ypcb_bist::channels[1].init_error) {
      init_error_[1] = value;
      return 0;
    }
    if (address == ypcb_bist::channels[0].base + ypcb_bist::channels[0].init_error) {
      init_error_[0] = value;
      return 0;
    }
    for (unsigned index = 0; index < ypcb_bist::channels.size(); ++index) {
      const auto& channel = ypcb_bist::channels[index];
      if (address == channel.base + channel.start) {
        if (value != 1) return -1;
        words_ = regs_[channel.base + channel.length];
        current_mode_ = regs_[channel.base + channel.mode];
        active_channel_ = index;
        active_ = true;
        done_reads_ = 0;
        ++start_count;
        start_order.emplace_back(index, current_mode_);
        if (fault_ == Fault::cancel) canceled_ = true;
        return 0;
      }
      if (address >= channel.base && address < channel.base + 0x2000) {
        regs_[address] = value;
        return 0;
      }
    }
    regs_[address] = value;
    return 0;
  }

  bool was_cancelled() const { return canceled_; }
  bool fault_seen() const { return fault_seen_; }
  uint32_t fault_address() const { return fault_address_; }
  std::vector<std::pair<uint32_t, uint32_t>> writes;
  std::vector<std::pair<unsigned, uint32_t>> start_order;
  std::array<std::vector<uint32_t>, 2> init_done_writes;
  std::vector<uint32_t> status_init_done_history;
  unsigned start_count = 0;

  void assert_blocked() const {
    assert(init_done_[0] == 0 && init_done_[1] == 0);
    assert(init_error_[0] == 1 && init_error_[1] == 1);
  }

  void assert_armed() const {
    assert(init_done_[0] == 1 && init_done_[1] == 1);
    assert(init_error_[0] == 0 && init_error_[1] == 0);
  }

private:
  bool fault_for(unsigned channel, uint32_t mode) const {
    return channel == fault_channel_ && mode == fault_mode_;
  }

  uint32_t read_done(unsigned channel) {
    if (fault_ == Fault::preexisting_bist && channel == fault_channel_ && start_count == 0)
      return 0;
    if (!active_ || channel != active_channel_)
      return 1;
    if (fault_for(channel, current_mode_) && fault_ == Fault::timeout)
      return 0;
    if (fault_for(channel, current_mode_) && fault_ == Fault::no_busy_transition) {
      active_ = false;
      return 1;
    }
    if (done_reads_++ == 0)
      return 0;
    active_ = false;
    return 1;
  }

  Fault fault_;
  uint32_t abi_;
  unsigned fault_channel_;
  uint32_t fault_mode_;
  unsigned fault_lane_;
  unsigned fault_word_;
  uint32_t current_mode_ = 0;
  uint32_t words_ = 0;
  unsigned active_channel_ = 0;
  unsigned done_reads_ = 0;
  bool active_ = false;
  bool canceled_ = false;
  bool fault_seen_ = false;
  uint32_t fault_address_ = 0;
  std::array<uint32_t, 2> init_done_{};
  std::array<uint32_t, 2> init_error_{};
  std::map<uint32_t, uint32_t> regs_;
};

bool cancelled() {
  return cancel_target && cancel_target->was_cancelled();
}

template <typename Callable>
void expect_failure(Callable&& action, const char* text) {
  bool failed = false;
  try {
    action();
  } catch (const std::exception& error) {
    failed = true;
    assert(std::string(error.what()).find(text) != std::string::npos);
  }
  assert(failed);
}

void test_success() {
  MockMmio mmio;
  ypcb_bist::Session session(mmio, std::chrono::milliseconds(100));
  const auto passes = session.run(16);
  assert(passes.size() == 8);
  assert(mmio.start_order.size() == 8);
  for (unsigned i = 0; i < passes.size(); ++i) {
    const unsigned channel = i / 4;
    const unsigned mode = i % 4;
    assert(passes[i].channel == channel && passes[i].mode == mode);
    assert(passes[i].words == 16 && passes[i].ticks >= 16);
    assert(passes[i].lanes == ypcb_bist::channels[channel].lanes);
    assert((mmio.start_order[i] == std::pair<unsigned, uint32_t>(channel, mode)));
  }
  mmio.assert_armed();
}

void test_full_length_counters() {
  constexpr uint32_t words = 1u << 25;
  MockMmio mmio;
  ypcb_bist::Session session(mmio, std::chrono::milliseconds(100));
  const auto passes = session.run(words);
  assert(passes.size() == 8 && mmio.start_count == 8);
  for (const auto& pass : passes) {
    assert(pass.words == words);
    assert(pass.ticks == words + 3);
  }
  mmio.assert_armed();
}

void test_preflight_rejects_without_writes() {
  {
    MockMmio mmio(Fault::none, 4);
    ypcb_bist::Session session(mmio, std::chrono::milliseconds(5));
    expect_failure([&] { (void)session.run(16); }, "ABI5");
    assert(mmio.writes.empty());
  }
  {
    MockMmio mmio(Fault::startup_busy);
    ypcb_bist::Session session(mmio, std::chrono::milliseconds(5));
    expect_failure([&] { (void)session.run(16); }, "idle startup");
    assert(mmio.writes.empty());
  }
}

void test_preexisting_bist_fails_closed() {
  MockMmio mmio(Fault::preexisting_bist);
  ypcb_bist::Session session(mmio, std::chrono::milliseconds(5));
  expect_failure([&] { (void)session.run(16); }, "already active");
  assert(mmio.start_count == 0);
  mmio.assert_blocked();
}

void test_fail_closed_faults() {
  for (const auto fault : {Fault::total_errors, Fault::lane_errors,
                           Fault::bit_errors, Fault::incomplete_beats,
                           Fault::no_busy_transition}) {
    MockMmio mmio(fault);
    ypcb_bist::Session session(mmio, std::chrono::milliseconds(10));
    expect_failure([&] { (void)session.run(16); },
                   fault == Fault::no_busy_transition ? "busy transition" :
                   fault == Fault::incomplete_beats ? "Incomplete" :
                   fault == Fault::lane_errors ? "lane errors" :
                   fault == Fault::bit_errors ? "bit errors" : "Incomplete");
    mmio.assert_blocked();
  }
}

void test_late_ch1_fault_keeps_both_channels_blocked(Fault fault,
                                                      unsigned fault_lane,
                                                      unsigned fault_word,
                                                      const char* expected_error,
                                                      unsigned failing_address_offset) {
  constexpr unsigned ch1 = 1;
  constexpr uint32_t last_mode = 3;
  MockMmio mmio(fault, 5, ch1, last_mode, fault_lane, fault_word);
  ypcb_bist::Session session(mmio, std::chrono::milliseconds(100));
  expect_failure([&] { (void)session.run(16); }, expected_error);
  assert(mmio.start_count == 8 && mmio.start_order.size() == 8);
  for (unsigned i = 0; i < mmio.start_order.size(); ++i) {
    const unsigned channel = i / 4;
    const uint32_t mode = i % 4;
    assert((mmio.start_order[i] == std::pair<unsigned, uint32_t>(channel, mode)));
  }
  const uint32_t expected_address = ypcb_bist::channels[ch1].base + failing_address_offset;
  assert(mmio.fault_seen() && mmio.fault_address() == expected_address);
  assert(mmio.status_init_done_history.size() == 9);
  assert(mmio.status_init_done_history.front() == 3);
  for (unsigned i = 1; i < mmio.status_init_done_history.size(); ++i)
    assert(mmio.status_init_done_history[i] == 0);
  for (const auto& writes : mmio.init_done_writes) {
    assert(writes.size() == 2);
    assert(writes[0] == 0 && writes[1] == 0);
  }
  mmio.assert_blocked();
}

void test_final_ch1_pass_faults_keep_both_channels_blocked() {
  constexpr unsigned ch1 = 1;
  const auto& channel = ypcb_bist::channels[ch1];
  const unsigned last_lane = channel.lanes - 1;
  test_late_ch1_fault_keeps_both_channels_blocked(
      Fault::lane_errors, last_lane, 0, "lane errors",
      channel.lane_errors + last_lane * 4);
  const unsigned final_lane_word = channel.lane_words - 1;
  test_late_ch1_fault_keeps_both_channels_blocked(
      Fault::bit_errors, last_lane, final_lane_word, "bit errors",
      channel.lane_bits + final_lane_word * 4);
}

void test_timeout_and_cancel_fail_closed() {
  {
    MockMmio mmio(Fault::timeout);
    ypcb_bist::Session session(mmio, std::chrono::milliseconds(3));
    expect_failure([&] { (void)session.run(16); }, "timed out");
    mmio.assert_blocked();
  }
  {
    MockMmio mmio(Fault::cancel);
    cancel_target = &mmio;
    ypcb_bist::Session session(mmio, std::chrono::milliseconds(20), cancelled);
    expect_failure([&] { (void)session.run(16); }, "interrupted");
    cancel_target = nullptr;
    mmio.assert_blocked();
  }
}

}

int main() {
  test_success();
  test_full_length_counters();
  test_preflight_rejects_without_writes();
  test_preexisting_bist_fails_closed();
  test_fail_closed_faults();
  test_final_ch1_pass_faults_keep_both_channels_blocked();
  test_timeout_and_cancel_fail_closed();
  std::cout << "Native BIST protocol mock PASS" << std::endl;
  return 0;
}
