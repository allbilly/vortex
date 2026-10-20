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
