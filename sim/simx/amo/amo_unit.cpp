// Copyright © 2019-2023
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "amo_unit.h"
#include <cassert>

using namespace vortex;

AmoUnit::AmoUnit(uint32_t reservation_size, uint32_t line_bits, uint32_t bank_bits)
  : address_shift_(line_bits + bank_bits)
  , reservations_(reservation_size, HOLD_CREDITS)
{}

AmoComputeResult AmoUnit::compute(MemOp op, uint8_t width,
                                  uint64_t old_word, uint64_t rhs,
                                  bool unsigned_minmax,
                                  uint64_t cmp) const {
  return amo_compute(op, width, old_word, rhs, unsigned_minmax, cmp);
}

void AmoUnit::reserve(uint32_t hart_id, uint64_t line_addr) {
  reservations_.reserve(hart_id, line_addr >> address_shift_);
}

bool AmoUnit::check(uint32_t hart_id, uint64_t line_addr) const {
  return reservations_.check(hart_id, line_addr >> address_shift_);
}

void AmoUnit::invalidate(uint64_t line_addr) {
  reservations_.invalidate(line_addr >> address_shift_);
}

void AmoUnit::clear(uint32_t hart_id, uint64_t line_addr) {
  reservations_.clear(hart_id, line_addr >> address_shift_);
}

void AmoUnit::reset() {
  reservations_.reset();
}
