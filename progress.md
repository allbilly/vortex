> Current goal, October 20: continue until GPU examples run on the FPGA.
> The OpenTPU exclusion watcher expired; the new user instruction resumes Vortex.
> v16 bitstream finalization passed in
> `build_ypcb_native32/ch1-jtag-pcie-20261020-v16-finalize/`, with 727 frozen inputs.
> The refined status-fanout review passed native positive and bypass-rejection checks.
> v13 is retired; the old checkpoint cannot be reused across this HDL change.
> Builds retain one worker and allocator arenas limited to two. Hardware use
> will acquire the shared exclusive JTAG lease before SRAM loading and runtime
> tests. The v16 image has now been programmed into SRAM and passed JTAG MMIO;
> DDR and GPU kernels are not yet tested. Local FPGA-side calibration is next.

Fresh ABI 3 synthesis/implementation is running in
`build_ypcb_native32/ch1-jtag-pcie-20261020-v17/`, freezing commit `6e96b4b9f`
and the tested `local-selfcal-ddr-20261020-v3` controller. Both Vivado worker
limits are one, with two allocator arenas. No checkpoint is reused. Native
ABI 3 startup/scrub and runtime builds passed. JTAG register-batch validation
passes 29 cases, including the actual Tcl parser with a hardware-API oracle;
PIO/host-memory RTL tests pass 2,730 byte-range cases and stall/error/timeout
checks. The full GPU/AFU PCIe/JTAG memory/demo/SGEMM simulation is running in
`build_ypcb_native32/native-shell-abi3-20261020-v1/`. None of these results is
physical DDR or GPU execution evidence.

## Local DDR calibration CPU — October 20

The new CH1 controller exports a 16 KiB RV32I calibration CPU and immutable
firmware without removing the external Wishbone control interface. Its CSRs
fit inside the existing `ddrctrl` group; all four original CSR blocks retain
their addresses. Firmware is 6,824 bytes plus 456 bytes BSS, with 9,104 bytes
remaining for stack. It has no unresolved external symbols. CPU RTL comes
from the pinned `pythondata-cpu-vexriscv==1.0.1.post407` package.

Native firmware checks pass 4,224 read-window cases, all nine lanes, 6,942
probes, ECC/readback, failure cleanup, timeout and open-row timing. Runtime
checks require ABI 3 and the exact generated firmware identity, read the local
result, and reject ABI 2, held/faulted CPUs, bad firmware, excessive row time,
disabled ECC, calibration failure and timeout. No host training fallback runs.

Actual VexRiscv RTL with BRAM and delayed Wishbone responses passed in
`build_ypcb_native32/selfcal-rtl-20261020-v1/`: 112,466,979 cycles, 424,243 MMIO
accesses, all 6,942 probes and nine lanes. Its longest conservative row span
was 801 cycles versus the 3,510-cycle limit at 100 MHz. BRAM upload/readback,
hold/drain/restart, bus faults and failed-lane cleanup also passed. This is
simulation evidence; physical CH1 training, memory/ECC and GPU workloads remain
open. A fresh synthesis is required; do not reuse the ABI 2 checkpoint.

## Physical ABI 2 JTAG probe — October 20

`build_ypcb_native32/fpga-probe-20261020-v1/manifest.json` records successful
SRAM programming, INIT=1, DONE=1, physical IDCODE `0x23751093`, stable signature
`0x56595043` and ABI 2. The exact image SHA-256 is
`3cab81128e26e4bb33d22e21296e19c9ed1245266f8d3d95cf6ca31822276269`.
Both CRC checkpoints, four checker vectors and 727 frozen input hashes passed.
The hardware server and bridge exited and the shared lease was released.
Permanent flash was not written; the new Vortex image remains in volatile SRAM.

