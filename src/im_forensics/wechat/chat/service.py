# -*- coding: utf-8 -*-
"""微信聊天记录导出服务 (Chat Export Pipeline)

处理联系人定位、Msg_{md5} 表跨分库聚合、WCDB 解压、XML 实体解析、时间过滤等全流程。
提供底层内存级查询 fetch_messages() 与上层导出 export()。
"""

from __future__ import annotations

import datetime
import glob
import hashlib
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common.contact_resolver import ContactProfile, ContactResolver
from ..common.db_locator import locate_wechat_db_dir
from ..common.time_utils import DEFAULT_TZ, format_timestamp, parse_date_boundary
from ..crypto.wcdb_decompress import decompress_wcdb_content
from .excel_writer import write_chat_excel
from .preprocessor import (
    process_records_to_compact_csv,
    process_xlsx_to_compact_csv,
)

# 微信核心消息类型映射
TYPE_MAP = {
    1: "文本",
    3: "图片",
    34: "语音",
    43: "视频",
    47: "表情",
    48: "位置",
    49: "分享/卡片",
    50: "音视频通话",
    10000: "系统通知",
    10002: "撤回通知",
}


def _parse_xml_message(raw_text: str, msg_type: int) -> tuple[str, str]:
    """解析 XML 消息中的标题、描述等结构化文本"""
    if not raw_text or not raw_text.strip().startswith("<"):
        return TYPE_MAP.get(msg_type, f"未知类型({msg_type})"), raw_text

    try:
        root = ET.fromstring(raw_text)
    except ET.ParseError:
        return TYPE_MAP.get(msg_type, f"未知类型({msg_type})"), raw_text

    appmsg = root.find("appmsg") if root.tag != "appmsg" else root
    if appmsg is not None:
        sub_type_str = appmsg.findtext("type")
        sub_type = int(sub_type_str) if sub_type_str and sub_type_str.isdigit() else msg_type

        title = (appmsg.findtext("title") or "").strip()
        des = (appmsg.findtext("des") or "").strip()

        # 微信红包
        if sub_type == 2001 or "微信红包" in title or "redpacket" in raw_text.lower():
            label = "微信红包"
            wording = title or "微信红包"
            return label, f"[微信红包] {wording}"

        # 转账
        if sub_type == 2000 or "转账" in title:
            return "微信转账", f"[微信转账] {title}"

        # 引用/回复消息
        if sub_type == 57:
            refer = appmsg.find("refermsg")
            refer_desc = ""
            if refer is not None:
                r_disp = (refer.findtext("displayname") or "").strip()
                r_cont = (refer.findtext("content") or "").strip()
                refer_desc = f" (引用 {r_disp}: {r_cont})" if r_disp or r_cont else ""
            return "引用回复", f"{title}{refer_desc}" if title else f"[引用消息]{refer_desc}"

        # 拍一拍 / 系统提示
        if "拍了拍" in title:
            return "拍一拍", title

        # 通用分享卡片
        type_labels = {
            5: "链接分享",
            6: "文件",
            19: "聊天记录合并转发",
            33: "小程序",
            36: "小程序",
            51: "视频号",
            63: "直播预约",
        }
        label = type_labels.get(sub_type, "分享/卡片")
        content_parts = [p for p in [title, des] if p]
        content_str = " - ".join(content_parts) if content_parts else raw_text
        return label, f"[{label}] {content_str}"

    return TYPE_MAP.get(msg_type, f"未知类型({msg_type})"), raw_text


@dataclass
class ChatExportResult:
    """聊天记录导出结果"""
    total_count: int
    output_files: list[Path]
    target_profile: ContactProfile
    summary: dict | None = None


