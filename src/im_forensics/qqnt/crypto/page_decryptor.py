# -*- coding: utf-8 -*-
"""QQ NT 数据库流式按页解密器

针对 QQ NT SQLCipher 数据库的物理存储特性：
- 前 1024 字节自定义私有头，跳过
- 每页 4096 字节，尾部 48 字节为 SQLCipher 保留区 (16 字节 IV + 20 字节 HMAC + 12 字节元数据)
- Page 1 头部 16 字节为 Salt
- 保留原始 SQLite 页保留区大小 (byte 20 = 80)，严禁强行置 0 以免破坏 B-Tree 偏移
- 流式落盘与实时进度反馈，单核解密吞吐达 60MB/s+
"""

import os
import struct
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

EXT_HEADER = 1024
PAGE_SIZE = 4096
SALT_SIZE = 16
RESERVE = 48


def decrypt_page(page_raw: bytes, enc_key: bytes, skip_salt: int = 0) -> bytes:
    """解密单个 4096 字节页面

    返回值保证为 4096 字节的标准 SQLite 页面结构。
    """
    data = page_raw[skip_salt:]
    encrypted_len = len(data) - RESERVE
    encrypted = data[:encrypted_len]
    iv = data[encrypted_len : encrypted_len + 16]

    cipher = Cipher(algorithms.AES(enc_key), modes.CBC(iv))
    decrypted = cipher.decryptor().update(encrypted)

    if skip_salt > 0:
        # Page 1 特殊处理：恢复标准 SQLite 头 b'SQLite format 3\x00' 并补充尾部填充至 PAGE_SIZE
        hdr = bytearray(b"SQLite format 3\x00" + decrypted)
        hdr[16:18] = struct.pack(">H", PAGE_SIZE)
        # 保持 byte 20 (reserve) 为原样，切勿修改为 0
        if len(hdr) < PAGE_SIZE:
            hdr += b"\x00" * (PAGE_SIZE - len(hdr))
        return bytes(hdr[:PAGE_SIZE])
    else:
        # 普通页面：解密数据为 4048 字节，尾部填充 48 字节零以填满 4096 字节
        pad = PAGE_SIZE - len(decrypted)
        if pad > 0:
            return decrypted + (b"\x00" * pad)
        return decrypted[:PAGE_SIZE]


class QQPageDecryptor:
    """流式页面解密器"""

    def __init__(self, key_hex: str):
        self.enc_key = bytes.fromhex(key_hex)

    def decrypt_database(
        self,
        src_path: Path,
        dst_path: Path,
        progress_callback: Optional[Callable[[int, int, float, float], None]] = None,
        force: bool = False,
    ) -> Path:
        """解密数据库文件并落盘到 dst_path

        :param src_path: 源加密数据库路径
        :param dst_path: 目标明文数据库路径
        :param progress_callback: 进度回调 (cur_pages, total_pages, mb_per_sec, eta_sec)
        :param force: 是否强制重新解密（若 False 且 dst_path 较新且有效则直接跳过）
        :return: dst_path
        """
        src_path = Path(src_path).resolve()
        dst_path = Path(dst_path).resolve()

        if not src_path.exists():
            raise FileNotFoundError(f"源数据库不存在: {src_path}")

        # 检查是否可以复用已有缓存
        if not force and dst_path.exists():
            src_mtime = src_path.stat().st_mtime
            dst_mtime = dst_path.stat().st_mtime
            if dst_mtime >= src_mtime and dst_path.stat().st_size > 4096:
                return dst_path

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dst = dst_path.with_suffix(".tmp")

        src_size = src_path.stat().st_size
        if src_size <= EXT_HEADER + PAGE_SIZE:
            raise ValueError(f"数据库文件太小 ({src_size} 字节)")

        sc_size = src_size - EXT_HEADER
        total_pages = sc_size // PAGE_SIZE

        start_time = time.time()
        last_report_time = start_time
        processed_pages = 0

        # 批量读写缓冲区（例如 256 页 = 1MB 一批）
        BATCH_PAGES = 256

        with open(src_path, "rb") as in_f, open(tmp_dst, "wb") as out_f:
            in_f.seek(EXT_HEADER)

            while processed_pages < total_pages:
                pages_to_read = min(BATCH_PAGES, total_pages - processed_pages)
                raw_chunk = in_f.read(pages_to_read * PAGE_SIZE)
                if not raw_chunk:
                    break

                actual_pages = len(raw_chunk) // PAGE_SIZE
                decrypted_blocks = []

                for i in range(actual_pages):
                    pgno = processed_pages + i + 1
                    page_raw = raw_chunk[i * PAGE_SIZE : (i + 1) * PAGE_SIZE]
                    skip = SALT_SIZE if pgno == 1 else 0
                    dec = decrypt_page(page_raw, self.enc_key, skip_salt=skip)
                    decrypted_blocks.append(dec)

                out_f.write(b"".join(decrypted_blocks))
                processed_pages += actual_pages

                now = time.time()
                if progress_callback and (now - last_report_time >= 0.5 or processed_pages == total_pages):
                    elapsed = now - start_time
                    speed = (processed_pages * PAGE_SIZE / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0
                    remaining_pages = total_pages - processed_pages
                    eta = (remaining_pages * PAGE_SIZE / (1024 * 1024)) / speed if speed > 0 else 0.0
                    progress_callback(processed_pages, total_pages, speed, eta)
                    last_report_time = now

        # 解密完成，原子重命名替换
        if dst_path.exists():
            try:
                dst_path.unlink()
            except Exception:
                pass
        tmp_dst.rename(dst_path)
        return dst_path
