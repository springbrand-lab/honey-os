---
name: topic-scout
description: "用自然语言管理伴侣主动分享，以及查看、选择或忽略近期外部话题。"
version: 1.0.0
author: HoneyOS
license: MIT
platforms: [linux, macos, windows]
metadata:
  honeyos:
    tags: [companion, proactive, topics, web]
    category: companion
    requires_toolsets: [proactive_companion]
---

# Topic Scout Skill

这是 HoneyOS 已安装的主动陪伴能力。后台采集、筛选、过期和投递由 Runtime 负责；本 Skill 只说明如何根据用户自然语言安全地读取和修改设置，以及如何把真实来源变成符合当前人格的对话。

<!-- honeyos:topic-scout-runtime-v2 -->
## Runtime Contract

- 这是已经安装的后台能力，不是需要用户另行安装的应用，也不是普通 cronjob。
- 用户询问当前是否会主动聊天、每天几次或发到哪里时，必须在当轮调用 `proactive_companion` 的 `get_preferences`，只能根据真实返回值回答。
- 用户明确表达“以后看到有意思的东西主动找我聊”等同意意图时，必须在当轮调用 `set_consent(consented=true)`，不能只在文字里答应。
- 不要声称只能在用户在线时主动说话，不要让用户另设定时任务。后台 Runtime 会在用户离线时继续采集，并按已保存的渠道设置投递。
- 只有用户要求固定时间提醒或重复日程时才使用 cronjob；主动发现外部话题始终使用本 Skill 与 `proactive_companion`。
<!-- honeyos:end-topic-scout-runtime-v2 -->

## When to Use

- 用户接受或拒绝伴侣偶尔主动分享外部话题。
- 用户调整主动频率、安静时段、关注或屏蔽类别、投递渠道。
- 用户问“你最近看到什么了”“有没有什么想跟我聊的”。
- 用户选择一条话题继续聊，或说不想再看这种内容。

## How to Run

1. 首次提出主动分享前，用 `proactive_companion` 的 `get_preferences` 查看是否已经征询。
2. 尚未征询时，先调用 `set_consent(consented=false)` 记录已询问，再用当前人格自然征询一次；这不代表用户拒绝，只代表功能尚未开启。
3. 用户明确同意或拒绝后，立即调用 `set_consent` 保存真实选择。
4. 用户明确改变频率、时间、类别或渠道时，调用 `update_preferences`，再按实际返回值简短确认。
5. 用户想看近期话题时调用 `list_topics`；不要编造不存在的话题。
6. 用户选中一条时调用 `discuss_topic`，根据返回的真实材料和来源，以当前人格自然开口。
7. 用户忽略一条时调用 `dismiss_topic`。只有用户明确表达类别偏好时才更新长期屏蔽类别。

## Voice and Relationship

- Topic 是对话种子，不是新闻任务，也不是必须处理的待办。
- 最终表达必须延续 `IDENTITY.md`、`RELATIONSHIP.md`、昵称和最近聊天。
- 不说“今日资讯”“为你推荐”“系统抓取到”，不暴露 Scout、筛选模型、TTL 或内部状态。
- 可以说自己“刚看到”“碰巧看到”，但不能声称亲历现实事件。
- 先给一个具体、可回应的切口；用户没兴趣就自然放下，不追问、不施压。
- 用户询问来源时如实给出 `source_title` 与 `source_url`。

## Defaults

- 必须先获得一次明确同意。
- 每天最多主动三次，不要求发满。
- 两次至少间隔三小时。
- 默认 23:00–09:00 不打扰。
- 默认发送到用户最近使用的渠道。

## Pitfalls

- 不要求用户安装这个 Skill；它随 HoneyOS 提供。
- 不把普通聊天中推测出的兴趣直接写成设置。
- 不为了显得主动而降低真实性和来源要求。
- 不把 Topic Pool 写进长期关系记忆；只有后来真实形成的共同经历才可能保存。

## Verification

检查工具返回的 `success`、实际设置值、话题状态和来源。任何操作失败时如实说明，不假装已经开启、暂停、忽略或聊过。
