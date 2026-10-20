# Clock/PHY helpers from OpenTPU tools/litedram/ld_test.py.
# See provenance.json and LICENSE.litedram in this directory.
from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from litex.gen import LiteXModule
from litex.soc.cores.clock import S7MMCM, S7PLL, S7IDELAYCTRL
from litex.soc.interconnect.csr import CSR, CSRStorage, CSRStatus
from litedram.modules import MT41K256M8, _SpeedgradeTimings

class MT41K256M8_tRFC160(MT41K256M8):
    """The board's 2 Gb parts with tRFC 160 ns (LiteDRAM's MT41K256M8 table: 128 nCK)."""
    speedgrade_timings = {"default": _SpeedgradeTimings(tRP=13.75, tRCD=13.75, tWR=15,
                                                        tRFC=(None, 160), tFAW=(None, 40),
                                                        tRAS=35)}

class WLCRG(LiteXModule):
    """The clocks of the write-leveled image (--phy wl): clk50 -> MMCM: sys (the SoC, the
    controllers, BISTs and PHYs' logic; each channel's WriteClocks MMCM is cascaded from it); a
    PLL: the 200 MHz IDELAYCTRL reference. clk50 as CRG's. rst_reg: sys's reset through a plain
    register after its synchronizer (whose ASYNC_REG flip-flop Vivado does not replicate), with
    max_fanout, a cycle later: the production core's sys reset reaches both channels' ends of the
    die (3,794 loads, 6.8 ns of route in the 812bb01 build). max_fanout 64 (256 until g2fix
    0885d436, whose worst sys path, +0.009 ns, was a replica into a bankmachine's level register
    across the die: 0 levels, 97% route): more replicas, each placed nearer its loads."""
    def __init__(self, platform, f, clk50=None, rst_reg=False):
        self.rst = Signal()
        self.cd_sys = ClockDomain()
        self.cd_idelay = ClockDomain()
        if clk50 is None:
            clk50_pad = platform.request("clk50")
            clk50 = Signal()
            self.specials += Instance("BUFG", i_I=clk50_pad, o_O=clk50)
        self.mmcm = mmcm = S7MMCM(speedgrade=-2, fractional=False)
        mmcm.register_clkin(clk50, 50e6)
        mmcm.create_clkout(self.cd_sys, f, with_reset=not rst_reg)
        if rst_reg:
            self.cd_sys_ars = ClockDomain()
            rst = Signal(reset=1, reset_less=True)
            rst.attr.add(("max_fanout", 64))
            self.comb += [self.cd_sys_ars.clk.eq(self.cd_sys.clk), self.cd_sys.rst.eq(rst)]
            self.specials += AsyncResetSynchronizer(self.cd_sys_ars, ~mmcm.locked)
            self.sync.sys_ars += rst.eq(ResetSignal("sys_ars"))
        self.comb += mmcm.reset.eq(self.rst)
        platform.add_false_path_constraints(self.cd_sys.clk, mmcm.clkin)
        self.pll = pll = S7PLL(speedgrade=-2)
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk50, 50e6)
        pll.create_clkout(self.cd_idelay, 200e6)
        self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)

class DQSPhase(LiteXModule):
    """The write DQS clock's phase: each write of dqs_shift moves it one fine step (1/56 of the
    VCO period: 16.7 ps at 1066.67 MHz) later (bit0 = 1) or earlier (0), once the MMCM has done
    the previous one (dqs_busy). dqs_steps: the steps since configuration (signed)."""
    def __init__(self, mmcm):
        self.dqs_shift = CSRStorage(1, description="Write: one step; 1 = later, 0 = earlier.")
        self.dqs_busy = CSRStatus(1)
        self.dqs_steps = CSRStatus(32)
        busy = Signal()
        steps = Signal((32, True))
        self.sync += [
            mmcm.psen.eq(0),
            If(self.dqs_shift.re & ~busy,
                mmcm.psen.eq(1), mmcm.psincdec.eq(self.dqs_shift.storage[0]), busy.eq(1),
                If(self.dqs_shift.storage[0], steps.eq(steps + 1)).Else(steps.eq(steps - 1)),
            ).Elif(mmcm.psdone, busy.eq(0)),
        ]
        if hasattr(mmcm, "ps_ready"):   # an MMCM with a reset of its own (WriteClocks) starts
            self.sync += If(~mmcm.ps_ready, busy.eq(0), steps.eq(0))   # from its static phases
        self.comb += [self.dqs_busy.status.eq(busy), self.dqs_steps.status.eq(steps)]

