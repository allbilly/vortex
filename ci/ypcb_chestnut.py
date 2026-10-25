#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.
# USB framing adapted from OpenTPU's Apache-2.0 Chestnut host transport.

from __future__ import annotations

import ctypes
import ctypes.util
import fcntl
import os
from pathlib import Path
import re
import socket
import socketserver
import struct
import threading
import time

class PcieCompletionError(OSError):
    """Structured Chestnut reply; bridge status is separate from TLP status."""
    def __init__(self,address,status,completion):
        self.address,self.status,self.completion=int(address),int(status),int(completion)
        super().__init__(f'PCIe completion at {address:#x}: status={status}, completion={completion}')

class _ChestnutUsb:
    """The control and bulk subset used by the verified Chestnut firmware."""
    def __init__(self):
        library = ctypes.util.find_library('usb-1.0')
        if library is None:
            library = next((str(p) for p in (Path('/opt/homebrew/lib/libusb-1.0.dylib'),
                                              Path('/usr/local/lib/libusb-1.0.dylib')) if p.exists()), None)
        if library is None:
            raise RuntimeError('libusb-1.0 is required (macOS: brew install libusb)')
        self.lib = ctypes.CDLL(library)
        p, i, u8, u16 = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint8, ctypes.c_uint16
        bindings = {
            'libusb_init': (i, [ctypes.POINTER(p)]),
            'libusb_exit': (None, [p]),
            'libusb_get_device_list': (ctypes.c_ssize_t, [p, ctypes.POINTER(ctypes.POINTER(p))]),
            'libusb_free_device_list': (None, [ctypes.POINTER(p), i]),
            'libusb_get_device_descriptor': (i, [p, p]),
            'libusb_open_device_with_vid_pid': (p, [p, u16, u16]),
            'libusb_claim_interface': (i, [p, i]),
            'libusb_release_interface': (i, [p, i]),
            'libusb_close': (None, [p]),
            'libusb_control_transfer': (i, [p, u8, u8, u16, u16, p, u16, ctypes.c_uint]),
            'libusb_bulk_transfer': (i, [p, u8, p, i, ctypes.POINTER(i), ctypes.c_uint]),
            'libusb_strerror': (ctypes.c_char_p, [i]),
        }
        for name, (result, args) in bindings.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = result, args
        self.context, self.handle, self.claimed = p(), None, False
        self.check(self.lib.libusb_init(ctypes.byref(self.context)))
        try:
            devices = ctypes.POINTER(p)()
            count = self.check(self.lib.libusb_get_device_list(self.context, ctypes.byref(devices)))
            matches = 0
            try:
                for index in range(count):
                    descriptor = ctypes.create_string_buffer(18)
                    self.check(self.lib.libusb_get_device_descriptor(devices[index], descriptor))
                    if struct.unpack_from('<HH', descriptor.raw, 8) == (0x3801, 1):
                        matches += 1
            finally:
                self.lib.libusb_free_device_list(devices, 1)
            if matches != 1:
                raise RuntimeError(f'Require one Chestnut 3801:0001; found {matches}')
            self.handle = self.lib.libusb_open_device_with_vid_pid(self.context, 0x3801, 1)
            if not self.handle:
                raise OSError('Cannot open Chestnut USB device')
            self.check(self.lib.libusb_claim_interface(self.handle, 0))
            self.claimed = True
        except BaseException:
            self.close()
            raise

    def check(self, result):
        if result < 0:
            raise OSError(f'Chestnut USB: {self.lib.libusb_strerror(result).decode()} ({result})')
        return result

    def control(self, direction, request, value, index, payload=bytes(), size=0, timeout=5000):
        length = size if direction & 0x80 else len(payload)
        buf = ctypes.create_string_buffer(length)
        if payload:
            ctypes.memmove(buf, payload, length)
        count = self.check(self.lib.libusb_control_transfer(
            self.handle, direction, request, value, index, buf, length, timeout))
        if count != length:
            raise OSError(f'Short USB control transfer: {count}/{length}')
        return buf.raw

    def read(self, addr, size):
        if addr < 0 or size < 0 or addr + size > 0x10000:
            raise ValueError('XDATA read wraps the 16-bit window')
        return b''.join(self.control(0xc0, 0xe4, addr + pos, 0, size=min(255, size-pos))
                        for pos in range(0, size, 255))

    def pcie_request(self, fmt_type, address, value=None, size=4, cnt=0):
        if not 1 <= size <= 4 or (address & 3) + size > 4:
            raise ValueError('PCIe access crosses a dword')
        shift = 8 * (address & 3)
        byte_enable = ((1 << size) - 1) << (address & 3)
        aligned = address & ~3
        payload = struct.pack('<III', aligned & 0xffffffff, aligned >> 32,
                              0 if value is None else int(value) << shift)
        self.control(0x40, 0xf0, fmt_type | byte_enable << 8, 0, payload)
        if fmt_type == 0x40:
            return None  # posted memory write
        reply = self.control(0xc0, 0xf0, 0, 0, size=8)
        status, completion = reply[7], (reply[4] >> 5) & 7
        if status or completion:
            raise PcieCompletionError(address,status,completion)
        return (struct.unpack_from('<I', reply)[0] >> shift) & ((1 << (8*size))-1)

    def pcie_cfg_req(self, off, bus=0, value=None, size=4):
        if not 0 <= bus <= 255 or not 0 <= off < 4096:
            raise ValueError('Invalid PCIe configuration address')
        fmt = (0x44 if value is not None else 4) | int(bus > 0)
        return self.pcie_request(fmt, bus << 24 | off, value, size)

    def scsi_write(self, data):
        data += bytes((-len(data)) % 512)
        if not 0 < len(data) <= 0x80000:
            raise ValueError('Transfer exceeds Chestnut staging SRAM')
        slots = (len(data) + 0x3fff) // 0x4000
        self.control(0x40, 0xf2, len(data)//512, slots << 8)
        buf, actual = ctypes.create_string_buffer(data), ctypes.c_int()
        self.check(self.lib.libusb_bulk_transfer(self.handle, 2, buf, len(data), ctypes.byref(actual), 5000))
        if actual.value != len(data):
            raise OSError(f'Short USB bulk transfer: {actual.value}/{len(data)}')

    def close(self):
        if self.handle:
            if self.claimed:
                self.lib.libusb_release_interface(self.handle, 0)
                self.claimed = False
            self.lib.libusb_close(self.handle)
            self.handle = None
        if self.context:
            self.lib.libusb_exit(self.context)
            self.context = None


class ChestnutPcie:
    BAR_BASE = 0x10000000
    BAR_SIZE = 0x10000

    def __init__(self, *, usb=None, lock_path=None):
        self.usb = None
        self.failed = False
        self.restore = {}
        self.identity = {}
        self.mutex = threading.RLock()
        self.lock = None
        self.physical = usb is None
        path = Path(lock_path) if lock_path is not None else Path(
            os.environ.get('OTPU_RUN_DIR', '/tmp/otpu')) / 'chestnut-3801-0001.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(descriptor)
            raise RuntimeError('Chestnut is already owned by another process')
        self.lock = descriptor
        try:
            self.usb = _ChestnutUsb() if usb is None else usb
            if self.usb.read(0xb450, 1) != b'\x78':
                raise RuntimeError('Chestnut PCIe link is not up')
            for bus in (0, 1):
                if self.cfg(bus, 0) != 0x24641b21:
                    raise RuntimeError('Unexpected Chestnut bridge topology')
                self.change(bus, 0x18, ((bus + 1) << 8) | (2 << 16))
            if self.cfg(2, 0) != 0x048010ee:
                raise RuntimeError('Expected Vortex PCIe endpoint 10ee:0480')
            command = self.cfg(2, 4, size=2)
            self.change(2, 4, command & ~6, size=2)
            bar = self.cfg(2, 0x10)
            if bar & 15:
                raise RuntimeError('Vortex requires its 32-bit non-prefetchable BAR0')
            self.change(2, 0x10, 0xffffffff)
            mask = self.cfg(2, 0x10)
            if mask != 0xffff0000:
                raise RuntimeError(f'Vortex BAR0 size mismatch: {mask:#010x}')
            self.change(2, 0x10, self.BAR_BASE)
            for bus in (0, 1):
                self.change(bus, 0x20, 0x1ff01000)
                self.change(bus, 4, self.cfg(bus, 4, size=2) | 6, size=2)
            self.change(2, 4, command | 6, size=2)
            magic, abi, status = [self.read32(offset) for offset in (0x3000, 0x3004, 0x3008)]
            if magic != 0x56595043 or abi != 5 or status & 0x7800:
                raise RuntimeError(f'Expected healthy Vortex ABI5: {magic:#x}, {abi}, {status:#x}')
            self.identity = {'usb': '3801:0001', 'pcie_vendor': 0x10ee,
                             'pcie_device': 0x0480, 'bar0_bytes': self.BAR_SIZE,
                             'bar0_base': self.BAR_BASE, 'board_magic': magic,
                             'board_abi': abi, 'board_status': status,
                             'physical_interface': 'PCIe via Chestnut',
                             'live_bitstream_sha256_readable': False}
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                raise RuntimeError(f'{original}; PCIe cleanup failed: {cleanup}') from original
            raise

    def cfg(self, bus, offset, value=None, size=4):
        return self.usb.pcie_cfg_req(offset, bus=bus, value=value, size=size)

    def change(self, bus, offset, value, size=4):
        key = (bus, offset, size)
        if key not in self.restore:
            self.restore[key] = self.cfg(bus, offset, size=size)
        self.cfg(bus, offset, value, size)

    @staticmethod
    def valid_offset(offset):
        return type(offset) is int and 0 <= offset < 0x10000 and offset % 4 == 0

    def read32(self, offset):
        with self.mutex:
            if self.failed or not self.valid_offset(offset):
                raise RuntimeError('Invalid or quarantined Vortex MMIO read')
            try:
                return self.usb.pcie_request(0, self.BAR_BASE + offset)
            except BaseException:
                self.failed = True
                raise

    def write32(self, offset, value):
        with self.mutex:
            if self.failed or not self.valid_offset(offset) or not 0 <= value <= 0xffffffff:
                raise RuntimeError('Invalid or quarantined Vortex MMIO write')
            try:
                self.usb.pcie_request(0x40, self.BAR_BASE + offset, value)
                status = self.usb.pcie_request(0, self.BAR_BASE + 0x3008)
                if status == 0xffffffff or status & 0x7800:
                    raise RuntimeError(f'Vortex PCIe posted-write fence failed: {status:#x}')
            except BaseException:
                self.failed = True
                raise

    def quiesce(self, timeout=30):
        self.write32(0x111c, 0)
        self.write32(0x1000, 0)
        self.write32(0, 0x10)
        deadline = time.monotonic() + timeout
        while True:
            status = self.read32(0)
            if status & 0x20:
                raise RuntimeError('Vortex AFU reported an error during cleanup')
            if status & 0x14 == 4:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError('Vortex AFU did not drain during cleanup')
            time.sleep(0.001)

    def close(self):
        errors = []
        with self.mutex:
            if self.usb is not None:
                for (bus, offset, size), value in reversed(list(self.restore.items())):
                    try:
                        self.cfg(bus, offset, value, size)
                    except BaseException as error:
                        errors.append(str(error))
                self.restore.clear()
                try:
                    self.usb.close()
                except BaseException as error:
                    errors.append(str(error))
                self.usb = None
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None
        if errors:
            raise RuntimeError('PCIe configuration restoration failed: ' + '; '.join(errors))


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        if not self.server.client_lock.acquire(blocking=False):
            self.wfile.write(b'ERR client already connected\n')
            return
        try:
            with self.server.connections_lock:
                if self.server.closing:
                    return
                self.server.connections.add(self.request)
            self.request.settimeout(30)
            while not self.server.closing:
                line = self.rfile.readline(257)
                if not line:
                    break
                try:
                    response = self.server.transact(line)
                    self.wfile.write(response)
                    self.wfile.flush()
                except BaseException as error:
                    self.server.last_error = str(error)
                    self.wfile.write(b'ERR MMIO request rejected\n')
                    break
        except OSError as error:
            if not self.server.closing:
                self.server.last_error = str(error)
                self.server.transport.failed = True
        finally:
            with self.server.connections_lock:
                self.server.connections.discard(self.request)
            self.server.client_lock.release()


class MmioServer(socketserver.ThreadingTCPServer):
    daemon_threads = False
    allow_reuse_address = False

    def __init__(self, transport):
        self.transport = transport
        self.client_lock = threading.Lock()
        self.last_error = None
        self.thread = None
        self.connections = set()
        self.connections_lock = threading.Lock()
        self.sessions = threading.Condition()
        self.active_requests = 0
        self.closing = False
        super().__init__(('127.0.0.1', 0), _Handler)

    def process_request(self, request, client_address):
        with self.sessions:
            self.active_requests += 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.request_finished()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_finished()

    def request_finished(self):
        with self.sessions:
            self.active_requests -= 1
            self.sessions.notify_all()

    def wait_idle(self, timeout=30):
        with self.sessions:
            if not self.sessions.wait_for(lambda: self.active_requests == 0, timeout):
                raise TimeoutError('Previous Chestnut MMIO session did not drain')
            if self.closing:
                raise RuntimeError('Chestnut MMIO server is closing')
            if self.last_error is not None:
                raise RuntimeError('Chestnut MMIO server reported: ' + self.last_error)

    def transact(self, line):
        if len(line) > 256 or not line.endswith(b'\n'):
            raise ValueError('Invalid MMIO command length')
        words = line.decode('ascii').strip().split()
        if len(words) < 2 or not re.fullmatch('[0-9a-fA-F]{4}', words[1]):
            raise ValueError('Invalid MMIO address')
        command, offset = words[0], int(words[1], 16)
        if command in ('R', 'W'):
            count = 1
            values = words[2:]
        elif command in ('BR', 'BW') and len(words) >= 3 and re.fullmatch('[0-9a-fA-F]{2}', words[2]):
            count = int(words[2], 16)
            values = words[3:]
        else:
            raise ValueError('Unknown MMIO command')
        write = command in ('W', 'BW')
        if not 1 <= count <= 16 or offset % 4 or offset + 4 * count > 0x10000:
            raise ValueError('MMIO range is invalid')
        if len(values) != (count if write else 0) or any(
                re.fullmatch('[0-9a-fA-F]{8}', value) is None for value in values):
            raise ValueError('MMIO payload is invalid')
        with self.transport.mutex:
            if write:
                for index, value in enumerate(values):
                    self.transport.write32(offset + 4 * index, int(value, 16))
                result = [0]
            else:
                result = [self.transport.read32(offset + 4 * index) for index in range(count)]
        return ('OK' + ''.join(f' {value:08x}' for value in result) + '\n').encode()

    def start(self):
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()
        return self.server_address[1]

    def close(self):
        self.closing = True
        if self.thread is not None:
            self.shutdown()
        with self.connections_lock:
            for connection in self.connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('Chestnut MMIO server did not stop')
