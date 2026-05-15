function normalizeCopiedPdfText(text) {
  return normalizePdfMathInlineSpacing(cleanDamagedPdfGlyphText(text)
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]*\n[ \t]*/g, "\n")
    .replace(/([A-Za-z0-9,.;:)%])\n([A-Za-z0-9(])/g, "$1 $2")
    .replace(/[ \t]{2,}/g, " ")
    .trim());
}

function cleanDamagedPdfGlyphText(text) {
  return String(text || "")
    .replace(/[\u0000\u0010]/g, "(")
    .replace(/[\u0001\u0011]/g, ")")
    .replace(/\u0002/g, "(")
    .replace(/\u0003/g, ")")
    .replace(/\u000c+/g, "|")
    .replace(/[\u0004-\u0008\u000b\u000e-\u000f\u0012-\u001f\u007f]/g, "")
    .replace(/\uFFFD+/g, "")
    .replace(/[\u200b\u200c\u200d\ufeff]/g, "");
}

function normalizePdfMathInlineSpacing(text) {
  const value = String(text || "");
  if (!/[\u{1D400}-\u{1D7FF}∈≔⩾≤≥×]/u.test(value)) return value;
  return value
    .replace(/([\u{1D400}-\u{1D7FF}A-Za-z0-9])\s+\(/gu, "$1(")
    .replace(/\(\s+/g, "(")
    .replace(/\s+\)/g, ")")
    .replace(/\s*=\s*/g, "=")
    .replace(/\s+,/g, ",")
    .replace(/,\s*(\(\d+\))/g, ", $1");
}

function median(values) {
  return medianNumber(values, 0);
}

function medianNumber(values, fallback = 0) {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!sorted.length) return fallback;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function normalizedPointer(event, pageElement) {
  const box = pageViewportBox(pageElement);
  return {
    x: clamp((event.clientX - box.left) / box.width, 0, 1),
    y: clamp((event.clientY - box.top) / box.height, 0, 1)
  };
}

function rectsIntersect(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

function clampClientRectToPage(rect, pageBox) {
  const left = clamp(rect.left, pageBox.left, pageBox.right);
  const right = clamp(rect.right, pageBox.left, pageBox.right);
  const top = clamp(rect.top, pageBox.top, pageBox.bottom);
  const bottom = clamp(rect.bottom, pageBox.top, pageBox.bottom);
  return { left, right, top, bottom, width: right - left, height: bottom - top };
}

function groupTextItemsByLine(items) {
  const lines = [];
  items
    .filter((item) => item?.rect && item.rect.width > 0 && item.rect.height > 0)
    .sort((a, b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left)
    .forEach((item) => {
      const center = rectCenterY(item.rect);
      const threshold = Math.max(4, item.rect.height * 0.55);
      let line = lines.find((entry) => Math.abs(entry.center - center) <= threshold);
      if (!line) {
        line = { center, items: [] };
        lines.push(line);
      }
      line.items.push(item);
      line.center = line.items.reduce((sum, entry) => sum + rectCenterY(entry.rect), 0) / line.items.length;
    });
  return lines;
}

function lineBoundsFromItems(items) {
  return {
    left: Math.min(...items.map((item) => item.rect.left)),
    right: Math.max(...items.map((item) => item.rect.right)),
    top: Math.min(...items.map((item) => item.rect.top)),
    bottom: Math.max(...items.map((item) => item.rect.bottom))
  };
}

function rectCenterY(rect) {
  return (rect.top + rect.bottom) / 2;
}

function shouldStartCopiedPdfLine(previous, current, typicalHeight) {
  if (!previous) return true;
  const gap = Math.max(0, current.top - previous.bottom);
  const height = Math.max(1, Math.min(previous.bottom - previous.top, current.bottom - current.top));
  return gap > Math.max(height * 0.72, typicalHeight * 0.82, 5);
}

function copiedTextFromSelectedItems(items) {
  const lines = groupTextItemsByLine(items).map((line) => {
    const sortedItems = line.items.slice().sort((a, b) => a.rect.left - b.rect.left);
    const bounds = lineBoundsFromItems(sortedItems);
    return {
      ...bounds,
      text: sortedItems.map((item) => item.text || "").join("")
    };
  }).filter((line) => normalizeText(line.text));

  const typicalHeight = medianNumber(lines.map((line) => line.bottom - line.top), 12);
  const output = [];
  lines.forEach((line, index) => {
    if (index > 0 && shouldStartCopiedPdfLine(lines[index - 1], line, typicalHeight)) {
      output.push("\n");
    } else if (index > 0) {
      output.push(" ");
    }
    output.push(line.text);
  });
  return normalizeCopiedPdfText(output.join(""));
}

function hasPdfSpanText(text) {
  return cleanDamagedPdfGlyphText(text).length > 0;
}

function lineRectsFromClientRects(clientRects, pageBox, type) {
  const items = clientRects
    .map((rect) => clampClientRectToPage(rect, pageBox))
    .filter((rect) => rect.width > 1 && rect.height > 1);

  return groupTextItemsByLine(items.map((rect) => ({ rect }))).map((line) => {
    const { left, right, top, bottom } = lineBoundsFromItems(line.items);
    const lineHeight = Math.max(1, bottom - top);
    const underlineHeight = Math.max(2, lineHeight * 0.13);
    const visualTop = type === "underline" ? bottom - underlineHeight : top + lineHeight * 0.08;
    const visualHeight = type === "underline" ? underlineHeight : lineHeight * 0.84;
    return normalizeAnnotationRect({
      x: (left - pageBox.left) / pageBox.width,
      y: (visualTop - pageBox.top) / pageBox.height,
      w: (right - left) / pageBox.width,
      h: visualHeight / pageBox.height
    });
  }).filter((rect) => rect.w >= 0.004 && rect.h >= 0.001);
}

function selectionClientRectsForPage(pageElement) {
  const selection = window.getSelection();
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  const textLayer = pageElement.querySelector(".textLayer");
  if (!selection || selection.isCollapsed || !canvas || !textLayer) return [];

  const pageBox = canvas.getBoundingClientRect();
  const layerBox = textLayer.getBoundingClientRect();
  const clientRects = [];
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    if (!textLayer.contains(range.commonAncestorContainer) && !range.intersectsNode(textLayer)) continue;
    Array.from(range.getClientRects())
      .filter((rect) => rectsIntersect(rect, layerBox) && rectsIntersect(rect, pageBox))
      .forEach((rect) => clientRects.push(rect));
  }
  return clientRects;
}

function selectedLineRectsForPage(pageElement, type) {
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  if (!canvas) return [];
  const pageBox = canvas.getBoundingClientRect();
  const clientRects = selectionVisualRectsForPage(pageElement);
  return lineRectsFromClientRects(clientRects.length ? clientRects : selectionClientRectsForPage(pageElement), pageBox, type);
}

function horizontalOverlap(a, b) {
  return Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
}

function verticalOverlap(a, b) {
  return Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
}

function textMeasurementContextForSpan(span) {
  const canvas = textMeasurementContextForSpan.canvas || (textMeasurementContextForSpan.canvas = document.createElement("canvas"));
  const context = canvas.getContext("2d");
  const style = getComputedStyle(span);
  context.font = style.font || `${style.fontSize} ${style.fontFamily}`;
  return context;
}

function measuredCharacterPositions(span, text) {
  const spanRect = span.getBoundingClientRect();
  const chars = Array.from(text || "");
  if (!chars.length || spanRect.width <= 0) return { chars, positions: [0] };
  const context = textMeasurementContextForSpan(span);
  const widths = chars.map((char) => Math.max(0, context.measureText(char).width));
  const total = widths.reduce((sum, width) => sum + width, 0) || 1;
  const positions = [0];
  let measured = 0;
  widths.forEach((width) => {
    measured += width;
    positions.push((measured / total) * spanRect.width);
  });
  return { chars, positions };
}

function codeUnitOffsetForCharacterIndex(chars, index) {
  return chars.slice(0, index).reduce((sum, char) => sum + char.length, 0);
}

function characterIndexForCodeUnitOffset(chars, offset) {
  let units = 0;
  for (let index = 0; index < chars.length; index += 1) {
    const nextUnits = units + chars[index].length;
    if (offset <= units) return index;
    if (offset < nextUnits) return index + 1;
    units = nextUnits;
  }
  return chars.length;
}

function characterIndexAtClientX(span, clientX) {
  const text = span.textContent || "";
  const spanRect = span.getBoundingClientRect();
  const { chars, positions } = measuredCharacterPositions(span, text);
  const x = clamp(clientX - spanRect.left, 0, spanRect.width);
  for (let index = 0; index < chars.length; index += 1) {
    const center = (positions[index] + positions[index + 1]) / 2;
    if (x <= center) return index;
  }
  return chars.length;
}

function isPdfWordCharacter(char) {
  return /[\p{L}\p{N}_-]/u.test(char || "");
}

function selectTextSpanWordAtPoint(span, clientX) {
  const node = span?.firstChild;
  const text = node?.textContent || "";
  if (!node || !text) return false;
  const chars = Array.from(text);
  let index = characterIndexAtClientX(span, clientX);
  if (index >= chars.length) index = chars.length - 1;
  if (!isPdfWordCharacter(chars[index]) && index > 0 && isPdfWordCharacter(chars[index - 1])) {
    index -= 1;
  }
  if (!isPdfWordCharacter(chars[index])) return false;
  let start = index;
  let end = index + 1;
  while (start > 0 && isPdfWordCharacter(chars[start - 1])) start -= 1;
  while (end < chars.length && isPdfWordCharacter(chars[end])) end += 1;

  const range = document.createRange();
  range.setStart(node, codeUnitOffsetForCharacterIndex(chars, start));
  range.setEnd(node, codeUnitOffsetForCharacterIndex(chars, end));
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  schedulePdfSelectionOverlayRender();
  return true;
}

function sliceSpanTextByRect(span, selectionRect) {
  const text = span.textContent || "";
  const spanRect = span.getBoundingClientRect();
  if (!text || spanRect.width <= 0) return "";
  const { chars, positions } = measuredCharacterPositions(span, text);
  const left = clamp(Math.max(selectionRect.left, spanRect.left) - spanRect.left, 0, spanRect.width);
  const right = clamp(Math.min(selectionRect.right, spanRect.right) - spanRect.left, 0, spanRect.width);
  if (right <= left) return "";

  let startIndex = 0;
  let endIndex = chars.length;
  for (let index = 0; index < chars.length; index += 1) {
    const center = (positions[index] + positions[index + 1]) / 2;
    if (center >= left) {
      startIndex = index;
      break;
    }
  }
  for (let index = chars.length - 1; index >= 0; index -= 1) {
    const center = (positions[index] + positions[index + 1]) / 2;
    if (center <= right) {
      endIndex = index + 1;
      break;
    }
  }
  return chars.slice(startIndex, endIndex).join("");
}

function textFromSelectionForPage(pageElement, options = {}) {
  const preferNative = options.preferNative !== false;
  const nativeText = window.getSelection()?.toString() || "";
  if (preferNative && nativeText && !nativeText.includes("\uFFFD")) return nativeText;

  const visualRects = selectionVisualRectsForPage(pageElement);
  const clientRects = visualRects.length ? visualRects : selectionClientRectsForPage(pageElement);
  if (!clientRects.length) return "";

  const spans = pdfSelectionSpansForPage(pageElement);
  const lines = groupTextItemsByLine(clientRects.map((rect) => ({ rect })));
  const selectedItems = [];
  lines.forEach((line) => {
    const lineRect = lineBoundsFromItems(line.items);
    spans
      .filter((entry) => {
        const vOverlap = verticalOverlap(entry.rect, lineRect);
        const hOverlap = horizontalOverlap(entry.rect, lineRect);
        return hOverlap > 1 && vOverlap >= Math.min(entry.rect.height, lineRect.bottom - lineRect.top) * 0.32;
      })
      .sort((a, b) => a.rect.left - b.rect.left)
      .forEach((entry) => {
        const text = sliceSpanTextByRect(entry.span, lineRect);
        if (text) selectedItems.push({ text, rect: entry.rect });
      });
  });
  return copiedTextFromSelectedItems(selectedItems);
}

function selectedPdfPages() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !elements.pdfViewer) return [];
  return Array.from(elements.pdfViewer.querySelectorAll(".pdf-page")).filter((pageElement) => {
    const textLayer = pageElement.querySelector(".textLayer");
    if (!textLayer) return false;
    for (let index = 0; index < selection.rangeCount; index += 1) {
      const range = selection.getRangeAt(index);
      try {
        if (range.intersectsNode(textLayer)) return true;
      } catch (error) {
        // Detached layers can briefly exist while pages rerender.
      }
    }
    return false;
  });
}

