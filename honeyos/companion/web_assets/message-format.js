(function (root) {
  "use strict";

  function inline(text) {
    const tokens = [];
    const pattern = /(\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\))/g;
    let cursor = 0;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > cursor) {
        tokens.push({ type: "text", value: text.slice(cursor, match.index) });
      }
      if (match[2] !== undefined) {
        tokens.push({ type: "strong", value: match[2] });
      } else if (match[3] !== undefined) {
        tokens.push({ type: "code", value: match[3] });
      } else {
        tokens.push({ type: "link", value: match[4], href: match[5] });
      }
      cursor = pattern.lastIndex;
    }
    if (cursor < text.length) {
      tokens.push({ type: "text", value: text.slice(cursor) });
    }
    return tokens.length ? tokens : [{ type: "text", value: "" }];
  }

  function joinLines(lines) {
    return lines.reduce((result, line) => {
      const value = line.trim();
      if (!result) return value;
      const last = result[result.length - 1] || "";
      const first = value[0] || "";
      const cjk = /[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]/;
      return result + (cjk.test(last) && cjk.test(first) ? "" : " ") + value;
    }, "");
  }

  function parse(source) {
    const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }
      if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) {
        blocks.push({ type: "hr" });
        index += 1;
        continue;
      }
      const heading = line.match(/^\s*(#{1,3})\s+(.+)$/);
      if (heading) {
        blocks.push({
          type: "heading",
          level: heading[1].length,
          inline: inline(heading[2].trim()),
        });
        index += 1;
        continue;
      }
      const quote = line.match(/^\s*>\s?(.*)$/);
      if (quote) {
        const parts = [quote[1]];
        index += 1;
        while (index < lines.length) {
          const next = lines[index].match(/^\s*>\s?(.*)$/);
          if (!next) break;
          parts.push(next[1]);
          index += 1;
        }
        blocks.push({ type: "quote", inline: inline(joinLines(parts)) });
        continue;
      }
      const list = line.match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);
      if (list) {
        const ordered = Boolean(list[2]);
        const items = [];
        while (index < lines.length) {
          const item = lines[index].match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);
          if (!item || Boolean(item[2]) !== ordered) break;
          items.push(inline(item[3].trim()));
          index += 1;
        }
        blocks.push({ type: ordered ? "ol" : "ul", items });
        continue;
      }
      if (/^\s*```/.test(line)) {
        const code = [];
        index += 1;
        while (index < lines.length && !/^\s*```/.test(lines[index])) {
          code.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push({ type: "code-block", value: code.join("\n") });
        continue;
      }

      const paragraph = [line];
      index += 1;
      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^\s*(---+|\*\*\*+|___+)\s*$/.test(lines[index]) &&
        !/^\s*(#{1,3})\s+/.test(lines[index]) &&
        !/^\s*>/.test(lines[index]) &&
        !/^\s*(?:[-+*]|\d+\.)\s+/.test(lines[index]) &&
        !/^\s*```/.test(lines[index])
      ) {
        paragraph.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "paragraph", inline: inline(joinLines(paragraph)) });
    }
    return blocks;
  }

  function appendInline(parent, tokens) {
    for (const token of tokens) {
      if (token.type === "text") {
        parent.append(document.createTextNode(token.value));
        continue;
      }
      const element = document.createElement(
        token.type === "strong" ? "strong" : token.type === "code" ? "code" : "a",
      );
      element.textContent = token.value;
      if (token.type === "link") {
        element.href = token.href;
        element.target = "_blank";
        element.rel = "noopener noreferrer";
      }
      parent.append(element);
    }
  }

  function render(container, source) {
    const fragment = document.createDocumentFragment();
    for (const block of parse(source)) {
      if (block.type === "hr") {
        fragment.append(document.createElement("hr"));
        continue;
      }
      if (block.type === "code-block") {
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = block.value;
        pre.append(code);
        fragment.append(pre);
        continue;
      }
      if (block.type === "ul" || block.type === "ol") {
        const list = document.createElement(block.type);
        for (const item of block.items) {
          const li = document.createElement("li");
          appendInline(li, item);
          list.append(li);
        }
        fragment.append(list);
        continue;
      }
      const tag = block.type === "heading" ? "h" + block.level : block.type === "quote" ? "blockquote" : "p";
      const element = document.createElement(tag);
      appendInline(element, block.inline);
      fragment.append(element);
    }
    container.classList.add("rich-text");
    container.replaceChildren(fragment);
  }

  root.HoneyOSMessageFormat = Object.freeze({ parse, render });
})(typeof window !== "undefined" ? window : globalThis);
