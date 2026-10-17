#!/usr/bin/env python3
# Copyright © 2019-2026
# Licensed under the Apache License, Version 2.0.

import hashlib
import os
from pathlib import Path
import sys
import tempfile


def patch(header):
    original = header.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    patched_hash = '90f9b473852d1f5be1b4261e37f87c9d88eda7847dbd99c28e5fa7d68963ca74'
    if digest == patched_hash:
        return
    if digest != '9499dc187c78f4f88c55f878afd375662912439b0cff69c8299a6054350432f7':
        raise ValueError('Ramulator fmt header differs from the pinned spdlog 1.11.0 input')
    # Keep the mapper alive until the mapped value has been consumed.
    updated = original.replace(
        b'  const auto& arg = arg_mapper<Context>().map(FMT_FORWARD(val));',
        b'  arg_mapper<Context> mapper;\n  const auto& arg = mapper.map(FMT_FORWARD(val));')
    if hashlib.sha256(updated).hexdigest() != patched_hash:
        raise ValueError('Unexpected Ramulator fmt patch result')
    with tempfile.NamedTemporaryFile(dir=header.parent, delete=False) as stream:
        stream.write(updated)
        temporary = Path(stream.name)
    try:
        temporary.chmod(header.stat().st_mode)
        os.replace(temporary, header)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
