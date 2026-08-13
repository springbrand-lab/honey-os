# HoneyOS 第三方 MCP 安装与 OAuth 测试用例

## 测试范围

本次测试验证的是：**HoneyOS 作为 MCP Client，在对话中安装、授权并使用第三方 MCP Server**。

不测试 `honeyos mcp serve`，也不测试“把 HoneyOS 作为 MCP Server 安装到 Claude Desktop、Codex 等其他客户端”。

当前故障链路：用户在对话中要求安装第三方 MCP → 配置可能已写入 → 正式安装缺少 MCP SDK，或后台发现流程遇到 OAuth → 后台不会打开授权页 → Companion 网页也没有授权入口 → MCP 无法使用。

## 测试准备

- 使用官方安装脚本创建全新 HoneyOS 环境。
- 准备两个可控测试服务：
  - `plain-mcp`：不需要认证，提供 `ping` 工具。
  - `oauth-mcp`：需要 OAuth，授权成功后提供 `whoami` 工具。
- OAuth 回调和授权状态必须由 Companion 网页所在的同源服务承接；测试不依赖单独启动 Dashboard。

## MCP-01 正式安装包含 MCP 能力

**步骤**

1. 执行官方安装脚本。
2. 在安装生成的虚拟环境中执行：

   ```bash
   python -c "import mcp; from mcp.client.streamable_http import streamablehttp_client; print('ok')"
   honeyos mcp --help
   ```

**期望结果**

- Python 输出 `ok`。
- `honeyos mcp --help` 成功，并包含 `add`、`login`、`test`。
- 不出现 `mcp.client.streamable_http is not available`。

**修复前结果**：失败；官方安装未安装 `mcp` extra，公开 CLI 也未暴露 `mcp`。

## MCP-02 对话安装无认证 MCP

**步骤**

1. 在 HoneyOS 对话中要求安装 `plain-mcp`。
2. 等待安装和工具发现完成。
3. 在对话中要求调用 `plain-mcp` 的 `ping`。

**期望结果**

- HoneyOS 保存 MCP 配置并报告连接成功。
- `ping` 出现在可用工具中并能返回测试值。
- 整个过程不要求 OAuth，也不要求用户执行底层 Python 命令。

**修复前结果**：失败；正式环境缺少 MCP SDK 时，HTTP MCP 无法连接。

## MCP-03 对话安装并授权 OAuth MCP

**步骤**

1. 在 HoneyOS 对话中要求安装 `oauth-mcp`。
2. 打开 Companion 网页的 MCP 状态或设置区域。
3. 点击“授权”。
4. 在打开的授权页完成确认，返回 HoneyOS。
5. 等待状态变为“已连接”，然后在对话中调用 `whoami`。

**期望结果**

- 后台发现流程不会自行弹浏览器，也不会长时间阻塞；网页显示“需要授权”。
- 点击“授权”后立即打开窗口；拿到 `authorization_url` 后在该窗口跳转。
- 如果浏览器拦截弹窗，页面提供可点击的授权链接。
- OAuth callback 校验成功，状态由 `authorization_required` 变为 `approved`。
- Token 被保存，`whoami` 可被发现并调用。
- 不要求额外启动 9119 Dashboard。

**修复前结果**：失败；Companion 服务没有 MCP OAuth 路由，网页也没有授权按钮和状态轮询。

## MCP-04 重启后复用授权

**步骤**

1. 在 MCP-03 成功后重启 HoneyOS。
2. 再次调用 `oauth-mcp` 的 `whoami`。
3. 使测试 Token 失效，再次重启或触发工具发现。

**期望结果**

- Token 有效时不再次弹窗，MCP 工具可直接使用。
- Token 失效时后台不尝试弹浏览器；网页显示“需要重新授权”。
- 用户可从网页重新授权，且其他聊天和 MCP 不受影响。

## 通过标准

四个用例全部通过，才说明 HoneyOS 已具备“在对话中安装并使用第三方 MCP，包括 OAuth MCP”的完整能力。
