import copy
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock

from ypcb_chestnut import ChestnutPcie, MmioServer, PcieCompletionError, _ChestnutUsb


class FakeUsb:
    def __init__(self):
        self.config = {(bus, off): 0 for bus in [0, 1, 2] for off in [0, 4, 0x10, 0x18, 0x20]}
        self.config.update({(0, 0): 0x24641b21, (1, 0): 0x24641b21,
                            (2, 0): 0x048010ee, (2, 4): 0x140, (2, 0x10): 0x80000000})
        self.original = copy.deepcopy(self.config)
        self.memory = {0x3000: 0x56595043, 0x3004: 5, 0x3008: 0x30000, 0: 4}
        self.mask = 0xffff0000
        self.calls = []
        self.closed = False
        self.read_error = False

    def read(self, address, size):
        return b'\x78'

    def pcie_cfg_req(self, offset, bus=0, value=None, size=4):
        key = (bus, offset)
        if value is None:
            value = self.config[key]
            return self.mask if key == (2, 0x10) and value == 0xffffffff else value
        self.config[key] = value

    def pcie_request(self, kind, address, value=None):
        offset = address - ChestnutPcie.BAR_BASE
        self.calls.append((kind, offset, value))
        if kind == 0:
            if self.read_error:
                raise PcieCompletionError(address, 1, 4)
            return self.memory.get(offset, 0)
        self.memory[offset] = value

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'device.lock'
        self.usb = FakeUsb()

    def tearDown(self):
        self.directory.cleanup()

    def test_identity_configuration_restored(self):
        card = ChestnutPcie(usb=self.usb, lock_path=self.path)
        self.assertEqual(card.identity['board_abi'], 5)
        self.assertFalse(card.physical)
        self.assertEqual(self.usb.config[(2, 0x10)], 0x10000000)
        card.close()
        self.assertEqual(self.usb.config, self.usb.original)
        self.assertTrue(self.usb.closed)

    def test_wrong_endpoint_restores_changed_bridge_configuration(self):
        self.usb.config[(2, 0)] = 0x702810ee
        self.usb.original = copy.deepcopy(self.usb.config)
        with self.assertRaisesRegex(RuntimeError, '10ee:0480'):
            ChestnutPcie(usb=self.usb, lock_path=self.path)
        self.assertEqual(self.usb.config, self.usb.original)
        self.assertTrue(self.usb.closed)

    def test_wrong_bar_mask_restores_probe_and_command(self):
        self.usb.mask = 0xfffff000
        with self.assertRaisesRegex(RuntimeError, 'size mismatch'):
            ChestnutPcie(usb=self.usb, lock_path=self.path)
        self.assertEqual(self.usb.config, self.usb.original)

    def test_wrong_abi_restores_all_configuration(self):
        self.usb.memory[0x3004] = 4
        with self.assertRaisesRegex(RuntimeError, 'ABI5'):
            ChestnutPcie(usb=self.usb, lock_path=self.path)
        self.assertEqual(self.usb.config, self.usb.original)

    def test_posted_write_is_fenced_and_valid_all_ones_data_is_allowed(self):
        card = ChestnutPcie(usb=self.usb, lock_path=self.path)
        card.write32(0x2040, 0xffffffff)
        self.assertEqual(self.usb.calls[-2:], [(0x40, 0x2040, 0xffffffff), (0, 0x3008, None)])
        self.assertEqual(card.read32(0x2040), 0xffffffff)
        card.close()

    def test_completion_failure_quarantines_without_retry(self):
        card = ChestnutPcie(usb=self.usb, lock_path=self.path)
        self.usb.read_error = True
        before = len(self.usb.calls)
        with self.assertRaises(PcieCompletionError):
            card.read32(0x2000)
        self.assertTrue(card.failed)
        with self.assertRaisesRegex(RuntimeError, 'quarantined'):
            card.write32(0x2000, 1)
        self.assertEqual(len(self.usb.calls), before + 1)
        card.close()
        self.assertEqual(self.usb.config, self.usb.original)

    def test_posted_write_fence_error_is_not_retried(self):
        card = ChestnutPcie(usb=self.usb, lock_path=self.path)
        self.usb.memory[0x3008] = 0x800
        with self.assertRaisesRegex(RuntimeError, 'fence'):
            card.write32(0x2000, 7)
        self.assertTrue(card.failed)
        self.assertEqual(sum(kind == 0x40 for kind, _, _ in self.usb.calls), 1)
        card.close()

    def test_shared_device_lock(self):
        card = ChestnutPcie(usb=self.usb, lock_path=self.path)
        with self.assertRaisesRegex(RuntimeError, 'already owned'):
            ChestnutPcie(usb=FakeUsb(), lock_path=self.path)
        card.close()
        next_card = ChestnutPcie(usb=FakeUsb(), lock_path=self.path)
        next_card.close()

    def test_restore_failure_still_closes_USB_and_releases_lock(self):
        card = ChestnutPcie(usb=self.usb, lock_path=self.path)
        original_cfg = self.usb.pcie_cfg_req

        def fail_one_restore(offset, bus=0, value=None, size=4):
            if bus == 2 and offset == 0x10 and value == 0x80000000:
                raise OSError('Injected restore failure')
            return original_cfg(offset, bus=bus, value=value, size=size)

        self.usb.pcie_cfg_req = fail_one_restore
        with self.assertRaisesRegex(RuntimeError, 'restoration failed'):
            card.close()
        self.assertTrue(self.usb.closed)
        next_card = ChestnutPcie(usb=FakeUsb(), lock_path=self.path)
        next_card.close()


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()
        self.transport.mutex = threading.RLock()
        self.transport.read32.side_effect = lambda offset: offset
        self.server = MmioServer(self.transport)

    def tearDown(self):
        self.server.close()

    def test_batches_and_writes(self):
        self.assertEqual(self.server.transact(b'BR 2000 02\n'), b'OK 00002000 00002004\n')
        self.assertEqual(self.server.transact(b'BW 2040 02 01234567 ffffffff\n'), b'OK 00000000\n')
        self.assertEqual(self.transport.write32.call_args_list[1].args, (0x2044, 0xffffffff))

    def test_rejects_invalid_frames_before_any_write(self):
        for line in [b'BW 2000 02 00000001\n', b'BR fffc 02\n', b'BR 2000 11\n',
                     b'W 2001 00000001\n', b'W 2000 fffffffff\n', b'R 2000 extra\n',
                     b'BW 2000 00\n', b'R 2000', b'W 0000 ' + b'1' * 257 + b'\n']:
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.server.transact(line)
        self.transport.write32.assert_not_called()

    def test_only_one_client_and_close_drains_threads(self):
        port = self.server.start()
        with socket.create_connection(('127.0.0.1', port)) as first:
            first.sendall(b'R 3000\n')
            self.assertEqual(first.recv(128), b'OK 00003000\n')
            with socket.create_connection(('127.0.0.1', port)) as second:
                self.assertIn(b'ERR client already connected', second.recv(128))
        self.server.close()
        self.assertFalse(self.server.thread.is_alive())

    def test_sequential_client_waits_for_previous_handler_teardown(self):
        teardown = threading.Event()
        release = threading.Event()
        waiting = threading.Event()
        drained = threading.Event()
        errors = []
        shutdown = self.server.shutdown_request

        def delayed_shutdown(request):
            teardown.set()
            if not release.wait(5):
                errors.append('Teardown was not released')
            shutdown(request)

        def wait_for_drain():
            waiting.set()
            try:
                self.server.wait_idle(timeout=5)
            except BaseException as error:
                errors.append(error)
            drained.set()

        self.server.shutdown_request = delayed_shutdown
        port = self.server.start()
        waiter = threading.Thread(target=wait_for_drain)
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=5) as first:
                first.sendall(b'R 3000\n')
                self.assertEqual(first.recv(128), b'OK 00003000\n')
            self.assertTrue(teardown.wait(5))
            waiter.start()
            self.assertTrue(waiting.wait(5))
            with self.assertRaisesRegex(TimeoutError, 'did not drain'):
                self.server.wait_idle(timeout=0)
            self.assertFalse(drained.is_set())
            self.transport.write32.assert_not_called()
            release.set()
            self.assertTrue(drained.wait(5))
            self.assertFalse(errors)
            with socket.create_connection(('127.0.0.1', port), timeout=5) as second:
                second.sendall(b'R 3004\n')
                self.assertEqual(second.recv(128), b'OK 00003004\n')
            self.server.wait_idle(timeout=5)
        finally:
            release.set()
            if waiter.ident is not None:
                waiter.join(timeout=5)
        self.assertFalse(waiter.is_alive())

    def test_drain_rejects_failed_or_closed_server(self):
        self.server.last_error = 'Injected transport failure'
        with self.assertRaisesRegex(RuntimeError, 'Injected transport failure'):
            self.server.wait_idle(timeout=0)
        self.server.last_error = None
        self.server.close()
        with self.assertRaisesRegex(RuntimeError, 'closing'):
            self.server.wait_idle(timeout=0)


