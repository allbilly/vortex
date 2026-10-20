#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import argparse
import hashlib
import json
import re
from pathlib import Path


def generate(ddr, output, c_header=False):
    csr_file = ddr / "csr.json"
    phy_file = ddr / "software/include/generated/sdram_phy.h"
    csr = json.loads(csr_file.read_text())
    phy = phy_file.read_text()
    constants = csr["constants"]
    if not 0 < constants["config_clock_frequency"] <= 1000000000:
        raise ValueError("Unsupported controller clock frequency")
    if (constants["config_csr_data_width"] != 32
            or constants["config_csr_alignment"] != 32
            or "config_csr_ordering_big" not in constants
            or csr["cores"]["ddrphy"] != "A7DDRPHY"
            or csr["cores"]["ecc_axi_0"] != "LiteDRAMNativePortECC"):
        raise ValueError("DDR metadata does not match the YPCB CSR/PHY/ECC interface")
    defines = {name: int(value, 0) for name, value in
               re.findall(r"^#define (\w+) (0x[0-9a-fA-F]+|[0-9]+)\s*$", phy, re.M)}
    expected = {"SDRAM_PHY_DATABITS": 72, "SDRAM_PHY_DFI_DATABITS": 144,
                "SDRAM_PHY_PHASES": 4, "SDRAM_PHY_XDR": 2,
                "SDRAM_PHY_MODULES": 9, "SDRAM_PHY_DQ_DQS_RATIO": 8,
                "SDRAM_PHY_DELAYS": 32, "SDRAM_PHY_BITSLIPS": 8}
    for name, value in expected.items():
        if defines.get(name) != value:
            raise ValueError(f"Unsupported YPCB PHY geometry: {name}")
    registers = csr["csr_registers"]
    occupied = set()
    for name, reg in registers.items():
        if reg["addr"] < 0 or reg["addr"] % 4 or reg["addr"] + reg["size"] * 4 > 0x2000:
            raise ValueError(f"CSR escapes its aligned 8 KiB window: {name}")
        size = 5 if name.endswith(("_wrdata", "_rddata")) else 1
        if reg["size"] != size:
            raise ValueError(f"Unsupported CSR width: {name}")
        words = set(range(reg["addr"], reg["addr"] + size * 4, 4))
        if words & occupied:
            raise ValueError(f"Overlapping DDR CSR register: {name}")
        occupied.update(words)
    body_match = re.search(r"static inline void init_sequence\(void\)\s*\{([^{}]*)\}", phy, re.S)
    if not body_match:
        raise ValueError("Generated JEDEC initialization sequence is absent or unsupported")
    body = re.sub(r"/\*.*?\*/", "", body_match[1], flags=re.S).strip()
    operations = []
    while body:
        call = re.match(r"(\w+)\(([^();]+)\);\s*", body)
        if not call:
            raise ValueError(f"Unsupported initialization statement: {body[:80]}")
        function, expression = call.group(1, 2)
        value = 0
        for token in expression.split("|"):
            token = token.strip()
            if token in defines:
                value |= defines[token]
            elif re.fullmatch(r"0x[0-9a-fA-F]+|[0-9]+", token):
                value |= int(token, 0)
            else:
                raise ValueError(f"Unsupported initialization value: {token}")
        if function == "cdelay":
            if value <= 0:
                raise ValueError("Initialization delay must be positive")
            operations.append(("wait", 0, value))
        elif function == "command_p0":
            operations.extend(("write", registers[name]["addr"], data) for name, data in
                              (("sdram_dfii_pi0_command", value), ("sdram_dfii_pi0_command_issue", 1)))
        elif function in {"sdram_dfii_pi0_address_write", "sdram_dfii_pi0_baddress_write",
                          "sdram_dfii_control_write"}:
            operations.append(("write", registers[function.removesuffix("_write")]["addr"], value))
        else:
            raise ValueError(f"Unsupported initialization call: {function}")
        body = body[call.end():].strip()
    if not operations:
        raise ValueError("Generated JEDEC initialization sequence is empty")
    lines = ["// Copyright © 2019-2026", "// Licensed under the Apache License, Version 2.0.",
             "", "#pragma once", "#include <array>", "#include <cstdint>", "",
             "namespace vortex::ypcb::ddr_config {"]
    for name, reg in sorted(registers.items()):
        lines.append(f"inline constexpr uint32_t {name} = 0x{reg['addr']:x};")
    for name, value in sorted(defines.items()):
        lines.append(f"inline constexpr uint32_t {name.lower()} = {value};")
    lines += [f"inline constexpr uint32_t sys_clock_hz = {constants['config_clock_frequency']};",
              "enum class Kind { write, wait };",
              "struct Operation { Kind kind; uint32_t offset; uint32_t value; };",
              f"inline constexpr std::array<Operation, {len(operations)}> initialization = {{{{"]
    lines.extend(f"  {{Kind::{kind}, 0x{offset:x}, {value}}}," for kind, offset, value in operations)
    lines += ["}};", "struct Phase { uint32_t command, issue, address, bank, wrdata, rddata; };",
              "inline constexpr std::array<Phase, 4> phases = {{"]
    for phase in range(4):
        names = [f"sdram_dfii_pi{phase}_{suffix}" for suffix in
                 ("command", "command_issue", "address", "baddress", "wrdata", "rddata")]
        lines.append("  {" + ", ".join(names) + "},")
    lines += ["}};", "}", ""]
    firmware_file = ddr / 'selfcal_fw/manifest.json'
    if not c_header and firmware_file.exists():
        firmware = json.loads(firmware_file.read_text())
        identifier = firmware['firmware_id']
        if not isinstance(identifier, int) or not 0 < identifier < 2**32:
            raise ValueError('Invalid calibration firmware identity')
        lines.insert(-2, f'inline constexpr uint32_t calibration_firmware_id = 0x{identifier:08x}u;')
    if c_header:
        lines = ["// Copyright © 2019-2026", "// Licensed under the Apache License, Version 2.0.",
                 "", "#pragma once", "#include <stdint.h>", ""]
        for name, reg in sorted(registers.items()):
            lines.append(f"#define cfg_{name} 0x{reg['addr']:x}u")
        for name, value in sorted(defines.items()):
            lines.append(f"#define cfg_{name.lower()} {value}u")
        lines += [f"#define cfg_sys_clock_hz {constants['config_clock_frequency']}u",
                  "enum { CFG_WRITE, CFG_WAIT };",
                  "struct cfg_operation { uint32_t kind, offset, value; };",
                  "static const struct cfg_operation cfg_initialization[] = {"]
        lines.extend(f"  {{CFG_{kind.upper()}, 0x{offset:x}u, {value}u}}," for kind, offset, value in operations)
        lines += ["};", "struct cfg_phase { uint32_t command, issue, address, bank, wrdata, rddata; };",
                  "static const struct cfg_phase cfg_phases[4] = {"]
        for phase in range(4):
            names = [f"cfg_sdram_dfii_pi{phase}_{suffix}" for suffix in
                     ("command", "command_issue", "address", "baddress", "wrdata", "rddata")]
            lines.append("  {" + ", ".join(names) + "},")
        lines += ["};", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines))
    manifest = {"inputs": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in ([csr_file, phy_file] + ([firmware_file] if not c_header and firmware_file.exists() else []))},
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "geometry": expected, "initialization_operations": operations}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ddr", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--c-header", action="store_true")
    args = parser.parse_args()
    generate(args.ddr, args.output, args.c_header)


if __name__ == "__main__":
    main()
