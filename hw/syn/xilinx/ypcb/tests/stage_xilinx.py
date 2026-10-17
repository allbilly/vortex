#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("library", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--netlist", type=Path, required=True)
parser.add_argument("--top", required=True)
args = parser.parse_args()
source = args.library.read_text()
netlist = json.loads(args.netlist.read_text())
cell_types = sorted({cell["type"] for cell in netlist["modules"][args.top]["cells"].values()})
modules = []
for cell_type in cell_types:
    if cell_type.startswith("$"):
        raise SystemExit(f"Unmapped cell: {cell_type}")
    match = re.search(rf"(?ms)^module {re.escape(cell_type)}\s*\(.*?^endmodule\s*$", source)
    if not match:
        raise SystemExit(f"Simulation module is absent: {cell_type}")
    modules.append(match[0])
license_end = source.index("*/") + 2
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(source[:license_end] + "\n\n`timescale 1ns/1ps\n" + "\n\n".join(modules) + "\n")
manifest = {
    "source": str(args.library.resolve()),
    "source_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
    "netlist_sha256": hashlib.sha256(args.netlist.read_bytes()).hexdigest(),
    "cell_types": cell_types,
    "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    "simulation_timescale": "1ns/1ps",
}
args.output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
