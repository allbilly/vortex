# YPCB FP16 and INT8 tensor kernels

Build a separate RV32 image that executes `sgemm_tcu` using FP16 inputs and
FP32 accumulation, plus INT8 inputs and INT32 accumulation. Preserve the
qualified scalar image and its evidence.
The tensor image retains the full GPU, CH1-only 2 GiB DDR3 with ECC, both JTAG
and PCIe memory/control paths, and JTAG operation without a PCIe connection.

`profiles/ypcb_tcu.json` selects one core, four warps, eight threads and one
TFR tensor block. The GPU target remains 125 MHz. DSP inference and the
five-stage tensor pipeline are selected explicitly in the profile so SimX,
RTL and synthesis use the same arithmetic and latency. `ITYPE=fp16` and
`OTYPE=fp32` select the floating-point application; `ITYPE=int8` and
`OTYPE=int32` select the integer application. Keep separate executable/kernel
copies for both formats. The WL/ABI4 DDR controller and
calibration firmware remain unchanged.

Use a new out-of-tree `build_ypcb_tcu32/` configured with `--profile=ypcb_tcu`,
RV32 and 2 GiB memory. Build the kernel library, runtime dispatcher, backend
and applications with that profile. The YPCB shell model must retain those
configuration flags in its RTL and host-side capability code.

The TFR Boolean parameter is named `DSP_ENABLE`: Vivado exports module
parameters as case-insensitive synthesis properties, and `USE_DSP` collides
with its string-valued `use_dsp` property. This parameter rename changes no
arithmetic or pipeline stage.

The first tensor implementation missed 125 MHz setup by 0.129 ns on one DMA
endpoint. Its path runs from `dst_offset` through buffer indexing, alignment
and the host read-back comparison into the DMA state register: 27 logic levels
and 8.036 ns of data-path delay. Hold, pulse, routing, skew, internal coverage
and DRC passed. Capture the final accepted host write beat and byte strobes,
then compare read-back data against that reference. It is available before
the write response and read-back request, so no state, AXI handshake or
command-completion cycle changes. SimX timing therefore needs no change.
Verify functional and cycle equivalence, including posted-write visibility,
then run fresh synthesis and the full integration and physical tests. The old
synthesis checkpoint cannot be reused after this RTL change.

Validation order:

1. Native TFR arithmetic, SimX `sgemm_tcu`, and actual GPU/AFU RTL through XRT,
   covering both datatype pairs. Use the canonical TFR FEDP reference at
   window width 25 from `hw/unittest/Makefile`, with its unchanged tolerance.
2. YPCB memory/control integration and tensor kernels through modeled PCIe
   and JTAG. Require numerical PASS and retired instructions.
3. Fresh single-worker synthesis, placement, routing, all routed report gates,
   frozen-input verification and bitstream CRC. Do not reuse scalar synthesis.
4. Authorized temporary SRAM programming, all-nine-lane calibration, enabled
   clean ECC, memory tests, scalar regression and physical `sgemm_tcu`.

Set both Vivado worker limits to one, use one heavy Vortex stage at a time,
and cap its service at 8 GiB. The native toolchain and Python environment are
shared read-only; generated objects belong to the tensor build. Permanent
flash is outside this work. Physical PCIe testing needs a connected host;
local FPGA execution uses JTAG while preserving both interfaces in the image.

The tensor variant is not yet physically qualified. Current run handles and
results belong in `progress.md` and the tensor build's receipts.
