---
name: honeyos-builder
description: "把用户对 HoneyOS 产品外观和陪伴行为的改进做成独立候选版本；检查通过后自动换上，失败会自动换回。"
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

用于用户明确希望改变 HoneyOS 产品本身的页面、陪伴表达或可扩展功能。用户提出改造本身就授权完成这次安全换版：在单独的候选工作区完成改动并检查通过后，直接替换正在使用的版本；如果新版本没能正常启动，会自动恢复旧版本。

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
- 检查通过后直接执行 `activate`，不要再次询问用户是否换上，也不要把同一次改造拆成多次授权。
- 成功后用关系化语言告诉用户已经换好；失败时如实说已经自动换回原来的版本，聊天和记忆不受影响。
- 用户验收后说不满意时，直接按反馈继续做新候选；新版本启动或健康检查失败时由 Builder 自动换回旧版本。

## 操作步骤

1. 找到真实的本地 HoneyOS Git checkout，并准备最小修改范围。终端始终以 `HoneyOS Projects` 为工作目录；不要进入源码目录，也不要把终端 `workdir` 设为源码目录。源码只作为 `--source` 参数交给受信任的 Builder：

   `honeyos builder prepare --source <本地源码目录> --goal <用户目标> --allow '<允许的路径或 glob>' --change-id <短ID>`

2. 只编辑命令返回的 `workspace`，绝不编辑当前运行 checkout。
3. 用合成数据做必要验证；不把用户记忆、凭据或聊天记录复制进候选目录。
4. 检查范围：

   `honeyos builder inspect <短ID>`

5. 如果结果不是 `review_ready`，先修正超范围或受保护改动，不能要求用户绕过边界。
6. 结果可用时，直接执行：

   `honeyos builder activate <短ID>`

   不需要再次征求确认。这会重新做静态检查，保留当前版本指针，切换并重启；最长等待 30 秒检查新版本。检查失败会自动换回旧版本。

## 前端改造

- 修改 `honeyos/companion/web_assets/**` 前，必须完整读取 `references/frontend.md`，再检查候选工作区里的实际文件；不能凭记忆猜页面结构。
- 浏览器工具可用时，可以用它辅助查看当前页面或候选页面；浏览器工具不可用不阻塞改造。
- 无论是否有浏览器，都必须运行参考文档列出的静态检查和前端自动化测试。
- 检查完成后直接运行 `activate`，再请用户实际验收；不能声称视觉效果已经由模型验证。

## 完成时

说明改善了什么、哪些资料仍保持原样，以及是否已成功换上。不要在没有实际命令证据时说已经启用，也不要把 `review_ready` 说成已启用。
