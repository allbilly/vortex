# Current Vortex status — October 21, 2026

**The FP16/INT8 image passed its offline implementation and integrity checks.**
The bitstream is `build_ypcb_tcu32/tcu-ch1-jtag-pcie-20261021-v3/vortex_ypcb.bit`.
Its SHA-256 is
`3b9decedf8af64836870c6b7f688b7e09dfd66983313470b0ad8cdf39516b2a0`.
It retains the full GPU, both JTAG/PCIe interfaces, CH1-only 2 GiB DDR3 with
all nine byte lanes and enabled ECC, and the 125 MHz GPU target.

Implementation exited zero, uninterrupted, in 5,635.700 seconds
(1 h 33 min 56 s), reusing the verified DMA-fixed synthesis checkpoint.
All seven internal report gates passed: setup +0.055 ns, hold +0.018 ns,
zero failing setup/hold/pulse endpoints, 251,833 fully routed nets, zero
routing errors, 14 design Gray buses and 12 vendor skew constraints.
Internal clock coverage is complete. The first route's -0.055 ns setup miss
was repaired by one post-route physical optimization in 275 seconds.
Both bitstream CRC checkpoints and four known-answer vectors passed.
All 814 frozen inputs and the synthesis/model provenance checks passed.

The runtime, memory/scalar tests and basic examples are prepared and bound to
the frozen controller, CSR and firmware metadata. Vendor bitstream-header
`SW_HDR_SHA256` is a different field from the DDR runtime C++ header digest;
the actual runtime binding checks use the controller/CSR/firmware hashes.
The exact baseline, limitations and artifact hashes are saved in
`build_ypcb_tcu32/offline-baseline-20261021-v3/manifest.json` and the image's
`SHA256SUMS`. FPGA programming, tensor kernels on physical hardware, physical
PCIe and a full-capacity DDR soak remain untested for this image. External
DDR I/O timing is not fully qualified by the internal report gates.

**OpenTPU retains JTAG priority; offline Vortex work is authorized.** No JTAG
access occurred. The current authorization is in
`build_ypcb_tcu32/offline-build-authorization-20261021-v1.json`.

The separate `ypcb_blackwell_like` profile is configured in
`build_ypcb_blackwell32/`. It inherits the board baseline, uses eight threads
and eight warps, and selects TF32, FP8, MXFP8/MXBF8, MXFP4/NVFP4, structured
sparsity, WGMMA, DXA, integer atomics/CAS and L2 alongside FP16/BF16 and INT8.
The full-profile frontend and 700,000 arithmetic cases passed. Eleven dense
and scaled formats passed square and rectangular SimX/XRT tests: 44 cases,
72 verified launches. The DXA address-width fix passed 480 before/after cases
at 31, 32 and 48 bits with identical address, delta and setup-cycle traces.
Evidence: `build_ypcb_blackwell32/native-validation-20261021-v3/manifest.json`
and `dxa-width-validation-20261021-v3/manifest.json`.

The new `examples/blackwell_like/` contains 21 reference-checked studies.
All 21 originally passed SimX; 19 passed XRT before local-memory LR/SC
stalled. The exact owned service was stopped for diagnosis; its old RUNNING
fields do not indicate a live process. A seven-event holder budget could not
protect a reservation across this profile's 64 harts. The budget now scales
with resident concurrency; SimX models the same bounded per-bank policy.
A focused regression passed 6,605 events at 16/64/128 harts with exact RTL/SimX
trace agreement. The original 64-hart XRT local-memory test now passes at both
one and eight iterations; one iteration took 1.59 seconds versus the prior
60-second diagnostic timeout. The DXA public Makefile all/run paths also pass.

The full eight-iteration XRT atomic suite now passes all 17 cases, including
both global/local-memory CAS ladders: 165.78 seconds. The second failure was
a simulation watchdog false positive: greedy issue let one warp wait while
other warps completed CAS operations and cache fences. The monitor now resets
on actual issue progress. Its regression reproduces the old false alarm,
accepts 128 progressing ALU operations during another warp's wait, and still
triggers when all issue progress stops. This monitor change is simulation-only;
the datapath and numerical checks are unchanged. The fixed 64-hart LR/SC
case also passes separately in 1.60 seconds. No stall limit was increased.
Receipts: `build_ypcb_blackwell32/lrsc-investigation-20261021-v3/manifest.json`,
`build_ypcb_bw_parity32/scoreboard-progress-20261021-v1/manifest.json` and
`scoreboard-before-20261021-v1/manifest.json`.

The application fingerprint now includes device linker flags; switching
`STARTUP_ADDR` relinks the kernel without cleaning. Both 0x40010000 and
0x40000000 ELF entry points were verified; the latter was restored. The
new one-hart parity test also exposed intentionally unused upper bits of the
fixed 64-bit AMO output on a 32-bit cache lane; that adapter now explicitly
marks just those discarded bits.
All three public unit compile/run targets pass. Local-memory model parity has
exactly 14,388 retired instructions on both drivers and a 0.62% cycle gap,
within the existing 5% threshold. All 21 fresh study cases now pass both SimX
and XRT, including the complete 17-test atomic suite. An independent audit
verified the exact profile/app flags, arguments, positive GPU counters and
all 84 binary hashes across those 42 study cases. Evidence:
`build_ypcb_blackwell32/study-validation-20261021-v2/manifest.json` and
`build_ypcb_blackwell32/study-audit-20261021-v2.json`.
These are functional study results; the parity claim above covers its named
local-memory test, not every contended atomic workload's timing.

