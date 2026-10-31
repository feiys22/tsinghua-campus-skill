---
name: campus-wechat
description: 微信本地消息只读（会话/历史/搜索/导出待办候选）。优先调用本机 wx-cli；否则读用户已解密的规范化库。当用户提到微信消息、群聊记录、从微信抽待办时使用。
metadata:
  openclaw:
    os: [windows, macos, linux]
---

# 微信（本地只读）

从**本机已登录微信**的本地数据查询会话与消息，输出 JSON。本子技能是**薄封装**，**不内置、不 vendoring 密钥提取/逆向代码**。

## 合规与风险（必读，首次 setup 必须 --ack）

> **使用即表示你已知悉并自行承担风险。**

1. 《腾讯微信软件许可及服务协议》禁止未授权的第三方工具对客户端内存/本地数据做复制、读取或控制；通过逆向/调试提取数据库密钥以解密本地库，存在**合规风险**。
2. 2025–2026 年起，腾讯已要求 GitHub 下架大批「导出/分析微信聊天记录」开源项目；相关工具随时可能失效或不可得。
3. 微信安全中心曾公开劝阻「访问本地聊天记录的第三方工具」。本地只读、不发消息通常低于机器人外挂的风控画像，但**仍可能违反 ToS，账号处理空间由平台决定**，本技能包**不保证**不封号。
4. 解密后的聊天记录含大量隐私（你与好友的）。密钥、`all_keys.json`、明文库、导出文件**禁止**提交 git、上传网盘或发给无关第三方/云端模型（除非用户明确要求且知情）。
5. 仅限**你自己的账号、本机数据、用户明确要求**的场景；禁止用于读取他人设备或未授权账号。

首次使用必须由 AI 运行：

```text
python wechat.py setup --ack
```

未 ack 时，sessions/history/search/export-todos 会拒绝执行。

---

## 如果你是 AI，请阅读以下内容

### 铁律

- **铁律 1：AI 运行所有脚本**。禁止让用户敲命令（安装外部工具时可指导用户确认权限弹窗）。
- **铁律 2：stdout 只输出 JSON**；进度写 `runtime/logs/campus.log`，不写 stderr。
- **铁律 3：不提取密钥**。本目录脚本禁止实现/复制内存扫描、GDB/LLDB hook、SQLCipher 爆破。密钥与解密交给用户本机已安装工具。
- **铁律 4：只读**。不发送微信消息、不改微信客户端数据。
- **铁律 5：隐私**。不把密钥、完整聊天导出贴进公开 issue；面向用户展示时按需摘要。
- **铁律 6：export-todos 需确认**。启发式待办必须展示给用户确认后再写入其他待办系统。

### 后端优先级

1. **wx-cli（推荐）**：本机 `wx` 二进制。命令与 JSON/`meta` 字段对齐 [jackwener/wx-cli-again](https://github.com/jackwener/wx-cli-again)（`wx sessions` / `history` / `search` / `doctor --json`）。上游发布仓库可能为 private（如 `botiverse/wx-cli`），需用户有权构建或拿到二进制。
2. **规范化 index.db**：私有目录下已解密 SQLite（`sessions` + `messages` 表），可由 `import-jsonl` 或用户从 wcdb-key-tool / wxextract 导出后转换得到。

强制后端：`--backend wx|index|auto`（默认 auto），或环境变量 `CAMPUS_WECHAT_BACKEND`。

### 使用

```text
wechat.py setup --ack
wechat.py status [--skip-doctor]
wechat.py sessions [-n 50] [--backend auto|wx|index]
wechat.py history --talker <名> [-n 50] [--since UNIX] [--until UNIX]
wechat.py search --query <词> [--in <会话>] [-n 50]
wechat.py export-todos [--talker <名>] [--days 14] [-n 50]
wechat.py import-jsonl --file <path.jsonl>   # 无 wx 时的后备导入
```

私有数据目录（仓外，可用 `CAMPUS_WECHAT_HOME` 覆盖）：

- Linux/macOS：`~/.local/share/campus-wechat/`
- Windows：`%LOCALAPPDATA%\campus-wechat\`

内含：`TOS_ACKNOWLEDGED`、`config.json`、`index.db`、`decrypted/`。**不要**把密钥写进该目录的日志；本脚本也不会把密钥打到 JSON。

### 工作流

```text
用户: 看看微信最近聊了啥 / 从微信抽待办
AI:
  1. wechat.py status → 若 ack_tos=false → setup --ack（先向用户复述风险摘要并获同意）
  2. 若 wx_cli.found=false → 按下方「各 OS 安装」协助安装并提醒用户完成 wx init（需管理员/sudo + 微信已登录）
  3. wechat.py sessions → 汇报
  4. 需要细节 → history / search
  5. export-todos → 展示候选，用户确认后再同步到待办应用
```

### 各 OS 安装要点（外部工具，非本仓代码）

#### 共用：wx-cli（优先）

参考文档与命令约定：[jackwener/wx-cli-again](https://github.com/jackwener/wx-cli-again)

- 平台：Windows / Linux / macOS；面向微信 **4.x**（含较新版本的 hook/扫描取钥路径，以上游为准）。
- 安装：按该 README（源码构建 `cargo build --release` 得到 `wx`，或有权限时从对应 release 取预编译包）。可将路径设为 `WX_CLI` / `CAMPUS_WX_CLI`。
- 初始化：微信已登录；Linux/macOS `sudo wx init`；Windows 管理员 PowerShell `wx init`。缺分片密钥时按上游文档 `wx key extract --hook-seconds 90`。
- 验证：`wx doctor --json`；然后本技能 `wechat.py status` / `sessions`。
- 日常查询一般**不必**一直开着微信（以 wx-cli 文档为准）；**取钥阶段**通常需要微信在跑。

#### Windows 后备：wcdb-key-tool + 解密库

- https://github.com/TANGandXUE/wcdb-key-tool （`wcdb_key_tool_windows.py`）
- 管理员、微信已登录；解密产物经转换/`import-jsonl` 进入 `index.db`，或放入 `decrypted/` 且含规范化表。
- 可选环境变量：`WCDB_KEY_TOOL` 指向脚本路径（仅供 status 探测）。

#### Linux 后备：wcdb-key-tool / wxextract

- wcdb-key-tool：`sudo` + gdb；4.1+ 常需重新登录抓 passphrase。
- [wxextract](https://github.com/boujuan/extract-wechat-messages-linux)：导出 JSONL 后 `wechat.py import-jsonl --file ...`。
- 注意：bwrap 沙箱版微信可能阻止 ptrace；官方包见 https://linux.weixin.qq.com/ 。

### 边界

- 不发送消息、不点赞、不操纵 UI。
- 不保证上游工具对微信最新小版本永远可用；微信升级可能导致取钥失败。
- `export-todos` 为关键词启发式，会漏报/误报。
- macOS 细节以 wx-cli-again 文档为准（本技能主目标为用户的 Windows + CachyOS Linux）。

---

## 如果你是用户，请阅读以下内容

对 AI 说：

- **「微信最近会话」** / **「某某群最近消息」** / **「搜微信里的作业」** / **「从微信抽待办」**

首次会请你确认风险（`--ack`），并可能需要你在本机完成 wx-cli 安装与一次管理员/`sudo` 初始化。聊天数据只在你电脑上处理。
