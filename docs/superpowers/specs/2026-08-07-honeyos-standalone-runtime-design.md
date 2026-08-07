# HoneyOS 独立运行时设计

日期：2026-08-07
状态：待产品确认

## 1. 目标

把当前“完整 Hermes 仓库 + Honey OS 产品层”的结构收缩为单一的 HoneyOS 产品和运行时。普通用户下载源码 ZIP、安装、查看后台服务、执行管理命令或阅读日志时，只会接触 HoneyOS，不会安装、启动或误操作本机已有的 Hermes。

本次工作同时解决两个问题：

1. 删除 HoneyOS 不使用的上游应用、网站、文档、平台、工具和 Skill 源码，缩小用户安装包。
2. 将 HoneyOS 确实依赖的 Agent、gateway、工具、记忆与调度代码迁入 HoneyOS 命名空间，移除 Hermes 的命令、包名、服务名和运行时环境变量。

## 2. 不可破坏的能力

源码收缩后必须保留当前伴侣产品能力：

- OpenAI Chat Completions 兼容模型配置与真实请求验证。
- 微信 iLink 扫码、扫码用户自动绑定、私聊单用户限制。
- 飞书机器人连接、首次私聊配对和 WebSocket 消息收发。
- 伴侣 system prompt、用户人设优先、关系连续性和 `/new` 长期记忆继承。
- 工具执行后的伴侣人格交接 Hook。
- 网页搜索与浏览、文件读写、隔离代码执行和 Computer Use。
- Skill 列表、安装、运行及 HoneyOS 自我扩展。
- 待办、定时任务、会话搜索和长期记忆蒸馏。
- 后台启动、停止、重启、状态、日志和安装诊断。

## 3. 对外命名契约

所有新安装统一使用以下名称：

| 对象 | 新名称 |
| --- | --- |
| 产品显示名 | HoneyOS |
| 命令 | `honeyos` |
| Python distribution | `honeyos` |
| Python 顶层包 | `honeyos` |
| 数据目录 | `~/.honeyos` |
| macOS LaunchAgent | `ai.honeyos.gateway` |
| Linux systemd unit | `honeyos-gateway.service` |
| PID、锁与日志 | 仅位于 `~/.honeyos` |
| 用户 ZIP | `honeyos-<version>.zip` |

不得继续注册 `hermes`、`hermes-agent`、`h2os` 或 `honey-os` 命令。不得创建或控制 `ai.hermes.*`、`hermes-gateway*`、`ai.springbrand.h2os` 或 `h2os-gateway` 服务。

## 4. 目标架构

仓库只保留一个可安装项目。现有 `h2os_cli`、被 HoneyOS 使用的 `agent`、`gateway`、`tools`、`cron` 及必要 provider/platform 代码，按职责迁入 `honeyos` 包：

```text
honeyos/
  cli/          # setup、doctor、start/stop/status/logs、迁移
  companion/    # system prompt、人设、关系、连续性、记忆蒸馏
  agent/        # 对话循环、模型请求、工具循环
  gateway/      # 私聊消息路由与后台生命周期
  platforms/    # 仅微信与飞书
  tools/        # 仅伴侣允许的基础工具
  skills/       # HoneyOS 内置 Skill 与普通 Skill runtime
  scheduler/    # todo 与 cron
```

模块之间只能使用 `honeyos.*` 导入。运行命令必须是当前安装环境中的绝对 Python 路径加 `-m honeyos`，不得通过 PATH 查找其他 Agent 程序。

## 5. 源码删除边界

### 5.1 直接删除

- 上游桌面端、Web UI、官网、演示、数据生成和研究资料。
- Docker、Nix、Termux、Windows 专属安装与本次 macOS/Linux 内测无关的交付代码。
- HoneyOS 不支持的平台适配器及其配置流程。
- 未进入 HoneyOS 工具白名单的工作型 Agent 能力、Kanban、委派、多 Agent 和无关 MCP。
- 未进入 HoneyOS 精选集合的上游 Skill、可选 Skill 和插件。
- 上游 CLI、认证、计费、皮肤、成就、Nous Portal 等产品功能。
- 上游测试、截图与构建脚本中不再覆盖目标运行时的部分。

### 5.2 迁移后删除原路径

- `h2os_cli`：迁移为 `honeyos.cli` 和 `honeyos.companion`。
- `hermes_cli`：仅抽取实际需要的后台生命周期、配置、配对和日志逻辑到 `honeyos`；随后删除整个原目录。
- `agent`、`gateway`、`tools`、`cron`：按运行时依赖抽取到 `honeyos`，替换导入后删除原路径。
- 根目录所有 `hermes_*` 模块：抽取仍使用的常量、状态和日志逻辑并改名，随后删除。

