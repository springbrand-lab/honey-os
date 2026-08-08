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
