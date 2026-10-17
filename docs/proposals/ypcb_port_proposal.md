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
`open-setup` stages pinned Migen, LiteX, LiteDRAM and PCIe generator references;
it does not run the archived nextpnr implementation flow.

Run the generated YPCB Makefile for board component tests. The shell simulation
exercises the AFU and command processor with memory/PHY oracles. A DDR host test
checks training software against modeled CSRs; it is not physical training.
Keep application, dispatcher and backend configuration identical.

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
