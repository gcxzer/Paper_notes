const READER_SCRIPT_VERSION = "provider-native-search-v1";

const READER_CLASSIC_SCRIPTS = [
  "scripts/note/app.js?v=annotations-v6",
  `scripts/reader/page_state.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/core.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/panes.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/render.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/prompts.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/tools.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/composer.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/models.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/sessions.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/debug.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/actions.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/layout.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/pdf/search.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/note-scroll.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/pdf/annotations.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/pdf/selection.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/pdf/links.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/pdf/render.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/pdf/tools.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/note.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/boot.js?v=${READER_SCRIPT_VERSION}`,
];

function loadClassicScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Could not load ${src}`));
    document.body.append(script);
  });
}

function showReaderLoaderError(error) {
  const title = document.querySelector("#readerTitle");
  const viewer = document.querySelector("#pdfViewer");
  if (title) title.textContent = "Reader setup needed";
  if (viewer) {
    viewer.innerHTML = `
      <div class="pdf-loading pdf-error">
        <strong>Could not load PDF.js.</strong>
        <span>${String(error?.message || error || "Refresh the page or reinstall dependencies.")}</span>
      </div>
    `;
  }
}

async function bootReader() {
  try {
    const pdfjsLib = await import("/node_modules/pdfjs-dist/legacy/build/pdf.mjs");
    pdfjsLib.GlobalWorkerOptions.workerSrc = "/node_modules/pdfjs-dist/legacy/build/pdf.worker.mjs";
    globalThis.pdfjsLib = pdfjsLib;
    for (const src of READER_CLASSIC_SCRIPTS) {
      await loadClassicScript(src);
    }
  } catch (error) {
    console.error(error);
    showReaderLoaderError(error);
  }
}

void bootReader();
