# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

from pathlib import Path
import json
import re
import sys


def drc_summary(text):
    section = re.search(r'(?ms)^1\. REPORT SUMMARY\n-+\n(.*?)^2\. REPORT DETAILS\n-+\n(.*)', text)
    if section is None:
        raise ValueError('Missing complete DRC summary and details')
    summary, details = section.groups()
    required = ('| Design       : ypcb_top', '| Device       : xc7k480tffg1156-2',
                '| Design State : Fully Routed', 'Design limits: <entire design considered>',
                'Ruledeck: default', 'Max checks: <unlimited>')
    if any(item not in text for item in required):
        raise ValueError('Missing full routed DRC report context')
    count = re.findall(r'(?m)^\s*Checks found:\s*(\d+)\s*$', summary)
    if len(count) != 1 or not re.search(r'\|\s*Rule\s*\|\s*Severity\s*\|\s*Description\s*\|\s*Checks\s*\|', summary):
        raise ValueError('Missing DRC check count or summary columns')
    rows = re.findall(r'(?m)^\|\s*([\w-]+)\s*\|\s*(Error|Critical Warning|Warning|Advisory)\s*\|[^\n|]*\|\s*(\d+)\s*\|\s*$', summary)
    expected = {(rule, severity): int(number) for rule, severity, number in rows}
    if len(expected) != len(rows) or sum(expected.values()) != int(count[0]):
        raise ValueError('Incomplete or duplicate DRC summary rows')
    blocks = list(re.finditer(r'(?ms)^([\w-]+)#(\d+) (Error|Critical Warning|Warning|Advisory)\s*\n(.*?)(?=^[\w-]+#\d+ (?:Error|Critical Warning|Warning|Advisory)\s*$|\Z)', details))
    if len(blocks) != int(count[0]):
        raise ValueError('Incomplete DRC violation details')
    actual = {}
    for block in blocks:
        rule, number, severity, body = block.groups()
        key = (rule, severity)
        actual.setdefault(key, []).append(int(number))
        if not re.search(r'(?m)^Related violations:\s+[^\n]+\n\s*\Z', body):
            raise ValueError('Truncated DRC violation detail: ' + rule + '#' + number)
    if set(actual) != set(expected) or any(numbers != list(range(1, expected[key] + 1))
                                           for key, numbers in actual.items()):
        raise ValueError('Inconsistent or duplicate DRC violation details')
    return expected


