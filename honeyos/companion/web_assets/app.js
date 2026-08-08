const elements = {
  messages: document.querySelector("#messages"),
  empty: document.querySelector("#empty-state"),
  form: document.querySelector("#composer"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-button"),
  name: document.querySelector("#companion-name"),
  status: document.querySelector("#companion-status"),
  avatar: document.querySelector("#avatar"),
};

let sessionId = "";
let sessionKey = "";
let activeActivity = null;
let activeAssistantBubble = null;
let sending = false;
let activityTimer = null;
let pendingActivity = null;
let turnStartedAt = 0;
const ACTIVITY_DELAY_MS = 1200;

function scrollToLatest() {
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function removeEmptyState() {
  if (elements.empty) {
    elements.empty.remove();
    elements.empty = null;
  }
}

function addMessage(role, content) {
  if (!content) return null;
  removeEmptyState();
  const row = document.createElement("div");
  row.className = `message-row ${role === "user" ? "user" : "assistant"}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  row.append(bubble);
  elements.messages.append(row);
  scrollToLatest();
  return bubble;
}

function showError(message) {
  const note = document.createElement("p");
  note.className = "error-note";
  note.textContent = message || "刚才没有连上，再试一次吧。";
  elements.messages.append(note);
  scrollToLatest();
}

function renderActivity(activity) {
  removeEmptyState();
  if (!activeActivity) {
    activeActivity = document.createElement("div");
    activeActivity.className = "activity-card";
    activeActivity.innerHTML = `
      <div class="activity-mark" aria-hidden="true"></div>
      <div>
        <p class="activity-title"></p>
        <p class="activity-detail"></p>
      </div>`;
    elements.messages.append(activeActivity);
  }
  activeActivity.dataset.state = activity.state || "active";
  activeActivity.querySelector(".activity-title").textContent = activity.title;
  const detail = activeActivity.querySelector(".activity-detail");
  detail.textContent = activity.detail || "";
  detail.hidden = !activity.detail;
  scrollToLatest();
}

function updateActivity(activity) {
  if (!activity || !activity.title) return;
  if (activity.state === "active" && !activeActivity) {
    pendingActivity = activity;
    if (!activityTimer) {
      const elapsed = Math.max(0, Date.now() - turnStartedAt);
      activityTimer = window.setTimeout(() => {
        activityTimer = null;
        if (pendingActivity) renderActivity(pendingActivity);
      }, Math.max(0, ACTIVITY_DELAY_MS - elapsed));
    }
    return;
  }
  if (activity.state === "completed" && !activeActivity) {
    pendingActivity = null;
    if (activityTimer) window.clearTimeout(activityTimer);
    activityTimer = null;
    return;
  }
  pendingActivity = null;
  if (activityTimer) window.clearTimeout(activityTimer);
  activityTimer = null;
  renderActivity(activity);
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
  if (payload.activity) updateActivity(payload.activity);
  if (name === "assistant.delta" && payload.delta) {
    if (!activeAssistantBubble) activeAssistantBubble = addMessage("assistant", "");
    if (!activeAssistantBubble) {
      removeEmptyState();
      const row = document.createElement("div");
      row.className = "message-row assistant";
      activeAssistantBubble = document.createElement("div");
      activeAssistantBubble.className = "bubble";
      row.append(activeAssistantBubble);
      elements.messages.append(row);
    }
    activeAssistantBubble.textContent += payload.delta;
    scrollToLatest();
  }
  if (name === "assistant.completed" && payload.content) {
    if (!activeAssistantBubble) activeAssistantBubble = addMessage("assistant", payload.content);
    else activeAssistantBubble.textContent = payload.content;
  }
  if (name === "error") showError(payload.message);
}

async function consumeSse(response) {
  if (!response.ok || !response.body) throw new Error("聊天服务暂时没有回应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
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
  const response = await fetch("/api/companion/bootstrap", { credentials: "same-origin" });
  if (!response.ok) throw new Error("本地伴侣还没有准备好");
  const data = await response.json();
  sessionId = data.session_id;
  sessionKey = data.session_key;
  elements.name.textContent = data.profile.name;
  elements.status.textContent = data.profile.status;
  elements.avatar.textContent = Array.from(data.profile.name || "H")[0];
  for (const message of data.messages || []) addMessage(message.role, message.content);
}

async function sendMessage(text) {
  sending = true;
  elements.send.disabled = true;
  activeActivity = null;
  activeAssistantBubble = null;
  pendingActivity = null;
  turnStartedAt = Date.now();
  if (activityTimer) window.clearTimeout(activityTimer);
  activityTimer = null;
  addMessage("user", text);
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/chat/stream`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-HoneyOS-Session-Key": sessionKey,
        "X-HoneyOS-Companion-View": "1",
      },
      body: JSON.stringify({ message: text }),
    });
    await consumeSse(response);
  } catch (error) {
    showError(error instanceof Error ? error.message : "刚才没有连上，再试一次吧。");
  } finally {
    sending = false;
    elements.send.disabled = false;
    activeAssistantBubble = null;
    pendingActivity = null;
    if (activityTimer) window.clearTimeout(activityTimer);
    activityTimer = null;
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
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 132)}px`;
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});

bootstrap().catch((error) => showError(error.message));
