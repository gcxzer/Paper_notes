function isPdfLinkAnnotation(annotation) {
  return annotation?.subtype === "Link" || annotation?.annotationType === pdfjsLib?.AnnotationType?.LINK;
}

function normalizePdfLinkAnnotation(annotation, viewport) {
  if (!isPdfLinkAnnotation(annotation) || !Array.isArray(annotation.rect)) return null;
  const rect = viewport.convertToViewportRectangle(annotation.rect);
  const left = Math.min(rect[0], rect[2]);
  const top = Math.min(rect[1], rect[3]);
  const right = Math.max(rect[0], rect[2]);
  const bottom = Math.max(rect[1], rect[3]);
  const link = {
    rect: normalizeAnnotationRect({
      x: left / viewport.width,
      y: top / viewport.height,
      w: (right - left) / viewport.width,
      h: (bottom - top) / viewport.height
    }),
    url: normalizeText(annotation.url || annotation.unsafeUrl),
    dest: annotation.dest || null,
    action: normalizeText(annotation.action),
    title: normalizeText(annotation.title || annotation.contents)
  };
  if (!link.url && !link.dest && !link.action) return null;
  return link.rect.w > 0 && link.rect.h > 0 ? link : null;
}

async function pdfLinkAnnotationsForPage(page, viewport) {
  try {
    const annotations = await page.getAnnotations({ intent: "display" });
    return annotations
      .map((annotation) => normalizePdfLinkAnnotation(annotation, viewport))
      .filter(Boolean);
  } catch (error) {
    console.warn("Failed to read PDF links.", error);
    return [];
  }
}

function pdfLinkLabel(link) {
  if (link.url) return `Open ${link.url}`;
  if (link.dest) return "Go to linked PDF location";
  if (link.action) return `Run PDF action ${link.action}`;
  return "PDF link";
}

function renderPdfLinksForPage(pageElement) {
  const layer = pageElement.querySelector(".pdf-link-layer");
  if (!layer) return;
  layer.innerHTML = "";
  const box = pageViewportBox(pageElement);
  (pageElement._pdfLinks || []).forEach((link, index) => {
    const hitbox = document.createElement("button");
    hitbox.type = "button";
    hitbox.className = "pdf-link-hitbox";
    hitbox.dataset.pdfLinkIndex = String(index);
    hitbox.setAttribute("aria-label", pdfLinkLabel(link));
    hitbox.title = link.url || normalizeText(link.dest) || normalizeText(link.action) || "PDF link";
    applyRectStyle(hitbox, link.rect, box);
    hitbox.addEventListener("click", (event) => {
      if (pdfState.mode !== "pan") return;
      if (normalizeText(window.getSelection()?.toString())) return;
      event.preventDefault();
      event.stopPropagation();
      activatePdfLink(link, pageElement);
    });
    layer.appendChild(hitbox);
  });
}

function pdfLinkAtPoint(event, pageElement) {
  if (pdfState.mode !== "pan") return null;
  if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return null;
  const links = pageElement._pdfLinks || [];
  if (!links.length) return null;
  const point = normalizedPointer(event, pageElement);
  return links.find((link) => {
    const rect = link.rect;
    return point.x >= rect.x && point.x <= rect.x + rect.w && point.y >= rect.y && point.y <= rect.y + rect.h;
  }) || null;
}

function targetPageElement(pageNumber) {
  return elements.pdfViewer?.querySelector(`.pdf-page[data-page="${pageNumber}"]`) || null;
}

async function pageNumberFromDestination(destination) {
  if (!Array.isArray(destination) || !pdfState.document) return 1;
  const pageRef = destination[0];
  if (typeof pageRef === "number") return pageRef + 1;
  try {
    return (await pdfState.document.getPageIndex(pageRef)) + 1;
  } catch (error) {
    console.warn("Failed to resolve PDF destination page.", error);
    return 1;
  }
}

function showPdfLinkBackButton(position) {
  if (!position || !elements.pdfLinkReturn) return;
  pdfState.linkReturnPosition = position;
  elements.pdfLinkReturn.hidden = false;
}

