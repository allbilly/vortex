import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--build', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--verilator', required=True)
parser.add_argument('--compile-only', action='store_true')
parser.add_argument('--rtl-source', type=Path)
args = parser.parse_args()
build = args.build.resolve()
config = (build / 'config.mk').read_text()
root = Path(re.search(r'^VORTEX_HOME[ \t]*\?=[ \t]*(.*)$',config,re.M)[1])
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
rtl = args.rtl_source or root / 'hw/rtl/core/VX_scoreboard.sv'
state = {'status':'RUNNING','hardware_accessed':False}
try:
    command = [args.verilator,'--binary','--timing','--assert','-j','1','--timescale-override','1ns/1ps',
               '--top-module','scoreboard_progress_tb','--Mdir',str(output/'model'),'-o','scoreboard-test',
               '-DSIMULATION','-DVX_CFG_XLEN=32','-DVX_CFG_XLEN_32','-DVX_CFG_NUM_WARPS=2','-DVX_CFG_NUM_THREADS=2',
               '-DVX_CFG_ISSUE_WIDTH=1','-DVX_CFG_DISPATCH_QUEUE_SIZE=4','-DVX_DBG_STALL_TIMEOUT=32',
               *['-I'+str(p) for p in [build/'hw',build/'sw',root/'hw/rtl',root/'hw/rtl/interfaces',root/'hw/rtl/libs']],
               '-y',str(root/'hw/rtl/libs'),'-y',str(root/'hw/rtl/interfaces'),str(root/'hw/rtl/VX_gpu_pkg.sv'),str(rtl),
               str(root/'hw/unittest/scoreboard_progress/tb.sv')]
    with (output/'compile.log').open('w') as log:
        subprocess.run(command,cwd=build,check=True,stdout=log,stderr=subprocess.STDOUT)
    if args.compile_only:
        state['status']='SCOREBOARD_COMPILE_PASS'
    else:
        for name,arguments in [('progress',[]),('quiescent',['+deadlock'])]:
            result=subprocess.run([output/'model/scoreboard-test',*arguments],cwd=build,capture_output=True,text=True)
            text=result.stdout+result.stderr
            (output/(name+'.log')).write_text(text)
            if name=='progress':
                assert result.returncode==0 and 'PASSED long-wait progress lsu=4 alu=128' in text,text
            else:
                assert result.returncode!=0 and 'timeout: wid=1' in text and 'Quiescent watchdog failed' not in text,text
            state[name+'_exit_code']=result.returncode
        state['status']='GREEDY_PROGRESS_ACCEPTED_AND_QUIESCENT_DEADLOCK_DETECTED_PASS'
except BaseException as error:
    state.update(status='FAIL',error=repr(error));raise
finally:
    (output/'manifest.json').write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps(state))
