# -*- coding: utf-8 -*-
"""WCDB 文本/XML 压缩数据解压服务

处理微信数据库中以 Zstandard (RFC 8878) 压缩的长文本与富文本 XML。
"""

from __future__ import annotations

import zstandard as zstd

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_DECOMPRESSOR = zstd.ZstdDecompressor()


def decompress_wcdb_content(raw_bytes: bytes | bytearray | str | None) -> str:
    """解压 WCDB 压缩内容并转为 UTF-8 字符串。若未压缩则直接解码。"""
    if not raw_bytes:
        return ""

    if isinstance(raw_bytes, str):
        return raw_bytes

    b = bytes(raw_bytes)
    if b.startswith(_ZSTD_MAGIC):
        try:
            decompressed = _DECOMPRESSOR.decompress(b)
            return decompressed.decode("utf-8", errors="replace")
        except Exception:
            pass

    return b.decode("utf-8", errors="replace")
