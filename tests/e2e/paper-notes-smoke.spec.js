const { test, expect } = require("@playwright/test");

const DEBUG_REQUEST_ID = "e2e-reader-chat-run";
const E2E_NOTE_ID = "pdf-deepseek-v4-e2e";
const E2E_PDF_BASE64 = "JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjcuMgoKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjcuMik+Pj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoKCjMgMCBvYmoKPDwvRm9udDw8L2hlbHYgNSAwIFI+Pj4+CmVuZG9iagoKNCAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDIwMCAyMDBdL1JvdGF0ZSAwL1Jlc291cmNlcyAzIDAgUi9QYXJlbnQgMiAwIFIvQ29udGVudHNbNiAwIFJdPj4KZW5kb2JqCgo1IDAgb2JqCjw8L1R5cGUvRm9udC9TdWJ0eXBlL1R5cGUxL0Jhc2VGb250L0hlbHZldGljYS9FbmNvZGluZy9XaW5BbnNpRW5jb2Rpbmc+PgplbmRvYmoKCjYgMCBvYmoKPDwvTGVuZ3RoIDYyPj4Kc3RyZWFtCgpxCkJUCjEgMCAwIDEgNDAgMTIwIFRtCi9oZWx2IDE2IFRmIFs8NDUzMjQ1MjA1MDQ0NDY+XVRKCkVUClEKCmVuZHN0cmVhbQplbmRvYmoKCnhyZWYKMCA3CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDA0MiAwMDAwMCBuIAowMDAwMDAwMTIwIDAwMDAwIG4gCjAwMDAwMDAxNzIgMDAwMDAgbiAKMDAwMDAwMDIxMyAwMDAwMCBuIAowMDAwMDAwMzIwIDAwMDAwIG4gCjAwMDAwMDA0MDkgMDAwMDAgbiAKCnRyYWlsZXIKPDwvU2l6ZSA3L1Jvb3QgMSAwIFIvSURbPEMyODA2QTZDNEIwMjNDQzNBQjA4MENDMjlFQzNBQTM1PjwxNUFCQUE0RjA0ODMyQjU3MENFNzdDNEU1NTMzQ0QzOD5dPj4Kc3RhcnR4cmVmCjUyMAolJUVPRgo=";

const E2E_LIBRARY = {
  categories: [
    { id: "all", name: "All Notes", parentId: null, order: 0, system: true },
    { id: "uncategorized", name: "Uncategorized", parentId: null, order: 1, system: true },
    { id: "deepseek", name: "DeepSeek", parentId: null, order: 2, system: false },
  ],
  notes: [{
    id: E2E_NOTE_ID,
    title: "DeepSeek V4",
    href: "resources/Papers/e2e-deepseek-v4.pdf",
    htmlHref: "resources/Paper-html/e2e-deepseek-v4.html",
    pdfStorageKey: "",
    date: "2026-05-13",
    order: 0,
    categoryId: "deepseek",
    venue: "",
    summary: "E2E fixture paper.",
    tags: ["tool-test", "deepseek"],
  }],
};

const E2E_NOTE_HTML = `<!doctype html>
<html>
  <body>
    <main class="note">
      <header class="note-section">
        <p class="note-eyebrow">Paper Note</p>
        <h1>DeepSeek V4</h1>
      </header>
      <section class="note-body">
        <h2>Overview</h2>
        <p>E2E fixture note.</p>
      </section>
    </main>
  </body>
</html>`;

function sseFrame(event, payload) {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

async function installReaderFixtures(page, options = {}) {
  await page.route("**/notes.json**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(E2E_LIBRARY) });
  });
  await page.route("**/resources/Paper-html/e2e-deepseek-v4.html**", async (route) => {
    await route.fulfill({ contentType: "text/html", body: E2E_NOTE_HTML });
  });
  await page.route("**/resources/Papers/e2e-deepseek-v4.pdf**", async (route) => {
    if (typeof options.beforePdfFulfill === "function") await options.beforePdfFulfill();
    await route.fulfill({
      contentType: "application/pdf",
      body: Buffer.from(E2E_PDF_BASE64, "base64"),
    });
  });
  await page.route("**/api/annotations**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route("**/api/settings/tools", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ globalAccess: "full_access", builtInTools: [], tools: [] }),
    });
  });
  await page.route("**/api/chat/context**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        usedTokens: 1200,
        maxTokens: 128000,
        percent: 1,
        status: "ok",
      }),
    });
  });
}

async function openFixtureReader(page) {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page).toHaveTitle("Paper Reader");
  await expect(page.getByRole("heading", { name: "DeepSeek V4" })).toBeVisible();
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");
}