The 32 physical MMIO samples were 12.65–27.37 ms, median 17.76 ms. Initial board
status was `2`: CH1 PLL locked, memory not initialized. Host-driven training
cannot meet the DDR row timing at this latency and was not attempted. This is
an initialization-transport limitation, not an observed GPU execution failure.
The next design uses a local calibration CPU, described in
[the proposal](docs/proposals/ypcb_local_ddr_calibration_proposal.md).

Latest October 20 result: v15 routing passed setup/hold at +0.068/+0.031 ns,
with 143,162 fully routed nets, no routing errors and zero unclocked or
unconstrained internal endpoints. Its old report verifier then stopped because
it counted 26 bus-skew constraints against the 14 design buses. Inspection found
the 14 expected design groups plus eight JTAG and four debug-hub IP constraints;
all have positive slack, worst +7.255 ns. The corrected verifier requires these
groups separately and cross-checks their detailed results. The exact routed
checkpoint was finalized as v16 and programmed for the JTAG-only probe above.

> OpenTPU hardware priority: Vortex Codex and its new synthesis build were stopped
> after c0182800 finished at 19:31 UTC on October 17 (03:31 HKT October 18).
> No hardware programming operation was interrupted; the idle login shell remains
> open. Stop evidence and preserved synthesis disposition are under
> `build_ypcb_vivado32/openTPU-return-20261018/completion-disposition.json`.
> No new GPU/DDR pass is implied by this handover. OpenTPU owns the next board task.

# OpenTPU hardware return requested — October 18, 2026

The user requires all Vortex work to stop when the combined-interface OpenTPU
c0182800 implementation finishes. Preserve Vortex results in this repository,
finish any atomic hardware programming safely and release the cable. A watcher
is active; its request, logs and receipt are under
[openTPU-return-20261018](build_ypcb_vivado32/openTPU-return-20261018/).
This is coordination of the existing temporary test, not permission for a new
permanent flash operation. The PCIe-only c0182301 target is retired.

# Native CH1/JTAG/PCIe build — routed signoff passed, bitstream finalization next

October 20 status-crossing audit: `shell/pcie/error_status` is registered on
`pcie_clk` but fed the board-clock startup read-data register directly. v13
was stopped, with exit -15 recorded and all outputs preserved. Its first
route had setup slack -1.888 ns; no bitstream or hardware operation resulted.
The repair adds two preserved synchronizer stages for each independent sticky
flag. Native constraints verify the source, both stages, direct connections,
absence of a bypass and distinct clocks before excluding only the first-stage
crossing. The shell test also checks that a real PCIe AXI error reaches board
status. Fresh synthesis and qualification are required for this HDL change.
The native checkpoint regression rejected the actual old netlist for missing
first-stage flops; `pcie-status-cdc-before-20261020-v1/` retains its timing
report and rejection receipt under `build_ypcb_native32`.
Fresh v14 freezes committed source `4d03888d4`; all 401 source HDL files and
both generated hardware headers match the passing repaired shell simulation.
Synthesis and implementation run sequentially with both Vivado worker limits
set to one. Routed qualification and physical execution remain pending.
Fresh v14 synthesis exited 0 after 1,414.6 seconds, with zero errors or critical
warnings. The design uses 79,304 LUTs, 66,118 registers and 151 BRAM tiles:
eight additional registers for the four two-stage PCIe status synchronizers.
Its checkpoint SHA-256 is
`fb975ddc2cf29d4222dec808bc49d3a3020cf9376bc8f7f604898df398c8b0cd`.
The actual synthesis exit receipt and utilization report are retained in the run.
v14 implementation stopped at an overstrict fanout check. Native inspection
showed each sticky flag feeding its own PCIe-clock register through a LUT and
its first board-clock synchronizer. The review now follows logic to capture
registers, permits source-clock feedback and rejects any unsynchronized receiving
clock. It uses the source register as the timing-exception launch object; Vivado
rejects a register's Q pin there. The native positive check passed for all four
chains and rejected an injected source-to-board-register bypass. Evidence is
`build_ypcb_native32/pcie-status-cdc-contract-20261020-v2/manifest.json`.
Only the constraint review changed; the verified v14 synthesis can be reused.
v15 accepted that reuse and is running implementation. The prepared
`build_ypcb_native32/resume-implementation.sh` now selects v14's checkpoint,
defaults to a fresh v16 directory and rejects an already-active Vortex build.
Its duplicate guard was verified without starting another CAD worker.
v15 passed the actual Gray/reset, four PCIe status-chain and mailbox payload
checks, then the post-optimization PCIe glitchless clock-mode review. Its
optimized checkpoint is written. Placement and post-placement optimization
completed; routing is running. Final routed timing,
integrity and hardware qualification are still open.
The first routed result had setup slack -0.051 ns and hold slack +0.031 ns.
The post-route loop subsequently closed timing at +0.068/+0.031 ns. The report
gate now requires ten AXI and four CSR Gray buses, eight JTAG IP constraints
and four debug-hub constraints, with complete matching detail sections.
Twenty report-gate/reuse/hardware-preflight regression cases passed. The
`finalize_vivado.py` tool verifies every frozen input and the current routed
reports, copies the exact checkpoint and frozen tools into a fresh directory,
then regenerates native reports before bitstream creation.

