# AGENTS Guide for Vortex GPGPU Development

This is the canonical entry point for **both human contributors and AI coding agents** working on Vortex. It captures the *rules* — invariants, conventions, and footguns — that every change should respect. Build/test/debug *recipes* live in the topic docs linked below.

---

## 1. Documentation Map

### Setup & build
- [docs/install_vortex.md](docs/install_vortex.md) — initial install + build setup
- [docs/building_toolchain.md](docs/building_toolchain.md) — building Verilator, RISC-V GNU, LLVM, compiler-rt, musl, POCL from source
- [docs/environment_setup.md](docs/environment_setup.md) — environment variables and toolchain layout
- [docs/fpga_setup.md](docs/fpga_setup.md) — FPGA target setup

### Codebase orientation
- [docs/codebase.md](docs/codebase.md) — repo file-tree map
- [docs/designs/microarchitecture.md](docs/designs/microarchitecture.md) — pipeline & cache architecture
- [docs/designs/cache_subsystem.md](docs/designs/cache_subsystem.md) — cache subsystem details
- [docs/hardware_library.md](docs/hardware_library.md) — `hw/rtl/libs/` reference

### Coding conventions
- [docs/coding_guidelines_cpp.md](docs/coding_guidelines_cpp.md) — C++ style
- [docs/coding_guidelines_verilog.md](docs/coding_guidelines_verilog.md) — Verilog/SystemVerilog style

### Simulation & test
- [docs/simulation.md](docs/simulation.md) — driver modes (simx, rtlsim, opae, xrt) and blackbox usage
- [docs/testing.md](docs/testing.md) — test and regression flow
- [docs/debugging.md](docs/debugging.md) — debug traces (`--debug`), VCD (`--vcd`), scope, trace_csv
- [docs/kernel_debugging.md](docs/kernel_debugging.md) — kernel debugging with GDB
- [docs/perfetto_analysis.md](docs/perfetto_analysis.md) — Perfetto trace and analysis
- [docs/synthesis_analysis.md](docs/synthesis_analysis.md) — synthesis/PPA analysis

### Process
- [CONTRIBUTING.md](CONTRIBUTING.md) — public fork/PR contribution flow
- [docs/bug_fixes.md](docs/bug_fixes.md) — bug-fix discipline (root-cause vs patch)
- [docs/continuous_integration.md](docs/continuous_integration.md) — CI pipeline
- [docs/proposals/](docs/proposals/) — design and migration proposals (drafts and in-progress)
- [docs/designs/](docs/designs/) — accepted designs (post-proposal, post-implementation)

---

## 2. Build & Toolchain Rules

See [docs/install_vortex.md](docs/install_vortex.md) for the full recipe. The non-negotiable rules:

- **Out-of-tree.** From the repo root:
  ```bash
  mkdir -p build && cd build
  ../configure --xlen=32 --tooldir=$HOME/tools   # or --xlen=64
  ./ci/toolchain_install.sh                # first time only
  make -s
  ```
