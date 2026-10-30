"""Application-generated IDs: UUIDv7 for entities addressed by the API (design/03 §3.1, DD22).

Python 3.13 has no uuid.uuid7 (it arrives in 3.14), so this is the RFC 9562 layout: 48-bit Unix time in
milliseconds, version 7, then random bits. Time-ordered, so B-tree inserts stay at the right edge.
"""
from __future__ import annotations

import os
import time
import uuid


def uuid7(unix_ms: int | None = None) -> uuid.UUID:
    ms = time.time_ns() // 1_000_000 if unix_ms is None else unix_ms
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits: 12 for rand_a, 62 for rand_b (6 spare)
    value = (ms & (1 << 48) - 1) << 80
    value |= 0x7 << 76                            # version
    value |= (rand >> 68) << 64                   # rand_a, 12 bits
    value |= 0b10 << 62                           # variant
    value |= rand & (1 << 62) - 1                 # rand_b
    return uuid.UUID(int=value)
