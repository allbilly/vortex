// Copyright © 2019-2026
// Licensed under the Apache License, Version 2.0.

#pragma once
#include <ypcb_transport.h>
#include <ypcb_ddr_config.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>

namespace ypcb_test {
using vortex::ypcb::Mmio;
namespace cfg = vortex::ypcb::ddr_config;

inline void require(bool condition, const char* message) {
  if (!condition) {
    std::fprintf(stderr, "FAIL: %s\n", message);
    std::exit(1);
  }
}

class CsrOracle : public Mmio {
public:
  struct State {
    std::array<uint32_t, 2048> registers{};
    std::array<unsigned, 9> delay{}, bitslip{}, write_bitslip{};
    std::array<std::array<uint32_t, 5>, 4> memory{}, capture{};
    std::vector<std::pair<uint32_t, uint32_t>> modes;
    unsigned reads = 0, writes = 0, activates = 0, precharges = 0;
    bool active = false;
  };
  std::array<State, 2> banks;
  unsigned accesses = 0;
  unsigned forced_status = 0;
  int broken_lane = -1;
  bool no_windows = false;
  bool persistent_error = false;
  bool reject_ecc_enable = false;
  uint32_t fail_once = 0;
  std::array<std::array<int, 8>, 9> read_bit_offset{};
  std::array<uint8_t, 9> unreadable_bits{};
  std::array<int, 9> required_write_slip{};

  static unsigned first(unsigned lane) {
    return 2 + lane * 2;
  }
  static unsigned last(unsigned lane) {
    return first(lane) + 3 + lane % 5;
  }
  static unsigned slip(unsigned lane, unsigned bank) {
    return (lane * 3 + bank) % 8;
  }

  int read32(uint32_t offset, uint32_t* value) override {
    ++accesses;
    if (persistent_error) {
      return -1;
    }
    if (offset == 0x3000) {
      *value = 0x56595043;
      return 0;
    }
    if (offset == 0x3004) {
      *value = 2;
      return 0;
    }
    if (offset == 0x3008) {
      *value = 0x8002 | forced_status;
      for (unsigned bank = 1; bank < 2; ++bank) {
        *value |= banks[bank].registers[cfg::ddrctrl_init_done / 4] << (2 + bank);
        *value |= banks[bank].registers[cfg::ddrctrl_init_error / 4] << (4 + bank);
      }
      return 0;
    }
    require(offset >= 0x4000 && offset < 0x8000 && offset % 4 == 0,
            "DDR read escaped its aligned BAR windows");
    const unsigned bank = (offset - 0x4000) / 0x2000;
    const uint32_t local = (offset - 0x4000) % 0x2000;
    for (unsigned phase = 0; phase < 4; ++phase) {
      if (local >= cfg::phases[phase].rddata && local < cfg::phases[phase].rddata + 20) {
        *value = banks[bank].capture[phase][(local - cfg::phases[phase].rddata) / 4];
        return 0;
      }
    }
    *value = banks[bank].registers[local / 4];
    return 0;
  }

  int write32(uint32_t offset, uint32_t value) override {
    ++accesses;
    if (persistent_error || offset == fail_once) {
      fail_once = 0;
      return -1;
    }
    require(offset >= 0x4000 && offset < 0x8000 && offset % 4 == 0,
            "DDR write escaped its aligned BAR windows");
    const unsigned bank = (offset - 0x4000) / 0x2000;
    const uint32_t local = (offset - 0x4000) % 0x2000;
    auto& state = banks[bank];
    const uint32_t selected = state.registers[cfg::ddrphy_dly_sel / 4];
    if (local == cfg::ecc_axi_0_enable && value == 1 && reject_ecc_enable) {
      return 0;
    }
    state.registers[local / 4] = value;
    for (unsigned lane = 0; lane < 9; ++lane) {
      if (!((selected >> lane) & 1)) {
        continue;
      }
      if (local == cfg::ddrphy_rdly_dq_rst) {
        state.delay[lane] = 0;
      } else if (local == cfg::ddrphy_rdly_dq_inc) {
        state.delay[lane] = (state.delay[lane] + 1) % 32;
      } else if (local == cfg::ddrphy_rdly_dq_bitslip_rst) {
        state.bitslip[lane] = 0;
      } else if (local == cfg::ddrphy_rdly_dq_bitslip) {
        state.bitslip[lane] = (state.bitslip[lane] + 1) % 8;
      } else if (local == cfg::ddrphy_wdly_dq_bitslip_rst) {
        state.write_bitslip[lane] = 0;
      } else if (local == cfg::ddrphy_wdly_dq_bitslip) {
        state.write_bitslip[lane] = (state.write_bitslip[lane] + 1) % 8;
      }
    }
    for (unsigned phase = 0; phase < 4; ++phase) {
      if (local == cfg::phases[phase].issue && value == 1) {
        execute(bank, phase);
      }
    }
    if (local == cfg::ddrctrl_init_done && value == 1) {
      require(!state.active && state.registers[cfg::sdram_dfii_control / 4] == 1
              && state.registers[cfg::ecc_axi_0_enable / 4] == 1,
              "Initialization was published before controller/ECC handoff");
    }
    return 0;
  }

private:
  void execute(unsigned bank, unsigned phase) {
    auto& state = banks[bank];
    const auto& ports = cfg::phases[phase];
    const uint32_t command = state.registers[ports.command / 4];
    if (command == 15) {
      require(phase == 0, "Mode register used the wrong phase");
      state.modes.emplace_back(state.registers[ports.bank / 4], state.registers[ports.address / 4]);
    } else if (command == 9) {
      require(!state.active && phase == 0 && state.registers[ports.address / 4] == 0
              && state.registers[ports.bank / 4] == 0, "Probe activated an unexpected row/bank");
      state.active = true;
      ++state.activates;
    } else if (command == 23) {
      require(state.active && phase == 3 && state.registers[ports.address / 4] == 0
              && state.registers[ports.bank / 4] == 0, "Probe write used the wrong phase/column");
      for (unsigned p = 0; p < 4; ++p) {
        for (unsigned word = 0; word < 5; ++word) {
          state.memory[p][word] = state.registers[(cfg::phases[p].wrdata / 4) + word];
        }
        require((state.memory[p][0] & 0xffff0000u) == 0, "144-bit CSR padding differs");
      }
      ++state.writes;
    } else if (command == 37) {
      require(state.active && phase == 3, "Probe read used the wrong phase");
      state.capture = state.memory;
      for (unsigned lane = 0; lane < 9; ++lane) {
        uint32_t bad = no_windows || int(lane) == broken_lane
            || int(state.write_bitslip[lane]) != required_write_slip[lane] ? 255 : unreadable_bits[lane];
        for (unsigned bit = 0; bit < 8; ++bit) {
          const unsigned framing = unsigned(int(slip(lane, bank)) + read_bit_offset[lane][bit]) & 7;
          if (state.bitslip[lane] != framing
              || state.delay[lane] < first(lane) || state.delay[lane] > last(lane)) {
            bad |= 1u << bit;
          }
        }
        for (unsigned byte : {lane, lane + 9}) {
          for (unsigned p = 0; p < 4; ++p) {
            state.capture[p][4 - byte / 4] ^= bad << ((byte % 4) * 8);
          }
        }
      }
      ++state.reads;
    } else if (command == 11) {
      require(state.active && phase == 0 && state.registers[ports.address / 4] == 0,
              "Probe precharge differed");
      state.active = false;
      ++state.precharges;
    } else {
      require(command == 3 && phase == 0 && state.registers[ports.address / 4] == 0x400,
              "Unexpected generated initialization command");
    }
  }
};

}
