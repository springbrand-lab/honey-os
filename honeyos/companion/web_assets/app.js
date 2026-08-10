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
  topicPoolTrigger: document.querySelector("#topic-pool-trigger"),
  topicPoolCount: document.querySelector("#topic-pool-count"),
  topicPoolLayer: document.querySelector("#topic-pool-layer"),
  topicPoolDrawer: document.querySelector("#topic-pool-drawer"),
  topicPoolList: document.querySelector("#topic-pool-list"),
  topicPoolClose: document.querySelector("#topic-pool-close"),
  topicPoolBackdrop: document.querySelector("#topic-pool-backdrop"),
  views: Array.from(document.querySelectorAll("[data-view]")),
  viewButtons: Array.from(document.querySelectorAll("[data-view-target]")),
  navigationItems: Array.from(document.querySelectorAll(".navigation-item")),
  memoryList: document.querySelector("#memory-list"),
  memoryCount: document.querySelector("#memory-count"),
  memoryTabs: Array.from(document.querySelectorAll("[data-memory-filter]")),
  profileForm: document.querySelector("#profile-form"),
  profileFormStatus: document.querySelector("#profile-form-status"),
  relationshipSummary: document.querySelector("#relationship-summary"),
  relationshipNickname: document.querySelector("#relationship-nickname"),
  relationshipAvatar: document.querySelector("#relationship-companion-avatar"),
  historyList: document.querySelector("#history-list"),
  historyPreview: document.querySelector("#history-preview"),
  historySearch: document.querySelector("#history-search"),
  newChatButton: document.querySelector("#new-chat-button"),
  conversationModel: document.querySelector("#conversation-model"),
  distillationModel: document.querySelector("#distillation-model"),
  proactiveSetting: document.querySelector("#proactive-setting"),
  toast: document.querySelector("#app-toast"),
};

let sessionId = "";
let sessionKey = "";
let activeAssistantBubble = null;
let sending = false;
const pendingMessages = [];
let turnState = HoneyOSRunState.create(Date.now());
let keepAtLatest = true;
let companionAvatarLabel = "H";
let actionTrailExpanded = false;
let topicPoolOpen = false;
let topicPoolLoading = false;
let proactivePollTimer = null;
let activeView = "chat";
let memoryFilter = "all";
let companionData = {
  memories: [],
  history: [],
  profile: {},
  settings: {},
};
let toastTimer = null;

function avatarLabel(name, fallback = "H") {
  const value = Array.from(String(name || "").trim()).find((character) => character.trim());
  return value || fallback;
}

function setAvatarLabel(name) {
  companionAvatarLabel = avatarLabel(name, "H");
  document.querySelectorAll('[data-avatar-surface="companion"]').forEach((surface) => {
    surface.textContent = companionAvatarLabel;
  });
}

function createIcon(name) {
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("class", "app-icon");
  icon.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "./icons.svg#" + name);
  icon.append(use);
  return icon;
}

function setSendState(isBusy) {
  elements.send.classList.toggle("is-busy", isBusy);
  elements.send.setAttribute("aria-label", isBusy ? "正在处理，仍可继续发送" : "发送");
  const label = elements.send.querySelector(".send-label");
  if (label) label.textContent = isBusy ? "处理中" : "发送";
}

function showToast(message) {
  if (!elements.toast) return;
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  requestAnimationFrame(() => { elements.toast.dataset.visible = "true"; });
  toastTimer = window.setTimeout(() => {
    elements.toast.dataset.visible = "false";
    window.setTimeout(() => { elements.toast.hidden = true; }, 180);
  }, 2600);
}

function openView(viewName) {
  const target = elements.views.find((view) => view.dataset.view === viewName);
  if (!target) return;
  activeView = viewName;
  for (const view of elements.views) {
    view.classList.toggle("is-active", view === target);
  }
  for (const item of elements.navigationItems) {
    item.classList.toggle("is-active", item.dataset.viewTarget === viewName);
  }
  document.body.dataset.activeView = viewName;
  if (viewName === "chat") {
    requestAnimationFrame(() => {
      scrollToLatest(true);
      elements.input?.focus();
    });
  }
}

