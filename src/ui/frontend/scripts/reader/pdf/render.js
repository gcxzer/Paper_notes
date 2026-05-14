function measuredTextWidth(text, fontSize, fontFamily) {
  const canvas = measuredTextWidth.canvas || (measuredTextWidth.canvas = document.createElement("canvas"));
  const context = canvas.getContext("2d");
  context.font = `${fontSize}px ${fontFamily}`;
  return Math.max(0.001, context.measureText(text).width);
}

function textChunksFromGlyphs(glyphs) {
  const chunks = [];
  let advance = 0;
  let chunk = null;

  const flush = () => {
    if (!chunk || !chunk.text) return;
    chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
    chunks.push(chunk);
    chunk = null;
  };

  glyphs.forEach((entry) => {
    if (typeof entry === "number") {
      if (entry <= -100 && chunk?.text) {
        chunk.text += " ";
        advance += -entry;
        chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
        flush();
        return;
      }
      advance += -entry;
      return;
    }
    const text = cleanDamagedPdfGlyphText(entry?.unicode || "");
    if (!text) {
      advance += Number(entry?.width) || 0;
      return;
    }
    if (!chunk) chunk = { text: "", startUnits: advance, widthUnits: 0 };
    chunk.text += text;
    advance += Number(entry.width) || 0;
    chunk.widthUnits = Math.max(0.001, advance - chunk.startUnits);
    if (entry.isSpace || /\s$/.test(text)) flush();
  });
  flush();

  return { chunks, advanceUnits: advance };
}

function appendTextLayerChunk(container, viewport, matrix, fontSize, fontFamily, chunk) {
  const offset = chunk.startUnits * fontSize / 1000;
  const x = matrix[4] + matrix[0] * offset;
  const y = matrix[5] + matrix[1] * offset;
  const transform = [
    matrix[0] * fontSize,
    matrix[1] * fontSize,
    matrix[2] * fontSize,
    matrix[3] * fontSize,
    x,
    y
  ];
  const tx = pdfjsLib.Util.transform(viewport.transform, transform);
  const angle = Math.atan2(tx[1], tx[0]);
  const fontHeight = Math.hypot(tx[2], tx[3]);
  const fontAscent = fontHeight * 0.8;
  const measuredWidth = measuredTextWidth(chunk.text, fontHeight, fontFamily);
  const targetWidth = Math.max(0.001, chunk.widthUnits * Math.hypot(tx[0], tx[1]) / 1000);
  const span = document.createElement("span");
  span.textContent = chunk.text;
  span.setAttribute("role", "presentation");
  span.style.left = `${tx[4]}px`;
  span.style.top = `${tx[5] - fontAscent}px`;
  span.style.width = `${measuredWidth}px`;
  span.style.fontSize = `${fontHeight}px`;
  span.style.fontFamily = fontFamily;
  span.style.transform = `${Math.abs(angle) > 0.001 ? `rotate(${angle}rad) ` : ""}scaleX(${targetWidth / measuredWidth})`;
  span.style.transformOrigin = "0% 0%";
  container.appendChild(span);
}

function textMatrixFromArgs(args, fallback) {
  const source = Array.isArray(args) && args.length === 1 && args[0] && typeof args[0] === "object"
    ? args[0]
    : args;
  const values = Array.isArray(source)
    ? source.slice(0, 6)
    : [source?.[0], source?.[1], source?.[2], source?.[3], source?.[4], source?.[5]];
  const matrix = values.map(Number);
  return matrix.length === 6 && matrix.every(Number.isFinite) ? matrix : fallback;
}

async function renderOperatorTextLayer(page, textContent, viewport, container) {
  const opList = await page.getOperatorList();
  const ops = pdfjsLib.OPS || {};
  let fontSize = 10;
  let fontFamily = "sans-serif";
  let textMatrix = [1, 0, 0, 1, 0, 0];
  let lineMatrix = [1, 0, 0, 1, 0, 0];

  opList.fnArray.forEach((fn, index) => {
    const args = opList.argsArray[index];
    if (fn === ops.setFont) {
      fontSize = Number(args?.[1]) || fontSize;
      fontFamily = textContent.styles?.[args?.[0]]?.fontFamily || "sans-serif";
      return;
    }
    if (fn === ops.setTextMatrix) {
      textMatrix = textMatrixFromArgs(args, textMatrix);
      lineMatrix = textMatrix.slice();
      return;
    }
    if (fn === ops.moveText) {
      const dx = Number(args?.[0]) || 0;
      const dy = Number(args?.[1]) || 0;
      lineMatrix = lineMatrix.slice();
      lineMatrix[4] += dx;
      lineMatrix[5] += dy;
      textMatrix = lineMatrix.slice();
      return;
    }
    if (fn !== ops.showText) return;
    const glyphs = Array.isArray(args?.[0]) ? args[0] : [];
    const { chunks, advanceUnits } = textChunksFromGlyphs(glyphs);
    chunks.forEach((chunk) => appendTextLayerChunk(container, viewport, textMatrix, fontSize, fontFamily, chunk));
    const advance = advanceUnits * fontSize / 1000;
    textMatrix = textMatrix.slice();
    textMatrix[4] += textMatrix[0] * advance;
    textMatrix[5] += textMatrix[1] * advance;
  });
}

