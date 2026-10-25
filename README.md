<p align="center">
  <img src="docs/assets/img/vortex_framework_stack.svg" alt="Vortex framework stack" width="100%">
</p>

# Vortex GPGPU

Vortex is a full-stack open-source RISC-V GPGPU. Vortex supports multiple **backend drivers**, including our C++ simulator (simx), an RTL simulator, and physical Xilinx and Altera FPGAs-- all controlled by a single driver script. The chosen driver determines the corresponding code invoked to run Vortex. Generally, developers will prototype their intended design in simx, before completing going forward with an RTL implementation. Alternatively, you can get up and running by selecting a driver of your choice and running a demo program.

## Website
Vortex news can be found on its [website](https://vortexgpgpu.github.io/index.html)

## Citation
```
@inproceedings{10.1145/3466752.3480128,
	author = {Tine, Blaise and Yalamarthy, Krishna Praveen and Elsabbagh, Fares and Hyesoon, Kim},
	title = {Vortex: Extending the RISC-V ISA for GPGPU and 3D-Graphics},
	year = {2021},
	isbn = {9781450385572},
	publisher = {Association for Computing Machinery},
	address = {New York, NY, USA},
	url = {https://doi.org/10.1145/3466752.3480128},
	doi = {10.1145/3466752.3480128},
	abstract = {The importance of open-source hardware and software has been increasing. However, despite GPUs being one of the more popular accelerators across various applications, there is very little open-source GPU infrastructure in the public domain. We argue that one of the reasons for the lack of open-source infrastructure for GPUs is rooted in the complexity of their ISA and software stacks. In this work, we first propose an ISA extension to RISC-V that supports GPGPUs and graphics. The main goal of the ISA extension proposal is to minimize the ISA changes so that the corresponding changes to the open-source ecosystem are also minimal, which makes for a sustainable development ecosystem. To demonstrate the feasibility of the minimally extended RISC-V ISA, we implemented the complete software and hardware stacks of Vortex on FPGA. Vortex is a PCIe-based soft GPU that supports OpenCL and OpenGL. Vortex can be used in a variety of applications, including machine learning, graph analytics, and graphics rendering. Vortex can scale up to 32 cores on an Altera Stratix 10 FPGA, delivering a peak performance of 25.6 GFlops at 200 Mhz.},
	booktitle = {MICRO-54: 54th Annual IEEE/ACM International Symposium on Microarchitecture},
	pages = {754–766},
	numpages = {13},
	keywords = {reconfigurable computing, memory systems., computer graphics},
	location = {Virtual Event, Greece},
	series = {MICRO '21}
}
```

## Specifications

- Support RISC-V RV32IMAFC and RV64IMAFDC

- Microarchitecture:
    - configurable number of cores, warps, and threads.
    - configurable number of ALU, FPU, LSU, and SFU units per core.
    - graphics fixed-function pipeline (rasterizer, texture units, output mergers).
    - hardware ray-tracing unit (BVH traversal, ray-box and ray-triangle intersection).
    - tensor cores with WGMMA and 2:4 structured sparsity support.
    - hardware-accelerated command processor and kernel management unit.
    - configurable pipeline issue width.
    - optional local memory, L1, L2, and L3 caches.
- Software:
    - OpenCL 1.2
    - Vulkan
    - HIP
- Supported FPGAs:
    - Altera Arria 10
    - Altera Stratix 10
    - Xilinx Alveo U50, U55C, U250, U280
    - Xilinx Alveo V80 (Versal, via the SLASH platform — see [setup guide](docs/xilinx_slash_setup.md))
    - Xilinx Versal VCK5000

## Directory structure

- `doc`: [Documentation](docs/index.md).
- `hw`: Hardware sources.
- `sw`: Software sources (kernel, runtime, and drivers).
- `sim`: Simulators repository.
- `tests`: Tests repository.
- `examples`: [Basic arithmetic, GEMM, convolution and pooling](examples/README.md).
- `ci`: Continuous integration scripts.
- `miscs`: Miscellaneous resources.
- `VX_config.toml` / `VX_types.toml`: Hardware configuration system.

## YPCB saved bitstreams (2026-10-25)

**The recommended current 4 GiB image passed all 57 JTAG qualification commands
and all 303 completion-audit checks.** Its JTAG suite has no pending or failed
cases. The incomplete or failed results below describe archived development
images and do not leave those same tests outstanding on the current image.
Permanent programming, readback and JTAG-triggered flash boot also passed, as
recorded below. Physical power-on boot and PCIe execution remain unverified.

This inventory snapshot contains **22 distinct full-board bitstreams**. Duplicate
copies and later flash/runtime staging copies do not count as new images. Failed
attempts that produced no bitstream and four small synthetic test fixtures are
excluded. These paths are relative
to the checkout and refer to local build artifacts, not files distributed by Git.
The [complete path/hash inventory](build_ypcb_4gb32/bitstream-inventory-20261025-v1.json)
and [per-image JTAG evidence](build_ypcb_4gb32/bitstream-readme-evidence-20261025-v1.json)
record the exact identities behind this table. SHA-256 values below are prefixes.

**Not every saved image has a complete JTAG runtime pass.** Twenty images have
matching JTAG records: 16 passed their recorded runtime suites, one has partial
DXA validation, two have SRAM/MMIO checks only, and one failed its DDR memory
test. Two images have no matching JTAG run recorded. All 13 incremental compute
stages (00–12) and the final 4 GiB image were loaded through JTAG; stage 11's
partial feature run does not establish completion of its full intermediate suite.
A DDR-test failure or SRAM-only result does not diagnose a GPU defect.

| Image / added feature | Local bitstream | SHA-256 prefix | Recorded JTAG result |
| --- | --- | --- | --- |
| Early Vivado prototype | [`.bit`](build_ypcb32/vivado-preparation-20261013/vortex-synthesis-v1/vortex_ypcb.bit) | `b7f522fec3b0` | No matching JTAG test record found |
| Initial YPCB image | [`.bit`](build_ypcb_vivado32/ypcb-vivado-bitstream-20261014/vortex_ypcb.bit) | `487df66a6dc0` | [SRAM INIT/DONE/IDCODE only; GPU/DDR untested](build_ypcb_vivado32/hardware-check-20261018/manifest.json) |
| Native JTAG shell v16 | [`.bit`](build_ypcb_native32/ch1-jtag-pcie-20261020-v16-finalize/vortex_ypcb.bit) | `3cab81128e26` | [SRAM and MMIO pass; DDR/kernels untested](build_ypcb_native32/fpga-probe-20261020-v1/manifest.json) |
| Native DDR diagnostic v18 | [`.bit`](build_ypcb_native32/ch1-jtag-pcie-20261020-v18-finalize/vortex_ypcb.bit) | `f5bd03e294c7` | [JTAG-loaded; DDR memory test failed; GPU runtime unqualified](build_ypcb_native32/fpga-kernels-20261020-v1/manifest.json) |
| CH1 scalar / basic examples | [`.bit`](build_ypcb_wl32/wl-ch1-jtag-pcie-20261020-v3/vortex_ypcb.bit) | `7590d5487b79` | [Memory, scalar kernels and all five examples pass (10 commands)](build_ypcb_wl32/completion-audit-20261020-v1.json) |
| TCU FP16/INT8 baseline | [`.bit`](build_ypcb_tcu32/tcu-ch1-jtag-pcie-20261021-v3/vortex_ypcb.bit) | `3b9decedf8af` | [Memory, examples, FP16 and INT8 square/rectangular pass (14 commands)](build_ypcb_tcu32/completion-audit-20261021-v3.json) |
| Earlier full Blackwell-like image | [`.bit`](build_ypcb_blackwell32/next-intmul-source/build_ypcb_blackwell32/blackwell-cache-register-replicated-20261022-v7/vortex_ypcb.bit) | `3c3ac665c840` | [53 commands pass; detached-helper cleanup recovery separately audited](build_ypcb_blackwell32/next-intmul-source/build_ypcb_blackwell32/completion-audit-20261023-v10-cleanup-recovery.json) |
| Reset-fixed intermediate image | [`.bit`](build_ypcb_blackwell_fixed32/blackwell-reset-fixed-ch1-jtag-pcie-20261023-v1/vortex_ypcb.bit) | `75c0e1a2d434` | [Offline signoff only; no matching JTAG run](build_ypcb_blackwell_fixed32/cad-monitor-20261023-v2/offline-image-completion-audit.json) |
| Stage 00: TCU baseline: FP16/BF16 and INT8/UINT8 | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage00-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `de27d1a12044` | [18-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage00-20261023-v1/completion-audit.json) |
| Stage 01: Eight warps | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage01-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `13c1bd3fbca7` | [18-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage01-20261023-v1/completion-audit.json) |
| Stage 02: L2 cache | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage02-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `d5c9be04e6b3` | [18-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage02-20261023-v1/completion-audit.json) |
| Stage 03: A-extension atomics | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage03-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `7181a8a29042` | [21-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage03-20261023-v1/completion-audit.json) |
| Stage 04: Native Zacas CAS | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage04-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `58fd1e2c28b9` | [22-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage04-20261023-v1/completion-audit.json) |
| Stage 05: TF32 | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage05-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `a853331891a7` | [24-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage05-20261023-v1/completion-audit.json) |
| Stage 06: FP8/BF8 | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage06-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `262dc60b1ed5` | [28-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage06-20261023-v1/completion-audit.json) |
| Stage 07: MXFP8/MXBF8 | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage07-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `7ad930aac224` | [32-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage07-20261023-v1/completion-audit.json) |
| Stage 08: MXFP4 | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage08-ch1-jtag-pcie-image-20261023-v1/vortex_ypcb.bit) | `501cd72d058b` | [34-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage08-20261023-v1/completion-audit.json) |
| Stage 09: NVFP4 (repaired build) | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage09-rebuilt-cdc-repair-20261024-v1/vortex_ypcb.bit) | `523e6e8a221b` | [36-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage09-20261023-v1/completion-audit.json) |
| Stage 10: Structured sparsity | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage10-rebuilt-ch1-image-20261024-v1/vortex_ypcb.bit) | `c15cf56ae81f` | [42-command stage suite passes](build_ypcb_blackwell_fixed32/fpga-incremental-stage10-20261024-v2/completion-audit.json) |
| Stage 11: DXA asynchronous copies / multicast | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage11-rebuilt-ch1-image-20261024-v1/vortex_ypcb.bit) | `1fb754652325` | [11 commands / six DXA cases pass; full 48-command suite intentionally stopped](build_ypcb_blackwell_fixed32/fpga-incremental-stage11-20261024-v1/feature-completion-audit-20261025-v1.json) |
| Stage 12: WGMMA; full 2 GiB configuration | [`.bit`](build_ypcb_blackwell_fixed32/incremental-stage12-rebuilt-ch1-image-20261024-v1/vortex_ypcb.bit) | `7e3207174fd2` | [Full 55-command suite and 292-check audit pass; 2 GiB ECC fallback](build_ypcb_blackwell_fixed32/fpga-incremental-stage12-20261024-v1/completion-audit.json) |
| Final full configuration, 4 GiB | [`.bit`](build_ypcb_4gb32/dual-4gib-image-20261025-v2/vortex_ypcb.bit) | `d6ad50f70469` | [Full 57-command suite and 303-check audit pass; selected permanent image](build_ypcb_4gb32/fpga-4gib-full57-20261025-v2/completion-audit.json) |

