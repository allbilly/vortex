import hashlib
import json
from pathlib import Path
import runpy

import pytest


@pytest.mark.parametrize('change', ['none', 'rtl', 'firmware', 'constraints', 'source', 'ecc', 'clock', 'abi', 'size'])
def test_controller_binding(tmp_path, change):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    check = runpy.run_path(str(root / 'hw/syn/xilinx/ypcb/build_vivado.py'))['wl_controller']
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    files = {'gateware/ypcb_ddr3.v': b'module ypcb_ddr3; endmodule\n',
             'phase-constraints.tcl': b'set_clock_uncertainty 1.3\n',
             'selfcal_fw/firmware.bin': b'\x13\x00\x00\x00', 'source.c': b'void boot(void) {}\n'}
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    firmware = {'firmware_id': 1, 'bytes': 4, 'memory_bytes': 16384,
                'sha256': sha(tmp_path / 'selfcal_fw/firmware.bin'),
                'inputs': {str(tmp_path / 'source.c'): sha(tmp_path / 'source.c')}}
    profile = {'board_abi': 4, 'input_clock_hz': 50000000, 'controller_clock_hz': 100000000,
               'ddr_data_rate': 800000000, 'physical_lanes': 9, 'payload_bytes': 2147483648,
               'ecc': True, 'phase_uncertainty_ns': 1.3, 'eligible_for_synthesis': True}
    profile['source_sha256'] = {str(tmp_path / 'source.c'): sha(tmp_path / 'source.c')}
    export = {'board_abi': 4, 'controller': 'WL7DDRPHY', 'profile': profile,
              'standalone_verilog_sha256': sha(tmp_path / 'gateware/ypcb_ddr3.v'),
              'phase_constraints_sha256': sha(tmp_path / 'phase-constraints.tcl')}
    mutations = {'rtl': 'gateware/ypcb_ddr3.v', 'firmware': 'selfcal_fw/firmware.bin',
                 'constraints': 'phase-constraints.tcl', 'source': 'source.c'}
    if change in mutations:
        path = tmp_path / mutations[change]
        path.write_bytes(path.read_bytes() + b'changed')
    elif change == 'ecc':
        profile['ecc'] = False
    elif change == 'clock':
        profile['input_clock_hz'] = 200000000
    elif change == 'abi':
        export['board_abi'] = 3
    elif change == 'size':
        firmware['memory_bytes'] = 32768
    (tmp_path / 'selfcal-export.json').write_text(json.dumps(export))
    (tmp_path / 'selfcal_fw/manifest.json').write_text(json.dumps(firmware))
    if change == 'none':
        assert check(tmp_path)['firmware_id'] == 1
    else:
        with pytest.raises(ValueError):
            check(tmp_path)
