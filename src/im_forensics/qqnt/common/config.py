# -*- coding: utf-8 -*-
"""QQ NT 配置文件管理模块

负责管理本地缓存配置（包含已知账号、数据库路径与已提取的解密密钥）。
一次提取成功后持久化落盘，后续操作直接复用，不再重复探测进程内存。
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# 默认优先寻找仓库根目录下的 config.json，或模块目录下的 config.json
# Path(__file__) 为 src/im_forensics/qqnt/common/config.py
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
REPO_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "config.json"
FALLBACK_CONFIG_PATH = Path("data/qqnt_cache/config.json").resolve()


class QQConfigManager:
    """管理 QQ NT 工具配置与密钥持久化"""

    def __init__(self, config_path: Optional[Path] = None):
        env_config = os.environ.get("QQNT_CONFIG_PATH")
        if config_path:
            self.config_path = config_path
        elif env_config:
            self.config_path = Path(env_config).resolve()
        elif REPO_CONFIG_PATH.exists():
            self.config_path = REPO_CONFIG_PATH
        else:
            self.config_path = DEFAULT_CONFIG_PATH
        self.data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        target = self.config_path
        if not target.exists() and FALLBACK_CONFIG_PATH.exists():
            target = FALLBACK_CONFIG_PATH

        if target.exists():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "uin": None,
            "db_dir": None,
            "cache_dir": "data/qqnt_cache",
            "databases": {}
        }

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_uin(self) -> Optional[int]:
        return self.data.get("uin")

    def set_uin(self, uin: int) -> None:
        self.data["uin"] = uin

    def get_db_dir(self) -> Optional[str]:
        return self.data.get("db_dir")

    def set_db_dir(self, db_dir: str) -> None:
        self.data["db_dir"] = str(Path(db_dir).resolve())

    def get_cache_dir(self) -> Path:
        cache_dir = self.data.get("cache_dir", "data/qqnt_cache")
        p = Path(cache_dir)
        if not p.is_absolute():
            p = (Path(__file__).resolve().parent.parent.parent.parent / p).resolve()
        return p

    def get_key(self, db_name: str, salt_hex: Optional[str] = None) -> Optional[str]:
        """获取指定数据库的缓存密钥；若提供 salt_hex，必须 salt 匹配才返回"""
        dbs = self.data.get("databases", {})
        info = dbs.get(db_name)
        if not info:
            return None
        if salt_hex and info.get("salt") and info.get("salt").lower() != salt_hex.lower():
            return None
        return info.get("key")

    def set_key(self, db_name: str, salt_hex: str, key_hex: str) -> None:
        if "databases" not in self.data:
            self.data["databases"] = {}
        self.data["databases"][db_name] = {
            "salt": salt_hex.lower(),
            "key": key_hex.lower()
        }