function formatDate(value, options = {}) {
  if (value === null || value === undefined || value === "") return "";
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric < 10_000_000_000 ? numeric * 1000 : numeric)
    : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  if (options.relative && date.toDateString() === now.toDateString()) return "今天";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (options.relative && date.toDateString() === yesterday.toDateString()) return "昨天";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    ...(options.withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

function memoryKindLabel(kind) {
  return {
    long_term_memory: "长期记忆",
    temporary_state: "最近",
    commitment: "答应过的",
    episode: "共同经历",
    open_loop: "待续",
  }[kind] || "记忆";
}

function memoryEvidenceLabel(evidence) {
  return {
    persistent_memory: "来自长期记忆",
    persistent_user: "来自对你的了解",
    user_stated: "来自你明确说过的话",
    assistant_committed: "来自它明确答应过的话",
    conversation_event: "来自真实发生的聊天",
  }[evidence] || "来自你们的聊天";
}

function memoryExpiryLabel(memory) {
  if (memory.kind === "long_term_memory") return "会一直记得";
  if (!memory.expires_at) return memory.kind === "episode" ? "会长期保留" : "没有设置到期时间";
  return "有效至 " + formatDate(memory.expires_at, { withTime: false });
}

function emptyPageState(title, copy) {
  const state = document.createElement("div");
  state.className = "page-empty-state";
  const mark = document.createElement("span");
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = "◇";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const text = document.createElement("p");
  text.textContent = copy;
  state.append(mark, heading, text);
  return state;
}

async function updateMemory(memory, action, button) {
  button.disabled = true;
  try {
    const response = await fetch(
      "/api/companion/memories/" + encodeURIComponent(memory.id),
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      },
    );
    if (!response.ok) throw new Error("memory_unavailable");
    companionData.memories = companionData.memories.filter((item) => item.id !== memory.id);
    renderMemories();
    showToast(action === "resolve" ? "已经标记为完成" : "这件事已经忘记了");
  } catch {
    button.disabled = false;
    showToast("刚才没有改成功，请稍后再试");
  }
}

function renderMemoryCard(memory) {
  const card = document.createElement("article");
  card.className = "memory-card";
  card.dataset.kind = memory.kind;

  const header = document.createElement("div");
  header.className = "memory-card-header";
  const kind = document.createElement("span");
  kind.className = "memory-kind";
  kind.textContent = memoryKindLabel(memory.kind);
  const expiry = document.createElement("span");
  expiry.className = "memory-expiry";
  expiry.textContent = memoryExpiryLabel(memory);
  header.append(kind, expiry);

  const content = document.createElement("h2");
  content.textContent = memory.content;
  const provenance = document.createElement("p");
  provenance.className = "memory-provenance";
  const sourceDate = formatDate(memory.created_at);
  provenance.textContent = memoryEvidenceLabel(memory.evidence) + (sourceDate ? " · " + sourceDate : "");

  const actions = document.createElement("div");
  actions.className = "memory-actions";
  if (memory.kind === "open_loop" || memory.kind === "commitment") {
    const resolve = document.createElement("button");
    resolve.type = "button";
    resolve.className = "memory-primary-action";
    resolve.textContent = "已经完成";
    resolve.addEventListener("click", () => void updateMemory(memory, "resolve", resolve));
    actions.append(resolve);
  }
  const forget = document.createElement("button");
  forget.type = "button";
  forget.className = "memory-quiet-action";
  forget.textContent = "忘记";
  forget.addEventListener("click", () => void updateMemory(memory, "forget", forget));
  actions.append(forget);

  card.append(header, content, provenance, actions);
  return card;
}

function renderMemories() {
  if (!elements.memoryList) return;
  const memories = companionData.memories.filter(
    (memory) => memoryFilter === "all" || memory.kind === memoryFilter,
  );
  if (elements.memoryCount) {
    elements.memoryCount.textContent = String(companionData.memories.length);
    elements.memoryCount.hidden = companionData.memories.length === 0;
  }
  if (!memories.length) {
    elements.memoryList.replaceChildren(
      emptyPageState(
        memoryFilter === "all" ? "还没有整理出需要延续的事情" : "这一类暂时是空的",
        "继续自然地聊天就好。值得留下的内容会慢慢出现在这里。",
      ),
    );
    return;
  }
  elements.memoryList.replaceChildren(...memories.map(renderMemoryCard));
}

