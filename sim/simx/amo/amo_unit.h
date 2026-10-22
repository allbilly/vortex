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

#pragma once

#include <stdint.h>
#include "reservation_set.h"
#include "types.h"
#include "amo_ops.h"

namespace vortex {

// Byte addresses are normalized to the RTL's bank-local line index/tag.
class AmoUnit {
public:
  AmoUnit(uint32_t reservation_size, uint32_t line_bits, uint32_t bank_bits);

  // Pure RMW kernel — no reservation touch, no mutation. `unsigned_minmax`
  // selects the unsigned variant of MIN/MAX (signed by default).
  AmoComputeResult compute(MemOp op, uint8_t width,
                           uint64_t old_word, uint64_t rhs,
                           bool unsigned_minmax = false,
                           uint64_t cmp = 0) const;

  void reserve(uint32_t hart_id, uint64_t line_addr);

  // SC's success criterion: an entry exists for (hart_id, line_addr).
  bool check(uint32_t hart_id, uint64_t line_addr) const;

  void invalidate(uint64_t line_addr);

  // Drop the reservation matching this entry. Called on a successful
  // SC to consume the lock.
  void clear(uint32_t hart_id, uint64_t line_addr);

  void reset();

private:
  static constexpr uint32_t HOLD_CREDITS = (1u << 6) - 1;
  uint32_t address_shift_;
  ReservationSet reservations_;
};

} // namespace vortex
