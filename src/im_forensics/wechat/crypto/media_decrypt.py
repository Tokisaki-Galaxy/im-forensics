# -*- coding: utf-8 -*-
"""微信 CDN 富媒体解密服务

基于 ISAAC-64 算法，解密微信朋友圈图片、缩略图及视频文件。
"""

from __future__ import annotations

from .isaac64 import Isaac64


def decrypt_wechat_media(data: bytearray | bytes, key: int | str, is_video: bool = False) -> bytearray:
    """解密微信朋友圈图片或视频数据。

    解密规则:
        - key 为 0、空或 None 时不执行解密，直接返回原始字节数组。
        - 图片: 全量字节按 ISAAC-64 大端序流式异或 (XOR) 解密。
        - 视频: 仅对前 128KB (131,072 字节) 进行异或解密，恢复 MP4 容器头部 (ftypisom)。
    """
    buf = bytearray(data)
    if not key or str(key).strip() in ("", "0"):
        return buf

    seed = int(key)
    isaac = Isaac64(seed)

    if is_video:
        enc_len = min(131072, len(buf))
    else:
        enc_len = len(buf)

    keystream = isaac.generate_keystream_be(enc_len)
    for i in range(enc_len):
        buf[i] ^= keystream[i]

    return buf
