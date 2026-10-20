import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


def tools():
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    board = root / 'hw/syn/xilinx/ypcb'
    return (runpy.run_path(str(board / 'verify_vivado_reports.py'))['evaluate'],
            runpy.run_path(str(board / 'finalize_vivado.py'))['prepare'])


def reports(directory, failure_kind=None):
    directory.mkdir()
    timing = '0.068 0.000 0 100 0.031 0.000 0 100 0.000 0.000 0 100'
    if failure_kind == 'timing':
        timing = '-0.001 -0.001 1 100 0.031 0.000 0 100 0.000 0.000 0 100'
    (directory / 'timing-summary.rpt').write_text('Design Timing Summary\n' + timing + '\n')
    (directory / 'route-status.rpt').write_text(
        '# of routable nets : 100\n# of fully routed nets : 100\n# of nets with routing errors : 0\n')
    (directory / 'check-timing-routed.rpt').write_text(
        'checking no_clock (0)\nchecking unconstrained_internal_endpoints (0)\n')
    (directory / 'drc-routed.rpt').write_text('| example | Warning | retained warning |\n')
    groups = []
    for index in range(14):
        instance = 'axi_crossing_1' if index < 10 else 'csr_crossing_1'
        number = index if index < 10 else index - 10
        if failure_kind == 'wrong_design_group' and index == 13:
            instance, number = 'axi_crossing_1', 10
        if failure_kind == 'duplicate_gray' and index == 1:
            number = 0
        if failure_kind == 'missing_gray' and index == 1:
            continue
        source = [f'{instance}/clockdomaincrossing0_cdc_graycounter{number}_q_reg[{bit}]' for bit in range(3)]
        target = [f'{instance}/xilinxmultiregimpl{number}_regs0_reg[{bit}]' for bit in range(3)]
        if failure_kind == 'wrong_bit' and index == 0:
            target[1] = target[0]
        groups.append((source, target, '0.500', '7.500'))
    for index in range(12):
        if failure_kind == 'missing_vendor' and index == 11:
            continue
        instance = 'jtag' if index < 8 else 'dbg_hub'
        if failure_kind == 'unknown' and index == 0:
            instance = 'unreviewed'
        actual, slack = ('8.001', '-0.001') if failure_kind == 'vendor_skew' and index == 0 else ('0.500', '7.500')
        groups.append(([f'{instance}/source{index}[0]'], [f'{instance}/target{index}[0]'], actual, slack))
    text = '1. Bus Skew Report Summary\n--------------------------\n'
    for index, (source, target, actual, slack) in enumerate(groups, 1):
        selectors = ['[get_cells [list ' + ' '.join('{' + name + '}' for name in names) + ']]'
                     for names in (source, target)]
        text += f'{index} {index + 10} {selectors[0]}\n {selectors[1]}\n Slow 8.000 {actual} {slack}\n'
    text += '\n2. Bus Skew Report Per Constraint\n--------------------------------\n'
    for index, (_, target, actual, slack) in enumerate(groups, 1):
        status = 'VIOLATED' if slack.startswith('-') else 'MET'
        text += f'Id: {index}\nRequirement: 8.000ns\nEndpoints: {len(target)}\nSlack ({status}) : {slack}ns\n'
    if failure_kind == 'truncated':
        text = text.rsplit('Slack (', 1)[0]
    (directory / 'bus-skew.rpt').write_text(text)


@pytest.mark.parametrize('failure_kind', [None, 'missing_gray', 'duplicate_gray', 'wrong_bit',
                                        'wrong_design_group', 'missing_vendor', 'vendor_skew', 'unknown'])
def test_all_design_and_vendor_skew_constraints(tmp_path, failure_kind):
    evaluate, _ = tools()
    directory = tmp_path / 'reports'
    reports(directory, failure_kind)
    result = evaluate(directory)
    assert result['checks']['gray_skew'] == (failure_kind is None)
    if failure_kind is None:
        assert result['gray_buses'] == 14
        assert result['vendor_skew_constraints'] == 12
        assert result['total_skew_constraints'] == 26
        assert all(result['checks'].values())


def test_truncated_skew_detail_is_rejected(tmp_path):
    evaluate, _ = tools()
    directory = tmp_path / 'reports'
    reports(directory, 'truncated')
    with pytest.raises(ValueError, match='bus skew detail'):
        evaluate(directory)