### 5.3 合规保留

根目录保留 MIT `LICENSE`，并新增精简的 `NOTICE`，说明 HoneyOS 基于 Nous Research 开源项目演化而来。原项目名称只允许出现在许可证、版权和来源声明中，不得进入程序入口、服务、数据路径、日志前缀或用户交互。

## 6. 旧数据迁移

首次执行 `honeyos setup`、`honeyos start` 或任何管理命令时，按以下顺序处理：

1. 若 `~/.honeyos` 已存在，直接使用，不覆盖。
2. 若 `~/.honeyos` 不存在且 `~/.h2os` 存在，停止旧 `ai.springbrand.h2os` / `h2os-gateway` 服务。
3. 将 `~/.h2os` 原子复制到临时目录，升级配置中的绝对路径和旧运行时标识。
4. 校验配置、记忆数据库、会话数据库和 IM 凭据可读后，将临时目录改名为 `~/.honeyos`。
5. 将原目录改名为带时间戳的 `~/.h2os.backup-<timestamp>`，不主动删除。
6. 注册并启动新的 HoneyOS 服务。

迁移器不得读取、复制、停止或修改 `~/.hermes` 以及任何 `ai.hermes.*` / `hermes-gateway*` 服务。检测到本机 Hermes 时只记录“已隔离，不受影响”的诊断结果。

如果迁移中任一步失败，新服务不得启动；临时目录应清理，旧数据和旧服务保持可恢复状态，并向用户给出明确的恢复说明。

## 7. 安装与发行

GitHub `main` 本身必须能生成干净的用户 ZIP。根目录只提供：

- `README.md`
- `Install-HoneyOS.command`
- `scripts/install_honeyos.sh`
- `pyproject.toml` 与锁文件
- `honeyos/` 运行时
- 必需测试、许可证和版本信息

安装器使用仓库内环境，不复用全局 Python 包或现有 Agent 虚拟环境。安装完成后只生成 `honeyos` 命令，并只注册一个 HoneyOS 后台服务。

升级 ZIP 覆盖代码后重新运行安装器，不得覆盖 `~/.honeyos` 的人设、关系记忆、会话、Skill、待办、定时任务和 IM 凭据。

## 8. 安全与冲突处理

- 安装前检测旧 H2OS 服务并进入迁移流程。
- 检测 Hermes 仅用于证明隔离，不以任何方式接管它。
- 服务查找必须使用 HoneyOS 的精确 label/unit，不得通过包含 `gateway` 或 `hermes_cli.main` 的宽泛进程扫描操作其他进程。
- 后台 plist/unit 必须固定当前 HoneyOS 虚拟环境中的 Python 绝对路径、`~/.honeyos` 和仓库绝对路径。
- 配置和凭据文件权限维持仅当前用户可读写。

## 9. 验收标准

必须通过以下自动化和真实安装验证：

1. 全仓扫描：除 `LICENSE`、`NOTICE`、旧数据迁移模块及其兼容测试外，不存在大小写任意形式的 `hermes`、`h2os` 或 `springbrand`；迁移模块中的旧名称只能作为精确识别旧目录与旧服务的常量，不能成为新运行入口。
2. 全新 macOS 用户从 ZIP 双击安装，只看到 HoneyOS，且微信或飞书可以正常对话和使用工具。
3. 已有 `~/.h2os` 用户升级后，人设、关系、记忆、会话、Skill、待办、定时任务和 IM 连接继续可用，原目录有备份。
4. 同一台电脑预先运行 Hermes 时，安装、启动、重启和卸载 HoneyOS 均不改变 Hermes 的 PID、服务状态、配置或消息连接。
5. 安装后系统中只新增一个 HoneyOS 服务，不新增 Hermes 服务或命令。
6. 删除任何保留模块都会由导入测试、工具表面测试或真实启动测试捕获，避免“为了精简而丢能力”。
7. 原有 HoneyOS 伴侣人格、工具交接和长期记忆测试继续通过。

## 10. 交付方式

实现放在独立分支，通过一个 PR 展示：

- 删除了哪些上游目录。
- 哪些必要运行时代码迁入 `honeyos`。
- 旧数据迁移和双运行时隔离测试结果。
- 最终用户 ZIP 的文件清单与大小。

在 PR 验证完成前不合并到 `main`，也不再把当前完整源码 ZIP 发给体验用户。
