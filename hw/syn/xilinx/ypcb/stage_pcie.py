#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

REVISION = 'cd1c33f53401d6ce1b6ec35da17884455477c2e9'
SOURCES = ('xilinx_pcie_mmcm.v', 'pcie_7x.v', 'pcie_axi_rx.v', 'pcie_axi_tx.v',
           'pcie_block.v', 'pcie_brams.v', 'pcie_tx_thrtl_ctl.v', 'pipe_wrapper_gtx.v')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
    status = subprocess.check_output(['git', '-C', str(args.source), 'status', '--porcelain'], text=True).strip()
    if revision != REVISION or status:
        raise ValueError('PCIe staging requires the clean pinned upstream revision')
    args.output.mkdir(parents=True, exist_ok=True)
    files = [Path('src') / name for name in SOURCES]
    files += [path.relative_to(args.source) for path in args.source.glob('LICENSE*')]
    records = []
    for relative in files:
        source, output = args.source / relative, args.output / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        if digest(source) != digest(output):
            raise ValueError(f'PCIe copy digest mismatch: {relative}')
        records.append({'path': str(relative), 'upstream_sha256': digest(source)})
    patch = Path(__file__).with_name('pcie-gtx.patch').resolve()
    subprocess.run(['patch', '--batch', '--forward', '-p1', '-i', str(patch)], cwd=args.output, check=True)
    for record in records:
        record['staged_sha256'] = digest(args.output / record['path'])
    manifest = {'status': 'PATCHED_UPSTREAM_SOURCE_FOLLOW_UP_REQUIRED', 'revision': revision,
                'source': str(args.source), 'patch': str(patch), 'patch_sha256': digest(patch),
                'files': records, 'physical_gtx_verified': False,
                'follow_up': 'Submit the declaration, binary-radix, explicit-width and missing signal-connection corrections upstream; verify GTX reset/link/power-management behavior on the board.'}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Copied {len(records)} pinned PCIe files and applied the explicit source patch')


if __name__ == '__main__':
    main()
