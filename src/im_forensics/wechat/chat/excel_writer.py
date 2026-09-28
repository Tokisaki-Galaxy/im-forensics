# -*- coding: utf-8 -*-
"""微信聊天记录标准 Excel 写入器

生成标准 11 列格式的 .xlsx 文件，严格遵守原始数据格式，并过滤低位非法控制字符。
"""

from __future__ import annotations

from pathlib import Path
import openpyxl
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

XLSX_HEADER = [
    "序号",
    "时间",
    "日期",
    "时刻",
    "星期",
    "发送者",
    "微信ID",
    "消息类型",
    "消息内容",
    "原始类型代码",
    "时间戳",
]


def write_chat_excel(rows: list[dict], output_file: Path) -> None:
    """将聊天记录列表写入标准 Excel 文件"""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "聊天记录"

    # 表头样式
    header_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    header_font = Font(name="Microsoft YaHei", size=10, bold=True)
    regular_font = Font(name="Microsoft YaHei", size=10)
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    ws.append(XLSX_HEADER)
    for col_idx in range(1, len(XLSX_HEADER) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center

    for idx, r in enumerate(rows, 1):
        raw_content = str(r["content"] or "")
        clean_content = ILLEGAL_CHARACTERS_RE.sub("", raw_content)

        row_data = [
            idx,
            r["time_str"],
            r["date_str"],
            r["moment_str"],
            r["weekday_str"],
            r["sender_name"],
            r["sender_wxid"],
            r["type_label"],
            clean_content,
            r["raw_type"],
            r["timestamp"],
        ]
        ws.append(row_data)

        # 简单对齐调整
        curr_row = idx + 1
        ws.cell(row=curr_row, column=1).alignment = align_center
        ws.cell(row=curr_row, column=2).alignment = align_center
        ws.cell(row=curr_row, column=3).alignment = align_center
        ws.cell(row=curr_row, column=4).alignment = align_center
        ws.cell(row=curr_row, column=5).alignment = align_center
        ws.cell(row=curr_row, column=6).alignment = align_center
        ws.cell(row=curr_row, column=7).alignment = align_left
        ws.cell(row=curr_row, column=8).alignment = align_center
        ws.cell(row=curr_row, column=9).alignment = align_left
        ws.cell(row=curr_row, column=10).alignment = align_center
        ws.cell(row=curr_row, column=11).alignment = align_center

        for col_idx in range(1, 12):
            ws.cell(row=curr_row, column=col_idx).font = regular_font

    # 设置列宽
    col_widths = {
        "A": 8,   # 序号
        "B": 20,  # 时间
        "C": 12,  # 日期
        "D": 10,  # 时刻
        "E": 8,   # 星期
        "F": 16,  # 发送者
        "G": 22,  # 微信ID
        "H": 12,  # 消息类型
        "I": 50,  # 消息内容
        "J": 14,  # 原始代码
        "K": 14,  # 时间戳
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    ws.freeze_panes = "A2"
    wb.save(output_file)
