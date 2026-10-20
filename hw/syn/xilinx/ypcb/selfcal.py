# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.
# Adapted from OpenTPU's tools/litedram/calcpu.py.

from migen import *
from litex.gen import LiteXModule
from litex.soc.cores.cpu.vexriscv import VexRiscv
from litex.soc.interconnect import wishbone
from litex.soc.interconnect.csr import CSRField, CSRStatus, CSRStorage

MEM_BYTES = 16384
MBOX_WORDS = 128
MAGIC = 0x5CA1


class CalibrationCpu(LiteXModule):
    autocsr_exclude = {'mem'}

    def __init__(self, platform, firmware=None):
        self.hold = CSRStorage(1, description='Hold the calibration CPU after its current bus access.')
        self.status = CSRStatus(fields=[
            CSRField('held', size=1),
            CSRField('mem_log2', size=4),
            CSRField('bus_error', size=1),
            CSRField('reserved', size=10),
            CSRField('magic', size=16, reset=MAGIC),
        ])
        self.state = CSRStorage(32, description='Calibration firmware state.')
        self.mbox_adr = CSRStorage(7)
        self.mbox_dat = CSRStatus(32, description='Calibration result mailbox word.')
        self.mem_adr = CSRStorage(12)
        self.mem_dat = CSRStorage(32, description='Firmware memory write while held.')
        self.mem_rdat = CSRStatus(32, description='Firmware memory read while held.')
        self.bus = bus = wishbone.Interface(data_width=32, address_width=32, addressing='word')
        self.cpu = cpu = VexRiscv(platform, variant='minimal')
        cpu.set_reset_address(0)
        ibus, dbus = cpu.ibus, cpu.dbus
        words = MEM_BYTES // 4
        aw = log2_int(words)
        self.mem = mem = Memory(32, words, init=list(firmware) if firmware is not None else None,
                                name='selfcal_mem')
        ip = mem.get_port()
        # READ_FIRST keeps the byte-writable data port consistent with native BRAM inference.
        dp = mem.get_port(write_capable=True, we_granularity=8, mode=READ_FIRST)
        mailbox = Memory(32, MBOX_WORDS, name='selfcal_mbox')
        mw = mailbox.get_port(write_capable=True)
        mr = mailbox.get_port()
        self.specials += mem, ip, dp, mailbox, mw, mr

        fetch_address, fetch_valid = Signal(aw), Signal()
        instruction_range = ibus.adr[aw:] == 0
        hit = fetch_valid & (fetch_address == ibus.adr[:aw])
        self.comb += [
            ibus.ack.eq(ibus.cyc & ibus.stb & instruction_range & hit),
            ibus.err.eq(ibus.cyc & ibus.stb & ~instruction_range),
            ip.adr.eq(Mux(ibus.cyc & ibus.stb & hit, ibus.adr[:aw] + 1, ibus.adr[:aw])),
            ibus.dat_r.eq(ip.dat_r),
        ]
        self.sync += [fetch_address.eq(ip.adr), fetch_valid.eq(1)]

        region = dbus.adr[26:30]
        request = dbus.cyc & dbus.stb
        to_memory = (region == 0) & (dbus.adr[aw:] == 0)
        to_local = (region == 2) & (dbus.adr[10:26] == 0)
        to_soc = (region == 15) & (dbus.adr[11:26] == 0)
        local_address = dbus.adr[:10]
        to_mailbox = to_local & (local_address[7:10] == 0)
        to_timer = to_local & (local_address[1:10] == 0x100)
        local_valid = to_memory | to_mailbox | to_timer
        local_ack, local_data = Signal(), Signal(32)
        held, started, gap, bus_error = Signal(), Signal(), Signal(), Signal()
        self.sync += local_ack.eq(request & ~to_soc & local_valid & ~local_ack)
        self.comb += [
            If(held,
                dp.adr.eq(self.mem_adr.storage), dp.dat_w.eq(self.mem_dat.storage),
                [dp.we[byte].eq(self.mem_dat.re) for byte in range(4)],
            ).Else(
                dp.adr.eq(dbus.adr[:aw]), dp.dat_w.eq(dbus.dat_w),
                [dp.we[byte].eq(request & dbus.we & dbus.sel[byte] & to_memory) for byte in range(4)],
            ),
            self.mem_rdat.status.eq(dp.dat_r),
            mw.adr.eq(local_address[:7]), mw.dat_w.eq(dbus.dat_w),
            mw.we.eq(request & dbus.we & to_mailbox),
            mr.adr.eq(self.mbox_adr.storage), self.mbox_dat.status.eq(mr.dat_r),
            self.status.fields.mem_log2.eq(aw), self.status.fields.bus_error.eq(bus_error),
        ]
        cycles, high = Signal(64), Signal(32)
        self.sync += [
            cycles.eq(cycles + 1), local_data.eq(0),
            If(request & ~dbus.we & to_timer & ~local_ack,
                If(local_address[0], local_data.eq(high)).Else(
                    local_data.eq(cycles[:32]), high.eq(cycles[32:]))),
            If(held, bus_error.eq(0)).Elif(ibus.err | dbus.err, bus_error.eq(1)),
        ]
        open_access = (~self.hold.storage | started) & ~gap
        self.comb += [
            bus.adr.eq(dbus.adr[:26]), bus.dat_w.eq(dbus.dat_w), bus.sel.eq(dbus.sel),
            bus.we.eq(dbus.we), bus.cti.eq(0), bus.bte.eq(0),
            bus.cyc.eq(dbus.cyc & to_soc & open_access),
            bus.stb.eq(dbus.stb & to_soc & open_access),
            dbus.dat_r.eq(Mux(to_soc, bus.dat_r, Mux(to_memory, dp.dat_r, local_data))),
            dbus.ack.eq(request & Mux(to_soc, bus.ack, local_ack)),
            dbus.err.eq(request & Mux(to_soc, bus.err, ~local_valid)),
            held.eq(self.hold.storage & ~started), cpu.reset.eq(held),
            self.status.fields.held.eq(held),
        ]
        self.sync += [
            If(bus.ack | bus.err, started.eq(0)).Elif(bus.cyc & bus.stb, started.eq(1)),
            gap.eq(bus.ack | bus.err),
        ]

    def set_firmware(self, firmware):
        if len(firmware) != self.mem.depth:
            raise ValueError('Calibration firmware must fill its exact BRAM image')
        self.mem.init = list(firmware)