async function installPdfTextFixture(page) {
  await page.evaluate(() => {
    const viewer = document.querySelector("#pdfViewer");
    viewer.innerHTML = "";
    viewer.style.position = "relative";
    viewer.style.height = "720px";
    viewer.style.overflow = "auto";

    function addPage(pageNumber, spans) {
      const page = document.createElement("div");
      page.className = "pdf-page";
      page.dataset.page = String(pageNumber);
      page.dataset.rendered = "true";
      page.style.position = "relative";
      page.style.width = "760px";
      page.style.height = "420px";
      page.style.margin = "20px auto";
      page.style.background = "white";

      const canvas = document.createElement("div");
      canvas.className = "pdf-page-canvas";
      canvas.style.position = "absolute";
      canvas.style.inset = "0";

      const selectionLayer = document.createElement("div");
      selectionLayer.className = "pdf-selection-layer";
      selectionLayer.style.position = "absolute";
      selectionLayer.style.inset = "0";

      const textLayer = document.createElement("div");
      textLayer.className = "textLayer pdf-text-layer";
      textLayer.style.position = "absolute";
      textLayer.style.inset = "0";
      textLayer.style.font = "28px Georgia, serif";

      const annotationLayer = document.createElement("div");
      annotationLayer.className = "pdf-annotation-layer";
      annotationLayer.style.position = "absolute";
      annotationLayer.style.inset = "0";

      spans.forEach((item) => {
        const span = document.createElement("span");
        span.setAttribute("role", "presentation");
        span.textContent = item.text;
        span.style.position = "absolute";
        span.style.left = `${item.x}px`;
        span.style.top = `${item.y}px`;
        span.style.font = item.font || "28px Georgia, serif";
        span.style.lineHeight = "1";
        textLayer.append(span);
      });

      textLayer.addEventListener("click", window.handleTextLayerMultiClick);
      textLayer.addEventListener("dblclick", window.handleTextLayerDoubleClick);
      textLayer.addEventListener("pointerdown", window.handleTextLayerPointerDown);
      textLayer.addEventListener("pointermove", window.handleTextLayerPointerMove);
      textLayer.addEventListener("pointerup", window.finishTextLayerPointerSelection);
      textLayer.addEventListener("pointercancel", window.finishTextLayerPointerSelection);
      textLayer.addEventListener("mouseup", window.schedulePdfSelectionOverlayRender);
      textLayer.addEventListener("copy", (event) => {
        const selectionText = window.textFromPdfSelection?.() || window.textFromSelectionForPage(page) || window.getSelection()?.toString() || "";
        const normalized = window.normalizeCopiedPdfText(selectionText);
        if (!normalized) return;
        event.preventDefault();
        event.clipboardData?.setData("text/plain", normalized);
      });

      page.append(canvas, selectionLayer, textLayer, annotationLayer);
      viewer.append(page);
      window.wirePageAnnotationEvents?.(page);
    }

    addPage(8, [
      { text: "Figure ", x: 40, y: 25 },
      { text: "fold of doubly ", x: 40, y: 70 },
      { text: "stochastic", x: 230, y: 70 },
      { text: " matrices 𝑀.", x: 365, y: 70 },
      { text: "normalization:", x: 40, y: 150 },
      { text: "𝑀", x: 40, y: 200, font: "30px Georgia, serif" },
      { text: "(𝑡)", x: 75, y: 198, font: "19px Georgia, serif" },
      { text: "=T", x: 120, y: 200, font: "30px Georgia, serif" },
      { text: "𝑟", x: 158, y: 214, font: "18px Georgia, serif" },
      { text: "(T", x: 176, y: 200, font: "30px Georgia, serif" },
      { text: "𝑐", x: 214, y: 214, font: "18px Georgia, serif" },
      { text: "(𝑀", x: 232, y: 200, font: "30px Georgia, serif" },
      { text: "(𝑡−1)", x: 286, y: 198, font: "19px Georgia, serif" },
      { text: ")),", x: 348, y: 200, font: "30px Georgia, serif" },
      { text: " (8)", x: 418, y: 200, font: "30px Georgia, serif" },
    ]);

    addPage(11, [
      { text: "𝑊", x: 80, y: 120, font: "30px Georgia, serif" },
      { text: "𝑈𝑄", x: 140, y: 120, font: "30px Georgia, serif" },
      { text: "𝑑", x: 220, y: 120, font: "30px Georgia, serif" },
      { text: "𝑐𝑛", x: 280, y: 120, font: "30px Georgia, serif" },
      { text: "Sliding KV Entries", x: 80, y: 230, font: "24px Georgia, serif" },
      { text: "Figure ", x: 80, y: 330, font: "28px Georgia, serif" },
      { text: "4 | Core architectures of HCA.", x: 175, y: 330, font: "28px Georgia, serif" },
    ]);

    window.updatePdfPageControl?.();
  });
}

async function installAgentMocks(page) {
  const requests = [];
  const debugRun = {
    requestId: DEBUG_REQUEST_ID,
    status: "completed",
    provider: "e2e",
    model: "mock-model",
    transport: "sse",
    sessionId: "e2e-session",
    noteId: E2E_NOTE_ID,
    startedAt: "2026-05-13T10:00:00.000Z",
    finishedAt: "2026-05-13T10:00:06.000Z",
    durationMs: 6000,
    preview: "这篇论文当前的 tags 是：tool-test、deepseek",
    events: [
      { type: "model_request", message: "Calling model provider.", data: { turn: 1 } },
      { type: "tool_call", message: "Executing tool: paper_notes_context", data: { toolName: "paper_notes_context" } },
      { type: "tool_result", message: "Tool completed: paper_notes_context", data: { toolName: "paper_notes_context" } },
      { type: "model_response", message: "Model provider returned a response.", data: { turn: 1 } },
    ],
  };

  await page.route("**/api/chat/progress**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        requestId: DEBUG_REQUEST_ID,
        status: "completed",
        stage: "completed",
        detail: "Agent run completed.",
        visibleDetail: "Reading note context...",
        events: debugRun.events,
        visibleEvents: [{ stage: "tool", detail: "Reading note context...", at: debugRun.startedAt }],
        workTrace: {
          status: "completed",
          items: [{ type: "tool", text: "Reading note context...", at: debugRun.startedAt }],
        },
      }),
    });
  });

  await page.route("**/api/chat/sessions**", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ sessions: [] }) });
  });

  await page.route("**/api/model/providers", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        defaultProvider: "openai",
        defaultModel: "gpt-5.5",
        modelConnectionConfigured: true,
        providers: [{
          name: "openai",
          displayName: "OpenAI API key",
          configured: true,
          ready: true,
          model: "gpt-5.5",
          selectedModel: "gpt-5.5",
          defaultModel: "gpt-5.5",
          capabilities: {
            supportsTools: true,
            supportsVision: true,
            supportsImageGeneration: true,
            supportsWebSearch: true,
          },
          models: [{
            value: "gpt-5.5",
            label: "GPT-5.5",
            shortLabel: "5.5",
            capabilities: {
              supportsTools: true,
              supportsVision: true,
              supportsImageGeneration: true,
              supportsWebSearch: true,
            },
          }],
        }],
      }),
    });
  });

  await page.route("**/api/debug/runs", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ runs: [debugRun] }) });
  });

  await page.route(`**/api/debug/runs/${DEBUG_REQUEST_ID}`, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ run: debugRun }) });
  });

  await page.route("**/api/media/file_e2e/download", async (route) => {
    await route.fulfill({
      contentType: "text/markdown",
      body: "# E2E file\n",
    });
  });

  await page.route("**/api/chat/stream", async (route) => {
    const request = route.request().postDataJSON();
    requests.push(request);
    const now = new Date().toISOString();
    const workTrace = {
      status: "completed",
      items: [{ type: "tool", text: "Reading note context...", at: now }],
    };
    const runTrace = {
      requestId: DEBUG_REQUEST_ID,
      startedAt: now,
      finishedAt: now,
      durationMs: 6000,
      status: "completed",
      events: debugRun.events,
    };
    const fileArtifacts = request.fileGeneration?.enabled ? [{
      id: "file_e2e",
      kind: "text",
      source: "generated",
      mimeType: "text/markdown",
      fileName: "reader-e2e.md",
      url: "/api/media/file_e2e",
      downloadUrl: "/api/media/file_e2e/download",
      size: 11,
      width: 0,
      height: 0,
    }] : [];
    const imageArtifacts = request.imageGeneration?.enabled ? [{
      id: "img_e2e",
      kind: "image",
      source: "generated",
      mimeType: "image/png",
      fileName: "generated.png",
      url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
      downloadUrl: "/api/media/img_e2e/download",
      size: 12,
      width: 1,
      height: 1,
    }] : [];
    const finalPayload = {
      completed: true,
      sessionId: "e2e-session",
      session: {
        id: "e2e-session",
        title: "E2E tags",
        noteId: request.noteId || E2E_NOTE_ID,
        provider: "e2e",
        model: "mock-model",
        updatedAt: now,
      },
      messages: [
        {
          role: "user",
          text: request.message,
          metadata: {
            generation: {
              imageGeneration: request.imageGeneration,
              fileGeneration: request.fileGeneration,
            },
          },
        },
        {
          role: "assistant",
          text: request.fileGeneration?.enabled
            ? "已创建 Markdown 文件：[`reader-e2e.md`](/api/media/file_e2e/download)"
            : "这篇论文当前的 tags 是：\n\n- `tool-test`\n- `deepseek`\n\n论文：**DeepSeek V4**",
          runTrace,
          workTrace,
          artifacts: [...fileArtifacts, ...imageArtifacts],
        },
      ],
      events: debugRun.events,
      artifacts: [...fileArtifacts, ...imageArtifacts],
    };
    const body = [
      sseFrame("progress", {
        progress: {
          requestId: request.requestId,
          status: "running",
          stage: "tool",
          detail: "Reading note context...",
          visibleDetail: "Reading note context...",
          events: debugRun.events.slice(0, 2),
          visibleEvents: [{ stage: "tool", detail: "Reading note context...", at: now }],
          workTrace,
        },
      }),
      sseFrame("final", finalPayload),
    ].join("");
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-store",
      },
      body,
    });
  });
  return { requests };
}

