# YPCB branch integration — October 18, 2026

`master` matches upstream `7b67f0210`. The `ypcb` branch starts at that commit
and retains the board, runtime, DMA, Vivado and rebuild-tracking changes.
Upstream replaces the local declaration-order patches. Standalone nextpnr
routing/assembly tooling and optional XDMA patches were archived separately;
existing build artifacts and hardware receipts remain in their original directories.

Fresh checks on the integrated tree: 777 CP DMA cases and four build-stamp
regressions passed. Software/configuration and simulator boundaries pass.
A complete updated AFU simulation and new bitstream have not yet been qualified.

The requested next image has both JTAG and PCIe control/memory interfaces and
uses only CH1's 2 GiB DDR3. CH0 remains inactive. JTAG must operate without a
PCIe reference clock or link. The previous image below predates these changes.

---

# Temporary hardware check — October 18, 2026

**SRAM configuration and JTAG status check passed.** The user requested this
bounded sibling-project test while the priority OpenTPU implementation runs,
and confirmed that the card is connected only to local JTAG.

| Check | Result |
| --- | --- |
| SRAM bitstream load | PASS |
| JTAG INIT / DONE / IDCODE | PASS: `1 / 1 / 0x23751093` |
| GPU kernel execution | NOT TESTED: no PCIe runtime connection |
| DDR training and memory workload | NOT TESTED |
| Normal runtime qualification | OPEN: existing CDC/external-timing/electrical review remains |

The earlier phrase "limited pass" described this test scope. It did not report
an observed GPU execution failure; no GPU workload was run.

The exact existing Vortex bitstream
`487df66a6dc00caf73b39d3f5d8473212bb80e549685afc4da66278a88d9fd90`
was loaded into volatile FPGA SRAM. Fresh INIT=1, DONE=1 and raw physical
IDCODE `0x23751093` were verified. All package checksums and 278 frozen source/
finalization input hashes passed; 234 DDR package-pin assignments matched the
YPCB reference. The two DDR reset output standard differences and the scoped
review are recorded, without changing normal-runtime qualification.

This is **not a GPU, PCIe or DDR-memory test**. The local host has no FPGA PCIe
endpoint or Chestnut, and this image exposes no JTAG runtime interface. No
kernel ran and no DDR training was requested. The existing normal-runtime
CDC/external-timing/electrical review remains open. The restricted SRAM
configuration observation did not approve those operating modes.

Permanent flash was not written. This check left Vortex in SRAM; the OpenTPU
permanent image was preserved. This is the state at test completion; later
configuration changes are recorded in the [OpenTPU handoff](../openTPU/HANDOFF.md). The programmer and its hardware server have exited, with
JTAG released for the priority OpenTPU image. Do not leave a Vortex workload
running when OpenTPU is ready.

All results: [hardware-check-20261018](build_ypcb_vivado32/hardware-check-20261018/),
including `sram-probe.json`, `restricted-sram-review.json`, package/source/pin
checks, cable boot/overlay/detection logs, `program.log` and the fresh native
status receipt. Earlier offline preparation follows unchanged.

---

# Vortex YPCB Vivado bitstream preparation

Last verified: 2026-10-13 19:16:23 UTC.

**Offline bitstream preparation is complete.** The full RV32 Vortex board design for YPCB-00338-1P1 / `xc7k480tffg1156-2` was synthesized, placed, routed and converted to a bitstream with full Vivado 2026.1. Core clock remains 125 MHz; the DDR user clocks retain their configured rates. No RAM cap or CPU quota was used for the final build.

Image: [vortex_ypcb.bit](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/vortex_ypcb.bit), 18,735,205 bytes.

SHA-256: `487df66a6dc00caf73b39d3f5d8473212bb80e549685afc4da66278a88d9fd90`.

| Preparation gate | Result |
|---|---|
| Full synthesis | PASS; actual exit 0, zero critical warnings |
| Internal routed setup | PASS; WNS +0.006 ns, TNS 0, no failing endpoints |
| Internal routed hold | PASS; WHS +0.040 ns, no failing endpoints |
| Pulse width | PASS; no violations |
| Routing | PASS; 170,599/170,599 routable nets, zero routing errors |
| Gray crossings | PASS; all 28 bus skew constraints, worst slack +7.261 ns |
| Internal timing coverage | PASS; zero unclocked registers and unconstrained internal endpoints |
| Routed / bitgen DRC | Zero errors; 107 routed warnings retained for review |
| Final checkpoint | PASS; PCIe mux mode and 125 MHz core clock revalidated; internal timing still passes |
| Bitstream generation | PASS; actual final Vivado exit 0 |
| Packet/header/target/CRC integrity | PASS; both CRC checkpoints match; qualified checker negative controls retained |
| Source and flow integrity | PASS; 273 synthesis inputs and five finalization inputs unchanged; source archive verified |
| DDR external timing | OPEN; 144 DDR inputs / 214 outputs lack external delay budgets; two async reset inputs explicitly excluded |
| Card electrical profile | UNCONFIRMED; CFGBVS=GND and CONFIG_VOLTAGE=1.8 are assumptions |
| Physical operation | Not verified; no card or flash programming occurred |

The image is an offline candidate. It does not establish electrical readiness, DDR board timing or hardware execution. CDC reports retain seven raw-reset findings, 26 combined-reset findings and 907 FIFO LUTRAM collision warnings; these were not waived. DDR read training has not run on this physical card. Those items remain part of physical qualification before loading.

The preparation fixes preserve the chosen architecture and clock rates. Vivado export now retains AXI/Wishbone synchronizer metadata, and the four existing CDC tests pass. The FPU `USE_DSP` parameter collision was removed; both DSP modes pass 39,340 FMA comparisons each. Equivalent normalizer guard/carry logic passes FP32/FP64 formal proofs and 152,530 applied-source SoftFloat comparisons, with unchanged pipeline cycles. The PCIe clock selection exception is limited to the exact BUFGCTRL S0/S1 pins after validating constant enables, inactive IGNORE inputs, complementary selection and both input periods. The PHY rate-change handshake permits variable switching latency; unsafe-mode qualification fails with the expected diagnostic, and real data timing failures remain visible.

Package: [README](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/README.md), [verification receipt](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/preparation.json), [checksums](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/SHA256SUMS), [frozen build inputs](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/frozen-build-inputs.tar.gz), [timing](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/reports/timing-summary.rpt), [CDC](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/reports/cdc-routed.rpt), [DRC](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/reports/drc-routed.rpt), and [final checkpoint audit](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/reports/final-checkpoint-audit.log).

Producer: [final implementation log](build_ypcb_vivado32/vivado-preparation-20261014/impl-v4b/implementation.log), [routed checkpoint](build_ypcb_vivado32/vivado-preparation-20261014/impl-v4b/routed.dcp), [actual exit](build_ypcb_vivado32/vivado-preparation-20261014/impl-v4b/command.exit). Earlier runs and unresolved investigations are preserved in [the prior handoff](build_ypcb_vivado32/vivado-preparation-20261014/progress-before-completion.md).