function fillProfileForm(profile) {
  if (!elements.profileForm) return;
  for (const key of [
    "companion_name",
    "personality",
    "speaking_style",
    "user_nickname",
    "relationship",
    "boundaries",
  ]) {
    const field = elements.profileForm.elements.namedItem(key);
    if (field) field.value = profile[key] || "";
  }
  elements.relationshipSummary.textContent = profile.relationship || "正在认识彼此";
  elements.relationshipNickname.textContent = profile.user_nickname
    ? "它会叫你“" + profile.user_nickname + "”"
    : "称呼可以由你决定";
}

async function saveProfile(event) {
  event.preventDefault();
  const submit = elements.profileForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  elements.profileFormStatus.textContent = "正在保存";
  const body = {};
  const formData = new FormData(elements.profileForm);
  for (const [key, value] of formData.entries()) body[key] = String(value).trim();
  try {
    const response = await fetch("/api/companion/profile", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "profile_unavailable");
    companionData.profile = data.profile || body;
    fillProfileForm(companionData.profile);
    const name = companionData.profile.companion_name || "Honey";
    elements.name.textContent = name;
    setAvatarLabel(name);
    elements.profileFormStatus.textContent = "已保存";
    showToast("你们的资料已经更新");
  } catch (error) {
    elements.profileFormStatus.textContent = error instanceof Error ? error.message : "保存失败";
  } finally {
    submit.disabled = false;
  }
}

function historyTitle(item) {
  if (item.is_current) return item.title || "正在进行的聊天";
  if (item.title) return item.title;
  if (item.preview) return item.preview.length > 28 ? item.preview.slice(0, 28) + "…" : item.preview;
  return "一段聊天";
}

function renderHistoryList(query = "") {
  if (!elements.historyList) return;
  const normalized = query.trim().toLowerCase();
  const history = companionData.history.filter((item) => {
    if (!normalized) return true;
    return (item.title + " " + item.preview).toLowerCase().includes(normalized);
  });
  if (!history.length) {
    elements.historyList.replaceChildren(
      emptyPageState("没有找到相关聊天", "换个词再找找看。"),
    );
    return;
  }
  const rows = history.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = historyTitle(item);
    const preview = document.createElement("small");
    preview.textContent = item.preview || (item.is_current ? "这段聊天刚刚开始" : "没有可显示的文字预览");
    copy.append(title, preview);
    const meta = document.createElement("em");
    meta.textContent = (formatDate(item.last_active || item.started_at, { relative: true }) || "") + "  ›";
    button.append(copy, meta);
    button.addEventListener("click", () => void loadHistoryPreview(item, button));
    return button;
  });
  elements.historyList.replaceChildren(...rows);
}

async function loadHistoryPreview(item, button) {
  for (const row of elements.historyList.querySelectorAll(".history-item")) {
    row.classList.toggle("is-active", row === button);
  }
  elements.historyPreview.replaceChildren(emptyPageState("正在打开", "我把这段聊天找出来。"));
  try {
    const response = await fetch(
      "/api/sessions/" + encodeURIComponent(item.id) + "/messages",
      { credentials: "same-origin" },
    );
    if (!response.ok) throw new Error("history_unavailable");
    const data = await response.json();
    const messages = (data.data || []).filter(
      (message) => ["user", "assistant"].includes(message.role) && typeof message.content === "string",
    );
    const heading = document.createElement("header");
    const title = document.createElement("h2");
    title.textContent = historyTitle(item);
    const meta = document.createElement("p");
    meta.textContent = formatDate(item.last_active || item.started_at, { withTime: true });
    heading.append(title, meta);
    const transcript = document.createElement("div");
    transcript.className = "history-transcript";
    for (const message of messages) {
      const bubble = document.createElement("p");
      bubble.className = "history-message " + message.role;
      bubble.textContent = message.content;
      transcript.append(bubble);
    }
    if (!messages.length) transcript.append(emptyPageState("这段聊天没有可显示的消息", "工具过程不会出现在这里。"));
    elements.historyPreview.replaceChildren(heading, transcript);
  } catch {
    elements.historyPreview.replaceChildren(emptyPageState("刚才没有打开", "稍后再试一次。"));
  }
}

