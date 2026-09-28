# -*- coding: utf-8 -*-
"""QQ NT 私聊 (C2C) 消息检索与关系分析核心服务

提供私聊消息提取、上下文检索、活跃度排行以及面向关系动力学的量化基线计算。
计算指标全面对齐 AGENTS.md 关系分析规范（比率、字符比、分时段中位延迟、追发突发等）。
"""

import datetime
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from ..common.contact_resolver import QQContactResolver
from ..common.time_utils import format_timestamp
from ..crypto.proto_parser import QQMsgContentParser


@dataclass
class C2CMessage:
    msg_id: int
    msg_time: int
    time_str: str
    peer_uin: int
    sender_uin: int
    is_self: bool
    sender_name: str
    msg_type: int
    display_text: str
    text_only: str
    char_count: int


class QQChatService:
    """QQ NT 聊天记录服务"""

    def __init__(self, decrypted_msg_db: Path, contact_resolver: QQContactResolver, my_uin: int):
        self.db_path = Path(decrypted_msg_db).resolve()
        self.contact_resolver = contact_resolver
        self.my_uin = my_uin

    def _get_connection(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"解密消息库不存在: {self.db_path}")
        return sqlite3.connect(self.db_path)

    def _row_to_message(self, row: tuple) -> C2CMessage:
        msg_id, msg_time, msg_direction, peer_uin, sender_uin, msg_type, msg_blob = row
        is_self = (sender_uin == self.my_uin) or (msg_direction in (1, 2))

        parsed = QQMsgContentParser.parse_msg_blob(msg_blob)

        if is_self:
            sender_name = "ME"
        else:
            sender_name = self.contact_resolver.get_display_name(sender_uin or peer_uin)

        return C2CMessage(
            msg_id=msg_id,
            msg_time=msg_time,
            time_str=format_timestamp(msg_time),
            peer_uin=peer_uin,
            sender_uin=sender_uin,
            is_self=is_self,
            sender_name=sender_name,
            msg_type=msg_type,
            display_text=parsed["display_text"],
            text_only=parsed["text_only"],
            char_count=parsed["raw_text_length"]
        )

    def get_c2c_peers(self) -> List[Dict[str, Any]]:
        """获取所有发生过私聊的联系人及消息汇总"""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            query = """
            SELECT "40030" as peer, count(*) as cnt, max("40050") as last_time
            FROM c2c_msg_table
            WHERE "40030" IS NOT NULL AND "40030" > 0
            GROUP BY "40030"
            ORDER BY last_time DESC
            """
            cur.execute(query)
            results = []
            for peer, cnt, last_time in cur.fetchall():
                c = self.contact_resolver.get_by_uin(peer)
                name = c.display_name if c else str(peer)
                results.append({
                    "peer_uin": peer,
                    "display_name": name,
                    "message_count": cnt,
                    "last_time": last_time,
                    "last_time_str": format_timestamp(last_time),
                    "nick": c.nick if c else "",
                    "remark": c.remark if c else ""
                })
            return results
        finally:
            conn.close()

    def get_recent(self, peer_uin: int, limit: int = 50) -> List[C2CMessage]:
        """获取与指定 peer 的最新 N 条私聊记录（按时间正序）"""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            query = """
            SELECT "40001", "40050", "40013", "40030", "40033", "40011", "40800"
            FROM c2c_msg_table
            WHERE "40030" = ?
            ORDER BY "40050" DESC, "40001" DESC
            LIMIT ?
            """
            cur.execute(query, (peer_uin, limit))
            rows = cur.fetchall()
            messages = [self._row_to_message(r) for r in reversed(rows)]
            return messages
        finally:
            conn.close()

    def search_messages(
        self,
        query: str,
        peer_uin: Optional[int] = None,
        context_window: int = 2,
        max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """全文检索私聊消息并附带上下文"""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            if peer_uin:
                sql = """
                SELECT "40001", "40050", "40013", "40030", "40033", "40011", "40800"
                FROM c2c_msg_table
                WHERE "40030" = ?
                ORDER BY "40050" ASC, "40001" ASC
                """
                cur.execute(sql, (peer_uin,))
            else:
                sql = """
                SELECT "40001", "40050", "40013", "40030", "40033", "40011", "40800"
                FROM c2c_msg_table
                ORDER BY "40050" ASC, "40001" ASC
                """
                cur.execute(sql)

            # 流式过滤与匹配
            all_rows = cur.fetchall()
            matched_indices = []
            parsed_cache: Dict[int, C2CMessage] = {}

            q_lower = query.lower()

            for idx, r in enumerate(all_rows):
                msg = self._row_to_message(r)
                parsed_cache[idx] = msg
                if q_lower in msg.display_text.lower():
                    matched_indices.append(idx)
                    if len(matched_indices) >= max_results:
                        break

            results = []
            for m_idx in matched_indices:
                target_msg = parsed_cache[m_idx]
                ctx_start = max(0, m_idx - context_window)
                ctx_end = min(len(all_rows), m_idx + context_window + 1)

                context_msgs = []
                for i in range(ctx_start, ctx_end):
                    if i not in parsed_cache:
                        parsed_cache[i] = self._row_to_message(all_rows[i])
                    context_msgs.append(parsed_cache[i])

                results.append({
                    "target": target_msg,
                    "context": context_msgs
                })
            return results
        finally:
            conn.close()

    def get_ranking(self, top_n: int = 20) -> List[Dict[str, Any]]:
        """获取私聊活跃度排行榜"""
        peers = self.get_c2c_peers()
        return peers[:top_n]

    def analyze_relationship(self, peer_uin: int) -> Dict[str, Any]:
        """计算与指定联系人的深度关系动力学指标（对齐 AGENTS.md 子代理一量化基线规范）"""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            sql = """
            SELECT "40001", "40050", "40013", "40030", "40033", "40011", "40800"
            FROM c2c_msg_table
            WHERE "40030" = ?
            ORDER BY "40050" ASC, "40001" ASC
            """
            cur.execute(sql, (peer_uin,))
            rows = cur.fetchall()
            if not rows:
                raise ValueError(f"未找到与 QQ 号 {peer_uin} 的私聊记录")

            messages = [self._row_to_message(r) for r in rows]

            contact = self.contact_resolver.get_by_uin(peer_uin)
            display_name = contact.display_name if contact else str(peer_uin)

            total_count = len(messages)
            my_count = 0
            peer_count = 0
            my_chars = 0
            peer_chars = 0

            # 时序与延迟统计
            hourly_counts = [0] * 24
            daily_series: Dict[str, Dict[str, int]] = {}

            # 延迟样本
            all_delays_me = []
            all_delays_peer = []
            daytime_delays_me = []
            daytime_delays_peer = []
            nighttime_delays_me = []
            nighttime_delays_peer = []

            # 追发统计（停顿超过 30 分钟后主动追发的次数）
            follow_up_gap_sec = 30 * 60
            my_follow_ups = 0
            peer_follow_ups = 0

            # 最大连续单向发送条数
            cur_sender = None
            cur_consecutive = 0
            my_max_consecutive = 0
            peer_max_consecutive = 0

            prev_msg: Optional[C2CMessage] = None

            for msg in messages:
                if msg.is_self:
                    my_count += 1
                    my_chars += msg.char_count
                else:
                    peer_count += 1
                    peer_chars += msg.char_count

                dt = datetime.datetime.fromtimestamp(msg.msg_time)
                hourly_counts[dt.hour] += 1

                day_str = dt.strftime("%Y-%m-%d")
                if day_str not in daily_series:
                    daily_series[day_str] = {"total": 0, "me": 0, "peer": 0}
                daily_series[day_str]["total"] += 1
                if msg.is_self:
                    daily_series[day_str]["me"] += 1
                else:
                    daily_series[day_str]["peer"] += 1

                # 连续发送分析
                if cur_sender == msg.is_self:
                    cur_consecutive += 1
                else:
                    cur_sender = msg.is_self
                    cur_consecutive = 1

                if msg.is_self:
                    my_max_consecutive = max(my_max_consecutive, cur_consecutive)
                else:
                    peer_max_consecutive = max(peer_max_consecutive, cur_consecutive)

                # 回复延迟与追发判定
                if prev_msg:
                    gap = msg.msg_time - prev_msg.msg_time
                    if gap >= 0:
                        if prev_msg.is_self == msg.is_self:
                            # 追发判定：同一人两次发送间隔 >= 30 分钟
                            if gap >= follow_up_gap_sec:
                                if msg.is_self:
                                    my_follow_ups += 1
                                else:
                                    peer_follow_ups += 1
                        else:
                            # 身份切换：回复延迟
                            hour = dt.hour
                            if msg.is_self:
                                all_delays_me.append(gap)
                                if 9 <= hour < 18:
                                    daytime_delays_me.append(gap)
                                elif 18 <= hour < 24:
                                    nighttime_delays_me.append(gap)
                            else:
                                all_delays_peer.append(gap)
                                if 9 <= hour < 18:
                                    daytime_delays_peer.append(gap)
                                elif 18 <= hour < 24:
                                    nighttime_delays_peer.append(gap)

                prev_msg = msg

            def median(lst: List[float]) -> float:
                if not lst:
                    return 0.0
                s = sorted(lst)
                n = len(s)
                mid = n // 2
                if n % 2 == 1:
                    return float(s[mid])
                return (s[mid - 1] + s[mid]) / 2.0

            first_time = messages[0].msg_time
            last_time = messages[-1].msg_time
            span_days = max(1, (last_time - first_time) / 86400.0)

            return {
                "metadata": {
                    "peer_uin": peer_uin,
                    "display_name": display_name,
                    "nick": contact.nick if contact else "",
                    "remark": contact.remark if contact else "",
                    "first_msg_time": format_timestamp(first_time),
                    "last_msg_time": format_timestamp(last_time),
                    "time_span_days": round(span_days, 1),
                },
                "volume_metrics": {
                    "total_messages": total_count,
                    "my_messages": my_count,
                    "peer_messages": peer_count,
                    "message_ratio": round(my_count / peer_count, 2) if peer_count > 0 else None,
                    "total_chars": my_chars + peer_chars,
                    "my_chars": my_chars,
                    "peer_chars": peer_chars,
                    "char_ratio": round(my_chars / peer_chars, 2) if peer_chars > 0 else None,
                    "my_avg_chars_per_msg": round(my_chars / my_count, 2) if my_count > 0 else 0,
                    "peer_avg_chars_per_msg": round(peer_chars / peer_count, 2) if peer_count > 0 else 0,
                },
                "latency_metrics": {
                    "me": {
                        "median_delay_sec": round(median(all_delays_me), 1),
                        "daytime_median_delay_sec": round(median(daytime_delays_me), 1),
                        "nighttime_median_delay_sec": round(median(nighttime_delays_me), 1),
                    },
                    "peer": {
                        "median_delay_sec": round(median(all_delays_peer), 1),
                        "daytime_median_delay_sec": round(median(daytime_delays_peer), 1),
                        "nighttime_median_delay_sec": round(median(nighttime_delays_peer), 1),
                    }
                },
                "burst_metrics": {
                    "my_follow_ups_after_30min": my_follow_ups,
                    "peer_follow_ups_after_30min": peer_follow_ups,
                    "my_max_consecutive_messages": my_max_consecutive,
                    "peer_max_consecutive_messages": peer_max_consecutive,
                },
                "hourly_distribution": hourly_counts,
                "daily_series": daily_series
            }
        finally:
            conn.close()