def bus_skew_summary(text):
    section = re.split(r'(?m)^1\. Bus Skew Report Summary\n-+\n', text, maxsplit=1)[1]
    sections = re.split(r'(?m)^2\. Bus Skew Report Per Constraint\n-+\n', section, maxsplit=1)
    if len(sections) != 2:
        raise ValueError('Missing detailed bus skew report')
    section, details = sections
    rows = []
    for match in re.finditer(r'(?ms)^(\d+)\s+(\d+)\s+(.*?)(?=^\d+\s+\d+\s+|\Z)', section):
        metrics = re.search(r'(Slow|Fast)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*$', match[3])
        selectors = re.findall(r'\[get_cells \[list (.*?)\]\]', match[3], re.S)
        if metrics is None or len(selectors) != 2:
            raise ValueError('Incomplete bus skew constraint: ' + match[1])
        sources, destinations = [re.findall(r'\{([^{}]+)\}', selector) for selector in selectors]
        if not sources or not destinations:
            raise ValueError('Missing bus skew endpoints: ' + match[1])
        kind = 'unknown'
        source_group = destination_group = None
        if all(re.match(r'(?:axi|csr)_crossing_[01]/', name) is not None for name in sources + destinations):
            source_bits = [re.fullmatch(r'((?:axi|csr)_crossing_[01]/.*cdc_graycounter\d+_q_reg)\[([0-2])\]', name)
                           for name in sources]
            target_bits = [re.fullmatch(r'((?:axi|csr)_crossing_[01]/xilinxmultiregimpl\d+_regs0_reg)\[([0-2])\]', name)
                           for name in destinations]
            if (len(source_bits) == len(target_bits) == 3 and all(source_bits) and all(target_bits)
                    and {bit[2] for bit in source_bits} == {'0', '1', '2'}
                    and {bit[2] for bit in target_bits} == {'0', '1', '2'}
                    and len({bit[1] for bit in source_bits}) == len({bit[1] for bit in target_bits}) == 1):
                source_group, destination_group = source_bits[0][1], target_bits[0][1]
                if source_group.split('/')[0] == destination_group.split('/')[0]:
                    kind = 'design_gray'
        elif all(name.startswith('jtag/') for name in sources + destinations):
            kind = 'jtag_ip'
        elif all(name.startswith('dbg_hub/') for name in sources + destinations):
            kind = 'debug_hub_ip'
        requirement, actual, slack = map(float, metrics.groups()[1:])
        rows.append({'id': int(match[1]), 'position': int(match[2]), 'kind': kind,
                     'source_group': source_group, 'destination_group': destination_group,
                     'endpoints': len(destinations),
                     'requirement_ns': requirement, 'actual_ns': actual, 'slack_ns': slack,
                     'passes': requirement > 0 and actual >= 0 and not metrics[4].startswith('-')
                               and abs(requirement - actual - slack) <= 0.002})
    if not rows or [row['id'] for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError('Incomplete or duplicate bus skew constraint IDs')
    if len({row['position'] for row in rows}) != len(rows):
        raise ValueError('Duplicate bus skew constraint positions')
    detailed_rows = list(re.finditer(r'(?ms)^Id:\s*(\d+)\s*\n(.*?)(?=^Id:|\Z)', details))
    if [int(row[1]) for row in detailed_rows] != [row['id'] for row in rows]:
        raise ValueError('Missing detailed bus skew constraints')
    for row, detailed in zip(rows, detailed_rows):
        slack = re.findall(r'(?m)^Slack \((?:MET|VIOLATED)\)\s*:\s*([-\d.]+)ns', detailed[2])
        requirement = re.findall(r'(?m)^Requirement:\s*([-\d.]+)ns', detailed[2])
        endpoints = re.findall(r'(?m)^Endpoints:\s*(\d+)', detailed[2])
        if (len(slack) != 1 or len(requirement) != 1 or len(endpoints) != 1
                or abs(float(slack[0]) - row['slack_ns']) > 0.001
                or abs(float(requirement[0]) - row['requirement_ns']) > 0.001
                or int(endpoints[0]) != row['endpoints']):
            raise ValueError('Incomplete or inconsistent bus skew detail: ' + str(row['id']))
    return rows


def evaluate(directory, expected_gray_buses=14):
    if expected_gray_buses not in (14, 28):
        raise ValueError('Expected one or two complete DDR CDC groups')
    channels = (1,) if expected_gray_buses == 14 else (0, 1)
    directory = Path(directory)
    timing = (directory / 'timing-summary.rpt').read_text()
    section = timing.split('Design Timing Summary', 1)[1]
    row = None
    for line in section.splitlines():
        parts = line.split()
        if len(parts) != 12:
            continue
        try:
            [float(value) for value in parts]
        except ValueError:
            continue
        row = parts
        break
    if row is None:
        raise ValueError('Missing final timing summary')
    fields = ['wns_ns', 'tns_ns', 'setup_failing_endpoints', 'setup_total_endpoints',
              'whs_ns', 'ths_ns', 'hold_failing_endpoints', 'hold_total_endpoints',
              'wpws_ns', 'tpws_ns', 'pulse_failing_endpoints', 'pulse_total_endpoints']
    values = {field: float(value) if field.endswith('_ns') else int(value)
              for field, value in zip(fields, row)}
    skews = bus_skew_summary((directory / 'bus-skew.rpt').read_text())
    design_skews = [item for item in skews if item['kind'] == 'design_gray']
    skew_groups = {name: sum(item['kind'] == name for item in skews)
                   for name in ('jtag_ip', 'debug_hub_ip')}
    design_groups = {name: sum(item['source_group'].startswith(name + '/') for item in design_skews)
                     for channel in channels for name in (f'axi_crossing_{channel}', f'csr_crossing_{channel}')}
    skew_coverage = (len(design_skews) == expected_gray_buses
                     and len({item['source_group'] for item in design_skews}) == expected_gray_buses
                     and len({item['destination_group'] for item in design_skews}) == expected_gray_buses
                     and design_groups == {f'{kind}_crossing_{channel}': count
                                           for channel in channels for kind, count in (('axi', 10), ('csr', 4))}
                     and skew_groups == {'jtag_ip': 8, 'debug_hub_ip': 4}
                     and all(item['kind'] != 'unknown' for item in skews))
    route = (directory / 'route-status.rpt').read_text()

    def route_count(label):
        return int(re.search(re.escape(label) + r'\.*\s*:\s*(\d+)', route)[1])

    coverage = (directory / 'check-timing-routed.rpt').read_text()
    internal_coverage = {}
    for name in ['no_clock', 'unconstrained_internal_endpoints']:
        match = re.search(r'checking ' + name + r' \((\d+)\)', coverage)
        if not match:
            raise ValueError('Missing internal coverage: ' + name)
        internal_coverage[name] = int(match[1])
    drc = (directory / 'drc-routed.rpt').read_text()
    drc_errors = [count for (_, severity), count in drc_summary(drc).items()
                  if severity in ('Error', 'Critical Warning')]
    routable = route_count('# of routable nets')
    routed = route_count('# of fully routed nets')
    route_errors = route_count('# of nets with routing errors')
    checks = {
        'setup': not row[0].startswith('-') and values['tns_ns'] == 0
                 and values['setup_failing_endpoints'] == 0,
        'hold': not row[4].startswith('-') and values['ths_ns'] == 0
                and values['hold_failing_endpoints'] == 0,
        'pulse': not row[8].startswith('-') and values['tpws_ns'] == 0
                 and values['pulse_failing_endpoints'] == 0,
        'gray_skew': skew_coverage and all(item['passes'] for item in skews),
        'route': routable > 0 and routed == routable and route_errors == 0,
        'internal_coverage': all(value == 0 for value in internal_coverage.values()),
        'drc': not drc_errors,
    }
    return {
        'status': 'INTERNAL_TIMING_ROUTE_AND_GRAY_SKEW_PASS' if all(checks.values()) else 'REPORT_GATES_FAILED',
        'checks': checks,
        'timing': values,
        'gray_buses': len(design_skews),
        'total_skew_constraints': len(skews),
        'vendor_skew_constraints': sum(item['kind'] in ('jtag_ip', 'debug_hub_ip') for item in skews),
        'design_skew_groups': design_groups,
        'vendor_skew_groups': skew_groups,
        'worst_gray_skew_slack_ns': min((item['slack_ns'] for item in design_skews), default=None),
        'worst_all_skew_slack_ns': min((item['slack_ns'] for item in skews), default=None),
        'skew_constraints': skews,
        'routed_nets': routed,
        'routing_errors': route_errors,
        'internal_coverage': internal_coverage,
        'external_ddr_io_timing_complete': False,
        'physical_profile_confirmed': False,
    }


if __name__ == '__main__':
    result = evaluate(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 14)
    print(json.dumps(result, indent=2))
    if result['status'] != 'INTERNAL_TIMING_ROUTE_AND_GRAY_SKEW_PASS':
        raise SystemExit(1)
