---
name: campus-wechat
description: 读取本机微信里的校园相关消息。用户说「看微信」「社团消息」「社工消息」「导师消息」「课题组消息」时使用。依赖本机 wx-cli，不走清华统一认证。
metadata:
  openclaw:
    requires:
      os:
        - windows
        - macos
        - linux
---

# 微信

读取本机已登录的微信桌面版消息。用来看社团、社工、导师和课题组的非正式安排。不发消息，不标已读。

## 如果你是 AI，请阅读以下内容

### 铁律

- **铁律 1：AI 运行所有脚本**。禁止让用户敲命令。
- **铁律 2：脚本面向 AI**。stdout 输出 JSON，进度写 `runtime/logs/campus.log`，不写 stderr。日志只记命令名，不记消息正文。
- **铁律 3：只读**。本子技能不发送消息，不标已读。用户明确要求发送时，停住并说明当前未实现。
- **铁律 4：不走 CAS**。微信不使用校园账号密码。缺的是本机 `wx-cli` 和已登录的微信桌面版。
- **铁律 5：不写死人名**。不要把某位老师、家长或群名写进代码或默认配置。按消息内容判断。
- **铁律 6：隐私**。聊天记录只留在本机。不要把正文写入笔记、提交到仓库，或写进 `campus.log`。

### 使用

```
wechat.py status
wechat.py sessions [--limit N] [--filter private,group]
wechat.py unread [--limit N] [--filter private,group]
wechat.py history --chat <名称> [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--limit N] [--type text]
wechat.py search --query <关键词> [--chat <名称>] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--limit N]
```

`limit` 最大 200。`--filter` 只能是 `all`、`private`、`group`、`official`、`folded`。

### 工作流

```
用户: 看微信 / 社团有什么消息 / 导师或课题组有没有安排
AI:
  1. wechat.py status。失败就说明 wx-cli 未安装、未 init，或微信未登录，停住。
  2. wechat.py sessions --filter private,group --limit 30
  3. 对可能相关的会话再 history 或 search。默认近 7 天；用户指定范围时用那个范围。
  4. 只汇报需要用户行动、回复、下载、提交、到场，或带明确时间的事项。
  5. 时间解析不出就列出原句，不编时间。
```

重要事项的例子：社团活动时间、社工值班、导师临时约谈、课题组让下载数据或交材料。这些只是例子，不是名单。

不汇报：闲聊、表情、广告、与用户无关的群消息、家教中介群和兼职群的群发招单。

### 边界

- 依赖本机 [wx-cli](https://github.com/jackwener/wx-cli)。微信桌面版必须已登录，并且完成过 `wx init`。
- `sessions` 和微信数据库都没有可靠置顶字段。`status` 固定返回 `pin_supported: false`。不能把最近会话当成置顶。
- 第一版只读。不能代发，不能标已读。
- 不接外部待办软件。取数到此为止。
- 公众号和折叠入口默认不扫。用户点名时再查。

---

## 如果你是用户，请阅读以下内容

对 AI 说：

- **「看微信」** — 看最近需要你处理的微信消息
- **「社团有什么新安排」** / **「导师有没有发消息」** / **「课题组让我做什么」** — 按内容查找

使用前，电脑上要已安装 `wx-cli`，微信桌面版保持登录。这个功能不需要填写统一认证密码。
