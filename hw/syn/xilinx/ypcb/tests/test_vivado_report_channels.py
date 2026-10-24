#!/usr/bin/env python3
"""Focused channel-count checks for Vivado report parsing; fixtures are not physical evidence."""

import argparse
import hashlib
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest


BOARD = Path(__file__).resolve().parents[1]
evaluate = runpy.run_path(str(BOARD / 'verify_vivado_reports.py'))['evaluate']
LEGACY_REPORT_DIR = None
REPORT_NAMES = ('timing-summary.rpt', 'bus-skew.rpt', 'route-status.rpt',
                'check-timing-routed.rpt', 'drc-routed.rpt')


def report_hashes(directory):
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in REPORT_NAMES}


def copy_reports(source, destination):
    destination.mkdir()
    for name in REPORT_NAMES:
        shutil.copy2(source / name, destination / name)


def complete_dual_bus_skew(mutation=None):
    design = []
    for channel in (0, 1):
        for kind, count in (('axi', 10), ('csr', 4)):
            for number in range(count):
                instance = f'{kind}_crossing_{channel}'
                design.append((
                    [f'{instance}/clockdomaincrossing0_cdc_graycounter{number}_q_reg[{bit}]'
                     for bit in range(3)],
                    [f'{instance}/xilinxmultiregimpl{number}_regs0_reg[{bit}]'
                     for bit in range(3)]))
    vendors = [([f'jtag/source{index}[0]'], [f'jtag/target{index}[0]'])
               for index in range(8)]
    vendors += [([f'dbg_hub/source{index}[0]'], [f'dbg_hub/target{index}[0]'])
                for index in range(4)]
    if mutation == 'missing':
        design.pop()
    elif mutation == 'duplicate':
        design.append(design[0])
    elif mutation == 'unknown':
        vendors[0] = (['unreviewed/source0[0]'], ['unreviewed/target0[0]'])
    elif mutation == 'cross_channel':
        sources, destinations = design[0]
        design[0] = (sources, [name.replace('axi_crossing_0/', 'axi_crossing_1/')
                               for name in destinations])
    groups = design + vendors
    text = '1. Bus Skew Report Summary\n--------------------------\n'
    for index, (sources, destinations) in enumerate(groups, 1):
        selectors = ['[get_cells [list ' + ' '.join('{' + name + '}' for name in names) + ']]'
                     for names in (sources, destinations)]
        text += (f'{index} {index + 100} {selectors[0]}\n {selectors[1]}\n'
                 ' Slow 8.000 0.500 7.500\n')
    text += '\n2. Bus Skew Report Per Constraint\n--------------------------------\n'
    for index, (_, destinations) in enumerate(groups, 1):
        text += (f'Id: {index}\nRequirement: 8.000ns\nEndpoints: {len(destinations)}\n'
                 'Slack (MET) : 7.500ns\n')
    return text


def complete_reports(directory, mutation=None):
    directory.mkdir()
    (directory / 'timing-summary.rpt').write_text(
        'Design Timing Summary\n0.068 0.000 0 100 0.031 0.000 0 100 0.000 0.000 0 100\n')
    (directory / 'bus-skew.rpt').write_text(complete_dual_bus_skew(mutation))
    (directory / 'route-status.rpt').write_text(
        '# of routable nets : 100\n# of fully routed nets : 100\n# of nets with routing errors : 0\n')
    (directory / 'check-timing-routed.rpt').write_text(
        'checking no_clock (0)\nchecking unconstrained_internal_endpoints (0)\n')
    (directory / 'drc-routed.rpt').write_text(
        '| Design       : ypcb_top\n| Device       : xc7k480tffg1156-2\n'
        '| Design State : Fully Routed\n\nReport DRC\n\n'
        '1. REPORT SUMMARY\n-----------------\nDesign limits: <entire design considered>\n'
        'Ruledeck: default\nMax checks: <unlimited>\nChecks found: 0\n'
        '| Rule | Severity | Description | Checks |\n\n'
        '2. REPORT DETAILS\n-----------------\n')


