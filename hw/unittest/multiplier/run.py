import subprocess
variants = [(33,33,66,1,3),(33,33,66,0,3),(33,33,64,1,2),(33,33,64,0,2),
            (32,32,31,0,2),(32,32,32,1,3),(32,32,64,0,2),(48,16,64,1,3),
            (48,32,96,0,2),(65,65,130,1,3),(17,19,36,0,3),(8,9,7,1,2),
            (2,2,1,0,2),(1,1,2,0,3),(33,33,66,1,0),(33,33,66,1,1)]
for aw,bw,rw,sgn,latency in variants:
    subprocess.run(['make','-j1','clean'],check=True)
    subprocess.run(['make','-j1','run',f'A_WIDTH={aw}',f'B_WIDTH={bw}',
                    f'R_WIDTH={rw}',f'SIGNED={sgn}',f'LATENCY={latency}'],check=True)
subprocess.run(['make','-j1','clean'],check=True)
subprocess.run(['make','-j1','run','A_WIDTH=33','B_WIDTH=33','R_WIDTH=66',
                'SIGNED=1','LATENCY=3','PARTIAL_REG=0'],check=True)