function textFromPdfSelection() {
  const nativeText = window.getSelection()?.toString() || "";
  if (nativeText && !nativeText.includes("\uFFFD")) return nativeText;
  const chunks = selectedPdfPages()
    .map((pageElement) => textFromSelectionForPage(pageElement, { preferNative: false }))
    .filter((text) => normalizeText(text));
  return normalizeCopiedPdfText(chunks.join("\n"));
}

function pdfSelectionSpansForPage(pageElement) {
  return Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
    .map((span) => ({ span, text: span.textContent || "", rect: span.getBoundingClientRect() }))
    .filter((entry) => hasPdfSpanText(entry.text) && entry.rect.width > 0 && entry.rect.height > 0);
}

let pdfTextDragSelection = null;
let pdfTextLastClick = null;

function textNodePositionForSpan(span, clientX, lineIndex = 0, itemIndex = 0) {
  const node = span?.firstChild;
  const text = node?.textContent || "";
  if (!node || !text) return null;
  const chars = Array.from(text);
  const charIndex = characterIndexAtClientX(span, clientX);
  return {
    node,
    span,
    textLayer: span.closest(".textLayer"),
    lineIndex,
    itemIndex,
    charIndex,
    offset: codeUnitOffsetForCharacterIndex(chars, charIndex)
  };
}