async function ignoreMissingFavicon(page) {
  await page.route("**/favicon.ico", async (route) => {
    await route.fulfill({ status: 204, body: "" });
  });
}

test("home settings, skills, and debug smoke", async ({ page }) => {
  await ignoreMissingFavicon(page);
  const consoleIssues = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleIssues.push(message.text());
  });
  const importUrlRequests = [];
  await page.route("**/notes.json**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        categories: [
          { id: "all", name: "All Notes", parentId: null, order: 0, system: true },
          { id: "uncategorized", name: "Uncategorized", parentId: null, order: 1, system: true },
        ],
        notes: [
          {
            id: "same-day-earlier",
            title: "Same Day Earlier",
            href: "",
            htmlHref: "",
            pdfStorageKey: "",
            date: "2026-05-13",
            order: 1,
            categoryId: "uncategorized",
            venue: "",
            summary: "",
            tags: [],
          },
          {
            id: "same-day-later",
            title: "Same Day Later",
            href: "",
            htmlHref: "",
            pdfStorageKey: "",
            date: "2026-05-13",
            order: 2,
            categoryId: "uncategorized",
            venue: "",
            summary: "",
            tags: [],
          },
        ],
      }),
    });
  });
  await page.route("**/api/import-paper-url", async (route) => {
    importUrlRequests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "url-import",
        title: "URL Imported Paper",
        href: "resources/Papers/url-import.pdf",
        htmlHref: "resources/Paper-html/url-import.html",
        pdfStorageKey: "",
        sourceUrl: "https://arxiv.org/pdf/1706.03762.pdf",
        date: "2026-05-14",
        order: 3,
        categoryId: "uncategorized",
        venue: "",
        summary: "",
        tags: [],
      }),
    });
  });
  await page.route("**/api/library", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: route.request().postData() || "{}" });
  });

  await page.goto("/index.html");
  await expect(page).toHaveTitle("Paper Notes");
  await expect(page.getByRole("heading", { name: "All Notes" })).toBeVisible();
  await expect(page.locator("#askAgentButton")).toHaveCount(0);
  await expect(page.locator("#chatDialog")).toHaveCount(0);
  await expect(page.locator(".note-card h3")).toHaveText(["Same Day Later", "Same Day Earlier"]);

  await page.locator("#sortButton").click();
  await page.getByRole("menuitem", { name: "Oldest first" }).click();
  await expect(page.locator("#sortButton")).toHaveText("Sort: Oldest");
  await expect(page.locator(".note-card h3")).toHaveText(["Same Day Earlier", "Same Day Later"]);

  await page.locator("#sortButton").click();
  await page.getByRole("menuitem", { name: "Newest first" }).click();
  await expect(page.locator("#sortButton")).toHaveText("Sort: Newest");
  await expect(page.locator(".note-card h3")).toHaveText(["Same Day Later", "Same Day Earlier"]);

  await page.locator("#addPdfButton").click();
  await expect(page.locator("#importMenu")).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Local PDF" })).toBeVisible();
  await page.getByRole("menuitem", { name: "DOI / arXiv / URL" }).click();
  await expect(page.locator("#importUrlDialog")).toBeVisible();
  await page.locator("#importUrlInput").fill("arxiv:1706.03762");
  await page.locator("#submitImportUrl").click();
  await expect(page.locator("#importUrlDialog")).not.toBeVisible();
  expect(importUrlRequests).toEqual([{ url: "arxiv:1706.03762", categoryId: "uncategorized" }]);
  await expect(page.locator(".note-card h3").first()).toHaveText("URL Imported Paper");

  await page.getByRole("button", { name: "New collection" }).click();
  await expect(page.locator("#categoryDialog")).toBeVisible();
  const categoryInputBox = await page.locator("#categoryNameInput").boundingBox();
  const categorySaveBox = await page.locator("#categoryDialog button[type='submit']").boundingBox();
  expect(categoryInputBox).not.toBeNull();
  expect(categorySaveBox).not.toBeNull();
  expect(categorySaveBox.y - (categoryInputBox.y + categoryInputBox.height)).toBeGreaterThanOrEqual(14);
  expect(Math.abs((categorySaveBox.x + categorySaveBox.width) - (categoryInputBox.x + categoryInputBox.width))).toBeLessThanOrEqual(2);
  await page.locator("#cancelCategoryDialog").click();
  await expect(page.locator("#categoryDialog")).not.toBeVisible();

  const settingsButton = page.getByRole("button", { name: "Settings" });
  const settingsBox = await settingsButton.boundingBox();
  expect(settingsBox).not.toBeNull();
  await page.mouse.move(settingsBox.x + settingsBox.width / 2, settingsBox.y + settingsBox.height / 2);
  await page.mouse.down();
  await expect(settingsButton).toHaveClass(/is-pressing/);
  await page.mouse.up();
  await expect(settingsButton).not.toHaveClass(/is-pressing/);
  await expect(page.locator("#openAiSettings")).toBeVisible();
  await expect(page.locator("#openMemorySettings")).toBeVisible();
  await expect(page.locator("#openToolSettings")).toBeVisible();
  await expect(page.locator("#openSkillsSettings")).toBeVisible();
  await expect(page.locator("#openDebugSettings")).toBeVisible();

  await page.locator("#openSkillsSettings").click();
  await expect(page.locator("#skillsSettingsDialog")).toBeVisible();
  await expect(page.locator("#skillsSettingsDialog")).toContainText("External directories");
  await expect(page.locator("#skillsSettingsDialog")).toContainText("file-artifact-creator");
  await page.locator('[data-skill-name="image-artifact-creator"]').click();
  await expect(page.locator("#skillsSettingsDetail")).toContainText("image-artifact-creator");
  await expect(page.locator("#skillsSettingsDetail")).toContainText("Image Artifact Creator");
  await page.locator("#closeSkillsSettingsDialog").click();

  await page.getByRole("button", { name: "Settings" }).click();
  await page.locator("#openDebugSettings").click();
  await expect(page.locator("#debugDialog")).toBeVisible();
  await expect(page.locator("#debugDialog")).toContainText("Debug");
  await expect(page.locator("#refreshDebugRuns")).toBeVisible();
  await expect(page.locator("#cleanupDebugRuns")).toBeVisible();

  expect(consoleIssues).toEqual([]);
});

