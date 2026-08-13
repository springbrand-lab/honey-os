# HoneyOS MCP 真实手测报告

测试日期：2026-08-13

## 结论

- MCP-01 命令行入口：通过。
- MCP-02 无认证 MCP 的安装、重连和工具调用：通过，但真实对话首次生成了错误的 CLI 参数顺序，随后能够自行修正。
- MCP-03 OAuth MCP 网页授权：修复后通过 HoneyOS 侧核心流程。Notion 授权 URL 能生成，授权页能打开；进入 Notion 后点击 Google 未产生新窗口，属于第三方登录页/当前浏览器网络侧的后续问题，不是 Honey 后台退出。
- MCP-04 Token 重启复用：未执行；MCP-03 尚未取得 Token。

## 实际操作记录

### 1. 命令行安装无认证 MCP

使用隔离目录 `/tmp/honeyos-mcp-manual`，在交互式终端执行：

```bash
honeyos mcp add manual-everything \
  --command npx \
  --args -y @modelcontextprotocol/server-everything
```

实际结果：

- 成功连接 `@modelcontextprotocol/server-everything`。
- 发现 16 个工具。
- 在终端输入 `Y` 后成功保存并启用全部工具。
- 再次执行 `honeyos mcp test manual-everything`，约 3 秒连接成功并再次发现 16 个工具。
- `honeyos mcp list` 显示服务器为 enabled。

### 2. 网页真实对话安装并调用 MCP

在 `http://127.0.0.1:8642/` 的真实 Companion 对话中发送：

> 请安装官方测试 MCP：使用 stdio 命令 npx -y @modelcontextprotocol/server-everything，名称设为 manual-everything。安装成功后调用它的 echo 工具，输入“honeyos-mcp-manual-ok”，并把结果告诉我。

实际结果：

1. HoneyOS 先请求修改本机配置的权限。
2. 点击“好，你继续”后，首次执行把 `--connect-timeout 30` 放在了 `--args` 后面，导致它被误写入 MCP 服务的 args。
3. HoneyOS 识别到错误后再次请求权限并修正配置。
4. 最终连接成功、发现 16 个工具，并通过 stdio 调用 `echo`。
5. 实际返回：`Echo: honeyos-mcp-manual-ok`。
6. 刷新设置页后可看到 `manual-everything / 已配置`。

这里暴露了一个独立问题：`mcp add` 的 `--args` 必须最后出现，但对话模型容易继续在其后添加 HoneyOS 自身参数。

### 3. 网页 OAuth 手测

分别使用两个官方 OAuth MCP：

- Figma：`https://mcp.figma.com/mcp`
- Notion：`https://mcp.notion.com/mcp`

两次均通过真实对话写入 `auth: oauth`、`enabled: true`，然后在设置页完成以下操作：

1. 页面正确显示 `OAuth MCP / 需要授权 / 授权`。
2. 点击“授权”。
3. 页面变为“正在准备授权”。
4. 后端创建了 OAuth client 注册缓存，说明流程已经进入 OAuth 初始化。
5. 但授权 URL 始终没有返回，浏览器没有出现 Figma 或 Notion 授权页。

两个独立供应商结果一致，因此不能归因于单个 MCP 服务。当前实机故障位于 Companion OAuth worker 从“完成发现/注册”到“发布 authorization URL”之间。worker 又把连接超时下限设为 315 秒，导致页面长时间停留在“正在准备授权”。

### 4. 修复后 OAuth 真实复测

本轮使用真实 Companion 对话安装官方 Notion Remote MCP：

- 名称：`notion-oauth-fixed`
- URL：`https://mcp.notion.com/mcp`
- 认证：OAuth

手测由测试者全程操作，没有等待用户代点：

1. 在真实对话中提交安装请求，并点击 HoneyOS 的本机能力确认按钮。
2. 进入 MCP 设置，亲自点击 `授权`。
3. 约 10 秒后页面从“正在准备授权”变为可打开授权页，并显示 `打开授权页` 兜底链接。
4. 亲自点击兜底链接，成功进入 `https://app.notion.com/login`，页面显示 Notion 登录表单和 Google、ChatGPT、Apple、Microsoft 等登录按钮。
5. 亲自点击 `Google`。按钮进入加载状态，但没有出现新的 Google 标签页或弹窗，地址仍为 Notion 登录页；浏览器同时记录到外网请求超时。
6. 点击 Google 后，HoneyOS 后台进程仍在监听 8642。清理后执行完整停启，首页返回 HTTP 200。

结论：原始故障“授权 URL 无法生成、授权页无法拉起”已经修复。Google 按钮没有继续跳转时，HoneyOS 后台并未挂掉；故障边界已经进入 Notion/Google 第三方登录页或测试浏览器的外网访问。未输入或提交账号、密码、验证码，也未执行最终授权。

代码回归：相关测试文件共 68 项，全部通过。

## 手测期间发现的其他问题

- `honeyos restart` 曾在旧进程尚未释放 8642 时拉起新进程，导致新进程报 address already in use。测试清理时再次观察到同类竞争；等待后台完全停止后再启动可恢复。
- 对话修改 `~/.honeyos/config.yaml` 会触发本机能力授权，这是预期的安全行为。

## 清理

- 已从日常 `~/.honeyos` 删除 `manual-everything`、两个 Figma 测试配置和所有 Notion 测试配置（包括 `notion-oauth-fixed`）。
- 已清理相应 OAuth 测试凭据。
- 最终 `honeyos mcp list` 显示没有配置 MCP；HoneyOS 首页返回 HTTP 200。
- 隔离目录 `/tmp/honeyos-mcp-manual` 保留无认证 MCP 配置，供后续复测使用。