function textLayerForDragPoint(clientX, clientY, fallbackTextLayer = null) {
  const directLayer = document.elementFromPoint(clientX, clientY)?.closest?.(".textLayer");
  if (directLayer && elements.pdfViewer?.contains(directLayer)) return directLayer;

  const layers = Array.from(elements.pdfViewer?.querySelectorAll(".pdf-page .textLayer") || []);
  if (!layers.length) return fallbackTextLayer;

  let bestLayer = fallbackTextLayer || layers[0];
  let bestDistance = Number.POSITIVE_INFINITY;
  layers.forEach((layer) => {
    const box = layer.getBoundingClientRect();
    const yDistance = clientY < box.top
      ? box.top - clientY
      : clientY > box.bottom
        ? clientY - box.bottom
        : 0;
    const xDistance = clientX < box.left
      ? (box.left - clientX) * 0.18
      : clientX > box.right
        ? (clientX - box.right) * 0.18
        : 0;
    const distance = yDistance + xDistance;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestLayer = layer;
    }
  });
  return bestLayer;
}

function textLayerPositionAtPoint(textLayer, clientX, clientY) {
  const lines = textLayerLines(textLayer);
  if (!lines.length) return null;

  let lineIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  lines.forEach((line, index) => {
    const distance = clientY < line.top
      ? line.top - clientY
      : clientY > line.bottom
        ? clientY - line.bottom
        : 0;
    if (distance < bestDistance) {
      bestDistance = distance;
      lineIndex = index;
    }
  });

  const line = lines[lineIndex];
  const items = line.items;
  const firstItem = items[0];
  const lastItem = items.at(-1);
  if (!firstItem || !lastItem) return null;

  if (clientX <= firstItem.rect.left) {
    return textNodePositionForSpan(firstItem.span, firstItem.rect.left, lineIndex, 0);
  }
  if (clientX >= lastItem.rect.right) {
    return textNodePositionForSpan(lastItem.span, lastItem.rect.right, lineIndex, items.length - 1);
  }

  let nearestItemIndex = 0;
  let nearestX = Number.POSITIVE_INFINITY;
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    if (clientX >= item.rect.left && clientX <= item.rect.right) {
      return textNodePositionForSpan(item.span, clientX, lineIndex, index);
    }
    const distance = Math.min(Math.abs(clientX - item.rect.left), Math.abs(clientX - item.rect.right));
    if (distance < nearestX) {
      nearestX = distance;
      nearestItemIndex = index;
    }
  }

  const item = items[nearestItemIndex];
  const snapX = clientX < item.rect.left ? item.rect.left : item.rect.right;
  return textNodePositionForSpan(item.span, snapX, lineIndex, nearestItemIndex);
}

