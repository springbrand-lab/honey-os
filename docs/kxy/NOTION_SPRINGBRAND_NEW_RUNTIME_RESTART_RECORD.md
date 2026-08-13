# Notion 与 SpringBrand MCP 安装后的 `/new` 和 Runtime 重启记录

记录日期：2026-08-13

信息来源：HoneyOS 本地网页当前对话 `http://127.0.0.1:8642/`

说明：本文只记录页面中已经出现的对话、操作和对话给出的原因，不对原因做独立分析或验证，也不包含修复操作。

## 安装后状态

对话中报告：

- SpringBrand MCP 已配置为原生 Streamable HTTP，URL 为 `https://connector.springbrand.ai/mcp`，OAuth 认证通过，状态为 `enabled`，服务端发现 2 个工具：`search_capabilities` 和 `execute_capability`。
- `springbrand-resource-discovery` 已作为 Skill 创建。对话提示当前会话不会重新加载新安装的 Skill，需要打开新的 Agent 会话。
- Notion MCP 已连通并完成 OAuth 认证，服务端发现 29 个工具。
- 当时的当前会话无法直接调用 SpringBrand 和 Notion 的 MCP 工具。

## 情况一：执行 `/new`

对话过程：

1. 用户询问如何开启新会话。
2. HoneyOS 回复直接发送 `/new`，并表示新会话会重新加载 Skill 和 MCP 工具。
3. 用户先后发送了 `/ne w` 和 `new`，HoneyOS 均提示格式不正确。
4. 用户正确发送 `/new`。
5. HoneyOS 回复：“好，新会话开始了。现在 Notion 和 SpringBrand 的工具应该都能用了。”
6. 用户随后要求调用 SpringBrand 的 `search_capabilities`。
7. HoneyOS 回复：MCP 服务器确实在运行，但 SpringBrand 的两个工具仍未出现在当前可调用工具列表中。

结果：

- `/new` 命令被接受，新会话已开始。
- 新会话没有让 SpringBrand MCP 工具进入当前可调用工具列表。
- 对话没有展示在 `/new` 后实际调用 Notion 工具的结果。

对话中给出的原因（未独立验证）：

- 新会话可以重新加载会话内容，但仅执行 `/new` 可能不足以让 HoneyOS Runtime 注入新安装的 MCP 工具。

## 情况二：提出重启 HoneyOS Runtime

SpringBrand 的情况：

- `/new` 后，`search_capabilities` 和 `execute_capability` 仍没有出现在可调用工具列表中。
- HoneyOS 提出可能需要执行 `honeyos restart`，让 Runtime 重新加载并注入 MCP 工具。

Notion 的情况：

- 用户询问 Notion 是否也需要重启。
- HoneyOS 回复 Notion 与 SpringBrand 情况相同：Notion 服务端存在 29 个工具，但这些工具没有出现在当前会话的可调用工具列表中。
- HoneyOS 因此也提出需要重启 HoneyOS Runtime。

对话中给出的原因（未独立验证）：

- MCP 已在服务端连通并完成认证，但新安装 MCP 的工具尚未被当前 HoneyOS Runtime 加载到会话工具列表。
- 对话认为 Runtime 重启可能是触发重新加载的必要步骤，而 `/new` 只创建新会话，未完成 Runtime 级别的重新加载。

## 后续补充：Runtime 重启后的实际状态

用户后续确认已经允许 HoneyOS 执行 `honeyos restart`。重启后的现场记录：

- 旧 runtime 于 14:35:31 开始退出。
- 新 runtime 于 14:35:43 启动，LaunchAgent 显示为 `running`，PID 为 58860。
- 新 runtime 启动时记录：`Could not bind 127.0.0.1:8642: address already in use`。
- 检查时 PID 58860 仍存活，但没有进程监听 8642。
- 访问 `http://127.0.0.1:8642/` 返回 HTTP 000，连接被拒绝。
- 因此实际状态是主进程仍在运行，但 HoneyOS 网页服务没有启动成功。

代码路径中记录的处理方式：

- API Server 遇到 `EADDRINUSE` 后把它标记为不可重试错误并返回失败。
- Gateway 保留主进程继续运行，不会在端口后来释放后自动重新绑定 API Server。
- macOS 的 restart 路径在重新注册 LaunchAgent 后直接返回，没有等待 HoneyOS HTTP 健康检查通过。

本次只补充记录和诊断，没有再次重启服务，也没有修改修复代码。

## 后续复测：干净停启和 MCP 实际调用

为避开 `honeyos restart` 的端口竞态，本次采用以下恢复过程：

1. 执行 `honeyos stop`。
2. 确认旧 runtime 已退出、LaunchAgent 已卸载、8642 无监听。
3. 执行 `honeyos start`。

恢复结果：

- 新 runtime PID 为 70085，正常监听 `127.0.0.1:8642`。
- HoneyOS 首页返回 HTTP 200。
- `/health` 返回 `status: ok`。
- `honeyos mcp list` 显示 `notion-oauth-manual` 和 `springbrand` 均为 `enabled`。

MCP 命令行连接测试：

- Notion：OAuth Token 复用成功，连接耗时约 3.2 秒，发现 29 个工具。
- SpringBrand：OAuth Token 复用成功，连接耗时约 2.0 秒，发现 2 个工具：`search_capabilities`、`execute_capability`。

HoneyOS 真实对话只读调用：

- 实际调用 SpringBrand `search_capabilities`，查询“客户反馈汇总工作流”，调用成功，返回 0 条匹配。
- 实际调用 Notion `notion_search`，查询“HoneyOS”，调用成功，返回 0 条匹配。
- 0 条是搜索业务结果，不是连接或工具调用错误。
- 两个调用均未创建、修改或删除数据。

调用完成后再次检查：8642 仍正常监听，首页和健康接口继续返回 200，两台 MCP 仍为 `enabled`。