October 20 update: fresh v7 export was rejected because the generated CDC files
differed only in LiteX's two timestamp comments. The reuse runner now verifies
that exact comment-only difference, records both hashes, and retains the original
compiled source. Four regression cases pass, including rejection of logic,
attribute and unrelated-file changes. Fresh v8 verified all 674 HDL/pin inputs
and started implementation without repeating synthesis. Earlier stop/retry
records below remain preserved; the prior active exclusion is no longer running.

The requested OpenTPU design review found reusable mailbox topology/endpoint
checks and its 16 KiB VexRiscv DDR calibration CPU. The mailbox checks are adapted
to Vortex's own two-stage handshake and clocks. Native v10 validation passed:
14 Gray buses/42 first-stage bits; request payload 51 sources/54 receivers;
response payload 34 sources/36 receivers; both payload bounds are 8 ns. The
write discriminator is covered, and local response-valid flags retain ordinary
timing. The CH1 status bits 1/3/5 and direct synchronizer wiring were verified
against the actual synthesis checkpoint. Source hashes and findings are in
`build_ypcb_native32/opentpu-design-review-20261020.json`.

v8 stopped on a non-hierarchical regexp query; v9 stopped on an overly broad
response-register query. v10 then exposed the PCIe review stage mismatch: the
pre-optimization netlist still has a LUT1 inverter, while Vivado absorbs it into
BUFGCTRL polarity during `opt_design`. v11 was stopped to correct that ordering.
v12 passed the original strict mux-mode review after optimization, adding an
explicit zero-initialized selector check. Placement then rejected debug-hub
settings modified after optimization because the core needed regeneration.
v13 configures and connects the debug hub before optimization and saves an
optimized checkpoint before placement. No RTL or device clock was changed.
Final routed gates and physical tests remain pending.

Hardware-run preparation is now in `ci/ypcb_run_fpga.py` and
`hw/syn/xilinx/ypcb/program_sram.tcl`. It binds the exact routed image and input
hashes, checks CRC, holds the shared JTAG lease through the native programming/
bridge/workload session, and records each child exit status. The probe stage
measures JTAG before DDR training. The kernel stage requires the actual memory,
demo and SGEMM checks, positive GPU counters and enabled/clean CH1 ECC using
the controller-matched CSR metadata. Three rejection tests passed before any
hardware lease or native child was opened; Tcl syntax checks passed. Actual
programming, bridge operation and GPU examples remain untested.

