# PHY response oracle adapted from OpenTPU opentpu/host/ddrcal.py.
# Licensed under the Apache License, Version 2.0.
import csv
from pathlib import Path
import random


def csr_map(path):
    with path.open() as stream:
        return {row[1]: (int(row[2], 16), int(row[3])) for row in csv.reader(stream)
                if row and row[0] == 'csr_register'}


class FakeCsr:
    """A PHY model for `selftest`: lane m reads back right only at its read bitslip RB[m], taps
    in [LO[m], HI[m]], and its write bitslip WB[m] (+-0 tCK), when the DQS phase step is within
    its write range. With `groups` (a WL7DDRPHY channel), a group 1 lane's step is the DQS
    step plus group 1's offset (7 steps per 1/8 VCO in the modelled DRP registers). BOFF[m, i]:
    DQ bit i of lane m reads right at RB[m] + BOFF instead (its ISERDES framed a CLK off); its
    read bitslip is its own when the CSR map has ddrphy_dly_sel_bits."""
    def __init__(self, build, nm=9, seed=1, groups=None, ps_moves_ck=False):
        self.regs = csr_map(Path(build) / "csr.csv")
        rnd = random.Random(seed)
        self.nm = nm
        self.RB = [rnd.randrange(8) for _ in range(nm)]
        self.WB = [rnd.choice((0, 2, 4)) for _ in range(nm)]
        self.LO = [rnd.randrange(0, 18) for _ in range(nm)]
        self.HI = [lo + rnd.randrange(4, 12) for lo in self.LO]
        self.WLO = [rnd.randrange(10, 30) for _ in range(nm)]
        self.WHI = [lo + rnd.randrange(40, 70) for lo in self.WLO]
        self.v = {}
        self.sel, self.wb, self.rd = 0, [0] * nm, [0] * nm
        self.rbb = [[0] * 8 for _ in range(nm)]     # read bitslip per DQ bit
        self.BOFF = {}
        self.wr = {}
        self.steps = 0
        self.groups = groups or [0] * nm
        self.ck = ps_moves_ck               # the phase shift moves CK, not DQ / DQS
        # write clock MMCM registers as configured: CLKOUT3 / 5 at 0, CLKOUT4 / 6 at 90 deg
        self.drp = {0x0E: 0x0041, 0x0F: 0, 0x10: 0x8041, 0x11: 0,
                    0x06: 0x0041, 0x07: 0, 0x12: 0x8041, 0x13: 0}

    def step_of(self, m):
        if not self.groups[m]:
            return self.steps
        ph = lambda a1, a2: (self.drp[a2] & 0x3F) * 8 + (self.drp[a1] >> 13)
        off = 7 * (ph(0x06, 0x07) - ph(0x0E, 0x0F))
        return self.steps - off if self.ck else self.steps + off

    @property
    def rb(self):
        return [r[0] for r in self.rbb]

    def bit_ok(self, m, i):
        return (self.rbb[m][i] == (self.RB[m] + self.BOFF.get((m, i), 0)) % 8
                and self.LO[m] <= self.rd[m] <= self.HI[m] and self.wb[m] == self.WB[m]
                and self.WLO[m] <= self.step_of(m) % 112 <= self.WHI[m])

    def w(self, name, v):
        self.v[name] = v
        lanes = [m for m in range(self.nm) if self.sel >> m & 1]
        bits = [i for i in range(8) if self.v.get("ddrphy_dly_sel_bits", 0xFF) >> i & 1]
        whole = len(bits) == 8
        if name == "ddrphy_dly_sel":
            self.sel = v
        elif name == "ddrphy_rdly_dq_rst":
            for m in lanes: self.rd[m] = 0
        elif name == "ddrphy_rdly_dq_inc":
            for m in lanes: self.rd[m] = (self.rd[m] + 1) % 32
        elif name == "ddrphy_rdly_dq_bitslip_rst":
            for m in lanes:
                for i in bits: self.rbb[m][i] = 0
        elif name == "ddrphy_rdly_dq_bitslip":
            for m in lanes:
                for i in bits: self.rbb[m][i] = (self.rbb[m][i] + 1) % 8
        elif name == "ddrphy_wdly_dq_bitslip_rst" and whole:
            for m in lanes: self.wb[m] = 0
        elif name == "ddrphy_wdly_dq_bitslip" and whole:
            for m in lanes: self.wb[m] = (self.wb[m] + 1) % 8
        elif name == "phase_dqs_shift":
            self.steps += 1 if v else -1
        elif name == "wclk_mmcm_reset":
            if not v:
                self.steps = 0              # the fine phase restarts from the static phases
        elif name == "wclk_drp_write":
            self.drp[self.v["wclk_drp_adr"]] = self.v["wclk_drp_dat_w"]
        elif name == "wclk_drp_read":
            self.v["wclk_drp_dat_r"] = self.drp.get(self.v["wclk_drp_adr"], 0)
        elif name.endswith("_command_issue") and self.v.get(name[:-6]) and name.startswith("sdram_dfii_pi"):
            c = self.v[name[:-6]]
            if c & 16:
                self.wr = {p: self.v.get(f"sdram_dfii_pi{p}_wrdata", 0) for p in range(4)}
            if c & 32:
                for p in range(4):
                    x = self.wr.get(p, 0)
                    for m in range(self.nm):
                        for i in range(8):
                            if not self.bit_ok(m, i):
                                x ^= (1 << (8 * m + i)) | (1 << (72 + 8 * m + i))
                    self.v[f"sdram_dfii_pi{p}_rddata"] = x

    def good(self, m):
        return all(self.bit_ok(m, i) for i in range(8))

    def r(self, name):
        if name == "phase_dqs_steps":
            return self.steps & 0xFFFFFFFF
        if name in ("phase_dqs_busy", "ctrl_bus_errors"):
            return 0
        if name in ("wclk_drp_drdy", "wclk_mmcm_locked"):
            return 1
        n = self.v.get("bist_length", 0)
        bad = [0 if self.good(m) else n for m in range(self.nm)] if self.v.get("bist_mode", 0) & 1 \
            else [0] * self.nm
        if name == "bist_done":
            return 1
        if name in ("bist_beats", "bist_ticks"):
            return n
        if name == "bist_errors":
            return max(bad)
        if name.startswith("bist_lane") and name.endswith("_errors"):
            return bad[int(name[len("bist_lane"):-len("_errors")])]
        if name == "xadc_temperature":
            return round((45 + 273.15) * 4096 / 503.975)
        if name == "i2c_in":
            return 0x1F                 # every line released (high): no device answers
        return self.v.get(name, 0)
