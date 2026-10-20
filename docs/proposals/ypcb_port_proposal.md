# Vortex on YPCB-00338-1P1

## Target

Use the full RV32 Vortex GPU on `xc7k480tffg1156-2`, with the STD RTL FPU.
The requested runtime interfaces are JTAG and PCIe, both exposing control and
memory access. Device memory will use only CH1's 2 GiB DDR3; CH0 stays inactive.
JTAG execution must work without a PCIe link or reference clock.

## Retained implementation

- Board wrapper, PCIe endpoint, control register routing, PIO memory window,
  DDR control, ECC scrub, readiness sequencing and clock-domain crossings.
- Linux PCIe transport and shared host-memory, startup and DDR helpers.
- Byte-exact command-processor DMA with offset, guard-byte and burst tests.
- Vivado-safe FPU parameter names and the equivalent divide/square-root
  normalizer timing optimization.
- Build flag and destination-path tracking for runtime and simulator rebuilds.

The standalone nextpnr routing/database patches and frame-assembly experiments
are archived outside the checkout. Shared RTL export, Yosys frontend checks,
LiteDRAM generation and board simulation targets remain available.

## Build and simulation

Use a fresh out-of-tree RV32 build and the toolchain revision in `VERSION`:

```sh
mkdir -p build_ypcb32
cd build_ypcb32
../configure --xlen=32 --memory-size=2147483648 --tooldir="$HOME/tools" --osversion=ubuntu/focal
./ci/ypcb_env.sh setup
./ci/ypcb_env.sh install-toolchain
./ci/ypcb_env.sh smoke
./ci/ypcb_env.sh smoke-xrt
```

The native Linux wrapper uses a uv environment and runs an immutable copy of
itself during reconfiguration. Install a C++ compiler, make, ccache, uv,
pkg-config and UUID development headers/libraries before setup.
The uv environment pins CMake below 4 for Ramulator's declared policy support.
Native smoke builds use a separate Ramulator build directory and hash-checked
patches for its pinned dependencies. The fmt 9 patch keeps its argument mapper
alive, retaining `-Werror` on modern GCC; yaml-cpp 0.7 explicitly includes the
integer-type header it uses. These are temporary dependency patches; replace
them by updating Ramulator's spdlog/fmt and yaml-cpp pins and qualifying the
rebuilt library. The upstream fmt diagnostic is
tracked in [fmt issue 3415](https://github.com/fmtlib/fmt/issues/3415).
`open-setup` stages pinned Migen, LiteX, LiteDRAM and PCIe generator references;
it does not run the archived nextpnr implementation flow.

Run the generated YPCB Makefile for board component tests. The shell simulation
exercises the AFU and command processor with memory/PHY oracles. A DDR host test
checks training software against modeled CSRs; it is not physical training.
Keep application, dispatcher and backend configuration identical.

The Vivado runner accepts `--reuse-synthesis <completed-run>` with a fresh
output directory to retry implementation. It requires a successful synthesis
receipt, verifies the frozen inputs, and rejects changes to HDL, pin constraints,
source order, defines or synthesis Tcl before copying the checkpoint. Only the
implementation stages then run.

The OpenTPU YPCB reference informed the mailbox constraint review: resolve
hierarchical registers, verify synchronizer attributes and direct stage wiring,
and time every held-payload receiver, including the write discriminator. The
Vortex bounds use its own clock periods and two-stage handshake.

OpenTPU also provides a 16 KiB VexRiscv calibration firmware design. It is a
useful reference if measured JTAG transaction latency prevents host-driven DDR
training; the current host algorithm performs 6,942 probes. Any adaptation must
retain CH1-only 2 GiB operation and use Vortex's actual PHY/CSR map. DDR readback
and ECC checks must precede interpretation of a failed kernel as a GPU defect.
Qualify command timing separately from the total training deadline: the current
probe performs nine host MMIO calls between ACTIVATE and PRECHARGE. The configured
MT41K256M8 reference specifies maximum `tRAS = 9 * tREFI`, or 70.2 microseconds
at or below 85 C. Compare measured transport latency against that bound before
host-driven training. The timing source is the
[Micron DDR3L datasheet, archived copy](https://dtsheet.com/doc/1384516/2gb--x4--x8--x16-ddr3l-sdram).

The Linux backend uses an unbound `10ee:0480` endpoint with a 64 KiB BAR0.
Select it with `VORTEX_DRIVER=ypcb VORTEX_YPCB_BDF=0000:bb:dd.f`.
Its DDR shadow command arena must remain reserved in the generic allocator.
The backend trains DDR, scrubs ECC, resets the AFU and checks the CP counter
before allowing workload submission.

## Previous results

The previous two-channel PCIe image is in
`build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/`. It passed offline internal
timing, routing and bitstream integrity checks. Its SHA-256 is
`487df66a6dc00caf73b39d3f5d8473212bb80e549685afc4da66278a88d9fd90`.
The saved October 18 check in
`build_ypcb_vivado32/hardware-check-20261018/` passed SRAM configuration and
JTAG INIT/DONE/IDCODE checks. It ran no GPU kernel or DDR workload.
These results do not qualify an updated RTL design.

## Remaining qualification

The independent JTAG control path, shared host arbitration, CH1 memory map,
runtime capacity and kernel placement are implemented. Board ABI 2 identifies
this layout. Set `VORTEX_YPCB_INTERFACE=jtag` to use the local Vivado MMIO
server, or `pcie` for the Linux BAR transport. A runtime lock keeps one host
interface in control of the shared staging windows.

The initial shell prototype passed memory, demo and SGEMM over both interfaces,
including JTAG with the PCIe clock stopped. Requalify the final ABI 2 image. Include full AFU simulation, byte-exact DMA, memory ordering tests,
matching SimX timing checks, and both runtime interfaces.

Before normal board operation, review CDC/reset crossings, external DDR timing,
DDR reset output standards and the configuration-bank electrical profile.
After implementation, check routed timing, DRC, report coverage and bitstream
integrity. Physical qualification then requires CH1 training, address/data
patterns and kernel runs with observable results.

The generated `ci/ypcb_run_fpga.py` runner requires the exact image run,
configured build, Vivado binary directory, CRC checker and shared hardware lease.
`--stage probe` loads SRAM and measures the native JTAG MMIO path;
`--stage kernels` additionally runs the memory-map test, `demo -n64` and
`sgemm -n16`, requiring verified results, nonzero GPU instruction/cycle counters
and clean CH1 ECC. It retains logs and artifact hashes and reaps its owned
process groups before releasing the lease. It contains no flash-write operation.