function appendTextLayerItem(container, viewport, item, style = {}) {
  const text = cleanDamagedPdfGlyphText(item?.str || "");
  if (!text) return;
  const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
  const angle = Math.atan2(tx[1], tx[0]);
  const fontHeight = Math.hypot(tx[2], tx[3]);
  const fontAscent = Number.isFinite(style.ascent)
    ? style.ascent * fontHeight
    : Number.isFinite(style.descent)
      ? (1 + style.descent) * fontHeight
      : fontHeight * 0.8;
  const fontFamily = style.fontFamily || "sans-serif";
  const measuredWidth = measuredTextWidth(text, fontHeight, fontFamily);
  const targetWidth = Math.max(0.001, (Number(item.width) || measuredWidth / Math.max(viewport.scale, 0.001)) * viewport.scale);
  const span = document.createElement("span");
  span.textContent = text;
  span.setAttribute("role", "presentation");
  span.style.left = `${tx[4] + (fontAscent * Math.sin(angle))}px`;
  span.style.top = `${tx[5] - (fontAscent * Math.cos(angle))}px`;
  span.style.width = `${measuredWidth}px`;
  span.style.fontSize = `${fontHeight}px`;
  span.style.fontFamily = fontFamily;
  span.style.transform = `${Math.abs(angle) > 0.001 ? `rotate(${angle}rad) ` : ""}scaleX(${targetWidth / measuredWidth})`;
  span.style.transformOrigin = "0% 0%";
  container.appendChild(span);
}

function renderTextContentLayer(textContent, viewport, container) {
  (textContent.items || []).forEach((item) => {
    appendTextLayerItem(container, viewport, item, textContent.styles?.[item.fontName]);
  });
}

async function renderPdfJsTextLayer(textContent, viewport, container) {
  if (typeof pdfjsLib.TextLayer === "function") {
    const layer = new pdfjsLib.TextLayer({
      textContentSource: textContent,
      container,
      viewport
    });
    const result = layer.render();
    if (result?.promise) {
      await result.promise;
    } else if (result && typeof result.then === "function") {
      await result;
    }
  } else if (typeof pdfjsLib.renderTextLayer === "function") {
    const task = pdfjsLib.renderTextLayer({
      textContentSource: textContent,
      container,
      viewport
    });
    await task.promise;
  } else {
    renderTextContentLayer(textContent, viewport, container);
  }

  container.querySelectorAll("span:not([role])").forEach((span) => {
    span.setAttribute("role", "presentation");
  });
}

async function renderSelectableTextLayer(page, textContent, viewport, container) {
  container.addEventListener("click", handleTextLayerMultiClick);
  container.addEventListener("click", (event) => {
    const pageElement = container.closest(".pdf-page");
    if (pageElement) handlePdfAnnotationClick(event, pageElement);
  });
  container.addEventListener("pointerdown", handleTextLayerPointerDown);
  container.addEventListener("pointermove", handleTextLayerPointerMove);
  container.addEventListener("pointerup", finishTextLayerPointerSelection);
  container.addEventListener("pointercancel", finishTextLayerPointerSelection);
  container.addEventListener("dblclick", handleTextLayerDoubleClick);
  container.addEventListener("mouseup", schedulePdfSelectionOverlayRender);
  container.addEventListener("copy", (event) => {
    const pageElement = container.closest(".pdf-page");
    const selectionText = typeof textFromPdfSelection === "function"
      ? textFromPdfSelection()
      : pageElement ? textFromSelectionForPage(pageElement) : window.getSelection()?.toString() || "";
    const normalized = normalizeCopiedPdfText(selectionText);
    if (!normalized) return;
    event.preventDefault();
    event.clipboardData?.setData("text/plain", normalized);
  });

  try {
    await renderOperatorTextLayer(page, textContent, viewport, container);
    if (container.querySelector("span[role='presentation']")) return;
  } catch (error) {
    console.warn("Precise text layer failed, falling back to PDF.js text layer.", error);
  }

  await renderPdfJsTextLayer(textContent, viewport, container);
}