class BusSkewChannelTests(unittest.TestCase):
    def test_actual_legacy_reports_pass_seven_gates(self):
        with tempfile.TemporaryDirectory(prefix='pio-legacy-report-copy-') as tmp:
            copied = Path(tmp) / 'legacy'
            copy_reports(LEGACY_REPORT_DIR, copied)
            result = evaluate(copied, expected_gray_buses=14)
            self.assertTrue(all(result['checks'].values()), result['checks'])
            self.assertEqual(set(result['checks']), {
                'setup', 'hold', 'pulse', 'gray_skew', 'route', 'internal_coverage', 'drc'})
            self.assertEqual(result['gray_buses'], 14)
            self.assertEqual(result['total_skew_constraints'], 26)
            self.assertEqual(result['vendor_skew_constraints'], 12)
            self.assertEqual(result['design_skew_groups'], {
                'axi_crossing_1': 10, 'csr_crossing_1': 4})

    def test_dual_selection_rejects_legacy_skew_coverage(self):
        with tempfile.TemporaryDirectory(prefix='pio-dual-legacy-copy-') as tmp:
            copied = Path(tmp) / 'legacy'
            copy_reports(LEGACY_REPORT_DIR, copied)
            result = evaluate(copied, expected_gray_buses=28)
            self.assertFalse(result['checks']['gray_skew'])
            self.assertTrue(all(value for name, value in result['checks'].items()
                                if name != 'gray_skew'))

    def test_synthetic_dual_channel_fixture_passes_parser_gates(self):
        with tempfile.TemporaryDirectory(prefix='pio-synthetic-dual-report-') as tmp:
            copied = Path(tmp) / 'synthetic'
            complete_reports(copied)
            result = evaluate(copied, expected_gray_buses=28)
            self.assertTrue(all(result['checks'].values()), result['checks'])
            self.assertEqual(result['gray_buses'], 28)
            self.assertEqual(result['total_skew_constraints'], 40)
            self.assertEqual(result['design_skew_groups'], {
                'axi_crossing_0': 10, 'csr_crossing_0': 4,
                'axi_crossing_1': 10, 'csr_crossing_1': 4})
            self.assertEqual(result['vendor_skew_groups'], {
                'jtag_ip': 8, 'debug_hub_ip': 4})
            self.assertTrue(result['checks']['gray_skew'])
            self.assertFalse(result['external_ddr_io_timing_complete'])
            self.assertFalse(result['physical_profile_confirmed'])

    def test_dual_channel_bad_group_fixtures_fail_skew_gate(self):
        for mutation in ('missing', 'duplicate', 'unknown', 'cross_channel'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                    prefix='pio-invalid-dual-report-') as tmp:
                copied = Path(tmp) / mutation
                complete_reports(copied, mutation)
                result = evaluate(copied, expected_gray_buses=28)
                self.assertFalse(result['checks']['gray_skew'], result['checks'])
                self.assertTrue(all(value for name, value in result['checks'].items()
                                    if name != 'gray_skew'))


def main():
    parser = argparse.ArgumentParser(
        description='Bus-skew parser tests; synthetic dual report is not physical evidence.')
    parser.add_argument('--legacy-report-dir', type=Path, required=True,
                        help='read-only directory containing the five complete legacy reports')
    args = parser.parse_args()
    global LEGACY_REPORT_DIR
    LEGACY_REPORT_DIR = args.legacy_report_dir.resolve()
    missing = [name for name in REPORT_NAMES if not (LEGACY_REPORT_DIR / name).is_file()]
    if missing:
        parser.error('legacy report directory is missing: ' + ', '.join(missing))
    before = report_hashes(LEGACY_REPORT_DIR)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BusSkewChannelTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if report_hashes(LEGACY_REPORT_DIR) != before:
        raise RuntimeError('Legacy reports were modified during the test')
    print('Synthetic dual-channel bus-skew reports are parser fixtures only, not physical evidence.')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
