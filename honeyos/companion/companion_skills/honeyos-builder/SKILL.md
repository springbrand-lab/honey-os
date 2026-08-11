---
name: honeyos-builder
description: "把用户对 HoneyOS 产品本身的改进需求做成隔离、可检查、仅供评审的候选版本。"
version: 0.1.0
author: HoneyOS
license: MIT
platforms: [linux, macos, windows]
metadata:
  honeyos:
    tags: [honeyos, builder, self-improvement, review]
    category: companion
    requires_toolsets: [terminal, file]
---

# HoneyOS Builder

用于用户明确要求修改 HoneyOS 产品本身的场景。它把需求转交给隔离的候选源码副本，不直接编辑当前运行版本，不自动安装、重启或合并。

## When to Use

- 用户要求调整记忆提取、召回、Session 或 `/new` 逻辑。
- 用户要求修改 Web 对话页、飞书或微信适配、工具状态展示。
- 用户要求增加 Agent Runtime 模块、MCP 接入、模型路由或数据结构。
- 这是产品级改造；普通人格、关系、记忆内容调整仍走专用资料与记忆工具，独立能力优先做普通 Skill。

## User Experience

- 先用人格化语言回应需求，不播报 terminal、patch、pytest 等内部动作。
- 明确告诉用户：会在不会影响当前聊天的安全副本中准备新版本。
- 当前聊天继续可用；只汇报“梳理逻辑、准备候选版本、检查影响、等待确认”等用户可理解的状态。
- 技术细节按需提供，不能谎称候选版本已经启用。

## Hard Boundaries

- 不能直接修改正在运行的 HoneyOS，也不能把 live checkout 当作工作区。
- 不读取真实用户记忆、聊天数据库、Token、Cookie、账号凭证或内部消息密钥。
- 不修改 Builder、审批、安全策略、目录边界、认证和威胁检测文件。
- 不扩大自己的文件、网络或账号权限。
- 第一版只生成候选改动、测试结果和评审报告；不自动安装、不自动重启、不自动推送或合并。

## Procedure

1. 先判断需求属于人格塑造、普通 Skill，还是产品级改造。只有第三类进入 Builder。
2. 把需求整理成用户结果、允许改动范围、明确不变项和验证标准。
3. 找到真实的本地 HoneyOS Git checkout，并用 `git rev-parse --show-toplevel` 验证；没有本地源码时如实说明需要先取得源码副本。
4. 为本次改造生成稳定的短 ID，然后准备独立候选版本：

   `honeyos builder prepare --source <真实源码目录> --goal <用户目标> --allow '<仓库相对路径或 glob>' --change-id <id>`

   每个额外允许范围都重复一个 `--allow`。只授予完成需求必要的最小路径，不使用 `/`、`..` 或电脑目录。
5. 只在命令返回的 `workspace` 中修改代码。保持当前运行 checkout 原样。
6. 使用合成测试数据完成针对性测试和相关回归，不复制真实伴侣记忆进入候选目录。
7. 检查最终范围：

   `honeyos builder inspect <id>`

8. `blocked` 表示触碰了受保护文件或超出允许范围：撤销这些候选改动后重新检查，不能要求用户绕过。
9. `review_ready` 只表示可以交给人工开发评审，不表示可安装。向用户展示目标、改动范围、测试结果、风险和当前版本未受影响。

## Completion Contract

完成时用产品语言说明：

- 改善了什么；
- 哪些内容保持不变；
- 测试是否通过；
- 是否存在阻塞项；
- 候选版本仍未启用，下一步是人工评审和 PR。

不要把代码 diff 当作唯一结果，也不要在没有实际命令和测试证据时声称已经完成。
