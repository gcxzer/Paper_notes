function safeChatLinkHref(rawHref) {
  const href = normalizeText(rawHref);
  if (!href) return "";
  const sandboxMedia = href.match(/^sandbox:(\/api\/media\/[A-Za-z0-9._~/%+-]+)$/i);
  if (sandboxMedia) return sandboxMedia[1];
  if (/^https?:\/\//i.test(href)) {
    try {
      return new URL(href).href;
    } catch (error) {
      return "";
    }
  }
  if (/^\/api\/media\/[A-Za-z0-9._~/%+-]+$/i.test(href)) {
    return href;
  }
  if (/^\/?(resources|assets)\//i.test(href) || /^\/(?!api\/)[A-Za-z0-9._~/%+-]+$/i.test(href)) {
    return href;
  }
  return "";
}

function safeChatImageHref(rawHref) {
  return safeChatLinkHref(rawHref);
}

function splitTrailingUrlPunctuation(url) {
  let trimmed = url;
  let trailing = "";
  while (/[.,!?;:，。！？；：、]$/.test(trimmed)) {
    trailing = trimmed.slice(-1) + trailing;
    trimmed = trimmed.slice(0, -1);
  }
  return [trimmed, trailing];
}

function renderChatMathExpression(source, displayMode = false) {
  const formula = String(source || "").trim();
  if (!formula) return "";
  if (globalThis.katex?.renderToString) {
    return globalThis.katex.renderToString(formula, {
      displayMode,
      throwOnError: false,
      strict: "ignore",
      trust: false
    });
  }
  const tag = displayMode ? "div" : "span";
  return `<${tag} class="chat-math-fallback">${escapeHtml(formula)}</${tag}>`;
}

function extractChatMathSegments(text) {
  const mathSegments = [];
  const protect = (displayMode) => (_, formula) => {
    const token = `@@CHATMATH${mathSegments.length}@@`;
    mathSegments.push({
      displayMode,
      html: renderChatMathExpression(formula, displayMode)
    });
    return token;
  };
  const protectInlineDollarMath = (match, prefix, formula) => {
    const normalizedFormula = String(formula || "").trim();
    if (!normalizedFormula) return match;
    return `${prefix}${protect(false)(match, normalizedFormula)}`;
  };
  const source = String(text || "")
    .replace(/\\\[([\s\S]*?)\\\]/g, protect(true))
    .replace(/\$\$([\s\S]*?)\$\$/g, protect(true))
    .replace(/\\\(([\s\S]*?)\\\)/g, protect(false))
    .replace(/(^|[^\\$])\$([^\s$\n](?:[^\n$]*?[^\s$\n])?)\$(?![\d$])/g, protectInlineDollarMath);
  return { source, mathSegments };
}

function restoreChatMathSegments(html, mathSegments) {
  let output = String(html || "");
  mathSegments.forEach((segment, index) => {
    const token = `@@CHATMATH${index}@@`;
    const replacement = segment.displayMode
      ? `<div class="chat-math-block">${segment.html}</div>`
      : `<span class="chat-math-inline">${segment.html}</span>`;
    output = output.replaceAll(`<p>${token}</p>`, replacement);
    output = output.replaceAll(token, replacement);
  });
  return output;
}

