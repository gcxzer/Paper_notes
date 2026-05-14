function pdfSearchNeedle() {
  return normalizeText(pdfState.searchQuery).toLocaleLowerCase();
}

function pdfSearchSpansForPage(pageElement) {
  return Array.from(pageElement?.querySelectorAll?.(".textLayer span[role='presentation']") || [])
    .filter((span) => normalizeText(span.textContent));
}

function clearPdfSearchHighlights() {
  elements.pdfViewer?.querySelectorAll(".pdf-search-match, .pdf-search-current").forEach((span) => {
    span.classList.remove("pdf-search-match", "pdf-search-current");
  });
}

function updatePdfSearchControls() {
  const total = pdfState.searchMatches.length;
  const current = total && pdfState.searchIndex >= 0 ? pdfState.searchIndex + 1 : 0;
  if (elements.pdfSearchCount) elements.pdfSearchCount.textContent = `${current}/${total}`;
  if (elements.pdfSearchPrev) elements.pdfSearchPrev.disabled = total < 1;
  if (elements.pdfSearchNext) elements.pdfSearchNext.disabled = total < 1;
}

function setPdfSearchOpen(open) {
  if (!elements.pdfSearchControl) return;
  elements.pdfSearchControl.hidden = !open;
}

function refreshPdfSearchMatches({ keepIndex = true } = {}) {
  const needle = pdfSearchNeedle();
  const previousMatch = keepIndex && pdfState.searchIndex >= 0
    ? pdfState.searchMatches[pdfState.searchIndex]
    : null;
  clearPdfSearchHighlights();
  pdfState.searchMatches = [];

  if (!needle) {
    pdfState.searchIndex = -1;
    updatePdfSearchControls();
    return;
  }

  elements.pdfViewer?.querySelectorAll(".pdf-page").forEach((pageElement) => {
    const page = Number(pageElement.dataset.page) || 1;
    const spans = pdfSearchSpansForPage(pageElement);
    const textOccurrences = new Map();
    spans.forEach((span) => {
      const text = normalizeText(span.textContent);
      if (!text.toLocaleLowerCase().includes(needle)) return;
      const occurrence = (textOccurrences.get(text) || 0) + 1;
      textOccurrences.set(text, occurrence);
      span.classList.add("pdf-search-match");
      pdfState.searchMatches.push({
        page,
        element: span,
        text,
        key: `${page}:${occurrence}:${text}`
      });
    });
  });

  if (!pdfState.searchMatches.length) {
    pdfState.searchIndex = -1;
    updatePdfSearchControls();
    return;
  }

  if (previousMatch) {
    let nextIndex = pdfState.searchMatches.findIndex((match) => match.element === previousMatch.element);
    if (nextIndex < 0 && previousMatch.key) {
      nextIndex = pdfState.searchMatches.findIndex((match) => match.key === previousMatch.key);
    }
    pdfState.searchIndex = nextIndex >= 0 ? nextIndex : clamp(pdfState.searchIndex, 0, pdfState.searchMatches.length - 1);
  } else {
    pdfState.searchIndex = 0;
  }
  pdfState.searchMatches[pdfState.searchIndex]?.element?.classList.add("pdf-search-current");
  updatePdfSearchControls();
}

async function goToPdfSearchMatch(delta = 1) {
  const total = pdfState.searchMatches.length;
  if (!total) return;
  pdfState.searchIndex = (pdfState.searchIndex + delta + total) % total;
  refreshPdfSearchMatches({ keepIndex: true });
  const match = pdfState.searchMatches[pdfState.searchIndex];
  if (!match?.element || !elements.pdfViewer) return;
  const pageElement = match.element.closest(".pdf-page");
  if (pageElement && typeof ensurePdfPageRendered === "function") {
    await ensurePdfPageRendered(pageElement);
  }
  const viewerBox = elements.pdfViewer.getBoundingClientRect();
  const matchBox = match.element.getBoundingClientRect();
  elements.pdfViewer.scrollTo({
    top: elements.pdfViewer.scrollTop + (matchBox.top - viewerBox.top) - Math.max(80, elements.pdfViewer.clientHeight * 0.24),
    behavior: "auto"
  });
  if (typeof updatePdfPageControl === "function") updatePdfPageControl(match.page);
}

function setPdfSearchQuery(query) {
  pdfState.searchQuery = normalizeText(query);
  setPdfSearchOpen(Boolean(pdfState.searchQuery) || document.activeElement === elements.pdfSearchInput);
  refreshPdfSearchMatches({ keepIndex: false });
  if (pdfState.searchMatches.length) void goToPdfSearchMatch(0);
}

function focusPdfSearchInput() {
  if (!elements.pdfSearchInput) return;
  setPdfSearchOpen(true);
  elements.pdfSearchInput.focus();
  elements.pdfSearchInput.select();
}

function closePdfSearch() {
  if (elements.pdfSearchInput) elements.pdfSearchInput.value = "";
  setPdfSearchQuery("");
  setPdfSearchOpen(false);
  elements.pdfSearchInput?.blur();
}

function initializePdfSearch() {
  elements.pdfSearchInput?.addEventListener("focus", () => setPdfSearchOpen(true));
  elements.pdfSearchInput?.addEventListener("input", (event) => {
    setPdfSearchQuery(event.target.value);
  });
  elements.pdfSearchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void goToPdfSearchMatch(event.shiftKey ? -1 : 1);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closePdfSearch();
    }
  });
  elements.pdfSearchPrev?.addEventListener("click", () => void goToPdfSearchMatch(-1));
  elements.pdfSearchNext?.addEventListener("click", () => void goToPdfSearchMatch(1));
  elements.pdfSearchClose?.addEventListener("click", closePdfSearch);
  document.addEventListener("keydown", (event) => {
    if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "f") return;
    event.preventDefault();
    focusPdfSearchInput();
  });
  updatePdfSearchControls();
}