The initial YPCB image also has an identical copy at
[`build_ypcb_vivado32/vivado-preparation-20261014/impl-v4b/vortex_ypcb.bit`](build_ypcb_vivado32/vivado-preparation-20261014/impl-v4b/vortex_ypcb.bit).
The distinct-image count includes that SHA-256 only once. The incremental
feature plan is documented in the
[incremental compute proposal](docs/proposals/ypcb_incremental_compute_proposal.md).

### Permanently programmed Vortex image

The full-feature 4 GiB image
[`dual-4gib-image-20261025-v2/vortex_ypcb.bit`](build_ypcb_4gb32/dual-4gib-image-20261025-v2/vortex_ypcb.bit)
was **permanently programmed and verified on 2026-10-25**, following explicit
authorization for this exact image. Its SHA-256 is:

```text
d6ad50f70469d6cf3d25f8ca0f8dee1875988b0ac07bec0fa88b8cd0ff06dfb3
```

It retains the full 125 MHz compute profile and both JTAG/PCIe interfaces,
provides 2 GiB CH0 without ECC plus 2 GiB CH1 with ECC, and passed the complete
57-command physical suite, full-capacity memory BIST and 303-check audit.
CH0's former ECC lane replaces its unusable data lane. Application allocations
still reserve runtime staging and hart-stack regions within the 4 GiB map.