test("reader ask flow renders response, work trace, and debug", async ({ page }) => {
  await openFixtureReader(page);
  const htmlToggle = page.getByRole("link", { name: "Toggle HTML note" });
  await expect(htmlToggle).toHaveAttribute("href", /resources\/Paper-html\/e2e-deepseek-v4\.html$/);
  await expect(htmlToggle).toHaveAttribute("target", "_blank");
  const readerUrl = page.url();
  await htmlToggle.click();
  await expect(page).toHaveURL(readerUrl);
  await expect(htmlToggle).toHaveAttribute("aria-expanded", "false");
  await htmlToggle.click();
  await expect(htmlToggle).toHaveAttribute("aria-expanded", "true");
  await installAgentMocks(page);
  const consoleIssues = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleIssues.push(message.text());
  });

  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  await expect(askInput).toBeVisible();
  await askInput.fill("查一下这篇论文的 tags");
  await page.getByRole("button", { name: "Send" }).click();

  const askPane = page.locator("#askPane");
  await expect(askPane.getByText("tool-test")).toBeVisible();
  await expect(askPane.getByText("deepseek", { exact: true })).toBeVisible();
  await expect(askPane.getByText("Worked for")).toBeVisible();
  await expect(askPane.getByText("Debug", { exact: true })).toBeVisible();

  await askPane.getByText("Worked for").click();
  await expect(askPane.getByText("Reading note context...")).toBeVisible();

  await page.locator(`[data-debug-run-open="${DEBUG_REQUEST_ID}"]`).click();
  await expect(page.locator("#readerDebugDialog")).toBeVisible();
  await expect(page.locator("#readerDebugDialog")).toContainText(DEBUG_REQUEST_ID);
  await expect(page.locator("#readerDebugDialog")).toContainText("model_request");

  expect(consoleIssues).toEqual([]);
});

test("reader HTML note renders before a delayed PDF finishes", async ({ page }) => {
  await ignoreMissingFavicon(page);
  let releasePdf;
  const pdfGate = new Promise((resolve) => {
    releasePdf = resolve;
  });
  await installReaderFixtures(page, { beforePdfFulfill: () => pdfGate });

  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page.locator("#notePage")).toContainText("E2E fixture note.");
  await expect(page.locator("#htmlPaneToggle")).toHaveAttribute("href", /resources\/Paper-html\/e2e-deepseek-v4\.html$/);

  releasePdf();
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");
});

test("reader PDF zoom persists after reload", async ({ page }) => {
  await openFixtureReader(page);

  await expect(page.locator("#zoomLabel")).toHaveText("215%");
  await page.locator("#zoomIn").click();
  await expect(page.locator("#zoomLabel")).toHaveText("225%");

  await page.reload();
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");
  await expect(page.locator("#zoomLabel")).toHaveText("225%");
});