- **Separate build dirs per major variant** (`build32/`, `build64/`, `build_fpga64/`, ...) to avoid config/tool contamination. Never reuse one build dir for incompatible configurations.
- **RTL exports must retain explicit package order and every selected extension's source paths.** Directory enumeration can put an importer before its prerequisites even when source export succeeds; require elaboration of the selected configuration before a long build. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Standalone FPGA RTL exports must select the target toolchain explicitly and load its timing constraints.** LiteX defaults to ISE, which omits Vivado CDC attributes even when the exported logic is unchanged; see [docs/fpga_setup.md](docs/fpga_setup.md).
- **Vivado worker limits are separate.** Set both `general.maxThreads` and `synth.maxThreads` when limiting host memory use; the general limit alone does not bound synthesis workers. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Isolated timing must use the selected geometry and actual primitive registers.** Derive tensor widths and scale-slot counts from the profile, and inspect DSP registers after physical optimization; source annotations and synthesis-time register absorption do not prove the routed pipeline mapping. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Match Vivado IP commands to the build mode.** `synth_ip` requires the non-project flow; a disk-backed project must use IP runs. Mixing the modes produces a critical warning even if synthesis continues. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Checkpoint reuse must validate generated RTL and synthesis configuration.** Wall-clock banner comments can change without changing hardware; handle only known metadata fields explicitly and preserve the exact compiled inputs. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Checkpoint post-route optimization before considering a reroute.** The optimizer maintains routing; a full reroute can undo timing gains. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Physical optimization success must include evidence that the operation ran.** Forced replication requires pre-route mode; selectively unrouting a routed checkpoint can leave post-route mode active and make Vivado skip optimization with exit zero. Verify replicas or driver loads before accepting the result. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Address fanout fixes must cover the actual driver primitives.** A LUT-only filter misses directly registered addresses; include eligible flip-flops and verify their added drivers or loads. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Transient build stages must preserve exit, interruption and timeout separately.** A timed-out child can handle termination and exit zero. Record each disposition in the run directory and require an explicit successful receipt; a missing unit or field cannot prove completion. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Hardware cleanup must include daemonized vendor children.** A debug helper can escape its launcher's process group. Track ownership per invocation, verify process identity before termination, and prove cleanup before releasing the run; never terminate helpers by name alone. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Dependency discovery must fail closed.** A failed or empty RTL file list can silently reuse an old simulation model. See [docs/testing.md](docs/testing.md).
- **`configure` generates a runnable tree** by copying and instantiating `ci/`, `runtime/`, `sim/`, and `tests/` into `build/`. For execution and test automation, *always* prefer the generated scripts/Makefiles under `build/` over the source-tree `.in` files.
- **Re-`../configure` from `build/`** whenever you `git pull`, edit source Makefiles or copied `ci/` scripts/tests, edit `VX_config.toml` / any `*.toml`, or add/remove a build-participating directory. The runnable Python scripts/tests are copies too; editing their source does not refresh the generated tree. Symptom of forgetting this: stale binaries, missing targets, or "I edited this Makefile and nothing happened."
- **Profile edits require re-`configure`, including inherited profiles.** Profile values are defaults in generated C++/RTL headers as well as compiler flags. Regenerate both together, preserving header timestamps when their contents are unchanged, so simulation and synthesis keep the same machine.
- **RTL exports must forward generated enum selector flags.** `VX_CFG_TCU_TYPE=TFR` alone does not select an `ifdef VX_CFG_TCU_TYPE_TFR` branch; resolve the configuration with `ci/gen_config.py` and pass its selector flags alongside the value.
- **Generated wrappers that invoke `configure` must run from an immutable script copy.** Replacing a running script can make Bash read a mixture of old and new input and fail after its child command finishes. Each invocation must own and clean up its copy, including nested invocations.
- **Always ensure the build is current before running any test or app** — re-run `../configure` from `build/` first. `configure` regenerates `<build>/sw/VX_config.h` and `<build>/hw/*.vh` from `VX_config.toml`, but only when the toml is newer (it guards on mtime). The simx/RTL **cores `#include` this generated header**, so a stale header makes a core compile against old config values and silently diverge from the toml — and from the runtime/RTL, which re-expand the config every build. This is a real footgun: a stale `VX_config.h` once made SimX run a write-back D-cache while the toml/RTL were write-through, producing SimX-only wrong results. **Never** work around such a divergence by injecting `-DVX_CFG_*` overrides into a Makefile — that masks the stale artifact and fights the config system. The toml is the single source of truth; fix it by re-`configure`-ing.
- **`ccache` can serve stale objects on `fmt`-version mismatches** (typical symptom: `fmt::v8` undefined-reference link errors in sim builds). Before deep-diving, retry with `CCACHE_DISABLE=1`.
- **Standalone RTL tests must resolve `VERILATOR` from `VERILATOR_PATH`.** An empty executable before `--cc` makes GNU Make invoke `cc` with an error-ignore prefix, hiding the first failure.
- **Unit-specific configuration must enter profile resolution before `config.mk`.** Profiles mark `CONFIGS` as an override; ordinary assignments afterward are ignored and can leave parameterized units with incompatible widths. See [docs/testing.md](docs/testing.md).
- **Compiler flag stamps must exclude per-target dependency-output options.** Keep `-MF $(@:.o=.d)` in compile recipes: `$@` changes with output paths, so storing it in the configuration fingerprint can force full rebuilds for equivalent directories. Normalize `DESTDIR` in both caller and callee: make treats equivalent path strings as different targets and can otherwise skip a required rebuild.
- **Device linker flags belong in the application fingerprint.** A changed `STARTUP_ADDR` must relink the kernel even when compiler flags stay constant; otherwise a valid 2 GiB build can reuse a kernel linked outside its memory window.
- **Borrowed runtime libraries must not become build destinations.** `VORTEX_RT_LIB` is a forced runtime build target as well as a link path. Build against task-owned copies, and select a preserved baseline only when executing the finished application; never point a Make output override at frozen evidence. See [docs/testing.md](docs/testing.md).
- **Toolchain changes must ship through `vortex-toolchain-prebuilt`.** Vortex never builds its toolchain components from source: `ci/toolchain_install.sh` (used by CI and by every fresh `TOOLDIR`) downloads prebuilt binary tarballs from the `vortex-toolchain-prebuilt` repository at the tag pinned in `VERSION` (`TOOLCHAIN_REV`), resolved at run time. So any change to a component packaged there (mesa, pocl, LLVM, RISC-V GNU, libc/libcrt, Verilator, ...) is invisible to Vortex until the corresponding tarball is repackaged, committed to `vortex-toolchain-prebuilt`, and the pinned tag is moved — pushing the component's source repo alone does nothing for CI. Landing order for a coupled change: component source repos first, then the prebuilt refresh (tarballs + tag push), then the Vortex push **last, immediately after**, so the CI run the Vortex push triggers already downloads matching binaries.

