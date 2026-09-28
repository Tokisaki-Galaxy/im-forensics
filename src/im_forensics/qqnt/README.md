# QQ NT 本地数据提取与关系动力学分析工具 (QQ NT Tools)

用于本地 QQ NT 客户端数据库（`nt_msg.db`、`profile_info.db`）的安全密钥提取、流式解密、聊天记录检索、联系人解析与关系动力学量化分析的 Python 工具库与命令行程序。

---

## 常用命令速查

所有子命令均通过统一入口执行，支持通过联系人备注、昵称或 QQ 号进行匹配：

```bash
# 1. 首次初始化与解密 (自动复用配置文件密钥，无需每次探测)
python scripts/qqnt_tools/cli.py init

# 2. 查看所有存在私聊记录的联系人
python scripts/qqnt_tools/cli.py contacts

# 3. 查看与某个联系人的最近 20 条私聊消息
python scripts/qqnt_tools/cli.py recent -c "张秀峰" -n 20

# 4. 检索聊天关键词，并显示命中消息的前后 2 条上下文
python scripts/qqnt_tools/cli.py search -c "张秀峰" -q "作业" -C 2

# 5. 统计全库私聊联系人消息总量排行榜 (前 15 名)
python scripts/qqnt_tools/cli.py rank -n 15

# 6. 一键分析与指定联系人的关系动力学指标 (条数比、字数比、回复延迟、追发频率等)
python scripts/qqnt_tools/cli.py analyze -c "1503896033" -o "analysis_reports/data/agent1_metrics.json"

# 7. 导出结构化聊天记录 (支持 compact / csv / jsonl)
python scripts/qqnt_tools/cli.py export -c "张秀峰" --format compact -o "exports/zhangxiufeng.txt"
```

---

## 目录与模块职责

```text
scripts/qqnt_tools/
├── cli.py                     # 统一命令行入口 (init/contacts/recent/search/rank/analyze/export)
├── README.md                  # 使用指南与协议说明
├── common/                    # 基础通用工具
│   ├── config.py              # 本地配置文件管理 (config.json 读写与密钥防重复探测)
│   ├── contact_resolver.py    # profile_info.db 联系人昵称/备注/UID 映射
│   ├── db_locator.py          # QQ NT 本地数据路径探测
│   └── time_utils.py          # 时间戳与相对时间格式化
├── crypto/                    # 密钥抓取与加解密
│   ├── key_extractor.py       # 无注入 Windows 内存只读扫描与 HMAC 校验
│   ├── page_decryptor.py      # AES-256-CBC 按页流式解密 (保留 80 字节 SQLite Reserve)
│   └── proto_parser.py        # 40800 Protobuf 消息体轻量 Wire 逆向解析器
└── chat/                      # 聊天记录模块
    ├── service.py             # C2C 私聊检索、上下文提取、排行榜与关系动力学分析
    └── excel_writer.py        # 结构化文本/CSV/JSONL 数据导出器
```

---

## 底层机制与关键避坑说明

在直接编写代码操作 QQ NT 本地数据库时，需要特别注意以下底层特性：

1. **密钥持久化与单次抓取原则**  
   - QQ NT 每个数据库（`nt_msg.db`、`profile_info.db` 等）具有独立的 Salt 与派生 Key。
   - 第一次从 `QQ.exe` 进程的 `wrapper.node` 模块只读扫描到密钥后，会自动持久化到本地 `scripts/qqnt_tools/config.json`（已加入 `.gitignore`）。
   - 后续所有工具运行优先从配置文件直读，**绝不进行重复的进程内存扫描**。

2. **SQLite Reserve 字段陷阱（关键避坑）**  
   - QQ NT 的 SQLCipher 数据库每页 4096 字节，尾部保留 48 字节的加密元数据（IV + HMAC）。
   - 同时，数据库文件第 20 字节记录了 SQLite Page Reserve 为 80。
   - 解密生成明文 SQLite 文件时，**必须保留第 20 字节的 80 不变**，绝不能强行写 0。写 0 会导致 SQLite B-tree 内部 Cell 偏移量错位，引发 `database disk image is malformed` 错误。

3. **Protobuf 消息体提取**  
   - `c2c_msg_table` 的文本与富媒体保存在 `40800` 列的 BLOB 中。
   - 内部包含嵌套结构 `MsgBody -> repeated MsgContent`。纯文本位于 tag `45101`，图片与文件元信息位于 `45402` 与 `45815`，表情位于 `45002` 与 `45302`。
   - 本工具内置了原生轻量 Wire 格式解码器，无需额外安装或编译复杂的 Protobuf 描述符库。

---

## Python 代码调用示例

如果你在子代理或其他脚本中需要直接调用 QQ NT 聊天数据：

```python
from qqnt_tools.common import QQContactResolver, QQNTLocator
from qqnt_tools.chat import QQChatService

locator = QQNTLocator()
plain_msg_db, plain_profile_db = locator.get_cache_plain_dbs()

# 1. 初始化联系人解析服务
contact_resolver = QQContactResolver(plain_profile_db)

# 2. 初始化聊天服务
chat_service = QQChatService(plain_msg_db, contact_resolver)

# 3. 获取最近聊天记录
peer, msgs = chat_service.get_recent("张秀峰", limit=20)
for m in msgs:
    print(f"[{m.time_str}] {m.sender_name}: {m.display_text}")

# 4. 获取关系动力学分析基准指标 (对齐 AGENTS.md 规范)
metrics = chat_service.analyze_relationship(peer.uin)
print("条数比:", metrics["volume_metrics"]["message_ratio"])
print("手打字数比:", metrics["volume_metrics"]["char_ratio"])
print("全天响应延迟中位数 (我 vs 对方):", 
      metrics["latency_metrics"]["me"]["median_delay_sec"], 
      metrics["latency_metrics"]["peer"]["median_delay_sec"])
```
