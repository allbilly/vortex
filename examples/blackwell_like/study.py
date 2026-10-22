import argparse
from dataclasses import dataclass
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


@dataclass(frozen=True)
class Case:
    project: str
    description: str
    required: tuple
    configs: tuple = ()
    arguments: tuple = ()
    gemm: bool = False
    repeat_launches: bool = False


def tensor(dtype, project='sgemm_tcu', extra=(), required=()):
    target = 'int32' if dtype in ('int8', 'uint8') else 'fp32'
    return Case(project, f'{dtype} inputs, {target} accumulation',
                ('EXT_TCU_ENABLE', *required),
                (f'-DITYPE={dtype}', f'-DOTYPE={target}', *extra), gemm=True,
                repeat_launches=project == 'sgemm_tcu')


CASES = {
    'fp16': tensor('fp16', required=('TCU_FP16_ENABLE',)),
    'bf16': tensor('bf16', required=('TCU_FP16_ENABLE',)),
    'tf32': tensor('tf32', required=('TCU_TF32_ENABLE',)),
    'fp8': tensor('fp8', required=('TCU_FP8_ENABLE',)),
    'bf8': tensor('bf8', required=('TCU_FP8_ENABLE',)),
    'int8': tensor('int8', required=('TCU_INT8_ENABLE',)),
    'uint8': tensor('uint8', required=('TCU_INT8_ENABLE',)),
    'mxfp8': tensor('mxfp8', 'sgemm_tcu_mx', required=('TCU_MX_ENABLE', 'TCU_FP8_ENABLE')),
    'mxbf8': tensor('mxbf8', 'sgemm_tcu_mx', required=('TCU_MX_ENABLE', 'TCU_FP8_ENABLE')),
    'mxfp4': tensor('mxfp4', 'sgemm_tcu_mx', required=('TCU_MX_ENABLE', 'TCU_FP4_ENABLE', 'TCU_MXFP4_ENABLE')),
    'nvfp4': tensor('nvfp4', 'sgemm_tcu_mx', extra=('-DTCU_MX_TLS',),
                    required=('TCU_MX_ENABLE', 'TCU_FP4_ENABLE', 'TCU_NVFP4_ENABLE')),
    'sparse': tensor('fp16', 'sgemm_tcu_sp', required=('TCU_FP16_ENABLE', 'TCU_SPARSE_ENABLE')),
    'sparse-mx': tensor('mxfp8', 'sgemm_tcu_sp_mx',
                        required=('TCU_FP8_ENABLE', 'TCU_MX_ENABLE', 'TCU_SPARSE_ENABLE')),
    'wgmma': tensor('fp16', 'sgemm_tcu_wg', extra=('-DWGMMA_NRC=8', '-DWGMMA_SS'),
                    required=('TCU_FP16_ENABLE', 'TCU_WGMMA_ENABLE')),
    'wgmma-mx': tensor('mxfp8', 'sgemm_tcu_wg_mx', extra=('-DWGMMA_NRC=8', '-DWGMMA_SS'),
                       required=('TCU_FP8_ENABLE', 'TCU_MX_ENABLE', 'TCU_WGMMA_ENABLE')),
    'copy': Case('dxa_copy', 'Two-dimensional asynchronous global-to-shared copy',
                 ('EXT_DXA_ENABLE',), arguments=('-d2',)),
    'multicast': Case('dxa_copy_mcast', 'Copy one source tile to co-resident CTAs',
                      ('EXT_DXA_ENABLE',), arguments=('-r16', '-c16', '-R16', '-C8')),
    'pipeline': tensor('fp16', 'sgemm_tcu_wg_dxa', extra=('-DWGMMA_NRC=8',),
                       required=('TCU_FP16_ENABLE', 'TCU_WGMMA_ENABLE', 'EXT_DXA_ENABLE')),
    'sparse-pipeline': tensor('fp16', 'sgemm_tcu_wg_sp_dxa', extra=('-DWGMMA_NRC=8',),
                              required=('TCU_FP16_ENABLE', 'TCU_SPARSE_ENABLE', 'TCU_WGMMA_ENABLE', 'EXT_DXA_ENABLE')),
    'atomics': Case('amo', 'Contended integer atomics, including CAS when enabled',
                    ('EXT_A_ENABLE',), arguments=('-n8',)),
    'cache-reuse': tensor('fp16', required=('TCU_FP16_ENABLE',)),
}


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def main():
    parser = argparse.ArgumentParser(description='Reference-checked Vortex compute-kernel studies')
    parser.add_argument('--build', type=Path, default=Path.cwd())
    parser.add_argument('--driver', choices=('simx', 'xrt', 'ypcb'), default='simx')
    parser.add_argument('--case', choices=(*CASES, 'all'), default='fp8')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('-m', type=positive, default=16)
    parser.add_argument('-n', type=positive, default=16)
    parser.add_argument('-k', type=positive, default=64)
    parser.add_argument('--output', type=Path)
    options = parser.parse_args()
    if options.list:
        for name, case in CASES.items():
            print(f'{name:18} {case.description:54} tests/regression/{case.project}/kernel.cpp')
        return
    build = options.build.expanduser().resolve()
    config = build / 'config.mk'
    if not config.is_file():
        parser.error('--build must name a configured build directory')
    text = config.read_text()

    def setting(name):
        match = re.search(r'^' + name + r'[ \t]*\?=[ \t]*(.*)$', text, re.M)
        if not match:
            raise RuntimeError('Missing build setting: ' + name)
        return match[1].strip()

    root = Path(setting('VORTEX_HOME'))
    profile = setting('PROFILE')
    if setting('XLEN') != '32' or setting('MEMORY_SIZE') != '2147483648' or not profile:
        parser.error('Use a named RV32, 2 GiB YPCB study profile')
    wrapper = build / 'ci/ypcb_env.sh'
    if not wrapper.is_file():
        parser.error('Re-run configure to generate the YPCB native wrapper')
    workers = os.environ.get('THREADS', str(os.cpu_count() or 1))
    env = dict(os.environ, THREADS=workers, OMP_NUM_THREADS=workers, MALLOC_ARENA_MAX='2',
               STARTUP_ADDR='0x40000000', CONFIGS='')
    for name in ('DEBUG', 'SCOPE', 'CHIPSCOPE', 'VORTEX_DRIVER'):
        env.pop(name, None)
    subprocess.run([wrapper, 'configure'], cwd=build, env=env, check=True)
    generator = [str(wrapper), 'exec', 'python3', str(build / 'ci/gen_config.py'),
                 '--config=' + str(root / 'VX_config.toml'), '--profile=' + profile]
    configs = subprocess.check_output([*generator, '--merge-configs', '--cflags='], cwd=build, env=env, text=True).strip()
    resolved = subprocess.check_output([*generator, '--cflags=' + configs + ' -DVX_CFG_XLEN=32'], cwd=build, env=env, text=True).split()
    selected = list(CASES) if options.case == 'all' else [options.case]
    for name in selected:
        missing = [key for key in CASES[name].required if '-DVX_CFG_' + key not in resolved]
        if missing:
            parser.error(name + ' requires ' + ', '.join(missing) + ' in the configured hardware profile')
    if options.driver == 'ypcb' and not (build / 'sw/ypcb/ypcb_wl_config.h').is_file():
        parser.error('Prepare the image-bound YPCB runtime and connection before hardware use')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = options.output or build / 'examples/blackwell_like/runs' / stamp
    output = output.resolve()
    output.mkdir(parents=True)
    manifest = {'status': 'RUNNING', 'profile': profile, 'driver': options.driver, 'cases': {},
                'physical_driver_requested': options.driver == 'ypcb',
                'physical_execution_verified': False}
    env.update(CONFIGS=configs, LD_LIBRARY_PATH=str(build / 'sw/runtime') + ':' + env.get('LD_LIBRARY_PATH', ''))

    def run(command, log_path, cwd=build, overrides=None):
        with log_path.open('w') as log:
            result = subprocess.run([str(wrapper), 'exec', *map(str, command)], cwd=cwd,
                                    env=dict(env, **(overrides or {})), stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(shlex.join(map(str, command)) + f' exited {result.returncode}; see {log_path}')
        return log_path.read_text(errors='replace')

    try:
        for target in ('sw/kernel', 'sw/runtime/stub', 'sw/runtime/' + options.driver):
            command = ['make', '-j' + workers, '-C', target]
            if options.driver == 'xrt' and target.endswith('/xrt'):
                command += ['TARGET=xrtsim']
            run(command, output / (target.replace('/', '-') + '.log'))
        for name in selected:
            case = CASES[name]
            directory = output / name
            directory.mkdir()
            case_configs = ' '.join((configs, *case.configs))
            print(f'{name}: profile={profile}, driver={options.driver}; {case.description}', flush=True)
            print('  kernel:', root / 'tests/regression' / case.project / 'kernel.cpp', flush=True)
            run(['make', '-j' + workers, '-C', 'tests/regression/' + case.project], directory / 'build.log',
                overrides={'CONFIGS': case_configs})
            for filename in (case.project, 'kernel.vxbin'):
                shutil.copy2(build / 'tests/regression' / case.project / filename, directory / filename)
            arguments = list(case.arguments)
            if case.gemm:
                arguments = [f'-m{options.m}', f'-n{options.n}', f'-k{options.k}']
                if case.repeat_launches:
                    arguments += ['-r2']
            result = run([directory / case.project, *arguments], directory / 'run.log', directory,
                         {'VORTEX_DRIVER': options.driver})
            print(result, end='', flush=True)
            counters = re.findall(r'PERF: instrs=(\d+), cycles=(\d+)', result)
            if 'PASSED' not in result or not counters or not all(min(map(int, item)) > 0 for item in counters):
                raise RuntimeError(name + ' lacks numerical success and positive GPU retirement')
            manifest['cases'][name] = {'status': 'PASS', 'arguments': arguments, 'configs': case_configs,
                                      'gpu_counters': [{'instructions': int(i), 'cycles': int(c)} for i, c in counters],
                                      'artifacts': {filename: hashlib.sha256((directory / filename).read_bytes()).hexdigest()
                                                    for filename in (case.project, 'kernel.vxbin')}}
            if options.driver == 'ypcb':
                manifest['physical_execution_verified'] = True
            (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        manifest['status'] = 'PASS'
    except BaseException as error:
        manifest.update(status='FAIL', error=repr(error))
        raise
    finally:
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print('Results:', output, flush=True)


if __name__ == '__main__':
    main()