The full board model compiled successfully. Its modeled PCIe interface has
passed the CH1 2 GiB memory-map/DMA test, scalar demo and SGEMM, and FP16 and
INT8 tensor tests with two verified launches each. The remaining format,
copy and atomic cases and the modeled JTAG interface continue under
`vortex-blackwell-combined-validation-20261021-v3.service`:
`build_ypcb_blackwell32/combined-validation-20261021-v3/manifest.json`.
Board-model receipt: `build_ypcb_blackwell32/board-validation-20261021-v2/manifest.json`.
DDR/PHY responses in that model are oracles; these tests do not access JTAG
or qualify the physical DRAM interface.

Fresh synthesis and implementation are queued under
`vortex-blackwell-vivado-queued-20261021-v1.service`. The queue waits for every
native and modeled-board check to pass before starting CAD; failed checks
prevent CAD from starting. Its receipt is
`build_ypcb_blackwell32/vivado-queue-20261021-v1/manifest.json`; the future
build receipt is `build_ypcb_blackwell32/vivado-build-20261021-v1/manifest.json`
and output is `build_ypcb_blackwell32/blackwell-ch1-jtag-pcie-20261021-v1/`.
The driver freezes committed sources, uses fresh synthesis, checks all seven
report gates and frozen inputs, and verifies bitstream CRCs. It never opens
JTAG. Both Vivado worker limits remain one, with an 8 GiB service memory cap.
See [the compute-study proposal](docs/proposals/ypcb_blackwell_like_proposal.md).
Both Vivado worker limits remain one, with an 8 GiB service memory cap.

The latest `git fetch origin master` found no upstream advancement:
`master` and `origin/master` are `7b67f0210c95`; `ypcb` descends from it.
No rebase was needed. Historical interrupted runs and their receipts remain
preserved below and in their original directories.

## Earlier build history

# Current Vortex status — October 21, 2026

**The separate FP16 and INT8 tensor image is in progress.** The `ypcb_tcu`
profile selects one eight-thread core, a five-stage TFR tensor unit with DSP
inference, FP16-to-FP32 and INT8-to-INT32 arithmetic. CH1-only 2 GiB ECC and
both JTAG/PCIe interfaces are retained. The scalar image below is preserved.

Native TFR arithmetic passed FP16, signed INT8 and unsigned INT8 checks using
the canonical references from `hw/unittest/Makefile`. The initial invocation
used the generic floating-point reference and stopped on a two-ULP difference;
the corrected TFR command uses `USE_FEDP` and `--W=25`, with unchanged tolerance.
Both requested formats passed SimX square and rectangular matrix tests, with
two launches per case. INT8 uses K=32 to satisfy its tensor tile geometry.
Both formats also passed XRT square and rectangular tests, with two launches
per case: eight matrix cases and sixteen verified launches across SimX/XRT.
The native job completed successfully under `vortex-tcu-native-20261021-v5.service`.
Evidence: `build_ypcb_tcu32/native-validation-20261021-v5/manifest.json` and
`tensor-log-checks.json` in that directory. No tensor FPGA pass is claimed.

All 72 profile/runner checks passed. Profile regeneration now follows inherited
profile contents, preserves unchanged header timestamps and rejects invalid
profiles; the pytest freshness guard uses the configured profile too. The
TFR Boolean parameter is renamed `DSP_ENABLE` to avoid Vivado's `use_dsp`
property collision. The YPCB export and shell model now include the tensor
package and sources and retain the selected profile. The verified export has
31 tensor source entries, including `VX_tcu_pkg.sv`. The initial board-model
attempt stopped at elaboration because the YPCB paths omitted the generated
`VX_CFG_TCU_TYPE_TFR` selector. Both the export and shell model now forward it;
`frontend-sources-20261021-v3/` selects the TFR implementation and contains no
missing-implementation sentinel in the preprocessed tensor core.

Build directory: `build_ypcb_tcu32/`; proposal:
[FP16 and INT8 tensor kernels](docs/proposals/ypcb_tcu_proposal.md).
The freshly rebuilt board-level model passed memory, demo, scalar SGEMM and
both tensor formats through modeled PCIe and JTAG after the DMA RTL change.
Each tensor matrix case verified two launches. The compiled model contains the
new DMA reference registers. Evidence:
`build_ypcb_tcu32/integration-build-20261021-v4/manifest.json`, field
`board_integration_status=FP16_INT8_SCALAR_MEMORY_PCIE_AND_JTAG_RTL_PASS`.
DDR/PHY responses in these board tests remain oracles.

The first tensor synthesis passed in 1,274.334 seconds, with actual exit zero and no
critical warnings/errors. The checkpoint SHA-256 is
`4c72ed096933710c2cf1206026ab676e238d16bfbd3901b4916dd949cf8cc902`.
Synthesis estimates 149,205 LUTs (49.97%), 194 block-RAM tiles (20.31%) and
144 DSPs (7.50%); these are not final routed figures. Observation:
`build_ypcb_tcu32/synthesis-observation-20261021-v1.json`.

