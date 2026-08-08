(function attachRunState(root) {
  "use strict";

  const PHASES = new Set([
    "idle",
    "present",
    "acting",
    "responding",
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
      error: "",
    };
  }

  function upsertActivity(activities, next) {
    const safeNext = {
      activity_id: String(next.activity_id || "activity"),
      kind: String(next.kind || "handling"),
      state: String(next.state || "active"),
      title: String(next.title || ""),
      detail: String(next.detail || ""),
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
        activities: upsertActivity(current.activities, payload.activity),
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
    return current;
  }

  root.HoneyOSRunState = Object.freeze({ create, reduce });
})(typeof window === "undefined" ? globalThis : window);

