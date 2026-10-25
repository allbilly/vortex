# Matched YPCB 4 GiB runtime data

These Git-tracked fixtures select the already flashed image with SHA-256
`d6ad50f70469d6cf3d25f8ca0f8dee1875988b0ac07bec0fa88b8cd0ff06dfb3`:
125 MHz compute, CH0 2 GiB without ECC and CH1 2 GiB with ECC, ABI 5.

- `generated/`: the three matching C++ configuration headers.
- `kernels/`: 40 unchanged RISC-V kernel binaries from the passing FPGA suite.
- `references/`: the preserved numerical/setup reference logs.
- `runtime.json`: the exact 54-case application/raw-memory matrix, source/data
  hashes, compiler configuration and pinned SoftFloat revision.
- `runtime.sha256`: integrity check for the descriptor.

Host code comes directly from the Git checkout. The native build uses the
existing `third_party/softfloat` Git submodule and writes outputs only under
the selected build directory. Run `bash ci/mac_vortex.sh preflight` from the
repo root; see [the Mac guide](../../docs/mac_vortex.md) for all commands.

JTAG and flash qualification do not establish a physical Mac/Chestnut result.
The live PCIe register surface does not expose a bitstream SHA-256; the test
records compatibility checks and keeps that attestation limit explicit.