function renderChatMarkdown(text) {
  const source = normalizeText(text);
  if (!source) return "";
  const codeBlocks = [];
  const withCodeBlocks = source.replace(/```([A-Za-z0-9_+.-]*)[ \t]*\n([\s\S]*?)```/g, (_, language, code) => {
    const token = `@@CODEBLOCK${codeBlocks.length}@@`;
    codeBlocks.push(renderChatCodeBlock(normalizeFencedCode(code), language));
    return token;
  });
  const { source: withMath, mathSegments } = extractChatMathSegments(withCodeBlocks);
  const codeSpans = [];
  const codeSpanLabels = [];
  let html = escapeHtml(withMath).replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `@@CODESPAN${codeSpans.length}@@`;
    codeSpans.push(`<code>${code}</code>`);
    codeSpanLabels.push(code);
    return token;
  });
  html = html.replace(/\*\*([^*\n](?:[\s\S]*?[^*\n])?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_\n](?:[\s\S]*?[^_\n])?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*\*/g, "");
  html = html.replace(/__/g, "");
  html = html.replace(/~~([^~\n](?:[\s\S]*?[^~\n])?)~~/g, "<del>$1</del>");
  html = html.replace(/~~/g, "");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/g, "$1<em>$2</em>");
  const imageSpans = [];
  html = html.replace(/!\[([^\]\n]{0,240})\]\(([^)\s]+)(?:\s+"[^"]{0,160}")?\)/g, (match, alt, href) => {
    const safeHref = safeChatImageHref(href);
    if (!safeHref) return match;
    const token = `@@IMAGESPAN${imageSpans.length}@@`;
    const altText = alt.replace(/@@CODESPAN(\d+)@@/g, (spanToken, index) => codeSpanLabels[Number(index)] ?? spanToken);
    imageSpans.push(`<a class="chat-markdown-image-link" href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer"><img class="chat-markdown-image" src="${escapeHtml(safeHref)}" alt="${escapeHtml(altText)}" loading="lazy" decoding="async"></a>`);
    return token;
  });
  const linkSpans = [];
  html = html.replace(/\[([^\]\n]{1,240})\]\(([^)\s]+)\)/g, (match, label, href) => {
    const safeHref = safeChatLinkHref(href);
    if (!safeHref) return match;
    const token = `@@LINKSPAN${linkSpans.length}@@`;
    const linkLabel = label.replace(/@@CODESPAN(\d+)@@/g, (spanToken, index) => codeSpanLabels[Number(index)] ?? spanToken);
    linkSpans.push(`<a href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer">${linkLabel}</a>`);
    return token;
  });
  html = html.replace(/(https?:\/\/[^\s<>"'()[\]{}（）【】《》]+)/gi, (url) => {
    const [hrefCandidate, trailing] = splitTrailingUrlPunctuation(url);
    const safeHref = safeChatLinkHref(hrefCandidate);
    return safeHref
      ? `<a href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer">${hrefCandidate}</a>${trailing}`
      : url;
  });
  html = html.replace(/(^|[\s(])((?:\/api\/media\/)[A-Za-z0-9._~/%+-]+)(?=$|[\s).,!?;:])/g, (match, prefix, path) => (
    `${prefix}<a href="${escapeHtml(path)}" target="_blank" rel="noopener noreferrer">${path}</a>`
  ));
  html = renderChatMarkdownBlocks(html);
  linkSpans.forEach((link, index) => {
    html = html.replace(`@@LINKSPAN${index}@@`, link);
  });
  imageSpans.forEach((image, index) => {
    html = html.replace(`@@IMAGESPAN${index}@@`, image);
  });
  codeSpans.forEach((code, index) => {
    html = html.replace(`@@CODESPAN${index}@@`, code);
  });
  html = restoreChatCodeBlocks(html, codeBlocks);
  return restoreChatMathSegments(html, mathSegments);
}

function renderTraceInlineMarkdown(text) {
  const source = normalizeText(text);
  if (!source) return "";
  let html = escapeHtml(source);
  html = html.replace(/\*\*([^*\n](?:[\s\S]*?[^*\n])?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_\n](?:[\s\S]*?[^_\n])?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*\*/g, "");
  html = html.replace(/__/g, "");
  return html;
}

