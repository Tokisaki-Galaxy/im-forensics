# -*- coding: utf-8 -*-
"""QQ NT 聊天记录导出器

支持导出为多种结构化格式：
1. compact (清晰对齐纯文本，适合人类阅读或 LLM 提示词输入)
2. jsonl (机器解析与归档)
3. csv (表格化统计分析)
"""

import csv
import json
from pathlib import Path
from typing import List

from .service import C2CMessage


class QQChatExporter:
    """聊天记录导出器"""

    @staticmethod
    def export_compact(messages: List[C2CMessage], output_path: Path) -> Path:
        """导出为 compact 紧凑文本格式"""
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(f"[{msg.time_str}] {msg.sender_name}: {msg.display_text}\n")
        return output_path

    @staticmethod
    def export_jsonl(messages: List[C2CMessage], output_path: Path) -> Path:
        """导出为 JSONL 格式"""
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for msg in messages:
                item = {
                    "msg_id": msg.msg_id,
                    "time": msg.time_str,
                    "timestamp": msg.msg_time,
                    "peer_uin": msg.peer_uin,
                    "sender_uin": msg.sender_uin,
                    "is_self": msg.is_self,
                    "sender_name": msg.sender_name,
                    "msg_type": msg.msg_type,
                    "display_text": msg.display_text,
                    "text_only": msg.text_only,
                    "char_count": msg.char_count,
                }
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return output_path

    @staticmethod
    def export_csv(messages: List[C2CMessage], output_path: Path) -> Path:
        """导出为 CSV 格式"""
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "msg_id",
            "time",
            "sender",
            "is_self",
            "text",
            "char_count",
            "msg_type",
        ]
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for msg in messages:
                writer.writerow({
                    "msg_id": msg.msg_id,
                    "time": msg.time_str,
                    "sender": msg.sender_name,
                    "is_self": 1 if msg.is_self else 0,
                    "text": msg.display_text,
                    "char_count": msg.char_count,
                    "msg_type": msg.msg_type,
                })
        return output_path
