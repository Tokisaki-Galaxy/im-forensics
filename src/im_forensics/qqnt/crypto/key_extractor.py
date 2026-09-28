# -*- coding: utf-8 -*-
"""QQ NT 数据库密钥提取器

利用 Windows ReadProcessMemory 对运行中 QQ NT 主进程 (加载 wrapper.node 的进程)
进行无注入只读扫描，提取并 HMAC 校验 SQLCipher AES-256 密钥。
提取成功后写入本地配置文件，后续调用优先从配置读取，避免重复扫描。
"""

import ctypes
import ctypes.wintypes as wt
import hashlib
import hmac
import os
import struct
from pathlib import Path
from typing import List, Optional, Tuple

from ..common.config import QQConfigManager

EXT_HEADER = 1024
PAGE_SIZE = 4096
SALT_SIZE = 16
RESERVE = 48
KDF_ITER = 4000

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PAGE_READONLY = 0x02
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40

kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD),
        ("PartitionId", wt.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


def verify_key_hmac(page1_raw: bytes, enc_key_bytes: bytes) -> bool:
    """验证 32 字节 AES 密钥与 Page 1 存储的 HMAC-SHA1 校验和是否吻合"""
    if len(page1_raw) < PAGE_SIZE:
        return False
    salt = page1_raw[:SALT_SIZE]
    hmac_salt = bytes(b ^ 0x3A for b in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", enc_key_bytes, hmac_salt, 2, 32)

    content = page1_raw[SALT_SIZE : PAGE_SIZE - RESERVE]
    iv = page1_raw[PAGE_SIZE - RESERVE : PAGE_SIZE - RESERVE + 16]
    stored_hmac = page1_raw[PAGE_SIZE - RESERVE + 16 : PAGE_SIZE - RESERVE + 36]

    computed_hmac = hmac.new(
        hmac_key,
        content + iv + struct.pack("<I", 1),
        hashlib.sha1
    ).digest()

    return computed_hmac == stored_hmac


def get_db_salt(db_path: Path) -> Tuple[bytes, bytes]:
    """读取 DB 的 salt 与 Page 1 原始密文 (跳过 1024 字节自定义头)"""
    with open(db_path, "rb") as f:
        f.seek(EXT_HEADER)
        page1 = f.read(PAGE_SIZE)
    if len(page1) < PAGE_SIZE:
        raise ValueError(f"数据库文件过小或已损坏: {db_path}")
    salt = page1[:SALT_SIZE]
    return salt, page1


def find_qq_pids() -> List[int]:
    """枚举所有 QQ.exe 进程 PID"""
    import subprocess
    cmd = 'tasklist /fi "imagename eq QQ.exe" /fo csv /nh'
    try:
        output = subprocess.check_output(cmd, shell=True, text=True, errors="ignore")
    except Exception:
        return []
    pids = []
    for line in output.strip().splitlines():
        parts = [p.strip('"\r') for p in line.split(",")]
        if len(parts) >= 2 and parts[0].lower() == "qq.exe" and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


def is_wrapper_node_loaded(pid: int) -> bool:
    """检查指定 PID 进程是否加载了 wrapper.node 模块"""
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h_proc:
        return False
    try:
        cb_needed = wt.DWORD()
        h_mods = (wt.HMODULE * 1024)()
        if not psapi.EnumProcessModules(h_proc, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed)):
            return False
        mod_count = cb_needed.value // ctypes.sizeof(wt.HMODULE)
        buf = ctypes.create_unicode_buffer(512)
        for i in range(mod_count):
            if psapi.GetModuleBaseNameW(h_proc, h_mods[i], buf, 512):
                if buf.value.lower() == "wrapper.node":
                    return True
        return False
    finally:
        kernel32.CloseHandle(h_proc)


def scan_process_memory_for_keys(pid: int, targets: dict) -> dict:
    """扫描指定进程内存中匹配目标 salt 的 SQLCipher 密钥

    targets: {salt_hex: (db_name, page1_raw)}
    返回: {db_name: (salt_hex, key_hex)}
    """
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h_proc:
        return {}

    readable_flags = (PAGE_READONLY | PAGE_READWRITE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE)
    remaining = dict(targets)
    found = {}

    try:
        mbi = MEMORY_BASIC_INFORMATION()
        cur_addr = 0
        max_addr = 0x7FFFFFFF0000

        while cur_addr < max_addr and remaining:
            res = kernel32.VirtualQueryEx(h_proc, ctypes.c_void_p(cur_addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
            if not res:
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            cur_addr = base + size

            if mbi.State != MEM_COMMIT or not (mbi.Protect & readable_flags):
                continue

            buf = ctypes.create_string_buffer(size)
            bytes_read = ctypes.c_size_t()
            if not kernel32.ReadProcessMemory(h_proc, ctypes.c_void_p(base), buf, size, ctypes.byref(bytes_read)):
                continue

            mem_data = buf.raw[: bytes_read.value]

            # 遍历每个尚未找到 key 的 salt
            for salt_hex in list(remaining.keys()):
                salt_ascii = salt_hex.encode("ascii")
                idx = 0
                while True:
                    idx = mem_data.find(salt_ascii, idx)
                    if idx == -1:
                        break

                    # 检查前方是否有 x' 标记及 64 字节十六进制 key: x'<64hex><32salt>'
                    if idx >= 66 and mem_data[idx - 66 : idx - 64] == b"x'":
                        candidate_key_hex = mem_data[idx - 64 : idx].decode("ascii", errors="ignore")
                        if len(candidate_key_hex) == 64:
                            try:
                                candidate_key_bytes = bytes.fromhex(candidate_key_hex)
                                db_name, page1_raw = remaining[salt_hex]
                                if verify_key_hmac(page1_raw, candidate_key_bytes):
                                    found[db_name] = (salt_hex, candidate_key_hex)
                                    del remaining[salt_hex]
                                    break
                            except ValueError:
                                pass
                    idx += 1
    finally:
        kernel32.CloseHandle(h_proc)

    return found


class QQKeyExtractor:
    """QQ NT 密钥提取门面"""

    def __init__(self, config_manager: Optional[QQConfigManager] = None):
        self.config_mgr = config_manager or QQConfigManager()

    def get_or_extract_key(self, db_path: Path) -> str:
        """获取或提取指定数据库的 AES-256 密钥（字符串十六进制）

        1. 优先尝试本地配置；若配置中的密钥能通过当前 DB 第 1 页的 HMAC 验证，立即返回。
        2. 若本地无有效密钥，自动扫描当前 QQ NT 进程内存，提取并验证，然后写入配置。
        """
        db_path = Path(db_path).resolve()
        salt, page1 = get_db_salt(db_path)
        salt_hex = salt.hex().lower()
        db_name = db_path.name

        # 1. 尝试缓存
        cached_key = self.config_mgr.get_key(db_name, salt_hex)
        if cached_key:
            try:
                cached_bytes = bytes.fromhex(cached_key)
                if verify_key_hmac(page1, cached_bytes):
                    return cached_key
            except Exception:
                pass

        # 2. 内存探测
        pids = find_qq_pids()
        if not pids:
            raise RuntimeError("未检测到运行中的 QQ.exe 进程，且本地无有效缓存密钥。请先登录 QQ。")

        target_pid = None
        for pid in pids:
            if is_wrapper_node_loaded(pid):
                target_pid = pid
                break
        if not target_pid:
            target_pid = pids[0]

        targets = {salt_hex: (db_name, page1)}
        results = scan_process_memory_for_keys(target_pid, targets)

        if db_name not in results:
            raise RuntimeError(f"在 QQ 进程内存中未能提取到 {db_name} 的有效解密密钥。")

        _, key_hex = results[db_name]

        # 3. 写入本地配置
        self.config_mgr.set_key(db_name, salt_hex, key_hex)
        self.config_mgr.save()

        return key_hex
