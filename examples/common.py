# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import ctypes as ct
import math
import os
from pathlib import Path

VX_CAPS_NUM_THREADS = 0x1
VX_MEM_READ_WRITE = 0x3
VX_QUEUE_PRIORITY_NORMAL = 1


class KernelArgs(ct.Structure):
    _fields_ = [("a", ct.c_uint64), ("b", ct.c_uint64), ("c", ct.c_uint64),
                ("count", ct.c_uint32), ("op", ct.c_uint32),
                ("dims", ct.c_uint32 * 8)]


class QueueInfo(ct.Structure):
    _fields_ = [("struct_size", ct.c_size_t), ("next", ct.c_void_p),
                ("priority", ct.c_int), ("flags", ct.c_uint32)]


class LaunchInfo(ct.Structure):
    _fields_ = [("struct_size", ct.c_size_t), ("next", ct.c_void_p),
                ("kernel", ct.c_void_p), ("args_host", ct.c_void_p),
                ("args_size", ct.c_size_t), ("ndim", ct.c_uint32),
                ("grid_dim", ct.c_uint32 * 3), ("block_dim", ct.c_uint32 * 3),
                ("lmem_size", ct.c_uint32), ("cluster_dim", ct.c_uint32 * 3)]


def positive(text):
    value = int(text)
    if not 0 < value < 2**31:
        raise argparse.ArgumentTypeError("must be a positive 31-bit integer")
    return value


def nonnegative(text):
    value = int(text)
    if not 0 <= value < 2**30:
        raise argparse.ArgumentTypeError("must be a nonnegative 30-bit integer")
    return value


def parser(description):
    cli = argparse.ArgumentParser(description=description)
    default_build = os.environ.get("VORTEX_BUILD_DIR")
    if not default_build:
        default_build = Path.cwd() if Path("config.mk").is_file() else Path(__file__).resolve().parents[1] / "build"
    cli.add_argument("--build", type=Path, default=Path(default_build), help="configured Vortex build directory")
    cli.add_argument("--driver", choices=("simx", "xrt", "rtlsim", "ypcb"), default="simx")
    return cli


def values(count, seed=0):
    return [((i * 7 + seed) % 23 - 11) / 8 for i in range(count)]


def spatial_shape(cli, height, width, kernel, stride, padding):
    if height + 2 * padding < kernel or width + 2 * padding < kernel:
        cli.error("kernel does not fit the padded input")
    if padding >= kernel:
        cli.error("padding must be smaller than the kernel")
    return ((height + 2 * padding - kernel) // stride + 1,
            (width + 2 * padding - kernel) // stride + 1)


def verify(name, actual, expected, driver):
    if len(actual) != len(expected):
        raise RuntimeError(f"{name}: output length differs")
    errors = [(i, a, b) for i, (a, b) in enumerate(zip(actual, expected))
              if not math.isfinite(a) or not math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-5)]
    if errors:
        raise RuntimeError(f"FAIL {name}: {len(errors)} mismatches; first (index, actual, expected)={errors[0]}")
    maximum = max(abs(a - b) for a, b in zip(actual, expected))
    print(f"PASS {name}: driver={driver}, float32 elements={len(actual)}, max_abs_error={maximum:.3g}")
    print("  output:", [round(x, 6) for x in actual[:8]])


