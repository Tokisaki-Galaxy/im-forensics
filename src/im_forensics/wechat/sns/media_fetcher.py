# -*- coding: utf-8 -*-
"""朋友圈媒体下载与自动 ISAAC-64 解密服务

使用线程池并发从微信 CDN 下载加密资源，自动根据媒体类型与 key 调用 ISAAC-64 解密落盘。
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..crypto.media_decrypt import decrypt_wechat_media

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781"
    ),
    "Accept": "*/*",
}


def _download_and_decrypt_one(item: dict, media_dir: Path) -> tuple[str, str | None]:
    """下载并解密单个文件"""
    url = item["url"]
    key = item["key"]
    is_video = item["is_video"]
    prefix = item.get("prefix", "media")

    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
    ext = ".mp4" if is_video else ".jpg"
    filename = f"{prefix}_{url_hash}{ext}"
    local_path = media_dir / filename

    if local_path.exists() and local_path.stat().st_size > 0:
        return url, f"sns_media/{filename}"

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw_data = resp.read()

        decrypted = decrypt_wechat_media(raw_data, key=key, is_video=is_video)
        with open(local_path, "wb") as f:
            f.write(decrypted)

        return url, f"sns_media/{filename}"
    except Exception as e:
        print(f"[下载失败] {url[:60]}...: {e}")
        return url, None


def download_and_decrypt_sns_media(
    items: list[dict],
    media_dir: Path,
    max_workers: int = 8,
) -> dict[str, str]:
    """批量并发下载朋友圈中的图片/视频并自动完成 ISAAC-64 解密。

    返回:
        映射字典 { cdn_url: local_relative_path }
    """
    media_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    for item in items:
        for m in item["media_list"]:
            m_type = m["type"]
            # 图片
            if m_type == 2:
                if m["url"]:
                    tasks.append({
                        "url": m["url"],
                        "key": m["url_key"],
                        "is_video": False,
                        "prefix": "img",
                    })
                elif m["thumb"]:
                    tasks.append({
                        "url": m["thumb"],
                        "key": m["thumb_key"],
                        "is_video": False,
                        "prefix": "thumb",
                    })
            # 视频
            elif m_type == 6:
                if m["url"]:
                    v_key = m["enc_key"] if m["enc_key"] else m["url_key"]
                    tasks.append({
                        "url": m["url"],
                        "key": v_key,
                        "is_video": True,
                        "prefix": "video",
                    })
                if m["thumb"]:
                    t_key = m["thumb_key"] if m["thumb_key"] else m["url_key"]
                    tasks.append({
                        "url": m["thumb"],
                        "key": t_key,
                        "is_video": False,
                        "prefix": "vthumb",
                    })

    # 去重
    unique_tasks = {}
    for t in tasks:
        if t["url"] and t["url"] not in unique_tasks:
            unique_tasks[t["url"]] = t

    print(f"待处理朋友圈媒体资源: {len(unique_tasks)} 个 (图片/视频/封面)")
    url_to_local: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(_download_and_decrypt_one, task, media_dir): task["url"]
            for task in unique_tasks.values()
        }
        for future in as_completed(future_map):
            raw_url, rel_path = future.result()
            if rel_path:
                url_to_local[raw_url] = rel_path

    print(f"媒体解密下载完成: 成功 {len(url_to_local)}/{len(unique_tasks)} 个")
    return url_to_local