function hidePdfLinkBackButton() {
  pdfState.linkReturnPosition = null;
  if (elements.pdfLinkReturn) elements.pdfLinkReturn.hidden = true;
}

function returnFromPdfLink() {
  if (!pdfState.linkReturnPosition) return;
  scrollToPdfPosition(pdfState.linkReturnPosition, "smooth");
  hidePdfLinkBackButton();
}

function destinationTopValue(destination) {
  if (!Array.isArray(destination)) return null;
  const mode = typeof destination[1] === "string" ? destination[1] : destination[1]?.name;
  const value = {
    XYZ: destination[3],
    FitH: destination[2],
    FitBH: destination[2],
    FitR: destination[5]
  }[mode] ?? null;
  if (value == null) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function sectionNumberFromDestination(destinationName) {
  const match = normalizeText(destinationName).match(/^section\.([A-Za-z0-9.]+)$/);
  return match ? match[1] : "";
}

function pdfDestinationTargetKind(destinationName) {
  const name = normalizeText(destinationName).toLowerCase();
  if (!name) return "";
  if (/^(figure|table)\.caption(?:\.|$)/.test(name)) return "object";
  if (/^(figure|table)\./.test(name)) return "object";
  if (/^(equation|eq)(?:\.|$)/.test(name)) return "object";
  if (/^section\./.test(name)) return "section";
  return "";
}

function shouldSnapPdfTargetToText(options = {}) {
  if (normalizeText(options.sectionNumber)) return true;
  return pdfDestinationTargetKind(options.destinationName) !== "object";
}

function pdfCaptionTargetKind(destinationName) {
  const match = normalizeText(destinationName).toLowerCase().match(/^(figure|table)\.caption(?:\.|$)/);
  return match ? match[1] : "";
}

function pdfCaptionLinePattern(kind, number = "") {
  const targetNumber = normalizeText(number);
  const numberPattern = targetNumber ? escapeRegExp(targetNumber) : "\\d+[A-Za-z]?";
  if (kind === "figure") return new RegExp(`^Figure\\s+${numberPattern}(?:\\s*\\([^)]+\\))?\\s*(?:[|:.\\-–—]|$)`, "i");
  if (kind === "table") return new RegExp(`^Table\\s+${numberPattern}(?:\\s*\\([^)]+\\))?\\s*(?:[|:.\\-–—]|$)`, "i");
  return null;
}

function lineTextFromItems(items) {
  return normalizeText(items
    .slice()
    .sort((a, b) => a.rect.left - b.rect.left)
    .map((item) => item.text || item.span?.textContent || "")
    .join("")
    .replace(/\s+/g, " "));
}

function sectionHeadingPattern(sectionNumber) {
  const pieces = normalizeText(sectionNumber).split(".").map(escapeRegExp);
  return new RegExp(`^${pieces.join("\\s*\\.\\s*")}(?:\\s|$|[.)])`);
}

function splitPdfTargetLineItems(items) {
  const sorted = items.slice().sort((a, b) => a.rect.left - b.rect.left);
  const typicalHeight = medianNumber(sorted.map((item) => item.rect.height), 20);
  const gapThreshold = Math.max(72, typicalHeight * 3.5);
  return sorted.reduce((clusters, item) => {
    const current = clusters[clusters.length - 1];
    const previous = current?.[current.length - 1];
    if (!previous || item.rect.left - previous.rect.right <= gapThreshold) {
      if (current) current.push(item);
      else clusters.push([item]);
    } else {
      clusters.push([item]);
    }
    return clusters;
  }, []);
}

function pdfTextLineBounds(pageElement) {
  const pageBox = pageElement.getBoundingClientRect();
  const spans = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
    .map((span) => ({ span, rect: span.getBoundingClientRect(), text: span.textContent || "" }))
    .filter((entry) => normalizeText(entry.text) && entry.rect.width > 0 && entry.rect.height > 0);
  return groupTextItemsByLine(spans).flatMap((line) => splitPdfTargetLineItems(line.items).map((items) => {
      const bounds = lineBoundsFromItems(items);
      const localTop = bounds.top - pageBox.top;
      const localBottom = bounds.bottom - pageBox.top;
      return {
        ...bounds,
        localTop,
        localBottom,
        localCenter: (localTop + localBottom) / 2,
        localHeight: Math.max(1, localBottom - localTop),
        text: lineTextFromItems(items)
      };
    }))
    .filter((line) => (
    normalizeText(line.text)
    && line.localBottom >= -40
    && line.localTop <= pageBox.height + 40
  ))
    .sort((a, b) => a.localTop - b.localTop || a.left - b.left);
}

function pdfLinkSourceContext(link, pageElement) {
  if (!link || !pageElement) return null;
  const pageBox = pageElement.getBoundingClientRect();
  const linkRect = {
    left: pageBox.left + link.rect.x * pageBox.width,
    right: pageBox.left + (link.rect.x + link.rect.w) * pageBox.width,
    top: pageBox.top + link.rect.y * pageBox.height,
    bottom: pageBox.top + (link.rect.y + link.rect.h) * pageBox.height
  };
  const expandedRect = {
    left: linkRect.left - 3,
    right: linkRect.right + 3,
    top: linkRect.top - 3,
    bottom: linkRect.bottom + 3
  };
  const selectedText = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
    .filter((span) => rectsIntersect(span.getBoundingClientRect(), expandedRect))
    .map((span) => (typeof sliceSpanTextByRect === "function"
      ? sliceSpanTextByRect(span, expandedRect)
      : span.textContent || ""))
    .join("");
  const localCenter = ((linkRect.top + linkRect.bottom) / 2) - pageBox.top;
  const line = pdfTextLineBounds(pageElement)
    .slice()
    .sort((a, b) => Math.abs(a.localCenter - localCenter) - Math.abs(b.localCenter - localCenter))[0];
  return {
    selectedText: normalizeText(selectedText),
    lineText: normalizeText(line?.text)
  };
}

function pdfCaptionNumberFromSourceContext(sourceContext, kind) {
  const selectedText = normalizeText(sourceContext?.selectedText);
  const directNumber = selectedText.match(/\b(\d+[A-Za-z]?)\b/);
  if (directNumber) return directNumber[1];

  const lineText = normalizeText(sourceContext?.lineText);
  const label = kind === "table" ? "Table" : "Figure";
  const lineNumber = lineText.match(new RegExp(`\\b${label}s?\\.?\\s+(\\d+[A-Za-z]?)`, "i"));
  return lineNumber ? lineNumber[1] : "";
}

function pdfCaptionLineBounds(lineBounds, y, options = {}) {
  const kind = pdfCaptionTargetKind(options.destinationName);
  const pattern = pdfCaptionLinePattern(kind, options.captionNumber);
  if (!pattern) return null;
  let candidates = lineBounds.filter((bounds) => pattern.test(bounds.text));
  if (!candidates.length && options.captionNumber) {
    const fallbackPattern = pdfCaptionLinePattern(kind);
    candidates = lineBounds.filter((bounds) => fallbackPattern.test(bounds.text));
  }
  if (!candidates.length) return null;

  if (kind === "figure" && Number.isFinite(y)) {
    const belowAnchor = candidates
      .filter((bounds) => bounds.localTop >= y - 40)
      .sort((a, b) => a.localTop - b.localTop || a.left - b.left)[0];
    if (belowAnchor) return belowAnchor;
  }

  if (Number.isFinite(y)) {
    return candidates
      .slice()
      .sort((a, b) => Math.abs(a.localCenter - y) - Math.abs(b.localCenter - y))[0];
  }
  return candidates[0];
}

function pdfTargetLineBounds(pageElement, y, options = {}) {
  if (!Number.isFinite(y)) return null;
  const lineBounds = pdfTextLineBounds(pageElement);
  if (!lineBounds.length) return null;

  const captionLine = pdfCaptionLineBounds(lineBounds, y, options);
  if (captionLine) return captionLine;
  if (!shouldSnapPdfTargetToText(options)) return null;

  const sectionNumber = normalizeText(options.sectionNumber);
  if (sectionNumber) {
    const headingPattern = sectionHeadingPattern(sectionNumber);
    const sectionLine = lineBounds.find((bounds) => (
      bounds.localTop >= y - 20
      && bounds.localTop <= y + 260
      && headingPattern.test(bounds.text)
    ));
    if (sectionLine) return sectionLine;
  }

  const insideLine = lineBounds.find((bounds) => (
    y >= bounds.localTop + Math.min(8, bounds.localHeight * 0.25)
    && y <= bounds.localBottom - Math.min(2, bounds.localHeight * 0.08)
  ));
  const belowLine = lineBounds
    .filter((bounds) => bounds.localTop >= y - Math.max(6, bounds.localHeight * 0.2))
    .sort((a, b) => a.localTop - b.localTop)[0];
  const nearestLine = lineBounds
    .slice()
    .sort((a, b) => Math.abs(a.localCenter - y) - Math.abs(b.localCenter - y))[0];
  return insideLine || belowLine || nearestLine || null;
}

function pdfTargetScrollY(pageElement, y, options = {}) {
  if (!Number.isFinite(y)) return y;
  const shouldUseTextTarget = normalizeText(options.sectionNumber) || pdfCaptionTargetKind(options.destinationName);
  if (!shouldUseTextTarget) return y;
  const targetLine = pdfTargetLineBounds(pageElement, y, options);
  return targetLine ? Math.max(0, targetLine.localTop - 18) : y;
}

function rawPdfTargetHighlightRect(pageElement, y) {
  const pageBox = pageElement.getBoundingClientRect();
  const height = Math.max(38, pageBox.height * 0.045);
  return {
    left: pageBox.width * 0.06,
    top: Math.max(0, Number.isFinite(y) ? y - 18 : pageBox.height * 0.06),
    width: pageBox.width * 0.88,
    height
  };
}

function pdfTargetHighlightRect(pageElement, y, options = {}) {
  const pageBox = pageElement.getBoundingClientRect();
  const bestLine = pdfTargetLineBounds(pageElement, y, options);

  if (!bestLine) {
    return rawPdfTargetHighlightRect(pageElement, y);
  }

  return {
    left: Math.max(0, bestLine.left - pageBox.left - 8),
    top: Math.max(0, bestLine.top - pageBox.top - 6),
    width: Math.min(pageBox.width, bestLine.right - bestLine.left + 16),
    height: Math.max(30, bestLine.bottom - bestLine.top + 12)
  };
}

function flashPdfJumpTarget(pageElement, y = null, options = {}) {
  if (!pageElement) return;
  pageElement.querySelectorAll(".pdf-link-target-flash").forEach((element) => element.remove());
  const rect = pdfTargetHighlightRect(pageElement, y, options);
  const marker = document.createElement("div");
  marker.className = "pdf-link-target-flash";
  marker.style.left = `${rect.left}px`;
  marker.style.top = `${rect.top}px`;
  marker.style.width = `${rect.width}px`;
  marker.style.height = `${rect.height}px`;
  pageElement.appendChild(marker);
  window.setTimeout(() => marker.remove(), 2600);
}

async function scrollToPdfDestination(rawDestination, sourceContext = null) {
  if (!rawDestination || !pdfState.document) return false;
  const destinationName = typeof rawDestination === "string" ? rawDestination : "";
  const captionKind = pdfCaptionTargetKind(destinationName);
  const targetOptions = {
    destinationName,
    sectionNumber: sectionNumberFromDestination(destinationName),
    captionNumber: pdfCaptionNumberFromSourceContext(sourceContext, captionKind)
  };
  const destination = typeof rawDestination === "string"
    ? await pdfState.document.getDestination(rawDestination)
    : rawDestination;
  if (!Array.isArray(destination)) return false;

  const pageNumber = await pageNumberFromDestination(destination);
  const pageElement = targetPageElement(pageNumber);
  if (!pageElement) return false;

  const topValue = destinationTopValue(destination);
  if (!Number.isFinite(topValue)) {
    pageElement.scrollIntoView({ block: "start", behavior: "smooth" });
    window.setTimeout(() => flashPdfJumpTarget(pageElement), 280);
    return true;
  }

  const page = await pdfState.document.getPage(pageNumber);
  const viewport = page.getViewport({ scale: pdfState.scale });
  const [, y] = viewport.convertToViewportPoint(0, topValue);
  const scrollY = pdfTargetScrollY(pageElement, y, targetOptions);
  const viewerBox = elements.pdfViewer.getBoundingClientRect();
  const pageBox = pageElement.getBoundingClientRect();
  elements.pdfViewer.scrollTo({
    top: elements.pdfViewer.scrollTop + pageBox.top - viewerBox.top + scrollY - pdfScrollAnchorOffset(),
    behavior: "smooth"
  });
  window.setTimeout(() => flashPdfJumpTarget(pageElement, y, targetOptions), 280);
  return true;
}

function scrollToPdfNamedAction(action) {
  const pageCount = Number(pdfState.document?.numPages || pdfState.document?._pdfInfo?.numPages || 0);
  const currentPage = currentPdfScrollPosition()?.page || 1;
  const actions = {
    FirstPage: 1,
    LastPage: pageCount,
    NextPage: Math.min(pageCount, currentPage + 1),
    PrevPage: Math.max(1, currentPage - 1)
  };
  const pageNumber = actions[action];
  if (!pageNumber) return false;
  const pageElement = targetPageElement(pageNumber);
  pageElement?.scrollIntoView({ block: "start", behavior: "smooth" });
  window.setTimeout(() => flashPdfJumpTarget(pageElement), 280);
  return true;
}

async function activatePdfLink(link, sourcePageElement = null) {
  if (link.url) {
    window.open(link.url, "_blank", "noopener,noreferrer");
    return;
  }
  if (link.dest) {
    const returnPosition = currentPdfScrollPosition();
    const didNavigate = await scrollToPdfDestination(link.dest, pdfLinkSourceContext(link, sourcePageElement));
    if (didNavigate) showPdfLinkBackButton(returnPosition);
    return;
  }
  if (link.action) {
    const returnPosition = currentPdfScrollPosition();
    if (scrollToPdfNamedAction(link.action)) showPdfLinkBackButton(returnPosition);
  }
}

function handlePdfLinkClick(event) {
  if (normalizeText(window.getSelection()?.toString())) return;
  const link = pdfLinkAtPoint(event, event.currentTarget);
  if (!link) return;
  event.preventDefault();
  event.stopPropagation();
  activatePdfLink(link, event.currentTarget);
}

function handlePdfLinkPointerMove(event) {
  const link = pdfLinkAtPoint(event, event.currentTarget);
  event.currentTarget.classList.toggle("is-over-pdf-link", Boolean(link));
}

function wirePageAnnotationEvents(pageElement) {
  pageElement.addEventListener("click", handlePdfLinkClick);
  pageElement.addEventListener("click", (event) => handlePdfAnnotationClick(event, pageElement));
  pageElement.addEventListener("pointermove", handlePdfLinkPointerMove);
  pageElement.addEventListener("pointerleave", () => pageElement.classList.remove("is-over-pdf-link"));
  pageElement.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || pdfState.mode === "pan") return;
    if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return;
    if (pdfState.mode === "note") {
      event.preventDefault();
      addNoteAnnotation(event, pageElement);
    }
  });
  pageElement.addEventListener("pointerup", (event) => {
    if (!["highlight", "underline"].includes(pdfState.mode)) return;
    if (event.target.closest(".pdf-annotation, .pdf-annotation-editor")) return;
    finishSelectionAnnotation(pageElement, pdfState.mode);
  });
}
