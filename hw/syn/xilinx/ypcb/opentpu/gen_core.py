#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

from migen import ClockDomainsRenamer, ClockSignal, ResetSignal, Signal, log2_int
from litex.build.xilinx import XilinxPlatform
from litex.soc.integration.builder import Builder
from litex.soc.integration.soc_core import SoCCore
from litex.soc.interconnect import wishbone
from litex.soc.interconnect.axi import AXIInterface
from litedram.common import LiteDRAMNativePort
from litedram.core.controller import ControllerSettings
from litedram.frontend.axi import LiteDRAMAXI2Native
from litedram.frontend.ecc import LiteDRAMNativePortECC
from litedram.gen import (LiteDRAMCoreControl, get_common_ios, get_dram_ios,
                          get_axi_user_port_ios, connect_axi_user_port)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gen_ddr import standalone
from selfcal import CalibrationCpu
from bist import BIST
from clocks import DQSPhase, MT41K256M8_tRFC160, WLCRG, WriteClocks
from dfii_q import registered_injector
from wl7ddrphy import WL7DDRPHY
from firmware import build as build_firmware


class Ch1Core(SoCCore):
    csr_map = {'ddrctrl': 0, 'ddrphy': 1, 'ecc_axi_0': 2, 'sdram': 3}

    def __init__(self, platform):
        frequency = 100e6
        platform.add_extension(get_common_ios())
        SoCCore.__init__(self, platform, frequency, cpu_type=None, with_uart=False,
                         with_timer=False, with_ctrl=False, integrated_rom_size=0,
                         integrated_sram_size=0, csr_data_width=32)
        self.crg = WLCRG(platform, frequency, clk50=platform.request('clk'), rst_reg=True)
        self.comb += self.crg.rst.eq(platform.request('rst'))
        configuration = {'memtype': 'DDR3', 'sdram_module': MT41K256M8_tRFC160,
                         'sdram_module_nb': 9, 'sdram_rank_nb': 1}
        platform.add_extension(get_dram_ios(configuration))

        self.ddrctrl = LiteDRAMCoreControl()
        self.ddrctrl.selfcal = CalibrationCpu(platform)
        self.bus.add_master(name='selfcal', master=self.ddrctrl.selfcal.bus)
        self.ddrctrl.write_clocks = clocks = WriteClocks(1, frequency)
        self.ddrctrl.phase = DQSPhase(clocks)
        self.ddrphy = phy = ClockDomainsRenamer(clocks.domains)(WL7DDRPHY(
            platform.request('ddram'), groups=[0] * 9, sys_clk_freq=frequency,
            iodelay_clk_freq=200e6, cl=6, cwl=5, rd_reg=False))
        phy.settings.add_electrical_settings(rtt_nom='60ohm', rtt_wr='60ohm', ron='34ohm')
        with registered_injector():
            self.add_sdram('sdram', phy=phy, module=MT41K256M8_tRFC160(frequency, '1:4'),
                           with_soc_interconnect=False,
                           controller_settings=ControllerSettings(cmd_buffer_depth=16))
        self.ddrctrl.bist = BIST(self.sdram.crossbar.get_port(), modules=9)
        self.comb += [platform.request('pll_locked').eq(self.crg.mmcm.locked & clocks.locked),
                      platform.request('init_done').eq(self.ddrctrl.init_done.storage),
                      platform.request('init_error').eq(self.ddrctrl.init_error.storage),
                      platform.request('user_clk').eq(ClockSignal('sys')),
                      platform.request('user_rst').eq(ResetSignal('sys'))]
        control = wishbone.Interface()
        self.bus.add_master(name='host', master=control)
        platform.add_extension(control.get_ios('wb_ctrl'))
        self.comb += control.connect_to_pads(platform.request('wb_ctrl'), mode='slave')

        raw = self.sdram.crossbar.get_port()
        assert raw.data_width == 576
        user = LiteDRAMNativePort('both', raw.address_width, 512)
        self.ecc_axi_0 = LiteDRAMNativePortECC(user, raw, with_error_injection=False)
        axi = AXIInterface(data_width=512, address_width=user.address_width + log2_int(64), id_width=8)
        self.axi_to_native = LiteDRAMAXI2Native(axi, user, with_read_modify_write=True)
        platform.add_extension(get_axi_user_port_ios('axi_0', axi.address_width, 512, 8))
        enabled = Signal()
        self.sync += enabled.eq(self.ddrctrl.init_done.storage & ~self.ddrctrl.init_error.storage)
        self.comb += connect_axi_user_port(axi, platform.request('user_port_axi_0'), enabled)
        self.phase_constraints = clocks.constraints(ns=1.3, hier=True) + phy.constraints()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CalibrationBuilder(Builder):
    def __init__(self, soc, output, compiler):
        super().__init__(soc, output_dir=str(output), compile_software=False, compile_gateware=False,
                         csr_json=str(output / 'csr.json'), csr_csv=str(output / 'csr.csv'))
        self.output = output
        self.compiler = compiler

    def _generate_csr_map(self):
        super()._generate_csr_map()
        build_firmware(self.soc, self.output, self.compiler)


def main():
    parser = argparse.ArgumentParser(description='Elaborate the OpenTPU-derived CH1 integration prototype')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cc', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Prototype export requires a fresh output directory')
    if importlib.metadata.version('pythondata-cpu-vexriscv') != '1.0.1.post407':
        raise ValueError('Unexpected calibration CPU RTL package version')
    platform = XilinxPlatform('xc7k480tffg1156-2', io=[], toolchain='vivado')
    soc = Ch1Core(platform)
    builder = CalibrationBuilder(soc, output, args.cc.resolve())
    builder.build(build_name='ypcb_ddr3')
    export = standalone(output / 'gateware/ypcb_ddr3.v', platform.sources)
    constraints = output / 'phase-constraints.tcl'
    constraints.write_text('\n'.join(soc.phase_constraints) + '\n')
    files = [Path(__file__), Path(__file__).with_name('wl7ddrphy.py'),
             Path(__file__).with_name('clocks.py'), Path(__file__).with_name('dfii_q.py'),
             Path(__file__).with_name('bist.py'),
             Path(__file__).with_name('firmware.py'),
             Path(__file__).with_name('provenance.json')]
    metadata = {'status': 'WL_CALIBRATION_CONTROLLER_EXPORTED_PHYSICAL_QUALIFICATION_PENDING',
                'eligible_for_synthesis': True, 'hardware_qualified': False, 'hardware_accessed': False,
                'board_abi': 4,
                'input_clock_hz': 50000000, 'controller_clock_hz': 100000000,
                'ddr_data_rate': 800000000, 'physical_lanes': 9, 'payload_bytes': 2147483648,
                'ecc': True, 'phase_uncertainty_ns': 1.3,
                'source_sha256': {str(p): digest(p) for p in files}, 'export': export}
    (output / 'prototype.json').write_text(json.dumps(metadata, indent=2) + '\n')
    export.update(cpu_rtl_package='pythondata-cpu-vexriscv==1.0.1.post407', board_abi=4,
                  controller='WL7DDRPHY', profile={k: v for k, v in metadata.items() if k != 'export'},
                  phase_constraints_sha256=digest(constraints))
    (output / 'selfcal-export.json').write_text(json.dumps(export, indent=2) + '\n')
    print('YPCB_WL_CH1_CONTROLLER_EXPORTED_PHYSICAL_QUALIFICATION_PENDING')


if __name__ == '__main__':
    main()