@pytest.mark.parametrize('failure_kind', [None, 'corrupt_input', 'interrupted', 'timing'])
def test_routed_finalization_preflight(tmp_path, failure_kind):
    _, prepare = tools()
    original, output = tmp_path / 'original', tmp_path / 'output'
    reports(original, failure_kind)
    source = original / 'frozen.sv'
    source.write_text('module frozen; endmodule\n')
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    (original / 'inputs.json').write_text(json.dumps({'source_revision': 'fixture', 'inputs': {'frozen.sv': expected}}))
    (original / 'implement-exit.json').write_text(json.dumps({'exit_code': 1, 'interrupted': 15 if failure_kind == 'interrupted' else 0}))
    (original / 'implement.log').write_text('completed route; verifier rejected total count\n')
    (original / 'routed.dcp').write_bytes(b'fixture routed checkpoint')
    if failure_kind == 'corrupt_input':
        source.write_text('module changed; endmodule\n')
    if failure_kind is None:
        result = prepare(original, output)
        assert (output / 'routed.dcp').read_bytes() == b'fixture routed checkpoint'
        for name, digest in result['inputs'].items():
            assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
        assert not (output / 'vortex_ypcb.bit').exists()
    else:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            prepare(original, output)
        assert not output.exists()


@pytest.mark.parametrize('failure_kind', [None, 'active', 'corrupt_input', 'timing', 'bad_synthesis', 'no_opt_in'])
def test_abandoned_routed_recovery(tmp_path, monkeypatch, failure_kind):
    _, prepare = tools()
    original, output = tmp_path / 'original', tmp_path / 'output'
    reports(original, failure_kind)
    source = original / 'frozen.sv'
    source.write_text('module frozen; endmodule\n')
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    (original / 'inputs.json').write_text(json.dumps({'source_revision': 'fixture', 'inputs': {'frozen.sv': expected}}))
    (original / 'progress.json').write_text(json.dumps({'stage': 'implement', 'pid': 123, 'running': True}))
    (original / 'synthesize-exit.json').write_text(json.dumps({'exit_code': 1 if failure_kind == 'bad_synthesis' else 0, 'interrupted': 0}))
    (original / 'implement.log').write_text('route checkpoint and reports saved; bitstream producer interrupted\n')
    (original / 'routed.dcp').write_bytes(b'verified abandoned checkpoint')
    if failure_kind == 'corrupt_input':
        source.write_text('module changed; endmodule\n')
    monkeypatch.setitem(prepare.__globals__, 'active_producers',
                        lambda path: [{'pid': 123}] if failure_kind == 'active' else [])
    if failure_kind is None:
        result = prepare(original, output, recover_abandoned=True)
        recovery = result['routed_finalization']['abandoned_producer_recovery']
        assert recovery['original_exit_receipt'] is None
        assert result['routed_finalization']['original_implementation_exit_sha256'] is None
        assert not (original / 'implement-exit.json').exists()
        assert not (output / 'finalize-exit.json').exists()
        assert not (output / 'vortex_ypcb.bit').exists()
        for name, digest in result['inputs'].items():
            assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    else:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            prepare(original, output, recover_abandoned=failure_kind != 'no_opt_in')
        assert not output.exists()


@pytest.mark.parametrize('joined', [False, True])
def test_recovery_detects_actual_live_producer(tmp_path, joined):
    _, prepare = tools()
    arguments = ['--output=' + str(tmp_path)] if joined else [str(tmp_path)]
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', 'build_vivado.py', *arguments],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        found = prepare.__globals__['active_producers'](tmp_path)
        assert child.pid in [item['pid'] for item in found]
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_recovery_cli_excludes_its_own_wrapper(tmp_path):
    root = Path((Path.cwd() / 'config.mk').read_text().split('VORTEX_HOME ?= ', 1)[1].splitlines()[0])
    original, output = tmp_path / 'original', tmp_path / 'output'
    reports(original)
    (original / 'inputs.json').write_text(json.dumps({'source_revision': 'fixture', 'inputs': {}}))
    (original / 'progress.json').write_text(json.dumps({'stage': 'implement', 'pid': 123, 'running': True}))
    (original / 'synthesize-exit.json').write_text(json.dumps({'exit_code': 0, 'interrupted': 0}))
    (original / 'implement.log').write_text('completed routing; producer interrupted\n')
    (original / 'routed.dcp').write_bytes(b'fixture checkpoint')
    result = subprocess.run(['bash', '-c', '"$@"; result=$?; exit "$result"', 'wrapper',
                             sys.executable, str(root / 'hw/syn/xilinx/ypcb/finalize_vivado.py'),
                             '--run', str(original), '--output', str(output),
                             '--recover-abandoned-run', '--vivado', '/bin/false'],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert 'Routed finalization failed' in result.stderr
    metadata = json.loads((output / 'inputs.json').read_text())
    assert metadata['routed_finalization']['abandoned_producer_recovery']['original_exit_receipt'] is None
    assert json.loads((output / 'finalize-exit.json').read_text())['exit_code'] == 1