Keep the
[stage 12 full 2 GiB ECC image](build_ypcb_blackwell_fixed32/incremental-stage12-rebuilt-ch1-image-20261024-v1/vortex_ypcb.bit)
as the fallback, or choose it when ECC on all enabled memory matters more than
capacity. It passed all 55 commands and a 292-check audit. Its SHA-256 is:

```text
7e3207174fd2bf266b12ba6aa2ca5e48df36727681856b7227666ff2d4f7a734
```

The 4 GiB flash operation passed native erase/program verification, a separate
verify-only pass, a full 64 MiB NOR readback, and an exact comparison of all
18,735,004 configuration-payload bytes with the approved image. Booting from
flash through JTAG passed INIT/DONE, Vortex ABI 5 and boot-status checks, with no
fallback, ID or CRC error. The flash-booted image then passed eight full-capacity
DDR BIST passes, the scalar GPU demo, and both FP16 and INT8 tensor launches
twice, with clean CH1 ECC. The final audit passes all 33 checks; hardware helpers
stopped and both hardware leases were released.

Flash evidence:

- [Operation manifest](build_ypcb_4gb32/flash-4gib-permanent-20261025-v1/manifest.json)
- [Independent 33-check audit](build_ypcb_4gb32/flash-4gib-permanent-20261025-v1/completion-audit.json)
- [Successful service exit](build_ypcb_4gb32/flash-4gib-permanent-20261025-v1/unit-exit.json)
- [Complete programmed-flash readback](build_ypcb_4gb32/flash-4gib-permanent-20261025-v1/programmed-flash.bin)

