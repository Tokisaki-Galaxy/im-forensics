# -*- coding: utf-8 -*-
"""微信数据库目录探测器

负责自适应定位解密后的微信数据库根目录 (包含 contact/, message/, sns/, head_image/ 等)。
"""

from __future__ import annotations

import os
from pathlib import Path


def locate_wechat_db_dir(specified_path: str | Path | None = None) -> Path:
    """自适应查找并返回合法的微信数据根目录。

    查找策略:
        1. 若用户指定了路径，优先使用并校验有效性。
        2. 若设置了 WECHAT_DB_DIR 环境变量，优先使用该环境变量指定的路径。
        3. 若未指定，按常用层级顺序探测常见路径 (如 WX/DB, data/WX/DB, lyx/output, output, .)。
    """
    if specified_path:
        p = Path(specified_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的微信数据库目录不存在: {p}")
        return p

    # 环境变量探测
    env_dir = os.environ.get("WECHAT_DB_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.exists() and ((p / "contact" / "contact.db").exists() or (p / "sns" / "sns.db").exists()):
            return p

    # 仓库根目录定位与常见候选位置
    # Path(__file__) 为 src/im_forensics/wechat/common/db_locator.py
    # .parent.parent.parent.parent.parent 即定位到 im-forensics 仓库根目录
    repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    candidates = [
        repo_root / "WX" / "DB",
        repo_root / "WX",
        repo_root / "data" / "WX" / "DB",
        Path("WX/DB").resolve(),
        Path("WX").resolve(),
        Path("data/WX/DB").resolve(),
        Path("lyx/output").resolve(),
        Path("output").resolve(),
        Path(".").resolve(),
    ]

    for cand in candidates:
        # 只要存在 contact/contact.db 或 message/ 或 sns/ 即判定为有效数据库目录
        if (cand / "contact" / "contact.db").exists() or (cand / "sns" / "sns.db").exists():
            return cand

    raise FileNotFoundError(
        "未能自动定位到微信数据库目录 (未找到 contact/contact.db 或 sns/sns.db)。\n"
        "请通过 -d / --db-dir 参数手动指定数据库目录。"
    )
