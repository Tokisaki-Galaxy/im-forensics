# IM-Forensics (即时通讯数据取证与关系分析工具库)

针对微信 (WeChat WCDB) 与 QQ NT 的本地数据库取证、流式解密、消息链路还原与关系动力学分析工具套件。

## 架构说明

```text
im-forensics/
├── WX/DB/               # [本地持久化，受 .gitignore 保护] 微信解密数据库 (contact, message, sns 等)
├── data/qqnt_cache/     # [本地持久化，受 .gitignore 保护] QQ NT 解密数据库与中间缓存
├── config.json          # [本地持久化，受 .gitignore 保护] QQ NT 数据库解密密钥配置
├── src/
│   └── im_forensics/
│       ├── wechat/      # 微信取证与分析模块
│       └── qqnt/        # QQ NT 取证与分析模块
├── pyproject.toml
└── .gitignore
```

## 安装与快速上手

建议以可编辑模式（editable mode）安装至当前 Python 环境：

```bash
pip install -e .
```

安装完成后，可以在系统任意工作区直接使用命令行工具：

### 1. 微信 CLI (`wechat-cli`)
```bash
# 查看与指定联系人的最近 20 条消息
wechat-cli recent -c "张三" -n 20

# 关键词搜索（支持正则与上下文窗口）
wechat-cli search -c "张三" -q "合同" -C 3

# 私聊互动排行榜
wechat-cli rank -n 15

# 关系动力学量化分析
wechat-cli analyze -c "张三" -o "analysis.json"

# 导出格式化表格或紧凑 CSV
wechat-cli export -c "张三" --format both
```

### 2. QQ NT CLI (`qqnt-cli`)
```bash
# 查看所有私聊联系人概览
qqnt-cli contacts

# 查看最近私聊
qqnt-cli recent -c "李四" -n 20

# 关系动力学量化体检
qqnt-cli analyze -c "1503896033" -o "metrics.json"

# 导出紧凑对话文本
qqnt-cli export -c "李四" --format compact -o "exports/lisi.txt"
```

## 数据安全与规范

1. **零数据泄露**：`WX/DB/`、`data/`、`config.json` 以及所有 `.db`、`.key` 均已在 `.gitignore` 中作永久屏蔽。
2. **纯算法开源**：本仓库只维护取证算法、解密解压逻辑与数据流处理管道，绝不将任何真实会话、个人隐私或凭据提交入库。
