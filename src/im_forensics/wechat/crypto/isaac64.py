# -*- coding: utf-8 -*-
"""ISAAC-64: A fast cryptographic PRNG

纯 Python 完整复现 Bob Jenkins 的 ISAAC-64 算法，与微信官方客户端 WxIsaac64 完全同构。
"""

from __future__ import annotations

import struct


class Isaac64:
    """64 位 ISAAC 伪随机发生器 (用于微信朋友圈媒体与视频号解密)"""

    MASK = 0xFFFFFFFFFFFFFFFF
    # 注意：微信 WxIsaac64 使用的黄金分割常量为 0x9e3779b97f4a7c13 (结尾为 7c13，非 7c15)
    GOLDEN_RATIO = 0x9E3779B97F4A7C13

    def __init__(self, seed: int | str):
        self.mm = [0] * 256
        self.aa = 0
        self.bb = 0
        self.cc = 0
        self.randrsl = [0] * 256
        self.randcnt = 0
        self.randrsl[0] = int(seed) & self.MASK
        self._init(True)

    def _init(self, flag: bool):
        a = b = c = d = e = f = g = h = self.GOLDEN_RATIO

        def mix():
            nonlocal a, b, c, d, e, f, g, h
            a = (a - e) & self.MASK; f ^= h >> 9; h = (h + a) & self.MASK
            b = (b - f) & self.MASK; g ^= (a << 9) & self.MASK; a = (a + b) & self.MASK
            c = (c - g) & self.MASK; h ^= b >> 23; b = (b + c) & self.MASK
            d = (d - h) & self.MASK; a ^= (c << 15) & self.MASK; c = (c + d) & self.MASK
            e = (e - a) & self.MASK; b ^= d >> 14; d = (d + e) & self.MASK
            f = (f - b) & self.MASK; c ^= (e << 20) & self.MASK; e = (e + f) & self.MASK
            g = (g - c) & self.MASK; d ^= f >> 17; f = (f + g) & self.MASK
            h = (h - d) & self.MASK; e ^= (g << 14) & self.MASK; g = (g + h) & self.MASK

        for _ in range(4):
            mix()

        for i in range(0, 256, 8):
            if flag:
                a = (a + self.randrsl[i]) & self.MASK
                b = (b + self.randrsl[i + 1]) & self.MASK
                c = (c + self.randrsl[i + 2]) & self.MASK
                d = (d + self.randrsl[i + 3]) & self.MASK
                e = (e + self.randrsl[i + 4]) & self.MASK
                f = (f + self.randrsl[i + 5]) & self.MASK
                g = (g + self.randrsl[i + 6]) & self.MASK
                h = (h + self.randrsl[i + 7]) & self.MASK
            mix()
            self.mm[i] = a; self.mm[i + 1] = b; self.mm[i + 2] = c; self.mm[i + 3] = d
            self.mm[i + 4] = e; self.mm[i + 5] = f; self.mm[i + 6] = g; self.mm[i + 7] = h

        if flag:
            for i in range(0, 256, 8):
                a = (a + self.mm[i]) & self.MASK
                b = (b + self.mm[i + 1]) & self.MASK
                c = (c + self.mm[i + 2]) & self.MASK
                d = (d + self.mm[i + 3]) & self.MASK
                e = (e + self.mm[i + 4]) & self.MASK
                f = (f + self.mm[i + 5]) & self.MASK
                g = (g + self.mm[i + 6]) & self.MASK
                h = (h + self.mm[i + 7]) & self.MASK
                mix()
                self.mm[i] = a; self.mm[i + 1] = b; self.mm[i + 2] = c; self.mm[i + 3] = d
                self.mm[i + 4] = e; self.mm[i + 5] = f; self.mm[i + 6] = g; self.mm[i + 7] = h

        self._isaac64()
        self.randcnt = 256

    def _isaac64(self):
        self.cc = (self.cc + 1) & self.MASK
        self.bb = (self.bb + self.cc) & self.MASK
        for i in range(256):
            x = self.mm[i]
            rem = i & 3
            if rem == 0:
                self.aa = (self.aa ^ (((self.aa << 21) & self.MASK) ^ self.MASK)) & self.MASK
            elif rem == 1:
                self.aa = (self.aa ^ (self.aa >> 5)) & self.MASK
            elif rem == 2:
                self.aa = (self.aa ^ ((self.aa << 12) & self.MASK)) & self.MASK
            elif rem == 3:
                self.aa = (self.aa ^ (self.aa >> 33)) & self.MASK

            self.aa = (self.mm[(i + 128) & 255] + self.aa) & self.MASK
            y = (self.mm[(x >> 3) & 0xFF] + self.aa + self.bb) & self.MASK
            self.mm[i] = y
            self.bb = (self.mm[(y >> 11) & 0xFF] + x) & self.MASK
            self.randrsl[i] = self.bb

    def get_next(self) -> int:
        """获取下一个 64 位无符号随机数"""
        if self.randcnt == 0:
            self._isaac64()
            self.randcnt = 256
        self.randcnt -= 1
        return self.randrsl[self.randcnt]

    def generate_keystream_be(self, size: int) -> bytearray:
        """生成大端序 (Big-Endian) 64 位密钥流字节数组"""
        buf = bytearray(size)
        full_blocks = size // 8
        for i in range(full_blocks):
            val = self.get_next()
            struct.pack_into(">Q", buf, i * 8, val)
        rem = size % 8
        if rem > 0:
            last_k = self.get_next()
            temp = struct.pack(">Q", last_k)
            buf[full_blocks * 8 : full_blocks * 8 + rem] = temp[:rem]
        return buf