async function startNewConversation() {
  if (!window.confirm("开启新的聊天窗口？之前的聊天仍会保留。")) return;
  elements.newChatButton.disabled = true;
  const newChatLabel = elements.newChatButton.querySelector("span");
  if (newChatLabel) newChatLabel.textContent = "正在开启…";
  try {
    const response = await fetch("/api/companion/new", {
      method: "POST",
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("new_session_unavailable");
    window.location.reload();
  } catch {
    elements.newChatButton.disabled = false;
    if (newChatLabel) newChatLabel.textContent = "开启新的聊天";
    showToast("刚才没有开启成功，请稍后再试");
  }
}

function hydrateCompanionPages(data) {
  companionData.memories = Array.isArray(data.memories) ? data.memories : [];
  companionData.history = Array.isArray(data.history) ? data.history : [];
  companionData.profile = data.profile_details || {};
  companionData.settings = data.settings || {};
  renderMemories();
  fillProfileForm(companionData.profile);
  renderHistoryList();
  const label = companionAvatarLabel;
  if (elements.relationshipAvatar) elements.relationshipAvatar.textContent = label;
  if (elements.conversationModel) {
    elements.conversationModel.textContent = companionData.settings.conversation_model || "当前配置";
  }
  if (elements.distillationModel) {
    elements.distillationModel.textContent = companionData.settings.distillation_model === "auto"
      ? "跟随对话模型"
      : companionData.settings.distillation_model || "跟随对话模型";
  }
  void fetch("/api/companion/proactive-preferences", { credentials: "same-origin" })
    .then((response) => response.ok ? response.json() : null)
    .then((payload) => {
      if (!payload?.preferences || !elements.proactiveSetting) return;
      elements.proactiveSetting.textContent = payload.preferences.enabled === false ? "已关闭" : "按当前规则";
    })
    .catch(() => {});
}

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
  avatar.dataset.avatarSurface = role === "user" ? "user" : "companion";
  avatar.textContent = role === "user" ? "你" : companionAvatarLabel;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "user") row.append(bubble, avatar);
  else row.append(avatar, bubble);
  elements.messages.append(row);
  return bubble;
}

