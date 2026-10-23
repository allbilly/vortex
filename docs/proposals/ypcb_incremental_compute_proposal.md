# Incremental YPCB compute qualification

The final target remains `ypcb_blackwell_like`: all eleven selected tensor formats, structured sparsity, DXA, WGMMA, A/Zacas, eight warps, L2, 125 MHz, CH1 2 GiB ECC, and both host interfaces. Intermediate images do not establish completion of the full 55-command physical suite.

The saved `ypcb_tcu` baseline supports FP16/BF16 and INT8/U8 using four warps. The full profile changes more than arithmetic: it also changes warp-dependent queues, cache hierarchy and write policy, atomics/CAS request width, and asynchronous/cooperative engines. Separate these changes before attributing a routing regression to one format.

| Stage profile suffix | Added configuration |
| --- | --- |
| `00_baseline` | Exact existing `ypcb_tcu` resolved machine |
| `01_warps8` | Eight warps |
| `02_l2` | L2, including its derived L1 write-policy/line-size changes |
| `03_atomics` | A extension |
| `04_zacas` | Native CAS |
| `05_tf32` | TF32 |
| `06_fp8` | FP8/BF8 |
| `07_mx8` | Block-scaled FP8/BF8 |
| `08_mxfp4` | FP4 datapath and MXFP4 together |
| `09_nvfp4` | NVFP4 |
| `10_sparse` | Structured sparsity |
| `11_dxa` | Asynchronous copies and multicast |
| `12_wgmma` | WGMMA; resolved values must equal the existing full profile |

Each profile inherits the previous stage. Use a distinct out-of-tree build per stage and re-run configure when a profile or inherited file changes. Keep the board, clock, threads, issue width, DSP choice and tensor latency constant. Never reuse runtime objects, applications or simulation models across incompatible stage configurations. Device kernels must link within the 2 GiB device window; preserve the configured startup address in their linker fingerprint.

First resolve and inspect the exact configuration delta, then run matching SimX and XRT functional checks and selected RTL elaboration. Use canonical testcase definitions for dependencies and app geometry. Do not invent a fixed latency or alter numerical, cycle, area or timing baselines. All tests run from the generated build tree.

Only after those checks pass, build the current stage's FPGA image and require complete routed timing/coverage/CDC/DRC reports, source/header/profile bindings, full CRC coverage and actual successful command receipts. Temporarily program SRAM under the shared JTAG lease and run the basic examples plus every applicable format/feature regression. Require clean ECC and owned-process/lease cleanup. Record the source commit, resolved configuration, bitstream hash, LUT/FF/BRAM/DSP usage, slack, elapsed time and numerical results. Stop at the first new failure and diagnose that delta before advancing.

Profile resolution and simulation can cover every rung. Whole-board builds should advance one rung at a time while isolating the first regression; do not launch all thirteen costly implementations together. The final accepted image uses the original full profile and must pass the complete 55-command physical suite. Preserve the earlier qualified images and every failed run separately.

The previous hard-LOC placement experiment produced a Vivado placement SIGSEGV, with no memory cap or CPU quota and no OOM-kill record. This is a separate tool/constraint issue; reducing feature count does not by itself explain or repair that crash. Do not carry those experimental hard FF/DSP locations into this baseline.

Example configuration from the checkout:

```sh
mkdir -p build_ypcb_inc00
cd build_ypcb_inc00
../configure --xlen=32 --memory-size=2147483648 --tooldir="$HOME/tools" --profile=ypcb_inc_00_baseline
```

Use the installed toolchain directory through `--tooldir` when it differs from that example. If host detection is unsupported, pass `--osversion` matching the already installed prebuilt archive flavor. This selects toolchain packaging metadata; it does not change the host distribution. A configured stage and a resolved-profile comparison are preparation evidence, not FPGA qualification.