function compareTextLayerPositions(a, b) {
  if (a.textLayer && b.textLayer && a.textLayer !== b.textLayer) {
    const position = a.textLayer.compareDocumentPosition(b.textLayer);
    if (position & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
    if (position & Node.DOCUMENT_POSITION_PRECEDING) return 1;
  }
  if (a.lineIndex !== b.lineIndex) return a.lineIndex - b.lineIndex;
  if (a.itemIndex !== b.itemIndex) return a.itemIndex - b.itemIndex;
  return a.offset - b.offset;
}

function setTextLayerDragSelection(anchor, focus) {
  if (!anchor || !focus) return false;
  const [start, end] = compareTextLayerPositions(anchor, focus) <= 0
    ? [anchor, focus]
    : [focus, anchor];
  const range = document.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  schedulePdfSelectionOverlayRender();
  return true;
}

function selectTextLayerLinesAtPoint(textLayer, targetSpan, detail, event) {
  const lines = textLayerLines(textLayer);
  const lineIndex = findTextLayerLineIndex(lines, targetSpan, event);
  if (lineIndex < 0) return false;
  const selectedLines = detail >= 4 ? paragraphLinesAround(lines, lineIndex) : [lines[lineIndex]];
  return selectTextLayerLines(selectedLines);
}

function textLayerClickDetail(textLayer, event) {
  const last = pdfTextLastClick;
  if (!last || last.textLayer !== textLayer) return 1;
  const elapsed = Math.max(0, event.timeStamp - last.timeStamp);
  const distance = Math.hypot(event.clientX - last.x, event.clientY - last.y);
  return elapsed <= 520 && distance <= 8 ? last.detail + 1 : 1;
}

function rememberTextLayerClick(textLayer, event, detail) {
  pdfTextLastClick = {
    textLayer,
    timeStamp: event.timeStamp,
    x: event.clientX,
    y: event.clientY,
    detail
  };
}

function handleTextLayerPointerDown(event) {
  if (event.button !== 0) return;
  const textLayer = event.currentTarget;
  const targetSpan = event.target.closest("span[role='presentation']");
  if (!targetSpan || !textLayer.contains(targetSpan)) return;
  const clickDetail = textLayerClickDetail(textLayer, event);

  if (clickDetail > 1) {
    event.preventDefault();
    if (clickDetail === 2) selectTextSpanWordAtPoint(targetSpan, event.clientX);
    else selectTextLayerLinesAtPoint(textLayer, targetSpan, clickDetail, event);
    rememberTextLayerClick(textLayer, event, clickDetail);
    return;
  }

  const anchor = textLayerPositionAtPoint(textLayer, event.clientX, event.clientY);
  if (!anchor) return;

  pdfTextDragSelection = {
    textLayer,
    pointerId: event.pointerId,
    anchor,
    lastClientX: event.clientX,
    lastClientY: event.clientY,
    autoScrollFrame: 0,
    startX: event.clientX,
    startY: event.clientY,
    clickDetail,
    moved: false
  };
  try {
    textLayer.setPointerCapture?.(event.pointerId);
  } catch (error) {
    // Pointer capture is best-effort; selection still works inside the text layer.
  }
  window.addEventListener("pointermove", handleTextLayerGlobalPointerMove, true);
  window.addEventListener("pointerup", finishTextLayerPointerSelection, true);
  window.addEventListener("pointercancel", finishTextLayerPointerSelection, true);
  event.preventDefault();
  setTextLayerDragSelection(anchor, anchor);
}

function handleTextLayerPointerMove(event) {
  const state = pdfTextDragSelection;
  if (!state || state.pointerId !== event.pointerId) return;
  updateTextLayerDragSelection(event);
}

function handleTextLayerGlobalPointerMove(event) {
  const state = pdfTextDragSelection;
  if (!state || state.pointerId !== event.pointerId) return;
  updateTextLayerDragSelection(event);
}

function updateTextLayerDragSelection(event) {
  const state = pdfTextDragSelection;
  if (!state) return;
  state.lastClientX = event.clientX;
  state.lastClientY = event.clientY;
  const distance = Math.hypot(event.clientX - state.startX, event.clientY - state.startY);
  if (!state.moved && distance < 3) return;
  state.moved = true;
  event.preventDefault();

  updateTextLayerDragFocus();
  schedulePdfTextDragAutoScroll();
}

function updateTextLayerDragFocus() {
  const state = pdfTextDragSelection;
  if (!state) return;
  const textLayer = textLayerForDragPoint(state.lastClientX, state.lastClientY, state.textLayer);
  const focus = textLayer ? textLayerPositionAtPoint(textLayer, state.lastClientX, state.lastClientY) : null;
  setTextLayerDragSelection(state.anchor, focus);
}

function pdfDragAutoScrollVelocity() {
  const state = pdfTextDragSelection;
  const viewer = elements.pdfViewer;
  if (!state || !viewer) return 0;
  const box = viewer.getBoundingClientRect();
  const threshold = Math.min(96, Math.max(42, viewer.clientHeight * 0.18));
  let velocity = 0;
  if (state.lastClientY < box.top + threshold) {
    velocity = -Math.pow((box.top + threshold - state.lastClientY) / threshold, 1.55) * 30;
  } else if (state.lastClientY > box.bottom - threshold) {
    velocity = Math.pow((state.lastClientY - (box.bottom - threshold)) / threshold, 1.55) * 30;
  }
  const maxScroll = Math.max(0, viewer.scrollHeight - viewer.clientHeight);
  if ((velocity < 0 && viewer.scrollTop <= 0) || (velocity > 0 && viewer.scrollTop >= maxScroll)) return 0;
  return clamp(velocity, -36, 36);
}

function schedulePdfTextDragAutoScroll() {
  const state = pdfTextDragSelection;
  if (!state || state.autoScrollFrame) return;
  state.autoScrollFrame = window.requestAnimationFrame(runPdfTextDragAutoScroll);
}

function runPdfTextDragAutoScroll() {
  const state = pdfTextDragSelection;
  if (!state) return;
  state.autoScrollFrame = 0;
  const viewer = elements.pdfViewer;
  const velocity = pdfDragAutoScrollVelocity();
  if (!viewer || !velocity) return;

  const before = viewer.scrollTop;
  viewer.scrollTop = clamp(before + velocity, 0, Math.max(0, viewer.scrollHeight - viewer.clientHeight));
  if (viewer.scrollTop !== before) {
    updateTextLayerDragFocus();
    schedulePdfSelectionOverlayRender();
  }
  schedulePdfTextDragAutoScroll();
}

function finishTextLayerPointerSelection(event) {
  const state = pdfTextDragSelection;
  if (!state || state.pointerId !== event.pointerId) return;
  try {
    state.textLayer.releasePointerCapture?.(event.pointerId);
  } catch (error) {
    // The browser may already have released capture after pointer cancellation.
  }
  window.removeEventListener("pointermove", handleTextLayerGlobalPointerMove, true);
  window.removeEventListener("pointerup", finishTextLayerPointerSelection, true);
  window.removeEventListener("pointercancel", finishTextLayerPointerSelection, true);
  window.cancelAnimationFrame(state.autoScrollFrame);
  if (state.moved) {
    pdfTextLastClick = null;
  } else {
    rememberTextLayerClick(state.textLayer, event, state.clickDetail || 1);
  }
  pdfTextDragSelection = null;
  schedulePdfSelectionOverlayRender();
}

function selectedOffsetsForSpanRange(range, span) {
  const node = span.firstChild;
  const text = node?.textContent || "";
  if (!node || !text) return null;
  try {
    if (!range.intersectsNode(span)) return null;
  } catch (error) {
    return null;
  }

  const chars = Array.from(text);
  let start = 0;
  let end = chars.length;
  if (range.startContainer === node) {
    start = characterIndexForCodeUnitOffset(chars, range.startOffset);
  }
  if (range.endContainer === node) {
    end = characterIndexForCodeUnitOffset(chars, range.endOffset);
  }
  if (range.collapsed || end <= start) return null;
  return { start, end };
}

function selectedRectForSpanRange(range, span) {
  const offsets = selectedOffsetsForSpanRange(range, span);
  if (!offsets) return null;
  const text = span.textContent || "";
  const spanRect = span.getBoundingClientRect();
  const { positions } = measuredCharacterPositions(span, text);
  const left = spanRect.left + positions[offsets.start];
  const right = spanRect.left + positions[offsets.end];
  if (right <= left) return null;
  return {
    left,
    right,
    top: spanRect.top,
    bottom: spanRect.bottom,
    width: right - left,
    height: spanRect.height
  };
}

function selectionVisualRectsForPage(pageElement) {
  const selection = window.getSelection();
  const canvas = pageElement.querySelector(".pdf-page-canvas");
  const textLayer = pageElement.querySelector(".textLayer");
  if (!selection || selection.isCollapsed || !canvas || !textLayer) return [];
  const pageBox = canvas.getBoundingClientRect();
  const rects = [];
  const spans = pdfSelectionSpansForPage(pageElement);
  for (let index = 0; index < selection.rangeCount; index += 1) {
    const range = selection.getRangeAt(index);
    if (!textLayer.contains(range.commonAncestorContainer) && !range.intersectsNode(textLayer)) continue;
    spans.forEach(({ span }) => {
      const rect = selectedRectForSpanRange(range, span);
      if (rect && rectsIntersect(rect, pageBox)) rects.push(clampClientRectToPage(rect, pageBox));
    });
  }
  return rects;
}

function clearPdfSelectionOverlays() {
  window.cancelAnimationFrame(pdfState.selectionRenderFrame);
  pdfState.selectionRenderFrame = 0;
  elements.pdfViewer?.classList.remove("has-pdf-selection");
  elements.pdfViewer?.querySelectorAll(".pdf-selection-layer").forEach((layer) => {
    layer.innerHTML = "";
  });
}

function renderPdfSelectionOverlays() {
  pdfState.selectionRenderFrame = 0;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !elements.pdfViewer) {
    clearPdfSelectionOverlays();
    return;
  }

  let hasSelection = false;
  elements.pdfViewer.querySelectorAll(".pdf-page").forEach((pageElement) => {
    const layer = pageElement.querySelector(".pdf-selection-layer");
    const canvas = pageElement.querySelector(".pdf-page-canvas");
    if (!layer || !canvas) return;
    const pageBox = canvas.getBoundingClientRect();
    const rects = selectionVisualRectsForPage(pageElement);
    layer.innerHTML = "";
    rects.forEach((rect) => {
      const marker = document.createElement("div");
      marker.className = "pdf-selection-rect";
      marker.style.left = `${rect.left - pageBox.left}px`;
      marker.style.top = `${rect.top - pageBox.top}px`;
      marker.style.width = `${rect.width}px`;
      marker.style.height = `${rect.height}px`;
      layer.appendChild(marker);
      hasSelection = true;
    });
  });
  elements.pdfViewer.classList.toggle("has-pdf-selection", hasSelection);
  if (hasSelection && typeof refreshReaderSelectedPdfTextFromSelection === "function") {
    refreshReaderSelectedPdfTextFromSelection();
  }
}