async function renderPdfPage(pageNumber, renderToken, scale, target = elements.pdfViewer, options = {}) {
  const page = await pdfState.document.getPage(pageNumber);
  if (renderToken !== pdfState.renderToken) return false;
  const viewport = page.getViewport({ scale });
  const outputScale = Math.min(window.devicePixelRatio || 1, 3);
  const pageElement = options.pageElement || document.createElement("section");
  const canvas = document.createElement("canvas");
  const selectionLayer = document.createElement("div");
  const textLayer = document.createElement("div");
  const linkLayer = document.createElement("div");
  const overlay = document.createElement("div");
  const context = canvas.getContext("2d");
  const ownsPageElement = !options.pageElement;

  pageElement.className = "pdf-page";
  pageElement.dataset.page = String(pageNumber);
  pageElement.dataset.rendering = "true";
  pageElement.replaceChildren();
  canvas.className = "pdf-page-canvas";
  selectionLayer.className = "pdf-selection-layer";
  textLayer.className = "textLayer pdf-text-layer";
  linkLayer.className = "pdf-link-layer";
  overlay.className = "pdf-annotation-layer";
  pageElement._pdfLinks = await pdfLinkAnnotationsForPage(page, viewport);
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  textLayer.style.width = `${viewport.width}px`;
  textLayer.style.height = `${viewport.height}px`;
  textLayer.style.setProperty("--scale-factor", String(viewport.scale));
  textLayer.style.setProperty("--total-scale-factor", String(viewport.scale));
  pageElement.style.setProperty("--scale-factor", String(viewport.scale));
  pageElement.style.setProperty("--total-scale-factor", String(viewport.scale));
  pageElement.style.width = `${viewport.width}px`;
  pageElement.style.height = `${viewport.height}px`;

  pageElement.append(canvas, selectionLayer, textLayer, linkLayer, overlay);
  if (renderToken !== pdfState.renderToken) return false;
  if (ownsPageElement) target.appendChild(pageElement);
  renderPdfLinksForPage(pageElement);
  wirePageAnnotationEvents(pageElement);
  const renderTask = page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0]
  }).promise;
  const textContent = await page.getTextContent();
  if (renderToken !== pdfState.renderToken) {
    if (ownsPageElement) pageElement.remove();
    return false;
  }
  await renderSelectableTextLayer(page, textContent, viewport, textLayer);
  await renderTask;
  if (renderToken !== pdfState.renderToken) {
    if (ownsPageElement) pageElement.remove();
    return false;
  }
  if (options.renderAnnotations !== false) {
    renderAnnotationsForPage(pageElement);
  }
  pageElement.removeAttribute("data-rendering");
  schedulePdfSelectionOverlayRender();
  return true;
}

function createPdfPagePlaceholder(pageNumber, scale, previousPage) {
  const pageElement = document.createElement("section");
  const previousScale = Number(previousPage?.style.getPropertyValue("--scale-factor")) || scale;
  const ratio = previousScale > 0 ? scale / previousScale : 1;
  const previousWidth = Number.parseFloat(previousPage?.style.width) || previousPage?.offsetWidth || 760;
  const previousHeight = Number.parseFloat(previousPage?.style.height) || previousPage?.offsetHeight || 980;
  pageElement.className = "pdf-page";
  pageElement.dataset.page = String(pageNumber);
  pageElement.dataset.rendering = "true";
  pageElement.style.setProperty("--scale-factor", String(scale));
  pageElement.style.setProperty("--total-scale-factor", String(scale));
  pageElement.style.width = `${Math.max(1, previousWidth * ratio)}px`;
  pageElement.style.height = `${Math.max(1, previousHeight * ratio)}px`;
  return pageElement;
}

function prioritizedPdfPageNumbers(pageCount, anchorPage) {
  const anchor = clamp(Math.round(Number(anchorPage) || 1), 1, Math.max(1, pageCount));
  const numbers = [anchor];
  for (let distance = 1; numbers.length < pageCount; distance += 1) {
    const before = anchor - distance;
    const after = anchor + distance;
    if (before >= 1) numbers.push(before);
    if (after <= pageCount) numbers.push(after);
  }
  return numbers;
}

