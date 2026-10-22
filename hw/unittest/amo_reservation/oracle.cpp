#include "reservation_set.h"
#include "amo_unit.h"
#include <cstdlib>
#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
  if (argc != 7) {
    return 2;
  }
  auto credits = std::strtoul(argv[2], nullptr, 0);
  auto entries = std::strtoul(argv[3], nullptr, 0);
  bool global = std::strtoul(argv[4], nullptr, 0);
  auto line_bits = std::strtoul(argv[5], nullptr, 0);
  auto bank_bits = std::strtoul(argv[6], nullptr, 0);
  vortex::ReservationSet local_reservations(entries, credits);
  vortex::AmoUnit global_reservations(entries, line_bits, bank_bits);
  auto address = [=](uint64_t word) {
    return (word << (line_bits + bank_bits))
         | (((uint64_t(1) << bank_bits) - 1) << line_bits);
  };
  std::ifstream input(argv[1]);
  int op, hart, word, blocked, expected, count = 0;
  while (input >> op >> hart >> word >> blocked >> expected) {
    bool match = global ? global_reservations.check(hart, address(word))
                        : local_reservations.check(hart, word);
    if (expected >= 0 && match != bool(expected)) {
      return 1;
    }
    std::cout << "TRACE " << count++ << ' ' << op << ' ' << hart << ' ' << word
              << ' ' << blocked << ' ' << match << '\n';
    if (!blocked) {
      if (global) {
        if (op == 1) {
          global_reservations.reserve(hart, address(word));
        } else if (op == 2) {
          global_reservations.clear(hart, address(word));
        } else if (op == 3) {
          global_reservations.invalidate(address(word));
        }
      } else {
        if (op == 1) {
          local_reservations.reserve(hart, word);
        } else if (op == 2) {
          local_reservations.clear(hart, word);
        } else if (op == 3) {
          local_reservations.invalidate(word);
        }
      }
    }
  }
  return input.eof() ? 0 : 2;
}
