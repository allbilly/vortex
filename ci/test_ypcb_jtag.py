import socket
import subprocess
import threading
from pathlib import Path

import pytest


@pytest.mark.parametrize('failure', [False, True])
def test_jtag_mmio_protocol_and_poisoning(tmp_path, failure):
    build = Path.cwd()
    config = (build / 'config.mk').read_text()
    root = Path(config.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    source = tmp_path / 'main.cpp'
    source.write_text('''#include <ypcb_jtag.h>
#include <cstdlib>
int main(int argc, char** argv) {
  if (argc != 3) return 10;
  vortex::ypcb::Jtag jtag;
  if (jtag.connect(std::strtoul(argv[1], nullptr, 10))) return 11;
  uint32_t value = 0;
  int result = jtag.read32(0x3000, &value);
  if (argv[2][0] == '1') {
    if (result == 0 || jtag.write32(0x3010, 1) == 0) return 12;
  } else {
    if (result || value != 0x56595043 || jtag.write32(0x3010, 1)) return 13;
    if (jtag.read32(3, &value) == 0 || jtag.read32(65536, &value) == 0) return 14;
  }
  return 0;
}
''')
    executable = tmp_path / 'probe'
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
                    '-I' + str(root / 'sw/common'), str(source),
                    str(root / 'sw/common/ypcb_jtag.cpp'), '-o', str(executable)],
                   check=True, capture_output=True, timeout=60)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(10)
    requests = []
    errors = []

    def serve():
        try:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(10)
                stream = connection.makefile('rwb')
                with stream:
                    requests.append(stream.readline())
                    stream.write(b'ERR AXI transport error\n' if failure else b'OK 56595043\n')
                    stream.flush()
                    request = stream.readline()
                    if request:
                        requests.append(request)
                        stream.write(b'OK 00000000\n')
                        stream.flush()
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        result = subprocess.run([str(executable), str(listener.getsockname()[1]),
                                 str(int(failure))], capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr.decode()
    finally:
        thread.join(timeout=15)
        listener.close()
    assert not thread.is_alive()
    assert not errors
    assert requests == ([b'R 3000\n'] if failure else [b'R 3000\n', b'W 3010 00000001\n'])


@pytest.mark.parametrize('fault', ['none', 'short', 'long', 'hex', 'error', 'closed'])
def test_jtag_register_batches(tmp_path, fault):
    config = (Path.cwd() / 'config.mk').read_text()
    root = Path(config.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    source = tmp_path / 'batch.cpp'
    source.write_text('''#include <ypcb_jtag.h>
#include <array>
#include <cstdlib>
int main(int argc, char** argv) {
  if (argc != 3) return 1;
  vortex::ypcb::Jtag jtag;
  if (jtag.connect(std::strtoul(argv[1], nullptr, 10))) return 2;
  std::array<uint32_t, 16> words{};
  if (!jtag.read_words(3, words.data(), 16) || !jtag.read_words(65532, words.data(), 2)
      || !jtag.read_words(0, nullptr, 1) || !jtag.read_words(0, words.data(), 0)
      || !jtag.read_words(0, words.data(), 17)) return 3;
  const auto result = jtag.read_words(0x2100, words.data(), 16);
  if (argv[2][0] == '1') {
    return result && jtag.write_words(0x2100, words.data(), 16) ? 0 : 4;
  }
  if (result) return 5;
  for (unsigned i = 0; i < words.size(); ++i) if (words[i] != 0x100 + i) return 6;
  if (jtag.write_words(0x2100, words.data(), 16)) return 7;
  uint32_t signature;
  return jtag.read32(0x3000, &signature) || signature != 0x56595043 ? 8 : 0;
}
''')
    executable = tmp_path / 'batch'
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
                    '-I' + str(root / 'sw/common'), str(source),
                    str(root / 'sw/common/ypcb_jtag.cpp'), '-o', str(executable)],
                   check=True, capture_output=True, timeout=60)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(10)
    requests, errors = [], []
    words = [f'{0x100+i:08x}' for i in range(16)]

    def serve():
        try:
            connection, _ = listener.accept()
            with connection, connection.makefile('rwb') as stream:
                connection.settimeout(10)
                requests.append(stream.readline())
                if fault == 'closed':
                    return
                response = words.copy()
                if fault == 'short': response.pop()
                if fault == 'long': response.append('00000000')
                if fault == 'hex': response[7] = 'xyz00000'
                text = 'ERR injected failure' if fault == 'error' else 'OK ' + ' '.join(response)
                # Exercise partial socket deliveries as well as the maximum response size.
                for fragment in (text[:5], text[5:] + '\n'):
                    stream.write(fragment.encode())
                    stream.flush()
                request = stream.readline()
                if request:
                    requests.append(request)
                    stream.write(b'OK 00000000\n')
                    stream.flush()
                    requests.append(stream.readline())
                    stream.write(b'OK 56595043\n')
                    stream.flush()
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        result = subprocess.run([str(executable), str(listener.getsockname()[1]),
                                 str(int(fault != 'none'))], capture_output=True, timeout=15)
        assert result.returncode == 0, (fault, result.returncode, result.stderr.decode())
    finally:
        thread.join(timeout=15)
        listener.close()
    assert not thread.is_alive() and not errors
    expected = [b'BR 2100 10\n']
    if fault == 'none':
        expected += [('BW 2100 10 ' + ' '.join(words) + '\n').encode(), b'R 3000\n']
    assert requests == expected


def test_jtag_tcl_queue_and_request_validation(tmp_path):
    config = (Path.cwd() / 'config.mk').read_text()
    root = Path(config.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    board = root / 'hw/syn/xilinx/ypcb'
    result = subprocess.run(['tclsh', str(board / 'tests/jtag_batch.tcl'), str(board / 'jtag_server.tcl')],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASSED:' in result.stdout
