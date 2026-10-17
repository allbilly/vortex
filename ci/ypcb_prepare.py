#!/usr/bin/env python3
"""Collect YPCB preparation evidence without programming the board."""

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def command(args, cwd=None, timeout=30):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {"command": args, "returncode": result.returncode,
                "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": args, "returncode": None, "error": str(error)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(build, name, data):
    data["collected_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    target = build / name
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(target)


def find_source_root():
    required = (Path("hw/syn/xilinx/ypcb/ypcb_top.sv"),
                Path("sw/runtime/ypcb/vortex.cpp"))
    starts = (Path(__file__).resolve().parent, Path.cwd().resolve())
    for start in starts:
        for candidate in (start, *start.parents):
            if all((candidate / path).is_file() for path in required):
                return candidate
    return Path(__file__).resolve().parent.parent


def inventory(build, home):
    exclusions = [".git", "build*", "out", "node_modules", "__pycache__", "target", "dist"]
    roots = []
    for root in sorted(home.iterdir()):
        if not root.is_dir() or root.name.startswith("."):
            continue
        if root.name in {"Downloads", "vivado", "models", "go"} or root.name.startswith("vortex-tools-"):
            continue
        args = ["rg", "--files", "--hidden"]
        for exclusion in exclusions:
            args += ["-g", f"!**/{exclusion}/**"]
        listing = command(args + [str(root)], timeout=90)
        files = listing.get("stdout", "").splitlines()
        candidates = []
        for name in files:
            relative = str(Path(name).relative_to(root))
            if any(word in relative.lower() for word in
                   ("ypcb", "xc7k480", "mig_7", "xdma", "pcie", "bscan", "fpga", "vortex", "riscv", "toolchain")):
                candidates.append(relative)
        content_args = ["rg", "-n", "-i", "--max-count", "2"]
        for exclusion in exclusions:
            content_args += ["-g", f"!**/{exclusion}/**"]
        for pattern in ("*.md", "*.tcl", "*.xdc", "*.prj", "*.xml", "Makefile*", "*.v", "*.sv", "*.cpp", "*.h"):
            content_args += ["-g", pattern]
        references = command(content_args + [r"\bypcb\b|xc7k480t|\bDLC10\b|vortexgpgpu", str(root)], timeout=90)
        roots.append({"root": str(root), "source_files": len(files), "candidates": candidates,
                      "board_reference_search": references,
                      "scan_returncode": listing["returncode"], "scan_error": listing.get("error"),
                      "revision": command(["git", "rev-parse", "HEAD"], cwd=root)
                      if (root / ".git").exists() else None})
    save(build, "home-project-inventory.json", {"home": str(home), "excluded": exclusions,
         "excluded_roots": ["hidden directories", "Downloads", "vivado", "models", "go", "vortex-tools-*"],
         "projects": roots})


def stage_reference(build, reference):
    board = reference / "ypcb003381p1/1.0"
    if not (board / "board.xml").is_file():
        raise SystemExit(f"Missing YPCB board reference: {board}")
    files = [reference / "LICENSE", reference / "constraints/ypcb003381p1.xdc",
             reference / "constraints/MEMORY_CH0.ucf", reference / "constraints/MEMORY_CH1.ucf"]
    files += [p for p in sorted(board.iterdir()) if p.is_file()]
    example = reference / "examples/YPCB_00338_1P1_systest"
    files += [example / "YPCB_00338_1P1_systest.srcs/sources_1/bd/top/top.bd",
              example / "YPCB_00338_1P1_systest.srcs/sources_1/bd/top/ip/top_xdma_0_0/top_xdma_0_0.xci"]
    target = build / "board_reference"
    manifest = []
    for source in files:
        if not source.is_file():
            raise SystemExit(f"Missing reference file: {source}")
        relative = source.relative_to(reference)
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        if digest(dest) != digest(source):
            raise SystemExit(f"Copy verification failed: {dest}")
        manifest.append({"path": str(relative), "sha256": digest(dest), "bytes": dest.stat().st_size})
    bd = json.loads((target / files[-2].relative_to(reference)).read_text())["design"]
    save(build, "board-reference-manifest.json", {"source": str(reference), "staged": str(target),
         "revision": command(["git", "rev-parse", "HEAD"], cwd=reference),
         "source_status": command(["git", "status", "--short"], cwd=reference), "files": manifest,
         "design_info": bd["design_info"],
         "reference_ip": {name: value for name, value in bd["components"].items()
                          if name in ("xdma_0", "mig_7series_0", "clk_wiz_1")}})


def preflight(build, home, vivado):
    source = find_source_root()
    executable = shutil.which(vivado)
    checks = {"usb": command(["lsusb"]), "pci": command(["lspci", "-nn"]),
              "vortex_revision": command(["git", "rev-parse", "HEAD"], cwd=source),
              "submodules": command(["git", "submodule", "status", "--recursive"], cwd=source),
              "source_root": str(source), "vivado": executable}
    checks["tools"] = {name: shutil.which(name) for name in ("sv2v", "iverilog", "uv", "ccache")}
    checks["platform_sources"] = {str(path): (source / path).is_file() for path in
                                  (Path("hw/syn/xilinx/ypcb/ypcb_top.sv"),
                                   Path("sw/runtime/ypcb/vortex.cpp"))}
    blockers = []
    if executable is None:
        blockers.append("Vivado is unavailable; use --vivado PATH or load its environment.")
    if not all(checks["platform_sources"].values()):
        blockers.append("YPCB board wrapper or runtime backend is missing.")
    pci = checks["pci"].get("stdout", "").lower()
    if "10ee:0480" not in pci:
        blockers.append("YPCB PCIe endpoint is absent; PCIe runtime cannot be tested.")
    blockers.append("Physical DDR timing, CDC/reset and electrical qualification remain open.")
    save(build, "ypcb-preflight.json", {"fpga_toolchain": "vivado", "checks": checks,
         "blockers": blockers, "hardware_ready": False, "fpga_programmed": False})
    for blocker in blockers:
        print(blocker)
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "stage-reference", "preflight"))
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--vivado", default="vivado", help="Vivado executable")
    args = parser.parse_args()
    args.build.mkdir(parents=True, exist_ok=True)
    if args.action == "inventory":
        inventory(args.build, args.home)
    elif args.action == "stage-reference":
        stage_reference(args.build, args.reference or args.home / "ypcb/ref/ypcb_00338_1p1_hack")
    else:
        return preflight(args.build, args.home, args.vivado)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