class Vortex:
    def __init__(self, options):
        self.build = options.build.expanduser().resolve()
        library = self.build / "sw/runtime/libvortex.so"
        if not (self.build / "config.mk").is_file() or not library.is_file():
            raise RuntimeError("Configure the build and run 'make -C examples runtime' first; see examples/README.md")
        os.environ["VORTEX_DRIVER"] = options.driver
        self.lib = ct.CDLL(str(library), mode=ct.RTLD_GLOBAL)
        handle, pointer, u32, u64 = ct.c_void_p, ct.POINTER(ct.c_void_p), ct.c_uint32, ct.c_uint64
        signatures = {
            "vx_device_open": [u32, pointer], "vx_device_release": [handle],
            "vx_device_query": [handle, u32, ct.POINTER(u64)],
            "vx_queue_create": [handle, ct.POINTER(QueueInfo), pointer],
            "vx_queue_finish": [handle, u64], "vx_queue_release": [handle],
            "vx_buffer_create": [handle, u64, u32, pointer],
            "vx_buffer_address": [handle, ct.POINTER(u64)], "vx_buffer_release": [handle],
            "vx_module_load_file": [handle, ct.c_char_p, pointer],
            "vx_module_get_kernel": [handle, ct.c_char_p, pointer],
            "vx_module_release": [handle], "vx_kernel_release": [handle],
            "vx_enqueue_write": [handle, handle, u64, handle, u64, u32, pointer, pointer],
            "vx_enqueue_read": [handle, handle, handle, u64, u64, u32, pointer, pointer],
            "vx_enqueue_launch": [handle, ct.POINTER(LaunchInfo), u32, pointer, pointer],
            "vx_event_wait_value": [handle, u64, u64], "vx_event_release": [handle],
        }
        for name, args in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, ct.c_int
        self.lib.vx_result_string.argtypes = [ct.c_int]
        self.lib.vx_result_string.restype = ct.c_char_p
        self.device, self.queue = handle(), handle()
        self.resources, self.pending = [], []
        self.timeout = 60 * 10**9
        try:
            self.check("vx_device_open", 0, ct.byref(self.device))
            info = QueueInfo(ct.sizeof(QueueInfo), None, VX_QUEUE_PRIORITY_NORMAL, 0)
            self.check("vx_queue_create", self.device, ct.byref(info), ct.byref(self.queue))
            threads = u64()
            self.check("vx_device_query", self.device, VX_CAPS_NUM_THREADS, ct.byref(threads))
            self.threads = threads.value
        except BaseException:
            self.close()
            raise

    def check(self, name, *args):
        result = getattr(self.lib, name)(*args)
        if result:
            message = self.lib.vx_result_string(result).decode()
            raise RuntimeError(f"{name}: {message} ({result})")

    def resource(self, create, release, *args):
        handle = ct.c_void_p()
        self.check(create, *args, ct.byref(handle))
        self.resources.append((release, handle))
        return handle

    def run(self, name, a, b, count, *, op=0, dims=()):
        path = self.build / "examples/kernels" / name / "kernel.vxbin"
        if not path.is_file():
            raise RuntimeError(f"Missing {path}; run 'make -C examples' from the build directory")
        if not 0 < count < 2**32 or len(dims) > 8 or any(not 0 <= d < 2**31 for d in dims):
            raise ValueError("kernel dimensions exceed the argument format")
        first = len(self.resources)
        arrays = [(ct.c_float * len(a))(*a), (ct.c_float * len(b))(*b),
                  (ct.c_float * count)(*([float("nan")] * count))]
        args = KernelArgs(count=count, op=op)
        self.pending.append((arrays, args))
        for field, array in zip(("a", "b", "c"), arrays):
            buffer = self.resource("vx_buffer_create", "vx_buffer_release", self.device,
                                   ct.sizeof(array), VX_MEM_READ_WRITE)
            address = ct.c_uint64()
            self.check("vx_buffer_address", buffer, ct.byref(address))
            setattr(args, field, address.value)
            self.check("vx_enqueue_write", self.queue, buffer, 0, array, ct.sizeof(array), 0, None, None)
            if field == "c":
                output_buffer = buffer
        for i, value in enumerate(dims):
            args.dims[i] = value
        module = self.resource("vx_module_load_file", "vx_module_release", self.device, os.fsencode(path))
        kernel = self.resource("vx_module_get_kernel", "vx_kernel_release", module, b"main")
        launch = LaunchInfo(struct_size=ct.sizeof(LaunchInfo), kernel=kernel,
                            args_host=ct.cast(ct.byref(args), ct.c_void_p), args_size=ct.sizeof(args), ndim=1)
        launch.grid_dim[:] = ((count + self.threads - 1) // self.threads, 1, 1)
        launch.block_dim[:] = (self.threads, 1, 1)
        event = self.resource("vx_enqueue_launch", "vx_event_release", self.queue, ct.byref(launch), 0, None)
        read = self.resource("vx_enqueue_read", "vx_event_release", self.queue, arrays[2], output_buffer,
                             0, ct.sizeof(arrays[2]), 1, ct.byref(event))
        self.check("vx_event_wait_value", read, 1, self.timeout)
        result = list(arrays[2])
        while len(self.resources) > first:
            release, handle = self.resources.pop()
            self.check(release, handle)
        self.pending.clear()
        return result

    def close(self):
        if self.queue:
            self.lib.vx_queue_finish(self.queue, self.timeout)
        while self.resources:
            release, handle = self.resources.pop()
            getattr(self.lib, release)(handle)
        if self.queue:
            self.lib.vx_queue_release(self.queue)
            self.queue = ct.c_void_p()
        if self.device:
            self.lib.vx_device_release(self.device)
            self.device = ct.c_void_p()
        self.pending.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
