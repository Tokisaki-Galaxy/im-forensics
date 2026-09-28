# -*- coding: utf-8 -*-
"""微信聊天记录预处理核心模块 (LLM 紧凑会话切分与 Token 压缩引擎)

支持两种输入模式:
1. 直接接收内存中的 records 列表 (流式直通，免落盘 xlsx)
2. 读取既有的 xlsx 文件 (向前兼容)

输出列 (固定 5 列, UTF-8-SIG):
    会话ID / 日期 / 时刻 / 发送者 / 消息内容
    - 会话ID: 主对话按时间间隔切段; 转发块展开的子消息用 "父会话ID.序号" 表示
    - 日期:   每段首行保留完整日期, 其余留空
    - 时刻:   每段首行为绝对时间(HH:MM:SS), 其余为相对上一条的 "+Nmin"
"""

from __future__ import annotations

import collections
import csv
import datetime
import re
from pathlib import Path

import openpyxl

HEADER = ["会话ID", "日期", "时刻", "发送者", "消息内容"]

MEDIA_TAG = {
    "动画表情": "[动图]",
    "图片消息": "[图片]",
    "语音消息": "[语音]",
    "视频消息": "[视频]",
    "链接消息": "[链接]",
    "名片消息": "[名片]",
    "位置消息": "[位置]",
}

INNER_MEDIA_TAG = {
    "动画表情": "[动图]",
    "图片": "[图片]",
    "语音消息": "[语音]",
    "视频": "[视频]",
}

FORWARD_ENTRY = re.compile(
    r"^(\d+)\.\s*\[(.+?)\]\s+(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)\s+(\S+):\s?(.*)$",
    re.S,
)


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).replace("&#x20;", " ").replace("\u2005", " ").strip()


def parse_ts(value) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        return value
    s = clean_text(value)
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def compress_main(mtype: str, content: str) -> str:
    c = clean_text(content)
    if mtype == "文本消息":
        return c
    if mtype == "文件消息":
        rest = re.sub(r"^\s*\[文件\]\s*", "", c)
        return "[文件] " + rest if rest else "[文件]"
    if mtype == "系统消息":
        return "[系统] " + c
    if mtype == "其他消息":
        return "[消息]" if c == "[消息]" else "[互动] " + c
    tag = MEDIA_TAG.get(mtype)
    if tag:
        return tag
    return c


def parse_forward_block(content: str) -> list[tuple[int, str, datetime.datetime, str, str]]:
    c = clean_text(content)
    lines = c.split("\n")
    entries = []
    cur = None
    for line in lines:
        m = FORWARD_ENTRY.match(line)
        if m:
            if cur:
                entries.append(cur)
            idx_str, tag, ts_str, sender, rest = m.groups()
            ts = parse_ts(ts_str)
            cur = [int(idx_str), tag, ts, sender, rest]
        else:
            if cur:
                cur[4] += "\n" + line
    if cur:
        entries.append(cur)

    res = []
    for idx, tag, ts, sender, body in entries:
        body = body.strip()
        if tag == "聊天记录":
            compressed = "[转发]"
        elif tag == "微信转账":
            compressed = "[转账]"
        elif tag in INNER_MEDIA_TAG:
            compressed = INNER_MEDIA_TAG[tag]
        elif tag == "文件":
            rest = re.sub(r"^\s*\[文件\]\s*", "", body)
            compressed = "[文件] " + rest if rest else "[文件]"
        elif tag == "链接":
            compressed = "[链接]"
        elif tag == "合并转发的聊天记录":
            compressed = "[转发]"
        else:
            compressed = body if body else f"[{tag}]"
        res.append((idx, tag, ts, sender, compressed))
    return res


def build_events_from_records(records: list[dict]) -> list[dict]:
    """直接从 ChatExportService 产出的 records 内存字典列表构建事件流"""
    events = []
    for r in records:
        ts = r.get("datetime")
        if not ts:
            ts = parse_ts(r.get("time_str"))
        if not ts:
            continue

        sender = clean_text(r.get("sender_name", ""))
        mtype = clean_text(r.get("type_label", "文本消息"))
        raw_body = clean_text(r.get("content", ""))

        if mtype == "聊天记录合并转发" or "聊天记录详情" in raw_body:
            subs = parse_forward_block(raw_body)
            if subs:
                events.append({
                    "is_fwd": True,
                    "outer_ts": ts,
                    "outer_sender": sender,
                    "subs": subs,
                })
                continue

        body = compress_main(mtype, raw_body)
        events.append({
            "is_fwd": False,
            "ts": ts,
            "sender": sender,
            "body": body,
            "raw_body": raw_body,
            "type": mtype,
        })
    return events