class UsbReplyTests(unittest.TestCase):
    def test_bridge_status_failure_is_checked(self):
        usb = _ChestnutUsb.__new__(_ChestnutUsb)
        usb.control = Mock(side_effect=[b'', bytes(7) + b'\x01'])
        with self.assertRaises(PcieCompletionError) as caught:
            usb.pcie_request(0, 0x10000000)
        self.assertEqual(caught.exception.status, 1)
        self.assertEqual(caught.exception.completion, 0)

    def test_pcie_completion_and_bridge_status_are_checked(self):
        usb = _ChestnutUsb.__new__(_ChestnutUsb)
        usb.control = Mock(side_effect=[b'', struct.pack('<I', 5) + b'\x80\x00\x00\x00'])
        with self.assertRaises(PcieCompletionError) as caught:
            usb.pcie_request(0, 0x10000000)
        self.assertEqual(caught.exception.completion, 4)

    def test_posted_write_has_no_fabricated_completion(self):
        usb = _ChestnutUsb.__new__(_ChestnutUsb)
        usb.control = Mock(return_value=b'')
        self.assertIsNone(usb.pcie_request(0x40, 0x10000000, 42))
        self.assertEqual(usb.control.call_count, 1)

    def test_subword_request_byte_enable_and_shift(self):
        usb = _ChestnutUsb.__new__(_ChestnutUsb)
        usb.control = Mock(side_effect=[b'', struct.pack('<I', 0xab00) + bytes(4)])
        self.assertEqual(usb.pcie_request(0, 0x10000001, size=1), 0xab)
        self.assertEqual(usb.control.call_args_list[0].args[2], 0x200)


if __name__ == '__main__':
    unittest.main()
