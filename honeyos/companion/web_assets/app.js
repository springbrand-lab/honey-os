const elements = {
  messages: document.querySelector("#messages"),
  empty: document.querySelector("#empty-state"),
  form: document.querySelector("#composer"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-button"),
  name: document.querySelector("#companion-name"),
  status: document.querySelector("#companion-status"),
  avatar: document.querySelector("#avatar"),
  turnStatus: document.querySelector("#turn-status"),
  presence: document.querySelector("#presence-line"),
  presenceCopy: document.querySelector("#presence-copy"),
  actionTrail: document.querySelector("#action-trail"),
  scrollLatest: document.querySelector("#scroll-to-latest"),
};

let sessionId = "";
let sessionKey = "";
let activeAssistantBubble = null;
let sending = false;
let turnState = HoneyOSRunState.create(Date.now());
let keepAtLatest = true;

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
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  row.append(bubble);
  elements.messages.append(row);
  return bubble;
}

function addMessage(role, content, options = {}) {
  if (!content) return null;
  const forceScroll = Boolean(options.forceScroll);
  const shouldFollow = forceScroll || isNearLatest();
  const bubble = createMessage(role);
  bubble.textContent = content;
  keepAtLatest = shouldFollow;
  scrollToLatest(forceScroll);
  return bubble;
}

function hideTurnStatus() {
  elements.turnStatus.hidden = true;
  elements.presence.hidden = true;
  elements.actionTrail.hidden = true;
}

function renderPresence(state) {
  const activity = state.presence || { title: "我在想你刚才说的事" };
  elements.presenceCopy.textContent =
    activity.title || "我在想你刚才说的事";
  elements.turnStatus.hidden = false;
  elements.presence.hidden = false;
  elements.actionTrail.hidden = true;
}

function activityStatusLabel(activity) {
  if (activity.state === "completed") return "好了";
  if (activity.state === "failed") return "换个办法";
  return "正在做";
}

function renderActionTrail(state) {
  const activities = state.activities || [];
  const current =
    [...activities].reverse().find((activity) => activity.state === "active") ||
    activities[activities.length - 1];
  if (!current) {
    renderPresence(state);
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "action-current";
  wrapper.dataset.state = current.state || "active";

  const mark = document.createElement("span");
  mark.className = "action-mark";
  mark.setAttribute("aria-hidden", "true");

  const copy = document.createElement("div");
  copy.className = "action-copy";
  const title = document.createElement("p");
  title.textContent = current.title;
  copy.append(title);
  if (current.detail) {
    const detail = document.createElement("span");
    detail.textContent = current.detail;
    copy.append(detail);
  }

  const meta = document.createElement("span");
  meta.className = "action-meta";
  meta.textContent =
    activities.length > 1
      ? activityStatusLabel(current) + "，共 " + activities.length + " 件"
      : activityStatusLabel(current);

  wrapper.append(mark, copy, meta);
  elements.actionTrail.replaceChildren(wrapper);
  elements.turnStatus.hidden = false;
  elements.presence.hidden = true;
  elements.actionTrail.hidden = false;
}

function renderTurnState(state) {
  if (state.phase === "present") renderPresence(state);
  else if (state.phase === "acting") renderActionTrail(state);
  else hideTurnStatus();
  scrollToLatest();
}

function safeErrorMessage() {
  return "刚才没有连上。你可以再发一次，我也会在这里。";
}

function showError() {
  const note = document.createElement("div");
  note.className = "error-note";
  const message = document.createElement("span");
  message.textContent = safeErrorMessage();
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "再试一次";
  retry.addEventListener("click", () => {
    note.remove();
    elements.input.focus();
  });
  note.append(message, retry);
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
    activeAssistantBubble.textContent = turnState.content;
  }

  if (name === "assistant.completed" && payload.content) {
    if (!activeAssistantBubble) activeAssistantBubble = createMessage("assistant");
    activeAssistantBubble.textContent = turnState.content;
  }

  if (name === "error") showError();
  renderTurnState(turnState);
}

async function consumeSse(response) {
  if (!response.ok || !response.body) throw new Error("chat_unavailable");
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
  elements.avatar.textContent = Array.from(data.profile.name || "H")[0];
  for (const message of data.messages || []) {
    addMessage(message.role, message.content);
  }
  scrollToLatest(true);
}

async function sendMessage(text) {
  sending = true;
  elements.send.disabled = true;
  activeAssistantBubble = null;
  turnState = HoneyOSRunState.create(Date.now());
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
  } catch {
    turnState = HoneyOSRunState.reduce(
      turnState,
      { name: "error", payload: { message: "chat_unavailable" } },
      Date.now(),
    );
    showError();
    renderTurnState(turnState);
  } finally {
    sending = false;
    elements.send.disabled = false;
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
  bootstrap().catch(() => showError());
}

