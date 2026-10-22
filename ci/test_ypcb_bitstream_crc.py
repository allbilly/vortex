from pathlib import Path
import json
import struct
import subprocess

import pytest


def root_directory():
    return Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])


@pytest.fixture(scope='module')
def checker(tmp_path_factory):
    output = tmp_path_factory.mktemp('ypcb-crc') / 'series7-crc'
    source = root_directory() / 'hw/syn/xilinx/ypcb/series7_crc.cpp'
    subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(source), '-o', str(output)], check=True)
    return output


def packet(register, values):
    if len(values) > 2047:
        words = [0x30000000 | register << 13, 0x50000000 | len(values), *values]
    else:
        words = [0x30000000 | register << 13 | len(values), *values]
    return struct.pack('>' + 'I' * len(words), *words)


def update_crc(state, register, value):
    for bit in [*(value >> index & 1 for index in range(32)),
                *(register >> index & 1 for index in range(5))]:
        feedback = (state & 1) ^ bit
        state >>= 1
        if feedback:
            state ^= 0x82f63b78
    return state


@pytest.fixture(scope='module')
def configuration():
    payload = bytes.fromhex('ffffffff aa995566')
    offsets = {}
    state = 0
    writes = [('reset', 4, [7]), ('idcode', 12, [0x03751093]),
              ('frames', 2, [0x12345678] * 100001), ('frame_crc', 0, None),
              ('restore', 4, [10]), ('high', 4, [3]), ('start', 4, [5]),
              ('far', 1, [0x03be0000]), ('mask', 6, [0x501]), ('ctl', 5, [0x501]),
              ('startup_crc', 0, None), ('desync', 4, [13])]
    for name, register, values in writes:
        offsets[name] = len(payload)
        if values is None:
            values = [state]
            state = 0
        elif name == 'reset':
            state = 0
        else:
            for value in values:
                state = update_crc(state, register, value)
        payload += packet(register, values)
    payload += bytes.fromhex('20000000')
    return payload, offsets


def bitstream(payload):
    signature = bytes.fromhex('0ff00ff00ff00ff000')
    data = struct.pack('>H', len(signature)) + signature + b'\0\1'
    for tag, value in [('a', 'test'), ('b', 'xc7k480tffg1156-2'),
                       ('c', '2026/10/23'), ('d', '00:00:00')]:
        value = value.encode() + b'\0'
        data += tag.encode() + struct.pack('>H', len(value)) + value
    return data + b'e' + struct.pack('>I', len(payload)) + payload


def check(checker, tmp_path, payload):
    path = tmp_path / 'fixture.bit'
    path.write_bytes(bitstream(payload))
    return subprocess.run([str(checker), str(path)], capture_output=True, text=True, timeout=10)


def test_full_device_crc_coverage(checker, configuration, tmp_path):
    result = check(checker, tmp_path, configuration[0])
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['crc_checkpoints'] == 2
    assert report['fdri_words'] == report['fdri_words_checked'] == 100001
    assert report['crc_coverage_complete'] is True
    assert report['startup_crc_checked'] is True
    assert report['known_answer_vectors'] == 4


@pytest.mark.parametrize('mutation', ['crc_header_bit', 'missing_frame_crc', 'missing_startup_crc',
                                     'duplicate_startup_crc', 'crc_reset_discards_frames',
                                     'frame_data_after_start', 'write_after_startup_crc',
                                     'write_after_desync', 'duplicate_start', 'bad_crc',
                                     'corrupt_frame_data'])
def test_incomplete_or_corrupt_configuration_rejected(checker, configuration, tmp_path, mutation):
    payload, offsets = configuration
    data = bytearray(payload)
    if mutation == 'crc_header_bit':
        index = offsets['startup_crc']
        header = int.from_bytes(data[index:index + 4], 'big') ^ (1 << 13)
        data[index:index + 4] = header.to_bytes(4, 'big')
    elif mutation in ('missing_frame_crc', 'missing_startup_crc'):
        index = offsets['frame_crc' if mutation == 'missing_frame_crc' else 'startup_crc']
        data[index:index + 8] = bytes.fromhex('20000000 20000000')
    elif mutation == 'duplicate_startup_crc':
        index = offsets['desync']
        data[index:index] = packet(0, [0])
    elif mutation == 'crc_reset_discards_frames':
        index = offsets['frame_crc']
        data[index:index + 8] = packet(4, [7])
    elif mutation == 'frame_data_after_start':
        index = offsets['startup_crc']
        data[index:index] = packet(2, [0x12345678])
    elif mutation == 'write_after_startup_crc':
        index = offsets['desync']
        data[index:index] = packet(1, [0])
    elif mutation == 'write_after_desync':
        data += packet(1, [0])
    elif mutation == 'duplicate_start':
        index = offsets['far']
        data[index:index] = packet(4, [5])
    elif mutation == 'bad_crc':
        data[offsets['startup_crc'] + 7] ^= 1
    elif mutation == 'corrupt_frame_data':
        data[offsets['frames'] + 8] ^= 1
    result = check(checker, tmp_path, data)
    assert result.returncode != 0, result.stdout
