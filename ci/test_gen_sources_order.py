import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('mode', ['original', 'copy', 'preprocess'])
def test_explicit_package_order_elaborates_parameterized_interface(tmp_path, mode):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    verilator = shutil.which('verilator')
    assert verilator, 'The configured Verilator must be on PATH'
    source = tmp_path / 'source'
    source.mkdir()
    files = {
        'a_user_pkg.sv': ('package a_user_pkg; import z_base_pkg::*; '
                          'typedef struct packed { payload_t payload; } message_t; endpackage\n'),
        'z_base_pkg.sv': ('package z_base_pkg; typedef union packed { '
                          'logic [7:0] data; logic [7:0] mask; } payload_t; endpackage\n'),
        'test_if.sv': ('interface test_if #(parameter WIDTH=8); '
                       'logic [WIDTH-1:0] data; endinterface\n'),
        'leaf.sv': ('module leaf #(parameter WIDTH=8) (test_if bus, output wire [WIDTH-1:0] value); '
                    'assign value=bus.data; endmodule\n'),
        'top.sv': ('module top #(parameter WIDTH=8) (input wire [WIDTH-1:0] value, '
                   'output wire [WIDTH-1:0] result); import a_user_pkg::*; message_t message; '
                   'test_if #(WIDTH) bus(); assign bus.data=value; '
                   'leaf #(WIDTH) u_leaf(bus,result); assign message.payload.data=value[7:0]; endmodule\n'),
    }
    for name, text in files.items():
        (source / name).write_text(text)
    filelist = tmp_path / 'sources.f'
    command = ['bash', str(root / 'hw/scripts/gen_sources.sh'), '-I' + str(source),
               '-Ttop', '-O' + str(filelist)]
    if mode != 'original':
        command += ['-C' + str(tmp_path / 'export')]
    if mode == 'preprocess':
        command += ['-P']
    command += [str(source / name) for name in ['z_base_pkg.sv', 'a_user_pkg.sv']]
    subprocess.run(command, env=dict(os.environ, VERILATOR=verilator), check=True,
                   capture_output=True, text=True)
    names = [Path(line).name for line in filelist.read_text().splitlines() if not line.startswith('+')]
    assert names[:2] == ['z_base_pkg.sv', 'a_user_pkg.sv']
    assert len(names) == len(set(names))
    subprocess.run([verilator, '--lint-only', '-Wno-fatal', '--top-module', 'top',
                    '-GWIDTH=16', '-f', str(filelist)], check=True, capture_output=True, text=True)
