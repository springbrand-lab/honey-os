const elements = {
  messages: document.querySelector("#messages"),
  empty: document.querySelector("#empty-state"),
  form: document.querySelector("#composer"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-button"),
  name: document.querySelector("#companion-name"),
  status: document.querySelector("#companion-status"),
  avatar: document.querySelector("#avatar"),
  statusAvatar: document.querySelector("#status-avatar"),
  turnStatus: document.querySelector("#turn-status"),
  presence: document.querySelector("#presence-line"),
  presenceCopy: document.querySelector("#presence-copy"),
  actionTrail: document.querySelector("#action-trail"),
  permissionCard: document.querySelector("#permission-card"),
  scrollLatest: document.querySelector("#scroll-to-latest"),
};

let sessionId = "";
let sessionKey = "";
let activeAssistantBubble = null;
let sending = false;
let turnState = HoneyOSRunState.create(Date.now());
let keepAtLatest = true;
let companionAvatarLabel = "H";
let actionTrailExpanded = false;

function isNearLatest() {
  const remaining =
    elements.messages.scrollHeight -
    elements.messages.scrollTop -
    elements.messages.clientHeight;
  return remaining < 80;
}

function updateScrollButton() {
  const shouldShow =
    !isNearLatest() &&
    elements.messages.scrollHeight > elements.messages.clientHeight;
  elements.scrollLatest.hidden = !shouldShow;
}

function scrollToLatest(force = false) {
  if (!force && !keepAtLatest) {
    updateScrollButton();
    return;
  }
  elements.messages.scrollTop = elements.messages.scrollHeight;
  keepAtLatest = true;
  updateScrollButton();
}

function removeEmptyState() {
  if (elements.empty) {
    elements.empty.remove();
    elements.empty = null;
  }
}

function createMessage(role) {
  removeEmptyState();
  const row = document.createElement("div");
  row.className = "message-row " + (role === "user" ? "user" : "assistant");
  const avatar = document.createElement("div");
  avatar.className =
    "message-avatar " + (role === "user" ? "user-avatar" : "assistant-avatar");
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = role === "user" ? "你" : companionAvatarLabel;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "user") row.append(bubble, avatar);
  else row.append(avatar, bubble);
  elements.messages.append(row);
  return bubble;
}

function renderMessage(bubble, role, content) {
  if (role === "assistant") {
    HoneyOSMessageFormat.render(bubble, content);
    return;
  }
  bubble.textContent = content;
}

function addMessage(role, content, options = {}) {
  if (!content) return null;
  const forceScroll = Boolean(options.forceScroll);
  const shouldFollow = forceScroll || isNearLatest();
  const bubble = createMessage(role);
  renderMessage(bubble, role, content);
  keepAtLatest = shouldFollow;
  scrollToLatest(forceScroll);
  return bubble;
}

function hideTurnStatus() {
  elements.turnStatus.hidden = true;
  elements.presence.hidden = true;
  elements.actionTrail.hidden = true;
  elements.permissionCard.hidden = true;
}

function showTurnStatus() {
  const shouldMoveToLatest =
    elements.turnStatus.hidden ||
    elements.turnStatus.parentElement !== elements.messages;
  if (shouldMoveToLatest) elements.messages.append(elements.turnStatus);
  elements.turnStatus.hidden = false;
}

function renderPresence(state) {
  const activity = state.presence || { title: "我在想你刚才说的事" };
  elements.presenceCopy.textContent =
    activity.title || "我在想你刚才说的事";
  showTurnStatus();
  elements.presence.hidden = false;
  elements.actionTrail.hidden = true;
  elements.permissionCard.hidden = true;
}

function permissionChoiceLabel(choice) {
  return {
    once: "好，你继续",
    session: "本次对话都可以",
    always: "以后同类操作都可以",
    deny: "先别动",
  }[choice] || choice;
}

async function answerPermission(choice) {
  const permission = turnState.permission;
  if (!permission) return;
  const buttons = elements.permissionCard.querySelectorAll("button");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(
      "/api/sessions/" + encodeURIComponent(sessionId) + "/approval",
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-HoneyOS-Session-Key": sessionKey,
        },
        body: JSON.stringify({ choice }),
      },
    );
    if (!response.ok) throw new Error("approval_unavailable");
    turnState = HoneyOSRunState.reduce(
      turnState,
      { name: "approval.responded", payload: { choice } },
      Date.now(),
    );
    elements.permissionCard.replaceChildren();
    elements.permissionCard.hidden = true;
    renderTurnState(turnState);
  } catch {
    buttons.forEach((button) => { button.disabled = false; });
    showError("approval_unavailable");
  }
}

