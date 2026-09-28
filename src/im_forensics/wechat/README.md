# 微信本地数据提取与关系动力学分析工具 (WeChat Tools)

用于本地微信数据库（WCDB）的数据提取、关键词检索、关系动力学量化分析与朋友圈导出的 Python 工具库与命令行程序。

---

## 常用命令速查

所有子命令均通过统一入口执行，支持通过联系人备注、昵称、微信号或拼音模糊匹配：

```bash
# 1. 查看与某个联系人的最近 20 条消息
python scripts/wechat_tools/cli.py recent -c "王韵怡" -n 20

# 2. 检索聊天关键词，并显示命中消息的前后 3 条上下文
python scripts/wechat_tools/cli.py search -c "刘雅轩" -q "不婚主义" -C 3

# 3. 统计全库私聊联系人消息总量排行榜 (前 15 名)
python scripts/wechat_tools/cli.py rank -n 15

# 4. 一键分析与指定联系人的互动平衡与动力学指标 (字数比、响应延迟、追发频率)
python scripts/wechat_tools/cli.py analyze -c "王亦然"

# 5. 导出结构化聊天记录 (支持生成给大模型做分析的紧凑版 CSV)
python scripts/wechat_tools/cli.py export -c "杜晨晓" --format compact

# 6. 导出朋友圈为离线网页，自动解密图片与视频
python scripts/wechat_tools/cli.py sns -c "王韵怡" --download-media
```

---

## 目录与模块职责

```text
scripts/wechat_tools/
├── cli.py                     # 统一命令行入口
├── common/                    # 基础通用工具
│   ├── contact_resolver.py    # 联系人索引构建与模糊解析
│   ├── db_locator.py          # 微信本地数据库路径自动探测
│   └── time_utils.py          # 时间格式与时间戳转换
├── crypto/                    # 解压与解密
│   ├── wcdb_decompress.py     # WCDB 长文本 zstd 解压缩核心
│   ├── isaac64.py             # 朋友圈媒体流解密算法
│   └── media_decrypt.py       # 朋友圈图片/视频解密调度
├── chat/                      # 聊天记录模块
│   ├── service.py             # 聊天数据提取、检索与排行榜
│   ├── metrics.py             # 关系动力学与互动平衡度计算引擎
│   ├── excel_writer.py        # 标准格式 Excel 导出
│   └── preprocessor.py        # 大模型紧凑 CSV 预处理
└── sns/                       # 朋友圈模块
    ├── service.py             # 朋友圈时间线提取调度
    ├── parser.py              # 时间线 XML 与动态结构解析
    ├── media_fetcher.py       # 媒体异步下载
    └── html_renderer.py       # 高保真离线 HTML 网页生成
```

---

## 底层机制与关键避坑说明

在直接编写代码操作本地微信数据库时，需要特别注意以下机制，避免踩坑：

1. **长文本不是明文，严禁截断原始字节**  
   微信聊天表中的长文本和分享卡片以二进制 BLOB 存储，采用 **Zstandard (RFC 8878)** 压缩（文件头为 `\x28\xb5\x2f\xfd`）。  
   在 SQL 查询时，切勿使用类似 `substr(content, 1, 30)` 的操作，破坏压缩帧会导致解压崩溃。请统一通过 `crypto.wcdb_decompress.decompress_wcdb_content()` 整体解压。

2. **跨分卷数据库与动态表名**  
   聊天记录分散在 `message_0.db` 至 `message_6.db` 等多个分卷中。  
   每位联系人的数据表名为 `Msg_<md5(wxid)>`。检索时必须遍历全部存在的 `message_*.db` 分卷。

3. **发送者身份判定规则**  
   消息表中的发送者标识字段不能直接硬编码对比。判定发送方时，需要结合当前所在分卷库的 `Name2Id` 表映射（`rowid -> wxid`），或者直接通过 `ChatExportService` 自动处理好的 `sender_wxid` 进行区分。

---

## Python 代码调用示例

如果你在其他脚本或代理任务中需要获取聊天数据，直接导入服务类即可获得解析好的结构化字典，无需手写 SQL：

```python
from wechat_tools.chat.service import ChatExportService

service = ChatExportService()

# 1. 内存获取解析好的消息列表
profile, messages = service.fetch_messages(contact="王亦然", limit=50, reverse=True)
for msg in messages:
    print(f"[{msg['time_str']}] {msg['sender_name']}: {msg['content']}")

# 2. 获取量化体检指标字典
metrics = service.analyze_relationship(contact="王亦然")
print("字符投入比 (我:对方) =", metrics["balance"]["char_ratio_user_to_target"])
```