function renderChatMarkdownBlocks(html) {
  const lines = String(html || "").split(/\r?\n/);
  const output = [];
  const listStack = [];
  let blockquote = [];

  const leadingSpaces = (value) => (String(value || "").match(/^\s*/) || [""])[0].replace(/\t/g, "  ").length;
  const listStartAttr = (type, start = "") => (
    type === "ol" && start ? ` start="${escapeHtml(start)}"` : ""
  );
  const closeTopList = () => {
    const top = listStack.pop();
    if (!top) return;
    if (top.openLi) output.push("</li>");
    output.push(`</${top.type}>`);
  };
  const closeListsDeeperThan = (indent) => {
    while (listStack.length && listStack[listStack.length - 1].indent > indent) {
      closeTopList();
    }
  };
  const closeLists = () => {
    while (listStack.length) closeTopList();
  };
  const closeBlockquote = () => {
    if (!blockquote.length) return;
    closeLists();
    output.push(`<blockquote>${blockquote.join("<br>")}</blockquote>`);
    blockquote = [];
  };
  const renderListItem = ({ type, indent, content, start = "", task = null }) => {
    closeBlockquote();
    closeListsDeeperThan(indent);
    let current = listStack[listStack.length - 1];
    if (!current || current.indent < indent || current.type !== type) {
      if (current && current.indent === indent && current.type !== type) {
        closeTopList();
      }
      output.push(`<${type}${listStartAttr(type, start)}>`);
      current = { type, indent, openLi: false };
      listStack.push(current);
    } else if (current.openLi) {
      output.push("</li>");
      current.openLi = false;
    }
    current.openLi = true;
    if (task) {
      const checked = task.checked ? " checked" : "";
      output.push(`<li class="chat-task-list-item"><span class="chat-task-list-row"><input type="checkbox" disabled${checked}><span class="chat-task-list-text">${content}</span></span>`);
      return;
    }
    output.push(`<li>${content}`);
  };
  const closeBlocks = () => {
    closeBlockquote();
    closeLists();
  };
  const tableSeparator = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const tableRow = (line) => /^\s*\|.+\|\s*$/.test(line);
  const tableCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  const renderTable = (tableLines) => {
    const header = tableCells(tableLines[0]);
    const rows = tableLines.slice(2).map(tableCells);
    return `
      <div class="chat-table-wrap">
        <table class="chat-markdown-table">
          <thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>
          <tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>
      </div>
    `;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      closeBlocks();
      continue;
    }
    if (tableRow(line) && tableSeparator(lines[index + 1] || "")) {
      closeBlocks();
      const tableLines = [line, lines[index + 1].trimEnd()];
      index += 2;
      while (index < lines.length && tableRow(lines[index])) {
        tableLines.push(lines[index].trimEnd());
        index += 1;
      }
      index -= 1;
      output.push(renderTable(tableLines));
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      closeBlocks();
      const level = Math.min(6, heading[1].length);
      output.push(`<h${level}>${heading[2].trim()}</h${level}>`);
      continue;
    }
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      closeBlocks();
      output.push("<hr>");
      continue;
    }
    const unordered = line.match(/^(\s*)[-*+]\s+(?:(\[( |x|X)\])\s+)?(.+)$/);
    if (unordered) {
      renderListItem({
        type: "ul",
        indent: leadingSpaces(unordered[1]),
        content: unordered[4],
        task: unordered[2] ? { checked: unordered[3]?.toLowerCase() === "x" } : null
      });
      continue;
    }
    const ordered = line.match(/^(\s*)(\d+)[.)]\s+(.+)$/);
    if (ordered) {
      renderListItem({
        type: "ol",
        indent: leadingSpaces(ordered[1]),
        start: ordered[2],
        content: ordered[3]
      });
      continue;
    }
    const quote = line.match(/^\s*(?:>|&gt;)\s?(.*)$/);
    if (quote) {
      closeLists();
      blockquote.push(quote[1]);
      continue;
    }
    closeBlocks();
    output.push(`<p>${line}</p>`);
  }
  closeBlocks();
  return output.join("");
}

function normalizeFencedCode(code) {
  return String(code || "").replace(/^(?:[ \t]*\r?\n)+/, "").replace(/(?:\r?\n[ \t]*)+$/, "");
}

function restoreChatCodeBlocks(html, codeBlocks) {
  let output = String(html || "");
  codeBlocks.forEach((block, index) => {
    const token = `@@CODEBLOCK${index}@@`;
    output = output.replaceAll(`<p>${token}</p>`, block);
    output = output.replaceAll(token, block);
  });
  return output;
}

