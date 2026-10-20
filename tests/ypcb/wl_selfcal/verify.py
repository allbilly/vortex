#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import ctypes
import json
from pathlib import Path
import random

from oracle import FakeCsr


def arithmetic(path):
    library = ctypes.CDLL(str(path))
    for name in ('__mulsi3', '__umodsi3'):
        function = getattr(library, name)
        function.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        function.restype = ctypes.c_uint32
    library.__modsi3.argtypes = [ctypes.c_int32, ctypes.c_int32]
    library.__modsi3.restype = ctypes.c_int32
    rng = random.Random(18)
    cases = [(a, b) for a in (0, 1, 2, 111, 112, 0x7fffffff, 0x80000000, 0xffffffff)
             for b in (0, 1, 2, 3, 112, 0x80000000, 0xffffffff)]
    cases += [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(100000)]
    for a, b in cases:
        assert library.__mulsi3(a, b) == (a * b) & 0xffffffff
        assert library.__umodsi3(a, b) == (a % b if b else a)
        signed_a, signed_b = ctypes.c_int32(a).value, ctypes.c_int32(b).value
        expected = abs(signed_a) % abs(signed_b) if signed_b else abs(signed_a)
        if signed_a < 0:
            expected = -expected
        assert library.__modsi3(signed_a, signed_b) == expected
    print(f'ARITHMETIC PASS: {len(cases)} boundary/random cases', flush=True)


class Firmware:
    def __init__(self, path, ddr, cpu=False):
        self.lib = ctypes.CDLL(str(path))
        self.lib.ypcb_wl_calibrate.restype = ctypes.c_uint32
        self.lib.selfcal_host_now.restype = ctypes.c_uint64
        self.regs = json.loads((ddr / 'csr.json').read_text())['csr_registers']
        self.words = {reg['addr'] + i * 4: (name, i, reg['size'])
                      for name, reg in self.regs.items() for i in range(reg['size'])}
        self.ddr = ddr
        self.expected_id = json.loads((ddr / 'selfcal_fw/manifest.json').read_text())['firmware_id'] if cpu else 0
        if cpu:
            self.lib.sim_firmware.argtypes = [ctypes.c_char_p]
            self.lib.sim_firmware(str(ddr / 'selfcal_fw/firmware.bin').encode())

    def run(self, board, reject_ecc=False):
        mailbox, own, pending, errors, trace = [0] * 128, {}, {}, [], []

        def normalize(name):
            if name.startswith('ddrctrl_write_clocks_'):
                return name.replace('ddrctrl_write_clocks_', 'wclk_', 1)
            if name.startswith('ddrctrl_phase_'):
                return name.removeprefix('ddrctrl_')
            if name.startswith('ddrctrl_bist_'):
                return name.removeprefix('ddrctrl_')
            return name

        def read(address):
            try:
                name, word, width = self.words[address]
                value = own.get(name, 0) if name.startswith(('ddrctrl_selfcal_', 'ddrctrl_init_', 'ecc_')) \
                    else board.r(normalize(name))
                return (value >> ((width - 1 - word) * 32)) & 0xffffffff
            except BaseException as error:
                errors.append(error)
                return 0

        def write(address, value):
            try:
                name, word, width = self.words[address]
                combined = pending.get(name, 0) if word else 0
                combined = (combined << 32) | value
                pending[name] = combined
                if word != width - 1:
                    return
                trace.append((name, combined))
                if name == 'ddrctrl_init_done' and value:
                    assert own.get('ecc_axi_0_enable') == 1 and board.r('sdram_dfii_control') == 1
                if name == 'ddrctrl_selfcal_state' and value & 128 and value & 3 == 2:
                    assert own.get('ddrctrl_init_done') == 1 and own.get('ecc_axi_0_enable') == 1
                if name.startswith(('ddrctrl_selfcal_', 'ddrctrl_init_', 'ecc_')):
                    if not (reject_ecc and name == 'ecc_axi_0_enable' and value == 1):
                        own[name] = combined
                else:
                    board.w(normalize(name), combined)
            except BaseException as error:
                errors.append(error)

        def mbox(index, value):
            try:
                assert index < 128, 'Firmware escaped its actual 128-word mailbox'
                mailbox[index] = value
            except BaseException as error:
                errors.append(error)

        rd_type = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32)
        wr_type = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32)
        rd, wr, mb = rd_type(read), wr_type(write), wr_type(mbox)
        self.lib.selfcal_host_setup(rd, wr, mb)
        state = self.lib.ypcb_wl_calibrate()
        if errors:
            raise errors[0]
        assert state == mailbox[2] == own['ddrctrl_selfcal_state']
        assert mailbox[0] == 0x53435231
        assert mailbox[1] == self.expected_id
        return mailbox, own, trace


def calibration(library, ddr, cpu=False, cases=None, save=None):
    firmware = Firmware(library, ddr, cpu)
    for case in cases or ('normal', 'per_bit', 'framing_span', 'no_phase', 'clock_error', 'ecc_readback'):
        board = FakeCsr(ddr, groups=[0] * 9, ps_moves_ck=True)
        if case == 'per_bit':
            board.BOFF = {(2, 0): 2, (8, 0): -2, (8, 3): -2, (8, 5): 2}
        elif case == 'framing_span':
            board.RB[8] = 0
            board.BOFF = {(8, 0): -2}
        elif case == 'no_phase':
            board.WLO[8], board.WHI[8] = 200, 210
        elif case == 'clock_error':
            board.drp[0x10] = board.drp[0x0e]
        mailbox, own, trace = firmware.run(board, case == 'ecc_readback')
        if save:
            save.mkdir(parents=True, exist_ok=True)
            (save / (case + '.json')).write_text(json.dumps(mailbox) + '\n')
        if case in ('normal', 'per_bit'):
            assert mailbox[2] == 130 and mailbox[16] & 0xffff == 2, (case, mailbox[2], mailbox[16])
            assert own['ddrctrl_init_done'] == 1 and own['ddrctrl_init_error'] == 0
            assert all(board.good(lane) for lane in range(9))
            assert mailbox[18] & 0xffff > 0
            for lane in range(9):
                value = mailbox[23 + lane]
                assert value & 255 >= 3 and (value >> 8) & 255 == board.RB[lane]
                for bit in range(8):
                    shift = (8 * lane + bit) * 2
                    offset = (mailbox[32 + shift // 32] >> (shift % 32)) & 3
                    assert offset == (board.BOFF.get((lane, bit), 0) // 2) & 3
        else:
            expected = {'framing_span': 5, 'no_phase': 5, 'clock_error': 4, 'ecc_readback': 8}[case]
            assert mailbox[2] == 128 | (expected << 8) | 3
            assert own['ddrctrl_init_done'] == 0 and own['ddrctrl_init_error'] == 1
            assert board.r('sdram_dfii_control') == 4
        print(f'CALIBRATION PASS: {case}, {len(trace)} CSR writes, state {mailbox[2]}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--arithmetic', type=Path, required=True)
    parser.add_argument('--ddr', type=Path, required=True)
    parser.add_argument('--cpu', action='store_true')
    parser.add_argument('--save', type=Path)
    parser.add_argument('--case', action='append', choices=('normal', 'per_bit', 'framing_span', 'no_phase', 'clock_error', 'ecc_readback'))
    args = parser.parse_args()
    arithmetic(args.arithmetic)
    calibration(args.library, args.ddr, args.cpu, args.case, args.save)
