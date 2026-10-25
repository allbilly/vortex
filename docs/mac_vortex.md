# Vortex 4 GiB on macOS and Chestnut

Use this handoff with the already flashed Vortex image:

```text
d6ad50f70469d6cf3d25f8ca0f8dee1875988b0ac07bec0fa88b8cd0ff06dfb3
```

It provides one 125 MHz core, eight warps of eight threads, the full selected
tensor/sparse/DXA/WGMMA/atomic configuration, 2 GiB CH0 without ECC and 2 GiB
CH1 with ECC. The image passed 57 JTAG qualification commands, its 303-check
audit, permanent program/verify/readback and flash-boot checks, plus scalar,
FP16 and INT8 checks after flash boot. Those results do not qualify macOS or
physical PCIe. This handoff does not program SRAM, write flash or require JTAG.

## Get the Git checkout ready

Use the Vortex `ypcb` branch. All scripts, the 40 matched RISC-V GPU kernels,
generated headers and numerical references are tracked in this repository.
The small frozen runtime data is under `runtime/ypcb4g/`; the host sources are
used directly from `sw/`, `tests/` and `examples/`. SoftFloat comes from the
existing pinned Git submodule. No separate archive or export step is needed.
A Vivado installation or a Mac RISC-V compiler is not required for these tests.

```bash
git fetch origin
git switch ypcb
git pull --ff-only
git submodule update --init third_party/softfloat
xcode-select --install                 # first time only
brew install libusb
```

Use native Python 3.10 or newer. The Python helpers use only the standard library. An existing
native Python environment is sufficient; with uv, for example:

```bash
uv python install 3.12
export VORTEX_PYTHON="$(uv python find 3.12)"
```

Python, libusb and the compiler must use the same native Mac architecture.
The build explicitly selects Python's `arm64` or `x86_64` architecture. The
runtime libraries keep their Vortex `.so` filenames but contain native Mach-O
code; Linux ELF libraries and Linux SoftFloat archives are not reused.

## Run the tests

Connect the powered FPGA card through Chestnut. Coordinate access with other
FPGA users. The helper holds the same `chestnut-3801-0001` device lock used by
OpenTPU, temporarily maps PCIe configuration and restores it on exit.

First verify the checkout/runtime data and build the native host code. Neither command
opens a device:

```bash
bash ci/mac_vortex.sh preflight
export VORTEX_MAC_OUT="$PWD/results/native-build"
bash ci/mac_vortex.sh build
unset VORTEX_MAC_OUT
```

The native build is under `results/native-build/native`. It builds the actual
Vortex runtime, all required test hosts and SoftFloat with the canonical
RISC-V specialization and thread-local state. The GPU kernels remain unchanged; generated host binaries stay under the ignored build directory.

Check the Chestnut PCIe link, endpoint `10ee:0480`, 64 KiB BAR0 and Vortex ABI 5:

```bash
bash ci/mac_vortex.sh identity
```

Identity temporarily changes PCIe configuration but does not initialize DDR or
run a GPU kernel. It is a compatibility/identity check, not a full-image hash
readback: Vortex does not expose its bitstream SHA-256 through these registers.
The tracked runtime descriptor pins the expected programmed image and records this limitation.

For the complete physical qualification, power the FPGA card fully off and
back on, let it boot from flash, then run:

```bash
export VORTEX_MAC_OUT="$PWD/results/full-cold-boot-1"
bash ci/mac_vortex.sh full --native "$PWD/results/native-build/native" --cold-boot
```

`--cold-boot` is an explicit statement that the card was physically power-cycled.
Resetting only Chestnut, the USB cable or the host software is insufficient.
The full-capacity native BIST requires fresh initialization state and fails if
the card has already entered normal runtime; it does not silently skip BIST.
The full run then verifies:

- Eight full-channel BIST passes over all 4 GiB of physical payload.
- Seven public memory-map regions, both DDR channels and their boundary.
- Raw final byte `0xffffffff`, cross-channel partial writes and 27 address lines.
- Scalar demo and GEMM, all five basic examples and all 13 numerical groups.
- All 21 studies, 22 tensor-format cases and two LR/SC cases, retaining the
  qualified dimensions, arguments, numerical tolerances and retirement checks.
- Enabled, clean CH1 ECC after every application and restored PCIe configuration
  with the AFU quiesced at the end.

For a shorter first check, use `quick` instead of `full`. It runs the memory and
raw probes, scalar demo/GEMM, all five examples and repeated FP16/INT8 GEMM.
`memory` runs the two memory probes. Both accept `--cold-boot` for a fresh card.
Use a fresh result directory for each invocation. A warm follow-on run can omit
`--cold-boot`; its receipt will not claim physical cold-boot verification.

```bash
export VORTEX_MAC_OUT="$PWD/results/quick-warm-1"
bash ci/mac_vortex.sh quick --native "$PWD/results/native-build/native"
```

Keep the entire output directory, including failures. `manifest.json` records
the selected case set, numerical results, ECC snapshots, platform and cleanup.
Every native command has a log and an exit/interruption/timeout receipt. USB or
PCIe completion errors quarantine the session without retrying uncertain writes.
Do not treat an identity-only result, offline control test, Linux build, missing
case or failed cleanup as completed physical PCIe qualification.

## Git-tracked runtime data

`runtime/ypcb4g/runtime.json` pins the selected image, full test matrix, compiler
configuration, generated headers, GPU kernels and numerical references. File
hashes bind the data to the matching checked-out host sources. Preflight rejects
missing or changed inputs before opening USB. The submodule revision and the
canonical RISC-V specialization/thread-local SoftFloat options are checked too.

The runtime folder contains only the small data that cannot be recovered from
the flashed FPGA. Host source trees, Python wrappers and dependency sources are
not duplicated there. The Mac builds its host libraries and applications from
the actual Git checkout. Normal Git transfer is sufficient; local uncommitted
changes still need to be committed and published before another checkout can
retrieve them. Test results, host binaries and FPGA build intermediates remain
outside tracked source directories.

## Protocol reference and evidence boundary

Chestnut USB framing and temporary PCIe setup follow the read-only OpenTPU donor
`opentpu/host/chestnut.py`, SHA-256
`7c345bda395fc30a37fc6f5e8c4bc4b8f1abb502a0c41915f13e1bad27eec929`
(Apache-2.0). OpenTPU's XDMA descriptors and accelerator/DDR layout are not used.
The Vortex MMIO service reuses Vortex's command processor, calibration and memory
implementation. Actual transport in the receipt is **PCIe via Chestnut**, even
though the local socket framing is shared with the existing JTAG client.

The socket implementation uses Darwin's `SO_NOSIGPIPE`; see the
[Apple socket-options manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getsockopt.2.html).
Native libraries are loaded relative to their runtime directory; see
[Apple dynamic-library install-name settings](https://developer.apple.com/documentation/xcode/build-settings-reference).

Mac-native build/loading, cold power-on behavior and physical PCIe results remain
unverified until this checkout runs on the Mac and its receipts are reviewed.
