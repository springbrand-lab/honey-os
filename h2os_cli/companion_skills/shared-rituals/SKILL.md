---
name: shared-rituals
description: "建立双方同意的问候、提醒、纪念日与陪伴仪式。"
version: 1.0.0
author: HoneyOS
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [companion, rituals, reminders, cron]
    category: companion
    requires_toolsets: [cronjob]
---

# Shared Rituals Skill

把双方认可的陪伴方式变成可持续的共同仪式。它用于真实提醒和跟进，不用于无许可地频繁打扰用户。

## When to Use

- 用户要求在未来某个时间提醒、问候或跟进。
- 用户想建立早安、晚安、复盘、纪念日等固定仪式。
- 伴侣提出一个新的主动陪伴习惯，等待用户同意后落地。

## Prerequisites

需要 `cronjob`。发送目标沿用当前会话来源。

## How to Run

1. 提取时间、时区、频率、内容和结束条件。
2. 用户明确要求的提醒直接创建，无需再确认一次。
3. 由伴侣主动提出的重复仪式，首次创建前征得一次同意。
4. 用 `cronjob` 创建任务，并检查返回的时间和投递目标。
5. 将稳定的共同仪式更新到 `RELATIONSHIP.md`。

## Quick Reference

- 一次性提醒：使用明确时间戳。
- 重复习惯：使用 `every` 表达或 cron 表达式。
- 当前任务步骤：使用 `todo`，不要用 cronjob。
- Apple 系统提醒事项：使用 `apple-reminders`，不要与聊天提醒混淆。

## Procedure

- 时区不清楚且会改变触发时刻时，先问一个简短问题。
- 创建后用自然语言复述“什么时候、提醒什么”。
- 用户要求暂停、修改或取消时，直接操作对应任务。
- 提醒内容应延续关系语气，但不得借提醒施加内疚或依赖压力。

## Pitfalls

- 不创建用户未同意的高频消息。
- 不用 cronjob 代替当前对话内马上能完成的事情。
- 不承诺已经安排，除非工具返回成功。

## Verification

检查任务状态、下一次触发时间、时区和投递来源与用户要求一致。
