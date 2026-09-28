# -*- coding: utf-8 -*-
"""微信聊天动力学与统计量化计算引擎 (Chat Metrics Engine)

提供开箱即用的人际互动指标量化：
1. 消息量与字数不对等度 (Volume & Char Asymmetry)
2. 单条消息均长对比 (Avg Message Length)
3. 响应延迟中位数 (区分全天、白天工作时段、夜间空闲时段)
4. >30min 静默窗口后的主动追发比 (Chasing Bursts)
5. 时序轨迹与断崖拐点探测 (Phase Transition Inflection Points)
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Any


def calculate_chat_metrics(
    messages: list[dict[str, Any]],
    user_wxid: str,
    target_wxid: str,
    target_name: str,
) -> dict[str, Any]:
    """计算单联系人的完整关系动力学体检指标"""
    if not messages:
        return {"error": "消息记录为空"}

    # 1. 基础时空与容量统计
    total_msgs = len(messages)
    first_time = messages[0].get("timestamp") or messages[0].get("create_time", 0)
    last_time = messages[-1].get("timestamp") or messages[-1].get("create_time", 0)
    start_dt = datetime.datetime.fromtimestamp(first_time)
    end_dt = datetime.datetime.fromtimestamp(last_time)
    total_days = max(1, (end_dt.date() - start_dt.date()).days + 1)

    user_msgs = 0
    target_msgs = 0
    user_chars = 0
    target_chars = 0
    active_days_set: set[str] = set()
    daily_user_counts: dict[str, int] = defaultdict(int)
    daily_target_counts: dict[str, int] = defaultdict(int)

    # 2. 延迟与追发序列分析
    user_latencies_all: list[float] = []
    user_latencies_day: list[float] = []
    user_latencies_night: list[float] = []

    target_latencies_all: list[float] = []
    target_latencies_day: list[float] = []
    target_latencies_night: list[float] = []

    user_bursts_30m = 0
    target_bursts_30m = 0
    current_run_sender: str | None = None
    current_run_len = 0
    user_max_burst_streak = 0
    target_max_burst_streak = 0

    for idx, m in enumerate(messages):
        t = m.get("timestamp") or m.get("create_time", 0)
        dt = datetime.datetime.fromtimestamp(t)
        d_str = dt.strftime("%Y-%m-%d")
        active_days_set.add(d_str)

        sender = m["sender_wxid"]
        content = m.get("content") or ""
        
        # 针对字数统计做清洗，剥离长 XML / 引用卡片等非用户手打文字
        clean_text = content
        if " (引用 " in clean_text:
            clean_text = clean_text.split(" (引用 ")[0]
        if clean_text.startswith("<?xml") or clean_text.startswith("<msg"):
            clean_text = ""
        
        char_len = len(clean_text)

        is_user = (sender == user_wxid)
        if is_user:
            user_msgs += 1
            user_chars += char_len
            daily_user_counts[d_str] += 1
        else:
            target_msgs += 1
            target_chars += char_len
            daily_target_counts[d_str] += 1

        # 连续发送 streak 统计
        if sender == current_run_sender:
            current_run_len += 1
        else:
            current_run_sender = sender
            current_run_len = 1

        if is_user:
            if current_run_len > user_max_burst_streak:
                user_max_burst_streak = current_run_len
        else:
            if current_run_len > target_max_burst_streak:
                target_max_burst_streak = current_run_len

        # 延迟与追发判断 (从第2条起)
        if idx > 0:
            prev_m = messages[idx - 1]
            prev_t = prev_m.get("timestamp") or prev_m.get("create_time", 0)
            prev_sender = prev_m["sender_wxid"]
            delta_sec = t - prev_t

            # 跨会话/静默追发 (同一人间隔 > 30min 连续主动破冰发话)
            if delta_sec > 1800:
                if is_user and prev_sender == user_wxid:
                    user_bursts_30m += 1
                elif (not is_user) and prev_sender != user_wxid:
                    target_bursts_30m += 1

            # 交互响应延迟 (发送者发生切换时)
            if prev_sender != sender and delta_sec >= 0:
                hour = dt.hour
                is_day = 9 <= hour < 18
                is_night = 18 <= hour < 24

                if is_user:
                    user_latencies_all.append(delta_sec)
                    if is_day:
                        user_latencies_day.append(delta_sec)
                    elif is_night:
                        user_latencies_night.append(delta_sec)
                else:
                    target_latencies_all.append(delta_sec)
                    if is_day:
                        target_latencies_day.append(delta_sec)
                    elif is_night:
                        target_latencies_night.append(delta_sec)

    def _median(arr: list[float]) -> float:
        if not arr:
            return 0.0
        s = sorted(arr)
        n = len(s)
        if n % 2 == 1:
            return float(s[n // 2])
        return float((s[n // 2 - 1] + s[n // 2]) / 2.0)

    # 3. 周粒度时间序列与断崖拐点识别
    weekly_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"user": 0, "target": 0, "total": 0})
    for m in messages:
        t = m.get("timestamp") or m.get("create_time", 0)
        dt = datetime.datetime.fromtimestamp(t)
        # 获取周一作为周键
        w_monday = (dt - datetime.timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
        is_u = (m["sender_wxid"] == user_wxid)
        if is_u:
            weekly_buckets[w_monday]["user"] += 1
        else:
            weekly_buckets[w_monday]["target"] += 1
        weekly_buckets[w_monday]["total"] += 1

    sorted_weeks = sorted(weekly_buckets.keys())
    weekly_timeline = []
    inflection_points = []

    for i, w in enumerate(sorted_weeks):
        item = {
            "week": w,
            "total": weekly_buckets[w]["total"],
            "user": weekly_buckets[w]["user"],
            "target": weekly_buckets[w]["target"],
        }
        weekly_timeline.append(item)

        # 拐点检测: 如果前一周消息量较高(>=40条)，本周暴跌超过 50%
        if i > 0:
            prev_total = weekly_buckets[sorted_weeks[i - 1]]["total"]
            curr_total = item["total"]
            if prev_total >= 40 and (prev_total - curr_total) / prev_total >= 0.5:
                drop_rate = round((prev_total - curr_total) / prev_total * 100, 1)
                inflection_points.append({
                    "week": w,
                    "type": "骤冷断崖 (Drop)",
                    "prev_week_msgs": prev_total,
                    "curr_week_msgs": curr_total,
                    "drop_percentage": f"-{drop_rate}%",
                })

    active_days_count = len(active_days_set)
    user_avg_len = round(user_chars / max(1, user_msgs), 2)
    target_avg_len = round(target_chars / max(1, target_msgs), 2)
    char_ratio = round(user_chars / max(1, target_chars), 3)
    msg_ratio = round(user_msgs / max(1, target_msgs), 3)

    return {
        "summary": {
            "contact_name": target_name,
            "contact_wxid": target_wxid,
            "time_span": f"{start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}",
            "total_calendar_days": total_days,
            "active_days": active_days_count,
            "active_rate": f"{round(active_days_count / total_days * 100, 1)}%",
            "total_messages": total_msgs,
        },
        "balance": {
            "user_messages": user_msgs,
            "target_messages": target_msgs,
            "msg_ratio_user_to_target": msg_ratio,
            "user_msg_percent": f"{round(user_msgs / total_msgs * 100, 1)}%",
            "target_msg_percent": f"{round(target_msgs / total_msgs * 100, 1)}%",
            "user_total_chars": user_chars,
            "target_total_chars": target_chars,
            "char_ratio_user_to_target": char_ratio,
            "user_avg_chars_per_msg": user_avg_len,
            "target_avg_chars_per_msg": target_avg_len,
        },
        "response_rhythm": {
            "latency_median_all_seconds": {
                "user": _median(user_latencies_all),
                "target": _median(target_latencies_all),
            },
            "latency_median_daytime_seconds": {
                "user": _median(user_latencies_day),
                "target": _median(target_latencies_day),
            },
            "latency_median_night_seconds": {
                "user": _median(user_latencies_night),
                "target": _median(target_latencies_night),
            },
            "chasing_bursts_over_30min": {
                "user": user_bursts_30m,
                "target": target_bursts_30m,
                "ratio_user_to_target": round(user_bursts_30m / max(1, target_bursts_30m), 2),
            },
            "max_consecutive_messages": {
                "user": user_max_burst_streak,
                "target": target_max_burst_streak,
            },
        },
        "inflection_points": inflection_points,
        "weekly_timeline": weekly_timeline,
    }
