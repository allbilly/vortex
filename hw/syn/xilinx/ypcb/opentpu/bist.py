# Native-port traffic checker from OpenTPU tools/litedram/ld_test.py.
# See provenance.json and LICENSE.litedram in this directory.
from migen import *
from litex.gen import LiteXModule
from litex.soc.interconnect.csr import CSRStorage, CSRStatus

class BIST(LiteXModule):
    """Memtest and bandwidth on a native port of any width (LiteDRAM's BIST wants a power-of-two
    width; this port is 576 bits). The host sets base / length (beats), mode and seed and pulses
    start; the engine issues `length` commands to consecutive beats, back to back, and counts the
    cycles from start to the last data (ticks). Write: the data of beat i is the generator's word
    i. Read: every returned beat is compared with the same word (reads return in order), and per
    module (byte lane) the beats with a wrong bit are counted and the wrong bits OR'ed.
    Data (mode bit 1): 0 = a 64-bit xorshift stream from the seed, one step per beat, spread over
    the 72-bit groups rotated per group (every lane sees random data); 1 = the beat address and its
    complement XOR the seed in every group (finds aliased address bits)."""
    def __init__(self, port, modules=9):
        dw, aw = len(port.wdata.data), len(port.cmd.addr)
        ngroups = dw // (8 * modules)                 # 72-bit groups (DQ beats): 8
        self.start = CSRStorage(1, description="Write 1: start (mode / base / length as set).")
        self.mode = CSRStorage(2, description="bit0: 1 = read and check, 0 = write; bit1: data.")
        self.base = CSRStorage(aw)
        self.length = CSRStorage(aw + 1)
        self.seed = CSRStorage(64, reset=0x0123456789ABCDEF)
        self.done = CSRStatus(1)
        self.ticks = CSRStatus(32)
        self.beats = CSRStatus(aw + 1, description="Data beats seen (written or read).")
        self.errors = CSRStatus(32, description="Read beats with any wrong bit.")
        self.lane_errors = [CSRStatus(32, name=f"lane{m}_errors") for m in range(modules)]
        self.lane_bits = CSRStatus(8 * modules, description="Wrong bits seen, OR'ed per lane (bit 8m+b).")
        for m, c in enumerate(self.lane_errors):
            setattr(self, f"lane{m}_errors", c)

        read = self.mode.storage[0]
        addrmode = self.mode.storage[1]
        running, ncmd, ndat, ticks = Signal(), Signal(aw + 1), Signal(aw + 1), Signal(32)
        cmd_addr = Signal(aw)
        # data generator, stepped per data beat
        st = Signal(64)
        def xorshift(x):
            a = x ^ (x << 13)[:64]
            b = a ^ (a >> 7)
            return b ^ (b << 17)[:64]
        dat_addr = Signal(aw)
        exp = Signal(dw)
        groups = []
        for g in range(ngroups):
            gw = 8 * modules
            rot = (st << (7 * g % 64)) | (st >> (64 - 7 * g % 64)) if g else st
            rnd = Cat(rot[:64], rot[:gw - 64] ^ rot[64 - (gw - 64):64])
            pat = Cat(dat_addr, ~dat_addr, dat_addr)[:gw] ^ Cat(self.seed.storage, self.seed.storage)[:gw]
            groups.append(Mux(addrmode, pat, rnd))
        self.comb += exp.eq(Cat(*groups))
        wd_hs = port.wdata.valid & port.wdata.ready
        rd_hs = port.rdata.valid & port.rdata.ready
        step = Mux(read, rd_hs, wd_hs)
        self.comb += [
            port.cmd.valid.eq(running & (ncmd != self.length.storage)),
            port.cmd.we.eq(~read),
            port.cmd.addr.eq(cmd_addr),
            port.wdata.valid.eq(running & ~read & (ndat != ncmd)),
            port.wdata.we.eq(2**len(port.wdata.we) - 1),
            port.wdata.data.eq(exp),
            port.rdata.ready.eq(1),
            self.done.status.eq(~running),
            self.ticks.status.eq(ticks),
            self.beats.status.eq(ndat),
        ]
        start = Signal()
        self.comb += start.eq(self.start.re & self.start.storage[0])
        lane_err = Signal(modules)
        lane_bits = Signal(8 * modules)
        for m in range(modules):
            bits = Cat(*[(port.rdata.data ^ exp)[g * 8 * modules + 8 * m: g * 8 * modules + 8 * m + 8]
                         for g in range(ngroups)])
            self.comb += lane_err[m].eq(bits != 0)
            self.comb += lane_bits[8 * m:8 * m + 8].eq(
                reduce_or8(bits, ngroups))
        self.sync += [
            If(start,
                running.eq(1), ncmd.eq(0), ndat.eq(0), ticks.eq(0),
                cmd_addr.eq(self.base.storage), dat_addr.eq(self.base.storage),
                st.eq(self.seed.storage),
                self.errors.status.eq(0), self.lane_bits.status.eq(0),
                *[c.status.eq(0) for c in self.lane_errors],
            ).Elif(running,
                ticks.eq(ticks + 1),
                If(port.cmd.valid & port.cmd.ready, ncmd.eq(ncmd + 1), cmd_addr.eq(cmd_addr + 1)),
                If(step,
                    ndat.eq(ndat + 1), dat_addr.eq(dat_addr + 1), st.eq(xorshift(st)),
                    If(ndat + 1 == self.length.storage, running.eq(0)),
                ),
                If(rd_hs & read,
                    If(lane_err != 0, self.errors.status.eq(self.errors.status + 1)),
                    self.lane_bits.status.eq(self.lane_bits.status | lane_bits),
                    *[If(lane_err[m], c.status.eq(c.status + 1)) for m, c in enumerate(self.lane_errors)],
                ),
            ),
        ]

def reduce_or8(bits, n):
    """OR of n consecutive bytes of `bits`."""
    r = bits[0:8]
    for i in range(1, n):
        r = r | bits[8 * i:8 * i + 8]
    return r