async function renderPdfIntoExistingPlaceholders(renderToken, scale, positionToRestore, pageCount) {
  const previousPages = new Map(Array.from(elements.pdfViewer.querySelectorAll(".pdf-page"))
    .map((pageElement) => [Number(pageElement.dataset.page), pageElement]));
  const restorePage = clamp(Number(positionToRestore?.page) || 1, 1, Math.max(1, pageCount));
  const placeholders = [];
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    placeholders.push(createPdfPagePlaceholder(pageNumber, scale, previousPages.get(pageNumber)));
  }
  elements.pdfViewer.replaceChildren(...placeholders);
  restorePdfScrollPosition(positionToRestore);
  updatePdfPageControl(restorePage);
  await new Promise((resolve) => window.requestAnimationFrame(resolve));

  for (const pageNumber of prioritizedPdfPageNumbers(pageCount, restorePage)) {
    const pageElement = targetPageElement(pageNumber);
    if (!pageElement || renderToken !== pdfState.renderToken) {
      pdfState.suppressScrollSave = false;
      return false;
    }
    const rendered = await renderPdfPage(pageNumber, renderToken, scale, elements.pdfViewer, {
      pageElement,
      renderAnnotations: true
    });
    if (!rendered || renderToken !== pdfState.renderToken) {
      pdfState.suppressScrollSave = false;
      return false;
    }
    if (pageNumber === restorePage) {
      restorePdfScrollPosition(positionToRestore);
      updatePdfPageControl(restorePage);
    }
  }
  return true;
}

async function renderPdf() {
  if (!pdfState.document) return;
  const positionToRestore = currentPdfScrollPosition() || storedPdfScrollPosition();
  const renderToken = pdfState.renderToken + 1;
  const scale = pdfState.scale;
  const hasRenderedPages = Boolean(elements.pdfViewer.querySelector(".pdf-page"));
  const renderTarget = hasRenderedPages ? document.createDocumentFragment() : elements.pdfViewer;
  pdfState.renderToken = renderToken;
  pdfState.suppressScrollSave = true;
  if (!hasRenderedPages) elements.pdfViewer.innerHTML = "";
  if (elements.zoomLabel) elements.zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  const pageCount = pdfPageCount();
  updatePdfPageControl();
  if (!pageCount) {
    pdfState.suppressScrollSave = false;
    throw new Error("PDF loaded, but page count was unavailable.");
  }
  if (hasRenderedPages) {
    try {
      const rendered = await renderPdfIntoExistingPlaceholders(renderToken, scale, positionToRestore, pageCount);
      if (!rendered || renderToken !== pdfState.renderToken) return;
    } catch (error) {
      pdfState.suppressScrollSave = false;
      throw error;
    }
    schedulePdfSelectionOverlayRender();
    finishPdfScrollRestore(positionToRestore);
    return;
  }
  const restorePage = clamp(Number(positionToRestore?.page) || 1, 1, Math.max(1, pageCount));
  let restoredEarly = false;
  try {
    for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
      const rendered = await renderPdfPage(pageNumber, renderToken, scale, renderTarget, {
        renderAnnotations: !hasRenderedPages
      });
      if (!rendered || renderToken !== pdfState.renderToken) {
        pdfState.suppressScrollSave = false;
        return;
      }
      if (!hasRenderedPages && positionToRestore && !restoredEarly && pageNumber >= restorePage) {
        restoredEarly = true;
        restorePdfScrollPosition(positionToRestore);
        updatePdfPageControl(restorePage);
        window.requestAnimationFrame(() => {
          restorePdfScrollPosition(positionToRestore);
          updatePdfPageControl(restorePage);
        });
      }
    }
  } catch (error) {
    pdfState.suppressScrollSave = false;
    throw error;
  }
  if (hasRenderedPages) {
    elements.pdfViewer.replaceChildren(...Array.from(renderTarget.childNodes));
    elements.pdfViewer.querySelectorAll(".pdf-page").forEach(renderAnnotationsForPage);
  }
  schedulePdfSelectionOverlayRender();
  if (restoredEarly && !hasRenderedPages) {
    finishPdfScrollAfterEarlyRestore();
  } else {
    finishPdfScrollRestore(positionToRestore);
  }
}

async function loadPdf(pdfHref, noteId) {
  pdfState.noteId = noteId;
  pdfState.url = pdfHref;
  restoreStoredPdfScale(noteId);
  hidePdfLinkBackButton();
  pdfState.annotations = await readAnnotations(noteId);
  resetAnnotationHistory();
  setAnnotationStatus(pdfState.annotations.length ? "Annotations loaded" : "No annotations yet");
  renderAnnotationList();
  setPdfLoading("Fetching PDF...");
  try {
    const response = await fetch(pdfHref, { cache: "no-store" });
    if (!response.ok) throw new Error(`PDF request failed (${response.status})`);
    const pdfData = new Uint8Array(await response.arrayBuffer());
    setPdfLoading("Decoding PDF...");
    pdfState.document = await pdfjsLib.getDocument({
      data: pdfData,
      standardFontDataUrl: "/node_modules/pdfjs-dist/standard_fonts/",
      disableAutoFetch: true,
      disableStream: true
    }).promise;
    setPdfLoading("Rendering pages...");
    await renderPdf();
  } catch (error) {
    console.error(error);
    showPdfError(error);
  }
}
