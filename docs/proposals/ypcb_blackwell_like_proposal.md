# YPCB Blackwell-inspired compute and kernel studies

## Purpose and sequence

Use Vortex to study low-precision tensor arithmetic, structured sparsity and
overlapped memory/compute kernels associated with modern NVIDIA GPUs. This is
a Vortex implementation of related capabilities, not Blackwell ISA emulation
or CUDA binary compatibility.

Finish the existing FP16/INT8 image and its offline qualification before
starting this variant's builds. Preserve its bitstream, frozen inputs,
configuration and numerical evidence as a comparison baseline. Physical
baseline and variant testing remain subject to OpenTPU's JTAG priority;
finishing an offline image does not establish FPGA execution.

Keep a separate profile, `ypcb_blackwell_like`, and an independent configured
build directory, `build_ypcb_blackwell32/`. Preserve the full GPU, JTAG and
PCIe interfaces, CH1-only 2 GiB DDR3, all nine byte lanes and enabled ECC.
Use the existing native toolchain. Keep one heavy Vortex stage at a time,
both Vivado worker limits at one and the 8 GiB service memory cap.

## Feature set

All configuration names below have the `VX_CFG_` prefix. Select TFR with DSP
inference and matching RTL/SimX latency as the FPGA arithmetic backend.

| Capability | Configuration |
|---|---|
| Tensor unit | `EXT_TCU_ENABLE`, `TCU_TYPE=TFR` |
| FP16/BF16 and signed/unsigned INT8 | `TCU_FP16_ENABLE`, `TCU_INT8_ENABLE` |
| TF32 and FP8/BF8 | `TCU_TF32_ENABLE`, `TCU_FP8_ENABLE` |
| MXFP8/MXBF8 block scaling | `TCU_MX_ENABLE` with `TCU_FP8_ENABLE` |
| MXFP4 and NVFP4 | `TCU_FP4_ENABLE`, `TCU_MX_ENABLE`, `TCU_MXFP4_ENABLE`, `TCU_NVFP4_ENABLE` |
| Structured 2:4 sparsity | `TCU_SPARSE_ENABLE` |
| Shared-memory matrix operands | `TCU_WGMMA_ENABLE` |
| Asynchronous global-to-shared copies | `EXT_DXA_ENABLE` |
| Integer atomic operations | `EXT_A_ENABLE`, `EXT_ZACAS_ENABLE` |
| Memory hierarchy | Retain L1/shared memory and enable `L2_ENABLE` |

Choose warp count, thread count and shared-memory geometry from the canonical
cases in `ci/testcases/tensor*.yaml` and the DXA tests. A 32-thread warp is an
additional geometry to study, not evidence of architectural compatibility.
Measure its FPGA area and timing before selecting it for the physical image.
Do not silently remove features to make a build pass; record resource or
timing constraints and the resulting profile explicitly.

Vortex WGMMA and DXA provide related matrix/shared-memory and copy operations;
they do not implement Blackwell's TMEM/`tcgen05` instruction surface. This
checkout has no direct FP6 configuration switch. Vortex's `TCU_DSM_ENABLE`
means a dynamic sparsity mask, not NVIDIA distributed shared memory. NVFP4
studies must include scale packing and any tensor-level scaling in software.

## Study kernels and evidence

The [study launcher](../../examples/blackwell_like/README.md) reuses the
reference-checked device kernels and records configurations, binary hashes,
numerical checks and retirement counters. It provides these studies:

Runnable examples use a CPU reference, deterministic inputs, dimensions,
format/scale descriptions and a clear numerical result:

1. Dense FP16 and BF16 GEMM with FP32 accumulation as the baseline.
2. INT8/UINT8 GEMM with INT32 accumulation.
3. TF32, FP8/BF8 and MXFP8 GEMM, including quantization/scaling error.
4. NVFP4 and MXFP4 GEMM with explicitly documented block and tensor scales.
5. Structured-sparse GEMM against the corresponding dense computation.
6. Shared-memory tiled GEMM using WGMMA.
7. DXA copy and tiled GEMM to compare sequential and overlapped data movement.
8. Integer atomic reduction or histogram and a memory-reuse/cache study.

Reuse the existing examples' runtime conventions and the upstream tensor/DXA
intrinsics. Generate applications and runtime from the same configured
profile; do not mix binaries or generated headers between variants.

Verify each format's arithmetic using the canonical unit references, then
the kernels through SimX and XRT. Cover rectangular matrices, repeat launches,
legal tile geometries and scale/metadata edge cases. New timing behavior
requires matching SimX modeling and appropriate parity cases. Maintain the
existing numerical tolerances and performance/synthesis golden data.

Before FPGA use, validate both modeled host interfaces and run fresh whole-
design synthesis, implementation, all seven report gates, frozen-input and
bitstream CRC checks. After JTAG priority is released, test physical memory,
all-nine-lane calibration, clean ECC, scalar regressions and each selected
tensor/copy/atomic kernel. Keep simulation, offline implementation, physical
JTAG execution and physical PCIe qualification distinct in the results.

## References

- [Vortex TCU/WGMMA design](../designs/tensor_core_wgmma_engine.md)
- [Vortex DXA design](../designs/dxa_async_copy_multicast.md)
- [NVIDIA FP8, MXFP8 and NVFP4](https://docs.nvidia.com/deeplearning/transformer-engine-releases/release-2.13/user-guide/examples/fp8_primer.html)
- [NVIDIA fifth-generation tensor instructions](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html#tensorcore-5th-generation-instructions)