def build_events_from_xlsx(xlsx_path: Path) -> list[dict]:
    """从既有 xlsx 文件读取并构建事件流"""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        return []
    col_map = {name: idx for idx, name in enumerate(header) if name}

    events = []
    for r in rows:
        ts_val = r[col_map.get("时间", col_map.get("日期", 0))]
        ts = parse_ts(ts_val)
        if not ts:
            continue

        sender = clean_text(r[col_map.get("发送人", col_map.get("发送者", 0))])
        mtype = clean_text(r[col_map.get("类型", col_map.get("消息类型", 0))] or "文本消息")
        raw_body = clean_text(r[col_map.get("内容", col_map.get("消息内容", 0))])

        if mtype == "聊天记录合并转发" or "聊天记录详情" in raw_body:
            subs = parse_forward_block(raw_body)
            if subs:
                events.append({
                    "is_fwd": True,
                    "outer_ts": ts,
                    "outer_sender": sender,
                    "subs": subs,
                })
                continue

        body = compress_main(mtype, raw_body)
        events.append({
            "is_fwd": False,
            "ts": ts,
            "sender": sender,
            "body": body,
            "raw_body": raw_body,
            "type": mtype,
        })
    wb.close()
    return events


def resolve_quotes(events: list[dict]) -> dict:
    text_history: list[dict] = []
    stats = {"quote_exact": 0, "quote_like": 0, "quote_none": 0}

    for ev in events:
        if ev["is_fwd"]:
            continue
        body = ev["body"]
        m = re.search(r"\(引用\s*([^:]+?):\s*(.*?)\)\s*$", body, re.S)
        if m:
            quoted_user = m.group(1).strip()
            quoted_text = m.group(2).strip()
            orig_match = None

            if quoted_text:
                for h in reversed(text_history):
                    if h["raw_body"] == quoted_text:
                        orig_match = h
                        stats["quote_exact"] += 1
                        break

            if not orig_match:
                for h in reversed(text_history):
                    if h["sender"] != ev["sender"]:
                        orig_match = h
                        stats["quote_like"] += 1
                        break

            new_body = body[: m.start()].rstrip()
            if orig_match:
                orig_body = orig_match["body"]
                tag = "原文" if (quoted_text and orig_match["raw_body"] == quoted_text) else "疑似原文"
                ev["body"] = f"{new_body} [{tag}: {orig_body}]".strip()
            else:
                ev["body"] = f"{new_body} [回复]".strip()
                stats["quote_none"] += 1
        else:
            text_history.append(ev)

    return stats