---

## 3. Bug-Fix Rules

See [docs/bug_fixes.md](docs/bug_fixes.md) for the full rationale and examples. The rules:

- **Fix root causes, not symptoms.** Diagnose before patching.
- **Don't paper over upstream regressions** or mask bugs with fallback paths and suppressed warnings.
- **Don't add legacy API compatibility or fallback code** unless it is explicitly required for the change.
- **If a patch is genuinely unavoidable** (e.g. blocked by an external dep), label it as a patch explicitly *in the commit message* and pair it with a follow-up to do the proper fix.

---

## 4. Testing & Verification Rules

See [docs/testing.md](docs/testing.md) and [docs/debugging.md](docs/debugging.md) for recipes. The rules:

- **All test commands run from `build/`.** The generated `ci/` scripts assume it.
- **`CONFIGS` must match on both sides.** `blackbox.sh` only rebuilds the driver. If your test was compiled with `-DVX_CFG_NUM_THREADS=4`, blackbox can't fix that — rebuild the app first:
  ```bash
  make -C tests/regression/<app> clean
  CONFIGS="-DVX_CFG_NUM_THREADS=8 -DVX_CFG_EXT_TCU_ENABLE" make -C tests/regression/<app>
  CONFIGS="-DVX_CFG_EXT_TCU_ENABLE" ./ci/blackbox.sh --driver=simx --app=<app> --threads=8
  ```
