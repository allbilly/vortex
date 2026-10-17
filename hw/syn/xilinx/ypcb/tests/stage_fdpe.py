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
args = parser.parse_args()
source = args.library.read_text()
license_end = source.index("*/") + 2
match = re.search(r"(?ms)^module FDPE \(.*?^endmodule\s*$", source)
if not match:
    raise SystemExit("FDPE simulation module is absent")
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(source[:license_end] + "\n\n`timescale 1ns/1ps\n" + match[0] + "\n")
manifest = {"source": str(args.library.resolve()),
            "source_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
            "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            "simulation_timescale": "1ns/1ps"}
args.output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
