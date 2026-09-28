# -*- coding: utf-8 -*-
"""微信联系人解析器与头像读取服务

负责从 contact.db 和 head_image.db 中读取联系人档案、本地离线头像，
并提供多层级瀑布模糊匹配定位能力。
"""

from __future__ import annotations

import base64
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ContactProfile:
    """联系人档案实体"""
    username: str
    remark: str
    nick_name: str
    alias: str
    display_name: str
    avatar_base64: str | None = None

    @property
    def is_valid(self) -> bool:
        return bool(self.username)

    @property
    def is_chatroom(self) -> bool:
        return self.username.endswith("@chatroom")

    @property
    def is_official_account(self) -> bool:
        return self.username.startswith("gh_")

    @property
    def is_special_or_system(self) -> bool:
        system_prefixes = (
            "fmessage", "medianote", "floatbottle", "qmessage", "qqmail",
            "filehelper", "newsapp", "weixin", "weibo", "qqfriend",
        )
        return self.username.startswith(system_prefixes) or self.username in ("filehelper", "fmessage")

    @property
    def is_individual_contact(self) -> bool:
        """是否为正常私聊个人好友 (非群聊、非公众号、非系统号)"""
        return bool(self.username) and not (
            self.is_chatroom or self.is_official_account or self.is_special_or_system
        )


class ContactResolver:
    """联系人档案与头像解析管理服务"""

    def __init__(self, db_dir: Path | str):
        self.db_dir = Path(db_dir).resolve()
        self.contact_db_path = self.db_dir / "contact" / "contact.db"
        self.head_db_path = self.db_dir / "head_image" / "head_image.db"

        self._contacts_by_username: dict[str, ContactProfile] = {}
        self._avatars_by_username: dict[str, str] = {}
        self._loaded = False

    def load(self, force_reload: bool = False) -> None:
        """加载通讯录与本地头像缓存"""
        if self._loaded and not force_reload:
            return

        self._load_avatars()
        self._load_contacts()
        self._loaded = True

    def _load_avatars(self) -> None:
        """从 head_image.db 提取联系人头像并转为 Base64"""
        if not self.head_db_path.exists():
            return

        conn = sqlite3.connect(f"file:{self.head_db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        try:
            cur.execute("SELECT username, image_buffer FROM head_image WHERE image_buffer IS NOT NULL")
            for u, buf in cur.fetchall():
                if u and buf and len(buf) > 0:
                    b64 = base64.b64encode(buf).decode("ascii")
                    self._avatars_by_username[u.strip()] = f"data:image/jpeg;base64,{b64}"
        finally:
            conn.close()

    def _load_contacts(self) -> None:
        """从 contact.db 加载联系人档案"""
        if not self.contact_db_path.exists():
            return

        conn = sqlite3.connect(f"file:{self.contact_db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        try:
            cur.execute("SELECT username, remark, nick_name, alias FROM contact")
            for u, r, n, a in cur.fetchall():
                u_str = (u or "").strip()
                r_str = (r or "").strip()
                n_str = (n or "").strip()
                a_str = (a or "").strip()
                disp = r_str if r_str else (n_str if n_str else (a_str if a_str else u_str))
                avatar = self._avatars_by_username.get(u_str)

                profile = ContactProfile(
                    username=u_str,
                    remark=r_str,
                    nick_name=n_str,
                    alias=a_str,
                    display_name=disp,
                    avatar_base64=avatar,
                )
                self._contacts_by_username[u_str] = profile
        finally:
            conn.close()

    def get_contact_map(self) -> dict[str, ContactProfile]:
        """获取所有以 username 为 key 的联系人映射字典"""
        self.load()
        return self._contacts_by_username

    def get_avatar(self, username: str) -> str | None:
        """获取指定微信号的 Base64 头像"""
        self.load()
        return self._avatars_by_username.get(username)

    def find_contact(self, target: str) -> ContactProfile:
        """三层瀑布查找联系人:
        1. 优先精确匹配 username / remark / alias
        2. 其次精确匹配 nick_name
        3. 最后子串模糊包含匹配 (remark / nick_name / alias)
        """
        self.load()
        target_clean = target.strip().lower()

        profiles = list(self._contacts_by_username.values())

        # 1. 精确匹配微信号、备注或别名
        exact = [
            c for c in profiles
            if c.username.lower() == target_clean
            or c.remark.lower() == target_clean
            or c.alias.lower() == target_clean
        ]
        if len(exact) == 1:
            return exact[0]

        # 2. 精确匹配昵称
        nick_matches = [c for c in profiles if c.nick_name.lower() == target_clean]
        if len(nick_matches) == 1:
            return nick_matches[0]

        # 3. 模糊包含匹配
        fuzzy = [
            c for c in profiles
            if target_clean in c.remark.lower()
            or target_clean in c.nick_name.lower()
            or target_clean in c.alias.lower()
        ]

        if len(fuzzy) == 1:
            return fuzzy[0]
        elif len(fuzzy) > 1:
            matched_str = "\n".join(
                f"  - 微信ID: {c.username} | 备注: {c.remark} | 昵称: {c.nick_name} | 别名: {c.alias}"
                for c in fuzzy[:10]
            )
            raise ValueError(
                f"找到多个匹配联系人 '{target}', 请使用更精准的备注名或微信ID:\n{matched_str}"
            )
        else:
            raise ValueError(f"未在通讯录中找到匹配 '{target}' 的联系人")
