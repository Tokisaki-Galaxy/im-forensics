# -*- coding: utf-8 -*-
"""时间戳与日期辅助工具"""

import datetime
from typing import Optional, Union


def format_timestamp(ts: Union[int, float], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """将 Unix 秒级时间戳格式化为本地时间字符串"""
    if not ts:
        return ""
    try:
        dt = datetime.datetime.fromtimestamp(float(ts))
        return dt.strftime(fmt)
    except Exception:
        return str(ts)


def parse_date_to_timestamp(date_str: str, end_of_day: bool = False) -> Optional[int]:
    """将 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS 字符串解析为 Unix 秒级时间戳"""
    if not date_str:
        return None
    date_str = date_str.strip()
    try:
        if len(date_str) == 10:  # YYYY-MM-DD
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.timestamp())
        else:
            dt = datetime.datetime.fromisoformat(date_str)
            return int(dt.timestamp())
    except Exception:
        return None


def format_duration(seconds: float) -> str:
    """格式化秒数为时分秒友好展示"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}分钟"
    hours = minutes / 60
    return f"{hours:.1f}小时"