test("reader annotation sidebar divider can be resized and persists", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  await openFixtureReader(page);

  const sidebar = page.locator(".pdf-annotation-sidebar");
  const resizer = page.locator("#annotationSidebarResizer");
  const before = await sidebar.boundingBox();
  const grip = await resizer.boundingBox();
  expect(before).toBeTruthy();
  expect(grip).toBeTruthy();

  await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
  await page.mouse.down();
  await expect(resizer).toHaveClass(/is-active/);
  await expect(page.locator("#readerResizer")).not.toHaveClass(/is-active/);
  await expect(page.locator("#askResizer")).not.toHaveClass(/is-active/);
  await expect(page.locator(".reader-resizer.is-active")).toHaveCount(1);
  await page.mouse.move(grip.x + grip.width / 2 + 72, grip.y + grip.height / 2);
  await page.mouse.up();
  await expect(page.locator(".reader-resizer.is-active")).toHaveCount(0);
  await expect(page.locator("body")).not.toHaveClass(/is-resizing-reader/);

  const after = await sidebar.boundingBox();
  expect(after.width).toBeGreaterThan(before.width + 40);

  await page.getByRole("button", { name: "Toggle Ask panel" }).click();
  await expect(page.locator("#readerResizer")).toBeVisible();
  await expect(page.locator("#askResizer")).toBeVisible();

  async function dragDivider(selector, deltaX) {
    const divider = page.locator(selector);
    const box = await divider.boundingBox();
    expect(box).toBeTruthy();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await expect(divider).toHaveClass(/is-active/);
    await expect(page.locator(".reader-resizer.is-active")).toHaveCount(1);
    await page.mouse.move(box.x + box.width / 2 + deltaX, box.y + box.height / 2);
    await page.mouse.up();
    await expect(page.locator(".reader-resizer.is-active")).toHaveCount(0);
    await expect(page.locator("body")).not.toHaveClass(/is-resizing-reader/);
  }

  await dragDivider("#readerResizer", 48);
  await dragDivider("#askResizer", -48);

  await page.reload();
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");
  const afterReload = await sidebar.boundingBox();
  expect(afterReload.width).toBeGreaterThan(before.width + 40);
});

test("reader PDF copy slicing preserves math Unicode characters", async ({ page }) => {
  await openFixtureReader(page);
  const htmlToggle = page.getByRole("link", { name: "Toggle HTML note" });
  if ((await htmlToggle.getAttribute("aria-expanded")) === "true") {
    await htmlToggle.click();
  }
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) === "true") {
    await askToggle.click();
  }

  await installPdfTextFixture(page);

  const samples = await page.evaluate(() => {
    const spans = Array.from(document.querySelectorAll(".pdf-page[data-page='11'] .textLayer span[role='presentation']"));
    return ["𝑊", "𝑈𝑄", "𝑑", "𝑐𝑛"].map((candidate) => {
      const span = spans.find((entry) => (entry.textContent || "") === candidate);
      if (!span) return { candidate, found: false, full: "", partial: "", hasReplacement: false };
      const rect = span.getBoundingClientRect();
      const partialRect = {
        left: rect.left,
        right: rect.left + rect.width * 0.72,
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width * 0.72,
        height: rect.height,
      };
      const full = window.sliceSpanTextByRect(span, rect);
      const partial = window.sliceSpanTextByRect(span, partialRect);
      return {
        candidate,
        found: true,
        full,
        partial,
        hasReplacement: full.includes("\uFFFD") || partial.includes("\uFFFD"),
      };
    });
  });

  expect(samples.every((sample) => sample.found)).toBe(true);
  expect(samples.every((sample) => sample.full === sample.candidate)).toBe(true);
  expect(samples.every((sample) => !sample.hasReplacement)).toBe(true);
});

test("reader PDF search uses app highlighter without visible text layer text", async ({ page }) => {
  await openFixtureReader(page);
  await installPdfTextFixture(page);

  await page.keyboard.press(process.platform === "darwin" ? "Meta+F" : "Control+F");
  await expect(page.locator("#pdfSearchInput")).toBeVisible();
  await page.locator("#pdfSearchInput").fill("figure");
  await expect(page.locator("#pdfSearchCount")).toHaveText("1/2");
  await expect(page.locator(".pdf-search-current")).toHaveText("Figure ");

  const highlightStyle = await page.evaluate(() => {
    const match = document.querySelector(".pdf-search-current");
    const style = getComputedStyle(match);
    const before = getComputedStyle(match, "::before");
    return {
      color: style.color,
      fill: style.webkitTextFillColor,
      background: style.backgroundColor,
      beforeBackground: before.backgroundColor,
    };
  });

  expect(highlightStyle.color).toBe("rgba(0, 0, 0, 0)");
  expect(highlightStyle.fill).toBe("rgba(0, 0, 0, 0)");
  expect(highlightStyle.background).toBe("rgba(0, 0, 0, 0)");
  expect(highlightStyle.beforeBackground).toContain("255, 143, 0");

  const initialScrollTop = await page.locator("#pdfViewer").evaluate((viewer) => viewer.scrollTop);
  await page.locator("#pdfSearchNext").click();
  await expect(page.locator("#pdfSearchCount")).toHaveText("2/2");
  await page.waitForFunction((scrollTop) => {
    const viewer = document.querySelector("#pdfViewer");
    return viewer && viewer.scrollTop > scrollTop;
  }, initialScrollTop);
  await expect(page.locator(".pdf-search-current")).toHaveText("Figure ");
});

test("reader PDF figure links flash the caption instead of nearby diagram text", async ({ page }) => {
  await openFixtureReader(page);
  await installPdfTextFixture(page);

  const geometry = await page.evaluate(() => {
    const pageElement = document.querySelector(".pdf-page[data-page='11']");
    const textLayer = pageElement.querySelector(".textLayer");
    const figure9 = document.createElement("span");
    figure9.setAttribute("role", "presentation");
    figure9.textContent = "Figure 9 | DeepSeek-V4 series performance.";
    figure9.style.position = "absolute";
    figure9.style.left = "80px";
    figure9.style.top = "80px";
    figure9.style.font = "28px Georgia, serif";
    figure9.style.lineHeight = "1";
    textLayer.append(figure9);

    const figureRect = window.pdfTargetHighlightRect(pageElement, 168, { destinationName: "figure.caption.4" });
    const figureScrollY = window.pdfTargetScrollY(pageElement, 168, { destinationName: "figure.caption.4" });
    const sourceMatchedRect = window.pdfTargetHighlightRect(pageElement, 300, {
      destinationName: "figure.caption.16",
      captionNumber: "9",
    });
    const genericFigureRect = window.pdfTargetHighlightRect(pageElement, 300, { destinationName: "figure.caption.16" });
    const textSnappedRect = window.pdfTargetHighlightRect(pageElement, 168, { destinationName: "named.destination" });
    return {
      figureTop: figureRect.top,
      figureScrollY,
      figureLeft: figureRect.left,
      figureWidth: figureRect.width,
      sourceMatchedTop: sourceMatchedRect.top,
      genericFigureTop: genericFigureRect.top,
      textSnappedTop: textSnappedRect.top,
      textSnappedWidth: textSnappedRect.width,
    };
  });

  expect(geometry.figureTop).toBeGreaterThan(300);
  expect(geometry.figureTop).toBeLessThan(360);
  expect(geometry.figureScrollY).toBeGreaterThan(300);
  expect(geometry.figureScrollY).toBeLessThan(340);
  expect(geometry.figureLeft).toBeGreaterThan(40);
  expect(geometry.figureWidth).toBeGreaterThan(420);
  expect(geometry.sourceMatchedTop).toBeLessThan(110);
  expect(geometry.genericFigureTop).toBeGreaterThan(300);
  expect(geometry.textSnappedTop).toBeLessThan(250);
  expect(geometry.textSnappedWidth).toBeLessThan(360);
});

