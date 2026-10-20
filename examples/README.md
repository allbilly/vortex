# Basic Vortex operations

Small Python programs with readable C++ GPU kernels, deterministic float32
inputs and CPU reference checks. Python uses the public `vortex2.h` API through
`ctypes`; no additional Python packages are required. The computation runs on
the selected Vortex backend. CPU results are used only for verification.

| Program | Operation | Layout |
| --- | --- | --- |
| `simple_add.py` | Vector addition | Flat float32 arrays |
| `elementwise.py` | Add, subtract, multiply, divide, minimum, maximum, ReLU | Flat float32 arrays |
| `gemm.py` | `C = A @ B`, arbitrary rectangular sizes | Row-major `A[M,K]`, `B[K,N]`, `C[M,N]` |
| `conv.py` | 2D cross-correlation, stride and zero padding, batch 1 | Input CHW, weights OIHW, output CHW |
| `pooling.py` | Maximum, average and minimum pooling | CHW; average excludes padding |

The examples use finite inputs. Convolution and pooling use a square kernel,
floor output dimensions and `padding < kernel`. Defaults are deliberately
small; non-multiple vector and matrix sizes exercise the last partial warp.
These are scalar-FPU teaching kernels; they do not require tensor extensions.

## Build and run

First complete the [Vortex setup](../docs/install_vortex.md), including the
toolchain and third-party libraries. All commands below run from a configured
build directory. Re-run `configure` after updating the checkout so the new
`examples/` Makefiles are generated.

```bash
cd build
../configure --xlen=32 --tooldir="$HOME/tools"
make -j1 -C sw/kernel
make -j1 -C examples run
```

The last command builds the five device kernels and SimX runtime, then runs all
examples. Each operation reports `PASS` only after comparing every output
against its reference, and exits nonzero on a runtime or numerical failure.
Unwritten output elements retain a NaN sentinel and fail verification.

To build once and run individual operations:

```bash
make -j1 -C examples
make -j1 -C examples runtime DRIVER=simx
python3 ../examples/simple_add.py -n 37
python3 ../examples/elementwise.py --op all
python3 ../examples/gemm.py -m 5 -n 7 -k 3
python3 ../examples/conv.py --channels 2 --out-channels 3 --kernel 3 --padding 1
python3 ../examples/pooling.py --op all --kernel 3 --stride 2 --padding 1
```

Every script accepts `--help`, `--build PATH` and `--driver NAME`. SimX is the
default even if `VORTEX_DRIVER` was previously set. The build defaults to the
current directory when it contains `config.mk`, otherwise the checkout's
`build/`; `VORTEX_BUILD_DIR` or `--build` selects another configured tree.

Use identical `CONFIGS` for the kernel library, example kernels, runtime stub
and backend. If changing configuration, clean and rebuild `sw/kernel` before
building the examples; the example and runtime Makefiles track their own flag
changes. The configured XLEN selects the device toolchain and linker settings.

`make -j1 -C tests/examples run` checks the Python/C ABI against the actual
headers and runs independent known-output cases, including channel layout,
filter orientation, padding, average divisors and negative maximum pooling.

## YPCB build

The YPCB RV32 design uses CH1-only 2 GiB, the standard FPU and kernel entry
`0x40000000`. From its configured native build directory:

```bash
./ci/ypcb_env.sh configure
export CONFIGS="$(./ci/ypcb_env.sh exec make --no-print-directory -s -C hw/syn/xilinx/ypcb print-configs)"
export STARTUP_ADDR=0x40000000
./ci/ypcb_env.sh exec make -C sw/kernel clean
./ci/ypcb_env.sh exec make -j1 -C sw/kernel
./ci/ypcb_env.sh exec make -j1 -C examples run
```

These commands run SimX and use no FPGA connection. The October 20 WL/ABI4
image has passed physical CH1 calibration, memory, GPU demo and SGEMM through
JTAG. The five Python examples are still being checked; see
[current results](../progress.md) for their separate status. A successful
simulator run does not qualify DDR or hardware execution.

For an authorized board session, build `examples runtime DRIVER=ypcb` with
matching flags and use `--driver ypcb` with an already prepared JTAG or PCIe
runtime connection. Scripts use the existing backend; they do not program an
FPGA, start a JTAG server or replace the normal hardware ownership procedure. The
hardware qualification runner checks kernel address headers before taking the
JTAG lease; kernels must start at `0x40000000` and end by `0x50000000`.

## Source map

Each Python file creates inputs and calculates the reference. Its matching
`kernels/<name>/kernel.cpp` contains the complete GPU operation. `common.py`
handles the public runtime API, buffers, queue, launch and readback. The
64-byte argument layout is shared with `kernels/common.h`. Kernel builds reuse
the existing regression compiler/linker rules, including `.vxbin` metadata.
