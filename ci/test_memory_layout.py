from pathlib import Path
import re
import subprocess

import pytest


@pytest.mark.parametrize('xlen,size,capacity,stack,page', [
    (32, None, 0x100000000, 0xffff0000, 0xf0000000),
    (64, None, 0x200000000, 0x1ffff0000, 0xf0000000),
    (32, 0x80000000, 0x80000000, 0x7fff0000, 0x70000000),
])
def test_configured_memory_layout(tmp_path, xlen, size, capacity, stack, page):
    current = Path.cwd()
    config = (current / 'config.mk').read_text()
    root = Path(config.split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    tools = config.split('TOOLDIR ?= ', 1)[1].splitlines()[0]
    command = [str(root / 'configure'), f'--xlen={xlen}', f'--tooldir={tools}',
               '--osversion=ubuntu/focal']
    if size is not None:
        command.append(f'--memory-size={size}')
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    header = (tmp_path / 'sw/VX_types.h').read_text()

    def value(name):
        return int(re.search(r'^#define ' + name + r' (\S+)', header, re.M)[1], 0)

    assert value('VX_MEM_GLOBAL_SIZE') == capacity
    assert value('VX_MEM_STACK_BASE_ADDR') == stack
    assert value('VX_MEM_LMEM_BASE_ADDR') == stack
    assert value('VX_MEM_PAGE_TABLE_BASE_ADDR') == page
    assert value('VX_MEM_OM_END_ADDR') == page
    if size is not None:
        before = header
        result = subprocess.run([str(root / 'configure')], cwd=tmp_path,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (tmp_path / 'sw/VX_types.h').read_text() == before
