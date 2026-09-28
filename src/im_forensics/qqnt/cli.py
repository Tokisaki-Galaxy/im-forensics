# -*- coding: utf-8 -*-
"""QQ NT 数据提取与关系分析统一命令行工具 (Unified QQ NT CLI)

子命令:
    init    : 初始化配置，提取/复用密钥，流式解密数据库至本地缓存
    contacts: 查看所有存在私聊记录的联系人概览
    recent  : 快速查看与指定联系人的最近 N 条私聊
    search  : 在聊天记录中检索关键词 (支持上下文窗口)
    rank    : 全局统计所有私聊联系人的消息总数排行榜
    analyze : 量化分析与联系人的沟通动力学 (字数比/响应延迟/追发频次/时空分布)
    export  : 导出聊天记录到本地文件 (支持 compact 紧凑文本、CSV、JSONL)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 保证从任意工作区路径调用时均能正确导入
PKG_ROOT = Path(__file__).resolve().parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

try:
    from im_forensics.qqnt.chat.excel_writer import QQChatExporter
    from im_forensics.qqnt.chat.service import QQChatService
    from im_forensics.qqnt.common.config import QQConfigManager
    from im_forensics.qqnt.common.contact_resolver import QQContactResolver
    from im_forensics.qqnt.common.db_locator import QQNTLocator
    from im_forensics.qqnt.common.time_utils import format_duration
    from im_forensics.qqnt.crypto.key_extractor import QQKeyExtractor
    from im_forensics.qqnt.crypto.page_decryptor import QQPageDecryptor
except ImportError:
    from chat.excel_writer import QQChatExporter
    from chat.service import QQChatService
    from common.config import QQConfigManager
    from common.contact_resolver import QQContactResolver
    from common.db_locator import QQNTLocator
    from common.time_utils import format_duration
    from crypto.key_extractor import QQKeyExtractor
    from crypto.page_decryptor import QQPageDecryptor


def ensure_ready(sync: bool = False, force_decrypt: bool = False, verbose: bool = True) -> tuple[QQChatService, QQContactResolver]:
    """确保密钥已加载且数据库已解密，返回服务实例"""
    config_mgr = QQConfigManager()
    locator = QQNTLocator(config_mgr)
    uin, db_dir, raw_msg_db, raw_profile_db = locator.get_default_account()

    cache_dir = Path(config_mgr.get_cache_dir())
    cache_dir.mkdir(parents=True, exist_ok=True)

    plain_msg_db = cache_dir / "nt_msg_plain.db"
    plain_profile_db = cache_dir / "profile_info_plain.db"

    extractor = QQKeyExtractor(config_mgr)

    # 1. 解密 profile_info.db
    need_profile = force_decrypt or not plain_profile_db.exists() or (sync and raw_profile_db.stat().st_mtime > plain_profile_db.stat().st_mtime)
    if need_profile:
        if verbose:
            print("[1/2] 正在解密 profile_info.db ...", flush=True)
        p_key = extractor.get_or_extract_key(raw_profile_db)
        p_decryptor = QQPageDecryptor(p_key)
        p_decryptor.decrypt_database(raw_profile_db, plain_profile_db, force=True)
        if verbose:
            print("[1/2] profile_info.db 解密完成", flush=True)

    resolver = QQContactResolver(plain_profile_db)
    resolver.load()

    # 2. 解密 nt_msg.db
    need_msg = force_decrypt or not plain_msg_db.exists() or (sync and raw_msg_db.stat().st_mtime > plain_msg_db.stat().st_mtime)
    if need_msg:
        if verbose:
            print("[2/2] 正在解密 nt_msg.db (1.7GB 流式分页解密) ...", flush=True)
        m_key = extractor.get_or_extract_key(raw_msg_db)
        m_decryptor = QQPageDecryptor(m_key)

        def on_progress(cur, total, speed, eta):
            pct = (cur / total) * 100
            print(f"\r      进度: [{cur}/{total} 页] {pct:.1f}% | 速度: {speed:.1f} MB/s | 剩余: {eta:.1f}s", end="", flush=True)

        m_decryptor.decrypt_database(raw_msg_db, plain_msg_db, progress_callback=on_progress, force=True)
        if verbose:
            print("\n[2/2] nt_msg.db 解密完成", flush=True)

    service = QQChatService(plain_msg_db, resolver, my_uin=uin)
    return service, resolver


def handle_init(args: argparse.Namespace) -> None:
    print("=" * 60)
    print("QQ NT 本地数据库初始化与解密")
    print("=" * 60)
    service, resolver = ensure_ready(sync=True, force_decrypt=args.force, verbose=True)
    peers = service.get_c2c_peers()
    print(f"初始化成功！检测到活跃账号: {service.my_uin}")
    print(f"共有 {len(peers)} 位联系人产生过私聊记录")
    print("=" * 60)


def handle_contacts(args: argparse.Namespace) -> None:
    service, resolver = ensure_ready(verbose=False)
    peers = service.get_c2c_peers()

    if args.json:
        print(json.dumps(peers, ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print(f"私聊联系人列表 (共 {len(peers)} 位)")
    print("=" * 60)
    print(f"{'QQ 号':<12} {'显示名称':<20} {'消息数':<8} {'最后互动时间'}")
    print("-" * 60)
    for p in peers:
        print(f"{p['peer_uin']:<12} {p['display_name'][:18]:<20} {p['message_count']:<8} {p['last_time_str']}")
    print("=" * 60)


def handle_recent(args: argparse.Namespace) -> None:
    service, resolver = ensure_ready(verbose=False)
    target = resolver.resolve_target(args.contact)
    target_uin = target.uin if target else (int(args.contact) if str(args.contact).isdigit() else None)

    if not target_uin:
        print(f"[错误] 未能识别联系人: {args.contact}", file=sys.stderr)
        sys.exit(1)

    display_name = target.display_name if target else str(target_uin)
    messages = service.get_recent(target_uin, limit=args.limit)

    if args.json:
        out = {
            "contact": {
                "uin": target_uin,
                "display_name": display_name,
                "nick": target.nick if target else "",
                "remark": target.remark if target else ""
            },
            "count": len(messages),
            "messages": [
                {
                    "msg_id": m.msg_id,
                    "time": m.time_str,
                    "sender": m.sender_name,
                    "is_self": m.is_self,
                    "text": m.display_text,
                    "char_count": m.char_count
                }
                for m in messages
            ]
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print(f"最近消息: {display_name} ({target_uin}) - 共展示 {len(messages)} 条")
    print("=" * 60)
    for m in messages:
        t = m.time_str
        s = m.sender_name
        c = m.display_text
        if len(c) > 120:
            c = c[:115] + "..."
        print(f"[{t}] {s}: {c}")
    print("=" * 60)


def handle_search(args: argparse.Namespace) -> None:
    service, resolver = ensure_ready(verbose=False)
    target_uin = None
    if args.contact:
        target = resolver.resolve_target(args.contact)
        target_uin = target.uin if target else (int(args.contact) if str(args.contact).isdigit() else None)

    results = service.search_messages(
        query=args.query,
        peer_uin=target_uin,
        context_window=args.context,
        max_results=args.limit
    )

    if args.json:
        serializable = []
        for r in results:
            target_msg = r["target"]
            serializable.append({
                "peer_uin": target_msg.peer_uin,
                "display_name": resolver.get_display_name(target_msg.peer_uin),
                "match": {
                    "time": target_msg.time_str,
                    "sender": target_msg.sender_name,
                    "text": target_msg.display_text
                },
                "context": [
                    {
                        "time": m.time_str,
                        "sender": m.sender_name,
                        "text": m.display_text
                    }
                    for m in r["context"]
                ]
            })
        print(json.dumps(serializable, ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print(f"检索关键词: '{args.query}' (命中 {len(results)} 条)")
    print("=" * 60)
    for idx, r in enumerate(results, 1):
        target_msg = r["target"]
        peer_name = resolver.get_display_name(target_msg.peer_uin)
        print(f"--- [命中 #{idx}] 联系人: {peer_name} ({target_msg.peer_uin}) ---")
        for m in r["context"]:
            is_match = (m.msg_id == target_msg.msg_id)
            prefix = ">> " if is_match else "   "
            c = m.display_text
            if len(c) > 120 and not is_match:
                c = c[:115] + "..."
            print(f"{prefix}[{m.time_str}] {m.sender_name}: {c}")
    print("=" * 60)


def handle_rank(args: argparse.Namespace) -> None:
    service, resolver = ensure_ready(verbose=False)
    ranking = service.get_ranking(top_n=args.limit)

    if args.json:
        print(json.dumps(ranking, ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print(f"QQ NT 私聊活跃度排行榜 (Top {len(ranking)})")
    print("=" * 60)
    print(f"{'排名':<6} {'QQ 号':<12} {'联系人':<20} {'消息总数':<10} {'最后互动时间'}")
    print("-" * 60)
    for idx, p in enumerate(ranking, 1):
        print(f"{idx:<6} {p['peer_uin']:<12} {p['display_name'][:18]:<20} {p['message_count']:<10} {p['last_time_str']}")
    print("=" * 60)


def handle_analyze(args: argparse.Namespace) -> None:
    service, resolver = ensure_ready(verbose=False)
    target = resolver.resolve_target(args.contact)
    target_uin = target.uin if target else (int(args.contact) if str(args.contact).isdigit() else None)

    if not target_uin:
        print(f"[错误] 未能识别联系人: {args.contact}", file=sys.stderr)
        sys.exit(1)

    res = service.analyze_relationship(target_uin)

    if args.output:
        out_p = Path(args.output).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"[完成] 分析结果已保存至: {out_p}")

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    meta = res["metadata"]
    vol = res["volume_metrics"]
    lat = res["latency_metrics"]
    burst = res["burst_metrics"]

    print("=" * 60)
    print(f"关系动力学量化报告: {meta['display_name']} ({meta['peer_uin']})")
    print("=" * 60)
    print(f"时间跨度: {meta['first_msg_time']} 至 {meta['last_msg_time']} (约 {meta['time_span_days']} 天)")
    print("-" * 60)
    print("【消息与字数平衡性】")
    print(f"  - 消息总数: {vol['total_messages']} 条 (我方: {vol['my_messages']}, 对方: {vol['peer_messages']}, 条数比: {vol['message_ratio']})")
    print(f"  - 手打字符: {vol['total_chars']} 字 (我方: {vol['my_chars']}, 对方: {vol['peer_chars']}, 字数比: {vol['char_ratio']})")
    print(f"  - 单条均长: 我方 {vol['my_avg_chars_per_msg']} 字/条, 对方 {vol['peer_avg_chars_per_msg']} 字/条")
    print("-" * 60)
    print("【响应延迟中位数】")
    print(f"  - 我方回复延迟: 全天 {format_duration(lat['me']['median_delay_sec'])}, 工作段 {format_duration(lat['me']['daytime_median_delay_sec'])}, 晚间 {format_duration(lat['me']['nighttime_median_delay_sec'])}")
    print(f"  - 对方回复延迟: 全天 {format_duration(lat['peer']['median_delay_sec'])}, 工作段 {format_duration(lat['peer']['daytime_median_delay_sec'])}, 晚间 {format_duration(lat['peer']['nighttime_median_delay_sec'])}")
    print("-" * 60)
    print("【连续发言与主动追发】")
    print(f"  - 停顿 30 分钟后主动追发次数: 我方 {burst['my_follow_ups_after_30min']} 次, 对方 {burst['peer_follow_ups_after_30min']} 次")
    print(f"  - 单次最大连续发送消息数: 我方 {burst['my_max_consecutive_messages']} 条, 对方 {burst['peer_max_consecutive_messages']} 条")
    print("=" * 60)


def handle_export(args: argparse.Namespace) -> None:
    service, resolver = ensure_ready(verbose=False)
    target = resolver.resolve_target(args.contact)
    target_uin = target.uin if target else (int(args.contact) if str(args.contact).isdigit() else None)

    if not target_uin:
        print(f"[错误] 未能识别联系人: {args.contact}", file=sys.stderr)
        sys.exit(1)

    display_name = target.display_name if target else str(target_uin)
    messages = service.get_recent(target_uin, limit=999999)

    out_format = args.format.lower()
    if args.output:
        out_path = Path(args.output).resolve()
    else:
        cfg = QQConfigManager()
        ext = ".txt" if out_format == "compact" else (".csv" if out_format == "csv" else ".jsonl")
        out_path = Path(cfg.get_cache_dir()) / "exports" / f"{target_uin}_{display_name}{ext}"

    if out_format == "compact":
        p = QQChatExporter.export_compact(messages, out_path)
    elif out_format == "csv":
        p = QQChatExporter.export_csv(messages, out_path)
    else:
        p = QQChatExporter.export_jsonl(messages, out_path)

    print(f"[完成] 已导出 {len(messages)} 条聊天记录至: {p}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qqnt_tools",
        description="QQ NT 本地聊天数据库提取与关系分析工具集 (QQ NT Toolkit)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="可用操作模块")

    # 1. init
    init_p = subparsers.add_parser("init", help="初始化配置并解密数据库")
    init_p.add_argument("--force", action="store_true", help="强制重新扫描内存并全量解密")

    # 2. contacts
    contacts_p = subparsers.add_parser("contacts", help="查看所有存在私聊记录的联系人")
    contacts_p.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    # 3. recent
    recent_p = subparsers.add_parser("recent", help="快速查看与指定联系人的最近 N 条私聊")
    recent_p.add_argument("-c", "--contact", required=True, help="目标联系人 (QQ号/备注/昵称)")
    recent_p.add_argument("-n", "--limit", type=int, default=20, help="显示消息条数 (默认 20)")
    recent_p.add_argument("--json", action="store_true", help="以结构化 JSON 输出")

    # 4. search
    search_p = subparsers.add_parser("search", help="检索聊天记录关键词")
    search_p.add_argument("-q", "--query", required=True, help="关键词")
    search_p.add_argument("-c", "--contact", default=None, help="限定联系人 (QQ号/备注/昵称)")
    search_p.add_argument("-C", "--context", type=int, default=0, help="上下文消息条数")
    search_p.add_argument("-n", "--limit", type=int, default=50, help="最大返回匹配数 (默认 50)")
    search_p.add_argument("--json", action="store_true", help="以结构化 JSON 输出")

    # 5. rank
    rank_p = subparsers.add_parser("rank", help="私聊活跃度排行榜")
    rank_p.add_argument("-n", "--limit", type=int, default=15, help="榜单条数 (默认 15)")
    rank_p.add_argument("--json", action="store_true", help="以结构化 JSON 输出")

    # 6. analyze
    analyze_p = subparsers.add_parser("analyze", help="量化分析与联系人的沟通动力学指标")
    analyze_p.add_argument("-c", "--contact", required=True, help="目标联系人 (QQ号/备注/昵称)")
    analyze_p.add_argument("-o", "--output", default=None, help="将指标报表保存为 JSON 文件")
    analyze_p.add_argument("--json", action="store_true", help="以结构化 JSON 输出")

    # 7. export
    export_p = subparsers.add_parser("export", help="导出聊天记录到本地文件")
    export_p.add_argument("-c", "--contact", required=True, help="目标联系人 (QQ号/备注/昵称)")
    export_p.add_argument("--format", choices=["compact", "csv", "jsonl"], default="compact", help="导出格式")
    export_p.add_argument("-o", "--output", default=None, help="输出文件路径")

    return parser


def main() -> None:
    # 强制控制台输出使用 UTF-8
    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "init": handle_init,
        "contacts": handle_contacts,
        "recent": handle_recent,
        "search": handle_search,
        "rank": handle_rank,
        "analyze": handle_analyze,
        "export": handle_export,
    }

    handler = handlers.get(args.subcommand)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
