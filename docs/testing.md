# Testing

For small Python examples with GPU kernels and checked numerical output, see
[basic operations](../examples/README.md). From a configured build directory,
`make -j1 -C examples run` builds and runs them on SimX.

## Running a Vortex application

The framework provides a utility script: blackbox.sh under the /ci/ folder for executing applications in the tests tree. It gets copied into the `build` directory with all the environment variables resolved, so you should run it from the `build` directory as follows:
You can query the commandline options of the tool using:

    $ ./ci/blackbox.sh --help

To execute sgemm test program on the simx driver and passing "-n10" as argument to sgemm:

    $ ./ci/blackbox.sh --driver=simx --app=sgemm --args="-n10"

You can execute the same application of a GPU architecture with 2 cores:

    $ ./ci/blackbox.sh --core=2 --driver=simx --app=sgemm --args="-n10"

When excuting, Blackbox needs to recompile the driver if the desired architecture changes.
It tracks the latest configuration in a file under the current directory blackbox.<driver>.cache.
To avoid having to rebuild the driver all the time, Blackbox checks if the latest cached configuration matches the current.

## Running Benchmarks

The Vortex test suite is located under the /test/ folder
You can execute the default regression suite by running the following commands at the root folder.

    $ make -C tests/regression run-simx
    $ make -C tests/regression run-rtlsim

You can also run regression applications in parallel from a configured build tree.
The script accepts `simx`, `rtlsim`, or `rtl` (alias for `rtlsim`) and writes
per-test logs plus a summary under `tests/regression/logs/`.

    $ ./tests/regression/run_parallel.sh simx -j 8
    $ ./tests/regression/run_parallel.sh rtl -j 2

By default it scans every first-level regression directory with a Makefile. Use
`--suite makefile` to run the same test list selected by `tests/regression/Makefile`.

You can execute the default opncl suite by running the following commands at the root folder.

    $ make -C tests/opencl run-simx
    $ make -C tests/opencl run-rtlsim

## Standalone RTL unit tests

Run units from a configured build tree, for example
`make -j1 -C hw/unittest/cp_dma run`. Unit file lists must include dependencies
of enabled trace functions even when trace output is disabled. With TCU
enabled, put `VX_tcu_pkg.sv` after `VX_gpu_pkg.sv` and before `VX_trace_pkg.sv`
in `RTL_PKGS`.

RTL dependency enumeration must work in the build service's environment.
Treat discovery errors and empty file lists as fatal; otherwise source edits
can leave an existing model unchanged while Make reports success.

Put unit-specific configuration flags before including `config.mk` so profile
resolution sees them as explicit overrides. Profile resolution uses
`override CONFIGS`; a normal assignment after that include is ignored. A unit
that varies its word count must select matching geometry for both its RTL and
C++ reference, and rebuild between variants.

Scaled FP4 has scale-factor inputs that the generic `tcu_fedp` floating-point
generator does not model. Use the scale-aware multiplier test:

```bash
make -j1 -C hw/unittest/tcu_f4_mul run-matrix
make -j1 -C hw/unittest/tcu_mx_index run
```

The multiplier matrix checks MXFP4/NVFP4 products, exact cancellation, lane
masks and enable stalls at two/four words, zero/one product-register stages
and LUT/DSP multiplication. Each variant checks 100,000 frames against an
independent integer reference. The indexing test checks all 32 format codes,
small tile sizes and full-width overflow boundaries against division-based
formulas. The scaled GEMM cases in `ci/testcases/tensor_mx.yaml` cover full
GPU integration.

## Creating Your Own Regression Test

Inside `tests/regression` you will find a series of folders which are named based on what they test.
You can view the tests to see which ones have tests similar to what you are trying to create new tests for.
Once you have found a similar baseline, you can copy the folder and rename it to what you are planning to test.
A regression test typically implements the following files:
- ***kernel.cpp*** contains the GPU kernel code.
- ***main.cpp*** contains the host CPU code.
- ***Makefile*** defines the compiler build commands for the CPU and GPU binaries.

Sync your build folder: `$ ../configure`

Compile your test: `$ make -C tests/regression/<test-name>`

Run your test: `$ ./ci/blackbox.sh --driver=simx --app=<test-name> --debug`

## Adding Your Tests to the CI Pipeline
If you are a contributor, then you will need to add tests that integrate into the continuous integration pipeline. Remember, Pull Requests cannot be merged unless new code has tests and existing tests do not regress. Furthermore, if you are contributing a new feature, it is recommended that you add the ability to enable / disable the new feature that you are adding. See more at [CONTRIBUTING.md](../CONTRIBUTING.md) and [continuous_integration.md](continuous_integration.md).
