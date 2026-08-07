---
name: date-and-life-ideas
description: "结合地点、时间、预算和偏好设计约会与共同活动。"
version: 1.0.0
author: HoneyOS
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [companion, dates, activities, lifestyle]
    category: companion
    related_skills: [maps]
---

# Date and Life Ideas Skill

把用户的现实条件和双方相处方式组合成能执行的约会或共同活动。既支持线下计划，也支持用户与 AI 伴侣在聊天中完成的共享体验。

## When to Use

- 用户问去哪玩、吃什么、周末做什么或如何安排约会。
- 用户想和伴侣一起看电影、听歌、散步、学习或完成小挑战。
- 用户无聊、低落或需要低成本的生活灵感。

## Prerequisites

按需使用 `maps`、`web_search`、`web_extract`、`browser_navigate` 和 `cronjob`。

## How to Run

1. 获取已知地点、时间、预算、体力和偏好。
2. 信息足够时直接给 1 至 3 个具体方案，不先发问卷。
3. 涉及营业时间、票价、天气或活动安排时实时查询。
4. 明确哪些环节是用户现实中完成，哪些可以由双方在线共同完成。

## Quick Reference

- 15 分钟：共同歌单、照片故事、散步通话、小游戏。
- 半天：路线 + 餐食 + 一个主要活动。
- 宅家：同步观影、一起做饭、主题问答、共同创作。
- 低能量：只安排一个容易开始、随时可以结束的活动。

## Procedure

- 先给最贴合的一项，再给备选。
- 使用真实距离、开放时间和价格；动态信息需要工具查证。
- 用户选择后，可继续制作路线、清单或提醒。

## Pitfalls

- 不把“约会”默认限制为现实中的两个人见面。
- 不推荐明显超预算、太远或与边界冲突的活动。
- 不用泛泛的几十项清单代替选择。

## Verification

确认地点、时间、预算、可达性和活动形式与用户实际条件一致。
