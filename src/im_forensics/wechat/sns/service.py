# -*- coding: utf-8 -*-
"""微信朋友圈导出流水线服务 (Sns Export Pipeline)

负责查询 SnsTimeLine 数据库、XML 结构化解析、时间边界过滤、媒体下载/解密以及 HTML 静态页面渲染。
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from ..common.contact_resolver import ContactProfile, ContactResolver
from ..common.db_locator import locate_wechat_db_dir
from ..common.time_utils import DEFAULT_TZ, parse_date_boundary
from .html_renderer import render_sns_html
from .media_fetcher import download_and_decrypt_sns_media
from .parser import parse_sns_item


@dataclass
class SnsExportResult:
    """朋友圈导出结果"""
    total_count: int
    html_path: Path
    media_count: int
    target_profile: ContactProfile | None


class SnsExportService:
    """微信朋友圈数据提取与离线网页渲染流水线"""

    def __init__(self, db_dir: Path | str | None = None, tz: ZoneInfo = DEFAULT_TZ):
        self.db_dir = locate_wechat_db_dir(db_dir)
        self.tz = tz
        self.contact_resolver = ContactResolver(self.db_dir)
        self.sns_db_path = self.db_dir / "sns" / "sns.db"

    def export(
        self,
        target: str | None = None,
        export_all: bool = False,
        start_date: str | None = None,
        end_date: str | None = None,
        output_dir: Path | str | None = None,
        output_name: str | None = None,
        target_name_override: str | None = None,
        download_media: bool = False,
    ) -> SnsExportResult:
        """运行完整的朋友圈提取流水线:
        1. 验证 sns.db 数据库存在
        2. 定位联系人 (或指定全量朋友圈)
        3. 解析时间边界并在 SnsTimeLine 检索
        4. 解析 XML 内容与九宫格
        5. 可选: 并发下载并解密 ISAAC-64 图片与视频
        6. 渲染高保真响应式离线 HTML 网页
        """
        if not self.sns_db_path.exists():
            raise FileNotFoundError(f"未找到朋友圈数据库: {self.sns_db_path}")

        # 1. 查找目标联系人
        target_info = None
        if not export_all:
            if not target:
                raise ValueError("请指定联系人 target 或设置 export_all=True 导出全量朋友圈")
            target_info = self.contact_resolver.find_contact(target)
            disp_override = (target_name_override or "").strip()
            if disp_override:
                target_info.display_name = disp_override

            print("=" * 50)
            print(f"定位到朋友圈联系人: {target_info.display_name}")
            print(f"  微信ID: {target_info.username}")
            print(f"  备注名: {target_info.remark or '(无)'}")
            print(f"  昵称:   {target_info.nick_name or '(无)'}")
            print("=" * 50)
        else:
            print("模式: 导出全量好友朋友圈动态")

        # 2. 日期边界解析
        now = datetime.datetime.now(tz=self.tz)
        start_ts = 0
        end_ts = 9999999999
        if start_date:
            start_dt = parse_date_boundary(start_date, is_end=False, default_year=now.year, tz=self.tz)
            start_ts = int(start_dt.timestamp())
        if end_date:
            end_dt = parse_date_boundary(end_date, is_end=True, default_year=now.year, tz=self.tz)
            end_ts = int(end_dt.timestamp())

        # 3. 读取 SnsTimeLine 数据库
        conn = sqlite3.connect(f"file:{self.sns_db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        try:
            if target_info:
                cur.execute(
                    "SELECT tid, content FROM SnsTimeLine WHERE user_name = ? ORDER BY tid DESC",
                    (target_info.username,),
                )
            else:
                cur.execute("SELECT tid, content FROM SnsTimeLine ORDER BY tid DESC")

            rows = cur.fetchall()
        finally:
            conn.close()

        items = []
        for tid, content in rows:
            parsed = parse_sns_item(tid, content, tz=self.tz)
            if parsed and start_ts <= parsed["timestamp"] <= end_ts:
                items.append(parsed)

        # 倒序排列 (最新在前)
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        print(f"提取到符合条件的朋友圈动态: {len(items)} 条")

        # 4. 确定输出路径
        out_path = Path(output_dir).resolve() if output_dir else self.db_dir.parent
        out_path.mkdir(parents=True, exist_ok=True)

        if output_name:
            filename = output_name if output_name.endswith(".html") else f"{output_name}.html"
        else:
            filename = f"sns_{target_info.display_name}.html" if target_info else "sns_timeline.html"

        out_html = out_path / filename

        # 5. 下载与解密媒体
        url_to_local = None
        media_count = 0
        if download_media and items:
            media_dir = out_path / "sns_media"
            url_to_local = download_and_decrypt_sns_media(items, media_dir)
            media_count = len(url_to_local)

        # 6. 生成 HTML
        user_header_info = {
            "display": target_info.display_name if target_info else "微信朋友圈",
            "username": target_info.username if target_info else "",
        }
        contact_map = self.contact_resolver.get_contact_map()
        avatar_map = {
            k: v.avatar_base64
            for k, v in contact_map.items()
            if v.avatar_base64
        }

        render_sns_html(
            items=items,
            user_info=user_header_info,
            contact_map=contact_map,
            avatar_map=avatar_map,
            out_html=out_html,
            url_to_local=url_to_local,
        )

        print(f"[导出成功] HTML 网页已保存至: {out_html}")
        return SnsExportResult(
            total_count=len(items),
            html_path=out_html,
            media_count=media_count,
            target_profile=target_info,
        )
