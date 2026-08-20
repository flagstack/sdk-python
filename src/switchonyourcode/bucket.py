from __future__ import annotations

import hashlib

from .types import BUCKET_SCALE


def bucket(environment_id: str, flag_id: str, bucket_value: str) -> int:
    payload = f"switchonyourcode-v1\0{environment_id}\0{flag_id}\0{bucket_value}".encode()
    digest = hashlib.sha256(payload).digest()
    prefix = int.from_bytes(digest[:4], byteorder="big", signed=False)
    return prefix % BUCKET_SCALE