The final ABI 2 native FPGA host build passed on October 20. The kernel library
was rebuilt from clean objects, and the dispatcher, YPCB backend, memory-map
test, `demo` and SGEMM use matching board flags and the 2 GiB memory map. Both
example kernels link at `0x40000000`. The runtime DDR metadata was matched by
SHA-256 to v13's exact compiled controller. Commands, exit codes and artifact
hashes are in `build_ypcb_native32/native-fpga-host-20261020-v3.json`; this is
build evidence, with no physical DDR or kernel execution yet.

After the status CDC repair, the ABI 2 native shell simulation passes memory-map transfers, `demo`
and SGEMM over both PCIe and JTAG, including stopped PCIe clock in JTAG mode.
Both interfaces retire 2,444 instructions in 6,234 GPU cycles for `demo` and
7,632 instructions in 18,442 cycles for SGEMM. CH0 sees no DDR traffic. The
model uses real AFU/GPU RTL with memory and PHY status oracles; it does not
qualify physical DDR. Logs and exits are in
`build_ypcb_native32/native-shell-abi2-20261020-v2/manifest.json`.

Before host-driven DDR training, measure actual JTAG MMIO transaction latency
against the 6,942-probe training workload. If it prevents bounded initialization,
adapt the reference FPGA-side calibration design to CH1's PHY and CSR map;
do not hide the bottleneck by extending timeouts without that measurement.
The counted software-oracle workload is 424,234 MMIO calls, requiring a mean
under 0.707 ms per call to fit the existing five-minute limit before wait
overheads. This is a budget, not a measured cable speed. The count receipt is
`build_ypcb_native32/ddr-mmio-budget-20261020-v1/manifest.json`.
The probe also keeps a row open across nine host MMIO calls. For the configured
MT41K256M8 reference, the maximum ACTIVATE-to-PRECHARGE budget is 70.2 us at or
below 85 C, so its mean call budget is 7.8 us before wait overheads. Check this
against physical JTAG measurements before training; the five-minute deadline
alone is insufficient. The reference-chip identity and cable speed remain
unverified. The source, calculation and software-oracle count are saved in
`build_ypcb_native32/ddr-row-budget-20261020-v1/manifest.json`.

The Vortex Podman container and its Ubuntu image were removed as requested.
Host source/toolchain folders and all other containers were verified preserved;
the deletion receipt is `build_ypcb_native32/podman-removal.json`.
The wrapper now runs natively with a uv environment. `master` remains at
upstream `7b67f0210`; the CH1/JTAG/PCIe design is committed on `ypcb` as `8509bc26a`.

The new design uses only CH1's 2 GiB, an independent 125 MHz board-derived GPU
clock, PCIe AXI-Lite clock crossing, and a JTAG AXI master. Its board register
ABI is version 2. Runtime capacity, stack/IO maps and kernel placement agree
on the 2 GiB address space. Kernels link at `0x40000000`.

Completed checks: 777 DMA cases, nine native uv/Python/build regressions,
CH1 bounds/arbitration checks, startup and asynchronous AXI-Lite tests.
The initial CH1 shell prototype passed memory transfers, demo and SGEMM
through PCIe and JTAG simulation, including JTAG with the PCIe clock stopped.
Those prototypes used board ABI 1; ABI 2 still needs the final native shell
rerun. No new image has been programmed or physically executed.

The v6 outputs are under `build_ypcb_native32/ch1-jtag-pcie-20261018-v6/`.
Both Vivado thread limits were one, with allocator arenas limited to two.
Synthesis exited 0 in 1,081 seconds, with zero critical warnings/errors and
about 5 GB reported peak physical memory. The checkpoint is `synth.dcp`;
utilization is 79,303 LUTs, 66,110 registers and 151 BRAM tiles. The synthesis
DRC report contains warnings only. Routing and the new bitstream are pending.

Implementation exited 1 at the status synchronizer coverage check: six registers
remain in the two-channel status vector, including three inactive CH0 bits.
The proposed constraint now selects CH1 bits 1, 3 and 5 explicitly; confirmation
against the synthesized netlist is pending. The runner now prepares reuse of a
successful synthesis only when HDL, pins, source order, defines and synthesis Tcl
match. Final timing paths are queried again after the last routing attempt.