- **The runtime dispatcher must track configuration changes too.** Rebuild `sw/runtime/stub` with the same `CONFIGS` as the backend and application. Capabilities such as `VX_CAPS_CLOCK_RATE` come from its compile flags; stale flags can report the wrong clock even when the backend is current. Preserve its compiler-flag stamp and generated-header dependencies.
- **`make tests` / `make -C tests/regression` build with *default* macros.** Use `CONFIGS` + explicit per-app rebuild for non-default configurations.
- **There is no `--rebuild` option.** `blackbox.sh` re-makes the driver on every run, and make rebuilds it on any source or flag change.
- **Keep smoke/regression runs lean.** Don't enable debug or perf collection unless the run is explicitly for debug or measurement.
- **Cross-driver checks must distinguish application output from model diagnostics.** Simulator configuration banners are absent from hardware application logs; verify configuration through frozen build inputs and device capabilities. See [docs/testing.md](docs/testing.md).
- **Block-scaled arithmetic needs a scale-aware reference.** The generic FEDP floating-point generator does not supply FP4 scale factors; use the dedicated component test and scaled GEMM regressions. See [docs/testing.md](docs/testing.md).
- **Deadlock monitors must account for greedy scheduling.** One warp can wait through long cache fences while other warps issue instructions. Detect quiescence without treating that arbitration wait as a deadlock, and test that the monitor still fires when issue progress stops.
- **Synthesis frontend checks must exercise parameter overrides with nested interfaces.** A successful conversion does not prove elaboration: specialization can break module-rooted interface references even when the default module works. Keep a small elaboration/functional check ahead of long whole-design runs; see [docs/synthesis_analysis.md](docs/synthesis_analysis.md).
- **Staged synthesis must include every mapping stage and reject internal hardware cells in its final netlist.** Yosys `-run` excludes its ending label, and connectivity checks alone accept unmapped flip-flops. Normalize `$scopeinfo` metadata before applying cell gates; see [docs/synthesis_analysis.md](docs/synthesis_analysis.md).
- **Clock-control exceptions require a verified primitive mode and switching-latency contract.** BUFGCTRL selection inputs differ from its enables: qualify the glitch protection and exact post-optimization endpoints before excluding selection timing; see [docs/fpga_setup.md](docs/fpga_setup.md).
- **CDC review includes status and error sidebands.** A safe data mailbox does not synchronize separate status wires. Verify their source clocks and preserved synchronizer stages before applying timing exceptions; see [docs/fpga_setup.md](docs/fpga_setup.md).
- **Source reset cancellation must survive until the destination transaction drains.** A response arriving after reset deassertion still belongs to the old requester. Preserve the handshake, discard that response and test delayed read/write completion across reset; see [docs/fpga_setup.md](docs/fpga_setup.md).
- **CDC report coverage includes vendor debug IP.** Require the expected groups by owning module and check every constraint's result; a single design-only total can reject valid vendor constraints or miss omitted groups. See [docs/fpga_setup.md](docs/fpga_setup.md).
- **Qualification requires complete evidence before checking for errors.** Empty reports and streams missing a final CRC checkpoint can contain no reported failures. Verify report structure, counts and configuration coverage before accepting their results; see [docs/fpga_setup.md](docs/fpga_setup.md).
- **RTL coverage path is `xrt`, not `rtlsim`.** When discussing or planning RTL verification, `xrt` is the canonical path — `rtlsim` bypasses the AFU surface. `rtlsim` remains useful for fast iteration on processor RTL; `xrt` is what proves the full integration.
- **`ci/regression.sh` is the canonical source of tested configurations.** Use it to discover supported parameter combinations before inventing ad hoc ones.
- **Perf-regression baselines (`ci/baselines/perf/*.json`) are golden data — never hand-edit them, and never "fix" a red perf gate by bumping the number.** They are regenerated only by `pytest ci -m perf_gate --update-baselines` (a human-run, reviewed step), and CI must never pass that flag. A `perf_gate` failure means real cycles moved: root-cause it, or — if the change is intended — regenerate the baseline so the diff shows the perf delta for review. Same rule as image goldens and `known_issue:`.
- **Synthesis baselines (`ci/baselines/synthesis/{xilinx,yosys}/*.json`) are golden data under the same rule** — never hand-edited, regenerated only by a human running `ci/fpga_gate.py --update-baseline` / `ci/asic_gate.py --update-baseline`, never by CI. A red `fpga_gate`/`asic_gate` means real Fmax or area moved. Note the two gates measure the *same* `hw/unittest/*/VX_*_top.sv` wrappers through different flows, so a divergence between them is a finding, not noise — keep `hw/syn/{xilinx,yosys}/dut/catalog.mk` in step when you add or rename a DUT. See [docs/designs/continuous_integration.md §3.5](docs/designs/continuous_integration.md).
- **SimX is the RTL's timing model — keep them in lockstep.** Any change that moves RTL cycles (pipeline structure, arbitration, queue depths, cache/memory behavior) must land together with the matching SimX timing-model update, and vice-versa. The `model_parity` CI gate enforces this: a `check: model_parity` case (`ci/testcases/core.yaml` + per-extension parity categories) runs the same app/args/configs on simx and rtlsim and asserts exact retired-instruction match plus cycle agreement within the case tolerance (default 5%). Never widen a tolerance to absorb a divergence — model the behavior. When adding a hardware feature, add or extend a parity case that exercises it.
- **When RTL debugging stalls, switch to the SimX-as-oracle pattern.** For numerical bugs, deep pipeline races, or any failure mode where rtlsim is "close but wrong": (1) build/extend the SimX C++ model so it mirrors the *new* RTL architecture and gets to PASS; (2) add matching trace dumps to both SimX and RTL (cycle, FU events, SRAM addresses+data, hazards) — same CSV format on both sides; (3) diff trace files — the first divergence is the bug. Don't keep guessing from output values; localize via trace diff. See [docs/debugging.md](docs/debugging.md#simx-as-oracle-for-rtl-debug).

