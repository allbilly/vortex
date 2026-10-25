import re
import shlex


def format_checks(log, record):
    if re.search(r'(?m)^(?:FAIL(?:ED)?(?:!|:|\s|$)|ERROR(?:!|:|\s|$)|Error:)|%Error|Assertion failed|\*\*\* error:', log):
        raise ValueError('Explicit failure marker in full-suite application log')
    formats = {'fp16': ('fp16', 2), 'bf16': ('bf16', 3), 'tf32': ('tf32', 1),
               'fp8': ('fp8', 4), 'bf8': ('bf8', 5), 'int8': ('i8', 17), 'uint8': ('u8', 18),
               'mxfp8': ('mxfp8', 8), 'mxbf8': ('mxbf8', 9), 'mxfp4': ('mxfp4', 10), 'nvfp4': ('nvfp4', 11)}
    dtype, code = formats[record['input_type']]
    target = 'i32 (id=16)' if record['output_type'] == 'int32' else 'fp32 (id=0)'
    if f'input data type: {dtype} (id={code})' not in log or 'output data type: ' + target not in log:
        raise ValueError('Format case did not report its requested arithmetic types')
    if 'PASSED!' not in log:
        raise ValueError('Format case did not numerically verify its results')
    if record['input_type'] in ('mxfp8', 'mxbf8', 'mxfp4', 'nvfp4'):
        logical_depth = 64 if record['input_type'] in ('mxfp4', 'nvfp4') else 32
        if f'K(logical)={logical_depth}, K(storage)=32' not in log:
            raise ValueError('Scaled format did not report its logical/storage tile geometry')
    elif any(value not in log for value in (
            f"matrix A: {record['rows']}x{record['depth']}",
            f"matrix B: {record['depth']}x{record['cols']}")):
        raise ValueError('Dense format did not report its exact matrix dimensions')
    counters = re.findall(r'PERF: instrs=(\d+), cycles=(\d+)', log)
    repeated = record['verified_launches'] == 2
    if len(counters) != (3 if repeated else 1) or any(min(map(int, item)) <= 0 for item in counters):
        raise ValueError('Format case lacks complete positive GPU retirement')
    if repeated and re.findall(r'^\[iter (\d+)\] match \(0 errors\)$', log, re.M) != ['0', '1']:
        raise ValueError('Format case lacks both numerical launches')
    return {'input_type': record['input_type'], 'output_type': record['output_type'],
            'rows': record['rows'], 'cols': record['cols'], 'depth': record['depth'],
            'verified_launches': record['verified_launches'],
            'verified_outputs': record['rows'] * record['cols'] * record['verified_launches'],
            'gpu_counters': [dict(zip(('instructions', 'cycles'), map(int, item))) for item in counters]}


def study_checks(name, log, record, reference_log, hardware_flags):
    if re.search(r'(?m)^(?:FAIL(?:ED)?(?:!|:|\s|$)|ERROR(?:!|:|\s|$)|Error:)|%Error|Assertion failed|\*\*\* error:', log):
        raise ValueError('Explicit failure marker in full-suite application log')
    required_flags = {flag for flag in shlex.split(record['configs'])
                      if flag.startswith(('-DVX_CFG_', '-DVX_PROFILE='))}
    if not required_flags <= hardware_flags:
        raise ValueError(name + ' build configuration differs from the frozen image')
    setup_prefixes = ('input data type:', 'output data type:', 'input type:',
                      'matrix A:', 'matrix B:', 'matrix C:', 'WMMA Core Dimension:',
                      'WMMA Tile Dimension:', 'WGMMA tile:', 'num_harts:')
    setup = [line for line in reference_log.splitlines() if line.startswith(setup_prefixes)]
    numeric = [line for line in reference_log.splitlines()
               if re.fullmatch(r'Test\d+-\w+ PASSED|\[iter \d+\] match \(0 errors\)|PASSED!?', line)]
    if not numeric:
        raise ValueError(name + ' has no validated reference success markers')
    actual_lines = log.splitlines()
    if any(line not in actual_lines for line in setup + numeric):
        raise ValueError(name + ' lacks expected configuration or numerical verification')
    counters = re.findall(r'PERF: instrs=(\d+), cycles=(\d+)', log)
    if len(counters) != len(record['gpu_counters']) or any(min(map(int, item)) <= 0 for item in counters):
        raise ValueError(name + ' lacks complete positive GPU retirement evidence')
    if name == 'atomics' and len([line for line in numeric if line.startswith('Test')]) != 17:
        raise ValueError('The full 17-test atomic suite was not exercised')
    return setup, numeric, counters, sorted(required_flags)


def lrsc_checks(log, record):
    if re.search(r'(?m)^(?:FAIL(?:ED)?(?:!|:|\s|$)|ERROR(?:!|:|\s|$)|Error:)|%Error|Assertion failed|\*\*\* error:', log):
        raise ValueError('Explicit failure marker in full-suite application log')
    marker = 'PASSED: LRSC ordering/bounded progress and enabled native mixed-local/global nonzero CAS checks'
    summaries = re.findall(r'^LRSC order: harts=(\d+) iterations=(\d+) enabled_cases=([0-9a-f]+) '
                           r'failed_first_sc=([0-9a-f]+) cas_only=(\d+) global_banks=(\d+) '
                           r'local_banks=(\d+) lsu_lanes=(\d+) simd_width=(\d+)$', log, re.M)
    counters = re.findall(r'^PERF: instrs=(\d+), cycles=(\d+), IPC=([0-9.]+)$', log, re.M)
    if (len(summaries) != 1 or len(counters) != 1 or log.splitlines().count(marker) != 1
            or re.search(r'^(?:FAIL|ERROR)|%Error|Assertion failed', log, re.M)
            or any(int(value) <= 0 for value in counters[0][:2])):
        raise ValueError('LRSC case lacks complete numerical and retirement evidence')
    row = summaries[0]
    expected = tuple(record[name] for name in ('harts', 'iterations', 'cas_only', 'global_banks',
                                              'local_banks', 'lsu_lanes', 'simd_width'))
    if (tuple(map(int, (row[0], row[1], *row[4:]))) != expected
            or int(row[2], 16) != record['enabled_cases']
            or int(row[3], 16) & record['required_failed_first_sc'] != record['required_failed_first_sc']
            or int(row[3], 16) & ~record['allowed_failed_first_sc']):
        raise ValueError('LRSC case did not run the exact requested geometry and sequence set')
    return {'arguments': record['arguments'], 'harts': record['harts'], 'iterations': record['iterations'],
            'enabled_cases': record['enabled_cases'], 'failed_first_sc': int(row[3], 16),
            'allowed_failed_first_sc': record['allowed_failed_first_sc'],
            'enabled_order_sequences': record['harts'] * record['iterations'] * record['enabled_cases'].bit_count(),
            'bounded_progress_successes': 2 * record['harts'] * record['iterations'],
            'native_cas_operations': 4 * record['harts'],
            'host_verified_result_fields': 11 * record['harts'],
            'gpu_counters': {'instructions': int(counters[0][0]), 'cycles': int(counters[0][1])},
            'hart_count_evidence': 'Selected logical task count; unique hart IDs are not independently asserted'}
