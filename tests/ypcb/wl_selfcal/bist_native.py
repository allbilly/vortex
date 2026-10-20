#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

from collections import deque
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'hw/syn/xilinx/ypcb/opentpu'))
from migen import Module, run_simulation
from litedram.common import LiteDRAMNativePort
from bist import BIST

MASK64 = (1 << 64) - 1
MASK72 = (1 << 72) - 1
SEED = 0x0123456789abcdef


def expected_word(state, address, mode):
    if mode:
        group = ((address | ((~address & ((1 << 25) - 1)) << 25) | (address << 50))
                 ^ (SEED | SEED << 64)) & MASK72
        return sum(group << (72 * i) for i in range(8))
    result = 0
    for i in range(8):
        shift = i * 7
        rotated = ((state << shift) | (state >> (64 - shift))) & MASK64
        group = rotated | (((rotated & 255) ^ (rotated >> 56)) << 64)
        result |= group << (72 * i)
    return result


def next_state(state):
    state ^= (state << 13) & MASK64
    state ^= state >> 7
    return state ^ ((state << 17) & MASK64)


class Test(Module):
    def __init__(self):
        self.port = LiteDRAMNativePort('both', 25, 576)
        self.submodules.bist = BIST(self.port)


def check(dut):
    port, engine = dut.port, dut.bist
    rng = random.Random(9)
    memory = {}
    cases = 0
    for length in (1, 31, 128):
        for pattern in (0, 1):
            for reading, corrupt in ((False, False), (True, False), (True, True), (True, False)):
                commands, responses = deque(), deque()
                ncmd = ndata = errors = 0
                state = SEED
                yield port.cmd.ready.eq(0)
                yield port.wdata.ready.eq(0)
                yield port.rdata.valid.eq(0)
                yield engine.base.storage.eq(7)
                yield engine.length.storage.eq(length)
                yield engine.seed.storage.eq(SEED)
                yield engine.mode.storage.eq(int(reading) | pattern << 1)
                yield engine.start.storage.eq(1)
                yield engine.start.re.eq(1)
                yield
                yield engine.start.re.eq(0)
                yield engine.start.storage.eq(0)
                yield
                for cycle in range(10000):
                    if (yield port.cmd.valid) and (yield port.cmd.ready):
                        address = (yield port.cmd.addr)
                        assert address == 7 + ncmd and bool((yield port.cmd.we)) != reading
                        if reading:
                            responses.append((address, cycle + rng.randrange(1, 5)))
                        else:
                            commands.append(address)
                        ncmd += 1
                    if not reading and (yield port.wdata.valid) and (yield port.wdata.ready):
                        assert commands and (yield port.wdata.we) == (1 << 72) - 1
                        address = commands.popleft()
                        value = (yield port.wdata.data)
                        assert value == expected_word(state, address, pattern)
                        memory[address] = value
                        state = next_state(state)
                        ndata += 1
                    if reading and (yield port.rdata.valid) and (yield port.rdata.ready):
                        responses.popleft()
                        errors += int(corrupt and ndata % 17 == 0)
                        ndata += 1
                    if (yield engine.done.status):
                        break
                    yield port.cmd.ready.eq(rng.randrange(4) != 0)
                    yield port.wdata.ready.eq(rng.randrange(3) != 0)
                    response = bool(responses and responses[0][1] <= cycle and rng.randrange(3) != 0)
                    yield port.rdata.valid.eq(response)
                    if response:
                        value = memory[responses[0][0]]
                        if corrupt and ndata % 17 == 0:
                            value ^= (1 << 0) | (1 << (7 * 72 + 8 * 8 + 7))
                        yield port.rdata.data.eq(value)
                    yield
                else:
                    raise AssertionError('Native BIST timed out under backpressure')
                assert ncmd == ndata == length and not commands and not responses
                assert (yield engine.beats.status) == length
                assert (yield engine.errors.status) == errors
                assert (yield engine.lane_bits.status) == ((1 | 1 << 71) if errors else 0)
                for lane in range(9):
                    assert (yield engine.lane_errors[lane].status) == (errors if lane in (0, 8) else 0)
                cases += 1
                yield
    print(f'NATIVE BIST PASS: {cases} write/read cases, two patterns, stalls, lane0/ECC8 errors and counter reset')


if __name__ == '__main__':
    dut = Test()
    run_simulation(dut, check(dut))