function appendMessageActions(bubble, role, content) {
  if (role !== "assistant") return;
  const actions = document.createElement("div");
  actions.className = "message-actions";

  const copy = document.createElement("button");
  copy.type = "button";
  copy.setAttribute("aria-label", "复制这条回复");
  copy.append(createIcon("copy"));
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(content);
      showToast("已经复制好了");
    } catch {
      showToast("这次没复制成功");
    }
  });

  const helpful = document.createElement("button");
  helpful.type = "button";
  helpful.setAttribute("aria-label", "这条回复有帮助");
  helpful.append(createIcon("thumb-up"));
  helpful.addEventListener("click", () => {
    helpful.dataset.selected = "true";
    showToast("我记下了");
  });

  actions.append(copy, helpful);
  bubble.append(actions);
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
  appendMessageActions(bubble, role, content);
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

  const wrapper = document.createElement("details");
  wrapper.className = "activity-card";
  wrapper.dataset.state = summary.state;
  wrapper.open = actionTrailExpanded;

  const summaryButton = document.createElement("summary");
  summaryButton.className = "activity-summary";

  const mark = document.createElement("span");
  mark.className = "activity-mark";
  mark.setAttribute("aria-hidden", "true");

  const copy = document.createElement("div");
  copy.className = "activity-copy";
  const title = document.createElement("p");
  title.textContent = summary.title;
  copy.append(title);

  const meta = document.createElement("span");
  meta.className = "activity-meta";
  meta.textContent = summary.meta;

  const toggleMark = document.createElement("span");
  toggleMark.className = "activity-toggle";
  toggleMark.setAttribute("aria-hidden", "true");
  toggleMark.append(createIcon("chevron-down"));

  const details = document.createElement("ol");
  details.className = "activity-steps";
  for (const activity of activities) {
    const item = document.createElement("li");
    item.className = "activity-step";
    item.dataset.state = activity.state || "active";

    const stepMark = document.createElement("span");
    stepMark.className = "activity-step-mark";
    stepMark.setAttribute("aria-hidden", "true");

    const stepCopy = document.createElement("div");
    stepCopy.className = "activity-step-copy";
    const stepTitle = document.createElement("p");
    stepTitle.textContent = activity.title || "正在替你处理";
    stepCopy.append(stepTitle);
    if (activity.detail) {
      const stepDetail = document.createElement("span");
      stepDetail.textContent = activity.detail;
      stepCopy.append(stepDetail);
    }

    const stepState = document.createElement("span");
    stepState.className = "activity-step-state";
    stepState.textContent = activityStatusLabel(activity);
    item.append(stepMark, stepCopy, stepState);
    details.append(item);
  }

  wrapper.addEventListener("toggle", () => {
    actionTrailExpanded = wrapper.open;
    if (wrapper.open) scrollToLatest();
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
  else if (state.phase === "present" || state.phase === "acting") renderPresence(state);
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
  setAvatarLabel(data.profile.name || "Honey");
  hydrateCompanionPages(data);
  for (const message of data.messages || []) {
    addMessage(message.role, message.content);
  }
  void refreshTopicCount();
  startProactivePolling();
  scrollToLatest(true);
}

async function sendMessage(text, options = {}) {
  sending = true;
  setSendState(true);
  activeAssistantBubble = null;
  turnState = HoneyOSRunState.create(Date.now());
  actionTrailExpanded = false;
  hideTurnStatus();
  if (!options.hideUser && !options.userAlreadyShown) {
    addMessage("user", options.displayText || text, { forceScroll: true });
  }

  let completed = false;
  try {
    const headers = {
      "Content-Type": "application/json",
      "X-HoneyOS-Session-Key": sessionKey,
      "X-HoneyOS-Companion-View": "1",
    };
    if (options.proactiveDeliveryId) {
      headers["X-HoneyOS-Internal-Turn"] = "proactive-topic";
    }
    const response = await fetch(
      "/api/sessions/" + encodeURIComponent(sessionId) + "/chat/stream",
      {
        method: "POST",
        credentials: "same-origin",
        headers,
        body: JSON.stringify({ message: text }),
      },
    );
    await consumeSse(response);
    completed = true;
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
    setSendState(false);
    activeAssistantBubble = null;
    elements.input.focus();
  }
  return completed;
}

function processMessageQueue() {
  if (sending || pendingMessages.length === 0) return;
  const next = pendingMessages.shift();
  void sendMessage(next.text, {
    ...next.options,
    userAlreadyShown: !next.options.hideUser,
  }).then((completed) => {
    next.resolve(completed);
    processMessageQueue();
  });
}

function queueMessage(text, options = {}) {
  if (!options.hideUser) {
    addMessage("user", options.displayText || text, { forceScroll: true });
  }
  if (sending && pendingMessages.length === 0) {
    addMessage("assistant", "这句我也看见了，等我把上一句弄完。", {
      forceScroll: true,
    });
  }
  return new Promise((resolve) => {
    pendingMessages.push({ text, options, resolve });
    processMessageQueue();
  });
}

async function finishProactiveDelivery(deliveryId, success) {
  try {
    await fetch(
      "/api/companion/proactive/" + encodeURIComponent(deliveryId) + "/complete",
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ success }),
      },
    );
  } catch {
    // A stale reservation is released by the server on a later check.
  }
}