### Smoke tests

```bash
./ci/blackbox.sh --driver=simx --app=demo
./ci/blackbox.sh --driver=simx --app=sgemm --args="-n16"
```

### Regression suites

```bash
make -C tests/regression run-simx
make -C tests/regression run-rtlsim
make -C tests/opencl     run-simx
make -C tests/opencl     run-rtlsim
```

### Architecture overrides

`blackbox.sh` exposes the common knobs directly: `--clusters=`, `--cores=`, `--warps=`, `--threads=`, `--l2cache`, `--l3cache`, `--debug=`, `--vcd`, `--perf=`. For anything not exposed as a flag, use `CONFIGS="-D..."` (all parameters take the `VX_CFG_*` prefix — e.g. `-DVX_CFG_NUM_THREADS=8`, `-DVX_CFG_EXT_TCU_ENABLE`). Baseline parameters live in `VX_config.toml` and `VX_types.toml` at the repo root — edit those only when an override is needed for *all* builds, and re-`configure` afterward.

```bash
./ci/blackbox.sh --driver=simx --app=sgemm --clusters=1 --cores=2 --warps=4 --threads=4 --l2cache
```
OR

```bash
CONFIGS="-DVX_CFG_NUM_THREADS=4 -DVX_CFG_EXT_TCU_ENABLE -DVX_CFG_TCU_TYPE_TFR -DITYPE=bf16 -DOTYPE=fp32" ./ci/blackbox.sh --driver=rtlsim --app=sgemm_tcu
```

### Roofline Analysis

`ci/roofline.py` runs a kernel via `blackbox.sh`, optionally sweeps microarchitecture knobs to maximize IPC (`--config=fast|random|best`, comma-lists as search spaces), and plots a FLOP/cycle roofline. Run it from a configured build directory. `--perf=7` (the default) is required for the memory-traffic counters that place the measured point; pass the kernel's total FLOPs via `--flops`. The default compute roof models the scalar FPU — for TCU kernels pass `--peak-flops` explicitly.

```bash
python3 ci/roofline.py --app=sgemm --driver=simx --args="-n128" --flops=4194304 \
  --cores=1 --warps=4 --threads=8 --issue-width=2 --plot --output=sgemm_roofline.png
```

---

## 5. Design & Architecture Rules

- **Align with mainstream CUDA, HIP, OpenCL, and Vulkan API and driver stacks.** For any design question — driver surface, command-processor model, memory model, scheduling — pick the solution those stacks would use. This keeps Vortex's externals familiar to mainstream software and avoids one-off abstractions.

