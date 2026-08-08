---
name: honeyos-self-extension
description: "检查真实能力，并按用户需要安全地安装或创建 Skill。"
version: 1.0.0
author: HoneyOS
license: MIT
platforms: [linux, macos, windows]
metadata:
  honeyos:
    tags: [honeyos, skills, capability, extension]
    category: companion
    requires_toolsets: [skills, terminal]
---

# HoneyOS Self Extension Skill

让 HoneyOS 在能力不足时先检查现状，再选择已有工具、安装普通 Skill 或创建小型 Skill。它扩展边缘能力，不改写核心 Runtime、安全边界或伴侣数据规则。

## When to Use

- 用户问“你能不能做某事”“给自己装个能力”。
- 当前任务缺少明确工具、流程或重复性知识。
- 用户提供外部 Skill 或 GitHub 仓库，希望检查并接入。

## Prerequisites

需要 `skills_list`、`skill_view`、`skill_marketplace`、`skill_manage`、`terminal`、`web_search` 和 `browser_navigate` 中与任务相关的工具。

## How to Run

1. 用 `skills_list` 和真实工具列表检查现有能力，不能凭印象回答。
2. `skills_list` 返回的都是已经安装的 Skill，直接读取和使用，不再询问是否安装。
3. 缺少流程知识时，用 `skill_marketplace(action="search")` 搜索未安装的 Skill，再用精确 identifier 安装；没有合适来源时创建最小 Skill。
4. 安装后读取 Skill，继续完成原任务，不停在“安装成功”。
5. 用实际工具结果验证能力，再向用户报告。

## Installed Skills and Marketplace

- `skills_list` 是当前已经安装并可直接召回的 Skill 清单。
- 只有 `skill_marketplace` 的搜索结果才是尚未安装的候选项。
- 安装成功后立即继续原任务，不再询问用户要不要把它接入 HoneyOS。

## Quick Reference

- 普通 Skill 查看、安装、创建、更新：无需额外确认。
- 外部仓库：先检查来源、文件和脚本，不直接运行未知安装脚本。
- 系统软件、远程脚本、账号、Cookie、API Key：先获得明确确认。
- 核心 Runtime、安全策略、公开网络服务、伴侣数据删除：禁止自行修改。

## Procedure

- 使用 `web_search` 或 `browser_navigate` 读取公开仓库和文档。
- 用户提供的仓库 URL 是来源身份。必须检查该仓库的 README、安装文档和包元数据，不能根据项目名猜测 PyPI、npm 或其他注册表中的同名包。
- 对 Python CLI，优先按仓库文档使用锁定版本的源码安装；需要在隔离容器中持久保留时使用用户级 `--user` 安装，让文件进入持久的用户目录，而不是临时容器系统目录。
- 通过 `skill_marketplace` 搜索和安装外部 Skill；通过 `skill_manage` 创建或维护本地 Skill，并保持说明简短、工具名真实。
- 依赖系统软件时告诉用户用途、来源和影响，等待确认。
- 新能力只在后续会话生效时明确说明，不谎称当前会话已加载。
- 安装完成后检查包主页或源码来源，并依次运行 `command -v`、`--help` 以及项目提供的 `doctor` 或状态命令。随后完成一个真实任务验证能力，并继续完成用户原本的任务。

## Source Identity and Verification

- 用户提供的仓库 URL 是来源身份；同名注册表包不能替代指定仓库。
- 安装前读取指定仓库的安装说明和包元数据，安装后核对项目主页或源码来源。
- 隔离环境中的 Python CLI 优先使用用户级 `--user` 安装，以保存在持久用户目录。
- 必须运行 `command -v`、`--help`、可用的 `doctor` 或状态命令，并完成一个真实任务。
- 验证成功后继续完成用户原本的任务，不停在“安装完成”或询问用户 AI 应该如何调用 CLI。

## Pitfalls

- 不说“只能从内置市场安装”；公开仓库可以先读取和评估。
- 不把 GitHub 项目直接等同于可安装 Skill。
- 不运行任意远程脚本，不保存秘密，不绕过隔离环境。
- 不把同名注册表包当成用户指定的 GitHub 项目；来源不一致时立即报告并停止使用错误包。
- 不为了扩展能力修改 HoneyOS 核心代码。

## Verification

确认 Skill 可被 `skills_list` 发现、可被 `skill_view` 完整读取，并用一个真实任务验证所需工具链。