async function pollProactiveTopic() {
  if (!sessionId || sending || document.visibilityState !== "visible") return;
  try {
    const response = await fetch("/api/companion/proactive/claim", {
      method: "POST",
      credentials: "same-origin",
    });
    if (!response.ok) return;
    const data = await response.json();
    const delivery = data.delivery;
    if (!delivery?.id || !delivery?.prompt || sending) return;
    const success = await queueMessage(delivery.prompt, {
      hideUser: true,
      proactiveDeliveryId: delivery.id,
    });
    await finishProactiveDelivery(delivery.id, success);
    if (success) void refreshTopicCount();
  } catch {
    // This is a quiet background check. Normal chat must remain unaffected.
  }
}

function startProactivePolling() {
  if (proactivePollTimer !== null) return;
  window.setTimeout(() => void pollProactiveTopic(), 1500);
  proactivePollTimer = window.setInterval(() => void pollProactiveTopic(), 60_000);
}

function topicPoolState(message, kind = "quiet") {
  const state = document.createElement("div");
  state.className = "topic-pool-state " + kind;
  const mark = document.createElement("span");
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = kind === "error" ? "·" : "✦";
  const copy = document.createElement("p");
  copy.textContent = message;
  state.append(mark, copy);
  return state;
}

function setTopicCount(count) {
  if (!elements.topicPoolCount) return;
  const safeCount = Math.max(0, Number(count) || 0);
  elements.topicPoolCount.textContent = String(Math.min(safeCount, 99));
  elements.topicPoolCount.hidden = safeCount === 0;
}

