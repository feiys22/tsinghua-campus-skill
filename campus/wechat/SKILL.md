---
name: campus-wechat
description: 微信本地消息只读。直接调用本机 wx-cli（wx），不做封装。用户提到微信消息、群聊、搜微信时使用。
metadata:
  openclaw:
    os: [windows, macos, linux]
---

# 微信（直接调用 wx）

本子技能**不提供 Python 封装**。AI 直接调用用户本机已安装的 `wx`（[jackwener/wx-cli-again](https://github.com/jackwener/wx-cli-again)）。只读，不发消息。

## 合规（简）

逆向/调试取钥可能违反微信 ToS；密钥与明文聊天禁止提交 git、上传网盘或发给无关第三方。仅限用户本人账号、本机数据、用户明确要求的场景。

## 铁律

1. AI 直接跑 `wx`，禁止再包一层脚本。
2. 只读：不发送、不点赞、不改微信客户端数据。
3. 本技能不实现密钥提取；取钥交给用户本机的 wx / wcdb-key-tool。
4. 面向用户展示时按需摘要；密钥与完整导出不进公开 issue。

## wx 路径

| 系统 | 二进制 |
|------|--------|
| Windows | `C:\Users\<user>\AppData\Local\wx-cli\wx.exe`（也可在 PATH） |
| Linux | `~/.local/bin/wx` |
| 覆盖 | 环境变量 `WX_CLI` 指向完整路径 |

日常查询示例（微信已登录且已完成取钥后）：

```text
wx sessions -n 20
wx unread
wx search <关键词>
wx history <会话名或 wxid> -n 50
wx new-messages
```

Windows 上未在 PATH 时用完整路径，例如：

```text
& "$env:LOCALAPPDATA\wx-cli\wx.exe" sessions -n 20
```

## 工作流

```text
用户: 看看微信 / 搜微信里的作业 / 某某群最近消息
AI:
  1. 确认本机有 wx（which wx / 上述路径）
  2. 直接 wx sessions / unread / search / history / new-messages
  3. 失败且提示未 init → 按下方「首次取钥」协助，不要写封装
```

## 首次取钥

### Windows

微信桌面版已登录后，管理员 PowerShell：

```text
wx init
```

一般可直接扫内存取钥。完成后 `wx sessions -n 5` 验证。

### Linux（微信 4.1+ / wechat-bin AUR）

4.1+ **不在内存里留原始 DB 密钥**，`wx init` / 内存 hook 往往不够，需要用 [wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool) 在**登录瞬间**用 GDB 断点截获 passphrase，再派生各库密钥。

要点（踩坑记录，写进这里免得再绕）：

1. **`--verbose` 放在子命令前**：`python wcdb_key_tool.py --verbose extract ...`，不要写成 `extract --verbose`。
2. **PIE 基址**：工具若把「第一个 r-xp 映射」当镜像基址会断错点；应使用 **offset 为 0 的那条镜像映射** 作为基址（WeChat 是 PIE）。若本机脚本有此 bug，先改再跑。
3. **sudo 会清空 PATH**：用完整路径，例如 `sudo /home/<user>/.local/bin/wx ...`，不要只写 `sudo wx`。
4. **Linux 版 wx 忽略 `--hook-seconds`**（该参数主要是 macOS 实现）；不要靠加长 hook 秒数在 Linux 上等密钥。
5. 取钥常需：微信在跑 → 退出并重新登录一次以触发断点 → 成功后密钥写入 `~/.wx-cli/all_keys.json`。
6. 若该文件属主是 root：`sudo chown "$USER:$USER" ~/.wx-cli/all_keys.json && chmod 600 ~/.wx-cli/all_keys.json`。
7. bwrap 沙箱版微信可能拦 ptrace；优先用 https://linux.weixin.qq.com/ 或 AUR `wechat-bin` 非沙箱安装。

完成后无需 sudo，直接：

```text
~/.local/bin/wx sessions -n 5
```

### 参考

- wx-cli 命令约定：[jackwener/wx-cli-again](https://github.com/jackwener/wx-cli-again)
- Linux 取钥后备：[TANGandXUE/wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)

## 边界

- 不保证微信小版本升级后取钥仍可用。
- 无可靠「置顶会话」字段；不要把个人联系人写进仓库代码。
- 本目录不再维护 `wechat.py` / `_wxcli.py` / index.db 后备链路。