function renderPermission(state) {
  const permission = state.permission;
  if (!permission) return;
  const card = document.createElement("section");
  card.className = "permission-card-inner";

  const narration = document.createElement("p");
  narration.className = "permission-narration";
  narration.textContent = permission.narration || "这一步需要你点个头，我再继续。";
  const summary = document.createElement("strong");
  summary.className = "permission-summary";
  summary.textContent = permission.summary;

  const actions = document.createElement("div");
  actions.className = "permission-actions";
  const primaryChoices = ["once", "deny"].filter((choice) => permission.choices.includes(choice));
  for (const choice of primaryChoices) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "permission-button " + (choice === "once" ? "primary" : "quiet");
    button.textContent = permissionChoiceLabel(choice);
    button.addEventListener("click", () => void answerPermission(choice));
    actions.append(button);
  }

  const details = document.createElement("details");
  details.className = "permission-details";
  const detailsTitle = document.createElement("summary");
  detailsTitle.textContent = "看看具体会做什么";
  details.append(detailsTitle);
  const list = document.createElement("ul");
  for (const line of permission.boundaries) {
    const item = document.createElement("li");
    item.textContent = line;
    list.append(item);
  }
  details.append(list);
  if (permission.technical_detail) {
    const technical = document.createElement("pre");
    technical.textContent = permission.technical_detail;
    details.append(technical);
  }
  const scoped = document.createElement("div");
  scoped.className = "permission-scoped-actions";
  for (const choice of ["session", "always"].filter((item) => permission.choices.includes(item))) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = permissionChoiceLabel(choice);
    button.addEventListener("click", () => void answerPermission(choice));
    scoped.append(button);
  }
  details.append(scoped);
  card.append(narration, summary, actions, details);
  elements.permissionCard.replaceChildren(card);
  showTurnStatus();
  elements.presence.hidden = true;
  elements.actionTrail.hidden = true;
  elements.permissionCard.hidden = false;
}

function activityStatusLabel(activity) {
  if (activity.state === "completed") return "好了";
  if (activity.state === "failed") return "换个办法";
  return "进行中";
}

function renderActionTrail(state) {
  const activities = state.activities || [];
  if (!activities.length) {
    renderPresence(state);
    return;
  }
  const summary = HoneyOSRunState.summarize(state);

  const wrapper = document.createElement("div");
  wrapper.className = "action-current";
  wrapper.dataset.state = summary.state;

  const summaryButton = document.createElement("button");
  summaryButton.type = "button";
  summaryButton.className = "action-summary";
  summaryButton.setAttribute("aria-expanded", String(actionTrailExpanded));
  summaryButton.setAttribute(
    "aria-label",
    actionTrailExpanded ? "收起处理过程" : "查看处理过程",
  );

  const mark = document.createElement("span");
  mark.className = "action-mark";
  mark.setAttribute("aria-hidden", "true");

  const copy = document.createElement("div");
  copy.className = "action-copy";
  const title = document.createElement("p");
  title.textContent = summary.title;
  copy.append(title);

  const meta = document.createElement("span");
  meta.className = "action-meta";
  meta.textContent = summary.meta;

  const toggleMark = document.createElement("span");
  toggleMark.className = "action-toggle-mark";
  toggleMark.setAttribute("aria-hidden", "true");
  toggleMark.dataset.expanded = String(actionTrailExpanded);

  const details = document.createElement("ol");
  details.className = "action-details";
  details.hidden = !actionTrailExpanded;
  for (const activity of activities) {
    const item = document.createElement("li");
    item.className = "action-step";
    item.dataset.state = activity.state || "active";

    const stepMark = document.createElement("span");
    stepMark.className = "action-step-mark";
    stepMark.setAttribute("aria-hidden", "true");

    const stepCopy = document.createElement("div");
    stepCopy.className = "action-step-copy";
    const stepTitle = document.createElement("p");
    stepTitle.textContent = activity.title || "正在替你处理";
    stepCopy.append(stepTitle);
    if (activity.detail) {
      const stepDetail = document.createElement("span");
      stepDetail.textContent = activity.detail;
      stepCopy.append(stepDetail);
    }

    const stepState = document.createElement("span");
    stepState.className = "action-step-state";
    stepState.textContent = activityStatusLabel(activity);
    item.append(stepMark, stepCopy, stepState);
    details.append(item);
  }

  summaryButton.addEventListener("click", () => {
    actionTrailExpanded = !actionTrailExpanded;
    summaryButton.setAttribute("aria-expanded", String(actionTrailExpanded));
    summaryButton.setAttribute(
      "aria-label",
      actionTrailExpanded ? "收起处理过程" : "查看处理过程",
    );
    toggleMark.dataset.expanded = String(actionTrailExpanded);
    details.hidden = !actionTrailExpanded;
    if (actionTrailExpanded) scrollToLatest();
  });

  summaryButton.append(mark, copy, meta, toggleMark);
  wrapper.append(summaryButton, details);
  elements.actionTrail.replaceChildren(wrapper);
  showTurnStatus();
  elements.presence.hidden = true;
  elements.actionTrail.hidden = false;
}

function renderTurnState(state) {
  if (state.phase === "awaiting_permission" && state.permission) renderPermission(state);
  else if (state.activities.length) renderActionTrail(state);
  else if (state.phase === "present") renderPresence(state);
  else hideTurnStatus();
  scrollToLatest();
}