async function fetchTopics() {
  const response = await fetch("/api/companion/topics", {
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error("topics_unavailable");
  const data = await response.json();
  return Array.isArray(data.topics) ? data.topics : [];
}

async function refreshTopicCount() {
  try {
    const topics = await fetchTopics();
    setTopicCount(topics.length);
  } catch {
    setTopicCount(0);
  }
}

function topicSourceLabel(topic) {
  const source = String(topic.source_name || topic.source_title || "来源").trim();
  if (!topic.observed_at) return source;
  const observed = new Date(topic.observed_at);
  if (Number.isNaN(observed.getTime())) return source;
  const formatted = new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(observed);
  return source + " · " + formatted;
}

async function chooseTopic(topic, card, button) {
  if (sending) return;
  button.disabled = true;
  try {
    const response = await fetch(
      "/api/companion/topics/" + encodeURIComponent(topic.id) + "/discuss",
      { method: "POST", credentials: "same-origin" },
    );
    if (!response.ok) throw new Error("topic_unavailable");
    const data = await response.json();
    card.remove();
    closeTopicPool();
    setTopicCount(elements.topicPoolList.querySelectorAll(".topic-card").length);
    await queueMessage(data.prompt, {
      displayText: data.display_text || "这个我想听你聊聊",
    });
  } catch {
    button.disabled = false;
    const note = document.createElement("span");
    note.className = "topic-card-error";
    note.textContent = "这条刚好过期了，我再看看别的。";
    card.append(note);
  }
}

async function dismissTopic(topic, card, button) {
  button.disabled = true;
  try {
    const response = await fetch(
      "/api/companion/topics/" + encodeURIComponent(topic.id) + "/dismiss",
      { method: "POST", credentials: "same-origin" },
    );
    if (!response.ok) throw new Error("topic_unavailable");
    card.remove();
    const remaining = elements.topicPoolList.querySelectorAll(".topic-card").length;
    setTopicCount(remaining);
    if (!remaining) {
      elements.topicPoolList.replaceChildren(
        topicPoolState("暂时没有特别想拉你一起看的。等我再遇见点有意思的。"),
      );
    }
  } catch {
    button.disabled = false;
  }
}

function renderTopicCard(topic) {
  const card = document.createElement("article");
  card.className = "topic-card";

  const category = document.createElement("span");
  category.className = "topic-card-category";
  category.textContent = topic.category || "刚看到的";

  const hook = document.createElement("h3");
  hook.textContent = topic.hook || topic.summary || "有件事想和你聊聊";

  const summary = document.createElement("p");
  summary.className = "topic-card-summary";
  summary.textContent = topic.summary || "";

  const source = document.createElement("details");
  source.className = "topic-card-source";
  const sourceTitle = document.createElement("summary");
  sourceTitle.textContent = topicSourceLabel(topic);
  const sourceLink = document.createElement("a");
  sourceLink.href = topic.source_url;
  sourceLink.target = "_blank";
  sourceLink.rel = "noreferrer noopener";
  sourceLink.textContent = topic.source_title || "看看原始来源";
  source.append(sourceTitle, sourceLink);

  const actions = document.createElement("div");
  actions.className = "topic-card-actions";
  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.className = "topic-card-dismiss";
  dismiss.textContent = "先放着";
  dismiss.addEventListener("click", () => void dismissTopic(topic, card, dismiss));
  const discuss = document.createElement("button");
  discuss.type = "button";
  discuss.className = "topic-card-discuss";
  discuss.textContent = "想聊这个";
  discuss.addEventListener("click", () => void chooseTopic(topic, card, discuss));
  actions.append(dismiss, discuss);

  card.append(category, hook);
  if (summary.textContent) card.append(summary);
  card.append(source, actions);
  return card;
}

async function loadTopicPool() {
  if (topicPoolLoading) return;
  topicPoolLoading = true;
  elements.topicPoolList.replaceChildren(topicPoolState("我翻一下最近留下来的。"));
  try {
    const topics = await fetchTopics();
    setTopicCount(topics.length);
    if (!topics.length) {
      elements.topicPoolList.replaceChildren(
        topicPoolState("暂时没有特别想拉你一起看的。等我再遇见点有意思的。"),
      );
      return;
    }
    elements.topicPoolList.replaceChildren(...topics.map(renderTopicCard));
  } catch {
    elements.topicPoolList.replaceChildren(
      topicPoolState("刚才没翻出来。晚一点再陪你看。", "error"),
    );
  } finally {
    topicPoolLoading = false;
  }
}

function openTopicPool() {
  if (!elements.topicPoolLayer || topicPoolOpen) return;
  topicPoolOpen = true;
  elements.topicPoolLayer.hidden = false;
  document.body.classList.add("topic-pool-visible");
  requestAnimationFrame(() => {
    elements.topicPoolLayer.dataset.open = "true";
    elements.topicPoolClose.focus();
  });
  void loadTopicPool();
}

function closeTopicPool() {
  if (!elements.topicPoolLayer || !topicPoolOpen) return;
  topicPoolOpen = false;
  elements.topicPoolLayer.dataset.open = "false";
  document.body.classList.remove("topic-pool-visible");
  window.setTimeout(() => {
    if (!topicPoolOpen) elements.topicPoolLayer.hidden = true;
  }, 180);
  elements.topicPoolTrigger.focus();
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = elements.input.value.trim();
  if (!text) return;
  elements.input.value = "";
  elements.input.style.height = "auto";
  void queueMessage(text);
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
elements.topicPoolTrigger?.addEventListener("click", openTopicPool);
elements.topicPoolClose?.addEventListener("click", closeTopicPool);
elements.topicPoolBackdrop?.addEventListener("click", closeTopicPool);
for (const button of elements.viewButtons) {
  button.addEventListener("click", () => openView(button.dataset.viewTarget));
}
for (const tab of elements.memoryTabs) {
  tab.addEventListener("click", () => {
    memoryFilter = tab.dataset.memoryFilter || "all";
    for (const item of elements.memoryTabs) item.classList.toggle("is-active", item === tab);
    renderMemories();
  });
}
elements.profileForm?.addEventListener("submit", saveProfile);
elements.historySearch?.addEventListener("input", () => {
  renderHistoryList(elements.historySearch.value);
});
elements.newChatButton?.addEventListener("click", () => void startNewConversation());
for (const button of document.querySelectorAll("[data-coming-soon]")) {
  button.addEventListener("click", () => showToast(button.dataset.comingSoon));
}
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (topicPoolOpen) closeTopicPool();
  else if (activeView !== "chat") openView("chat");
});

if (window.location.protocol !== "file:") {
  bootstrap().catch((error) => {
    const message = error instanceof Error ? error.message : "bootstrap_unavailable";
    showError(message);
  });
}
