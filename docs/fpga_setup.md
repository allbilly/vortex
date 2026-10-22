# FPGA Startup and Configuration Guide

YPCB-00338-1P1 preparation and the remaining custom-platform work are tracked
in [the YPCB port proposal](proposals/ypcb_port_proposal.md). The Alveo build
instructions below do not produce a YPCB bitstream.

YPCB ABI 4 calibrates CH1's 2 GiB DDR3 with a local 100 MHz RV32I CPU. Export
the controller with the generated Makefile's `ddr-sources` target into a fresh
`DDR_OUT_DIR`; `ddr-host-config` binds the runtime to that firmware identity.
The controller uses the OpenTPU-derived WL PHY, with buffered 50 MHz input,
100 MHz control logic, clock-phase/per-bit calibration and native DDR traffic
checks. The primary LiteDRAM CPU configuration stays `None` to preserve external
Wishbone access. The local CPU is inside the existing `ddrctrl` CSR group.
See [the calibration design](proposals/ypcb_local_ddr_calibration_proposal.md).

The separate `ypcb_tcu` profile enables FP16-to-FP32 and INT8-to-INT32 tensor
arithmetic on one eight-thread core. Configure a fresh RV32, 2 GiB build with
`--profile=ypcb_tcu`; retain the scalar build separately. Its TFR pipeline uses
DSP inference and five stages consistently in simulation and synthesis.
See [the tensor-image plan](proposals/ypcb_tcu_proposal.md). Profile changes,
including inherited profiles, require `configure` so generated headers and
compiler flags describe the same machine. Unchanged generated contents retain
their timestamps. Existing scalar hardware results do not qualify this image.

Isolated tensor timing checks must derive `N` from `TCU_WG_FEDP_K` and `SF` from
`TCU_MX_MAX_SF`, as the core does. Sparsity can increase the scale-slot count
without increasing the dot-product width. Verify the elaborated parameters,
clock period and constraints before comparing results. Inspect DSP48 `MREG`
and `PREG` after synthesis and again after routing: physical optimization can
move an inferred product register back into fabric. A `use_dsp` annotation or
register depth in the source does not establish the final primitive mapping.

Optional extensions also need their packages and module search paths in both
the standalone export and board model. DXA requires `hw/rtl/dxa` and
`VX_dxa_pkg.sv`; its types import the core package. `gen_sources.sh` retains
the explicit package argument order before packages discovered through include
directories and emits each source once. Source export alone does not elaborate
imports or parameterized interfaces. Check the generated file list with the
selected configuration before synthesis; `ci/test_gen_sources_order.py` covers
original, copied and preprocessed lists with an interface parameter override.