class WriteClocks(LiteXModule):
    """One DDR3 channel's PHY clocks (tools/litedram/wl7ddrphy.py, docs/litedram.md section 8)
    from one MMCM, cascaded from sys at DIVCLK_DIVIDE 1 with its feedback through a BUFG: its
    outputs keep a fixed phase to sys (the PHY's logic and the controller run in sys). Fine phase
    shift, moved together by the host (DQSPhase): CLKOUT0 sysc (f) and CLKOUT1 sys4xc (4f), the
    CLKDIV / CLK of CK, the commands and the read capture. Static: CLKOUT2 sysw (f, CLKDIV of the
    write OSERDES, sys's phase), CLKOUT3 / 4 group 0's DQ and DQS (4f at 0 and 90 deg), CLKOUT5 / 6
    group 1's (4f at group1_deg and group1_deg + 90). (An MMCM's fine-phase outputs must share
    their sub-VCO phase fraction: DQ and DQS 90 deg apart cannot both shift, so CK does.) Group
    1's offset can be reprogrammed through the DRP (drp_*, mmcm_reset: the host holds the MMCM in
    reset for the write, 1/8 VCO period = 22.5 deg per step), the PHY's clocks stopping
    meanwhile. `domains` maps the PHY's clock names to this channel's."""
    OUTS = ("sys_ck", "sys4x_ck", "sys_w", "sys4x_w0", "sys4x_w0_dqs", "sys4x_w1", "sys4x_w1_dqs")
    SHIFTED = ("sys_ck", "sys4x_ck")

    def __init__(self, c, f, group1_deg=0.0):
        n = {"sys_ck": f"sysc{c}", "sys4x_ck": f"sys4xc{c}", "sys_w": f"sysw{c}",
             "sys4x_w0": f"sys4xw{c}a", "sys4x_w0_dqs": f"sys4xw{c}a_dqs",
             "sys4x_w1": f"sys4xw{c}b", "sys4x_w1_dqs": f"sys4xw{c}b_dqs"}
        self.domains = n
        cd = {k: ClockDomain(v, reset_less=True) for k, v in n.items()}   # clock pins only
        for k, d in cd.items():
            setattr(self, "cd_" + d.name, d)
        self.mmcm_reset = CSRStorage(1, description="1: this channel's MMCM held in reset.")
        self.mmcm_locked = CSRStatus(1)
        self.drp_adr = CSRStorage(7, reset_less=True)
        self.drp_dat_w = CSRStorage(16, reset_less=True)
        self.drp_dat_r = CSRStatus(16)
        self.drp_read = CSR()
        self.drp_write = CSR()
        self.drp_drdy = CSRStatus(1)
        self.locked = Signal()
        self.ps_ready = Signal()
        self.psen, self.psincdec, self.psdone = Signal(), Signal(), Signal()
        self.group1_deg, self.f, self.name_of = group1_deg, f, f"ldmmcm{c}"

        den, dwe, drdy, do = Signal(), Signal(), Signal(), Signal(16)
        self.sync += [
            den.eq(self.drp_read.re | self.drp_write.re),
            dwe.eq(self.drp_write.re),
            If(self.drp_read.re | self.drp_write.re, self.drp_drdy.status.eq(0))
            .Elif(drdy, self.drp_drdy.status.eq(1), self.drp_dat_r.status.eq(do)),
        ]
        rst = Signal()
        self.comb += [rst.eq(ResetSignal("sys") | self.mmcm_reset.storage),
                      self.mmcm_locked.status.eq(self.locked),
                      self.ps_ready.eq(self.locked & ~self.mmcm_reset.storage)]
        fb, fb_buf = Signal(), Signal()
        outs = [Signal() for _ in self.OUTS]
        phase = {"sys4x_w0_dqs": 90.0, "sys4x_w1": group1_deg, "sys4x_w1_dqs": group1_deg + 90.0}
        div = {"sys_ck": 8, "sys_w": 8}
        p = {}
        for i, k in enumerate(self.OUTS):
            d = div.get(k, 2)
            p[f"p_CLKOUT{i}_DIVIDE" + ("_F" if i == 0 else "")] = float(d) if i == 0 else d
            p[f"p_CLKOUT{i}_PHASE"] = phase.get(k, 0.0)
            p[f"p_CLKOUT{i}_DUTY_CYCLE"] = 0.5
            p[f"p_CLKOUT{i}_USE_FINE_PS"] = "TRUE" if k in self.SHIFTED else "FALSE"
            p[f"o_CLKOUT{i}"] = outs[i]
        self.specials += Instance("MMCME2_ADV", name=f"ldmmcm{c}",
            p_BANDWIDTH="OPTIMIZED", p_COMPENSATION="ZHOLD", p_STARTUP_WAIT="FALSE",
            p_CLKIN1_PERIOD=1e9 / f, p_REF_JITTER1=0.01, p_DIVCLK_DIVIDE=1,
            p_CLKFBOUT_MULT_F=8.0, p_CLKFBOUT_PHASE=0.0, p_CLKFBOUT_USE_FINE_PS="FALSE",
            i_CLKIN1=ClockSignal("sys"), i_CLKIN2=0, i_CLKINSEL=1,
            i_CLKFBIN=fb_buf, o_CLKFBOUT=fb, i_RST=rst, i_PWRDWN=0, o_LOCKED=self.locked,
            i_PSCLK=ClockSignal("sys"), i_PSEN=self.psen, i_PSINCDEC=self.psincdec,
            o_PSDONE=self.psdone,
            i_DCLK=ClockSignal("sys"), i_DEN=den, i_DWE=dwe, i_DADDR=self.drp_adr.storage,
            i_DI=self.drp_dat_w.storage, o_DO=do, o_DRDY=drdy, **p)
        self.specials += Instance("BUFG", i_I=fb, o_O=fb_buf)
        for k, o in zip(self.OUTS, outs):
            self.specials += Instance("BUFG", i_I=o, o_O=cd[k].clk)

    def constraints(self, ns=1.0, hier=False):
        """Pre-placement Tcl / XDC: commands and read data cross between sys (falling edge) and
        sysc, which the host keeps within half a tCK (0.94 ns) of sys (ddrcal.DqsPhase's wrap):
        `ns` of uncertainty both ways, setup and hold. sys is the MMCM's CLKIN1 clock. hier: the
        MMCM found anywhere in the hierarchy (the production core inside the board top)."""
        pin = (lambda p: f"[get_pins -hierarchical -filter {{NAME =~ */{self.name_of}/{p}}}]") \
            if hier else (lambda p: f"[get_pins {self.name_of}/{p}]")
        sys_, ck = (f"[get_clocks -of_objects {pin(p)}]" for p in ("CLKIN1", "CLKOUT0"))
        return [f"set_clock_uncertainty -{k} {ns:.3f} -from {a} -to {b}"
                for a, b in ((sys_, ck), (ck, sys_)) for k in ("setup", "hold")]
