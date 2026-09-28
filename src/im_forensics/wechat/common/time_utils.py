# -*- coding: utf-8 -*-
"""时区与时间处理通用工具

强制将时间解析绑定到 Asia/Shanghai (CST, UTC+8)，确保跨系统/跨时区运行时时间戳转换绝对准确。
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

# 统一微信中国标准时区
DEFAULT_TZ = ZoneInfo("Asia/Shanghai")
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


def parse_date_boundary(date_str: str, is_end: bool, default_year: int | None = None, tz: ZoneInfo = DEFAULT_TZ) -> datetime.datetime:
    """解析日期字符串并返回指定时区的当天起始 (00:00:00) 或截止 (23:59:59) 时间。

    支持格式:
        - 完整日期: '2026-08-01', '2026/08/01', '20260801'
        - 带具体时间: '2026-08-01 12:00:00', '2026-08-01 12:00'
        - 简写月日: '0801', '8-1', '08-01' (自动使用当前年或传入的 default_year)
    """
    if default_year is None:
        default_year = datetime.datetime.now(tz=tz).year

    s = date_str.strip().replace("/", "-").replace(".", "")
    dt = None

    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            break
        except ValueError:
            pass

    if dt is None:
        for fmt in ("%m-%d", "%m%d"):
            try:
                parsed = datetime.datetime.strptime(s, fmt)
                dt = parsed.replace(year=default_year)
                break
            except ValueError:
                pass

    if dt is None:
        raise ValueError(f"无法解析日期格式: '{date_str}' (支持 YYYY-MM-DD, MMDD 等)")

    if is_end:
        return datetime.datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=tz)
    else:
        return datetime.datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=tz)


def format_timestamp(ts: int | float, tz: ZoneInfo = DEFAULT_TZ) -> tuple[datetime.datetime, str, str, str, str]:
    """将 Unix 秒级时间戳格式化为中国时区下的各种日期分量。

    返回:
        (datetime_obj, full_time_str, date_str, time_str, weekday_str)
    """
    dt = datetime.datetime.fromtimestamp(ts, tz=tz)
    full_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M:%S")
    weekday_str = f"星期{WEEKDAYS[dt.weekday()]}"
    return dt, full_str, date_str, time_str, weekday_str