function schedulePdfSelectionOverlayRender() {
  window.cancelAnimationFrame(pdfState.selectionRenderFrame);
  pdfState.selectionRenderFrame = window.requestAnimationFrame(renderPdfSelectionOverlays);
}

function textLayerLines(textLayer) {
  const spans = Array.from(textLayer.querySelectorAll("span[role='presentation']"))
    .map((span) => ({ span, text: span.textContent || "", rect: span.getBoundingClientRect() }))
    .filter((entry) => hasPdfSpanText(entry.text) && entry.rect.width > 0 && entry.rect.height > 0);

  return groupTextItemsByLine(spans).map((line) => {
    const items = line.items
      .filter((item) => item.span)
      .sort((a, b) => a.rect.left - b.rect.left);
    const bounds = lineBoundsFromItems(items);
    return {
      ...bounds,
      height: Math.max(1, bounds.bottom - bounds.top),
      width: Math.max(1, bounds.right - bounds.left),
      items,
      text: items.map((item) => item.text).join("")
    };
  }).filter((line) => normalizeText(line.text));
}

function selectSpanRange(firstSpan, lastSpan) {
  const firstNode = firstSpan?.firstChild;
  const lastNode = lastSpan?.firstChild;
  if (!firstNode || !lastNode) return false;
  const range = document.createRange();
  range.setStart(firstNode, 0);
  range.setEnd(lastNode, lastNode.textContent.length);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  schedulePdfSelectionOverlayRender();
  return true;
}

