# HoneyOS Builder：自我改造与回滚

本文是 HoneyOS Builder 的研发入口。当前实现刻意保持简单：**用文件夹边界限制能改什么，用两个版本槽和健康检查解决改坏后的恢复问题。**

## 什么时候使用 Builder

只有用户明确要求修改 HoneyOS 产品本身时才召回内置 `honeyos-builder` Skill，例如修改聊天页面、伴侣活动文案、普通内置伴侣 Skill，或在稳定扩展目录中增加功能。

下列请求不进入 Builder：

- 安装普通 Skill：安装完成后立即进入 Skill 索引，不重启 HoneyOS。
- 写游戏、网页或其他用户项目：直接写入 `~/HoneyOS Projects`。
- 修改人格、昵称、关系和记忆内容：写入用户数据链路。
- 切换模型或语音：使用对应配置工具，不修改产品源码。

## 文件夹边界

候选工作区是从固定 Git 版本复制出的**部分工作区**，没有 `.git`，也不会包含当前用户的 `~/.honeyos` 数据。

允许进入候选工作区的范围：

```text
honeyos/companion/web_assets/**
honeyos/companion/activity.py
honeyos/companion/status_copy.py
honeyos/companion/topic_scout.py
honeyos/companion/extensions/**
honeyos/companion/companion_skills/**
```

其中 Builder 与 self-extension 自身仍受保护。未列出的路径默认不可见、不可创建、不可启用。

绝对保护层包括：

- 记忆数据库、记忆删除和迁移、用户画像与话题投递；
- 模型配置、API Key、微信/飞书凭据、渠道配对；
- 网关、权限、命令执行和文件访问边界；
- Builder、版本切换、更新、安装和回滚实现自身；
- 服务定义、依赖锁、发布脚本和当前运行目录；
- `~/.honeyos` 下的身份、关系、聊天、记忆和配置数据。

代码中的权威边界位于 `honeyos/companion/builder_workspace.py` 的 `DEFAULT_ACTIVATABLE_PATHS` 与 `DEFAULT_PROTECTED_PATHS`。文档不能扩大该边界。

## 用户与运行流程

```text
用户提出产品改造
  → prepare 创建部分候选工作区
  → AI 只修改候选文件
  → inspect 检查范围和候选摘要
  → 静态 preflight
  → 伴侣说明改动并询问“我改好了，现在换上吗？”
  → 用户明确同意
  → 生成完整只读版本槽
  → 原子切换 current 指针
  → 重写服务定义并重启
  → /health + 运行源码版本证明
      ├─ 成功：标记 healthy
      └─ 失败：恢复 previous 指针并重启旧版本
```

确认使用普通对话确认，不存在独立 token、GitHub PR、飞书专用授权或隐藏回调系统。状态采用 CAS 更新，重复确认不会再次切换同一候选。

## CLI

```bash
honeyos builder prepare --source <源码目录> --goal <目标> \
  --allow 'honeyos/companion/web_assets/**' --change-id <短ID>
honeyos builder inspect <短ID>
honeyos builder status
honeyos builder activate <短ID>
```

`activate` 只能在用户对本次改造明确同意后调用。目前自动切换支持 macOS 和 Linux；Windows 会明确拒绝，不会误用 Linux 服务命令。

## 版本与数据

- 完整候选代码保存在 `~/.honeyos/runtime/slots/`。
- `current.json` 指向当前版本，`previous.json` 保存上一版本。
- 切换日志用于恢复中途崩溃；恢复时优先回到旧指针并标记 `recovery_required`。
- 服务的 `HONEYOS_HOME` 不变，因此换版和回滚不会复制、覆盖或删除用户记忆、配置和凭据。
- 健康检查不仅判断服务管理器显示“运行中”，还要求本地 `/health` 成功，并验证运行进程实际从当前版本槽加载代码。

## 关键验证

重点测试文件：

```text
tests/honeyos/test_builder_workspace.py
tests/honeyos/test_builder_preflight.py
tests/honeyos/test_builder_activation.py
tests/honeyos/test_builder_cli.py
tests/honeyos/test_service_identity.py
tests/honeyos/test_skill_installation_contract.py
```

发布前至少验证：保护路径不进入候选目录、普通 Skill 和项目 Coding 不触发换版、公共 Builder 命令不初始化或改写用户数据、新版本确实被服务加载、异常与崩溃能够回滚，以及用户数据在切换前后字节不变。
