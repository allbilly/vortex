#include "reservation_set.h"
#include <cstdlib>
#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
  if (argc != 3)
    return 2;
  vortex::ReservationSet reservations(4, std::strtoul(argv[2], nullptr, 0));
  std::ifstream input(argv[1]);
  int op, hart, word, blocked, expected, count = 0;
  while (input >> op >> hart >> word >> blocked >> expected) {
    bool match = reservations.check(hart, word);
    if (expected >= 0 && match != bool(expected))
      return 1;
    std::cout << "TRACE " << count++ << ' ' << op << ' ' << hart << ' ' << word
              << ' ' << blocked << ' ' << match << '\n';
    if (!blocked) {
      if (op == 1) reservations.reserve(hart, word);
      if (op == 2) reservations.clear(hart, word);
      if (op == 3) reservations.invalidate(word);
    }
  }
  return input.eof() ? 0 : 2;
}