class ChatExportService:
    """微信聊天记录导出与数据查询服务流水线"""

    def __init__(self, db_dir: Path | str | None = None, tz: ZoneInfo = DEFAULT_TZ):
        self.db_dir = locate_wechat_db_dir(db_dir)
        self.tz = tz
        self.contact_resolver = ContactResolver(self.db_dir)

    def fetch_messages(
        self,
        contact: str,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        reverse: bool = False,
    ) -> tuple[ContactProfile, list[dict]]:
        """底层内存级消息获取流水线:
        跨分卷提取解密指定联系人的聊天记录，返回 (ContactProfile, list[record])
        - reverse: 是否按时间倒序排列 (用于 recent 场景)
        - limit: 限制获取条数
        """
        target_info = self.contact_resolver.find_contact(contact)
        target_wxid = target_info.username
        disp_name = target_info.display_name

        now = datetime.datetime.now(tz=self.tz)
        start_dt = (
            parse_date_boundary(since, is_end=False, default_year=now.year, tz=self.tz)
            if since
            else datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=self.tz)
        )
        end_dt = (
            parse_date_boundary(until, is_end=True, default_year=now.year, tz=self.tz)
            if until
            else datetime.datetime(2099, 12, 31, 23, 59, 59, tzinfo=self.tz)
        )

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        table_name = f"Msg_{hashlib.md5(target_wxid.encode('utf-8')).hexdigest()}"
        msg_dbs = sorted(glob.glob(str(self.db_dir / "message" / "message_*.db")))
        if not msg_dbs:
            single_msg = self.db_dir / "message" / "message.db"
            if single_msg.exists():
                msg_dbs = [str(single_msg)]

        all_records = []
        name_map = self.contact_resolver.get_contact_map()

        for db_file in msg_dbs:
            try:
                conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                if not cur.fetchone():
                    conn.close()
                    continue

                id_to_sender = {}
                cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Name2Id'")
                if cur.fetchone():
                    cur.execute("SELECT rowid, user_name FROM Name2Id")
                    for r_id, u_name in cur.fetchall():
                        id_to_sender[r_id] = u_name

                query = f"""
                    SELECT local_id, server_id, local_type, real_sender_id, create_time, message_content
                    FROM {table_name}
                    WHERE create_time >= ? AND create_time <= ?
                """
                cur.execute(query, (start_ts, end_ts))
                rows = cur.fetchall()

                for loc_id, srv_id, m_type, sender_id, c_time, m_content in rows:
                    content_str = decompress_wcdb_content(m_content)
                    sender_wxid = id_to_sender.get(sender_id, "")
                    if not sender_wxid:
                        sender_wxid = target_wxid

                    if sender_wxid == target_wxid:
                        sender_disp = disp_name
                    else:
                        sender_profile = name_map.get(sender_wxid)
                        sender_disp = sender_profile.display_name if sender_profile else sender_wxid

                    type_label, parsed_content = _parse_xml_message(content_str, m_type)
                    dt, full_time, date_str, time_str, weekday_str = format_timestamp(c_time, tz=self.tz)

                    all_records.append({
                        "local_id": loc_id,
                        "server_id": srv_id,
                        "timestamp": c_time,
                        "datetime": dt,
                        "time_str": full_time,
                        "date_str": date_str,
                        "moment_str": time_str,
                        "weekday_str": weekday_str,
                        "sender_wxid": sender_wxid,
                        "sender_name": sender_disp,
                        "is_sender": sender_wxid != target_wxid,
                        "type": m_type,
                        "type_label": type_label,
                        "content": parsed_content,
                        "raw_length": len(parsed_content),
                    })
                conn.close()
            except sqlite3.DatabaseError as e:
                print(f"[警告] 数据库文件损坏或读取异常，已跳过: {db_file} (错误: {e})", file=sys.stderr)
                continue

        # 排序
        all_records.sort(key=lambda x: (x["timestamp"], x["local_id"]), reverse=reverse)
        if limit is not None and limit > 0:
            all_records = all_records[:limit]

        return target_info, all_records

    def search_messages(
        self,
        query: str,
        contact: str | None = None,
        context: int = 0,
        limit: int = 50,
        regex: bool = False,
    ) -> list[dict]:
        """在聊天记录中检索关键词或正则模式
        返回结构包含命中项及前后上下文窗口
        """
        import re
        pattern = re.compile(query, re.IGNORECASE) if regex else None
        q_lower = query.lower()

        # 确定检索目标联系人列表
        contacts_to_search: list[ContactProfile] = []
        if contact:
            target_info = self.contact_resolver.find_contact(contact)
            contacts_to_search.append(target_info)
        else:
            for c in self.contact_resolver.get_contact_map().values():
                if c.is_individual_contact:
                    contacts_to_search.append(c)

        results = []
        for c_info in contacts_to_search:
            _, records = self.fetch_messages(c_info.username, reverse=False)
            if not records:
                continue

            for idx, msg in enumerate(records):
                text = str(msg.get("content") or "")
                matched = False
                if pattern:
                    matched = bool(pattern.search(text))
                else:
                    matched = q_lower in text.lower()

                if matched:
                    # 提取上下文
                    c_start = max(0, idx - context)
                    c_end = min(len(records), idx + context + 1)
                    ctx_msgs = records[c_start:c_end]

                    results.append({
                        "contact_username": c_info.username,
                        "contact_display_name": c_info.display_name,
                        "match_message": msg,
                        "match_index": idx,
                        "context_messages": ctx_msgs,
                    })
                    if len(results) >= limit:
                        return results

        return results

    def analyze_relationship(
        self,
        contact: str,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        """对指定联系人执行完整关系动力学量化分析"""
        from .metrics import calculate_chat_metrics

        profile, messages = self.fetch_messages(contact=contact, since=since, until=until, reverse=False)
        if not messages:
            return {"error": f"未找到与联系人 {contact} 的任何聊天记录"}

        # 动态推断用户本人的 wxid (消息列表中不是 target_wxid 的即为 user_wxid)
        user_wxid = "user"
        for m in messages:
            if m["sender_wxid"] != profile.username:
                user_wxid = m["sender_wxid"]
                break

        return calculate_chat_metrics(
            messages=messages,
            user_wxid=user_wxid,
            target_wxid=profile.username,
            target_name=profile.display_name,
        )

    def rank_top_contacts(self, limit: int = 15) -> list[dict[str, Any]]:
        """全库统计所有私聊联系人的消息总数排行榜 (自动过滤群聊与服务号)"""
        contact_map = self.contact_resolver.get_contact_map()
        results = []

        msg_dbs = sorted(glob.glob(str(self.db_dir / "message" / "message_*.db")))
        if not msg_dbs:
            single_msg = self.db_dir / "message" / "message.db"
            if single_msg.exists():
                msg_dbs = [str(single_msg)]

        # 1. 预先单次扫描所有分卷库中的所有 Msg_ 表总数 (毫秒级，防御损坏库或分卷)
        table_counts: dict[str, int] = {}
        for db_path in msg_dbs:
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
                tables = [r[0] for r in cur.fetchall()]
                for t in tables:
                    try:
                        cur.execute(f"SELECT count(*) FROM {t}")
                        cnt = cur.fetchone()[0]
                        table_counts[t] = table_counts.get(t, 0) + cnt
                    except sqlite3.DatabaseError as e:
                        print(f"[警告] 表读取异常，已跳过: {db_path.name} -> {t} (错误: {e})", file=sys.stderr)
                        continue
            except sqlite3.DatabaseError as e:
                print(f"[警告] 数据库文件损坏或读取异常，已跳过: {db_path} (错误: {e})", file=sys.stderr)
                continue
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        # 2. 匹配联系人映射并过滤非私聊
        for p_info in contact_map.values():
            if not p_info.is_individual_contact:
                continue

            md5_hash = hashlib.md5(p_info.username.encode("utf-8")).hexdigest()
            table_name = f"Msg_{md5_hash}"
            total_msgs = table_counts.get(table_name, 0)

            if total_msgs > 0:
                results.append({
                    "username": p_info.username,
                    "display_name": p_info.display_name,
                    "remark": p_info.remark,
                    "nick_name": p_info.nick_name,
                    "alias": p_info.alias,
                    "total_messages": total_msgs,
                })

        results.sort(key=lambda x: x["total_messages"], reverse=True)
        return results[:limit]

    def export(
        self,
        contact: str,
        since: str | None = None,
        until: str | None = None,
        output_dir: Path | str | None = None,
        contact_name_override: str | None = None,
        export_format: str = "xlsx",  # "xlsx", "compact", "both"
        session_minutes: int = 30,
    ) -> ChatExportResult:
        """完整导出流水线:
        支持导出标准 Excel (xlsx) 或 专门面向 LLM 的紧凑 CSV (compact)
        """
        target_info, all_records = self.fetch_messages(
            contact=contact,
            since=since,
            until=until,
            reverse=False,
        )
        disp_override = (contact_name_override or "").strip()
        disp_name = disp_override if disp_override else target_info.display_name

        print("=" * 50)
        print(f"定位到聊天联系人: {disp_name}")
        print(f"  微信ID: {target_info.username}")
        print(f"  备注名: {target_info.remark or '(无)'}")
        print(f"  昵称:   {target_info.nick_name or '(无)'}")
        print(f"  提取消息记录共: {len(all_records)} 条")
        print("=" * 50)

        target_dir = Path(output_dir).resolve() if output_dir else self.db_dir.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.datetime.now(tz=self.tz)
        if since and until:
            s_dt = parse_date_boundary(since, is_end=False, default_year=now.year, tz=self.tz)
            u_dt = parse_date_boundary(until, is_end=True, default_year=now.year, tz=self.tz)
            base_filename = f"{disp_name}_{s_dt.strftime('%m%d')}-{u_dt.strftime('%m%d')}"
        else:
            base_filename = f"chat_{disp_name}"

        output_files: list[Path] = []
        summary_res: dict | None = None

        # 1. 导出 Excel
        if export_format in ("xlsx", "both"):
            out_xlsx = target_dir / f"{base_filename}.xlsx"
            write_chat_excel(all_records, out_xlsx)
            print(f"[导出完成] Excel 文件已保存至: {out_xlsx}")
            output_files.append(out_xlsx)

        # 2. 导出 LLM 紧凑 CSV
        if export_format in ("compact", "both"):
            out_csv = target_dir / f"{base_filename}_preprocessed.csv"
            out_csv, summary_path, summary_res = process_records_to_compact_csv(
                records=all_records,
                out_csv_path=out_csv,
                session_minutes=session_minutes,
            )
            print(f"[导出完成] LLM 紧凑 CSV 已保存至: {out_csv}")
            print(f"[导出完成] 会话切分摘要已保存至: {summary_path}")
            output_files.append(out_csv)
            output_files.append(summary_path)

        return ChatExportResult(
            total_count=len(all_records),
            output_files=output_files,
            target_profile=target_info,
            summary=summary_res,
        )
