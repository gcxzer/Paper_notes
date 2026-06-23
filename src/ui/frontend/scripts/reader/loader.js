const READER_SCRIPT_VERSION = "pdf-visual-selection-v2";

const READER_CLASSIC_SCRIPTS = [
  "scripts/shared/floating-pad.js?v=scratchpad-api-v1",
  "scripts/note/app.js?v=annotations-v6",
  `scripts/reader/page_state.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/core_api.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/core_chat_state.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/core_tool_payloads.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/core_model_selection.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/core_chat_normalization.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/panes.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/markdown.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/normalization.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/progress.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/progress_render.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/attachments_render.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/sources_render.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/render.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/prompts.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/tools.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/attachments.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/selection.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/composer.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/context_controls.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/models.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/projects.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/sessions.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/slash_commands.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/message_actions.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/submit_stream.js?v=${READER_SCRIPT_VERSION}`,
  `scripts/reader/chat/send.js?v=${READER_SCRIPT_VERSION}`,
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
    viewer.textContent = "";
    const container = document.createElement("div");
    container.className = "pdf-loading pdf-error";
    const heading = document.createElement("strong");
    heading.textContent = "Could not load PDF.js.";
    const detail = document.createElement("span");
    detail.textContent = String(error?.message || error || "Refresh the page or reinstall dependencies.");
    container.append(heading, detail);
    viewer.append(container);
  }
}

async function bootReader() {
  try {
    const pdfjsLib = await import("/node_modules/pdfjs-dist/legacy/build/pdf.mjs");
    pdfjsLib.GlobalWorkerOptions.workerSrc = "/node_modules/pdfjs-dist/legacy/build/pdf.worker.mjs";
    globalThis.pdfjsLib = pdfjsLib;
    try {
      const mermaidModule = await import("/node_modules/mermaid/dist/mermaid.esm.min.mjs");
      const mermaid = mermaidModule.default || mermaidModule;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        suppressErrorRendering: true,
        theme: "base",
        flowchart: {
          htmlLabels: false,
          useMaxWidth: true
        },
        sequence: {
          useMaxWidth: true
        },
        themeVariables: {
          background: "transparent",
          primaryColor: "#f8fafc",
          primaryTextColor: "#111827",
          primaryBorderColor: "#94a3b8",
          lineColor: "#64748b",
          secondaryColor: "#eff6ff",
          tertiaryColor: "#f5f3ff",
          fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
        }
      });
      globalThis.mermaid = mermaid;
    } catch (error) {
      console.warn("Mermaid diagrams will fall back to source blocks.", error);
      globalThis.mermaid = null;
    }
    for (const src of READER_CLASSIC_SCRIPTS) {
      await loadClassicScript(src);
    }
  } catch (error) {
    console.error(error);
    showReaderLoaderError(error);
  }
}

void bootReader();
