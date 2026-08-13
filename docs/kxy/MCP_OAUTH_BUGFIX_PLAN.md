# HoneyOS 第三方 MCP OAuth Bug 修复方案

## 问题范围

修复 HoneyOS 作为 MCP Client 时，无法在对话中完成第三方 OAuth MCP 安装和授权的问题。不涉及把 HoneyOS 作为 MCP Server 安装到其他客户端。

## 根因

1. 官方安装只安装 `honeyos` extra，没有安装已经声明的 `mcp` extra。
2. 公开 `honeyos` CLI 没有把 `mcp` 转发给底层 runtime。
3. 后台工具发现会正确禁止交互式 OAuth，但 8642 Companion 服务没有承接 OAuth 的接口。
4. Companion 前端没有显示 MCP 状态、打开授权页或轮询授权结果。

## 修复设计

1. 官方安装同时安装 `honeyos` 和 `mcp` extras。
2. 公开 CLI 透传 `honeyos mcp ...`，复用现有 runtime 命令。
3. 将现有 Dashboard OAuth worker 移到已有的 `mcp_dashboard_oauth.py`，供 Dashboard 和 Companion 共用。
4. 在 8642 Companion 服务增加 MCP 列表、启动授权、flow 状态和 callback 路由。
5. 设置页增加精简 MCP 卡片。点击授权时先同步打开空白窗口，再把后端返回的 `authorization_url` 导航到该窗口；弹窗失败时显示普通链接。
6. 授权完成后复用现有 Token 存储和 MCP reconnect，不增加第二套 Token 或连接管理。

## 安全边界

- MCP 列表、启动授权和状态查询要求本地 Companion session。
- OAuth callback 不依赖跨站 Cookie，但必须校验一次性 `state`、server 和 flow 有效期。
- 前端和 API 不返回 Token、client secret 或内部异常详情。
- 后台启动不主动打开浏览器；只有明确的用户点击可以启动网页授权。

## 验收

以 [MCP_INSTALL_OAUTH_TEST_CASES.md](./MCP_INSTALL_OAUTH_TEST_CASES.md) 中 MCP-01 至 MCP-04 为准，并运行相关 pytest 回归测试。
