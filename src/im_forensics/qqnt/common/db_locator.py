# -*- coding: utf-8 -*-
"""QQ NT 数据库定位器

负责探测本地磁盘中的 QQ NT 数据目录及核心数据库文件（nt_msg.db、profile_info.db 等）。
支持配置优先、Z 盘优先及系统用户文档目录回退。
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import QQConfigManager


class QQNTLocator:
    """QQ NT 本地数据库探测器"""

    def __init__(self, config_manager: Optional[QQConfigManager] = None):
        self.config_mgr = config_manager or QQConfigManager()

    def get_candidate_roots(self) -> List[Path]:
        """获取可能包含 Tencent Files 的根目录"""
        roots = []
        cfg_dir = self.config_mgr.get_db_dir()
        if cfg_dir:
            p = Path(cfg_dir)
            if p.exists():
                roots.append(p)

        # 检查常见根路径
        candidates = [
            Path(r"Z:\Tencent Files"),
            Path.home() / "Documents" / "Tencent Files",
            Path(r"C:\Tencent Files"),
            Path(r"D:\Tencent Files"),
        ]
        for c in candidates:
            if c.exists() and c not in roots:
                roots.append(c)
        return roots

    def find_all_accounts(self) -> List[Dict[str, Path]]:
        """发现所有存在有效 nt_qq\\nt_db 的 QQ 账号目录"""
        accounts = []
        for root in self.get_candidate_roots():
            if root.name == "nt_db" and (root / "nt_msg.db").exists():
                # 直接指向 nt_db 的情况
                uin = 0
                for part in root.parts:
                    if part.isdigit():
                        uin = int(part)
                accounts.append({
                    "uin": uin,
                    "db_dir": root,
                    "nt_msg": root / "nt_msg.db",
                    "profile_info": root / "profile_info.db"
                })
                continue

            if not root.is_dir():
                continue

            for sub in root.iterdir():
                if sub.is_dir() and sub.name.isdigit():
                    nt_db = sub / "nt_qq" / "nt_db"
                    if nt_db.exists() and (nt_db / "nt_msg.db").exists():
                        accounts.append({
                            "uin": int(sub.name),
                            "db_dir": nt_db,
                            "nt_msg": nt_db / "nt_msg.db",
                            "profile_info": nt_db / "profile_info.db"
                        })
        return accounts

    def get_default_account(self) -> Tuple[int, Path, Path, Path]:
        """获取默认或当前配置账号的信息

        返回: (uin, db_dir, nt_msg_path, profile_info_path)
        """
        cfg_uin = self.config_mgr.get_uin()
        accounts = self.find_all_accounts()

        if not accounts:
            raise FileNotFoundError("未在常见路径中探测到 QQ NT 的 nt_db 目录。请在 config.json 中手动指定 db_dir。")

        # 优先匹配 config 中的 uin
        if cfg_uin:
            for acc in accounts:
                if acc["uin"] == cfg_uin:
                    return acc["uin"], acc["db_dir"], acc["nt_msg"], acc["profile_info"]

        # 默认取第一个账号
        target = accounts[0]
        self.config_mgr.set_uin(target["uin"])
        self.config_mgr.set_db_dir(str(target["db_dir"]))
        self.config_mgr.save()
        return target["uin"], target["db_dir"], target["nt_msg"], target["profile_info"]
