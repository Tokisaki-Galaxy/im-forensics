# -*- coding: utf-8 -*-
"""微信朋友圈 SnsTimeLine XML 结构化解析器

负责将 SnsTimeLine 表的 content 字段 XML 解析为结构化字典，提取文案、九宫格媒体、
分享卡片、点赞与评论列表。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from ..common.time_utils import DEFAULT_TZ, format_timestamp


def parse_sns_item(tid: int | str, xml_content: str, tz: ZoneInfo = DEFAULT_TZ) -> dict | None:
    """解析单个 SnsTimeLine 记录 XML"""
    if not xml_content or not xml_content.strip():
        return None

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return None

    # 1. 基础元数据
    user_name = root.findtext("username") or ""
    create_time_str = root.findtext("createTime") or "0"
    try:
        timestamp = int(create_time_str)
    except ValueError:
        timestamp = 0

    dt, full_time, date_str, time_str, weekday_str = format_timestamp(timestamp, tz=tz)

    content_obj = root.find("contentObject")
    title = (content_obj.findtext("title") if content_obj is not None else "") or ""
    desc = (content_obj.findtext("description") if content_obj is not None else "") or ""
    content_style_str = content_obj.findtext("contentStyle") if content_obj is not None else "1"
    try:
        content_style = int(content_style_str)
    except ValueError:
        content_style = 1

    # 2. 媒体列表解析 (图片 / 视频)
    media_list = []
    if content_obj is not None:
        media_container = content_obj.find("mediaList")
        if media_container is not None:
            for m in media_container.findall("media"):
                m_id = m.findtext("id") or ""
                m_type = m.findtext("type") or "2"  # 2: 图片, 6: 视频
                title_m = m.findtext("title") or ""
                desc_m = m.findtext("description") or ""

                # url 节点与 key 属性
                url_elem = m.find("url")
                raw_url = (url_elem.text or "").strip() if url_elem is not None else ""
                url_key = url_elem.get("key") or "" if url_elem is not None else ""

                # thumb 节点与 key 属性
                thumb_elem = m.find("thumb")
                raw_thumb = (thumb_elem.text or "").strip() if thumb_elem is not None else ""
                thumb_key = thumb_elem.get("key") or "" if thumb_elem is not None else ""

                # 视频专用 enc 节点
                enc_elem = m.find("enc")
                enc_key = enc_elem.get("key") or "" if enc_elem is not None else ""

                # 尺寸大小
                size_elem = m.find("size")
                width = 0
                height = 0
                total_size = 0
                if size_elem is not None:
                    try:
                        width = float(size_elem.get("width", 0))
                        height = float(size_elem.get("height", 0))
                        total_size = int(float(size_elem.get("totalSize", 0)))
                    except (ValueError, TypeError):
                        pass

                media_list.append({
                    "id": m_id,
                    "type": int(m_type) if m_type.isdigit() else 2,
                    "title": title_m,
                    "desc": desc_m,
                    "url": raw_url,
                    "url_key": url_key,
                    "thumb": raw_thumb,
                    "thumb_key": thumb_key,
                    "enc_key": enc_key,
                    "width": width,
                    "height": height,
                    "total_size": total_size,
                })

    # 3. 点赞列表
    like_list = []
    action_group = root.find("actionGroup")
    if action_group is not None:
        for like in action_group.findall("like"):
            l_user = like.findtext("username") or ""
            l_nick = like.findtext("nickname") or ""
            if l_user or l_nick:
                like_list.append({"username": l_user, "nickname": l_nick})

    # 4. 评论列表
    comment_list = []
    if action_group is not None:
        for comment in action_group.findall("comment"):
            c_user = comment.findtext("username") or ""
            c_nick = comment.findtext("nickname") or ""
            c_content = comment.findtext("content") or ""
            c_reply_user = comment.findtext("replyUsername") or ""
            c_reply_nick = comment.findtext("replyNickname") or ""
            c_time = comment.findtext("createTime") or "0"

            if c_content:
                comment_list.append({
                    "username": c_user,
                    "nickname": c_nick,
                    "content": c_content,
                    "reply_username": c_reply_user,
                    "reply_nickname": c_reply_nick,
                    "create_time": int(c_time) if c_time.isdigit() else 0,
                })

    return {
        "tid": tid,
        "username": user_name,
        "timestamp": timestamp,
        "datetime": dt,
        "full_time": full_time,
        "date_str": date_str,
        "time_str": time_str,
        "weekday_str": weekday_str,
        "title": title,
        "desc": desc,
        "content_style": content_style,
        "media_list": media_list,
        "like_list": like_list,
        "comment_list": comment_list,
    }
