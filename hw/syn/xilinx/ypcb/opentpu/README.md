# OpenTPU-derived CH1 integration prototype

This candidate brings OpenTPU's WL7 DDR PHY, clock control, registered command
injector and native traffic checker into a standalone CH1 controller. The
reference includes a physical TinyStories pass on build `c0182600`, with
28,909,056 verified bytes and matching tokens; CH1 calibration, including ECC
lane 8, succeeded. Source and reference identities are in `provenance.json`.
Qualification does not transfer to the new Vortex integration.

The prototype retains nine physical byte lanes, ECC, 2 GiB of payload, the
512-bit AXI port and external Wishbone control. It keeps the four original CSR
bank bases and places the extra clock/BIST controls inside `ddrctrl`, within
the existing 8 KiB CSR window. The AXI frontend retains read-modify-write for
partial beats because the board has no DM connections.

Generate from a configured build with the pinned Migen/LiteX/LiteDRAM packages
on `PYTHONPATH`:

```bash
python3 ../hw/syn/xilinx/ypcb/opentpu/gen_core.py --output ch1-wl-prototype \
  --cc "$TOOLDIR/riscv32-gnu-toolchain/bin/riscv32-unknown-elf-gcc"
```

**Physical qualification remains pending.** Its CPU now
runs the complete calibration algorithm: clock phase, write latency, per-bit
read framing and native traffic tests. Host response-oracle cases and an actual
RV32I CPU run passed; the latter exercised per-bit corrections including ECC
lane 8, bus stalls and failure admission. These are simulation results.
`prototype.json` records the export's unqualified status. The native traffic checker and runtime reader passed standalone tests. Board
clock/ABI4 integration is implemented; full GPU and routed timing/CDC checks
remain required.
The existing production generator and qualified v18 image remain separate.

The clock input is **50 MHz**, while the existing Vortex controller receives
200 MHz. Full board integration must connect the buffered 50 MHz clock and
review all clock/reset constraints before building an image. The controller
runs at 100 MHz, DDR800; phase scanning must remain within half a DDR clock
period. The provisional 1.3 ns clock uncertainty covers that 1.25 ns bound;
native endpoint, reset and timing review remain required.

The next steps are to integrate the runtime metadata, verify the native traffic
checker, connect the board clock and constraints, rerun the full GPU/AFU flow,
and qualify a freshly routed image.
Retain the full GPU and both JTAG/PCIe runtime interfaces throughout.

`wl7ddrphy.py` and `dfii_q.py` retain their original notices. Clock and BIST
classes were extracted from OpenTPU's `tools/litedram/ld_test.py`; see the
included license files. No checkout of OpenTPU is required by the generator.

The single-channel firmware uses logical mailbox channel 0 for physical CH1,
with 128 mailbox words. Terminal publication is deferred until Vortex's ECC
and controller handoff succeeds. The 32-bit cycle field retains the donor's
modulo-2^32 format. Integer multiply/remainder helpers are compiled for RV32I;
the installed GPU toolchain's floating-point-ABI `libgcc` is unsuitable for this
CPU. The full GPU keeps its separate FPU configuration.
