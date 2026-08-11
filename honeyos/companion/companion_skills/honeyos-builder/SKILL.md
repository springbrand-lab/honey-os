---
name: honeyos-builder
description: "把用户对 HoneyOS 产品外观和陪伴行为的改进做成独立候选版本；用户确认后安全换上，失败会自动换回。"
version: 0.2.0
author: HoneyOS
license: MIT
platforms: [linux, macos]
metadata:
  honeyos:
    tags: [honeyos, builder, self-improvement]
    category: companion
    requires_toolsets: [terminal, file]
---

# HoneyOS Builder

用于用户明确希望改变 HoneyOS 产品本身的页面、陪伴表达或可扩展功能。它在单独的候选工作区完成改动，用户说可以后才替换正在使用的版本；如果新版本没能正常启动，会自动恢复旧版本。

当前自动换版只支持 macOS 和 Linux；Windows 上不要尝试启用候选版本。

## 先判断是不是 Builder

以下情况**不要**用 Builder：

- 普通 Skill：直接安装，装好立即可用，不需要重启 HoneyOS。
- 用户项目：在 HoneyOS Projects 里直接写代码、创建文件和运行项目。
- 人格、昵称、关系、记忆内容、模型或语音：使用各自已有的资料或配置链路，不改产品源码。

只有用户明确要改 HoneyOS 产品的界面、陪伴活动文案、普通伴侣 Skill 或已提供的扩展点时，才使用 Builder。

## 可修改范围

候选工作区只会含有下面的文件；工作区中没有的文件一律不要尝试创建或修改：

- `honeyos/companion/web_assets/**`
- `honeyos/companion/activity.py`
- `honeyos/companion/status_copy.py`
- `honeyos/companion/topic_scout.py`
- `honeyos/companion/extensions/**`
- `honeyos/companion/companion_skills/**`（Builder 和 self-extension 自身除外）

不要碰记忆数据库/迁移/删除、人格模板、模型与密钥配置、渠道与配对、服务启动、更新安装、审批、安全策略或 Builder 自身。

## 用户体验

- 用伴侣当前的人设和对用户的称呼解释，不播报 terminal、patch、pytest 等内部动作。
- 开始时说会先在不影响当前聊天的副本里试着准备。
- 检查完成后，清楚说明改了什么、哪些不会动，然后自然地问：
  “我改好了，现在换上吗？”
- **在用户明确回答“可以”“换上”“启用”等肯定答复前，绝不运行 activate。**
- 成功后用关系化语言告诉用户已经换好；失败时如实说已经自动换回原来的版本，聊天和记忆不受影响。

## 操作步骤

1. 找到真实的本地 HoneyOS Git checkout，并准备最小修改范围：

   `honeyos builder prepare --source <本地源码目录> --goal <用户目标> --allow '<允许的路径或 glob>' --change-id <短ID>`

2. 只编辑命令返回的 `workspace`，绝不编辑当前运行 checkout。
3. 用合成数据做必要验证；不把用户记忆、凭据或聊天记录复制进候选目录。
4. 检查范围：

   `honeyos builder inspect <短ID>`

5. 如果结果不是 `review_ready`，先修正超范围或受保护改动，不能要求用户绕过边界。
6. 结果可用时，向用户说明并问“我改好了，现在换上吗？”。
7. 收到本次请求的明确肯定答复后才执行：

   `honeyos builder activate <短ID>`

   这会重新做静态检查，保留当前版本指针，切换并重启；最长等待 30 秒检查新版本。检查失败会自动换回旧版本。

## 完成时

说明改善了什么、哪些资料仍保持原样，以及是否已成功换上。不要在没有实际命令证据时说已经启用，也不要把 `review_ready` 说成已启用。