The diagnostic in `build_ypcb_native32/constraint-probe-v1/` was terminated by
SIGTERM. The active watcher and its signal evidence are in
`build_ypcb_vivado32/openTPU-return-20261018/exclusion-v1/`; it enforces
all Vortex workers being stopped until `exclusion-release.json` exists with
`release_vortex_exclusion: true`. Do not restart native jobs against that watcher
while the project-priority question remains unresolved. Check the release and
actual watcher process, then validate the constraint selection and resume only
implementation in a fresh output directory.
The checkpoint reuse contract passed eight fixture checks: implementation-only
changes are accepted; HDL, pin, define, source-order and synthesis-Tcl changes,
corrupted frozen inputs, and failed synthesis are rejected. The 718 real v6
frozen inputs were independently hash-verified. Evidence is in
`build_ypcb_native32/reuse-contract-checks/manifest.json`.

The prepared resume command is
`./build_ypcb_native32/resume-implementation.sh`. It checks for the active
exclusion watcher before reconfiguration, keeps the one-worker/allocator limits,
and uses the completed v6 checkpoint with a fresh v7 output directory. Its
preflight was verified to exit 2 without starting implementation while the
watcher remains active. If v7 already exists at resume time, supply another
fresh output directory as its argument.

Earlier v1 failed before IP creation, and v2/v3 were stopped for the ABI change
and the lower-memory restart. The completed OpenTPU handover watcher stopped v4
with SIGTERM. v5 was stopped during IP synthesis to correct a project/non-project
command mismatch; v6 uses the documented non-project flow. All earlier logs/exit
receipts remain preserved.
The pinned Ramulator fmt 9 header raised a dangling-reference diagnostic with
native GCC 15 and 16. A hash-checked temporary dependency patch now keeps its
mapper alive; the actual `dram_sim.cpp` syntax check passes under GCC 16 with
the original warning flags. The uv environment includes CMake 3.31.10, and the
native smoke wrapper builds Ramulator in a separate native directory. Full
simulator rebuilds and workload checks remain queued after the FPGA build.

October 20 native dependency update: the complete Ramulator library now builds
and passes `ldd -r` under native GCC 16. The full compile found yaml-cpp 0.7's
missing `<cstdint>` include. `ci/patch_ramulator_deps.py` now applies both pinned
dependency fixes, with pristine-input, idempotence and unknown-input rejection
checks passed. The wrapper uses the renamed helper. The library build/link
receipt is `build_ypcb_native32/native-ramulator-20261020-v2/manifest.json`;
simulator workload execution remains separate from this dependency check.

The final ABI 2 DDR host test passed natively: 4,224 read-window cases plus
CH1 training, both data edges, nine lanes, ECC, handoff and negative/timeout
cases. Its log is `build_ypcb_native32/native-ddr-host-abi2.log`; the CSR/data
oracle does not establish physical DDR training.

The partial-write review confirmed that the pinned generator already enables
AXI read/modify/write when ECC is selected; the compiled controller RTL contains
that stage. A focused AXI512/ECC576 component simulation preserved unmasked
bytes with randomized channel stalls and a raw endpoint that writes full words.
Disabling RMW failed the guard comparison as expected. No adapter HDL fix was
needed. Evidence is `build_ypcb_native32/ecc-rmw-chain-20261020-v4/manifest.json`;
the simulator supplies unused read signals on write-only memory ports for its
pinned memory lowerer. This is component evidence, not a physical DDR test.

The native bitstream CRC checker passed its four known-answer vectors and the
previous image's two CRC checkpoints. Corrupted payload, corrupted CRC and
truncated-image controls were rejected with the expected diagnostics. Evidence:
`build_ypcb_native32/crc-tool-checks/manifest.json`. The new image still needs
its own integrity check after implementation.

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
