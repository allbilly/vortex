# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

from pathlib import Path
import json
import re
import sys


def evaluate(directory, expected_gray_buses=14):
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
    bus = re.split(r'(?m)^1\. Bus Skew Report Summary\n-+\n',
                   (directory / 'bus-skew.rpt').read_text(), maxsplit=1)[1]
    bus = re.split(r'(?m)^2\. Bus Skew Report Per Constraint\n-+\n', bus, maxsplit=1)[0]
    skews = re.findall(r'^\s*(?:Slow|Fast)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*$', bus, re.M)
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
    drc_errors = re.findall(r'^\|[^\n]*\|\s*(?:Error|Critical Warning)\s*\|', drc, re.M)
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
        'gray_skew': len(skews) == expected_gray_buses and all(not item[2].startswith('-') for item in skews),
        'route': routable > 0 and routed == routable and route_errors == 0,
        'internal_coverage': all(value == 0 for value in internal_coverage.values()),
        'drc': not drc_errors,
    }
    return {
        'status': 'INTERNAL_TIMING_ROUTE_AND_GRAY_SKEW_PASS' if all(checks.values()) else 'REPORT_GATES_FAILED',
        'checks': checks,
        'timing': values,
        'gray_buses': len(skews),
        'worst_gray_skew_slack_ns': min((float(item[2]) for item in skews), default=None),
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