test("reader PDF annotation editor stays inside the page without covering the annotation", async ({ page }) => {
  await openFixtureReader(page);
  await installPdfTextFixture(page);

  const placement = await page.evaluate(() => {
    const pageElement = document.querySelector(".pdf-page[data-page='8']");
    pageElement.style.height = "900px";
    const annotation = {
      id: "right-edge-annotation",
      type: "highlight",
      page: 8,
      x: 0.08,
      y: 0.18,
      w: 0.88,
      h: 0.13,
      rects: [
        { x: 0.08, y: 0.18, w: 0.88, h: 0.035 },
        { x: 0.08, y: 0.225, w: 0.88, h: 0.035 },
        { x: 0.08, y: 0.27, w: 0.44, h: 0.035 },
      ],
      color: "red",
      comment: "",
      quote: "",
    };
    window.openAnnotationEditor(annotation, pageElement);
    const editor = document.querySelector(".pdf-annotation-editor");
    const pageRect = pageElement.getBoundingClientRect();
    const editorRect = editor.getBoundingClientRect();
    const overlaps = annotation.rects.map((rect) => {
      const annotationRect = {
        left: pageRect.left + rect.x * pageRect.width,
        top: pageRect.top + rect.y * pageRect.height,
        right: pageRect.left + (rect.x + rect.w) * pageRect.width,
        bottom: pageRect.top + (rect.y + rect.h) * pageRect.height,
      };
      const width = Math.max(0, Math.min(editorRect.right, annotationRect.right) - Math.max(editorRect.left, annotationRect.left));
      const height = Math.max(0, Math.min(editorRect.bottom, annotationRect.bottom) - Math.max(editorRect.top, annotationRect.top));
      return width * height;
    });
    return {
      pageLeft: pageRect.left,
      pageRight: pageRect.right,
      editorLeft: editorRect.left,
      editorRight: editorRect.right,
      placement: editor.dataset.placement,
      maxOverlap: Math.max(...overlaps),
    };
  });

  expect(placement.editorLeft).toBeGreaterThanOrEqual(placement.pageLeft + 9);
  expect(placement.editorRight).toBeLessThanOrEqual(placement.pageRight - 9);
  expect(placement.maxOverlap).toBe(0);
});

test("reader PDF annotation list jumps without opening the editor", async ({ page }) => {
  await openFixtureReader(page);
  await installPdfTextFixture(page);

  await page.evaluate(() => {
    const pageElement = document.querySelector(".pdf-page[data-page='8']");
    pageElement.style.height = "900px";
    pdfState.annotations = [normalizeAnnotation({
      id: "lower-page-annotation",
      type: "highlight",
      page: 8,
      x: 0.08,
      y: 0.72,
      w: 0.72,
      h: 0.04,
      rects: [{ x: 0.08, y: 0.72, w: 0.72, h: 0.04 }],
      color: "yellow",
      comment: "Lower-page annotation",
      quote: "",
    })];
    renderAllAnnotations();
  });

  await page.locator(".annotation-card[data-annotation-id='lower-page-annotation']").click();
  await expect(page.locator(".pdf-annotation-editor")).toHaveCount(0);
  await expect(page.locator(".annotation-card[data-annotation-id='lower-page-annotation']")).toHaveClass(/is-selected/);
  const selectedMarker = page.locator(".pdf-annotation[data-annotation-id='lower-page-annotation']").first();
  await expect(selectedMarker).toHaveClass(/is-selection-outlined/);
  await expect(selectedMarker).toHaveCSS("outline-style", "solid");
  await page.waitForTimeout(3200);
  await expect(selectedMarker).not.toHaveClass(/is-selection-outlined/);
  await expect(selectedMarker).toHaveCSS("outline-style", "none");

  const placement = await page.evaluate(() => {
    const viewer = document.querySelector("#pdfViewer");
    const pageElement = document.querySelector(".pdf-page[data-page='8']");
    const annotation = pdfState.annotations.find((entry) => entry.id === "lower-page-annotation");
    const bounds = annotationBounds(annotation.rects);
    const viewerBox = viewer.getBoundingClientRect();
    const pageBox = pageElement.getBoundingClientRect();
    const annotationCenter = pageBox.top + (bounds.y + bounds.h / 2) * pageBox.height;
    return {
      ratio: (annotationCenter - viewerBox.top) / viewerBox.height,
      selectedId: pdfState.selectedAnnotationId,
    };
  });

  expect(placement.ratio).toBeGreaterThan(0.32);
  expect(placement.ratio).toBeLessThan(0.5);
  expect(placement.selectedId).toBe("lower-page-annotation");
});