def emit_compact_data(events: list[dict], session_minutes: int) -> tuple[list[list[str]], dict]:
    stats = resolve_quotes(events)
    session_gap = datetime.timedelta(minutes=session_minutes)

    rows: list[list[str]] = []
    cur_session_id = 0
    last_main_ts: datetime.datetime | None = None
    last_main_date: str | None = None

    main_sender_counts = collections.Counter()
    sub_sender_counts = collections.Counter()
    type_counts = collections.Counter()
    session_info: dict[int, list] = {}
    raw_chars = 0
    out_chars = 0
    all_times: list[datetime.datetime] = []
    fwd_blocks = 0
    fwd_sub = 0

    for ev in events:
        if not ev["is_fwd"]:
            ts = ev["ts"]
            all_times.append(ts)
            sender = ev["sender"]
            body = ev["body"]
            main_sender_counts[sender] += 1
            type_counts[ev.get("type", "文本消息")] += 1
            raw_chars += len(ev.get("raw_body", body))

            if last_main_ts is None or (ts - last_main_ts) > session_gap:
                cur_session_id += 1
                session_info[cur_session_id] = [ts, 0, set()]
                last_main_date = None

            cur_date = ts.strftime("%Y/%m/%d")
            date_col = cur_date if cur_date != last_main_date else ""
            last_main_date = cur_date

            if session_info[cur_session_id][1] == 0:
                time_col = ts.strftime("%H:%M:%S")
            else:
                delta_m = max(0, int((ts - last_main_ts).total_seconds() // 60))
                time_col = f"+{delta_m}min"

            session_info[cur_session_id][1] += 1
            session_info[cur_session_id][2].add(sender)
            last_main_ts = ts

            rows.append([str(cur_session_id), date_col, time_col, sender, body])
            out_chars += len(body)
        else:
            fwd_blocks += 1
            outer_ts = ev["outer_ts"]
            all_times.append(outer_ts)
            if last_main_ts is None or (outer_ts - last_main_ts) > session_gap:
                cur_session_id += 1
                session_info[cur_session_id] = [outer_ts, 0, set()]
                last_main_date = None
            last_main_ts = outer_ts

            sub_session_idx = 0
            last_sub_ts: datetime.datetime | None = None
            last_sub_date: str | None = None

            for idx, tag, sub_ts, sub_sender, sub_body in ev["subs"]:
                fwd_sub += 1
                sub_sender_counts[sub_sender] += 1
                raw_chars += len(sub_body)
                eff_ts = sub_ts or outer_ts
                all_times.append(eff_ts)

                if last_sub_ts is None or (eff_ts - last_sub_ts) > session_gap:
                    sub_session_idx += 1
                    last_sub_date = None

                sid_str = f"{cur_session_id}.{sub_session_idx}"
                cur_date = eff_ts.strftime("%Y/%m/%d")
                date_col = cur_date if cur_date != last_sub_date else ""
                last_sub_date = cur_date

                if last_sub_ts is None:
                    time_col = eff_ts.strftime("%H:%M:%S")
                else:
                    delta_m = max(0, int((eff_ts - last_sub_ts).total_seconds() // 60))
                    time_col = f"+{delta_m}min"

                session_info[cur_session_id][1] += 1
                session_info[cur_session_id][2].add(f"[{sub_sender}]")
                last_sub_ts = eff_ts

                rows.append([sid_str, date_col, time_col, sub_sender, sub_body])
                out_chars += len(sub_body)

    stats["fwd_blocks"] = fwd_blocks
    stats["fwd_sub"] = fwd_sub

    summary = {
        "rows": len(rows),
        "sessions": len(session_info),
        "session_info": session_info,
        "main_senders": main_sender_counts,
        "sub_senders": sub_sender_counts,
        "types": type_counts,
        "quote": dict(stats["quote_exact"] and {"exact": stats["quote_exact"]} or {}),
        "stats": stats,
        "raw_chars": raw_chars,
        "out_chars": out_chars,
        "range": (min(all_times).strftime("%Y-%m-%d %H:%M"), max(all_times).strftime("%Y-%m-%d %H:%M")) if all_times else None,
    }
    return rows, summary


def generate_summary_text(summary: dict) -> str:
    lines = []
    lines.append("==== 微信对话 LLM 紧凑预处理统计摘要 ====")
    lines.append("")
    if summary["range"]:
        lines.append(f"时间范围: {summary['range'][0]} ~ {summary['range'][1]}")
    lines.append(f"输出总行数: {summary['rows']} (主对话 + 转发子消息)")
    lines.append(f"切分独立会话数: {summary['sessions']}")
    lines.append(f"转发块数: {summary['stats']['fwd_blocks']} | 转发子消息数: {summary['stats']['fwd_sub']}")
    q = summary["quote"]
    lines.append(
        f"引用消息: 精确命中 {q.get('exact', 0)} | 疑似命中 {summary['stats'].get('quote_like', 0)} | 未命中 {summary['stats'].get('quote_none', 0)}"
    )
    lines.append("")
    lines.append("---- 主对话发送者分布 ----")
    for sender, cnt in summary["main_senders"].most_common():
        pct = cnt / summary["rows"] * 100 if summary["rows"] else 0
        lines.append(f"{sender}: {cnt} 条 ({pct:.1f}%)")
    lines.append("")
    raw_tok = max(1, int(summary["raw_chars"] / 1.6))
    out_tok = max(1, int(summary["out_chars"] / 1.6))
    reduction = (1 - out_tok / raw_tok) * 100 if raw_tok else 0
    lines.append("---- Token 压缩预估 (按 1.6 字符/Token 折算) ----")
    lines.append(f"原始文本字符: {summary['raw_chars']} (~{raw_tok} Token)")
    lines.append(f"紧凑处理字符: {summary['out_chars']} (~{out_tok} Token)")
    lines.append(f"估算节省 Token: {reduction:.1f}%")
    return "\n".join(lines) + "\n"


def process_records_to_compact_csv(
    records: list[dict],
    out_csv_path: Path,
    session_minutes: int = 30,
) -> tuple[Path, Path, dict]:
    """直接将内存中的 records 转换为紧凑 CSV 与 summary 文本"""
    events = build_events_from_records(records)
    rows, summary = emit_compact_data(events, session_minutes)

    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)

    summary_path = out_csv_path.with_name(out_csv_path.stem.replace("_preprocessed", "") + "_summary.txt")
    summary_text = generate_summary_text(summary)
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(summary_text)

    return out_csv_path, summary_path, summary


def process_xlsx_to_compact_csv(
    xlsx_path: Path,
    out_csv_path: Path | None = None,
    session_minutes: int = 30,
) -> tuple[Path, Path, dict]:
    """读取已有 xlsx 文件并转换为紧凑 CSV 与 summary 文本"""
    events = build_events_from_xlsx(xlsx_path)
    rows, summary = emit_compact_data(events, session_minutes)

    target_csv = out_csv_path or xlsx_path.with_name(xlsx_path.stem + "_preprocessed.csv")
    target_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(target_csv, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)

    summary_path = target_csv.with_name(target_csv.stem.replace("_preprocessed", "") + "_summary.txt")
    summary_text = generate_summary_text(summary)
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(summary_text)

    return target_csv, summary_path, summary
