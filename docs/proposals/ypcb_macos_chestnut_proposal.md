# YPCB macOS/Chestnut qualification

The selected image is the existing 125 MHz, 4 GiB Vortex image with SHA-256
`d6ad50f70469d6cf3d25f8ca0f8dee1875988b0ac07bec0fa88b8cd0ff06dfb3`.
Its JTAG and permanent-programming results remain separate from Mac/PCIe
acceptance. This host-side work changes no FPGA RTL or bitstream.

Chestnut exposes vendor USB requests for PCIe configuration and memory TLPs.
Reuse the measured OpenTPU USB framing and temporary configuration/restore
pattern, retaining the Apache-2.0 attribution. Vortex has endpoint `10ee:0480`,
one 32-bit 64 KiB BAR, its own ABI 5, PIO memory bridge and command processor.
OpenTPU's XDMA descriptors, endpoint IDs and accelerator registers are not
compatible with that surface.

A loopback-only MMIO service translates the existing register protocol to
Chestnut PCIe transactions. The runtime explicitly selects `chestnut`, requires
the service port, and retains the native Vortex calibration, startup, memory
allocator and command-processor implementation. Posted writes receive a status
read fence; transfer uncertainty quarantines the session without resubmission.
The shared Chestnut device lock excludes OpenTPU writers. Shutdown drains the
MMIO handlers, quiesces the Vortex AFU and restores saved PCIe configuration.

Track the 40 already qualified RISC-V kernels, their generated configuration
headers and numerical references in `runtime/ypcb4g/`. Use host sources directly
from the Git checkout and dependency sources from the pinned Git submodule. Build the runtime and
application hosts natively on the Mac; build SoftFloat with the same RISC-V
specialization and thread-local state as the canonical Vortex build. No Linux
ELF host executable or Linux static library is a Darwin runtime artifact.

Preflight verifies the checkout and tracked runtime data without opening USB. Identity checks the link,
endpoint, BAR and ABI. Memory and quick stages provide focused checks; full
runs all 53 software cases plus the raw physical-memory probe. An explicit
card-power-cycle attestation enables the eight-pass full-capacity BIST before
runtime initialization. Later repeats use fresh output directories.

Vortex's PCIe register surface does not expose a cryptographic bitstream hash.
The tracked runtime descriptor pins the flashed image and verifies compatible live identities,
while reporting that the live bitstream SHA-256 was not read over PCIe.
Offline protocol controls and Linux native builds cannot qualify Darwin or
physical PCIe; those outcomes require the Mac's actual run receipts.
