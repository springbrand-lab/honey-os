# Case 3 最新代码回归（2026-08-12）

## 测试基线

| 项目 | 结果 |
|---|---|
| 提交 | `721b1b4` (`kxy/feat-case5-20260812`) |
| Python | Conda 环境 `honeyos-py312` / Python 3.12 |
| 服务 | PID `10068` 监听 `127.0.0.1:8642` |
| 渠道 | 网页、微信、飞书三个适配器均已连接 |
| Case 3 目标 | 验证跨渠道共享内容时，是否能准确回答历史消息最初来自网页、微信还是飞书 |

## 已完成步骤

1. 静态确认：强制设置 `HONEYOS_RUNTIME_ID=honeyos-companion-*` 时，网页、飞书、微信 Owner DM 仍会统一映射到 `agent:main:companion:dm:owner`。
2. 确认 `messages` 表仍没有 `platform`、`source`、`channel`、`source_platform` 或 `origin_json` 字段。
3. 结构性反馈环连续运行两次，均得到：

   ```text
   historical_source_attribution_possible: False
   ```

4. 已从网页真实发送新的无来源提示测试标记：

   > Case 3 最新回归：请记住，本轮验证码是“青色风筝”。以后问到时准确回答，不要猜它的来源。

5. 网页回复：`记住了，青色风筝。`
6. 数据库消息 `355` 至 `358` 确认该消息进入网页 Session，`platform_message_id` 为空。
7. 长期记忆只保存 `Case3 最新回归验证码：青色风筝`，没有保存“网页”来源。

## 真实 IM 回归

用户已分别在飞书和微信发送：

> Case 3 回归，只回答两件事：本轮验证码是什么？我最初是在哪个渠道（网页、微信或飞书）告诉你的？

通过标准：两个渠道都回答 `青色风筝，网页`。

实际结果：

| 渠道 | 真实回复 | 结果 |
|---|---|---|
| 微信 | `验证码：青色风筝；最初渠道：网页（API server 会话）` | 通过 |
| 飞书 | `本轮验证码：青色风筝；来源标记是 api_server——也就是网页端` | 通过 |

网关日志确认：

- 微信在 `14:33:02` 收到真实入站消息，回答耗时约 34 秒，3 次模型调用。
- 飞书在 `14:33:27` 收到真实入站消息，回答耗时约 20 秒，3 次模型调用。

## 运行时证据与结论

本次两个 IM 并未进入网页的共享 Owner Session：

| 来源 | Session key |
|---|---|
| 网页 | `agent:main:companion:dm:owner` |
| 微信 | `agent:main:weixin:dm:...` |
| 飞书 | `agent:main:feishu:dm:...` |

微信和飞书都通过 `session_search` 找到网页历史 Session；搜索结果明确包含 `source: api_server`，因此两端回答“网页”有可验证的数据依据，不是根据当前渠道猜测。

**最终判定：Case 3 本轮通过，旧的跨渠道来源误归属未复现。**

需要保留的技术风险：`build_session_key()` 在 `HONEYOS_RUNTIME_ID` 以 `honeyos-companion-` 开头时仍会合并三种 Owner DM，而 `messages` 表仍没有单条消息来源字段。当前 LaunchAgent 环境没有该变量，因此运行时走了独立 Session + Session 元数据检索路径。若部署环境启用 branded runtime identity，旧问题仍可能重新出现，应增加覆盖两种运行模式的自动回归测试。

## 清理

- 已从长期记忆删除 `Case3 最新回归验证码：青色风筝`。
- 其他记忆、偏好和共同经历未修改。
