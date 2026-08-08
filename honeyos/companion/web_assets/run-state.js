(function attachRunState(root) {
  "use strict";

  const PHASES = new Set([
    "idle",
    "present",
    "acting",
    "responding",
    "awaiting_permission",
    "completed",
    "failed",
  ]);

  function create(now) {
    const startedAt = Number.isFinite(now) ? now : Date.now();
    return {
      phase: "idle",
      startedAt,
      updatedAt: startedAt,
      content: "",
      presence: null,
      activities: [],
      permission: null,
      error: "",
    };
  }

  function upsertActivity(activities, next, updatedAt) {
    const existing = activities.find(
      (item) => item.activity_id === String(next.activity_id || "activity"),
    );
    const safeNext = {
      activity_id: String(next.activity_id || "activity"),
      kind: String(next.kind || "handling"),
      state: String(next.state || "active"),
      title: String(next.title || ""),
      detail: String(next.detail || ""),
      startedAt: existing ? existing.startedAt : updatedAt,
      updatedAt,
    };
    const index = activities.findIndex(
      (item) => item.activity_id === safeNext.activity_id,
    );
    if (index < 0) return [...activities, safeNext];
    return activities.map((item, itemIndex) =>
      itemIndex === index ? safeNext : item,
    );
  }

  function reduce(state, event, now) {
    const current = state && PHASES.has(state.phase) ? state : create(now);
    const name = String((event && event.name) || "");
    const payload = (event && event.payload) || {};
    const updatedAt = Number.isFinite(now) ? now : Date.now();

    if (name === "run.started") {
      return { ...create(updatedAt), phase: "present" };
    }
    if (name === "presence.updated" && current.phase !== "responding") {
      return {
        ...current,
        phase: current.activities.length ? "acting" : "present",
        presence: payload.activity || current.presence,
        updatedAt,
      };
    }
    if (name.startsWith("tool.") && payload.activity) {
      return {
        ...current,
        phase: "acting",
        activities: upsertActivity(
          current.activities,
          payload.activity,
          updatedAt,
        ),
        updatedAt,
      };
    }
    if (name === "assistant.delta") {
      return {
        ...current,
        phase: "responding",
        content: current.content + String(payload.delta || ""),
        updatedAt,
      };
    }
    if (name === "approval.request") {
      return {
        ...current,
        phase: "awaiting_permission",
        permission: {
          approval_id: String(payload.approval_id || "approval"),
          narration: String(payload.narration || ""),
          summary: String(payload.summary || "需要你确认这一步"),
          boundaries: Array.isArray(payload.boundaries) ? payload.boundaries.map(String) : [],
          technical_detail: String(payload.technical_detail || ""),
          choices: Array.isArray(payload.choices) ? payload.choices.map(String) : ["once", "deny"],
        },
        updatedAt,
      };
    }
    if (name === "approval.responded") {
      return {
        ...current,
        phase: "acting",
        permission: null,
        presence: {
          activity_id: "permission-resumed",
          kind: "presence",
          state: "active",
          title: payload.choice === "deny" ? "好，这次先不做" : "好，我继续了",
          detail: "",
        },
        updatedAt,
      };
    }
    if (name === "assistant.completed") {
      return {
        ...current,
        phase: "completed",
        content: String(payload.content || current.content),
        updatedAt,
      };
    }
    if (name === "error") {
      return {
        ...current,
        phase: "failed",
        error: String(payload.message || ""),
        updatedAt,
      };
    }
    if (name === "run.completed" || name === "done") {
      return {
        ...current,
        phase: current.phase === "failed" ? "failed" : "completed",
        updatedAt,
      };
    }
    return current;
  }

  function summarize(state) {
    const current = state && PHASES.has(state.phase) ? state : create();
    const activities = current.activities || [];
    const total = activities.length;
    const completed = activities.filter(
      (activity) => activity.state === "completed",
    ).length;
    const active = [...activities]
      .reverse()
      .find((activity) => activity.state === "active");

    if (current.phase === "failed") {
      return {
        state: "failed",
        title: "刚才没走通，我换个办法",
        meta: total ? `做到 ${completed}/${total} 步` : "还没完成",
        completed,
        total,
      };
    }
    if (current.phase === "completed") {
      return {
        state: "completed",
        title: "刚刚替你处理好了",
        meta: `共 ${total} 步，点开看过程`,
        completed,
        total,
      };
    }
    if (active) {
      const position = activities.indexOf(active) + 1;
      return {
        state: "active",
        title: active.title || "正在替你处理",
        meta: `正在第 ${position} 步，共 ${total} 步`,
        completed,
        total,
      };
    }
    if (current.phase === "responding") {
      return {
        state: "active",
        title: "我在整理给你的回复",
        meta: `已完成 ${completed} 步，还在继续`,
        completed,
        total,
      };
    }
    return {
      state: "active",
      title: "我还在继续处理",
      meta: `已完成 ${completed} 步，还在继续`,
      completed,
      total,
    };
  }

  root.HoneyOSRunState = Object.freeze({ create, reduce, summarize });
})(typeof window === "undefined" ? globalThis : window);
