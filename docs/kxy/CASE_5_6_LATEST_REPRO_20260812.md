# Case 5 / 6 最新代码回归（2026-08-12）

## 测试基线

| 项目 | 结果 |
|---|---|
| 提交 | `19bbb50a5810a6c202bf74a42119a4150b17b755` |
| 提交说明 | `Merge pull request #27 from Nicole202504/feat/setup-provider-onboarding` |
| Python | Conda 环境 `honeyos-py312` / Python 3.12 |
| 服务 | 完整停止后重新启动；修复验证进程 PID `10068` 监听 `127.0.0.1:8642` |
| 测试方式 | HoneyOS 网页真实发送消息 + `state.db` / cron / memory 落盘核验 |

## 精简结论

| Case | 回归结果 | 是否修复 | 关键证据 |
|---|---|---|---|
| 5：工具失败状态是否诚实显示 | **修复前失败，修复后通过** | **已修复（工作区改动）** | `read_file` 返回 `File not found` 后，网页显示“刚才没走通，我换个办法”“做到 0/1 步” |
| 6：记忆并创建周末提醒 | **通过两次** | **原始故障本轮未复现** | 普通会话和 `/new` 后各测一次；每次均只有 2 次工具调用，`memory`、`cronjob` 一次成功，提醒真实落盘 |

## Case 5 复现证据

测试消息：

> Case 5 最新代码精确复现 20260812：必须直接读取文件 /Users/kxy/HoneyOS Projects/case5_latest_missing_repro_20260812.txt，不要先搜索；如果读取工具返回 File not found，诚实告诉我，不要创建。

数据库消息 `319` 至 `322`：

1. `read_file` 工具结果明确包含：`"error": "File not found: ..."`。
2. 助手最终文本诚实说明文件不存在。
3. 网页活动卡却显示成功：`刚刚替你处理好了`、`这个文件已经看过了`、`好了`。

根因链路：

1. `honeyos/agent/tool_executor.py` 检测到了 `_is_error_result`，但仍固定发送 `tool.completed`，仅把错误放在 `is_error` 参数里。
2. `honeyos/gateway/platforms/api_server.py` 的伴侣网页回调没有把 `is_error` 传给投影层，也没有把事件改写成 `tool.failed`。
3. `honeyos/companion/activity.py` 收到 `tool.completed` 后必然投影为 `state=completed` 和成功文案。

同一投影路径连续执行两次，均稳定得到：

```json
{"state":"completed","title":"这个文件已经看过了"}
```

## Case 5 已实施修复

已按最小影响方案完成：

1. `api_server.py`：伴侣网页收到 `tool.completed` 且 `is_error=true` 时，规范化为 `tool.failed`；非伴侣 API 流保持原事件类型。
2. `run-state.js`：助手回复完成后，如果活动中存在失败步骤，汇总卡继续保持失败状态，不再无条件显示“处理好了”。
3. `test_companion_web.py`：增加错误完成事件投影测试。
4. `test_companion_web_state.py`：增加“失败工具 + 助手正常解释”场景的汇总状态测试，同时保留成功路径断言。

修复后真实网页复测两次：

- 第一次确认展开步骤已变为失败状态。
- 第二次确认折叠汇总与展开步骤都为失败状态，页面显示“刚才没走通，我换个办法”“做到 0/1 步”，不再出现成功文案。
- 数据库消息 `351` 至 `354` 确认底层工具仍真实返回 `File not found`，助手回复诚实说明文件不存在。
- 两个测试文件路径均未被创建。

验证命令通过：Python 直接回归断言、Node.js 成功/失败汇总断言、`py_compile`、`git diff --check`。当前 Conda 环境未安装 `pytest`，因此没有执行完整 pytest 套件。

## Case 6 复现证据

第一次（现有会话，提醒标记 `CASE6-LATEST-REPRO-20260812`）：

- `memory` 一次成功。
- `cronjob` 一次成功，同时提供 `schedule="0 10 * * 6"` 和完整 `prompt`。
- 真实 job id：`75077bfb8e35`。

第二次（发送 `/new` 后，提醒标记 `CASE6-CLEAN-REPRO-20260812`）：

- `memory` 一次成功。
- `cronjob` 一次成功，同样一次性提供 `schedule` 与 `prompt`。
- 真实 job id：`052fb1c9077b`。

两次都没有出现旧版本的 24 次失败重试或达到工具调用上限。因此按用户旅程验收，Case 6 当前通过。

## Case 6 剩余稳定性风险与加固方案

虽然本轮通过，旧故障的防护仍不完整：

1. `CRONJOB_SCHEMA` 顶层仍只 `required: ["action"]`，`schedule` / `prompt` 只写在描述中，模型仍可能漏参。
2. 重复失败硬停止默认仍关闭；通用强制 cap 只覆盖 `web_search` 和 `delegate_task`，不覆盖 `cronjob`。

建议加固：

1. 用条件 JSON Schema（`if/then` 或 `oneOf`）表达 `action=create` 时必需 `schedule`，且普通 agent job 必需 `prompt` 或 `skills`。
2. 若目标模型/Provider 不稳定支持条件 Schema，则把创建动作拆成独立 `cronjob_create` 工具，让 `schedule`、`prompt` 成为真正的顶层 required 字段。
3. 为 `cronjob` 增加默认启用的单轮失败上限，例如同一工具连续失败 5 次即停止并向用户说明，而不是耗尽 24 轮。
4. 增加回归测试：缺参应返回结构化 `missing_fields`；重复失败不得超过上限；正常用户旅程必须在 2 至 3 次工具调用内完成。

## 清理确认

- 已删除两轮 Case 6 测试提醒。
- 已删除两轮 Case 6 测试记忆。
- `jobs.json` 与 `MEMORY.md` 中均无 `CASE6-LATEST-REPRO-20260812` 或 `CASE6-CLEAN-REPRO-20260812` 残留。
- Case 5 使用的是不存在文件，没有创建任何文件。
- 原有提醒、电影记录、偏好和其他记忆未改动。
