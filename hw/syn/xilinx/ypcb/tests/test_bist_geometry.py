#!/usr/bin/env python3
"""Bounded Migen coverage for the 8-lane and 9-lane native-port BIST."""

import unittest

from migen import Module
from migen.sim import run_simulation
from litedram.common import LiteDRAMNativePort

from opentpu.bist import BIST


MASK64 = (1 << 64) - 1
BASE = 0x1357
LENGTH = 9
SEED = 0x8B12D4E65A3907CF
ADDRESS_WIDTH = 16


def xorshift64(value):
    value ^= (value << 13) & MASK64
    value ^= value >> 7
    value ^= (value << 17) & MASK64
    return value & MASK64


def expected_word(modules, beat, addrmode):
    group_width = 8 * modules
    data_width = group_width * 8
    if addrmode:
        addr_mask = (1 << ADDRESS_WIDTH) - 1
        address = (BASE + beat) & addr_mask
        repeated_addr = (address | (((~address) & addr_mask) << ADDRESS_WIDTH)
                         | (address << (2 * ADDRESS_WIDTH)))
        repeated_seed = SEED | (SEED << 64)
        group_value = (repeated_addr ^ repeated_seed) & ((1 << group_width) - 1)
        return sum(group_value << (group * group_width) for group in range(8))
    else:
        state = SEED
        for _ in range(beat):
            state = xorshift64(state)
        group_value = 0
        for group in range(8):
            rotate = (7 * group) % 64
            rotated = state if rotate == 0 else (
                ((state << rotate) | (state >> (64 - rotate))) & MASK64)
            if group_width == 72:
                high = (rotated & 0xff) ^ ((rotated >> 56) & 0xff)
                rotated |= high << 64
            group_value |= rotated << (group * group_width)
    return group_value & ((1 << data_width) - 1)


def make_bist(modules):
    port = LiteDRAMNativePort('both', ADDRESS_WIDTH, 8 * modules * 8)
    top = Module()
    top.submodules.bist = BIST(port, modules=modules)
    return top, port, top.bist


def run_case(modules, mode, inject_lane_errors=False):
    top, port, bist = make_bist(modules)
    read = bool(mode & 1)
    addrmode = bool(mode & 2)
    beat_limit = modules + 1 if inject_lane_errors else LENGTH
    response_queue = []
    accepted_commands = []
    accepted_data = 0
    returned_data = 0
    command_count = 0
    data_count = 0

    def process():
        nonlocal accepted_data, returned_data, command_count, data_count
        yield port.cmd.ready.eq(0)
        yield port.wdata.ready.eq(0)
        yield port.rdata.valid.eq(0)
        yield bist.base.storage.eq(BASE)
        yield bist.length.storage.eq(beat_limit)
        yield bist.seed.storage.eq(SEED)
        yield bist.mode.storage.eq(mode)
        yield bist.start.storage.eq(1)
        yield bist.start.re.eq(1)
        yield
        yield bist.start.re.eq(0)
        yield bist.start.storage.eq(0)

        for cycle in range(500):
            cmd_valid = (yield port.cmd.valid)
            cmd_addr = (yield port.cmd.addr)
            cmd_we = (yield port.cmd.we)
            cmd_ready = (yield port.cmd.ready)
            data_valid = (yield port.wdata.valid)
            data_value = (yield port.wdata.data)
            data_ready = (yield port.wdata.ready)
            response_valid = False
            response_value = 0
            response_index = None
            if read and response_queue and cycle - response_queue[0][0] >= 2:
                response_valid = True
                response_index = response_queue[0][1]
                response_value = expected_word(modules, response_index, addrmode)
                if inject_lane_errors and response_index > 0:
                    lane = response_index - 1
                    group = lane % 8
                    bit = lane % 8
                    bit_index = group * (8 * modules) + lane * 8 + bit
                    response_value ^= 1 << bit_index

            yield port.rdata.valid.eq(response_valid)
            yield port.rdata.data.eq(response_value)

            if cmd_valid and cmd_ready:
                self_addr = (BASE + command_count) & ((1 << ADDRESS_WIDTH) - 1)
                assert cmd_addr == self_addr, (modules, mode, cmd_addr, self_addr)
                assert cmd_we == (not read)
                if read:
                    response_queue.append((cycle, command_count))
                accepted_commands.append(cmd_addr)
                command_count += 1

            if data_valid and data_ready:
                if read:
                    raise AssertionError('read mode produced write data')
                expected = expected_word(modules, data_count, addrmode)
                assert data_value == expected, (modules, mode, data_count, hex(data_value), hex(expected))
                data_count += 1
                accepted_data += 1

            if response_valid:
                if not read:
                    raise AssertionError('write mode produced read data')
                returned_data += 1
                response_queue.pop(0)

            yield
            yield port.cmd.ready.eq(cycle % 4 != 1)
            yield port.wdata.ready.eq(cycle % 5 not in (1, 2))
            if (yield bist.done.status):
                break
        else:
            raise AssertionError(f'BIST did not finish within 500 cycles: modules={modules}, mode={mode}')

        assert command_count == beat_limit, (modules, mode, command_count, beat_limit)
        assert (yield bist.beats.status) == beat_limit
        if read:
            assert returned_data == beat_limit
            assert data_count == 0
        else:
            assert accepted_data == beat_limit
            assert returned_data == 0
        if inject_lane_errors:
            actual_errors = (yield bist.errors.status)
            assert actual_errors == modules, (modules, actual_errors)
            expected_lane_bits = 0
            for lane in range(modules):
                assert (yield bist.lane_errors[lane].status) == 1
                expected_lane_bits |= (1 << (lane % 8)) << (8 * lane)
            assert (yield bist.lane_bits.status) == expected_lane_bits
        elif read:
            assert (yield bist.errors.status) == 0
            assert (yield bist.lane_bits.status) == 0

    run_simulation(top, process(), clocks={'sys': 10})


class BISTGeometryTests(unittest.TestCase):
    def test_write_xorshift_backpressure_8_and_9_lanes(self):
        for modules in (8, 9):
            with self.subTest(modules=modules):
                run_case(modules, mode=0)

    def test_write_address_pattern_backpressure_8_and_9_lanes(self):
        for modules in (8, 9):
            with self.subTest(modules=modules):
                run_case(modules, mode=2)

    def test_read_address_pattern_and_lane_error_fold_8_and_9_lanes(self):
        for modules in (8, 9):
            with self.subTest(modules=modules):
                run_case(modules, mode=3, inject_lane_errors=True)

    def test_read_xorshift_pattern_clean_8_and_9_lanes(self):
        for modules in (8, 9):
            with self.subTest(modules=modules):
                run_case(modules, mode=1)

    def test_rejects_unsupported_lane_geometries(self):
        for modules, width in ((7, 448), (10, 640), (8, 520), (9, 512)):
            port = LiteDRAMNativePort('both', ADDRESS_WIDTH, width)
            with self.subTest(modules=modules, width=width):
                with self.assertRaises(ValueError):
                    BIST(port, modules=modules)


if __name__ == '__main__':
    unittest.main()
