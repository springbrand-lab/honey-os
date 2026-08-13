# HoneyOS Case 3、5、6 错误原因定位

范围：只分析 Case 3、5、6；本轮不修改产品代码。

## 结论总表

| Case | 主要错误 | 根因 | 置信度 |
|---|---|---|---|
| 3 | 飞书把微信中的改名归到飞书 | Web、飞书、微信私聊被有意合并到同一个 Owner Session，但消息表没有单条消息的 `platform/source/channel` 字段；模型回放历史时只看到文本，不知道每条历史消息来自哪里 | 高 |
| 5 | 工具失败却显示成功 | 执行器虽然识别到失败，却仍发送 `tool.completed`，仅附带 `is_error=true`；陪伴页事件转换没有传递这个标记，并把所有 `tool.completed` 固定映射为成功文案 | 高 |
| 5 | Skill 创建连续失败 | `content` 只写在参数说明中，没有在 JSON Schema 中按 `action=create` 设为结构化必填；模型收到明确错误后仍连续省略 `content`，而工具循环的硬停止默认关闭 | 高 |
| 5 | 搜索和网页提取失败 | 当前仅配置 `web.backend: ddgs`；DDGS 搜索本次 30 秒超时，并且 DDGS 本身是 search-only，不能承担网页提取 | 高 |
| 6 | 定时任务失败 15 次、耗时约 88.4 秒 | 首次调用有 `schedule` 但没有 `prompt`；模型收到错误后反而删除 `schedule` 并重复错误参数。Cron Schema 也只把 `action` 设为结构化必填；循环警告不会阻止继续调用 | 高 |
| 6 | 创建/暂停定时任务都显示“记下了” | `cronjob` 被静态归类到 `remembering`，因此创建、暂停和失败都复用记忆类文案；再叠加 Case 5 的失败状态丢失问题 | 高 |

## Case 3：跨渠道来源串线

### 数据链路

1. `build_session_key()` 明确把 HoneyOS 的 Web、飞书、微信 Owner DM 合并为同一个 `agent:main:companion:dm:owner` Session。这保证了跨渠道连续性。
2. `messages` 表只保存 `session_id`、文本和可选的 `platform_message_id`，没有 `platform/source/channel`。
3. `append_message()` 也没有接收消息来源字段；历史回放构造给模型的消息时同样不会补回渠道。
4. 实际数据库中，微信改名消息和飞书中的错误回答位于同一 Session；改名消息的 `platform_message_id` 也是空值。

因此，模型能知道“名字从小树改成小河”，却无法从历史数据判断“这次改名发生在微信”。当前轮系统提示只告诉模型当前正在飞书，所以模型把当前渠道误当成历史事件来源。

这不是名字记忆覆盖失败，而是历史消息来源信息在进入共享 Session 后丢失。

## Case 5：工具行动、审批和失败提示

### 失败被显示成成功

执行器在工具完成后已经计算出 `_is_error_result`，但无论成功失败都调用：

```text
tool_progress_callback("tool.completed", ..., is_error=_is_error_result)
```

陪伴页转换函数只把 `event_type/tool_name/args` 交给 `project_activity()`，没有传递 `is_error`。`project_activity()` 看到 `tool.completed` 就固定返回 `state=completed` 和成功文案。于是：

- 搜索超时仍显示“已经找到相关内容了”；
- Skill 参数校验失败仍显示“新能力已经整理好了”；
- 文件不存在仍显示“这个文件已经看过了”；
- Case 6 的 Cron 失败也同样误报成功。

这是一个共同的事件状态传递缺陷，不是四类工具分别出错。

### Skill 重复失败

数据库记录显示本轮共调用 `skill_manage` 10 次：

- 第 1 次带 `content`，但描述超过长度限制；
- 后续 8 次没有 `content`；
- 其中 6 次完全重复同一组错误参数；
- 第 10 次才重新带上 `content` 并成功。

工具返回已经明确写明 `content is required`。但 Schema 的结构化 `required` 只有 `action` 和 `name`，所以缺少 `content` 的 `create` 调用仍能通过模型侧参数校验并进入运行期。

同时，循环保护默认只警告：`hard_stop_enabled=False`。因此即使系统已检测到重复失败，也不会在第 5 或第 8 次真正阻止继续调用。

### 搜索失败

当前配置只有：

```yaml
web:
  backend: ddgs
```

本轮 DDGS 搜索触发其 30 秒超时。随后模型调用网页提取，但 `extract_backend` 没有单独配置，仍落到 DDGS；代码明确拒绝让 search-only 的 DDGS 执行网页提取。

### “没有最终回复”的复核修正

保存下来的 `case5_search.sse` 和 `case5_install.sse` 都包含：

```text
assistant.completed
run.completed
done
```

所以后端并没有漏发最终回复，现有证据不能把它定为服务端交付失败。若当时页面确实没显示，更可能是当时页面状态、连接观察时机或前端展示问题，需要单独用浏览器复现；当前前端代码本身已有 `assistant.completed` 的渲染分支。原报告中的“后端没有最终回复”应降级为未确认。

### 审批没有结构化卡

当时模型先用普通文本询问用户，获得同意后才调用复制命令。因此工具层从未收到一次“待审批的工具调用”，自然不会产生 `approval.request` 结构化事件。这是模型选择了会话式预确认路径，不是审批系统在收到待批工具后漏发卡片。

## Case 6：一句话配置电影记录和周末提醒

### 15 次 Cron 失败的真实顺序

数据库记录共有 16 次 `cronjob` 调用：

1. 第 1 次：有 `schedule="0 10 * * 6"`，但缺少 `prompt`，返回 `create requires either prompt or at least one skill`。
2. 第 2～15 次：模型没有补 `prompt`，反而把已经正确的 `schedule` 也删掉；其中参数 `{"action":"create","attach_to_session":true}` 完全重复 10 次，持续返回 `schedule is required for create`。
3. 第 16 次：同时提供 `schedule`、`prompt`、`name`，创建成功。

Cron 的文字说明已经明确说 `create` 需要 `schedule` 和 `prompt`，但 JSON Schema 的 `required` 仍只有 `action`，所以错误参数不能在调用前被结构化拦截。再加上硬停止默认关闭，模型可以忽略循环警告一直重试。

本轮 17 次模型调用由 1 次记忆调用和 16 次 Cron 调用构成；约 88.4 秒主要消耗在重复的模型往返，不是 Cron 创建动作本身慢。

### 状态文案错误

`activity.py` 把 `cronjob` 放在 `remembering` 分类中，完成文案固定为“已经替你记下了”。这个分类没有区分 `create/pause/resume/remove`，所以即使没有失败状态丢失，暂停提醒也仍会显示成“记下了”。

## 根因优先级

1. **P0：工具失败状态在执行层到陪伴页之间丢失。** 同时影响 Case 5 和 Case 6，造成用户被系统性误导。
2. **P0：共享跨渠道 Session 没有单条消息来源。** 直接导致 Case 3 无法可靠回答历史来源。
3. **P1：条件必填参数未编码进 Schema，重复失败硬停止默认关闭。** 导致 Case 5、6 的调用循环和高延迟。
4. **P1：Cron 行动语义被固定归入“记忆”。** 导致创建、暂停等动作状态不准确。
5. **P1：Web 提取后端未配置。** 搜索偶发超时后没有可用的官方页面抓取降级路径。
