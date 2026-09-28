# -*- coding: utf-8 -*-
"""微信数据提取统一命令行工具 (Unified WeChat CLI)

支持规范化子命令:
    export  : 导出聊天记录到本地文件 (支持 XLSX 或 LLM 紧凑 CSV)
    recent  : 快速查看与指定联系人的最近 N 条对话
    search  : 在聊天记录中检索关键词 (支持正则与上下文窗口)
    sns     : 导出微信朋友圈为高保真离线 HTML 网页 (支持媒体解密)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 保证从任意工作区路径调用时均能正确导入
PKG_ROOT = Path(__file__).resolve().parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

try:
    from im_forensics.wechat.chat.service import ChatExportService
    from im_forensics.wechat.sns.service import SnsExportService
except ImportError:
    from chat.service import ChatExportService
    from sns.service import SnsExportService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wechat_tools",
        description="微信数据库分析与导出工具集 (WeChat Toolkit)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="可用操作模块")

    # 1. 聊天记录导出子命令 (export)
    export_p = subparsers.add_parser("export", help="导出聊天记录到本地文件 (支持 xlsx 或 LLM 紧凑 CSV)")
    export_p.add_argument("-c", "--contact", default=None, help="目标联系人 (微信ID/备注名/昵称/拼音)")
    export_p.add_argument("-s", "--since", default=None, help="起始时间 (例如 2026-08-01, 0801)")
    export_p.add_argument("-u", "--until", default=None, help="截止时间 (例如 2026-09-10, 0910)")
    export_p.add_argument("--format", choices=["xlsx", "compact", "both"], default="xlsx", help="导出格式: xlsx(表格), compact(LLM紧凑CSV), both(两者兼备)")
    export_p.add_argument("--session-gap", type=int, default=30, help="会话切分间隔分钟数 (默认 30 分钟)")
    export_p.add_argument("-d", "--db-dir", default=None, help="微信数据库目录 (默认自动探测)")
    export_p.add_argument("-o", "--output-dir", default=None, help="导出文件存放目录 (默认数据库父目录)")
    export_p.add_argument("--name", default=None, help="强制覆盖目标联系人在报表中的展示名")
    export_p.add_argument("--from-file", default=None, help="直接从已有 chat.xlsx 文件执行紧凑化转换")

    # 兼容别名 chat (保持向前兼容)
    chat_p = subparsers.add_parser("chat", help="[别名] 等同于 export 命令")
    chat_p.add_argument("-c", "-t", "--contact", "--target", dest="contact", required=True, help="目标联系人")
    chat_p.add_argument("-s", "--since", "--start", dest="since", default=None, help="起始时间")
    chat_p.add_argument("-u", "-e", "--until", "--end", dest="until", default=None, help="截止时间")
    chat_p.add_argument("--format", choices=["xlsx", "compact", "both"], default="xlsx", help="导出格式")
    chat_p.add_argument("--session-gap", type=int, default=30, help="会话切分间隔分钟数")
    chat_p.add_argument("-d", "--db-dir", default=None, help="微信数据库目录")
    chat_p.add_argument("-o", "--output-dir", default=None, help="导出文件存放目录")
    chat_p.add_argument("--name", default=None, help="强制覆盖目标联系人的展示名")

    # 2. 快速查看最近消息 (recent)
    recent_p = subparsers.add_parser("recent", help="快速查看与指定联系人的最近 N 条对话")
    recent_p.add_argument("-c", "--contact", required=True, help="目标联系人 (微信ID/备注名/昵称/拼音)")
    recent_p.add_argument("-n", "--limit", type=int, default=20, help="显示消息条数 (默认 20)")
    recent_p.add_argument("--json", action="store_true", help="以结构化 JSON 格式输出 (适合 Agent 解析)")
    recent_p.add_argument("-d", "--db-dir", default=None, help="微信数据库目录")

    # 3. 关键词检索与上下文还原 (search)
    search_p = subparsers.add_parser("search", help="在聊天记录中检索关键词 (支持正则与上下文窗口)")
    search_p.add_argument("-q", "--query", required=True, help="检索关键词或正则表达式")
    search_p.add_argument("-c", "--contact", default=None, help="限定联系人 (默认搜索全库私聊)")
    search_p.add_argument("-C", "--context", type=int, default=0, help="匹配项前后上下文条数 (类似 grep -C)")
    search_p.add_argument("-n", "--limit", type=int, default=50, help="最大返回匹配数 (默认 50)")
    search_p.add_argument("--regex", action="store_true", help="将 query 视为正则表达式")
    search_p.add_argument("--json", action="store_true", help="以结构化 JSON 格式输出")
    search_p.add_argument("-d", "--db-dir", default=None, help="微信数据库目录")

    # 4. 关系动力学量化分析子命令 (analyze)
    analyze_p = subparsers.add_parser("analyze", help="量化分析与联系人的沟通动力学 (字数比/响应延迟/追发频次/相变拐点)")
    analyze_p.add_argument("-c", "-t", "--contact", "--target", dest="contact", required=True, help="目标联系人 (微信ID/备注名/昵称)")
    analyze_p.add_argument("-s", "--since", "--start", dest="since", default=None, help="起始时间 (例如 2026-08-01, 0801)")
    analyze_p.add_argument("-u", "-e", "--until", "--end", dest="until", default=None, help="截止时间 (例如 2026-09-10, 0910)")
    analyze_p.add_argument("--json", action="store_true", help="以结构化 JSON 格式输出指标报表")
    analyze_p.add_argument("-d", "--db-dir", default=None, help="微信数据库目录")

    # 5. 联系人消息总数排行榜子命令 (rank)
    rank_p = subparsers.add_parser("rank", help="全局统计所有私聊联系人的消息总数排行榜 (自动过滤群聊与服务号)")
    rank_p.add_argument("-n", "--top", "--limit", dest="limit", type=int, default=15, help="榜单展示条数 (默认 15)")
    rank_p.add_argument("--json", action="store_true", help="以结构化 JSON 格式输出榜单数组")
    rank_p.add_argument("-d", "--db-dir", default=None, help="微信数据库目录")

    # 6. 朋友圈导出子命令 (sns)
    sns_p = subparsers.add_parser("sns", help="导出微信朋友圈为高保真离线 HTML 网页 (支持 ISAAC-64 媒体解密)")
    sns_p.add_argument("-c", "-t", "--contact", "--target", dest="contact", default=None, help="目标联系人 (微信ID/备注名/昵称)")
    sns_p.add_argument("--all", action="store_true", help="导出全量好友朋友圈动态")
    sns_p.add_argument("-s", "--since", "--start", dest="since", default=None, help="起始时间 (例如 2026-08-01, 0801)")
    sns_p.add_argument("-u", "-e", "--until", "--end", dest="until", default=None, help="截止时间 (例如 2026-09-10, 0910)")
    sns_p.add_argument("-d", "--db-dir", default=None, help="微信数据库目录")
    sns_p.add_argument("-o", "--output-dir", "--out-dir", dest="output_dir", default=None, help="导出目录")
    sns_p.add_argument("--out-name", default=None, help="指定生成的 HTML 文件名")
    sns_p.add_argument("--target-name", default=None, help="强制覆盖目标联系人的展示名")
    sns_p.add_argument("--download-media", action="store_true", help="并发下载图片/视频并自动解密")

    return parser


def handle_export(args: argparse.Namespace) -> None:
    if args.from_file:
        try:
            from im_forensics.wechat.chat.preprocessor import process_xlsx_to_compact_csv
        except ImportError:
            from chat.preprocessor import process_xlsx_to_compact_csv
        xlsx_p = Path(args.from_file)
        if not xlsx_p.exists():
            print(f"[错误] 文件不存在: {xlsx_p}", file=sys.stderr)
            sys.exit(1)
        out_csv = xlsx_p.with_name(xlsx_p.stem + "_preprocessed.csv")
        out_csv, summary_p, _ = process_xlsx_to_compact_csv(xlsx_p, out_csv, session_minutes=args.session_gap)
        print(f"[预处理完成] 紧凑 CSV 已生成: {out_csv}")
        print(f"[预处理完成] 会话摘要已生成: {summary_p}")
        return

    if not args.contact:
        print("[错误] 请通过 -c / --contact 参数指定目标联系人，或通过 --from-file 指定已有 xlsx 文件", file=sys.stderr)
        sys.exit(1)

    service = ChatExportService(db_dir=args.db_dir)
    service.export(
        contact=args.contact,
        since=args.since,
        until=args.until,
        output_dir=args.output_dir,
        contact_name_override=args.name,
        export_format=args.format,
        session_minutes=args.session_gap,
    )


def handle_recent(args: argparse.Namespace) -> None:
    service = ChatExportService(db_dir=args.db_dir)
    profile, messages = service.fetch_messages(
        contact=args.contact,
        limit=args.limit,
        reverse=True,
    )
    # 按时间正序排列以便阅读
    messages.reverse()

    if args.json:
        output_data = {
            "contact": {
                "username": profile.username,
                "remark": profile.remark,
                "nick_name": profile.nick_name,
                "display_name": profile.display_name,
            },
            "count": len(messages),
            "messages": [
                {
                    "time": m["time_str"],
                    "sender": m["sender_name"],
                    "sender_wxid": m["sender_wxid"],
                    "type": m["type_label"],
                    "content": m["content"],
                }
                for m in messages
            ],
        }
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print(f"最近消息: {profile.display_name} (共展示 {len(messages)} 条)")
    print("=" * 60)
    for m in messages:
        t = m["time_str"]
        s = m["sender_name"]
        c = m["content"]
        if len(c) > 120:
            c = c[:115] + "..."
        print(f"[{t}] {s}: {c}")
    print("=" * 60)


def handle_search(args: argparse.Namespace) -> None:
    service = ChatExportService(db_dir=args.db_dir)
    results = service.search_messages(
        query=args.query,
        contact=args.contact,
        context=args.context,
        limit=args.limit,
        regex=args.regex,
    )

    if args.json:
        serializable = []
        for r in results:
            serializable.append({
                "contact_display_name": r["contact_display_name"],
                "contact_username": r["contact_username"],
                "match_time": r["match_message"]["time_str"],
                "match_sender": r["match_message"]["sender_name"],
                "match_content": r["match_message"]["content"],
                "context": [
                    {
                        "time": m["time_str"],
                        "sender": m["sender_name"],
                        "content": m["content"],
                    }
                    for m in r["context_messages"]
                ],
            })
        print(json.dumps(serializable, ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print(f"检索关键词: '{args.query}' (找到 {len(results)} 条命中)")
    print("=" * 60)
    for idx, r in enumerate(results, 1):
        c_name = r["contact_display_name"]
        print(f"--- [命中 #{idx}] 联系人: {c_name} ---")
        for m in r["context_messages"]:
            t = m["time_str"]
            s = m["sender_name"]
            c = m["content"]
            is_match = (m["local_id"] == r["match_message"]["local_id"])
            prefix = ">> " if is_match else "   "
            if len(c) > 120 and not is_match:
                c = c[:115] + "..."
            print(f"{prefix}[{t}] {s}: {c}")
    print("=" * 60)


def handle_analyze(args: argparse.Namespace) -> None:
    service = ChatExportService(db_dir=args.db_dir)
    res = service.analyze_relationship(
        contact=args.contact,
        since=args.since,
        until=args.until,
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    summary = res["summary"]
    balance = res["balance"]
    rhythm = res["response_rhythm"]
    inflections = res["inflection_points"]

    lat_all = rhythm["latency_median_all_seconds"]
    lat_day = rhythm["latency_median_daytime_seconds"]
    lat_night = rhythm["latency_median_night_seconds"]
    bursts = rhythm["chasing_bursts_over_30min"]
    streaks = rhythm["max_consecutive_messages"]

    print("=" * 66)
    print(f"关系动力学体检看板: {summary['contact_name']} (活跃 {summary['active_days']}/{summary['total_calendar_days']} 天, 消息 {summary['total_messages']:,} 条)")
    print("=" * 66)
    print("【容量与平衡 (Volume & Asymmetry)】")
    print(f"  • 消息总数比 (我 : 对方): {balance['user_messages']:,} : {balance['target_messages']:,} ({balance['user_msg_percent']} : {balance['target_msg_percent']})")
    print(f"  • 字符总量比 (我 : 对方): {balance['user_total_chars']:,} : {balance['target_total_chars']:,} ({balance['char_ratio_user_to_target']:.2f} : 1)")
    print(f"  • 单条平均字符: 我 {balance['user_avg_chars_per_msg']:.1f} 字 vs 对方 {balance['target_avg_chars_per_msg']:.1f} 字")
    print()
    print("【节奏与响应延迟 (Latency & Rhythm)】")
    print(f"  • 全天响应延迟中位数: 我 {lat_all['user']}s vs 对方 {lat_all['target']}s")
    print(f"  • 日间工作时段 (09-18h): 我 {lat_day['user']}s vs 对方 {lat_day['target']}s")
    print(f"  • 夜间空闲时段 (18-24h): 我 {lat_night['user']}s vs 对方 {lat_night['target']}s")
    print(f"  • >30min 静默后追发次数: 我 {bursts['user']} 次 vs 对方 {bursts['target']} 次 (追发比 {bursts['ratio_user_to_target']:.1f} : 1)")
    print(f"  • 单次最大连续追发: 我 {streaks['user']} 条 vs 对方 {streaks['target']} 条")
    print()
    print("【相变与拐点探测 (Phase Transitions)】")
    if not inflections:
        print("  • 未探测到显著相变拐点 (关系平稳)")
    else:
        for inf in inflections:
            print(f"  • {inf['week']} [{inf['type']}]: 周消息量从 {inf['prev_week_msgs']} 跌至 {inf['curr_week_msgs']} ({inf['drop_percentage']})")
    print("=" * 66)


def handle_rank(args: argparse.Namespace) -> None:
    service = ChatExportService(db_dir=args.db_dir)
    rankings = service.rank_top_contacts(limit=args.limit)

    if args.json:
        print(json.dumps(rankings, ensure_ascii=False, indent=2))
        return

    print("=" * 66)
    print(f"微信私聊联系人消息总数排行榜 Top {len(rankings)} (已过滤群聊与公众号)")
    print("=" * 66)
    print(f"{'排名':<4} {'联系人':<18} {'微信 ID':<26} {'总消息数':>10}")
    print("-" * 66)
    for idx, r in enumerate(rankings, 1):
        name = r["display_name"]
        if len(name) > 16:
            name = name[:15] + "…"
        print(f"#{idx:<3} {name:<18} {r['username']:<26} {r['total_messages']:>10,}")
    print("=" * 66)


def handle_sns(args: argparse.Namespace) -> None:
    service = SnsExportService(db_dir=args.db_dir)
    service.export(
        target=args.contact,
        export_all=args.all,
        start_date=args.since,
        end_date=args.until,
        output_dir=args.output_dir,
        output_name=args.out_name,
        target_name_override=args.target_name,
        download_media=args.download_media,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.subcommand in ("export", "chat"):
        handle_export(args)
    elif args.subcommand == "recent":
        handle_recent(args)
    elif args.subcommand == "search":
        handle_search(args)
    elif args.subcommand == "analyze":
        handle_analyze(args)
    elif args.subcommand == "rank":
        handle_rank(args)
    elif args.subcommand == "sns":
        handle_sns(args)


if __name__ == "__main__":
    main()
