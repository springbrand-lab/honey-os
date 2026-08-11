window.HoneyOSTheme = (() => {
  const storageKey = "honeyos-theme";
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");

  function get() {
    try {
      const saved = window.localStorage.getItem(storageKey);
      if (saved === "light" || saved === "dark") return saved;
    } catch {
      // The page still follows the OS theme when storage is unavailable.
    }
    return "system";
  }

  function apply(preference) {
    const value = preference === "light" || preference === "dark" ? preference : "system";
    const resolved = value === "system" ? (systemTheme.matches ? "dark" : "light") : value;
    document.documentElement.dataset.theme = resolved;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      resolved === "dark" ? "#24231f" : "#efede8",
    );
    return value;
  }

  function set(preference) {
    const value = apply(preference);
    try {
      window.localStorage.setItem(storageKey, value);
    } catch {
      // Keep the selected theme for this page even when it cannot be persisted.
    }
    return value;
  }

  systemTheme.addEventListener("change", () => {
    if (get() === "system") apply("system");
  });
  apply(get());
  return { get, set };
})();

if (window.location.protocol === "file:") {
  document.documentElement.dataset.fileMode = "true";
  try {
    window.location.replace("http://127.0.0.1:8642/");
  } catch {
    // Some embedded browsers block navigation from local files.
  }
  window.addEventListener("DOMContentLoaded", () => {
    window.setTimeout(() => {
      if (window.location.protocol !== "file:") return;
      const notice = document.querySelector("#file-mode-notice");
      if (notice) notice.hidden = false;
    }, 800);
  });
}