The JTAG AXI core has sixteen entries in both transaction queues. Software
batches the sixteen PIO data-window words into distinct AXI Lite transactions,
then executes them with [AMD's `run_hw_axi -queue`](https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/run_hw_axi).
PIO timeouts bound each submitted hardware command. A complete application has
its own deadline in `ci/ypcb_run_fpga.py`. Run the generated `tests/ypcb/selfcal`
firmware/CPU checks, `tests/ypcb/wl_selfcal` traffic/report checks and
`ci/test_ypcb_jtag.py` before hardware use. Those checks
use PHY or transport oracles; physical memory and GPU results remain separate.

The YPCB AXI and Wishbone crossing generators explicitly select LiteX's
`vivado` toolchain when exporting RTL. `XilinxPlatform` defaults to ISE;
its attribute translation omits Vivado's `ASYNC_REG`, `mr_ff`, and
`ars_ff1`/`ars_ff2` metadata. The FIFO logic still simulates correctly, but
Vivado can fail to preserve and place its synchronizers correctly.
Regenerate both crossings and run the generated Makefile's `cdc-test` and
`wb-cdc-test` targets when changing their exporter.

Attributes and timing exceptions serve different purposes. Preserve the
synchronizer attributes, and load constraints that bound Gray-pointer delay
and skew while excluding the appropriate asynchronous reset checks. A broad
asynchronous clock group overrides maximum-delay constraints, so it cannot
replace bounded FIFO crossing constraints; see
[AMD UG903](https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/Constraining-Asynchronous-Signals).
The YPCB [Vivado CDC constraints](../hw/syn/xilinx/ypcb/vivado_cdc.tcl)
check the synthesized Gray-pointer drivers before applying their delay and
skew budgets. DDR external I/O timing still needs its own board and memory
delay budget.

Review status and error sidebands separately from the data mailbox. PCIe error
flags are sticky, independent bits; YPCB crosses each through two `ASYNC_REG`
stages before the board-clock status register consumes it. The constraints
require the actual source, both receiving stages, distinct source/destination
clocks and direct wiring without a bypass. Only source-to-first-stage paths
are excluded; settling paths between stages retain ordinary timing.
The sticky source bit may also feed its own input logic. Follow that logic to
the capture registers and compare their clocks when checking for a bypass.

The routed YPCB bus-skew report has 14 design Gray buses (ten AXI and four CSR),
eight JTAG AXI IP constraints and four debug-hub IP constraints. The report gate
checks each group separately, verifies the three-bit design endpoint sets and
unique pointer groups, and requires passing results for all vendor constraints.
Summary and detailed IDs, endpoint counts, requirements and slack must agree;
truncated or unknown groups fail qualification.

The PCIe PIPE clock mux uses BUFGCTRL's glitchless selection mode. The
rate-change logic waits for PHY completion signals and its state machine;
it permits variable clock switching latency. In this mode, missing setup or
hold on an `S` input can delay switching without creating a short clock
pulse; `CE` timing still matters. See
[AMD UG953](https://docs.amd.com/r/en-US/ug953-vivado-7series-libraries/BUFGCTRL).
The [PCIe clock constraint](../hw/syn/xilinx/ypcb/vivado_pcie_clock.tcl)
checks constant enables, inactive IGNORE inputs, complementary selection
from one register, and both clock periods before excluding the two selection
pins. Requalify those checks if the clock wrapper changes.
Run this review after `opt_design`: Vivado absorbs an external inverter into
the primitive's programmable inversion attribute during optimization. The
unoptimized synthesized netlist can therefore have a LUT1 at S0 while the
optimized netlist has one shared selector register and inverted S0 polarity.

For a low-memory run, set both `general.maxThreads` and `synth.maxThreads`
to the chosen worker count. They are independent limits; changing only the
general setting can leave synthesis using several worker processes. Run large
simulation compilations and implementation stages sequentially.

The YPCB Vivado builder defaults to the host CPU count, capped at eight workers.
Use `build_vivado.py --threads=1` to reduce it. The input receipt records the
selected count, and each stage prints both effective Vivado limits. Native
simulation builds use `THREADS`, defaulting to the host CPU count.

Use `synth_ip` only in the non-project flow, initialized with `set_part`.
A disk-backed `create_project` requires `create_ip_run` and `launch_runs`;
mixing these flows produces a critical warning even if synthesis continues.
See [AMD UG896](https://docs.amd.com/r/2025.1-English/ug896-vivado-ip/Scripting-Examples).

LiteX's standalone CDC exports include wall-clock banner timestamps. The YPCB
checkpoint-reuse check permits differences only in those two known comment lines
of its AXI and Wishbone CDC exports, verifies every remaining byte, and retains
the exact compiled files. Both regenerated and retained hashes are recorded.
HDL, attributes, pins, source order, defines and synthesis Tcl remain strict gates.

Consecutive post-route `phys_opt_design` passes maintain routing. Avoid a full
`route_design` after every pass, which can undo timing improvements. Save a
checkpoint after initial routing and each repair pass. The final candidate must
still pass all timing, route, DRC and CDC gates. See
[AMD UG904](https://docs.amd.com/r/en-US/ug904-vivado-implementation/Physical-Optimization).

When running Vivado in a transient systemd unit, save the actual command exit
code in its run directory before the wrapper exits. A successful unit can be
unloaded before a dependent observes its result. Preserve its log and
checkpoint; a missing unit alone cannot establish stage completion.
The hardware runner likewise requires the successful, uninterrupted exit receipt
from implementation or routed finalization before programming. Reports written
before bitstream generation do not establish that the producer finished.

If a producer disappears after saving a routed checkpoint, keep its missing
exit status unknown. `finalize_vivado.py --recover-abandoned-run` explicitly
checks that no producer still owns that run, requires successful synthesis,
verifies the frozen inputs and routed reports, and copies the checkpoint into
a fresh output directory. The native finalizer rechecks the part, clock, CH1
interface and all routed reports before generating a bitstream. Hardware use
still requires this new finalizer's own successful exit receipt.

## Gaining Access to FPGA's with CRNCH
If you are associated with Georgia Tech (or related workshops) you can use CRNCH's server to gain remote access to FPGA's. Otherwise, you can skip to the Xilinx or Intel (Altera) synthesis steps below.

## What is CRNCH?

**C**enter for **R**esearch into **N**ovel **C**omputing **H**ierarchies

## What does CRNCH Offer?

**The Rogues Gallery (RG)**: new concept focused on developing our understanding of next-generation hardware with a focus on unorthodox and uncommon technologies. **RG** will acquire new and unique hardware (ie, the aforementioned “*rogues*”) from vendors, research labs, and startups and make this hardware available to students, faculty, and industry collaborators within a managed data center environment

## Why are the Rouges Important?

By exposing students and researchers to this set of unique hardware, we hope to foster cross-cutting discussions about hardware designs that will drive future *performance improvements in computing long after the Moore’s Law era of “cheap transistors” ends*. Specifically, the Rouges Gallery contains FPGA's which can be synthesized into Vortex hardware.

## How is the Rouges Gallery Funded?

Rogues Gallery testbed is primarily supported by the National Science Foundation (NSF) under NSF Award Number [#2016701](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2016701&HistoricalAwards=false)

## Rouges Gallery Documentation

You can read about RG in more detail on its official documentation [page](https://gt-crnch-rg.readthedocs.io/en/main/index.html#).

You can listen to a talk about RG [here](https://mediaspace.gatech.edu/media/Jeff%20Young%20-%20Rogues%20Gallery%20-%20CRNCH%20Summit%202021/1_lqlgr0jj)

[CRNCH Summit 2023](https://github.com/gt-crnch/crnch-summit-2023/tree/main)

## Request Access for Rouges Gallery

You should use [this form](https://crnch-rg.cc.gatech.edu/request-rogues-gallery-access/) to request access to RG’s reconfigurable computing (vortex fpga) resources. You should receive an email with your ticket item being created. Once it gets processed, you should get an email confirmed your access has been granted. It might take some time to get processed.

## How to Access Rouges Gallery?
There are two methods of accessing CRNCH's Rouges Gallery
1) Web-based GUI: [rg-ood.crnch.gatech.edu](http://rg-ood.crnch.gatech.edu/)
2) SSH: `ssh <your-gt-username>@rg-login.crnch.gatech.edu`


## Where should I keep my files?
The CRNCH servers have a folder called `USERSCRATCH` which can be found in your home directory: `echo $HOME`. You should keep all your files in this folder since it is available across all the Rouges Gallery Nodes.

## **What Machines are Available in the Rogues Gallery?**

Complete list of machines can be found [here](https://gt-crnch-rg.readthedocs.io/en/main/general/rg-hardware.html). Furthermore, you can find detailed information about the FPGA hardware [here](https://gt-crnch-rg.readthedocs.io/en/main/reconfig/xilinx/xilinx-getting-started.html).

## Allocate an FPGA Node
Once you’ve connected to the CRNCH login node, you can use the Slurm scheduler to request an interactive job using `salloc`. This [page](https://gt-crnch-rg.readthedocs.io/en/main/general/using-slurm.html) explains why we use Slurm to request resources. Documentation for `salloc` can be found [here](https://gt-crnch-rg.readthedocs.io/en/main/general/using-slurm-examples.html). And here.


To request 16 cores and 64GB of RAM for 6 hours on flubber9, a fpga dev node:
```bash
salloc -p rg-fpga --nodes=1 --ntasks-per-node=16 --mem=64G --nodelist flubber1 --time=06:00:00
```
Synthesis for Xilinx Boards
----------------------
Once you are logged in, you will need to complete some first time configurations. If you are interested in the Intel (Altera) synthesis steps, scroll down below.

### Source Configuration Scripts
```
# From any directory
$ source /opt/xilinx/xrt/setup.sh
$ source /tools/reconfig/xilinx/Vitis/2023.1/settings64.sh
```

If you are using an apptainer,
```
$ export LD_LIBRARY_PATH=/opt/boost-1.66/lib/:/opt/openssl-1.1/lib/:$LD_LIBRARY_PATH
```


### Check Installed FPGA Platforms
`platforminfo -l` which tells us the correct name of the platform installed on the current fpga node. It should be used for the `PLATFORM` variable below. Otherwise, if there is an error then there was an issue with the previous two commands.

### Install Vortex Toolchain
The Xilinx synthesis process requires verilator to generate the bitstream. Eventually, you will need the whole toolchain to run the bitstream on the FPGA. Therefore, the Vortex toolchain and can be installed as follows. If you complete these steps properly, you should only need to complete them once and you can skip to `Activate Vortex Toolchain`
```
# Make a build directory from root and configure scripts for your environment
mkdir build && cd build && ../configure --tooldir=$HOME/tools

# Install the whole prebuilt toolchain
./ci/toolchain_install.sh
```

### Verify Toolchain Install
```
# Tools are invoked by absolute path from the Vortex Makefiles -- no
# shell env sourcing required. Confirm the install with:
$TOOLDIR/verilator/bin/verilator --version
```

### Build the FPGA Bitstream
The root directory contains the path `hw/syn/xilinx/xrt` which has the makefile used to generate the Vortex bitstream.

```
    $ cd hw/syn/xilinx/xrt
    $ PREFIX=test1 PLATFORM=xilinx_u50_gen3x16_xdma_5_202210_1 TARGET=hw NUM_CORES=1 make > build_u250_hw_1c.log 2>&1 &
```
Will run the synthesis under new build directory: BUILD_DIR := "\<PREFIX>\_\<PLATFORM>\_\<TARGET>"
The generated bitstream will be located under <BUILD_DIR>/bin/vortex_afu.xclbin

`NUM_CORES=N` here is a Makefile shorthand that selects a pre-defined cluster/core/L2 combination (see `hw/syn/xilinx/xrt/Makefile`); it expands to `-DVX_CFG_NUM_CLUSTERS=… -DVX_CFG_NUM_CORES=…` under the hood.

For long-running jobs, invocation of this makefile can be made of the following form:

`[CONFIGS=<vortex macros>] [PREFIX=<prefix directory name>] [NUM_CORES=<#>] TARGET=hw|hw_emu PLATFORM=<platform baseName> nohup make > <log filename> 2>&1 &`

For example:

```bash
CONFIGS="-DVX_CFG_L2_ENABLE -DVX_CFG_DCACHE_SIZE=8192" PREFIX=build_4c_u280 NUM_CORES=4 TARGET=hw PLATFORM=xilinx_u280_gen3x16_xdma_1_202310_1 nohup make > build_u250_hw_4c.log 2>&1 &
```

The build is complete when the bitstream file `vortex_afu.xclbin` exists in `<prefix directory name><platform baseName>hw|hw_emu/bin`.

### Enable Host Memory Access (required on hardware)

The Vortex AFU is driven by an on-chip **Command Processor (CP)** that fetches its
command ring and other control buffers directly from **host memory** over the
platform's host-memory bridge (CPU RAM exposed to the card, a.k.a. the "host bank"
or slave-bridge). The XRT runtime therefore allocates these buffers in host memory
at device open.

This bank is **disabled by default** and must be enabled once per card (it persists
until disabled or reboot). If it is not enabled, `vx_device_open` fails with:

```
[XRT] ERROR: Failed to allocate host memory buffer (Operation not permitted),
             make sure host bank is enabled (xrt-smi configure --host-mem)
```

Enable it (requires root). `sudo` resets `PATH`, so source the XRT environment
inside the elevated shell and pass the card's BDF (from `xrt-smi examine`):

```bash
sudo bash -c 'source /opt/xilinx/xrt/setup.sh && \
  xrt-smi configure --host-mem -d <BDF> --size 1G enable'
# e.g. -d 0000:3d:00.1
```

- `--size` must be a power of two and is bounded by available host CMA/huge-page
  memory. **256M** is sufficient for the CP ring and typical test buffers; **1G**
  is a safe default with headroom.
- This applies to the **`hw`** flow only. **`hw_emu`** models host memory in the
  emulator and needs no card configuration.

### Running a Program on Xilinx FPGA

The [blackbox.sh](./simulation.md) script within the build directory can be used to run a test with Vortex’s xrt driver using the following command:

`FPGA_BIN_DIR=<path to bitstream directory> TARGET=hw|hw_emu PLATFORM=<platform baseName> ./ci/blackbox.sh --driver=xrt --app=<test name>`

For example:

```FPGA_BIN_DIR=<realpath> hw/syn/xilinx/xrt/build_4c_u280_xilinx_u280_gen3x16_xdma_1_202211_1_hw/bin TARGET=hw PLATFORM=xilinx_u280_gen3x16_xdma_1_202211_1 ./ci/blackbox.sh --driver=xrt --app=demo```

Run sgemm on a U55C `hw` bitstream (host memory enabled per the section above), `-n` sets the matrix size:

```bash
FPGA_BIN_DIR=$(realpath hw/syn/xilinx/xrt/<build dir>/bin) TARGET=hw \
  ./ci/blackbox.sh --driver=xrt --app=sgemm --args="-n128"
```

The same command with `TARGET=hw_emu` against a `hw_emu` build runs it in emulation
(use a small `-n`, e.g. `-n16`, since emulation is slow).

Synthesis for Intel (Altera) Boards
----------------------

> **⚠️ Deprecated / unmaintained.** The Intel (Altera) OPAE flow is legacy and
> is no longer actively maintained or CI-tested. It targets discontinued Intel
> PAC cards (Arria 10 / Stratix 10) and depends on Intel-supplied platform files
> (e.g. `platform_if.vh` provided by the OPAE PIM at Quartus build time), so the
> steps below may be out of date and the build is not guaranteed to work on
> current toolchains. **The supported FPGA path is the Xilinx Alveo / XRT flow
> above.** The notes here are retained for reference only; please use Xilinx XRT
> for new work.

### OPAE Environment Setup


    $ source /opt/inteldevstack/init_env_user.sh
    $ export OPAE_HOME=/opt/opae/1.1.2
    $ export PATH=$OPAE_HOME/bin:$PATH
    $ export C_INCLUDE_PATH=$OPAE_HOME/include:$C_INCLUDE_PATH
    $ export LIBRARY_PATH=$OPAE_HOME/lib:$LIBRARY_PATH
    $ export LD_LIBRARY_PATH=$OPAE_HOME/lib:$LD_LIBRARY_PATH

### OPAE Build

The FPGA has to following configuration options:
- DEVICE_FAMILY=arria10 | stratix10
- NUM_CORES=#n

Command line:

    $ cd hw/syn/altera/opae
    $ PREFIX=test1 TARGET=fpga NUM_CORES=4 make

A new folder (ex: `test1_xxx_4c`) will be created and the build will start and take ~30-480 min to complete.
Setting TARGET=ase will build the project for simulation using Intel ASE.


### OPAE Build Configuration

Hardware parameters live in `VX_config.toml` and `VX_types.toml` at the repo root (auto-generated headers like `VX_config.vh` are produced under `build/` by `configure`). All build-time overrides use the `VX_CFG_*` namespace. For example:
- `VX_CFG_NUM_WARPS`:   Number of warps per core
- `VX_CFG_NUM_THREADS`: Number of threads per warp
- `PERF_ENABLE`: enable the use of all profile counters

You configure the synthesis build from the command line:

    $ CONFIGS="-DPERF_ENABLE -DVX_CFG_NUM_THREADS=8" make

### OPAE Build Progress

You could check the last 10 lines in the build log for possible errors until build completion.

    $ tail -n 10 <build_dir>/build.log

Check if the build is still running by looking for quartus_sh, quartus_syn, or quartus_fit programs.

    $ ps -u <username>

If the build fails and you need to restart it, clean up the build folder using the following command:

    $ make clean

The file `vortex_afu.gbs` should exist when the build is done:

    $ ls -lsa <build_dir>/synth/vortex_afu.gbs


### Signing the bitstream and Programming the FPGA

    $ cd <build_dir>
    $ PACSign PR -t UPDATE -H openssl_manager -i vortex_afu.gbs -o vortex_afu_unsigned_ssl.gbs
    $ fpgasupdate vortex_afu_unsigned_ssl.gbs

### Sample FPGA Run Test
Ensure you have the correct opae runtime for the FPGA target

```
$ TARGET=FPGA make -C runtime/opae
```

Run the [blackbox.sh](./simulation.md) from your Vortex build directory

```
$ TARGET=fpga ./ci/blackbox.sh --driver=opae --app=sgemm --args="-n128"
```

### FPGA sample test running OpenCL sgemm kernel

You can use the `blackbox.sh` script to run the following from your Vortex build directory

    $ TARGET=fpga ./ci/blackbox.sh --driver=opae --app=sgemm --args="-n128"

### Testing Vortex using OPAE with Intel ASE Simulation
Building ASE synthesis

```$ TARGET=asesim make -C runtime/opae```

Building ASE runtime

```$ TARGET=asesim make -C runtime/opae```

Running ASE simulation

```$ ASE_LOG=0 ASE_WORKDIR=<build_dir>/synth/work TARGET=asesim ./ci/blackbox.sh --driver=opae --app=sgemm --args="-n16"```