The previous 64 MiB flash contents were saved in two matching reads:
[backup A](build_ypcb_4gb32/flash-4gib-permanent-20261025-v1/previous-flash-a.bin)
and [backup B](build_ypcb_4gb32/flash-4gib-permanent-20261025-v1/previous-flash-b.bin),
SHA-256 `311059bc9ba1c37608c8cad515c8e88dcd1306b03c7be002c37982c9efaf847d`.
Bytes from `0x01200000` to the end of flash were verified unchanged.

**A physical power-off/on cold boot and physical PCIe execution remain untested.**
The verified JTAG-triggered flash boot is a warm reconfiguration, not a power
cycle. After powering the card fully off and on, repeat DDR calibration,
memory and kernel checks without loading another SRAM image. The 2 GiB fallback
remains SRAM/JTAG-qualified; it was not written by this flash operation. JTAG
configuration and configuration-memory boot are separate paths in the
[AMD 7-series configuration guide (UG470)](https://docs.amd.com/v/u/en-US/ug470_7Series_Config).
The archived intermediate images remain available for diagnosis; their older
incomplete suites do not leave cases outstanding in the current image's JTAG suite.

### macOS and Chestnut tests

The [Mac/Chestnut guide](docs/mac_vortex.md) and
[`ci/mac_vortex.sh`](ci/mac_vortex.sh) run directly from this Git checkout against
the already flashed image. The matched GPU kernels, headers, test settings and
references are tracked under [`runtime/ypcb4g/`](runtime/ypcb4g/); host sources
are read from the repository and SoftFloat from its pinned Git submodule.

```bash
git submodule update --init third_party/softfloat
bash ci/mac_vortex.sh preflight
VORTEX_MAC_OUT="$PWD/build/mac-native" bash ci/mac_vortex.sh build
# Power the FPGA card fully off and on before the cold-boot run.
bash ci/mac_vortex.sh full --native "$PWD/build/mac-native/native" --cold-boot
```

`quick`, `memory` and `identity` stages are also available. Full runs all 53
application cases and the raw physical-memory probe; `--cold-boot` adds eight
full-capacity native BIST passes before normal initialization. Native host code
is rebuilt for the Mac, while GPU binaries and numerical validators are preserved.
Logs and manifests distinguish preflight, identity, numerical tests, ECC and
cleanup. **Actual macOS/Chestnut PCIe and physical cold-boot qualification remain
for the Mac run.** See the guide for native Python/libusb setup.


## Quick Start
If you are interested in a stable release of Vortex, you can download the latest release [here](https://github.com/vortexgpgpu/vortex/releases/latest). Otherwise, you can pull the most recent, but (potentially) unstable version as shown below. The following steps demonstrate how to build and run Vortex with the default driver: SimX. If you are interested in a different backend, look [here](docs/simulation.md).

### Supported OS Platforms
- Ubuntu 22.04
- Centos 7
### Toolchain Dependencies
The following dependencies will be fetched prebuilt by `toolchain_install.sh`.
- [POCL](http://portablecl.org/)
- [LLVM](https://llvm.org/)
- [RISCV-GNU-TOOLCHAIN](https://github.com/riscv-collab/riscv-gnu-toolchain)
- [Verilator](https://www.veripool.org/verilator)
- [cvfpu](https://github.com/openhwgroup/cvfpu.git)
- [SoftFloat](https://github.com/ucb-bar/berkeley-softfloat-3.git)
- [Ramulator](https://github.com/CMU-SAFARI/ramulator.git)
- [Yosys](https://github.com/YosysHQ/yosys)
- [Sv2v](https://github.com/zachjs/sv2v)
- [Mesa](https://www.mesa3d.org/)
- [chipStar](https://github.com/CHIP-Star/chipStar)
### Install Vortex codebase
```sh
	git clone --depth=1 --recursive https://github.com/vortexgpgpu/vortex.git
	cd vortex
```
### Install system dependencies
```sh
# ensure dependent libraries are present
sudo ./ci/install_dependencies.sh
```
### Configure your build folder
```sh
    mkdir build
    cd build
    # for 32bit
    ../configure --xlen=32 --tooldir=$HOME/tools
    # for 64bit
    ../configure --xlen=64 --tooldir=$HOME/tools
```
### Install prebuilt toolchain
```sh
   ./ci/toolchain_install.sh
```

### Building and installing Vortex
```sh
make -s
make install
export VORTEX_PATH=$(pwd)/install
export PKG_CONFIG_PATH=$VORTEX_PATH/lib/pkgconfig:$PKG_CONFIG_PATH
```
`make install` lays out a sysroot under `$VORTEX_PATH` containing the
public headers, libraries, and `vortex-runtime.pc` / `vortex-kernel.pc`
pkg-config files. Downstream tools (mesa-vortex, pocl-vortex,
chipstar) integrate with Vortex exclusively through `$VORTEX_PATH` and
pkg-config — the same shape as the CUDA, ROCm and oneAPI SDKs. The
source tree (`$VORTEX_HOME`) and build tree (`$VORTEX_BUILD_DIR`) are
internal to Vortex and not exposed to consumers. Override the install
root with `../configure --prefix=<path>` or `--installdir=<path>` (default `<build>/install`).

### Quick demo running vecadd OpenCL kernel on 2 cores
```sh
./ci/blackbox.sh --cores=2 --app=vecadd
```

### Compiler Toolchain (VOLT)

Vortex's compiler toolchain is **[VOLT](https://github.com/vortexgpgpu/Volt)** (Vortex-Optimized Lightweight Toolchain), an LLVM-based SIMT compiler for the Vortex GPU. To build the toolchain locally instead of using the prebuilt one, follow the instructions in the [VOLT repo](https://github.com/vortexgpgpu/Volt). Its design is described in the [VOLT paper (CC '26)](https://dl.acm.org/doi/10.1145/3771775.3786275).

### Common Developer Tips
- Building Vortex 64-bit requires setting --xlen=64 configure option.
```sh
../configure --xlen=64 --tooldir=$HOME/tools
```
- No shell environment setup is required. `../configure` bakes the full
  toolchain layout (paths, XCONFIGS, every tool binary) into the build
  dir's `config.mk` and domain `common.mk` files. Make recipes invoke
  tools by absolute path (`$(VERILATOR_PATH)/bin/verilator` etc.), so
  multiple Vortex trees on the same machine can coexist without any
  `~/.bashrc` sourcing.
- Making changes to Makefiles in your source tree, editing `VX_config.toml` (or any `*.toml`), or adding new folders will require executing the "configure" script again without any options to get changes propagated to your build folder.
```sh
../configure
```
- Always make sure your build is up to date before running any test or app: re-run `../configure` from your build folder first. `configure` regenerates `<build>/sw/VX_config.h` and `<build>/hw/*.vh` from `VX_config.toml` (only when the toml is newer). The simulator and RTL `#include` this generated header, so a stale header makes them compile against old config values and silently diverge from the toml. `VX_config.toml` is the single source of truth — never paper over a divergence by hardcoding `-DVX_CFG_*` flags in a Makefile; re-`configure` instead.
- To debug the GPU, the simulation can generate a runtime trace for analysis. See /docs/debugging.md for more information.
```sh
./ci/blackbox.sh --app=demo --debug=3
```
- Running the CI suite locally: the test catalog lives in `ci/testcases/` and runs
  through pytest via the `regression.sh` wrapper (from your build folder). See
  [docs/continuous_integration.md](docs/continuous_integration.md) for details.
```sh
./ci/regression.sh --all               # full catalog
./ci/regression.sh --test regression   # one category
```
- For additional information, check out the [documentation](docs/index.md)