The first implementation exited 1, uninterrupted, after 15,992.366 seconds
(4 h 26 min 32 s). Its directory is
`build_ypcb_tcu32/tcu-ch1-jtag-pcie-20261021-v1/`. Setup missed by 0.129 ns on
one endpoint; hold was +0.016 ns. All six other report gates passed, including
251,140 fully routed nets, zero routing errors, complete internal clock/timing
coverage, 14 design Gray buses and 12 vendor skew constraints. All 811 frozen
inputs matched. No bitstream was generated and no tensor image was programmed.
Evidence: `timing-failure-analysis-20261021-v1.json` in the tensor build, the
original `implement-exit.json`, timing reports and `routed.dcp`. The routed
checkpoint SHA-256 is
`92661dfff1dd55fdc507fa3552db7af9709a19e579139973f07ebf97201b0bb2`.

The failing path is entirely in DMA read-back validation: `dst_offset` through
buffer indexing/alignment and a wide comparison into the DMA state register.
It has 27 logic levels and 8.036 ns of data-path delay. The RTL now captures
the final accepted host write data and byte strobes before read-back validation.
No state or AXI handshake cycle is added. Both original and modified RTL
passed 787 DMA cases, including nine posted-write cases with 234 stale
read-backs. Every transfer's completion cycles and request counts matched:
37,624 cycles and 4,385 requests total. Evidence:
`dma-timing-validation-20261021-v2/manifest.json` and `cycle-comparison.json`.
The first unit attempt stopped on a missing TCU trace-package dependency;
the DMA unit file list now supplies it under the TCU profile.