- **SimX Cardinal Rule — modules communicate *only* through channels.** A `SimObject` may observe or mutate another module's state *only* via its bound `SimChannel` ports (`MemReq`/`MemRsp`, `result_if`, …). **Never reach across the ownership hierarchy** to touch another object directly (`core_->processor()->memsim()`, `parent()->child()->field`, a leaf unit grabbing the global `Memory`). See [docs/designs/simobject.md](docs/designs/simobject.md#the-cardinal-rule).

---

## 6. Coding Conventions

See [docs/coding_guidelines_cpp.md](docs/coding_guidelines_cpp.md) and [docs/coding_guidelines_verilog.md](docs/coding_guidelines_verilog.md) for full style. Cross-cutting comment rules:

- **`sw/{kernel,runtime}/` and `sim/`/`hw/` are bidirectionally isolated.** Source files under `sw/kernel/` and `sw/runtime/` MUST NOT reference anything in `hw/*` or `sim/*`. Equally, source files under `sim/*` and `hw/*` MUST NOT reference anything in `sw/kernel/` or `sw/runtime/`. If the layers genuinely need to share host-side helper code or an on-wire ABI definition, put it in `sw/common/` — vortex-internal, never installed, accessible from all four layers. Enforced by [ci/check_sw_sim_boundary.sh](ci/check_sw_sim_boundary.sh).
- **Default to no comment.** Add one only when the *why* is non-obvious — a hidden constraint, a subtle invariant, a workaround for a specific bug, a surprising behavior.
- **Comments explain *why*, not *what*.** Well-named identifiers carry the *what*.
- **Never reference the current task, PR, caller, issue number, or fix.** Those belong in the commit message and rot in code. Don't write `// used by foo()`, `// added for the X flow`, `// handles issue #123`.
- **`RTL_PKGS` is for `VX_*_pkg.sv` only.** Verilog interfaces are illegal there. If an interface isn't being discovered, fix it via include paths or file naming — not by stuffing it into `RTL_PKGS`.
- **Trace package dependencies follow enabled extensions.** Standalone units using `VX_trace_pkg.sv` with TCU enabled must load `VX_tcu_pkg.sv` first. See [docs/testing.md](docs/testing.md).
- **RTL parameter names must avoid Vivado synthesis-property names.** Vivado exports module parameters as case-insensitive cell properties: a Boolean `USE_DSP` collides with the enum property `use_dsp`. Use `DSP_ENABLE` for the Boolean feature knob.
- **Library RTL defaults to `TRACING_OFF`.** Modules under `hw/rtl/libs/` are excluded from VCD by default to keep waveform size manageable. Toggle per-file with `TRACING_ON`/`TRACING_OFF`, or globally with `CONFIGS="-DTRACING_ALL"`.
- **No multi-paragraph docstrings or multi-line block comments** for trivial code. One short line is the ceiling unless the logic genuinely needs more.
- **No `// removed code` or stale-rename breadcrumbs.** If something is unused, delete it.

---

## 7. Proposals

Design and migration proposals belong in [`docs/proposals/`](docs/proposals/) — never in build dirs or the repo root. A proposal captures the *why* of a non-trivial change before the code lands.

Accepted designs that outlive their proposal phase live in [`docs/designs/`](docs/designs/).

---

## 8. Living Document Policy

This file is versioned alongside the code and evolves with it. Both humans and agents are expected to update it:

- **Add a rule** when you discover a footgun the next contributor will hit. Include the *why*.
- **Update or remove a rule** that's gone stale. A stale rule is worse than no rule.
- **Don't duplicate** content from the topic docs in `docs/`. AGENTS.md links; the topic doc explains.
- **Branch-specific addenda are forbidden.** Branch context goes in a `docs/proposals/<feature>_proposal.md`, not in branch-local `AGENTS.md` variants. If the rule is general, promote it here; if it's a project-tracking detail, keep it in the proposal.