function selectTextLayerLines(lines) {
  const firstSpan = lines.at(0)?.items.at(0)?.span;
  const lastSpan = lines.at(-1)?.items.at(-1)?.span;
  return selectSpanRange(firstSpan, lastSpan);
}

function findTextLayerLineIndex(lines, targetSpan, event) {
  const spanIndex = lines.findIndex((line) => line.items.some((item) => item.span === targetSpan));
  if (spanIndex !== -1) return spanIndex;
  const y = event.clientY;
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  lines.forEach((line, index) => {
    const center = (line.top + line.bottom) / 2;
    const distance = Math.abs(center - y);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function lineGap(previousLine, nextLine) {
  return Math.max(0, nextLine.top - previousLine.bottom);
}

function shouldJoinParagraphLine(previousLine, nextLine, typicalGap) {
  const gap = lineGap(previousLine, nextLine);
  const averageHeight = (previousLine.height + nextLine.height) / 2;
  const heightRatio = Math.max(previousLine.height, nextLine.height) / Math.max(1, Math.min(previousLine.height, nextLine.height));
  const overlap = horizontalOverlap(previousLine, nextLine) / Math.max(1, Math.min(previousLine.width, nextLine.width));
  const maxGap = Math.max(averageHeight * 0.92, typicalGap * 2.2, 8);
  return gap <= maxGap && overlap >= 0.35 && heightRatio <= 1.45;
}

function paragraphLinesAround(lines, lineIndex) {
  const gaps = lines.slice(1).map((line, index) => lineGap(lines[index], line));
  const typicalGap = median(gaps) || 0;
  let start = lineIndex;
  let end = lineIndex;

  while (start > 0 && shouldJoinParagraphLine(lines[start - 1], lines[start], typicalGap)) {
    start -= 1;
  }
  while (end < lines.length - 1 && shouldJoinParagraphLine(lines[end], lines[end + 1], typicalGap)) {
    end += 1;
  }
  return lines.slice(start, end + 1);
}

function handleTextLayerDoubleClick(event) {
  if (event.button !== 0) return;
  const targetSpan = event.target.closest("span[role='presentation']");
  if (!targetSpan || !event.currentTarget.contains(targetSpan)) return;
  selectTextSpanWordAtPoint(targetSpan, event.clientX);
}

function handleTextLayerMultiClick(event) {
  if (event.button !== 0 || event.detail < 3) return;
  const textLayer = event.currentTarget;
  const targetSpan = event.target.closest("span[role='presentation']");
  if (!targetSpan || !textLayer.contains(targetSpan)) return;

  const lines = textLayerLines(textLayer);
  const lineIndex = findTextLayerLineIndex(lines, targetSpan, event);
  if (lineIndex < 0) return;

  event.preventDefault();
  const selectedLines = event.detail >= 4 ? paragraphLinesAround(lines, lineIndex) : [lines[lineIndex]];
  selectTextLayerLines(selectedLines);
}

function addNoteAnnotation(event, pageElement) {
  const point = normalizedPointer(event, pageElement);
  const box = pageViewportBox(pageElement);
  const noteWidth = PDF_NOTE_MARKER_SIZE / Math.max(1, box.width);
  const noteHeight = PDF_NOTE_MARKER_SIZE / Math.max(1, box.height);
  const annotation = normalizeAnnotation({
    id: `note-${Date.now().toString(36)}`,
    type: "note",
    page: Number(pageElement.dataset.page),
    x: clamp(point.x - noteWidth / 2, 0, 1 - noteWidth),
    y: clamp(point.y - noteHeight / 2, 0, 1 - noteHeight),
    w: noteWidth,
    h: noteHeight,
    color: pdfState.color,
    text: "",
    comment: ""
  });
  pushAnnotationHistory();
  pdfState.annotations.push(annotation);
  scheduleSaveAnnotations();
  renderAnnotationsForPage(pageElement);
}

function finishSelectionAnnotation(pageElement, type) {
  window.setTimeout(() => {
    const rects = selectedLineRectsForPage(pageElement, type);
    if (!rects.length) return;
    const bounds = annotationBounds(rects);
    const selectedText = textFromSelectionForPage(pageElement);
    const annotation = normalizeAnnotation({
      id: `${type}-${Date.now().toString(36)}`,
      type,
      page: Number(pageElement.dataset.page),
      ...bounds,
      rects,
      color: pdfState.color,
      quote: selectedText,
      text: "",
      comment: ""
    });
    if (annotation.w < 0.01 || annotation.h < 0.001) return;
    pushAnnotationHistory();
    pdfState.annotations.push(annotation);
    scheduleSaveAnnotations();
    renderAnnotationsForPage(pageElement);
  }, 0);
}
