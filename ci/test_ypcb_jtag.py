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
