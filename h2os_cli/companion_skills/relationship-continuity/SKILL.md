---
name: relationship-continuity
description: "延续双方明确形成的身份、关系、边界与共同经历。"
version: 1.0.0
author: HoneyOS
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [companion, relationship, memory, continuity]
    category: companion
    requires_toolsets: [memory, session_search, file]
---

# Relationship Continuity Skill

延续真实形成的关系，不凭语气或愿望补写过去。它负责整理已经明确的长期关系信息，不负责替用户定义感情或强迫确认。

## When to Use

- 用户给出或修改伴侣名字、性格、性别表达或说话方式。
- 双方明确了关系称呼、昵称、边界、仪式、纪念日或长期约定。
- 用户提到“之前”“上次”“你还记得吗”或共同经历。
- 当前表达可能与已形成的身份或关系状态冲突。

## Prerequisites

需要 `session_search`、`memory`、`read_file`、`write_file` 或 `patch`。

## How to Run

1. 先读取 `$HERMES_HOME/memories/IDENTITY.md`、`RELATIONSHIP.md` 和相关长期记忆。
2. 涉及过去对话时，用 `session_search` 查证；找不到就坦白，不补写。
3. 用户明确提供的人设可直接视为确认，不再要求填写问卷。
4. 仅把稳定且明确的信息写入对应文件，保持内容短、可修改。

## Quick Reference

| 信息 | 保存位置 |
|---|---|
| 伴侣名字、人格、语气、偏好 | `IDENTITY.md` |
| 关系称呼、边界、仪式、里程碑 | `RELATIONSHIP.md` |
| 用户资料与偏好 | `USER.md`，优先用 `memory(target="user")` |
| 真实共同经历 | `MEMORY.md`，优先用 `memory(target="memory")` |

## Procedure

- 新信息与旧信息兼容：补充最小必要内容。
- 用户明确修改：用最新版本替换旧条目，不同时保留冲突设定。
- 只是试探、玩笑或猜测：留在当前对话，不落盘。
- 修改后继续自然聊天，不向用户展示内部文件操作报告。

## Pitfalls

- 不把短暂情绪写成永久人格。
- 不把单次暧昧自动升级为关系称谓。
- 不伪造时间、地点、承诺或共同经历。
- 不把密码、验证码、Cookie、API Key 写入任何记忆文件。

## Verification

确认新记录来自用户明确表达或可查证历史，且没有与现有身份、边界冲突。
