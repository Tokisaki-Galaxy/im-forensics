# -*- coding: utf-8 -*-
"""QQ NT 联系人解析器

从解密后的 profile_info.db 中提取 QQ 好友信息，构建 UID/UIN ↔ 昵称/备注双向索引。
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union


@dataclass
class QQContact:
    uin: int
    uid: str
    nick: str
    remark: str
    qid: str = ""

    @property
    def display_name(self) -> str:
        if self.remark and self.remark.strip():
            return self.remark.strip()
        if self.nick and self.nick.strip():
            return self.nick.strip()
        return str(self.uin)


class QQContactResolver:
    """QQ 联系人信息查询与解析服务"""

    def __init__(self, decrypted_profile_db: Path):
        self.db_path = Path(decrypted_profile_db).resolve()
        self._uin_map: Dict[int, QQContact] = {}
        self._uid_map: Dict[str, QQContact] = {}
        self._contacts_list: List[QQContact] = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        if not self.db_path.exists():
            return

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            # profile_info_v6 列定义:
            # 1000: uid, 1002: uin, 20002: nick, 20009: remark, 1001: qid
            query = """
            SELECT "1002", "1000", "20002", "20009", "1001"
            FROM profile_info_v6
            WHERE "1002" IS NOT NULL AND "1002" > 0
            """
            cur.execute(query)
            for row in cur.fetchall():
                uin = int(row[0])
                uid = str(row[1] or "")
                nick = str(row[2] or "").strip()
                remark = str(row[3] or "").strip()
                qid = str(row[4] or "").strip()

                contact = QQContact(
                    uin=uin,
                    uid=uid,
                    nick=nick,
                    remark=remark,
                    qid=qid,
                )
                self._uin_map[uin] = contact
                if uid:
                    self._uid_map[uid] = contact
                self._contacts_list.append(contact)

            self._loaded = True
        finally:
            conn.close()

    def get_by_uin(self, uin: Union[int, str]) -> Optional[QQContact]:
        self.load()
        try:
            return self._uin_map.get(int(uin))
        except (ValueError, TypeError):
            return None

    def get_by_uid(self, uid: str) -> Optional[QQContact]:
        self.load()
        return self._uid_map.get(uid)

    def get_display_name(self, uin: Union[int, str]) -> str:
        c = self.get_by_uin(uin)
        if c:
            return c.display_name
        return str(uin)

    def search(self, query: str) -> List[QQContact]:
        """按 QQ 号、昵称或备注模糊检索联系人"""
        self.load()
        q = str(query).strip().lower()
        if not q:
            return []

        # 精确 QQ 号优先
        if q.isdigit():
            c = self.get_by_uin(int(q))
            if c:
                return [c]

        matched = []
        for c in self._contacts_list:
            if (
                q in str(c.uin)
                or q in c.display_name.lower()
                or q in c.nick.lower()
                or q in c.remark.lower()
                or q in c.qid.lower()
            ):
                matched.append(c)
        return matched

    def resolve_target(self, query: Union[int, str]) -> Optional[QQContact]:
        """智能解析唯一目标联系人"""
        self.load()
        q_str = str(query).strip()
        if q_str.isdigit():
            c = self.get_by_uin(int(q_str))
            if c:
                return c

        candidates = self.search(q_str)
        if not candidates:
            return None
        # 精确等于备注或昵称的优先
        for c in candidates:
            if c.remark == q_str or c.nick == q_str:
                return c
        return candidates[0]
