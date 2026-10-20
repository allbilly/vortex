#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import hashlib
import os
from pathlib import Path
import sys
import tempfile


def patch(header, original_hash, patched_hash, before, after):
    original = header.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if digest == patched_hash:
        return
    if digest != original_hash:
        raise ValueError(f'Ramulator dependency differs from its pinned input: {header}')
    updated = original.replace(before, after, 1)
    if hashlib.sha256(updated).hexdigest() != patched_hash:
        raise ValueError(f'Unexpected Ramulator dependency patch result: {header}')
    with tempfile.NamedTemporaryFile(dir=header.parent, delete=False) as stream:
        stream.write(updated)
        temporary = Path(stream.name)
    try:
        temporary.chmod(header.stat().st_mode)
        os.replace(temporary, header)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    root = Path(sys.argv[1])
    patch(root / 'ext/spdlog/include/spdlog/fmt/bundled/core.h',
          '9499dc187c78f4f88c55f878afd375662912439b0cff69c8299a6054350432f7',
          '90f9b473852d1f5be1b4261e37f87c9d88eda7847dbd99c28e5fa7d68963ca74',
          b'  const auto& arg = arg_mapper<Context>().map(FMT_FORWARD(val));',
          b'  arg_mapper<Context> mapper;\n  const auto& arg = mapper.map(FMT_FORWARD(val));')
    patch(root / 'ext/yaml-cpp/src/emitterutils.cpp',
          'f7f4b6a9b6659c4dc05c6f08654b0fa389bcd87e229146ace55f48afed799383',
          'bf12841de312bf58593fc135300820e89dc2094ae9859156d478ad2be426a5b0',
          b'#include <algorithm>\n', b'#include <algorithm>\n#include <cstdint>\n')