Fresh synthesis is required after the DMA RTL change; the prepared
synthesis-reuse retry is superseded. Integration attempt v3 was stopped before
CAD: missing `rg` in the service PATH silently emptied the RTL dependency list,
and inspection showed that its existing model lacked the new DMA registers.
Those model results are invalidated in `integration-build-20261021-v3/model-invalidation.json`.
Discovery now uses standard `find` and rejects errors or empty lists. Three
regression cases failed before that change and passed afterward; receipts are
in `model-dependency-validation-20261021-v1/`. The v4 integration runner
rebuilds both interfaces and checks for the new DMA registers in the compiled
model before numerical testing. Its receipts are in
`integration-build-20261021-v4/`. Those tests passed. Fresh synthesis then
exited zero, uninterrupted, in 1,167.989 seconds (19 min 28 s), with no errors
or critical warnings. The new checkpoint SHA-256 is
`50dd9a220c396f6a78711b4597411664d65038f88c1bd96fdd38d7a85c4babb7`.
Synthesis estimates 149,180 LUTs (49.96%), 105,839 registers (17.72%),
194 block-RAM tiles (20.31%) and 144 DSPs (7.50%). These are synthesis
figures; routed timing is still unqualified. Evidence:
`build_ypcb_tcu32/synthesis-observation-20261021-v2.json`.
Implementation was interrupted at 07:58 HKT on October 21 by an explicit
OpenTPU priority switch. The service
`vortex-tcu-integration-build-20261021-v4.service` is stopped and its CAD
processes are gone. The last logged phase was physical-synthesis
initialization during post-placement optimization. No implementation exit
receipt or new bitstream exists; no Vortex design failure is inferred.
Preserve `tcu-ch1-jtag-pcie-20261021-v2/` and its successful synthesis
checkpoint. The scheduling hold is recorded in the build-local
`OPENTPU_PRIORITY_NOTICE.md` and
`opentpu-priority-return-c0184809-20261021/manifest.json`; its release or an
explicit priority decision is required before restarting.
All 811 frozen inputs matched at synthesis completion; its preprocessed
DMA RTL contains the validated data/strobe reference and both tensor formats
remain selected. Require all report/CRC gates and physical memory/ECC,
scalar and FP16/INT8 tests. The unchanged DDR block still needs qualification
in the newly routed tensor image.
Prepared build-local launchers are `run-hardware-preparation-20261021-v2.py`
(requires successful producer and reports), `run-fpga-tensor-kernels-20261021-v2.sh`
and `audit-fpga-completion-20261021-v2.py`. Capture the hardware service's owned
process identities during the physical run for the cleanup audit.
These syntax-checked, unexecuted launchers are bound to the new v2 image.
The hardware runner reports `FPGA_TENSOR_KERNEL_SUITE_RUNNING` until both
formats finish. All 71 runner checks passed after regenerating the build tree.
The source flow now checkpoints initial routing and each post-route optimization
pass, preserving the optimizer's routed result instead of rerunning the full
router after every pass. This follows
[AMD UG904](https://docs.amd.com/r/en-US/ug904-vivado-implementation/Physical-Optimization).
Tcl syntax and all four synthesis-reuse checks passed. The failed run preserves
its original frozen script. The revised flow has not yet been exercised in Vivado.
Vortex uses one heavy stage at a time and an 8 GiB service limit. It has
not acquired JTAG for this tensor work, and permanent flash remains untouched.

## Qualified scalar image

**Vortex GPU kernels now run and pass on the physical FPGA.** The OpenTPU-derived
WL/ABI4 image passed CH1 DDR memory, GPU demo, SGEMM and all five basic-operation
Python scripts: 13 basic numerical checks covering 472 output values. The run
finished at 00:07:29 HKT under `vortex-wl-fpga-kernels-20261020-v2.service`.
All eight memory/application stages retained enabled ECC with zero corrected
or uncorrectable errors. Scalar image qualification is complete for the local
JTAG connection.

| Check | Latest physical result |
| --- | --- |
| SRAM/JTAG | INIT=1, DONE=1, IDCODE `0x23751093`; scalar and queued PIO checks passed |
| CH1 calibration | All nine byte lanes, including ECC lane 8, passed; firmware `a77fc8fe`, CK phase -44, common window 81 steps |
| DDR memory | Four distinct 8 KiB regions, including upper-address regions, passed upload/download/copy, alias and 2 GiB bounds checks; this is not a full-capacity soak |
| GPU demo, `-n64` | Numerical PASS; 2,444 retired instructions, 9,133 cycles; ECC enabled, zero corrected/uncorrectable errors |
| SGEMM, `-n16` | Numerical PASS; 7,632 retired instructions, 18,925 cycles; ECC enabled, zero corrected/uncorrectable errors |
| Basic vector addition | PASS: all 37 outputs exact; ECC enabled and clean |
| Seven elementwise operators | PASS: add/subtract/multiply/divide/minimum/maximum/ReLU, 37 outputs each; division max absolute error `5.11e-08`, others exact; ECC enabled and clean |
| Basic GEMM | PASS: `5×3 @ 3×7`, all 35 outputs exact; ECC enabled and clean |
| Convolution | PASS: padded two-channel input, `3×5×7` output, all 105 values exact; ECC enabled and clean |
| Pooling | PASS: maximum, average and minimum, 12 outputs each, all exact; ECC enabled and clean |
| Physical PCIe runtime | Not tested on this JTAG-only host; both interfaces are present and passed the GPU/AFU RTL model |

Evidence: [hardware manifest](build_ypcb_wl32/fpga-kernels-20261020-v2/manifest.json),
[demo log](build_ypcb_wl32/fpga-kernels-20261020-v2/demo.log) and
[SGEMM log](build_ypcb_wl32/fpga-kernels-20261020-v2/sgemm.log).
Terminal status: `FPGA_MEMORY_DEMO_SGEMM_AND_BASIC_EXAMPLES_PASS`; all ten command
steps exited zero. The independent [completion audit](build_ypcb_wl32/completion-audit-20261020-v1.json)
passed 47 checks covering all 783 frozen image inputs, 20 host artifacts, seven
kernel image layouts, runtime/controller binding, numerical output, ECC and
hardware cleanup. Its [script](build_ypcb_wl32/audit-fpga-completion-20261020-v1.py)
only inspects artifacts, process state and leases; it does not access JTAG.

Image: `build_ypcb_wl32/wl-ch1-jtag-pcie-20261020-v3/vortex_ypcb.bit`, SHA-256
`7590d5487b793402feaeb73e0e5988e0867133436d6c58624230e97b837060bd`.
Implementation exited zero in 5,234.554 seconds. Routed setup/hold slack is
+0.034/+0.027 ns. The owned hardware servers and bridge exited; both JTAG
leases were confirmed available and ports 3122/3124 had no listeners. The GPU
test is finished and JTAG is released. The image remains in volatile FPGA
SRAM; permanent flash has not been written. The test service peaked at 939.9 MiB
and took 38 minutes 10.608 seconds, including programming and JTAG transfers.

Both DDR implementations use LiteDRAM and the same CH1 DDR800 profile. The
earlier Vortex A7 PHY used fixed CK phase and byte-wide read training; adding
write-alignment search alone still failed ECC lane 8. The new integration
adopts OpenTPU's adjustable CK/command clocks, static DQ/DQS clocks, per-bit
read alignment, registered command injection and traffic-tested phase sweep.
This is the better-supported training approach for this board. No comparative
bandwidth benchmark has been run. The pass qualifies the integrated approach;
it does not isolate one change as the sole cause of the earlier failure.

The observations below preserve earlier stages and failures. The table above
is the current status.

## Earlier October 20 diagnostics

JTAG access was explicitly reauthorized by the user: “jag lock is release and
can be used for vortex”. Temporary SRAM and runtime tests may continue; permanent
flash is outside this authorization. The earlier per-bit diagnostic finished
and released its processes and leases. The write-alignment diagnostic also
finished; its owned processes exited and both leases were observed free.

**GPU examples have not run on the FPGA.** The per-bit physical test loaded the
qualified ABI 3 v18 image, verified INIT=1/DONE=1 and IDCODE `0x23751093`, and
passed eight queued 64-byte JTAG PIO-window write/read pairs. It held the local
calibration CPU, uploaded and read-verified all 4,096 firmware BRAM words, then
ran diagnostic firmware `78dc1fa8`. CH1 data lanes 0–7 trained, but ECC lane 8 had
no individual-bit read eyes: valid bits `0x00`, error OR/AND `0xff`, zero passing
taps across all 256 read settings. Calibration stopped after 6,936 probes;
maximum open-row span was 687 controller cycles. This does not identify a GPU
failure or qualify DDR traffic. No GPU kernel or permanent flash write occurred.
Evidence: `build_ypcb_native32/ddr-bit-diagnostics-20261020-v1/manifest.json`.

The result does not support a read-framing-only explanation for lane 8. Write-side alignment was also tested and did not fix lane 8, as recorded below. OpenTPU's proven design searches write alignment as well as clock
phase and individual-bit read framing. Its working TinyStories record is
`~/openTPU/build/hardware/tinystories-c0182600-20261018-v1/manifest.json`
(28,909,056 verified bytes and exact tokens); that qualification belongs to
OpenTPU and does not transfer to Vortex. The copied controller under
`hw/syn/xilinx/ypcb/opentpu/` now includes the full calibration firmware and passes standalone tests;
board integration and physical qualification remain incomplete. ECC remains enabled on CH1's nine physical
lanes; using CH1 alone does not remove its ECC byte lane.

## Write alignment candidate

The calibration firmware now searches write bitslips 0, 2, 4 and 6 for each
lane and selects the setting with the widest read window. A complete successful
run has 27,678 probes, with all nine lanes still required. The native host tests
passed 4,224 window cases, write alignment choices on lanes 0/8, 40 per-bit
failure cases, timeout, row timing, restart and runtime rejection checks. The
Python firmware/producer checks passed all 47 cases. Actual RV32I CPU simulation
passed: 450,028,903 cycles, 1,691,053 MMIO operations, 27,678 probes and an
801-cycle maximum open-row span. Restart, stalls, bus faults and lane8 failure
diagnostics passed too. The physical overlay test finished under
`vortex-ddr-write-diagnostics-20261020-v1.service`. All 4,096 words were uploaded
and verified, but ECC lane 8 had no byte-wide eye at any of the four write
alignments. Calibration failed after 27,672 probes and 433,354,686 cycles, with
a 687-cycle maximum open-row span. Lanes 0–7 selected write slip zero. Lane8
per-bit diagnostics at write zero remained all invalid. Results:
`build_ypcb_native32/ddr-write-diagnostics-20261020-v1/manifest.json`.
Write alignment alone does not repair the existing A7 PHY integration.

Candidate export: `build_ypcb_native32/local-selfcal-ddr-20261020-v5-write-alignment/`.
Firmware ID `0c0c441c`, 8,648 bytes, SHA-256
`fc50db3478c8709b102ccb178e678039a1b908ef6d894c18e893c1a0ce4ed72e`;
972-byte BSS and 6,764-byte remaining stack. The generated controller logic,
CSR map and PHY header match v18 exactly after replacing firmware words and
known banner metadata. Evidence:
`build_ypcb_native32/firmware-overlay-write-proof-20261020-v1/`.
The matching CPU proof and physical test are complete. No GPU workload ran.
The next repair is the OpenTPU-derived PHY/clock/calibration integration, followed
by fresh synthesis, routing and physical memory/kernel checks. An exact BRAM-only
patch plan for v18 was prepared in `firmware-bram-map-20261020-v1/`, but was not
applied or turned into a bitstream because write alignment alone did not fix DDR.

## Full OpenTPU-derived CH1 calibration port

The candidate now runs the full clock-phase sweep, write-latency search,
per-bit read alignment and 64 MiB native DDR traffic checks per phase. It keeps
CH1-only 2 GiB with ECC and the 512-bit AXI/external Wishbone interfaces.
Logical mailbox channel 0 identifies physical CH1; the CPU retains its 128-word
mailbox and 16 KiB BRAM. Terminal success is deferred until ECC/controller
handoff. The donor's cycle report remains a low-32-bit counter.

Firmware `a77fc8fe` is 8,956 bytes, SHA-256
`19a6e26aad635f3eb3ba09d079a2a5bafdb3707c52cf4ff6b46bd90a8d44c73c`.
BSS is 3,416 bytes, leaving 4,012 bytes for stack. The image has only RV32I
instructions and no unresolved symbols. The installed GPU compiler's libgcc
has a floating-point ABI, so matching multiply/remainder helpers are compiled
with the firmware. Their 100,056 boundary/random cases passed.

The actual VexRiscv CPU passed a complete per-bit phase calibration, including
ECC lane8 corrections: 381,939,895 cycles, 8,826,959 MMIO operations, maximum
open-row interval 470 cycles (limit 3,510). All 4,096 firmware words were
uploaded/read-verified in the CPU RTL test, with variable bus stalls. Native
clock-error cleanup passed too. Host tests additionally passed normal, no-phase,
unsupported framing-span and ECC-enable readback failures. The controller
export passed Yosys hierarchy/proc/check elaboration.

The native traffic checker passed 24 functional simulations: both data patterns,
independent command/data/response stalls, lengths 1/31/128, injected data-lane0
and ECC-lane8 errors, and counter reset. The proposed ABI4 runtime reader passed
an actual firmware-generated mailbox and 36 admission checks. It is not yet
connected to the production runtime or board startup.

Evidence: `build_ypcb_wl32/standalone-validation-20261020-v2/manifest.json`.
CPU proof: `build_ypcb_native32/wl-selfcal-cpu-proof-20261020-v2/manifest.json`.
The new variant has its own `build_ypcb_wl32/` directory, sharing only the pinned
Python environment and reference dependencies. Remaining work: buffered50MHz
board connection, reviewed phase/SERDES constraints, ABI4 runtime/startup,
full GPU/AFU checks, fresh single-worker synthesis/routing/report/CRC gates,
then authorized SRAM, DDR/ECC and GPU tests. No new bitstream or physical GPU
pass is claimed from these standalone results.

## ABI4 board integration and implementation

The board now connects buffered 50 MHz to the WL controller; the GPU stays at
125 MHz. Runtime, startup hardware and JTAG identity checks require ABI4. The
runtime uses the validated phase/per-bit result reader before requesting ECC
scrub. DDR MMCM lock status now crosses two preserved synchronizer stages.
Both Vivado worker settings remain one, with an 8 GiB service memory limit.

ABI4 startup/scrub RTL and host tests passed. All 69 integration Python checks
passed. The complete actual-GPU shell passed memory, demo and SGEMM via both
modeled PCIe and modeled JTAG, with source/DDR responses still simulated:
`build_ypcb_wl32/shell-abi4-20261020-v1/manifest.json`.
The production runtime and all five basic-operation GPU kernels build. A
preparation check caught a default-address example build; the kernels and kernel
library were rebuilt with matching YPCB flags and entry `0x40000000`. All seven
physical-test kernels (demo, SGEMM and five basic operations) are RV32 and fit
the code region below `0x50000000`. The hardware runner checks those `.vxbin`
address bounds before taking a hardware lease. Build receipts:
`build_ypcb_wl32/basic-examples-board-build-20261020-v1/manifest.json`; readiness:
`build_ypcb_wl32/hardware-test-preparation-20261020-v1.json`. Their frozen package
paths/help were checked without accessing hardware. Physical
qualification now includes all five example scripts after memory/demo/SGEMM,
with enabled and clean ECC required after each application.

Fresh synthesis succeeded in 990.125 seconds, peak Vivado allocation 4,865.719 MiB.
Checkpoint SHA-256:
`95b1add2be39a4867a3b53e206f1ac4e9023f107e2816c2606376dd23723dee8`.
Receipt: `build_ypcb_wl32/wl-ch1-jtag-pcie-20261020-v1/synthesize-exit.json`.
Implementation stopped before placement on clock-check Tcl queries. The native
netlist confirms both preserved lock synchronizer registers and an identity LUT
on the retained status-wire name. The checks now verify that LUT explicitly,
keep the second-stage settling path timed, and distinguish unused data-mask
serializers from physical outputs. Native positive and four altered-netlist checks passed in the recorded
interactive session `clock-inspect-20261020-v1/`: all 179 connected serializer
resets, both lock synchronizer stages and their settling path were verified.
The reset-constraint exporter now selects FDRE sources, excluding inferred LUTs
that caused invalid-startpoint warnings. The regenerated controller was compared
after only the known hierarchy/date comments; identical hardware logic was
proved and the exact compiled RTL retained in `wl-controller-20261020-v3/`.

The first resumed implementation also stopped during those checks; its synthesis
reuse verified all 674 hardware inputs and retained the exact compiled CDC RTL.
Neither earlier run reached routing or produced a new bitstream. The fresh `wl-ch1-jtag-pcie-20261020-v3/` has resumed implementation from the
verified synthesis checkpoint after the successful native clock checks. Unit
`vortex-wl-board-20261020-v3.service` is active, with both Vivado thread limits
set to one and MemoryMax=8 GiB. Reuse revalidated all 674 hardware inputs;
The new run passed both pre- and post-optimization clock checks and completed
placement successfully (zero placement warnings/errors, 898 reported seconds).
Physical optimization is active; routing and final timing/bitstream checks are
pending. Observation: `build_ypcb_wl32/placement-observation-20261020-v1.json`. Keep all original run directories. JTAG remains released while offline work
continues, and physical GPU execution is still unverified.

## Basic operations through actual GPU/AFU RTL

All 14 Python/public-runtime checks passed through the JTAG model of the actual
GPU/AFU RTL, using the correctly linked YPCB kernels: vector addition, all seven
elementwise operators (including division), rectangular GEMM, two convolution
layouts and all three pooling modes. This uses the explicit test backend, with
simulated DDR/PHY responses, and is not a physical FPGA result. Evidence:
`build_ypcb_wl32/basic-ops-rtl-20261020-v1/manifest.json` (7.325 seconds).

The physical result validator now recognizes the individual operation labels
printed by the existing scripts and requires all 13 default numerical checks
across the five files. Missing, duplicate, wrong-backend, empty and nonfinite
reports are rejected. All 54 runner tests passed, including those formatter
contract cases and the kernel address/producer checks. The FPGA implementation
continues in detail placement; no new bitstream has been programmed.

## Routed report gates passed; bitstream generation active

The new WL/ABI4 run passed all seven routed gates: setup +0.034 ns, hold
+0.027 ns, pulse width, Gray-bus skew, complete routing, internal timing coverage
and DRC. All 152,477 routable nets are routed, with no routing errors, unclocked
register endpoints or unconstrained internal endpoints. This is internal FPGA
implementation evidence; external DDR operation remains a physical test.

Bitstream generation is active under `vortex-wl-board-20261020-v3.service`.
Do not program until its actual successful exit receipt and bitstream CRC check
exist. Observation, including checkpoint hash:
`build_ypcb_wl32/routed-signoff-observation-20261020-v1.json`.
Prepared physical run: `build_ypcb_wl32/run-fpga-kernels-20261020-v1.sh`.
It checks authorization, producer, frozen inputs and CRC, takes the normal leases,
loads SRAM and runs memory/demo/SGEMM plus all five example scripts (13 numerical
checks). Clean enabled ECC is required after each application; flash is not used.

## Basic-operation examples verified on SimX

The requested [examples folder](examples/README.md) now has flat Python entry
points `simple_add.py`, `elementwise.py`, `gemm.py`, `conv.py` and `pooling.py`,
with readable device kernels under `examples/kernels/`. They cover float32
addition, subtraction, multiplication, division, minimum/maximum, ReLU,
rectangular matrix multiplication, CHW/OIHW convolution and max/average/min
pooling. CPU arithmetic is the verification reference; all reported results
come back through the Vortex runtime and GPU kernel.

All 50 numerical checks passed on SimX across 23 command cases, including
independent known outputs, partial warps, rectangular matrices, channel/filter
layout, padded borders and average-pool divisors. Invalid shapes exit 2, help
works without a device, and the default remains SimX even with an inherited
`VORTEX_DRIVER=ypcb`. The Python/C argument and launch layouts match actual C++
headers. Generated build Makefiles reuse the existing kernel toolchain rules;
source builds stay out of tree. No additional Python packages are required.

All five ELF kernels are RV32 with entry `0x40000000`, using the same YPCB
configuration as the rebuilt kernel library, runtime stub and SimX backend.
The shared build-rule change also passed existing demo and SGEMM regressions:
demo 284 instructions/910 cycles; SGEMM 7,632 instructions/18,686 cycles. This
completes the previously pending native SimX smoke check.

Evidence and exact commands/hashes:
`build_ypcb_native32/basic-ops-examples-20261020-v2-final/manifest.json`.
Build receipts: `build_ypcb_native32/basic-ops-examples-20261020-v1/`.
The build used one worker with a 4 GiB service memory limit. No bitstream was
built or changed, and no FPGA/JTAG access or lock acquisition occurred. Physical
DDR calibration and GPU execution remain pending as stated above.

To run a ready example from `build_ypcb_native32`:
`./ci/ypcb_env.sh exec python3 ../examples/simple_add.py`.

## Per-bit diagnostic firmware verified offline

Firmware `78dc1fa8` now records the failed lane's eight individual bit windows,
passing-tap counts, raw selected-bitslip masks and scan error masks. It uses
reserved words in the existing 128-word mailbox, adds no DDR probes, and still
rejects a byte with no common eye. The runtime validates and prints the report.

Native checks passed 4,224 window cases and 40 per-bit cases covering both
framing offsets and unreadable bits, with malformed-report rejection and failed
initialization retained. The actual RV32I CPU/BRAM/Wishbone simulation passed
its normal 6,942-probe run and a 6,936-probe lane 8 failure with bit 5 shifted by
two read bitslips. The failed run retained eight individual eyes and kept memory
disabled. Normal execution took 112,954,178 simulated cycles; maximum open-row
span was 801 cycles against the 3,510-cycle limit. Reset/restart, BRAM upload,
backpressure, bus-error propagation and failure cleanup also passed.

The new firmware is 7,288 bytes, BSS 712 bytes and stack reserve 8,384 bytes.
It contains 1,705 RV32I instruction words, no unresolved symbols and no M/F/C
instructions. SHA-256:
`2a49007e44b931ec381563506113bc56022d36e2aa5834e1e8c70da7ba67ee2c`.
The fresh controller export is
`build_ypcb_native32/local-selfcal-ddr-20261020-v4-bit-diagnostics/`.
Only firmware BRAM initialization differs from v3 after removing the specific
known generator metadata; CPU/mailbox/controller logic is unchanged. This
source comparison does not qualify checkpoint reuse or a new physical image.

The runtime built separately with strict link checks, and the software/hardware
source-boundary guard passed. The RTL test's missing Verilator default is fixed;
the original failed command receipt is preserved. Its corrected native unit
finished with exit 0, no interruption, in 112.3 seconds. It used one build worker
and a 3 GiB service memory limit. No Vivado build or hardware access was started.

Evidence: `build_ypcb_native32/selfcal-bit-diagnostics-20261020-v1/manifest.json`;
actual CPU log/exit: `build_ypcb_native32/selfcal-bit-diagnostics-20261020-v2-rtl/`.
The next offline step is a reviewed firmware upload/provenance path for the
existing calibration CPU. The old v18 runner's image/firmware binding must
remain enforced. Diagnostic firmware is not a DDR fix or permission to reacquire
JTAG; physical per-bit evidence, memory/ECC and GPU examples are still pending.

## Offline OpenTPU review

OpenTPU provides a relevant calibration approach: per-bit read framing,
write-latency scanning and adjustable clock phase. Its `docs/litedram.md`
documents CH1 lane 8 with no byte-wide eye because individual DQ bits needed
different read bitslips. Vortex currently has only byte-wide read training.

A baseline native experiment runs the pre-diagnostic Vortex C firmware against
synthetic raw PHY responses. Uniform ECC framing passes all nine lanes and
6,942 probes. Shifting each of the eight ECC bits independently by two read
bitslips reproduces lane 8 NO_EYE, all-zero byte masks and 6,936 probes, despite
valid eyes for every individual bit. All eight cases retain failure cleanup.
This confirms a calibration limitation that can produce the saved symptom;
it does **not** prove the physical Vortex cause without per-bit observations.

All 117 CH1 pins match OpenTPU. A completed native inspection of the saved
routed checkpoint confirms internal VREF 0.750 V on banks 16–18. None of ECC
DQ64–71 has a VREF package-pin function; the earlier VREF-pin hypothesis is
rejected. No pin or VREF change is justified by this evidence.

The exact OpenTPU PHY metadata matching its c0182800 hardware record is DDR800,
100 MHz, CL6/CWL5, with the WL PHY and CK phase -44. Its successful CH1 startup
needed a per-bit +2 correction on lane 2 bit 0, while ECC lane 8 offsets were
zero in that image. The currently bundled host profile had a different hash
and was excluded; the review uses the exact frozen core metadata. Do not copy
measured constants or transfer qualification between the two designs.

Review, source hashes, reproducible experiment and actual exit codes:
`build_ypcb_native32/opentpu-ecc-framing-review-20261020-v1/manifest.json`.
The review did not access hardware or acquire either lock.

The diagnostic implementation above is verified offline. Review a bounded
firmware upload path and any required PHY/read training or phase change.
Any changed PHY/clock RTL requires fresh
synthesis and full bitstream qualification. Preserve the full RV32 GPU at
125 MHz, CH1-only 2 GiB/ECC, and both JTAG and PCIe runtime interfaces. Physical
calibration, memory/ECC, `demo` and SGEMM remain pending hardware authorization.
See [the proposal](docs/proposals/ypcb_local_ddr_calibration_proposal.md).

## Completed image and simulation evidence

The v17 implementation passed all seven routed report gates: setup +0.011 ns,
hold +0.040 ns, 147,570 fully routed nets, zero routing errors, and no unclocked
or unconstrained internal endpoints. Its producer disappeared during bitstream
generation with no exit receipt; the original exit remains unknown. A host OOM
occurred at the same time, but the exact Vortex termination cause is unproven.

The preserved routed checkpoint was finalized in the fresh
`build_ypcb_native32/ch1-jtag-pcie-20261020-v18-finalize/` directory. All 756
original frozen inputs, its archive CRC and all 760 finalization input hashes
passed. Native finalization exited 0 after 466.4 seconds, without interruption
or timeout. The bitstream is 18,735,205 bytes, SHA-256
`f5bd03e294c7ae4a678458f8d01213366109e87816abd6325555086d8dc61d5b`.
Both CRC checkpoints, four checker vectors and runtime/controller binding passed.
Both GPU ELF entries are RV32 at `0x40000000`. No synthesis or routing was
repeated during finalization. Both Vivado worker limits remain one and allocator
arenas remain two. This image is offline qualified but failed physical DDR
calibration as recorded above; rebuilding the same sources does not address it.

Full GPU/AFU simulation passed memory, `demo` and SGEMM through both PCIe and
JTAG in `build_ypcb_native32/native-shell-abi3-20261020-v1/`; JTAG also passed
with the PCIe clock stopped. Demo retired 2,444 instructions and SGEMM 7,632;
all numerical/memory checks passed. The local VexRiscv calibration CPU also
passed RTL simulation with PHY response oracles. These remain simulation
results, separate from physical DDR and GPU qualification.

## Earlier milestones and preserved history

v17 synthesis passed with actual exit 0 after 1,192.6 seconds, zero errors and
zero critical warnings. It uses 83,386 LUTs, 67,384 registers, 160 BRAM tiles
and 24 DSPs. The checkpoint SHA-256 is
`aaf6be96cde50c1b0bb571de8b60cc2b8078440c8b07fb4d49919c25a9ce935a`.
The complete native-client/Tcl loopback test exposed a stale socket-owner race;
the bridge now observes a previous peer's EOF before deciding ownership. All
ten protocol tests pass, including 64 reconnects with active-client rejection.
This software fix does not change the frozen FPGA HDL. The new physical job
above is the first ABI 3 SRAM/kernel attempt after the ABI 2 JTAG-only probe.

v17 placement and physical optimization completed. The last pre-route estimate
was setup slack +0.007 ns and TNS 0. Routing subsequently passed as recorded
above. Pre-route DRC reported zero errors. The placement milestone
is saved in `build_ypcb_native32/v17-placement-milestone-20261020.json`.
The hardware launcher now also requires a successful, uninterrupted producer
exit receipt before programming; all 16 checks and its native receipt check pass.

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
