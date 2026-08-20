# HoneyOS 前端改造参考

## 组成

HoneyOS 的本地伴侣页面是随 Python 包分发的静态前端，不使用 React、Vue，也不需要 Node.js 构建步骤。

- `honeyos/companion/web_assets/index.html`：页面结构、导航与各个页面。
- `honeyos/companion/web_assets/styles.css`：颜色、排版、组件状态与响应式布局。
- `honeyos/companion/web_assets/app.js`：聊天、页面切换、记忆、关系、设置和接口请求。
- `honeyos/companion/web_assets/run-state.js`：一轮聊天和工具活动的状态转换。
- `honeyos/companion/web_assets/message-format.js`：消息内容格式化。
- `honeyos/companion/web_assets/file-open.js`：本地文件打开保护。
- `honeyos/companion/web_assets/icons.svg`：界面图标。

后端从当前运行源码的 `honeyos/companion/web_assets/` 直接读取这些文件。首页使用 `no-store`，其余资源使用 `no-cache`。候选版本只有在用户确认激活、服务切换并重启后才成为正式页面。

## 修改流程

1. 先读取候选工作区中的 `index.html`、`app.js` 和与需求相关的其他文件，确认真实 DOM、事件和接口关系。
2. 只修改 Builder 返回的候选工作区，不修改当前运行目录。
3. 保留现有聊天、记忆、关系、模型设置和授权流程；除非用户明确要求，不删除无关功能。
4. 运行与改动相关的前端资源、消息格式、运行状态和伴侣页面测试。
5. 浏览器工具可用时，可以辅助预览；浏览器工具不可用时，不要阻塞，也不要假装看过页面。
6. 向用户说明候选版本改了什么，并请用户实际验收。用户明确确认后才激活。

## 最低验证

根据改动范围运行以下相关测试：

```text
tests/honeyos/test_companion_web_assets.py
tests/honeyos/test_companion_web.py
tests/honeyos/test_companion_web_state.py
tests/honeyos/test_companion_message_format.py
```

如果某项测试在当前安装中不存在，记录这一事实并运行仍然存在的相关测试。自动化检查通过只代表候选版本可供验收，不代表用户已经接受视觉效果。
