# -*- coding: utf-8 -*-
"""微信高保真响应式朋友圈 HTML 页面渲染器

遵循微信原生浅色扁平设计语言 (WeChat Clean Flat)，生成含自适应九宫格、
原图灯箱 (Lightbox) 及可折叠点赞/评论的高保真静态离线网页。
"""

from __future__ import annotations

import html
from pathlib import Path

from ..common.contact_resolver import ContactProfile

# 微信官方默认头像 SVG (离线兜底)
DEFAULT_AVATAR_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<rect width='100' height='100' fill='%23E1E1E1'/>"
    "<circle cx='50' cy='38' r='20' fill='%23BDBDBD'/>"
    "<path d='M20 90 A30 30 0 0 1 80 90 Z' fill='%23BDBDBD'/>"
    "</svg>"
)

CSS_STYLES = """
:root {
    --wx-bg: #EDEDED;
    --wx-card-bg: #FFFFFF;
    --wx-text-main: #191919;
    --wx-text-sub: #7F7F7F;
    --wx-link: #576B95;
    --wx-border: #E5E5E5;
    --wx-comment-bg: #F7F7F7;
    --wx-green: #07C160;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-tap-highlight-color: transparent;
}

body {
    background-color: var(--wx-bg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    color: var(--wx-text-main);
    line-height: 1.5;
    padding-bottom: 60px;
}

.timeline-container {
    max-width: 640px;
    margin: 0 auto;
    background: var(--wx-bg);
    min-height: 100vh;
}

/* 顶部封面与用户信息 */
.header-banner {
    position: relative;
    background: #2E3238;
    height: 260px;
    margin-bottom: 50px;
    overflow: visible;
}

.header-banner .banner-bg {
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0.85;
}

.user-profile-bar {
    position: absolute;
    right: 20px;
    bottom: -32px;
    display: flex;
    align-items: center;
    gap: 14px;
    z-index: 10;
}

.user-profile-bar .user-name {
    color: #FFFFFF;
    font-size: 19px;
    font-weight: 600;
    text-shadow: 0 1px 3px rgba(0,0,0,0.6);
    margin-bottom: 8px;
}

.user-profile-bar .user-avatar {
    width: 72px;
    height: 72px;
    border-radius: 8px;
    border: 2px solid #FFFFFF;
    background: #FFF;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    object-fit: cover;
}

/* 朋友圈流列表 */
.timeline-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.feed-item {
    background: var(--wx-card-bg);
    padding: 18px 16px;
    display: flex;
    gap: 12px;
    position: relative;
}

.feed-avatar {
    flex-shrink: 0;
}

.feed-avatar img {
    width: 44px;
    height: 44px;
    border-radius: 6px;
    object-fit: cover;
    background: #E5E5E5;
}

.feed-content {
    flex: 1;
    min-width: 0;
}

.feed-author {
    color: var(--wx-link);
    font-weight: 600;
    font-size: 15px;
    margin-bottom: 4px;
    cursor: pointer;
}

.feed-text {
    font-size: 15px;
    color: var(--wx-text-main);
    word-break: break-word;
    white-space: pre-wrap;
    margin-bottom: 8px;
    line-height: 1.45;
}

/* 媒体九宫格 */
.media-grid {
    display: grid;
    gap: 6px;
    margin: 8px 0;
    max-width: 420px;
}

.media-grid-1 {
    grid-template-columns: 1fr;
    max-width: 260px;
}

.media-grid-1 img, .media-grid-1 video {
    max-height: 280px;
    border-radius: 4px;
    object-fit: cover;
    width: auto;
    cursor: zoom-in;
}

.media-grid-4 {
    grid-template-columns: repeat(2, 1fr);
    max-width: 260px;
}

.media-grid-9 {
    grid-template-columns: repeat(3, 1fr);
    max-width: 320px;
}

.media-thumb-box {
    aspect-ratio: 1 / 1;
    overflow: hidden;
    border-radius: 4px;
    background: #F0F0F0;
    position: relative;
}

.media-thumb-box img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    cursor: zoom-in;
    transition: transform 0.2s;
}

.media-thumb-box img:hover {
    transform: scale(1.03);
}

.video-player-box {
    position: relative;
    max-width: 360px;
    border-radius: 6px;
    overflow: hidden;
    background: #000;
    margin: 6px 0;
}

.video-player-box video {
    width: 100%;
    display: block;
    max-height: 360px;
}

/* 链接分享卡片 */
.share-card {
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--wx-comment-bg);
    padding: 8px;
    border-radius: 4px;
    margin: 8px 0;
    border: 1px solid var(--wx-border);
}

.share-card-icon {
    width: 40px;
    height: 40px;
    flex-shrink: 0;
    background: #D8D8D8;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
}

.share-card-title {
    font-size: 13px;
    color: var(--wx-text-main);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
}

/* 底部时间与操作 */
.feed-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 10px;
    font-size: 13px;
    color: var(--wx-text-sub);
}

/* 点赞与评论容器 */
.interaction-container {
    background: var(--wx-comment-bg);
    border-radius: 4px;
    margin-top: 8px;
    position: relative;
    font-size: 13.5px;
    border: 1px solid #ECECEC;
}

.interaction-container::before {
    content: "";
    position: absolute;
    top: -6px;
    left: 16px;
    width: 0;
    height: 0;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 6px solid var(--wx-comment-bg);
}

.like-box {
    padding: 6px 10px;
    color: var(--wx-link);
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px;
}

.like-heart {
    color: var(--wx-link);
    margin-right: 4px;
}

.like-user {
    font-weight: 500;
}

.comment-list-box {
    padding: 6px 10px;
    border-top: 1px solid #ECECEC;
}

.interaction-container .like-box:only-child {
    border-bottom: none;
}

.comment-item {
    margin-bottom: 4px;
    line-height: 1.4;
    word-break: break-word;
}

.comment-item:last-child {
    margin-bottom: 0;
}

.comment-author {
    color: var(--wx-link);
    font-weight: 500;
}

.comment-reply {
    color: var(--wx-text-sub);
    margin: 0 3px;
}

/* 原图灯箱 Lightbox */
#lightbox-modal {
    display: none;
    position: fixed;
    z-index: 9999;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(0, 0, 0, 0.9);
    justify-content: center;
    align-items: center;
    cursor: zoom-out;
}

#lightbox-img {
    max-width: 95%;
    max-height: 95%;
    border-radius: 4px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}

.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: var(--wx-text-sub);
    font-size: 15px;
}
"""