function normalizeError(rawMessage) {
  const message = String(rawMessage || "");
  const lower = message.toLowerCase();
  if (lower.includes("no llm provider configured")) {
    return {
      message: "还差一步模型配置，配置好我们就能说话了。",
      action: "请在终端运行 honeyos setup",
    };
  }
  if (lower.includes("authentication") || lower.includes("credentials")) {
    return {
      message: "模型的连接信息没有通过验证。",
      action: "检查 API Key 后，再来找我。",
    };
  }
  if (lower.includes("failed after retries") || lower.includes("retry")) {
    return {
      message: "刚才连续几次都没连上。",
      action: "等一会儿再试，我会在这里。",
    };
  }
  return {
    message: "刚才没有连上。你可以再发一次，我也会在这里。",
    action: "",
  };
}

function showError(rawMessage) {
  const safe = normalizeError(rawMessage);
  const note = document.createElement("div");
  note.className = "error-note";
  const copy = document.createElement("div");
  copy.className = "error-note-copy";
  const message = document.createElement("span");
  message.textContent = safe.message;
  copy.append(message);
  if (safe.action) {
    const action = document.createElement("small");
    action.textContent = safe.action;
    copy.append(action);
  }
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "再试一次";
  retry.addEventListener("click", () => {
    note.remove();
    elements.input.focus();
  });
  note.append(copy, retry);
  elements.messages.append(note);
  keepAtLatest = true;
  scrollToLatest(true);
}

function parseEventBlock(block) {
  let name = "message";
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!data.length) return null;
  try {
    return { name, payload: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

function handleStreamEvent(name, payload) {
  turnState = HoneyOSRunState.reduce(
    turnState,
    { name, payload },
    Date.now(),
  );

  if (name === "assistant.delta" && payload.delta) {
    if (!activeAssistantBubble) activeAssistantBubble = createMessage("assistant");
    renderMessage(activeAssistantBubble, "assistant", turnState.content);
  }

  if (name === "assistant.completed" && payload.content) {
    if (!activeAssistantBubble) activeAssistantBubble = createMessage("assistant");
    renderMessage(activeAssistantBubble, "assistant", turnState.content);
  }

  if (name === "error") showError(payload.message);
  renderTurnState(turnState);
}

async function consumeSse(response) {
  if (!response.ok || !response.body) {
    let message = "chat_unavailable";
    try {
      const data = await response.json();
      message = data.error?.message || data.message || message;
    } catch {
      // The response may not contain JSON. Keep the safe fallback code.
    }
    throw new Error(message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const result = await reader.read();
    const value = result.value;
    const done = result.done;
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const event = parseEventBlock(block);
      if (event) handleStreamEvent(event.name, event.payload);
    }
    if (done) break;
  }
}

async function bootstrap() {
  const response = await fetch("/api/companion/bootstrap", {
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error("bootstrap_unavailable");
  const data = await response.json();
  sessionId = data.session_id;
  sessionKey = data.session_key;
  elements.name.textContent = data.profile.name;
  elements.status.textContent = data.profile.status;
  companionAvatarLabel = Array.from(data.profile.name || "H")[0];
  elements.avatar.textContent = companionAvatarLabel;
  elements.statusAvatar.textContent = companionAvatarLabel;
  for (const message of data.messages || []) {
    addMessage(message.role, message.content);
  }
  scrollToLatest(true);
}

async function sendMessage(text) {
  sending = true;
  elements.send.disabled = true;
  elements.send.textContent = "处理中";
  activeAssistantBubble = null;
  turnState = HoneyOSRunState.create(Date.now());
  actionTrailExpanded = false;
  hideTurnStatus();
  addMessage("user", text, { forceScroll: true });

  try {
    const response = await fetch(
      "/api/sessions/" + encodeURIComponent(sessionId) + "/chat/stream",
      {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-HoneyOS-Session-Key": sessionKey,
          "X-HoneyOS-Companion-View": "1",
        },
        body: JSON.stringify({ message: text }),
      },
    );
    await consumeSse(response);
  } catch (error) {
    const message = error instanceof Error ? error.message : "chat_unavailable";
    turnState = HoneyOSRunState.reduce(
      turnState,
      { name: "error", payload: { message } },
      Date.now(),
    );
    showError(message);
    renderTurnState(turnState);
  } finally {
    sending = false;
    elements.send.disabled = false;
    elements.send.textContent = "发送";
    activeAssistantBubble = null;
    elements.input.focus();
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.input.value.trim();
  if (!text || sending) return;
  elements.input.value = "";
  elements.input.style.height = "auto";
  void sendMessage(text);
});

elements.input.addEventListener("input", () => {
  elements.input.style.height = "auto";
  elements.input.style.height =
    Math.min(elements.input.scrollHeight, 132) + "px";
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});

elements.messages.addEventListener("scroll", () => {
  keepAtLatest = isNearLatest();
  updateScrollButton();
});

elements.scrollLatest.addEventListener("click", () => scrollToLatest(true));

if (window.location.protocol !== "file:") {
  bootstrap().catch((error) => {
    const message = error instanceof Error ? error.message : "bootstrap_unavailable";
    showError(message);
  });
}