function isMermaidCodeBlockLanguage(language = "") {
  return ["mermaid", "mmd"].includes(normalizeText(language).trim().toLowerCase());
}

function renderChatCodeBlock(code, language = "") {
  const normalizedCode = String(code || "");
  const label = normalizeText(language);
  if (isMermaidCodeBlockLanguage(label)) return renderChatMermaidBlock(normalizedCode);
  return `<div class="chat-code-block">${label ? `<div class="chat-code-language">${escapeHtml(label)}</div>` : ""}<pre><code>${escapeHtml(normalizedCode)}</code></pre><button class="chat-code-copy" type="button" data-code-copy="${escapeHtml(encodeURIComponent(normalizedCode))}">Copy</button></div>`;
}

function renderChatMermaidBlock(code) {
  const normalizedCode = String(code || "");
  const encodedCode = escapeHtml(encodeURIComponent(normalizedCode));
  return `
    <div class="chat-mermaid-block">
      <div class="chat-mermaid-header">
        <div class="chat-code-language">mermaid</div>
        <button class="chat-code-copy" type="button" data-code-copy="${encodedCode}">Copy</button>
      </div>
      <div class="chat-mermaid-diagram" data-mermaid-code="${encodedCode}" aria-label="Mermaid diagram">
        <pre class="chat-mermaid-source"><code>${escapeHtml(normalizedCode)}</code></pre>
      </div>
    </div>
  `;
}

let chatMermaidRenderCounter = 0;

function decodeChatMermaidCode(element) {
  try {
    return decodeURIComponent(element?.dataset?.mermaidCode || "");
  } catch (error) {
    console.warn("Could not decode Mermaid source.", error);
    return "";
  }
}

function scheduleChatMermaidRender(container, { keepScrolledToBottom = false } = {}) {
  if (!container?.querySelector?.(".chat-mermaid-diagram")) return;
  requestAnimationFrame(() => {
    renderChatMermaidDiagrams(container)
      .then(() => {
        if (keepScrolledToBottom && container.isConnected) {
          container.scrollTop = container.scrollHeight;
        }
      })
      .catch((error) => console.warn("Failed to render Mermaid diagrams.", error));
  });
}

async function renderChatMermaidDiagrams(container = elements.readerChatMessages) {
  const mermaid = globalThis.mermaid;
  if (!container || !mermaid?.render) return;
  const diagrams = Array.from(container.querySelectorAll(".chat-mermaid-diagram:not([data-mermaid-status])"));
  await Promise.all(diagrams.map((diagram) => renderChatMermaidDiagram(diagram, mermaid)));
}

async function renderChatMermaidDiagram(diagram, mermaid) {
  const code = decodeChatMermaidCode(diagram).trim();
  if (!code) return;
  const renderId = `chat-mermaid-svg-${Date.now()}-${chatMermaidRenderCounter += 1}`;
  diagram.dataset.mermaidStatus = "rendering";
  diagram.dataset.mermaidRenderId = renderId;
  try {
    const result = await mermaid.render(renderId, code);
    if (!diagram.isConnected || diagram.dataset.mermaidRenderId !== renderId) return;
    diagram.innerHTML = result.svg;
    diagram.dataset.mermaidStatus = "rendered";
    diagram.closest(".chat-mermaid-block")?.classList.add("is-rendered");
    if (typeof result.bindFunctions === "function") result.bindFunctions(diagram);
  } catch (error) {
    if (!diagram.isConnected || diagram.dataset.mermaidRenderId !== renderId) return;
    diagram.dataset.mermaidStatus = "error";
    diagram.closest(".chat-mermaid-block")?.classList.add("is-error");
    diagram.innerHTML = `
      <div class="chat-mermaid-error">Could not render Mermaid diagram.</div>
      <pre class="chat-mermaid-source"><code>${escapeHtml(code)}</code></pre>
    `;
    console.warn("Could not render Mermaid diagram.", error);
  }
}