test("reader PDF double-click selects the clicked word", async ({ page, context }) => {
  await openFixtureReader(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(page.url()).origin });
  const htmlToggle = page.getByRole("link", { name: "Toggle HTML note" });
  if ((await htmlToggle.getAttribute("aria-expanded")) === "true") {
    await htmlToggle.click();
  }
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) === "true") {
    await askToggle.click();
  }

  await installPdfTextFixture(page);
  await page.evaluate(() => {
    pdfState.annotations = [normalizeAnnotation({
      id: "text-selection-over-highlight",
      type: "highlight",
      page: 8,
      x: 0.28,
      y: 0.14,
      w: 0.24,
      h: 0.12,
      rects: [{ x: 0.28, y: 0.14, w: 0.24, h: 0.12 }],
      color: "yellow",
      comment: "",
      quote: "stochastic",
    })];
    renderAllAnnotations();
  });
  await page.evaluate(() => {
    const target = Array.from(document.querySelectorAll(".pdf-page[data-page='8'] .textLayer span[role='presentation']"))
      .find((span) => (span.textContent || "").includes("stochastic"));
    target?.scrollIntoView({ block: "center", inline: "center" });
  });

  const point = await page.evaluate(() => {
    const span = Array.from(document.querySelectorAll(".pdf-page[data-page='8'] .textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    const text = span.textContent || "";
    const index = text.indexOf("stochastic") + 4;
    const range = document.createRange();
    range.setStart(span.firstChild, index);
    range.setEnd(span.firstChild, index + 1);
    const rect = range.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  });

  await page.mouse.dblclick(point.x, point.y);
  await page.waitForFunction(() => document.querySelector(".pdf-selection-rect"));
  await page.keyboard.press(process.platform === "darwin" ? "Meta+C" : "Control+C");

  expect(await page.evaluate(() => getSelection().toString())).toBe("stochastic");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("stochastic");
  await expect(page.locator(".pdf-selection-rect")).toHaveCount(1);
  await expect(page.locator(".pdf-annotation-editor")).toHaveCount(0);

  await page.evaluate(() => {
    window.getSelection()?.removeAllRanges();
    clearPdfSelectionOverlays();
  });
  await page.waitForTimeout(650);
  const annotationHit = await page.evaluate(({ x, y }) => {
    const pageElement = document.querySelector(".pdf-page[data-page='8']");
    const canvas = pageElement?.querySelector(".pdf-page-canvas");
    const box = canvas?.getBoundingClientRect();
    const annotation = pageElement ? annotationAtPagePoint(pageElement, { clientX: x, clientY: y }) : null;
    return {
      hit: annotation?.id || "",
      mode: pdfState.mode,
      x: box ? (x - box.left) / box.width : null,
      y: box ? (y - box.top) / box.height : null,
    };
  }, point);
  expect(annotationHit.hit).toBe("text-selection-over-highlight");
  await page.mouse.click(point.x, point.y);
  await expect(page.locator(".pdf-annotation-editor")).toBeVisible();
  await expect(page.locator(".pdf-annotation.is-selection-outlined")).toHaveCount(0);
});

test("reader PDF drag selection stays on the current line over blank space", async ({ page }) => {
  await openFixtureReader(page);
  const htmlToggle = page.getByRole("link", { name: "Toggle HTML note" });
  if ((await htmlToggle.getAttribute("aria-expanded")) === "true") {
    await htmlToggle.click();
  }
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) === "true") {
    await askToggle.click();
  }

  await installPdfTextFixture(page);

  const points = await page.evaluate(() => {
    const pageElement = document.querySelector(".pdf-page[data-page='8']");
    const canvas = pageElement.querySelector(".pdf-page-canvas");
    const span = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    span.scrollIntoView({ block: "center", inline: "center" });
    const spanBox = span.getBoundingClientRect();
    const pageBox = canvas.getBoundingClientRect();
    return {
      start: { x: spanBox.left + 2, y: spanBox.top + spanBox.height / 2 },
      blank: { x: pageBox.right - 36, y: spanBox.top + spanBox.height / 2 },
    };
  });

  await page.mouse.move(points.start.x, points.start.y);
  await page.mouse.down();
  await page.mouse.move(points.blank.x, points.blank.y, { steps: 8 });
  await page.waitForFunction(() => getSelection().toString().includes("stochastic"));

  const selected = await page.evaluate(() => getSelection().toString());
  expect(selected).toContain("stochastic");
  expect(selected).toContain("matrices");
  expect(selected).not.toContain("Figure");
  expect(selected).not.toContain("fold of doubly");
  await page.mouse.up();
});

test("reader PDF drag selection auto-scrolls and can cross pages", async ({ page }) => {
  await openFixtureReader(page);
  const htmlToggle = page.getByRole("link", { name: "Toggle HTML note" });
  if ((await htmlToggle.getAttribute("aria-expanded")) === "true") {
    await htmlToggle.click();
  }
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) === "true") {
    await askToggle.click();
  }

  await installPdfTextFixture(page);
  const points = await page.evaluate(() => {
    const viewer = document.querySelector("#pdfViewer");
    viewer.style.height = "300px";
    viewer.scrollTop = 0;
    const firstPage = document.querySelector(".pdf-page[data-page='8']");
    const span = Array.from(firstPage.querySelectorAll(".textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    const spanBox = span.getBoundingClientRect();
    const viewerBox = viewer.getBoundingClientRect();
    return {
      start: { x: spanBox.left + 2, y: spanBox.top + spanBox.height / 2 },
      bottom: { x: spanBox.left + 8, y: viewerBox.bottom - 8 },
    };
  });

  await page.mouse.move(points.start.x, points.start.y);
  await page.mouse.down();
  await page.mouse.move(points.bottom.x, points.bottom.y, { steps: 12 });
  await page.waitForFunction(() => document.querySelector("#pdfViewer").scrollTop > 100);
  await page.waitForFunction(() => document.querySelectorAll(".pdf-page[data-page='11'] .pdf-selection-rect").length > 0);

  const selectionState = await page.evaluate(() => ({
    scrollTop: document.querySelector("#pdfViewer").scrollTop,
    page8Rects: document.querySelectorAll(".pdf-page[data-page='8'] .pdf-selection-rect").length,
    page11Rects: document.querySelectorAll(".pdf-page[data-page='11'] .pdf-selection-rect").length,
    text: window.getSelection()?.toString() || "",
  }));
  expect(selectionState.scrollTop).toBeGreaterThan(100);
  expect(selectionState.page8Rects).toBeGreaterThan(0);
  expect(selectionState.page11Rects).toBeGreaterThan(0);
  expect(selectionState.text).toContain("stochastic");
  await page.mouse.up();
});

