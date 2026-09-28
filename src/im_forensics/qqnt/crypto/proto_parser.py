# -*- coding: utf-8 -*-
"""QQ NT 消息体 (40800 BLOB) 轻量 Protobuf Wire 解析器

针对 QQ NT 客户端存储的 Protobuf 消息结构进行免依赖纯 Python Wire 级解码。
字段规范对应关系：
- 40800: MsgBody / MsgContent (Repeated 元素列表)
- 45002: 消息元素类型 (1: 文本, 2: 图片, 3: 文件, 6: 系统表情, 7: 引用回复, 11: 结构化卡片)
- 45101: 纯文本内容 (UTF-8)
- 45302: 系统表情 ID / 描述
- 45402: 媒体文件名 / 图片 Hash
- 45403: 媒体文件大小
- 45815: 媒体描述或缩略说明 (如 [动画表情])
"""

from typing import Any, Dict, List, Optional, Tuple

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_32BIT = 5


def decode_varint(data: bytes, offset: int) -> Tuple[int, int]:
    """解码 Varint 整数，返回 (value, new_offset)"""
    res = 0
    shift = 0
    pos = offset
    length = len(data)
    while pos < length:
        b = data[pos]
        pos += 1
        res |= (b & 0x7F) << shift
        if not (b & 0x80):
            return res, pos
        shift += 7
    return res, pos


def parse_protobuf_wire(data: bytes) -> List[Tuple[int, int, Any]]:
    """低级解析 Protobuf 字节流为 (tag, wire_type, raw_value) 列表"""
    pos = 0
    length = len(data)
    fields = []

    while pos < length:
        tag_wire, pos = decode_varint(data, pos)
        if pos > length:
            break
        tag = tag_wire >> 3
        wire_type = tag_wire & 0x07

        if wire_type == WIRE_VARINT:
            val, pos = decode_varint(data, pos)
            fields.append((tag, wire_type, val))
        elif wire_type == WIRE_LENGTH_DELIMITED:
            str_len, pos = decode_varint(data, pos)
            if pos + str_len > length:
                val = data[pos:]
                pos = length
            else:
                val = data[pos : pos + str_len]
                pos += str_len
            fields.append((tag, wire_type, val))
        elif wire_type == WIRE_64BIT:
            val = data[pos : pos + 8]
            pos += 8
            fields.append((tag, wire_type, val))
        elif wire_type == WIRE_32BIT:
            val = data[pos : pos + 4]
            pos += 4
            fields.append((tag, wire_type, val))
        else:
            break

    return fields


class QQMsgContentParser:
    """QQ NT 40800 消息体解析器"""

    @classmethod
    def parse_msg_blob(cls, blob: Optional[bytes]) -> Dict[str, Any]:
        """解析 40800 BLOB 数据

        返回结构:
        {
            "display_text": "[图片: xxx.jpg] 文本内容",
            "text_only": "文本内容",
            "elements": [
                {"type": "text", "content": "好甜"},
                {"type": "image", "filename": "ADEA.jpg", "summary": "[动画表情]"}
            ],
            "raw_text_length": 2
        }
        """
        if not blob:
            return {
                "display_text": "",
                "text_only": "",
                "elements": [],
                "raw_text_length": 0
            }

        fields = parse_protobuf_wire(blob)
        elements = []

        # 40800 是顶级 repeated MsgContent
        for tag, wire, val in fields:
            if tag == 40800 and wire == WIRE_LENGTH_DELIMITED:
                elem = cls._parse_single_element(val)
                if elem:
                    elements.append(elem)

        # 聚合生成展示文本与纯文本
        display_parts = []
        text_only_parts = []

        for elem in elements:
            etype = elem.get("type")
            if etype == "text":
                c = elem.get("content", "")
                display_parts.append(c)
                text_only_parts.append(c)
            elif etype == "image":
                summary = elem.get("summary")
                fn = elem.get("filename", "")
                if summary:
                    display_parts.append(f"[{summary}]")
                elif fn:
                    display_parts.append(f"[图片: {fn}]")
                else:
                    display_parts.append("[图片]")
            elif etype == "face":
                desc = elem.get("desc", "表情")
                display_parts.append(f"[{desc}]")
            elif etype == "file":
                fn = elem.get("filename", "未知文件")
                display_parts.append(f"[文件: {fn}]")
            elif etype == "reply":
                display_parts.append("[回复]")
            elif etype == "other":
                summary = elem.get("summary")
                if summary:
                    display_parts.append(f"[{summary}]")

        display_text = "".join(display_parts).strip()
        text_only = "".join(text_only_parts).strip()

        return {
            "display_text": display_text,
            "text_only": text_only,
            "elements": elements,
            "raw_text_length": len(text_only)
        }

    @classmethod
    def _parse_single_element(cls, elem_bytes: bytes) -> Optional[Dict[str, Any]]:
        """递归解析单个 MsgContent 元素"""
        sub_fields = parse_protobuf_wire(elem_bytes)
        elem_dict = {}

        for tag, wire, val in sub_fields:
            if tag == 45002 and wire == WIRE_VARINT:
                elem_dict["elem_type_id"] = val
            elif tag == 45101 and wire == WIRE_LENGTH_DELIMITED:
                # 文本
                try:
                    elem_dict["text"] = val.decode("utf-8")
                except Exception:
                    elem_dict["text"] = val.decode("utf-8", errors="replace")
            elif tag == 45402 and wire == WIRE_LENGTH_DELIMITED:
                # 文件名或图片名
                try:
                    elem_dict["filename"] = val.decode("utf-8")
                except Exception:
                    elem_dict["filename"] = ""
            elif tag == 45403 and wire == WIRE_VARINT:
                elem_dict["filesize"] = val
            elif tag == 45815 and wire == WIRE_LENGTH_DELIMITED:
                # 摘要描述
                try:
                    elem_dict["summary"] = val.decode("utf-8")
                except Exception:
                    elem_dict["summary"] = ""
            elif tag == 45302 and wire == WIRE_VARINT:
                elem_dict["face_index"] = val

        type_id = elem_dict.get("elem_type_id", 0)

        if "text" in elem_dict:
            return {"type": "text", "content": elem_dict["text"]}
        elif type_id == 2 or ("filename" in elem_dict and any(elem_dict["filename"].lower().endswith(ext) for ext in [".jpg", ".png", ".gif", ".webp"])):
            return {
                "type": "image",
                "filename": elem_dict.get("filename", ""),
                "summary": elem_dict.get("summary", "")
            }
        elif type_id == 6 or "face_index" in elem_dict:
            idx = elem_dict.get("face_index", 0)
            return {"type": "face", "face_index": idx, "desc": f"表情{idx}"}
        elif type_id == 3 or "filename" in elem_dict:
            return {
                "type": "file",
                "filename": elem_dict.get("filename", ""),
                "filesize": elem_dict.get("filesize", 0)
            }
        elif elem_dict.get("summary"):
            return {"type": "other", "summary": elem_dict["summary"]}

        return None