LIGHTBOX_JS = """
function openLightbox(src) {
    const modal = document.getElementById('lightbox-modal');
    const img = document.getElementById('lightbox-img');
    img.src = src;
    modal.style.display = 'flex';
}

function closeLightbox() {
    const modal = document.getElementById('lightbox-modal');
    modal.style.display = 'none';
}

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeLightbox();
    }
});
"""


def render_sns_html(
    items: list[dict],
    user_info: dict,
    contact_map: dict[str, ContactProfile],
    avatar_map: dict[str, str],
    out_html: Path,
    url_to_local: dict[str, str] | None = None,
) -> None:
    """渲染朋友圈数据并写入 HTML 离线文件"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    mapping = url_to_local or {}

    feed_html_list = []
    for item in items:
        u_name = item["username"]
        contact = contact_map.get(u_name)
        disp_name = contact.display_name if contact else u_name
        avatar_src = avatar_map.get(u_name) or DEFAULT_AVATAR_SVG

        # 文本
        text_html = ""
        if item["title"]:
            text_html = f"<div class='feed-text'>{html.escape(item['title'])}</div>"

        # 媒体部分 (图片 / 视频)
        media_html = ""
        media_list = item["media_list"]
        if media_list:
            first_m = media_list[0]
            if first_m["type"] == 6:
                # 视频
                v_url = first_m["url"]
                local_v = mapping.get(v_url, v_url)
                t_url = first_m["thumb"]
                local_t = mapping.get(t_url, t_url)
                poster_attr = f" poster='{html.escape(local_t)}'" if local_t else ""

                media_html = f"""
                <div class="video-player-box">
                    <video controls playsinline preload="metadata"{poster_attr}>
                        <source src="{html.escape(local_v)}" type="video/mp4">
                        您的浏览器不支持 MP4 视频播放。
                    </video>
                </div>
                """
            else:
                # 图片九宫格
                count = len(media_list)
                if count == 1:
                    grid_class = "media-grid-1"
                elif count in (2, 4):
                    grid_class = "media-grid-4"
                else:
                    grid_class = "media-grid-9"

                items_markup = []
                for m in media_list:
                    raw_src = m["thumb"] if m["thumb"] else m["url"]
                    local_thumb = mapping.get(raw_src, raw_src)
                    full_src = m["url"] if m["url"] else m["thumb"]
                    local_full = mapping.get(full_src, full_src) or local_thumb

                    if not local_thumb:
                        continue

                    if count == 1:
                        items_markup.append(
                            f"<img src='{html.escape(local_thumb)}' alt='图片' onclick=\"openLightbox('{html.escape(local_full)}')\" loading='lazy'>"
                        )
                    else:
                        items_markup.append(
                            f"<div class='media-thumb-box'><img src='{html.escape(local_thumb)}' alt='图片' onclick=\"openLightbox('{html.escape(local_full)}')\" loading='lazy'></div>"
                        )

                if items_markup:
                    media_html = f"<div class='media-grid {grid_class}'>{''.join(items_markup)}</div>"

        # 分享卡片
        card_html = ""
        if item["content_style"] != 1 and not media_list and item["desc"]:
            card_html = f"""
            <div class="share-card">
                <div class="share-card-icon">🔗</div>
                <div class="share-card-title">{html.escape(item['desc'])}</div>
            </div>
            """

        # 点赞与评论容器
        interaction_html = ""
        has_likes = bool(item["like_list"])
        has_comments = bool(item["comment_list"])

        if has_likes or has_comments:
            like_markup = ""
            if has_likes:
                names = []
                for lk in item["like_list"]:
                    u_k = lk["username"]
                    p = contact_map.get(u_k)
                    d = p.display_name if p else (lk["nickname"] or u_k)
                    names.append(f"<span class='like-user'>{html.escape(d)}</span>")
                like_markup = f"""
                <div class="like-box">
                    <span class="like-heart">❤️</span>
                    {', '.join(names)}
                </div>
                """

            comment_markup = ""
            if has_comments:
                c_rows = []
                for cm in item["comment_list"]:
                    u_c = cm["username"]
                    p_c = contact_map.get(u_c)
                    d_c = p_c.display_name if p_c else (cm["nickname"] or u_c)

                    reply_part = ""
                    if cm["reply_username"] or cm["reply_nickname"]:
                        u_r = cm["reply_username"]
                        p_r = contact_map.get(u_r)
                        d_r = p_r.display_name if p_r else (cm["reply_nickname"] or u_r)
                        reply_part = f"<span class='comment-reply'>回复</span><span class='comment-author'>{html.escape(d_r)}</span>"

                    c_rows.append(
                        f"<div class='comment-item'>"
                        f"<span class='comment-author'>{html.escape(d_c)}</span>{reply_part}："
                        f"<span>{html.escape(cm['content'])}</span>"
                        f"</div>"
                    )
                comment_markup = f"""
                <div class="comment-list-box">
                    {''.join(c_rows)}
                </div>
                """

            interaction_html = f"""
            <div class="interaction-container">
                {like_markup}
                {comment_markup}
            </div>
            """

        feed_card = f"""
        <div class="feed-item">
            <div class="feed-avatar">
                <img src="{avatar_src}" alt="{html.escape(disp_name)}" loading="lazy">
            </div>
            <div class="feed-content">
                <div class="feed-author">{html.escape(disp_name)}</div>
                {text_html}
                {media_html}
                {card_html}
                <div class="feed-footer">
                    <span>{item['date_str']} {item['time_str']} ({item['weekday_str']})</span>
                </div>
                {interaction_html}
            </div>
        </div>
        """
        feed_html_list.append(feed_card)

    if not feed_html_list:
        feed_content_html = "<div class='empty-state'>暂未发现符合条件的朋友圈动态</div>"
    else:
        feed_content_html = "\n".join(feed_html_list)

    # 顶栏用户信息
    header_user_name = user_info.get("display") or user_info.get("username") or "微信朋友圈"
    header_avatar = avatar_map.get(user_info.get("username", "")) or DEFAULT_AVATAR_SVG

    full_page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>{html.escape(header_user_name)} - 微信朋友圈记录</title>
    <style>
{CSS_STYLES}
    </style>
</head>
<body>
    <div class="timeline-container">
        <div class="header-banner">
            <div class="user-profile-bar">
                <div class="user-name">{html.escape(header_user_name)}</div>
                <img class="user-avatar" src="{header_avatar}" alt="头像">
            </div>
        </div>

        <div class="timeline-list">
{feed_content_html}
        </div>
    </div>

    <!-- 原图查看灯箱模态框 -->
    <div id="lightbox-modal" onclick="closeLightbox()">
        <img id="lightbox-img" src="" alt="原图预览">
    </div>

    <script>
{LIGHTBOX_JS}
    </script>
</body>
</html>
"""

    with open(out_html, "w", encoding="utf-8") as f:
        f.write(full_page)