test("reader PDF underline can be clicked without blocking word selection", async ({ page }) => {
  await openFixtureReader(page);
  const htmlToggle = page.getByRole("link", { name: "Toggle HTML note" });
  if ((await htmlToggle.getAttribute("aria-expanded")) === "true") {
    await htmlToggle.click();
  }
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) === "true") {
    await askToggle.click();
  }

  await installPdfTextFixture(page);
  const point = await page.evaluate(() => {
    const pageElement = document.querySelector(".pdf-page[data-page='8']");
    const canvas = pageElement.querySelector(".pdf-page-canvas");
    const pageBox = canvas.getBoundingClientRect();
    const span = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    const spanBox = span.getBoundingClientRect();
    const underlineHeight = 3;
    pdfState.annotations = [normalizeAnnotation({
      id: "clickable-underline",
      type: "underline",
      page: 8,
      x: (spanBox.left - pageBox.left) / pageBox.width,
      y: (spanBox.bottom - underlineHeight - pageBox.top) / pageBox.height,
      w: spanBox.width / pageBox.width,
      h: underlineHeight / pageBox.height,
      rects: [{
        x: (spanBox.left - pageBox.left) / pageBox.width,
        y: (spanBox.bottom - underlineHeight - pageBox.top) / pageBox.height,
        w: spanBox.width / pageBox.width,
        h: underlineHeight / pageBox.height,
      }],
      color: "yellow",
      comment: "",
      quote: "stochastic",
    })];
    renderAllAnnotations();
    return { x: spanBox.left + spanBox.width / 2, y: spanBox.top + spanBox.height / 2 };
  });

  await page.mouse.dblclick(point.x, point.y);
  await page.waitForFunction(() => getSelection().toString() === "stochastic");
  await page.waitForTimeout(350);
  await expect(page.locator(".pdf-annotation-editor")).toHaveCount(0);

  await page.evaluate(() => {
    window.getSelection()?.removeAllRanges();
    clearPdfSelectionOverlays();
  });
  await page.waitForTimeout(650);
  await page.mouse.click(point.x, point.y);
  await expect(page.locator(".pdf-annotation-editor")).toBeVisible();
  await expect(page.locator(".pdf-annotation.is-selection-outlined")).toHaveCount(0);
});

test("reader PDF formula copy keeps inline subscript glyphs", async ({ page, context }) => {
  await openFixtureReader(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: new URL(page.url()).origin });
  const htmlToggle = page.getByRole("link", { name: "Toggle HTML note" });
  if ((await htmlToggle.getAttribute("aria-expanded")) === "true") {
    await htmlToggle.click();
  }
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) === "true") {
    await askToggle.click();
  }

  await installPdfTextFixture(page);

  const copied = await page.evaluate(async () => {
    const pageElement = document.querySelector(".pdf-page[data-page='8']");
    const spans = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"));
    const anchorIndex = spans.findIndex((span) => (span.textContent || "") === "normalization:");
    const firstIndex = spans.findIndex((span, index) => index > anchorIndex && (span.textContent || "") === "𝑀");
    const lastIndex = spans.findIndex((span, index) => index > firstIndex && (span.textContent || "").includes("(8)"));
    const first = spans[firstIndex];
    const last = spans[lastIndex];
    first.scrollIntoView({ block: "center", inline: "center" });

    const range = document.createRange();
    range.setStart(first.firstChild, 0);
    range.setEnd(last.firstChild, last.firstChild.textContent.length);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand("copy");
    return navigator.clipboard.readText();
  });

  expect(copied).toBe("𝑀(𝑡)=T𝑟(T𝑐(𝑀(𝑡−1))), (8)");
  expect(copied).not.toContain("\n𝑟𝑐");
});

test("reader ask tools send generation modes and render generated file cards", async ({ page }) => {
  await openFixtureReader(page);
  const { requests } = await installAgentMocks(page);

  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  await expect(askInput).toBeVisible();

  await page.locator("#readerToolMenuButton").click();
  await page.getByRole("button", { name: /Generate image/ }).click();
  await expect(page.locator("#readerAttachmentTray")).toContainText("Image generation");
  await askInput.fill("生成一张论文概念图");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator("#askPane")).toContainText("Worked for");
  expect(requests.at(-1).imageGeneration).toMatchObject({ enabled: true, format: "png" });
  await expect(page.locator("#readerAttachmentTray")).toBeHidden();

  await page.locator("#readerToolMenuButton").click();
  await page.getByRole("button", { name: /Generate file/ }).click();
  await page.getByRole("button", { name: /Markdown/ }).click();
  await expect(page.locator("#readerAttachmentTray")).toContainText("Markdown file");
  await askInput.fill("生成 markdown 总结文件");
  await page.getByRole("button", { name: "Send" }).click();
  const inlineFileLink = page.getByRole("link", { name: "reader-e2e.md", exact: true });
  await expect(inlineFileLink).toBeVisible();
  await expect(inlineFileLink.locator("code")).toHaveCount(0);
  await expect(page.locator("#askPane")).not.toContainText("@@CODESPAN");
  await expect(inlineFileLink).toHaveAttribute("href", /\/api\/media\/file_e2e\/download/);
  await expect(page.locator(".ask-file-card").filter({ hasText: "reader-e2e.md" })).toHaveAttribute("href", /\/api\/media\/file_e2e\/download/);
  expect(requests.at(-1).fileGeneration).toMatchObject({ enabled: true, format: "markdown" });
  await expect(page.locator("#readerAttachmentTray")).toBeHidden();
  await expect(page.getByText("Generate file · Markdown file")).toBeVisible();

  await page.getByRole("button", { name: "Edit" }).click();
  await page.locator("[data-user-message-edit-input]").fill("生成 markdown 总结文件，标题更短");
  await page.locator("[data-user-message-edit-form]").getByRole("button", { name: "Send" }).click();
  expect(requests.at(-1).fileGeneration).toMatchObject({ enabled: true, format: "markdown" });
  await expect(page.getByText("Generate file · Markdown file")).toBeVisible();

  await page.locator("#readerToolMenuButton").click();
  await page.getByRole("button", { name: /Generate file/ }).click();
  await page.getByRole("button", { name: /Markdown/ }).click();
  await page.locator("[data-generation-mode-remove]").click();
  await askInput.fill("普通聊天");
  await page.getByRole("button", { name: "Send" }).click();
  expect(requests.at(-1).fileGeneration).toBeUndefined();
  expect(requests.at(-1).imageGeneration).toBeUndefined();
});
