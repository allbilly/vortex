# Local CH1 DDR calibration

The qualified ABI 2 image loads into SRAM and exposes the JTAG register interface.
The physical probe measured 32 reads at 12.65–27.37 ms each, median 17.76 ms.
Host calibration performs 424,234 MMIO calls and keeps a row open across nine
calls. This transport cannot satisfy the configured DDR command timing, so host
training is not a viable initialization path.

Add a minimal RV32I calibration CPU inside the existing CH1 LiteDRAM core. Use
OpenTPU's 16 KiB dual-port BRAM, Wishbone master and local timer approach, with
firmware generated from Vortex's actual CSR and PHY metadata. Preserve the
external Wishbone control port, CH1-only 2 GiB, ECC, the full RV32 GPU at 125 MHz,
and both JTAG and PCIe interfaces.

Keep LiteDRAM's primary CPU setting at `None`; enabling its standard CPU would
remove the external control port. Place calibration controls and a result-mailbox
window within the existing `ddrctrl` CSR group so all registers remain inside
the current 8 KiB channel window. The local CPU runs at the controller's 100 MHz
clock and calibrates at reset. Its data port also supports bounded firmware
upload/readback while held, for bring-up without another bitstream per firmware
iteration. Bus errors must remain visible.

Board ABI 3 makes initialization ownership explicit. The runtime requires the
local CPU and waits for its result before starting ECC scrub and GPU submission.
It never attempts host DDR training. Keep the current native DDR algorithm as
the software oracle for firmware verification: nine lanes, all read taps and
bitslips, three test patterns, midpoint selection, ECC/readback and failure
cleanup. Record local command-span cycles to validate row timing.

Set both JTAG AXI transaction queues to sixteen entries, verified by property
readback, so software can transfer the sixteen-word PIO data window as a batch.
Individual register latency remains a separate transport measurement. PIO
completion timeouts bound each hardware command, while the hardware runner
bounds each complete application.

Before synthesis, verify native firmware behavior against the oracle, compile
RV32I firmware within the 16 KiB image/stack budget, check CPU/BRAM/Wishbone
integration and rerun the full AFU memory/demo/SGEMM simulation. Freeze the CPU
RTL and firmware initialization content in the controller export. Fresh synthesis
is required; the ABI 2 routed checkpoint cannot be reused for this design.
Retain one Vivado worker and perform final routing/report/integrity gates before
physical CH1 memory, ECC, `demo` and SGEMM checks. SRAM/JTAG success remains
separate from those runtime results.

## Physical result and OpenTPU comparison

The ABI 3 v18 image loaded successfully into SRAM and passed queued JTAG
register transfers. Its local firmware trained data lanes 0–7 but found no
read window on ECC lane 8, stopping after 6,936 probes. Memory and GPU kernels
did not run. ECC remains required; disabling it does not qualify this design.

OpenTPU's `docs/litedram.md` records CH1 lane 8 failures caused by individual
DQ bits arriving two read bitslips apart. Its PHY provides `dly_sel_bits` and
its firmware scans per-bit read eyes, write latency and clock phase. Vortex's
current PHY and firmware train read alignment per byte at a fixed clock phase.
That difference provides a specific diagnosis to investigate.

A native experiment with the actual Vortex C firmware reproduces the observed
failure when any one ECC bit requires two extra read bitslips: every byte-wide
scan mask is zero and calibration stops at lane 8 after 6,936 probes, although
all eight individual bit eyes remain valid. Uniform framing passes all nine
lanes and 6,942 probes. These are synthetic PHY responses, so this experiment
does not establish the physical card's failure mechanism.

All 117 CH1 pin assignments match OpenTPU. The saved routed Vortex checkpoint
already has internal VREF 0.750 V on banks 16–18, and no ECC DQ package pin has
a VREF function. These checks do not justify changing pins or VREF. The exact
OpenTPU profile bound to its saved c0182800 result is also DDR800 at 100 MHz,
CL6/CWL5, but uses a different PHY with adjustable CK phase. Its successful
CH1 result needed a per-bit correction on lane 2; ECC lane 8 required none in
that image. Do not transfer measured phase or bitslip constants between builds.

The next calibration change needs per-bit diagnostic evidence and a reviewed
implementation of any required per-bit or clock training. A PHY or clock RTL
change requires fresh synthesis and bitstream qualification. Preserve the full
GPU, CH1-only 2 GiB with ECC, and both runtime interfaces. Physical calibration,
memory/ECC, `demo` and SGEMM remain pending. The user has reserved JTAG for
another session; continue offline until hardware access is authorized again.

The reproducible comparison, source hashes, command exit codes and native log
are in `build_ypcb_native32/opentpu-ecc-framing-review-20261020-v1/`.

## Per-bit failure diagnostics

The firmware now collects per-bit pass masks during the existing byte scan;
it adds no training probes and changes no acceptance criterion. If a complete
scan has no byte-wide eye, it reports each bit's longest stable eye, its total
passing tap count and its raw mask at the selected read bitslip. A valid-bit
mask distinguishes independent eyes from bits with no stable eye. Error OR
and AND masks describe the three-pattern results across all 256 scan settings.
These observations distinguish candidate failure mechanisms without claiming
that per-bit alignment has been applied.

The existing 128-word mailbox has enough reserved space: words 9–14 contain
diagnostic magic, lane, valid bits, error OR/AND and completed scan settings;
104–111 contain packed bit windows, 112–119 contain passing-tap counts and
120–127 contain selected-bitslip masks. Windows use the existing lane format:
bitslip, first tap, last tap and center in successive bytes. Diagnostics are
published only after a full failed byte scan; the normal terminal state is
written last. Timeout or incomplete scans do not publish a complete diagnostic.

The runtime validates and prints these fields while retaining calibration
failure. It rejects malformed bounds and an initialization-ready result carrying
failure diagnostics. Firmware identity changes bind the updated reader to the
updated firmware. This diagnostic firmware alone does not repair DDR framing.
The CPU and mailbox RTL are unchanged; only the controller's firmware BRAM
initialization differs after removing known generator metadata. Using the new
firmware with an existing image still needs a reviewed upload/provenance path;
the current hardware runner must not bypass its image/firmware binding.
