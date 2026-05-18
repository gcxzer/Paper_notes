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
        <p>Inline math $M$ and escaped math \\(x^2\\).</p>
        <p>Block math \\[e^{ix}=\\cos x+i\\sin x\\]</p>
        <pre><code>Keep code math $not_rendered$</code></pre>
      </section>
    </main>
  </body>
</html>`;

function sseFrame(event, payload) {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

async function installReaderFixtures(page, options = {}) {
  await page.route("**/notes.json**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(options.library || E2E_LIBRARY),
    });
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
    if (route.request().method() === "POST") {
      const payload = route.request().postDataJSON();
      if (typeof options.onAnnotationSave === "function") {
        await options.onAnnotationSave(payload);
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(options.annotationSaveResponse || { ok: true }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(options.annotations || []),
    });
  });
  await page.route("**/api/settings/tools", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ globalAccess: "full_access", builtInTools: [], tools: [] }),
    });
  });
  await page.route("**/api/chat/context**", async (route) => {
    const payload = typeof options.contextStatus === "function"
      ? await options.contextStatus(route.request())
      : options.contextStatus;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(payload || {
        success: true,
        usedTokens: 1200,
        maxTokens: 128000,
        percent: 1,
        status: "ok",
      }),
    });
  });
  await page.route("**/api/chat/tool-snapshots**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(options.toolSnapshots || { snapshots: [] }),
    });
  });
}

async function installStubPdfJs(page, options = {}) {
  const pageCount = Number(options.pageCount || 12);
  const delayedZoomPage = Number(options.delayedZoomPage || 7);
  const delayedZoomMs = Number(options.delayedZoomMs || 250);
  const zoomHeightExtraByPage = JSON.stringify(options.zoomHeightExtraByPage || {});
  const moduleSource = `
    export const GlobalWorkerOptions = { workerSrc: "" };
    export const AnnotationType = { LINK: 2 };
    export const OPS = {};
    export const Util = {
      transform(left, right) {
        if (!Array.isArray(left) || !Array.isArray(right)) return [1, 0, 0, 1, 0, 0];
        const [a1, b1, c1, d1, e1, f1] = left;
        const [a2, b2, c2, d2, e2, f2] = right;
        return [
          a1 * a2 + c1 * b2,
          b1 * a2 + d1 * b2,
          a1 * c2 + c1 * d2,
          b1 * c2 + d1 * d2,
          a1 * e2 + c1 * f2 + e1,
          b1 * e2 + d1 * f2 + f1
        ];
      }
    };

    function delay(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function makeViewport(pageNumber, scale) {
      const width = 720;
      const zoomHeightExtraByPage = ${zoomHeightExtraByPage};
      const extraHeight = scale > 2.15 ? Number(zoomHeightExtraByPage[String(pageNumber)] || 0) : 0;
      const height = 960 + extraHeight;
      return {
        width,
        height,
        scale,
        transform: [1, 0, 0, 1, 0, 0],
        convertToViewportRectangle(rect) {
          return Array.isArray(rect) ? rect.slice() : [0, 0, 0, 0];
        }
      };
    }

    function makePage(pageNumber) {
      return {
        async getAnnotations() {
          return [];
        },
        async getOperatorList() {
          return { fnArray: [], argsArray: [] };
        },
        async getTextContent() {
          return { items: [], styles: {} };
        },
        getViewport({ scale }) {
          return makeViewport(pageNumber, scale);
        },
        render({ canvasContext, viewport }) {
          if (canvasContext) {
            canvasContext.fillStyle = pageNumber % 2 ? "#fbfbfd" : "#f3f4f8";
            canvasContext.fillRect(0, 0, canvasContext.canvas.width, canvasContext.canvas.height);
            canvasContext.fillStyle = "#222";
            canvasContext.font = "28px sans-serif";
            canvasContext.fillText("Stub page " + pageNumber, 32, 64);
          }
          const waitMs = pageNumber === ${delayedZoomPage} && viewport.scale > 2.15 ? ${delayedZoomMs} : 0;
          return { promise: delay(waitMs) };
        }
      };
    }

    export function getDocument() {
      return {
        promise: Promise.resolve({
          numPages: ${pageCount},
          async getPage(pageNumber) {
            return makePage(pageNumber);
          },
          async getPageIndex(ref) {
            return typeof ref === "number" ? ref : 0;
          }
        })
      };
    }
  `;

  await page.route("**/node_modules/pdfjs-dist/legacy/build/pdf.mjs", async (route) => {
    await route.fulfill({
      contentType: "text/javascript",
      body: moduleSource,
    });
  });
}

async function openFixtureLibrary(page, options = {}) {
  await ignoreMissingFavicon(page);
  await page.route("**/notes.json**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(options.library || E2E_LIBRARY),
    });
  });
  await page.route("**/api/library", async (route) => {
    const payload = route.request().postDataJSON();
    if (typeof options.onLibrarySync === "function") {
      await options.onLibrarySync(payload);
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
  await page.goto("/index.html");
  await expect(page).toHaveTitle("Paper Notes");
  await expect(page.getByRole("heading", { name: "All Notes" })).toBeVisible();
  await expect(page.locator(".note-card h3").first()).toHaveText("DeepSeek V4");
}

async function openFixtureReader(page) {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page).toHaveTitle("Paper Reader");
  await expect(page.getByRole("heading", { name: "DeepSeek V4" })).toBeVisible();
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");
}

async function showAskPane(page) {
  await page.waitForFunction(() => typeof window.openChatSessionView === "function");
  if (!(await page.locator("#askPane").isVisible())) {
    await page.waitForFunction(() => typeof window.setAskPaneVisible === "function");
    await page.evaluate(() => window.setAskPaneVisible(true));
  }
  await expect(page.locator("#askPane")).toBeVisible();
}

test("library workbench row exposes icon actions without changing note actions", async ({ page }) => {
  await openFixtureLibrary(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  const card = page.locator(".note-card").first();
  await expect(card.locator(".note-card-icon .ui-icon")).toBeVisible();
  await expect(card.getByRole("link", { name: "Open DeepSeek V4" })).toBeVisible();

  await card.getByRole("button", { name: "Rename DeepSeek V4" }).click();
  await expect(page.locator("#renameNoteDialog")).toBeVisible();
  await page.locator("#closeRenameNoteDialog").click();
  await expect(page.locator("#renameNoteDialog")).not.toBeVisible();

  await card.getByRole("button", { name: "Delete DeepSeek V4" }).click();
  await expect(page.locator("#confirmDialog")).toBeVisible();
  await page.locator("#cancelConfirmDialog").click();
  await expect(page.locator("#confirmDialog")).not.toBeVisible();
});

test("reader workbench toolbar toggles panes and keeps ask composer visible", async ({ page }) => {
  await openFixtureReader(page);

  await expect(page.getByRole("link", { name: "Toggle HTML note" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Toggle Ask panel" })).toBeVisible();
  await page.getByRole("button", { name: "Toggle Ask panel" }).click();

  await expect(page.locator("#askPane")).toBeVisible();
  await expect(page.locator("#readerChatInput")).toBeVisible();
  await expect(page.locator("#sendReaderChat")).toBeVisible();
  await expect(page.getByRole("button", { name: "Close Ask panel" })).toBeVisible();
});

test("settings modal stays within the mobile viewport and keeps provider list scrollable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/settings/ai", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "openai",
        providerSource: "default",
        supportedProviders: ["openai", "codex-oauth", "anthropic", "gemini", "deepseek"],
        configured: false,
        ready: false,
        model: "gpt-5.5",
        modelConfigured: false,
        modelConnectionConfigured: false,
        codexAuth: { loggedIn: false },
      }),
    });
  });
  await page.route("**/api/model/providers", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        defaultProvider: "openai",
        defaultModel: "gpt-5.5",
        modelConnectionConfigured: false,
        providers: [
          { name: "openai", displayName: "OpenAI API key", configured: false, ready: false, models: [{ value: "gpt-5.5", label: "GPT-5.5" }] },
          { name: "codex-oauth", displayName: "Codex OAuth", configured: false, ready: false, models: [{ value: "gpt-5.5", label: "GPT-5.5" }] },
          { name: "anthropic", displayName: "Anthropic", configured: false, ready: false, models: [{ value: "claude-sonnet-4.5", label: "Claude Sonnet 4.5" }] },
          { name: "gemini", displayName: "Gemini", configured: false, ready: false, models: [{ value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" }] },
          { name: "deepseek", displayName: "DeepSeek", configured: false, ready: false, models: [{ value: "deepseek-chat", label: "DeepSeek Chat" }] },
        ],
      }),
    });
  });

  await openFixtureLibrary(page);
  await page.getByRole("button", { name: "Settings" }).click();
  await page.locator("#openAiSettings").click();
  await expect(page.locator("#aiSettingsDialog")).toBeVisible();

  const metrics = await page.evaluate(() => {
    const card = document.querySelector(".ai-settings-card");
    const providerList = document.querySelector(".ai-provider-list");
    const rect = card.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      bottom: rect.bottom,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      listOverflowY: getComputedStyle(providerList).overflowY,
      listCanScroll: providerList.scrollHeight >= providerList.clientHeight,
    };
  });
  expect(metrics.left).toBeGreaterThanOrEqual(0);
  expect(metrics.right).toBeLessThanOrEqual(metrics.viewportWidth);
  expect(metrics.bottom).toBeLessThanOrEqual(metrics.viewportHeight);
  expect(metrics.listOverflowY).toBe("auto");
  expect(metrics.listCanScroll).toBe(true);
});

test("floating scratchpad persists content and position across library and reader", async ({ page }) => {
  let scratchpadState = { activeId: "", pads: [] };
  await page.route("**/api/scratchpads", async (route) => {
    if (route.request().method() === "POST") {
      scratchpadState = route.request().postDataJSON();
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(scratchpadState),
    });
  });
  await openFixtureLibrary(page);
  await expect(page.locator(".floating-pad")).toBeHidden();
  await page.locator("#settingsButton").click();
  await expect(page.locator("#scratchpadSettingsSwitch")).toHaveAttribute("aria-checked", "false");
  await page.locator("#scratchpadSettingsSwitch").click();
  await expect(page.locator("#scratchpadSettingsSwitch")).toHaveAttribute("aria-checked", "true");
  const button = page.locator(".floating-pad-button");
  await expect(button).toBeVisible();
  await page.locator(".app-shell").click({ position: { x: 20, y: 20 } });

  const before = await button.boundingBox();
  expect(before).toBeTruthy();
  await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
  await page.mouse.down();
  await page.mouse.move(before.x - 120, before.y - 82, { steps: 6 });
  await page.mouse.up();

  const after = await button.boundingBox();
  expect(after).toBeTruthy();
  expect(after.x).toBeLessThan(before.x - 60);
  expect(after.y).toBeLessThan(before.y - 40);
  await expect(page.locator(".floating-pad-panel")).toBeHidden();

  await button.click();
  await expect(page.locator(".floating-pad-panel")).toBeVisible();
  const panelBox = await page.locator(".floating-pad-panel").boundingBox();
  expect(panelBox).toBeTruthy();
  expect(panelBox.width).toBeGreaterThan(430);
  expect(panelBox.height).toBeGreaterThan(500);
  await expect(page.locator(".floating-pad-list-panel")).toBeHidden();
  await expect(page.locator(".floating-pad-panel")).not.toHaveClass(/is-list-open/);
  await page.locator(".floating-pad-input").fill("scratch idea\n\ncompare DeepSeek and Claude session UX");
  await expect(page.locator(".floating-pad-status")).toHaveText("Saved");
  await expect(page.locator(".floating-pad-active-title")).toHaveText("Pad 1");
  await page.locator("[data-floating-pad-clear]").click();
  await expect(page.locator(".floating-pad-input")).toHaveValue("");
  await page.keyboard.press(process.platform === "darwin" ? "Meta+Z" : "Control+Z");
  await expect(page.locator(".floating-pad-input")).toHaveValue(/compare DeepSeek/);
  await page.locator("[data-floating-pad-directory]").click();
  await expect(page.locator(".floating-pad-list-panel")).toBeVisible();
  await expect(page.locator(".floating-pad-input")).toBeHidden();
  await expect(page.locator(".floating-pad-footer")).toBeHidden();
  await expect(page.locator(".floating-pad-panel")).toHaveClass(/is-list-open/);
  await page.locator("[data-floating-pad-new]").click();
  await expect(page.locator(".floating-pad-list-panel")).toBeHidden();
  await expect(page.locator(".floating-pad-input")).toHaveValue("");
  await page.locator(".floating-pad-input").fill("second pad idea");
  await page.locator("[data-floating-pad-directory]").click();
  await expect(page.locator(".floating-pad-list-item")).toHaveCount(2);
  await expect(page.locator(".floating-pad-list-item").filter({ hasText: "Pad 1" })).not.toContainText("scratch idea");
  await page.locator(".floating-pad-list-row").last().hover();
  await page.locator("[data-floating-pad-menu]").last().click();
  await expect(page.locator(".floating-pad-action-menu:not([hidden])")).toBeVisible();
  const menuBox = await page.locator(".floating-pad-action-menu:not([hidden])").boundingBox();
  const viewport = page.viewportSize();
  expect(menuBox).toBeTruthy();
  expect(viewport).toBeTruthy();
  expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(viewport.width);
  expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(viewport.height);
  await page.locator("[data-floating-pad-rename]").last().click();
  await expect(page.locator(".floating-pad-rename-form")).toBeVisible();
  await page.locator(".floating-pad-rename-form input").fill("Renamed pad");
  await page.locator(".floating-pad-rename-form").locator("button", { hasText: "Save" }).click();
  await expect(page.locator(".floating-pad-active-title")).toHaveText("Renamed pad");
  await page.locator(".floating-pad-list-row").last().hover();
  await page.locator("[data-floating-pad-menu]").last().click();
  await page.locator("[data-floating-pad-delete]").last().click();
  await expect(page.locator(".floating-pad-action-menu:not([hidden])")).toContainText("Confirm delete");
  await page.locator("[data-floating-pad-delete]").last().click();
  await expect(page.locator(".floating-pad-list-item")).toHaveCount(1);
  await page.locator("[data-floating-pad-new]").click();
  await page.locator(".floating-pad-input").fill("second pad idea");
  await page.locator("[data-floating-pad-directory]").click();
  await expect(page.locator(".floating-pad-list-item")).toHaveCount(2);
  await page.locator(".floating-pad-list-item").filter({ hasText: "Pad 1" }).click();
  await expect(page.locator(".floating-pad-input")).toHaveValue(/compare DeepSeek/);
  await page.locator("[data-floating-pad-directory]").click();
  await page.locator(".floating-pad-list-item").filter({ hasText: "Pad 2" }).click();
  await expect(page.locator(".floating-pad-input")).toHaveValue("second pad idea");
  await page.locator(".floating-pad-input").click();
  await expect(page.locator(".floating-pad-panel")).toBeVisible();
  await page.locator(".app-shell").click({ position: { x: 20, y: 20 } });
  await expect(page.locator(".floating-pad-panel")).toBeHidden();
  await button.click();
  await expect(page.locator(".floating-pad-panel")).toBeVisible();

  await openFixtureReader(page);
  const readerButton = page.locator(".floating-pad-button");
  await expect(readerButton).toBeVisible();
  const readerBox = await readerButton.boundingBox();
  expect(readerBox).toBeTruthy();
  expect(Math.abs(readerBox.x - after.x)).toBeLessThan(2);
  expect(Math.abs(readerBox.y - after.y)).toBeLessThan(2);
  await expect(page.locator(".floating-pad-panel")).toBeVisible();
  await expect(page.locator(".floating-pad-input")).toHaveValue("second pad idea");
  await page.locator("[data-floating-pad-directory]").click();
  await page.locator(".floating-pad-list-item").filter({ hasText: "Pad 1" }).click();
  await expect(page.locator(".floating-pad-input")).toHaveValue(/compare DeepSeek/);
});

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

async function installAgentMocks(page, options = {}) {
  const requests = [];
  const cancelRequests = [];
  const extraArtifacts = Array.isArray(options.artifacts) ? options.artifacts : [];
  const streamGate = options.streamGate;
  const progressWorkItems = Array.isArray(options.workTraceItems) && options.workTraceItems.length
    ? options.workTraceItems
    : [{ type: "tool", text: "Reading note context...", at: "2026-05-13T10:00:00.000Z" }];
  const progressVisibleEvents = Array.isArray(options.progressVisibleEvents) && options.progressVisibleEvents.length
    ? options.progressVisibleEvents
    : [{ stage: "tool", detail: "Reading note context...", at: "2026-05-13T10:00:00.000Z" }];
  let streamFinished = false;
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
      { type: "tool_call", message: "Executing tool: get_note_context", data: { toolName: "get_note_context" } },
      { type: "tool_result", message: "Tool completed: get_note_context", data: { toolName: "get_note_context" } },
      { type: "model_response", message: "Model provider returned a response.", data: { turn: 1 } },
    ],
  };
  if (Array.isArray(options.runTraceEvents)) {
    debugRun.events = options.runTraceEvents;
  }

  await page.route("**/api/chat/progress**", async (route) => {
    const running = Boolean(streamGate && !streamFinished);
    const cancelled = Boolean(options.cancelReturnsCancelling && cancelRequests.length);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        requestId: DEBUG_REQUEST_ID,
        status: cancelled ? "cancelled" : running ? "running" : "completed",
        stage: cancelled ? "cancelled" : running ? "tool" : "completed",
        detail: cancelled ? "Agent run cancelled." : running ? "Reading note context..." : "Agent run completed.",
        visibleDetail: "Reading note context...",
        events: debugRun.events,
        visibleEvents: progressVisibleEvents,
        workTrace: {
          status: cancelled ? "cancelled" : running ? "running" : "completed",
          items: progressWorkItems,
        },
      }),
    });
  });

  await page.route("**/api/chat/cancel", async (route) => {
    cancelRequests.push(route.request().postDataJSON());
    streamFinished = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ cancelled: !options.cancelReturnsCancelling, status: options.cancelReturnsCancelling ? "cancelling" : "cancelled" }),
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
      items: progressWorkItems.map((item) => ({ ...item, at: item.at || now })),
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
            selectedTextContext: request.metadata?.selectedTextContext,
          },
        },
        {
          role: "assistant",
          text: request.fileGeneration?.enabled
            ? "已创建 Markdown 文件：[`reader-e2e.md`](/api/media/file_e2e/download)"
            : "这篇论文当前的 tags 是：\n\n- `tool-test`\n- `deepseek`\n\n论文：**DeepSeek V4**",
          runTrace,
          ...(options.omitFinalWorkTrace ? {} : { workTrace }),
          artifacts: [...fileArtifacts, ...imageArtifacts, ...extraArtifacts],
        },
      ],
      events: debugRun.events,
      artifacts: [...fileArtifacts, ...imageArtifacts, ...extraArtifacts],
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
    if (streamGate) await streamGate;
    streamFinished = true;
    try {
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
          "Cache-Control": "no-store",
        },
        body,
      });
    } catch (error) {
      if (!String(error?.message || error).includes("aborted")) throw error;
    }
  });
  return { requests, cancelRequests };
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
  const savedToolPayloads = [];
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
  await page.route("**/api/memory", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ entries: [] }),
    });
  });
  await page.route("**/api/settings/tools", async (route) => {
    if (route.request().method() === "POST") {
      savedToolPayloads.push(route.request().postDataJSON());
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        globalAccess: "default",
        defaultWriteMode: "ask",
        builtInTools: [
          {
            name: "paper_notes",
            label: "Paper Notes",
            description: "Local note tools.",
            readOnly: false,
            mutating: true,
            enabled: true,
            access: "inherit",
          },
          {
            name: "session_search",
            label: "Session Search",
            description: "Search previous chat transcripts.",
            readOnly: true,
            mutating: false,
            enabled: false,
            access: "readonly",
          },
        ],
        customTools: [
          {
            name: "web_search",
            label: "Custom Web Search",
            description: "Search the web with a configured provider.",
            readOnly: true,
            mutating: false,
            enabled: false,
            access: "readonly",
          },
          {
            name: "mcp",
            label: "MCP",
            description: "Call tools discovered from enabled MCP servers.",
            readOnly: true,
            mutating: false,
            enabled: true,
            access: "readonly",
          },
        ],
        tools: [],
        disabledTools: ["session_search", "web_search"],
        disabledToolsets: ["session_search", "web_search"],
        enabledToolsets: ["mcp"],
        webSearchProviders: {
          native_provider: {
            openaiCodex: { enabled: false },
            openaiAPIKey: { enabled: false },
            anthropic: { enabled: false },
            gemini: { enabled: false },
          },
          custom_provider: {
            Tavily: { enabled: false },
            Brave: { enabled: false },
          },
          tavilyKeyConfigured: false,
          braveSearchKeyConfigured: false,
        },
        settingsPath: ".paper-notes/tool-settings.json",
      }),
    });
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
  await expect(page.locator("#settingsMenuShield")).toBeVisible();
  const settingsLayering = await page.evaluate(() => {
    const menu = document.querySelector("#settingsMenu");
    const shield = document.querySelector("#settingsMenuShield");
    return {
      menuBackground: getComputedStyle(menu).backgroundColor,
      menuZIndex: Number(getComputedStyle(menu).zIndex),
      shieldZIndex: Number(getComputedStyle(shield).zIndex),
    };
  });
  expect(settingsLayering.menuBackground).not.toContain("rgba(0, 0, 0, 0)");
  expect(settingsLayering.menuZIndex).toBeGreaterThan(settingsLayering.shieldZIndex);

  await page.locator("#openToolSettings").click();
  await expect(page.locator("#toolSettingsDialog")).toBeVisible();
  await expect(page.locator("#toolSettingsCount")).toHaveText("1 tool");
  await expect(page.locator("#toolSettingsList")).not.toContainText("MCP");
  const sessionSearchToggle = page.locator('[data-tool-enabled="session_search"]');
  await expect(sessionSearchToggle).toBeEnabled();
  await expect(sessionSearchToggle).not.toBeChecked();
  await expect(page.locator(".tool-settings-item", { hasText: "Session Search" })).toContainText("Enabled");
  const tavilyToggle = page.locator('[data-web-search-provider-enabled="Tavily"]');
  await expect(tavilyToggle).toBeEnabled();
  await expect(tavilyToggle).not.toBeChecked();
  await expect(page.locator(".web-search-provider-row", { hasText: "Tavily" })).toContainText("Enabled");
  await expect(page.locator(".web-search-provider-row", { hasText: "Tavily" })).not.toContainText("Off");
  await sessionSearchToggle.check();
  await tavilyToggle.check();
  await page.locator("#saveToolSettings").click();
  await expect(page.locator("#toolSettingsDialog")).not.toBeVisible();
  expect(savedToolPayloads).toHaveLength(1);
  expect(savedToolPayloads[0].tools.find((tool) => tool.name === "session_search")?.enabled).toBe(true);
  expect(savedToolPayloads[0].tools.map((tool) => tool.name)).not.toContain("mcp");
  expect(savedToolPayloads[0].webSearchProviders.custom_provider.Tavily.enabled).toBe(true);

  await page.getByRole("button", { name: "Settings" }).click();
  await page.locator("#openAiSettings").click();
  await expect(page.locator("#aiSettingsDialog")).toBeVisible();
  await page.locator("#compareModelsButton").click();
  await expect(page.locator("#modelCapabilitiesDialog")).toBeVisible();
  await expect(page.locator("#modelCapabilitiesDialog")).toContainText("Model capabilities");
  await expect(page.locator(".model-capabilities-table")).toContainText("GPT-5.5");
  const capabilitiesBounds = await page.evaluate(() => {
    const panel = document.querySelector(".model-capabilities-panel");
    const tableWrap = document.querySelector("#modelCapabilitiesTableWrap");
    const panelRect = panel.getBoundingClientRect();
    const wrapRect = tableWrap.getBoundingClientRect();
    return {
      dialogOpen: document.querySelector("#modelCapabilitiesDialog")?.open === true,
      panelLeft: panelRect.left,
      panelRight: panelRect.right,
      panelBottom: panelRect.bottom,
      tableWrapRight: wrapRect.right,
      tableOverflowX: getComputedStyle(tableWrap).overflowX,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
  expect(capabilitiesBounds.dialogOpen).toBe(true);
  expect(capabilitiesBounds.panelLeft).toBeGreaterThanOrEqual(0);
  expect(capabilitiesBounds.panelRight).toBeLessThanOrEqual(capabilitiesBounds.viewportWidth);
  expect(capabilitiesBounds.panelBottom).toBeLessThanOrEqual(capabilitiesBounds.viewportHeight);
  expect(capabilitiesBounds.tableWrapRight).toBeLessThanOrEqual(capabilitiesBounds.panelRight);
  expect(capabilitiesBounds.tableOverflowX).toBe("auto");
  await page.locator("#closeModelCapabilitiesDialog").click();
  await expect(page.locator("#modelCapabilitiesDialog")).not.toBeVisible();
  await page.locator("#cancelAiSettings").click();
  await expect(page.locator("#aiSettingsDialog")).not.toBeVisible();

  await page.getByRole("button", { name: "Settings" }).click();
  await page.locator("#openMemorySettings").click();
  await expect(page.locator("#memoryDialog")).toBeVisible();
  await expect(page.locator("#cancelMemoryDialog")).toBeVisible();
  await expect(page.locator("#saveMemoryDialog")).toBeVisible();
  await page.locator("#cancelMemoryDialog").click();
  await expect(page.locator("#memoryDialog")).not.toBeVisible();

  await page.getByRole("button", { name: "Settings" }).click();
  await page.locator("#openSkillsSettings").click();
  await expect(page.locator("#skillsSettingsDialog")).toBeVisible();
  await expect(page.locator("#skillsSettingsDialog")).toContainText("External directories");
  await expect(page.locator("#skillsSettingsDialog")).toContainText("file-artifact-creator");
  await expect(page.locator("#cancelSkillsSettings")).toBeVisible();
  await expect(page.locator("#saveSkillsSettings")).toBeVisible();
  await expect(page.locator('[data-skill-name="image-artifact-creator"] .skill-list-status')).toContainText(/Ready|Off/);
  await page.locator('[data-skill-name="image-artifact-creator"]').click();
  await expect(page.locator("#skillsSettingsDetail .skill-enabled-switch")).toContainText(/Enabled|Off/);
  await expect(page.locator("#skillsSettingsDetail .skill-detail-title-row")).not.toContainText("image-artifact-creator");
  await expect(page.locator("#skillsSettingsDetail")).toContainText("Image Artifact Creator");
  await page.locator("#saveSkillsSettings").click();
  await expect(page.locator("#skillsSettingsDialog")).not.toBeVisible();

  await page.getByRole("button", { name: "Settings" }).click();
  await page.locator("#openDebugSettings").click();
  await expect(page.locator("#debugDialog")).toBeVisible();
  await expect(page.locator("#debugDialog")).toContainText("Debug");
  await expect(page.locator("#refreshDebugRuns")).toBeVisible();
  await expect(page.locator("#cleanupDebugRuns")).toBeVisible();
  await expect(page.locator("#cancelDebugDialog")).toBeVisible();
  await expect(page.locator("#saveDebugDialog")).toBeVisible();
  await page.locator("#saveDebugDialog").click();
  await expect(page.locator("#debugDialog")).not.toBeVisible();

  expect(consoleIssues).toEqual([]);
});

test("codex oauth status badge follows the signed-in auth state", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await page.route("**/api/settings/ai", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "codex-oauth",
        providerSource: "auto",
        supportedProviders: ["codex-oauth", "deepseek"],
        configured: true,
        ready: true,
        model: "gpt-5.5",
        modelConfigured: true,
        modelSource: "profile",
        modelConnectionConfigured: true,
        codexAuth: {
          loggedIn: true,
          authMode: "oauth",
          accountEmail: "",
          planType: "",
          authStorePath: ".paper-notes/auth/codex.json",
        },
      }),
    });
  });
  await page.route("**/api/model/providers", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        defaultProvider: "codex-oauth",
        defaultModel: "gpt-5.5",
        modelConnectionConfigured: true,
        providers: [
          {
            name: "codex-oauth",
            displayName: "Codex OAuth",
            configured: false,
            ready: false,
            model: "gpt-5.5",
            selectedModel: "gpt-5.5",
            defaultModel: "gpt-5.5",
            models: [{ value: "gpt-5.5", label: "GPT-5.5" }],
          },
          {
            name: "deepseek",
            displayName: "DeepSeek",
            configured: true,
            ready: true,
            model: "deepseek-v4-flash",
            selectedModel: "deepseek-v4-flash",
            defaultModel: "deepseek-v4-flash",
            models: [{ value: "deepseek-v4-flash", label: "V4 Flash" }],
          },
        ],
      }),
    });
  });

  await openFixtureLibrary(page);
  await page.getByRole("button", { name: "Settings" }).click();
  await page.locator("#openAiSettings").click();

  await expect(page.locator("#aiSettingsDialog")).toBeVisible();
  await expect(page.locator("#codexAuthDetail")).toContainText("Signed in locally.");
  await expect(page.locator("#codexStatusBadge")).toHaveText("Signed in");
});

test("MCP settings opens from URL and supports add test save remove", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await page.route("**/notes.json**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ categories: E2E_LIBRARY.categories, notes: [] }),
    });
  });
  await page.route("**/api/settings/tools", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ globalAccess: "default", builtInTools: [], tools: [] }),
    });
  });

  let currentServers = [];
  const savedPayloads = [];
  const testPayloads = [];
  const connectPayloads = [];
  const opsPayloads = [];
  const publicSettings = () => ({
    success: true,
    settingsPath: ".paper-notes/mcp-servers.json",
    servers: currentServers.map((server) => ({
      ...server,
      env: (server.env || []).map((entry) => ({ name: entry.name, configured: Boolean(entry.value || entry.configured) })),
      headers: (server.headers || []).map((entry) => ({ name: entry.name, configured: Boolean(entry.value || entry.configured) })),
      status: {
        connected: false,
        error: "Reconnect attempts paused after repeated failures.",
        toolCount: 1,
        state: "circuit_open",
        failureCount: 5,
        nextRetryAt: Math.floor(Date.now() / 1000) + 90,
        circuitOpen: true,
        securityWarnings: [{
          code: "mcp_prompt_injection_suspected",
          surface: "tool_description",
          message: "External MCP metadata contains instruction-like text.",
        }],
      },
      tools: [{
        name: "search",
        generatedName: "mcp_filesystem_search",
        readOnly: true,
        securityWarnings: [{ code: "mcp_prompt_injection_suspected", surface: "tool_description" }],
      }],
    })),
  });
  await page.route("**/api/settings/mcp**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/settings/mcp/stderr-log")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: true, log: "fixture stderr tail", truncated: false }),
      });
      return;
    }
    if (url.pathname.endsWith("/api/settings/mcp/test")) {
      testPayloads.push(route.request().postDataJSON());
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          toolCount: 1,
          tools: [{
            name: "search",
            generatedName: "mcp_filesystem_search",
            readOnly: true,
            securityWarnings: [{ code: "mcp_prompt_injection_suspected", surface: "tool_description" }],
          }],
          securityWarnings: [{
            code: "mcp_prompt_injection_suspected",
            surface: "server_metadata",
            message: "External MCP metadata contains instruction-like text.",
          }],
          error: "",
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/api/settings/mcp/connect")) {
      const payload = route.request().postDataJSON();
      connectPayloads.push(payload);
      currentServers = payload.servers || [];
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          serverId: payload.serverId,
          settingsPath: ".paper-notes/mcp-servers.json",
          servers: currentServers.map((server) => ({
            ...server,
            status: {
              connected: server.enabled !== false,
              error: "",
              toolCount: server.enabled === false ? 0 : 1,
              state: server.enabled === false ? "disconnected" : "connected",
              failureCount: 0,
              circuitOpen: false,
            },
            tools: server.enabled === false ? [] : [{
              name: "search",
              generatedName: "mcp_filesystem_search",
              readOnly: true,
            }],
          })),
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/api/settings/mcp/reconnect") || url.pathname.endsWith("/api/settings/mcp/reset-circuit")) {
      opsPayloads.push({ path: url.pathname, body: route.request().postDataJSON() });
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: true, serverId: route.request().postDataJSON().serverId }),
      });
      return;
    }
    if (route.request().method() === "POST") {
      const payload = route.request().postDataJSON();
      savedPayloads.push(payload);
      currentServers = payload.servers || [];
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(publicSettings()) });
  });

  await page.goto("/index.html?settings=mcp");
  await expect(page.locator("#mcpSettingsDialog")).toBeVisible();
  await expect(page.locator(".mcp-settings-header-actions")).toContainText("Refresh");
  await expect(page.locator(".mcp-settings-header-actions")).toContainText("Add server");
  await expect(page.locator(".mcp-settings-toolbar")).toHaveCount(0);
  await expect(page.locator("#mcpSearchInput")).toBeVisible();
  await expect(page.locator("#mcpSettingsCount")).toHaveText("0 servers");
  await expect(page.locator(".settings-menu-item .settings-theme-value")).toHaveCount(0);
  await expect(page.locator(".settings-menu-item .settings-theme-title")).toHaveText([
    "AI Provider",
    "Memory",
    "Tools",
    "MCP",
    "Skills",
    "Debug",
  ]);

  await page.locator("#addMcpServer").click();
  await expect(page.locator("#mcpSettingsCount")).toHaveText("1 server");
  await page.locator('[data-mcp-field="name"]').fill("Filesystem");
  await page.locator('[data-mcp-transport-option="http"]').click();
  await page.locator("#mcpSearchInput").fill("filesystem");
  await expect(page.locator(".mcp-server-row")).toHaveCount(1);
  await page.locator("#mcpSearchInput").fill("missing-server");
  await expect(page.locator(".mcp-server-row")).toHaveCount(0);
  await expect(page.locator("#mcpServerList")).toContainText("No matching servers");
  await page.locator("#mcpSearchInput").fill("");
  await page.locator('[data-mcp-field="url"]').fill("http://127.0.0.1:7777/mcp");
  await page.locator('[data-mcp-field="bearerTokenEnvVar"]').fill("MCP_BEARER_TOKEN");
  await expect(page.locator('[data-settings-info-hint="mcp-bearer-token-env-var"]')).toBeVisible();
  await expect(page.getByRole("tooltip").filter({ hasText: "Reads this variable from the process environment or local env files." })).toBeHidden();
  await page.locator('[data-settings-info-hint="mcp-bearer-token-env-var"]').hover();
  await expect(page.getByRole("tooltip").filter({ hasText: "Reads this variable from the process environment or local env files." })).toBeVisible();
  const headerEnvSection = page.locator(".mcp-section").filter({ hasText: "Headers from environment variables" });
  await expect(headerEnvSection.locator('[data-settings-info-hint="mcp-header-env-vars"]')).toBeVisible();
  await expect(page.getByRole("tooltip").filter({ hasText: "Only the declared variables are read from the process environment or local env files." })).toBeHidden();
  await headerEnvSection.locator('[data-settings-info-hint="mcp-header-env-vars"]').hover();
  await expect(page.getByRole("tooltip").filter({ hasText: "Only the declared variables are read from the process environment or local env files." })).toBeVisible();
  await headerEnvSection.getByRole("button", { name: "Add variable" }).click();
  await headerEnvSection.locator('[data-mcp-secret-name="headerEnvVars"]').fill("X-API-Key");
  await headerEnvSection.locator('[data-mcp-secret-value="headerEnvVars"]').fill("MCP_API_KEY");
  await page.locator('[data-mcp-field="includeTools"]').fill("search\nlist_resources");
  await page.locator('[data-mcp-field="excludeTools"]').fill("write_*");
  await page.locator('[data-mcp-test]').click();
  await expect(page.locator(".mcp-test-result")).toContainText("Discovered 1 tools");
  await expect(page.locator(".mcp-test-result")).toContainText("2 security warnings");
  await expect(page.locator(".mcp-tool-chip").filter({ hasText: "mcp_filesystem_search" })).toContainText("Warning");
  await page.locator('[data-mcp-field="enabled"]').uncheck();
  await expect(page.locator(".mcp-status-grid")).toContainText("Off");
  await expect(page.locator(".mcp-status-grid")).toContainText("0");
  await page.locator('[data-mcp-field="enabled"]').check();
  await expect(page.locator(".mcp-status-grid")).toContainText("Connected");
  await expect(page.locator(".mcp-status-grid")).toContainText("1");
  expect(connectPayloads).toHaveLength(2);
  await page.locator("#saveMcpSettings").click();
  await expect(page.locator("#mcpSettingsDialog")).not.toBeVisible();

  expect(testPayloads[0]).toMatchObject({
    name: "Filesystem",
    transport: "http",
    enabled: true,
    url: "http://127.0.0.1:7777/mcp",
    bearerTokenEnvVar: "MCP_BEARER_TOKEN",
    headerEnvVars: [{ name: "X-API-Key", value: "MCP_API_KEY" }],
    includeTools: ["search", "list_resources"],
    excludeTools: ["write_*"],
  });
  expect(connectPayloads[0]).toMatchObject({
    persist: false,
    servers: [{ enabled: false }],
  });
  expect(connectPayloads[1]).toMatchObject({
    persist: false,
  });
  expect(connectPayloads[1].servers[0]).toMatchObject({
    name: "Filesystem",
    transport: "http",
    enabled: true,
    url: "http://127.0.0.1:7777/mcp",
    bearerTokenEnvVar: "MCP_BEARER_TOKEN",
    headerEnvVars: [{ name: "X-API-Key", value: "MCP_API_KEY" }],
    includeTools: ["search", "list_resources"],
    excludeTools: ["write_*"],
  });
  expect(connectPayloads[1].servers[0].status).toBeUndefined();
  expect(connectPayloads[1].servers[0].tools).toBeUndefined();
  expect(savedPayloads[0].servers[0]).toMatchObject({
    name: "Filesystem",
    transport: "http",
    enabled: true,
    url: "http://127.0.0.1:7777/mcp",
    bearerTokenEnvVar: "MCP_BEARER_TOKEN",
    headerEnvVars: [{ name: "X-API-Key", value: "MCP_API_KEY" }],
    includeTools: ["search", "list_resources"],
    excludeTools: ["write_*"],
  });
  expect(savedPayloads[0].servers[0].status).toBeUndefined();
  expect(savedPayloads[0].servers[0].tools).toBeUndefined();

  await page.goto("/index.html?settings=mcp");
  await expect(page.locator("#mcpSettingsDialog")).toBeVisible();
  await expect(page.locator("#mcpServerList")).toContainText("Filesystem");
  await expect(page.locator("#mcpServerList")).toContainText("Circuit open");
  await expect(page.locator("#mcpServerList")).toContainText("5 failures");
  await expect(page.locator("#mcpServerEditor")).toContainText("Status");
  await expect(page.locator("#mcpServerEditor")).toContainText("Next retry");
  await expect(page.locator("#mcpServerEditor")).toContainText("2 security warnings");
  await expect(page.locator(".mcp-status-note.is-error")).toContainText("Reconnect attempts paused");
  await expect(page.locator('[data-mcp-reconnect]')).toBeVisible();
  await expect(page.locator('[data-mcp-reset-circuit]')).toBeVisible();
  await expect(page.locator('[data-mcp-view-log]')).toBeVisible();
  await page.locator('[data-mcp-view-log]').click();
  await expect(page.locator(".mcp-log-panel")).toContainText("fixture stderr tail");
  await page.locator('[data-mcp-reset-circuit]').click();
  await expect.poll(() => opsPayloads.length).toBeGreaterThan(0);
  expect(opsPayloads.at(-1)).toMatchObject({
    path: "/api/settings/mcp/reset-circuit",
    body: { serverId: expect.any(String) },
  });
  await expect(page.locator('[data-mcp-field="includeTools"]')).toHaveValue("search\nlist_resources");
  await expect(page.locator('[data-mcp-field="excludeTools"]')).toHaveValue("write_*");
  await expect(page.locator('[data-mcp-field="bearerTokenEnvVar"]')).toHaveValue("MCP_BEARER_TOKEN");
  const restoredHeaderEnvSection = page.locator(".mcp-section").filter({ hasText: "Headers from environment variables" });
  await expect(restoredHeaderEnvSection.locator('[data-mcp-secret-name="headerEnvVars"]')).toHaveValue("X-API-Key");
  await expect(restoredHeaderEnvSection.locator('[data-mcp-secret-value="headerEnvVars"]')).toHaveValue("MCP_API_KEY");
  await page.locator('[data-mcp-delete]').click();
  await expect(page.locator("#confirmDialog")).toContainText("Delete Filesystem?");
  await page.locator("#confirmDialogAction").click();
  await page.locator("#saveMcpSettings").click();

  expect(savedPayloads.at(-1)).toEqual({ servers: [] });
});

test("MCP settings renders each operation error under its button", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await page.route("**/notes.json**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ categories: E2E_LIBRARY.categories, notes: [] }),
    });
  });
  await page.route("**/api/settings/tools", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ globalAccess: "default", builtInTools: [], tools: [] }),
    });
  });
  await page.route("**/api/settings/mcp**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/settings/mcp/stderr-log")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: false, error: "Method not allowed" }),
      });
      return;
    }
    if (url.pathname.endsWith("/api/settings/mcp/test")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: false, error: "Connection refused", toolCount: 0, tools: [] }),
      });
      return;
    }
    if (url.pathname.endsWith("/api/settings/mcp/connect")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: false, error: "Connect denied" }),
      });
      return;
    }
    if (url.pathname.endsWith("/api/settings/mcp/reconnect")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: false, error: "Reconnect denied" }),
      });
      return;
    }
    if (url.pathname.endsWith("/api/settings/mcp/reset-circuit")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ success: false, error: "Reset denied" }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        settingsPath: ".paper-notes/mcp-servers.json",
        servers: [{
          id: "mcp_failure_fixture",
          name: "Failure fixture",
          enabled: true,
          transport: "http",
          url: "http://127.0.0.1:7777/mcp",
          status: {
            connected: false,
            error: "Server status failure",
            toolCount: 0,
            state: "error",
            failureCount: 1,
          },
          tools: [],
        }],
      }),
    });
  });

  await page.goto("/index.html?settings=mcp");
  await expect(page.locator("#mcpSettingsDialog")).toBeVisible();
  await expect(page.locator(".mcp-status-note.is-error")).toContainText("Server status failure");
  await page.locator('[data-mcp-reconnect]').click();
  await expect(page.locator('[data-mcp-action-error="reconnect"]')).toContainText("Reconnect failed");
  await expect(page.locator('[data-mcp-action-error="reconnect"]')).toContainText("Connect denied");
  await page.locator('[data-mcp-reset-circuit]').click();
  await expect(page.locator('[data-mcp-action-error="reset"]')).toContainText("Reset failed");
  await expect(page.locator('[data-mcp-action-error="reset"]')).toContainText("Reset denied");
  await page.locator('[data-mcp-test]').click();
  await expect(page.locator('[data-mcp-action-error="test"]')).toContainText("Connection failed");
  await expect(page.locator('[data-mcp-action-error="test"]')).toContainText("Connection refused");
  await page.locator('[data-mcp-connect]').click();
  await expect(page.locator('[data-mcp-action-error="connect"]')).toContainText("Connect failed");
  await expect(page.locator('[data-mcp-action-error="connect"]')).toContainText("Connect denied");
  await expect(page.locator(".mcp-status-grid")).toContainText("Error");
  await expect(page.locator(".mcp-status-note.is-error")).toHaveCount(0);
  await expect(page.locator(".mcp-server-row.is-active")).toContainText("Error");
  await expect(page.locator(".mcp-server-row.is-active")).toContainText("Connect denied");
  await expect(page.locator(".mcp-test-result.is-error")).toHaveCount(0);
  await page.locator('[data-mcp-view-log]').click();
  await expect(page.locator('[data-mcp-action-error="log"]')).toContainText("Log unavailable");
  await expect(page.locator('[data-mcp-action-error="log"]')).toContainText("Method not allowed");
  await expect(page.locator(".mcp-log-panel")).toHaveCount(0);
  const layout = await page.evaluate(() => {
    const rect = (element) => {
      const box = element.getBoundingClientRect();
      return { top: box.top, bottom: box.bottom, width: box.width };
    };
    const statusActions = document.querySelector(".mcp-status-actions");
    const editorActions = document.querySelector(".mcp-editor-actions");
    const buttonFor = (selector) => rect(document.querySelector(selector));
    const errorFor = (action) => rect(document.querySelector(`[data-mcp-action-error="${action}"]`));
    return {
      statusActions: rect(statusActions),
      editorActions: rect(editorActions),
      reconnectButton: buttonFor("[data-mcp-reconnect]"),
      resetButton: buttonFor("[data-mcp-reset-circuit]"),
      logButton: buttonFor("[data-mcp-view-log]"),
      testButton: buttonFor("[data-mcp-test]"),
      connectButton: buttonFor("[data-mcp-connect]"),
      reconnectError: errorFor("reconnect"),
      resetError: errorFor("reset"),
      logError: errorFor("log"),
      testError: errorFor("test"),
      connectError: errorFor("connect"),
    };
  });
  expect(layout.reconnectError.top).toBeGreaterThanOrEqual(layout.statusActions.bottom);
  expect(layout.resetError.top).toBeGreaterThanOrEqual(layout.statusActions.bottom);
  expect(layout.logError.top).toBeGreaterThanOrEqual(layout.statusActions.bottom);
  expect(layout.testError.top).toBeGreaterThanOrEqual(layout.editorActions.bottom);
  expect(layout.connectError.top).toBeGreaterThanOrEqual(layout.editorActions.bottom);
  expect(layout.reconnectError.width).toBeGreaterThan(layout.reconnectButton.width * 2);
  expect(layout.resetError.width).toBeGreaterThan(layout.resetButton.width * 2);
  expect(layout.logError.width).toBeGreaterThan(layout.logButton.width * 2);
  expect(layout.testError.width).toBeGreaterThan(layout.testButton.width * 2);
  expect(layout.connectError.width).toBeGreaterThan(layout.connectButton.width * 2);
});

test("MCP settings cancel restores preview runtime registration", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await page.route("**/notes.json**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ categories: E2E_LIBRARY.categories, notes: [] }),
    });
  });
  await page.route("**/api/settings/tools", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ globalAccess: "default", builtInTools: [], tools: [] }),
    });
  });

  const persistedServers = [{
    id: "mcp_cancel_fixture",
    name: "Cancel fixture",
    enabled: false,
    transport: "http",
    url: "http://127.0.0.1:8888/mcp",
    timeoutSeconds: 120,
    connectTimeoutSeconds: 10,
    status: { connected: false, error: "", toolCount: 0, state: "disconnected" },
    tools: [],
  }];
  const connectPayloads = [];
  let firstConnectStarted = false;
  let releaseFirstConnect = null;
  await page.route("**/api/settings/mcp**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/api/settings/mcp/connect")) {
      const payload = route.request().postDataJSON();
      connectPayloads.push(payload);
      if (payload.servers?.[0]?.enabled !== false && !firstConnectStarted) {
        firstConnectStarted = true;
        await new Promise((resolve) => {
          releaseFirstConnect = resolve;
        });
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          serverId: payload.serverId,
          settingsPath: ".paper-notes/mcp-servers.json",
          servers: (payload.servers || []).map((server) => ({
            ...server,
            status: {
              connected: server.enabled !== false,
              error: "",
              toolCount: server.enabled === false ? 0 : 1,
              state: server.enabled === false ? "disconnected" : "connected",
            },
            tools: server.enabled === false ? [] : [{
              name: "search",
              generatedName: "mcp_cancel_fixture_search",
              readOnly: true,
            }],
          })),
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        settingsPath: ".paper-notes/mcp-servers.json",
        servers: persistedServers,
      }),
    });
  });

  await page.goto("/index.html?settings=mcp");
  await expect(page.locator("#mcpSettingsDialog")).toBeVisible();
  await expect(page.locator(".mcp-status-grid")).toContainText("Off");
  await page.locator('[data-mcp-connect]').click();
  await expect.poll(() => connectPayloads.length).toBe(1);
  expect(connectPayloads[0]).toMatchObject({
    persist: false,
    servers: [{ id: "mcp_cancel_fixture", enabled: false }],
  });
  await expect(page.locator(".mcp-status-grid")).toContainText("Off");
  const enablePromise = page.locator('[data-mcp-field="enabled"]').check();
  await expect.poll(() => firstConnectStarted).toBe(true);
  await expect(page.locator(".mcp-status-grid")).toContainText("Connecting");
  releaseFirstConnect?.();
  await enablePromise;
  await expect(page.locator(".mcp-status-grid")).toContainText("Connected");
  await expect(page.locator(".mcp-status-grid")).toContainText("1");
  await page.locator("#cancelMcpSettings").click();
  await expect(page.locator("#mcpSettingsDialog")).not.toBeVisible();
  await expect.poll(() => connectPayloads.length).toBe(3);
  expect(connectPayloads[1]).toMatchObject({
    persist: false,
    servers: [{ id: "mcp_cancel_fixture", enabled: true }],
  });
  expect(connectPayloads[2]).toMatchObject({
    persist: false,
    servers: [{ id: "mcp_cancel_fixture", enabled: false }],
  });
});

test("library tag add and remove flows persist through the details panel", async ({ page }) => {
  const syncPayloads = [];
  const library = JSON.parse(JSON.stringify(E2E_LIBRARY));
  library.categories.push({ id: "agent", name: "Agent", parentId: null, order: 3, system: false });
  library.notes.push({
    ...library.notes[0],
    id: "pdf-same-tag-e2e",
    title: "Same Tag Paper",
    date: "2026-05-12",
    order: 1,
    categoryId: "agent",
    tags: ["tool-test", "agent"],
  }, {
    ...library.notes[0],
    id: "pdf-other-tag-e2e",
    title: "Other Tag Paper",
    date: "2026-05-11",
    order: 2,
    tags: ["other"],
  });
  await openFixtureLibrary(page, {
    library,
    onLibrarySync: (payload) => {
      syncPayloads.push(payload);
    },
  });

  await expect(page.locator(".details-tags")).toContainText("tool-test");
  await expect(page.locator(".details-tags")).toContainText("deepseek");
  await page.getByRole("button", { name: "Show papers tagged tool-test" }).click();
  await expect(page.locator("#contentTitle")).toHaveText("All Notes");
  await expect(page.locator("#libraryStatus")).toContainText("2 notes in All Notes");
  await expect(page.locator(".library-status-tag")).toContainText(["#tool-test"]);
  await expect(page.locator(".note-card h3")).toContainText(["DeepSeek V4", "Same Tag Paper"]);
  await expect(page.locator("#notesGrid")).not.toContainText("Other Tag Paper");
  await expect(page.locator("[data-category-id='all'] .category-count")).toHaveText("2");
  await expect(page.locator("[data-category-id='agent'] .category-count")).toHaveText("1");
  await expect(page.locator("[data-category-id='deepseek'] .category-count")).toHaveText("1");
  await page.getByRole("button", { name: "Show papers tagged deepseek" }).click();
  await expect(page.locator("#libraryStatus")).toContainText("1 notes in All Notes");
  await expect(page.locator(".library-status-tag")).toContainText(["#tool-test", "#deepseek"]);
  await page.getByRole("button", { name: "Remove tag filter deepseek" }).click();
  await expect(page.locator("#libraryStatus")).toContainText("2 notes in All Notes");
  await expect(page.locator(".library-status-tag")).toContainText(["#tool-test"]);
  await page.locator("[data-category-id='deepseek']").click();
  await expect(page.locator("#contentTitle")).toHaveText("DeepSeek");
  await expect(page.locator("#libraryStatus")).toContainText("1 notes in DeepSeek");
  await expect(page.locator(".library-status-tag")).toContainText(["#tool-test"]);
  await expect(page.locator(".note-card h3")).toContainText(["DeepSeek V4"]);
  await expect(page.locator("#notesGrid")).not.toContainText("Same Tag Paper");
  await expect(page.locator("#notesGrid")).not.toContainText("Other Tag Paper");
  await page.getByRole("button", { name: "Remove tag filter tool-test" }).click();
  await expect(page.locator("#contentTitle")).toHaveText("DeepSeek");
  await expect(page.locator("#libraryStatus")).toContainText("2 notes in DeepSeek");
  await expect(page.locator(".library-status-tag")).toHaveCount(0);
  await page.locator("#searchInput").fill("Same");
  await expect(page.locator("[data-category-id='all'] .category-count")).toHaveText("1");
  await expect(page.locator("[data-category-id='agent'] .category-count")).toHaveText("1");
  await expect(page.locator("[data-category-id='deepseek'] .category-count")).toHaveText("0");
  await page.locator("#searchInput").fill("");

  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.locator("#tagDialog")).toBeVisible();
  await expect(page.locator(".tag-suggestion")).toContainText(["agent", "other"]);
  await page.locator("#tagInput").fill("ag");
  await expect(page.locator(".tag-suggestion")).toContainText(["agent"]);
  await page.locator(".tag-suggestion", { hasText: "agent" }).click();
  await expect(page.locator("#tagInput")).toHaveValue("agent");
  await page.locator("#tagInput").fill("regression");
  await page.locator("#tagForm").getByRole("button", { name: "Add" }).click();

  await expect(page.locator("#tagDialog")).not.toBeVisible();
  await expect(page.locator(".details-tags")).toContainText("regression");
  await expect(page.getByRole("button", { name: "Remove regression tag" })).toBeVisible();
  expect(syncPayloads.at(-1)?.notes?.find((note) => note.id === E2E_NOTE_ID)?.tags).toEqual([
    "tool-test",
    "deepseek",
    "regression",
  ]);

  await page.locator(".details-tag", { hasText: "regression" }).hover();
  await page.getByRole("button", { name: "Remove regression tag" }).click();
  await expect(page.locator("#confirmDialog")).toBeVisible();
  await expect(page.locator("#confirmDialog")).toContainText("Remove #regression?");
  await page.locator("#confirmDialogAction").click();
  await expect(page.locator(".details-tags")).not.toContainText("regression");
  expect(syncPayloads.at(-1)?.notes?.find((note) => note.id === E2E_NOTE_ID)?.tags).toEqual([
    "tool-test",
    "deepseek",
  ]);
});

test("library collections can be dragged into and out of parent collections", async ({ page }) => {
  const syncPayloads = [];
  const library = JSON.parse(JSON.stringify(E2E_LIBRARY));
  library.categories.push(
    { id: "llm", name: "LLM", parentId: null, order: 3, system: false },
    { id: "agent", name: "Agent", parentId: null, order: 4, system: false },
  );
  await openFixtureLibrary(page, {
    library,
    onLibrarySync: (payload) => syncPayloads.push(payload),
  });

  async function dragCategory(sourceId, targetId, yRatio = 0.5) {
    await page.evaluate(({ sourceId, targetId, yRatio }) => {
      const source = document.querySelector(`[data-tree-node-id="${sourceId}"]`);
      const target = document.querySelector(`[data-tree-node-id="${targetId}"] .tree-row`);
      if (!source || !target) throw new Error("Missing category drag target");
      const rect = target.getBoundingClientRect();
      const dataTransfer = new DataTransfer();
      const eventInit = {
        bubbles: true,
        cancelable: true,
        dataTransfer,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height * yRatio,
      };
      source.dispatchEvent(new DragEvent("dragstart", eventInit));
      target.dispatchEvent(new DragEvent("dragover", eventInit));
      const freshTarget = document.querySelector(`[data-tree-node-id="${targetId}"] .tree-row`);
      (freshTarget || target).dispatchEvent(new DragEvent("drop", eventInit));
      source.dispatchEvent(new DragEvent("dragend", eventInit));
    }, { sourceId, targetId, yRatio });
  }

  await dragCategory("deepseek", "llm", 0.5);
  await expect(page.locator(".tree-level-1 [data-category-id='deepseek']")).toBeVisible();
  expect(syncPayloads.at(-1)?.categories?.find((category) => category.id === "deepseek")?.parentId).toBe("llm");

  await dragCategory("deepseek", "all", 0.5);
  await expect(page.locator(".tree-level-0 [data-category-id='deepseek']")).toBeVisible();
  expect(syncPayloads.at(-1)?.categories?.find((category) => category.id === "deepseek")?.parentId).toBeNull();
});

test("library paper cards can be dragged into collections", async ({ page }) => {
  const syncPayloads = [];
  const library = JSON.parse(JSON.stringify(E2E_LIBRARY));
  library.categories.push(
    { id: "agent", name: "Agent", parentId: null, order: 3, system: false },
    { id: "llm", name: "LLM", parentId: null, order: 4, system: false },
    { id: "llm-child", name: "Reasoning", parentId: "llm", order: 0, system: false },
  );
  await openFixtureLibrary(page, {
    library,
    onLibrarySync: (payload) => syncPayloads.push(payload),
  });

  async function dragPaperToCategory(noteId, categoryId) {
    await page.evaluate(({ noteId, categoryId }) => {
      const source = document.querySelector(`[data-note-id="${noteId}"]`);
      const target = document.querySelector(`[data-tree-node-id="${categoryId}"] .tree-row`);
      if (!source || !target) throw new Error("Missing paper drag target");
      const rect = target.getBoundingClientRect();
      const dataTransfer = new DataTransfer();
      const eventInit = {
        bubbles: true,
        cancelable: true,
        dataTransfer,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
      };
      source.dispatchEvent(new DragEvent("dragstart", eventInit));
      target.dispatchEvent(new DragEvent("dragover", eventInit));
      target.dispatchEvent(new DragEvent("drop", eventInit));
      source.dispatchEvent(new DragEvent("dragend", eventInit));
    }, { noteId, categoryId });
  }

  await dragPaperToCategory(E2E_NOTE_ID, "agent");
  expect(syncPayloads.at(-1)?.notes?.find((note) => note.id === E2E_NOTE_ID)?.categoryId).toBe("agent");

  await dragPaperToCategory(E2E_NOTE_ID, "llm");
  expect(syncPayloads.at(-1)?.notes?.find((note) => note.id === E2E_NOTE_ID)?.categoryId).toBe("llm-child");
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
  await expect(page.locator("#debugDialog")).toBeVisible();
  await expect(page.locator("#debugDialog")).toContainText(DEBUG_REQUEST_ID);
  await expect(page.locator("#debugDialog")).toContainText("model_request");

  expect(consoleIssues).toEqual([]);
});

test("reader ask user message copy icon falls back when Clipboard API rejects", async ({ page }) => {
  await openFixtureReader(page);
  await installAgentMocks(page);
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.evaluate(() => {
    window.__readerCopyFallbackText = "";
    const originalExecCommand = document.execCommand.bind(document);
    document.execCommand = (command) => {
      if (command === "copy") {
        window.__readerCopyFallbackText = document.activeElement?.value || "";
        return true;
      }
      return originalExecCommand(command);
    };
    const failingClipboard = {
      writeText: () => Promise.reject(new Error("clipboard unavailable")),
    };
    try {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: failingClipboard,
      });
    } catch (_error) {
      Object.defineProperty(Navigator.prototype, "clipboard", {
        configurable: true,
        get: () => failingClipboard,
      });
    }
  });

  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  const prompt = "复制这条用户消息";
  await askInput.fill(prompt);
  await page.getByRole("button", { name: "Send" }).click();

  const copyButton = page.locator("[data-user-message-copy]");
  await expect(copyButton).toHaveCount(1);
  await page.evaluate(() => setReaderChatError("Could not copy message."));
  await copyButton.click();

  await expect(copyButton).toHaveAttribute("aria-label", "Copied");
  await expect(page.locator("#readerChatError")).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.__readerCopyFallbackText)).toBe(prompt);
  expect(pageErrors).toEqual([]);
});

test("reader debug run list hides status-duplicate cancelled preview", async ({ page }) => {
  await openFixtureReader(page);
  const cancelledRun = {
    requestId: DEBUG_REQUEST_ID,
    status: "cancelled",
    provider: "codex-oauth",
    model: "gpt-5.3-codex-spark",
    transport: "json",
    sessionId: "cancelled-session",
    noteId: E2E_NOTE_ID,
    startedAt: "2026-05-17T15:29:57.000Z",
    finishedAt: "2026-05-17T15:32:16.000Z",
    durationMs: 139000,
    errorPreview: "cancelled",
    metadata: { requestOptions: { reasoning: { effort: "xhigh" } } },
    events: [],
  };
  await page.route("**/api/debug/runs?limit=50", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ runs: [cancelledRun] }) });
  });
  await page.route(`**/api/debug/runs/${DEBUG_REQUEST_ID}`, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ run: cancelledRun }) });
  });

  await page.evaluate((requestId) => openDebugDialog(requestId), DEBUG_REQUEST_ID);

  const runRow = page.locator(".debug-run-row");
  await expect(runRow).toHaveCount(1);
  await expect(runRow.locator("strong")).toContainText("cancelled");
  await expect(runRow.locator("span")).toContainText("codex-oauth / gpt-5.3-codex-spark");
  await expect(runRow.locator("span")).toContainText("Think XHigh");
  await expect(runRow.locator("span")).toContainText("2m 19s");
  await expect(runRow.locator("span")).not.toContainText("json");
  await expect(runRow.locator("small")).toHaveCount(0);

  const debugDetail = page.locator(".debug-run-detail");
  const detailValues = await debugDetail.locator(".debug-kv").evaluate((list) => {
    const values = {};
    Array.from(list.querySelectorAll("dt")).forEach((label) => {
      values[label.textContent.trim()] = label.nextElementSibling?.textContent?.trim() || "";
    });
    return values;
  });
  expect(detailValues.Model).toBe("codex-oauth / gpt-5.3-codex-spark · Think XHigh");
  expect(detailValues.Status).toBe("cancelled");
  expect(detailValues.Duration).toBe("2m 19s");
  expect(detailValues.Transport).toBeUndefined();
});

test("reader ask shows running progress as inline messages", async ({ page }) => {
  await openFixtureReader(page);
  let releaseStream;
  const streamGate = new Promise((resolve) => {
    releaseStream = resolve;
  });
  await installAgentMocks(page, {
    streamGate,
    workTraceItems: [
      { type: "reasoning", text: "Thinking through the paper context...", at: "2026-05-13T10:00:00.000Z" },
      { type: "tool", text: "Reading note context...", at: "2026-05-13T10:00:01.000Z" },
      { type: "status", text: "Preparing answer...", at: "2026-05-13T10:00:02.000Z" },
    ],
    progressVisibleEvents: [
      { stage: "thinking", detail: "Thinking through the paper context...", at: "2026-05-13T10:00:00.000Z" },
      { stage: "thinking", detail: "Thinking through the paper context and reading", at: "2026-05-13T10:00:00.500Z" },
      { stage: "tool", detail: "Reading note context...", at: "2026-05-13T10:00:01.000Z" },
      { stage: "status", detail: "Preparing answer...", at: "2026-05-13T10:00:02.000Z" },
    ],
  });

  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  await askInput.fill("查一下这篇论文的 tags");
  const sendButton = page.locator("#sendReaderChat");
  await sendButton.click();

  const askPane = page.locator("#askPane");
  await expect(sendButton).toHaveAttribute("aria-label", "Cancel");
  await expect(sendButton).toHaveText("");
  await expect(sendButton.locator("svg")).toHaveCount(1);
  await expect.poll(async () => page.evaluate(() => ({
    startingType: progressInlineType("starting"),
    startingLabel: workTraceItemLabel("starting"),
    pendingType: progressInlineType("pending"),
    haltedLabel: workTraceItemLabel("halted"),
    thinkingType: progressInlineType("thinking"),
    thinkingLabel: workTraceItemLabel("thinking"),
  }))).toEqual({
    startingType: "status",
    startingLabel: "Status",
    pendingType: "status",
    haltedLabel: "Status",
    thinkingType: "status",
    thinkingLabel: "Status",
  });
  await expect(askPane.locator(".ask-progress-card")).toHaveCount(0);
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Think" }).filter({ hasText: "Thinking through the paper context..." })).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Tool" }).filter({ hasText: "Reading note context..." })).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Status" }).filter({ hasText: "Preparing answer..." })).toBeVisible();
  const activeToolProgress = askPane.locator(".ask-progress-inline.is-active .ask-progress-inline-text").filter({ hasText: "Reading note context..." });
  const originalTheme = await page.evaluate(() => document.documentElement.dataset.theme || "");
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
  });
  await expect(activeToolProgress).toHaveCSS("color", "rgb(36, 33, 29)");
  await expect.poll(() => activeToolProgress.evaluate((node) => getComputedStyle(node.parentElement).getPropertyValue("--ask-progress-sheen-color").trim())).toBe("#ffffff");
  const activeToolChars = activeToolProgress.locator(".ask-progress-inline-char");
  await expect(activeToolChars).toHaveCount(Array.from("Reading note context...").length);
  await expect(activeToolChars.first()).toHaveCSS("animation-duration", "3.2s");
  await expect.poll(async () => {
    const firstDelay = await activeToolChars.first().evaluate((node) => Number.parseFloat(getComputedStyle(node).animationDelay));
    const lastDelay = await activeToolChars.last().evaluate((node) => Number.parseFloat(getComputedStyle(node).animationDelay));
    return firstDelay < 0 && lastDelay < 0 && Math.abs(lastDelay - firstDelay) > 0.5;
  }).toBe(true);
  const freshToolDelays = await page.evaluate(() => {
    const html = renderProgressInlineReadingText("Using a new tool call", new Date().toISOString());
    const shell = document.createElement("span");
    shell.innerHTML = html;
    return [...shell.querySelectorAll(".ask-progress-inline-char")].map((node) => node.style.getPropertyValue("--progress-char-delay"));
  });
  expect(Number.parseFloat(freshToolDelays[0])).toBeGreaterThan(-0.25);
  expect(Number.parseFloat(freshToolDelays.at(-1))).toBeLessThan(Number.parseFloat(freshToolDelays[0]));
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "dark";
  });
  await expect(activeToolProgress).toHaveCSS("color", "rgb(241, 242, 245)");
  await expect.poll(() => activeToolProgress.evaluate((node) => getComputedStyle(node.parentElement).getPropertyValue("--ask-progress-sheen-color").trim())).toBe("#000000");
  await page.evaluate((theme) => {
    if (theme) {
      document.documentElement.dataset.theme = theme;
    } else {
      delete document.documentElement.dataset.theme;
    }
  }, originalTheme);
  await expect.poll(async () => askPane.locator(".ask-message-progress-inline .ask-progress-inline-text").evaluateAll((nodes) => (
    nodes.map((node) => node.textContent?.trim()).filter(Boolean)
  ))).toEqual([
    "Thinking through the paper context...",
    "Reading note context...",
    "Preparing answer...",
  ]);
  await page.evaluate(() => {
    const runKey = chatSessionRunKey();
    appendReaderChatProgressWorkTrace({
      traceType: "status",
      source: "runtime",
      text: "Preparing answer with citations...",
    }, runKey, "work_trace_item");
    appendReaderChatProgressWorkTrace({
      traceType: "tool",
      source: "runtime",
      text: "Reading note context with HTML...",
    }, runKey, "work_trace_item");
    appendReaderChatProgressWorkTrace({
      traceType: "skill",
      source: "runtime",
      text: "Loading skill instructions...",
    }, runKey, "work_trace_item");
    appendReaderChatProgressWorkTrace({
      traceType: "skill",
      source: "runtime",
      text: "Loading skill instructions from disk...",
    }, runKey, "work_trace_item");
    renderReaderChatMessages({ scrollToBottom: true });
  });
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Status" }).filter({ hasText: "Preparing answer..." })).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Status" }).filter({ hasText: "Preparing answer with citations..." })).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Tool" }).filter({ hasText: "Reading note context..." })).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Tool" }).filter({ hasText: "Reading note context with HTML..." })).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Skill" }).filter({ hasText: "Loading skill instructions..." })).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").filter({ hasText: "Skill" }).filter({ hasText: "Loading skill instructions from disk..." })).toBeVisible();
  await page.evaluate(() => {
    appendReaderStreamingDelta("Streaming answer after tools.");
    renderReaderChatMessages({ scrollToBottom: true });
  });
  await expect.poll(async () => askPane.locator(".ask-message, .ask-message-progress-inline").evaluateAll((nodes) => (
    nodes
      .map((node) => node.textContent?.replace(/\s+/g, " ").trim())
      .filter((text) => text && (
        text.includes("Preparing answer...")
        || text.includes("Streaming answer after tools.")
      ))
  ))).toEqual([
    "Status Preparing answer...",
    "Streaming answer after tools.",
  ]);

  releaseStream();
  await expect(sendButton).toHaveAttribute("aria-label", "Send");
  await expect(sendButton).toHaveText("");
  await expect(sendButton.locator("svg")).toHaveCount(1);
  await expect(askPane.locator(".ask-message-progress-inline")).toHaveCount(0);
  await expect(askPane.getByText("Worked for")).toBeVisible();
  await askPane.getByText("Worked for").click();
  await expect(askPane.locator(".ask-run-summary-events").getByText("Starting agent run.")).toBeVisible();
  await expect(askPane.getByText("Reading note context...")).toBeVisible();
});

test("reader ask send button cancels a pending request", async ({ page }) => {
  await openFixtureReader(page);
  let releaseStream;
  const streamGate = new Promise((resolve) => {
    releaseStream = resolve;
  });
  const agentMocks = await installAgentMocks(page, {
    streamGate,
    cancelReturnsCancelling: true,
    workTraceItems: [
      { type: "reasoning", text: "Thinking through the paper context...", at: "2026-05-13T10:00:00.000Z" },
      { type: "tool", text: "Reading note context...", at: "2026-05-13T10:00:01.000Z" },
    ],
  });

  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  await askInput.fill("cancel this run");
  const sendButton = page.locator("#sendReaderChat");
  await sendButton.click();
  await expect(sendButton).toHaveAttribute("aria-label", "Cancel");
  await expect(sendButton).toHaveText("");
  await expect(sendButton.locator("svg")).toHaveCount(1);
  await expect(askInput).toBeEnabled();
  const toolButton = page.locator("#readerToolMenuButton");
  await expect(toolButton).toBeEnabled();

  await askInput.fill("/");
  await expect(page.locator("#readerSlashCommandMenu")).toBeVisible();
  await expect(page.locator("[data-slash-command='new']")).toBeEnabled();
  await expect(page.locator("[data-slash-command='compact']")).toBeDisabled();
  await expect(page.locator("[data-slash-command='compact']")).toContainText("Wait for current answer to finish");

  await askInput.fill("draft next question");
  await askInput.press("Enter");
  await expect.poll(() => agentMocks.cancelRequests.length).toBe(0);
  await expect(sendButton).toHaveAttribute("aria-label", "Cancel");
  await expect(askInput).toHaveValue("draft next question");
  await toolButton.click();
  await expect(page.locator("#readerToolPopover")).toBeVisible();
  await toolButton.click();

  await sendButton.click();
  await expect.poll(() => agentMocks.cancelRequests.length).toBe(1);
  releaseStream();
  await expect(sendButton).toHaveAttribute("aria-label", "Send");
  await expect(sendButton).toHaveText("");
  await expect(sendButton.locator("svg")).toHaveCount(1);
  const askPane = page.locator("#askPane");
  await expect(askPane.locator(".ask-progress-card")).toHaveCount(0);
  await expect(askPane.locator(".ask-message-progress-inline")).toHaveCount(0);
  await expect(askPane.locator(".ask-bubble").filter({ hasText: /^Agent run cancelled\.$/ })).toBeVisible();
  await expect(askPane.getByText("Worked for")).toBeVisible();
  await askPane.getByText("Worked for").click();
  await expect(askPane.getByText("Thinking through the paper context...")).toBeVisible();
  const summaryEvents = askPane.locator(".ask-run-summary-events");
  await expect(summaryEvents.getByText("Reading note context...").first()).toBeVisible();
  await expect(summaryEvents.getByText("Agent run cancelled.", { exact: true })).toBeVisible();
});

test("reader ask worked summary shows status-only run trace events", async ({ page }) => {
  await openFixtureReader(page);
  await installAgentMocks(page, {
    omitFinalWorkTrace: true,
    runTraceEvents: [
      { type: "starting", stage: "starting", message: "Starting agent run.", at: "2026-05-13T10:00:00.000Z", data: {} },
      { type: "running", stage: "running", message: "Reading local context.", at: "2026-05-13T10:00:01.000Z", data: {} },
      { type: "completed", stage: "completed", message: "Agent run completed.", at: "2026-05-13T10:00:06.000Z", data: {} },
    ],
  });

  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  await askInput.fill("status only run");
  await page.locator("#sendReaderChat").click();

  const askPane = page.locator("#askPane");
  await expect(askPane.getByText("Worked for")).toBeVisible();
  await askPane.getByText("Worked for").click();
  await expect(askPane.getByText("No visible work steps recorded.")).toHaveCount(0);
  await expect(askPane.locator(".ask-run-summary-events").getByText("Starting agent run.")).toBeVisible();
  await expect(askPane.locator(".ask-run-summary-events").getByText("Reading local context.")).toBeVisible();
});

test("reader ask worked summary stays expanded during progress rerenders", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Ask" });
  if (await askToggle.isVisible()) await askToggle.click();
  await page.evaluate(() => {
    readerState.chatMessages = [
      {
        role: "assistant",
        text: "Previous answer.",
        runTrace: {
          requestId: "reader-chat-previous-run",
          startedAt: "2026-05-13T10:00:00.000Z",
          finishedAt: "2026-05-13T10:00:06.000Z",
          durationMs: 6000,
          status: "completed",
          events: [
            { type: "starting", stage: "starting", message: "Starting agent run.", at: "2026-05-13T10:00:00.000Z", data: {} },
            { type: "running", stage: "running", message: "Reading local context.", at: "2026-05-13T10:00:01.000Z", data: {} },
            { type: "completed", stage: "completed", message: "Agent run completed.", at: "2026-05-13T10:00:06.000Z", data: {} },
          ],
        },
      },
      { role: "user", text: "New running request." },
    ];
    const runKey = chatSessionRunKey();
    readerState.chatPendingBySession[runKey] = true;
    readerState.chatProgressBySession[runKey] = {
      requestId: "reader-chat-current-run",
      status: "running",
      stage: "tool",
      detail: "Generating image...",
      visibleEvents: [{ stage: "tool", detail: "Generating image...", at: "2026-05-13T10:00:08.000Z" }],
      workTrace: {
        status: "running",
        items: [{ type: "tool", text: "Generating image...", at: "2026-05-13T10:00:08.000Z", source: "runtime" }],
      },
    };
    syncCurrentChatRunState();
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  const askPane = page.locator("#askPane");
  const previousSummary = askPane.locator(".ask-run-summary").first();
  await previousSummary.locator("[data-run-summary-toggle]").scrollIntoViewIfNeeded();
  await previousSummary.locator("[data-run-summary-toggle]").click();
  await expect(previousSummary.locator(".ask-run-summary-events").getByText("Reading local context.")).toBeVisible();

  await page.evaluate(() => {
    const runKey = chatSessionRunKey();
    readerState.chatProgressBySession[runKey] = {
      ...readerState.chatProgressBySession[runKey],
      updatedAt: "2026-05-13T10:00:09.000Z",
    };
    syncCurrentChatRunState();
    renderReaderChatMessages({ scrollToBottom: true });
  });

  await expect(askPane.locator(".ask-run-summary").first().locator(".ask-run-summary-events").getByText("Reading local context.")).toBeVisible();
  await expect(askPane.locator(".ask-message-progress-inline").getByText("Generating image...")).toBeVisible();
});

test("reader ask flow renders MCP artifact cards", async ({ page }) => {
  await openFixtureReader(page);
  await installAgentMocks(page, {
    artifacts: [
      {
        id: "mcp_img_e2e",
        kind: "image",
        source: "mcp",
        mimeType: "image/png",
        fileName: "mcp-chart.png",
        url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
        downloadUrl: "/api/media/mcp_img_e2e/download",
        size: 12,
        width: 1,
        height: 1,
      },
      {
        id: "mcp_file_e2e",
        kind: "text",
        source: "mcp",
        mimeType: "text/markdown",
        fileName: "mcp-note.md",
        url: "/api/media/mcp_file_e2e",
        downloadUrl: "/api/media/mcp_file_e2e/download",
        size: 18,
        width: 0,
        height: 0,
      },
    ],
  });

  await showAskPane(page);
  const askInput = page.getByPlaceholder("Ask anything");
  await askInput.fill("展示 MCP 返回的 artifact");
  await page.getByRole("button", { name: "Send" }).click();

  const askPane = page.locator("#askPane");
  const imageCard = askPane.locator(".ask-image-card").filter({ hasText: "mcp-chart.png" });
  await expect(imageCard).toBeVisible();
  await expect(imageCard.locator("img")).toHaveAttribute("src", /^data:image\/png;base64,/);
  await expect(askPane.locator(".ask-file-card").filter({ hasText: "mcp-note.md" })).toHaveAttribute("href", /\/api\/media\/mcp_file_e2e\/download/);
});

test("reader trash uses clear all with confirmation", async ({ page }) => {
  const deletedSessionIds = [];
  const trashedSessions = [
    {
      id: "trashed-session-1",
      title: "First trashed chat",
      lastMessagePreview: "First",
      updatedAt: "2026-05-15T10:00:00.000Z",
      trashedAt: "2026-05-15T10:05:00.000Z",
      state: "trashed",
    },
    {
      id: "trashed-session-2",
      title: "Second trashed chat",
      lastMessagePreview: "Second",
      updatedAt: "2026-05-15T11:00:00.000Z",
      trashedAt: "2026-05-15T11:05:00.000Z",
      state: "trashed",
    },
  ];
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sessions: url.searchParams.get("state") === "trashed" ? trashedSessions : [],
      }),
    });
  });
  await page.route("**/api/chat/session/delete", async (route) => {
    deletedSessionIds.push(route.request().postDataJSON().sessionId);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ success: true }),
    });
  });
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);

  await showAskPane(page);
  await page.getByRole("button", { name: "Trash chats" }).click();
  await expect(page.locator("#chatSessionPopoverTitle")).toHaveText("Trash");
  await expect(page.locator("#clearTrashSessions")).toHaveText("Clear all");
  await expect(page.locator("#clearTrashSessions")).toBeEnabled();

  await page.locator("#clearTrashSessions").click();
  await expect(page.locator("#readerClearTrashDialog")).toBeVisible();
  await expect(page.locator("#readerClearTrashMessage")).toContainText("Permanently delete 2 trashed chats");
  await page.locator("#readerCancelClearTrash").click();
  await expect(page.locator("#readerClearTrashDialog")).not.toBeVisible();
  expect(deletedSessionIds).toEqual([]);

  await page.locator("#clearTrashSessions").click();
  await expect(page.locator("#readerClearTrashDialog")).toBeVisible();
  await page.locator("#readerConfirmClearTrash").click();
  await expect.poll(() => deletedSessionIds).toEqual(["trashed-session-1", "trashed-session-2"]);
});

test("reader session tabs expose archive trash and active views", async ({ page }) => {
  const activeSessions = [{
    id: "active-session-1",
    title: "Active chat",
    noteId: "pdf-deepseek-v4-old123",
    originNoteId: "pdf-deepseek-v4-old123",
    lastMessagePreview: "Working",
    updatedAt: "2026-05-15T09:00:00.000Z",
    state: "active",
  }];
  const archivedSessions = [{
    id: "archived-session-1",
    title: "Archived chat",
    originNoteId: "pdf-deepseek-v4-archive123",
    lastMessagePreview: "Done",
    updatedAt: "2026-05-15T08:00:00.000Z",
    archivedAt: "2026-05-15T08:05:00.000Z",
    state: "archived",
  }];
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    const url = new URL(route.request().url());
    const state = url.searchParams.get("state") || "active";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sessions: state === "archived" ? archivedSessions : state === "active" ? activeSessions : [],
      }),
    });
  });
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);

  await showAskPane(page);
  const sessionTabs = page.locator(".ask-session-tabs button");
  await expect(sessionTabs).toHaveCount(4);
  await expect(sessionTabs.nth(0)).toHaveAttribute("aria-label", "Show context window");
  await expect(sessionTabs.nth(1)).toHaveAttribute("aria-label", "Archived chats");
  await expect(sessionTabs.nth(2)).toHaveAttribute("aria-label", "Trash chats");
  await expect(sessionTabs.nth(3)).toHaveAttribute("aria-label", "Chats");

  await page.locator("#chatSessionArchivedButton").click();
  await expect(page.locator("#chatSessionPopoverTitle")).toHaveText("Archived");
  await expect(page.locator("#newChatSession")).toBeHidden();
  await expect(page.locator("#clearTrashSessions")).toBeHidden();
  await expect(page.getByText("Archived chat")).toBeVisible();
  await expect(page.locator(".ask-session-row", { hasText: "Archived chat" }).locator(".ask-session-meta")).toContainText("DeepSeek V4");
  await page.locator(".ask-session-row", { hasText: "Archived chat" }).hover();
  await page.getByRole("button", { name: /More actions for Archived chat/ }).click();
  await expect(page.getByRole("button", { name: /Restore Archived chat/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Move Archived chat to Trash/ })).toBeVisible();

  await page.locator("#chatSessionMenuButton").click();
  await expect(page.locator("#chatSessionPopoverTitle")).toHaveText("Sessions");
  await expect(page.locator("#newChatSession")).toBeVisible();
  await expect(page.getByText("Active chat")).toBeVisible();
  await expect(page.locator(".ask-session-row", { hasText: "Active chat" })).toContainText("DeepSeek V4");
  await page.locator(".ask-session-row", { hasText: "Active chat" }).hover();
  await page.getByRole("button", { name: /More actions for Active chat/ }).click();
  await expect(page.getByRole("button", { name: /Rename Active chat/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Archive Active chat/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Move Active chat to Trash/ })).toBeVisible();
});

test("reader restore keeps the current session list view", async ({ page }) => {
  const archiveCalls = [];
  const stateBySessionId = new Map([["archived-session-1", "archived"]]);
  const archivedSession = {
    id: "archived-session-1",
    title: "Archived chat",
    lastMessagePreview: "Done",
    updatedAt: "2026-05-15T08:00:00.000Z",
    archivedAt: "2026-05-15T08:05:00.000Z",
  };
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    const url = new URL(route.request().url());
    const state = url.searchParams.get("state") || "active";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sessions: stateBySessionId.get("archived-session-1") === state
          ? [{ ...archivedSession, state }]
          : [],
      }),
    });
  });
  await page.route("**/api/chat/session/archive", async (route) => {
    const payload = route.request().postDataJSON();
    archiveCalls.push(payload);
    stateBySessionId.set(payload.sessionId, payload.state);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session: {
          ...archivedSession,
          id: payload.sessionId,
          sessionId: payload.sessionId,
          state: payload.state,
          archived: payload.state === "archived",
          trashed: payload.state === "trashed",
        },
      }),
    });
  });
  await page.route("**/api/chat/session?id=archived-session-1", async (route) => {
    throw new Error(`Restore should not load the restored session: ${route.request().url()}`);
  });

  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await showAskPane(page);

  await page.locator("#chatSessionArchivedButton").click();
  await expect(page.locator("#chatSessionPopoverTitle")).toHaveText("Archived");
  await expect(page.getByText("Archived chat")).toBeVisible();
  await page.locator(".ask-session-row", { hasText: "Archived chat" }).hover();
  await page.getByRole("button", { name: /More actions for Archived chat/ }).click();
  await page.getByRole("button", { name: /Restore Archived chat/ }).click();

  await expect(page.locator("#chatSessionPopoverTitle")).toHaveText("Archived");
  await expect(page.locator("#chatSessionPopover")).toBeVisible();
  await expect(page.locator("#chatSessionList")).toContainText("Archive is empty");
  await expect(page.locator("#readerChatMessages")).not.toContainText("Archived loaded message");
  expect(archiveCalls).toEqual([{ sessionId: "archived-session-1", state: "active" }]);
});

test("reader can click an archived session to use it without moving it", async ({ page }) => {
  const archivedSession = {
    id: "archived-session-1",
    title: "Archived chat",
    originNoteTitle: "Original Paper",
    lastMessagePreview: "Done",
    updatedAt: "2026-05-15T08:00:00.000Z",
    archivedAt: "2026-05-15T08:05:00.000Z",
    state: "archived",
  };
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    const url = new URL(route.request().url());
    const state = url.searchParams.get("state") || "active";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ sessions: state === "archived" ? [archivedSession] : [] }),
    });
  });
  await page.route("**/api/chat/session/archive", async (route) => {
    throw new Error(`Clicking an archived session should not move it: ${route.request().postData()}`);
  });
  await page.route("**/api/chat/session?id=archived-session-1", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session: {
          ...archivedSession,
          state: "active",
          messages: [{ role: "assistant", content: "Archived loaded message" }],
        },
      }),
    });
  });

  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await showAskPane(page);

  await page.locator("#chatSessionArchivedButton").click();
  await expect(page.locator("#chatSessionPopoverTitle")).toHaveText("Archived");
  await expect(page.locator(".ask-session-row", { hasText: "Archived chat" }).locator(".ask-session-meta")).toContainText("Original Paper");
  await page.locator(".ask-session-row", { hasText: "Archived chat" }).locator(".ask-session-item").click();

  await expect(page.locator("#chatSessionPopover")).toBeHidden();
  await expect(page.locator("#readerChatMessages")).toContainText("Archived loaded message");
  await expect(page.locator("#readerChatInput")).toBeEnabled();
});

test("reader archive and trash actions run from the row menu without confirm", async ({ page }) => {
  const archiveCalls = [];
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sessions: [{
          id: "active-session-1",
          title: "Active chat",
          updatedAt: "2026-05-15T09:00:00.000Z",
          state: "active",
        }],
      }),
    });
  });
  await page.route("**/api/chat/session/archive", async (route) => {
    const payload = route.request().postDataJSON();
    archiveCalls.push(payload);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session: {
          id: payload.sessionId,
          sessionId: payload.sessionId,
          title: "Active chat",
          state: payload.state,
          archived: payload.state === "archived",
          trashed: payload.state === "trashed",
        },
      }),
    });
  });
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await showAskPane(page);

  await page.locator("#chatSessionMenuButton").click();
  await expect(page.getByText("Active chat")).toBeVisible();
  await page.locator(".ask-session-row", { hasText: "Active chat" }).hover();
  await page.getByRole("button", { name: /More actions for Active chat/ }).click();
  await page.getByRole("button", { name: /Archive Active chat/ }).click();
  await expect.poll(() => archiveCalls).toEqual([{ sessionId: "active-session-1", state: "archived" }]);

  archiveCalls.length = 0;
  await page.locator("#chatSessionMenuButton").click();
  await page.locator("#chatSessionMenuButton").click();
  await expect(page.getByText("Active chat")).toBeVisible();
  await page.locator(".ask-session-row", { hasText: "Active chat" }).hover();
  await page.getByRole("button", { name: /More actions for Active chat/ }).click();
  await page.getByRole("button", { name: /Move Active chat to Trash/ }).click();
  await expect.poll(() => archiveCalls).toEqual([{ sessionId: "active-session-1", state: "trashed" }]);
});

test("reader permanent delete still requires confirmation", async ({ page }) => {
  const deletedSessionIds = [];
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sessions: url.searchParams.get("state") === "trashed"
          ? [{
            id: "trashed-session-1",
            title: "Trashed chat",
            updatedAt: "2026-05-15T09:00:00.000Z",
            trashedAt: "2026-05-15T09:05:00.000Z",
            state: "trashed",
          }]
          : [],
      }),
    });
  });
  await page.route("**/api/chat/session/delete", async (route) => {
    deletedSessionIds.push(route.request().postDataJSON().sessionId);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ success: true }) });
  });
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await showAskPane(page);

  await page.locator("#chatSessionTrashButton").click();
  await expect(page.locator(".ask-session-row", { hasText: "Trashed chat" })).toBeVisible();
  await page.locator(".ask-session-row", { hasText: "Trashed chat" }).hover();
  await page.getByRole("button", { name: /More actions for Trashed chat/ }).click();
  await page.getByRole("button", { name: /Permanently delete Trashed chat/ }).click();
  expect(deletedSessionIds).toEqual([]);
  await expect(page.getByRole("button", { name: /Confirm delete Trashed chat/ })).toBeVisible();
  await page.getByRole("button", { name: /Confirm delete Trashed chat/ }).click();
  await expect.poll(() => deletedSessionIds).toEqual(["trashed-session-1"]);
});

test("reader chats tab opens immediately from a closed session menu", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ sessions: [] }),
    });
  });
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");

  if ((await page.locator("#askPaneToggle").getAttribute("aria-expanded")) !== "true") {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  await page.locator("#chatSessionMenuButton").click();
  await expect(page.locator("#chatSessionPopover")).toBeVisible();
  await expect(page.locator("#chatSessionPopoverTitle")).toHaveText("Sessions");

  await page.locator("#chatSessionMenuButton").click();
  await expect(page.locator("#chatSessionPopover")).toBeHidden();

  await page.locator("#chatSessionMenuButton").click();
  await expect(page.locator("#chatSessionPopover")).toBeVisible();
});

test("reader new chat is available in sessions and at the bottom of the ask tools menu", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ sessions: [] }),
    });
  });
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");

  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }
  await page.locator("#chatSessionMenuButton").click();
  await expect(page.locator("#chatSessionPopover")).toBeVisible();
  await expect(page.locator("#newChatSession")).toBeVisible();
  await page.locator("#chatSessionMenuButton").click();

  await page.evaluate(() => {
    readerState.chatMessages = [{ role: "assistant", text: "Old session text." }];
    setCurrentChatSessionId("session-before-new-chat");
    renderReaderChatMessages({ forceScrollToBottom: true });
  });
  await expect(page.locator("#readerChatMessages")).toContainText("Old session text.");

  await page.locator("#chatSessionMenuButton").click();
  await page.locator("#newChatSession").click();
  await expect(page.locator("#chatSessionPopover")).toBeHidden();
  await expect(page.locator("#readerChatMessages")).not.toContainText("Old session text.");
  await expect(askInput).toBeFocused();

  await page.evaluate(() => {
    readerState.chatMessages = [{ role: "assistant", text: "Old session text." }];
    setCurrentChatSessionId("session-before-new-chat");
    renderReaderChatMessages({ forceScrollToBottom: true });
  });
  await expect(page.locator("#readerChatMessages")).toContainText("Old session text.");

  await page.locator("#readerToolMenuButton").click();
  const toolOptions = page.locator("#readerToolRoot .ask-tool-menu-option");
  await expect(toolOptions.last()).toContainText("New chat");
  await toolOptions.last().click();

  await expect(page.locator("#readerToolPopover")).toBeHidden();
  await expect(page.locator("#readerChatMessages")).not.toContainText("Old session text.");
  await expect(askInput).toBeFocused();
});

test("reader slash commands show icons filter and start a new chat", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/chat/sessions**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ sessions: [] }),
    });
  });
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await showAskPane(page);

  const askInput = page.locator("#readerChatInput");
  await page.evaluate(() => {
    readerState.chatMessages = [{ role: "assistant", text: "Old session text." }];
    setCurrentChatSessionId("session-before-slash-new");
    renderReaderChatMessages({ forceScrollToBottom: true });
  });
  await expect(page.locator("#readerChatMessages")).toContainText("Old session text.");

  await askInput.fill("/");
  await expect(page.locator("#readerSlashCommandMenu")).toBeVisible();
  await expect(page.locator(".slash-command-item")).toHaveCount(2);
  await expect(page.locator(".slash-command-icon")).toHaveCount(2);
  await expect(page.locator(".slash-command-item").nth(0)).toContainText("New chat");
  await expect(page.locator(".slash-command-item").nth(0)).toContainText("Start a fresh Ask session");
  await expect(page.locator(".slash-command-item").nth(1)).toContainText("Compact");

  await askInput.fill("/ne");
  await expect(page.locator(".slash-command-item")).toHaveCount(1);
  await expect(page.locator(".slash-command-item")).toContainText("New chat");
  await expect(page.locator(".slash-command-item")).not.toContainText("Compact");
  await page.locator("[data-slash-command='new']").click();

  await expect(page.locator("#readerSlashCommandMenu")).toBeHidden();
  await expect(page.locator("#readerChatMessages")).not.toContainText("Old session text.");
  await expect(askInput).toHaveValue("");
  await expect(askInput).toBeFocused();
});

test("reader slash compact is disabled without a session and executable with one", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await showAskPane(page);

  let compressRequest = null;
  await page.route("**/api/chat/compress", async (route) => {
    compressRequest = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        compressed: true,
        context: {
          provider: "openai",
          model: "gpt-5.5",
          contextLength: 128000,
          tokensUsed: 64000,
          percentFull: 50,
          messageCount: 7,
          compactionEnabled: true,
          compressionCount: 1,
          lastCompressedAt: "2026-05-15T11:30:00.000Z",
          summaryAvailable: true,
        },
        message: {
          role: "divider",
          text: "Context compacted. Earlier conversation was summarized.",
          metadata: { type: "context_compaction" },
        },
      }),
    });
  });

  const askInput = page.locator("#readerChatInput");
  await askInput.fill("/compact");
  await expect(page.locator("#readerSlashCommandMenu")).toBeVisible();
  await expect(page.locator("[data-slash-command='compact']")).toBeDisabled();
  await expect(page.locator("[data-slash-command='compact']")).toContainText("No active session yet");
  await askInput.press("Enter");
  await expect.poll(() => compressRequest).toBeNull();

  await page.evaluate(() => {
    setCurrentChatSessionId("slash-compact-session");
    setReaderChatPending(true, "slash-compact-session");
  });
  await askInput.fill("/compact");
  await expect(page.locator("[data-slash-command='compact']")).toBeDisabled();
  await expect(page.locator("[data-slash-command='compact']")).toContainText("Wait for current answer to finish");
  await askInput.press("Enter");
  await expect.poll(() => compressRequest).toBeNull();

  await page.evaluate(() => {
    setReaderChatPending(false, "slash-compact-session");
  });
  await askInput.fill("/");
  await askInput.press("ArrowDown");
  await expect(page.locator("[data-slash-command='compact']")).toHaveClass(/is-active/);
  await expect(page.locator("[data-slash-command='compact']")).toBeEnabled();
  await expect(page.locator("[data-slash-command='compact']")).toContainText("Summarize this session's context");
  await askInput.press("Enter");

  await expect(page.locator("#readerSlashCommandMenu")).toBeHidden();
  await expect(page.locator(".ask-message-divider")).toContainText("Context compacted");
  expect(compressRequest).toMatchObject({ sessionId: "slash-compact-session", noteId: E2E_NOTE_ID });
});

test("reader attachment uploads show tray progress and can be removed", async ({ page }) => {
  await openFixtureReader(page);
  const askInput = page.getByPlaceholder("Ask anything");
  if (!(await askInput.isVisible())) {
    await page.getByRole("button", { name: "Ask" }).click();
  }

  const uploads = [];
  let releaseUpload;
  const uploadGate = new Promise((resolve) => {
    releaseUpload = resolve;
  });
  await page.route("**/api/chat/attachments", async (route) => {
    uploads.push(route.request().postDataJSON());
    await uploadGate;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        artifact: {
          id: "file_upload_1",
          kind: "text",
          source: "uploaded",
          mimeType: "text/plain",
          fileName: "reader-attachment.txt",
          size: 19,
          url: "/api/media/file_upload_1",
          downloadUrl: "/api/media/file_upload_1/download",
        },
      }),
    });
  });

  await page.locator("#readerAttachmentInput").setInputFiles({
    name: "reader-attachment.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("reader attachment\n"),
  });

  await expect(page.locator("#readerAttachmentTray")).toBeVisible();
  await expect(page.locator("#readerAttachmentTray")).toContainText("reader-attachment.txt");
  await expect(page.locator(".ask-attachment-loading")).toContainText("Uploading...");
  await expect(page.locator(".ask-attachment-badge")).toContainText("Uploading");

  releaseUpload();

  await expect(page.locator("#readerAttachmentTray")).toContainText("reader-attachment.txt");
  await expect(page.locator(".ask-attachment-loading")).toHaveCount(0);
  await expect(page.locator(".ask-attachment-badge")).toHaveCount(0);
  expect(uploads).toHaveLength(1);
  expect(uploads[0]).toMatchObject({
    fileName: "reader-attachment.txt",
    mimeType: "text/plain",
    metadata: { source: "reader_upload" },
  });

  await page.getByRole("button", { name: "Remove attachment" }).click();
  await expect(page.locator("#readerAttachmentTray")).toBeHidden();
});

test("reader ask tools add the current PDF page as an attachment", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await installAgentMocks(page);
  const uploads = [];
  await page.route("**/api/chat/attachments", async (route) => {
    const payload = route.request().postDataJSON();
    uploads.push(payload);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        artifact: {
          id: "img_pdf_page_1",
          kind: "image",
          source: "uploaded",
          mimeType: "image/png",
          fileName: payload.fileName,
          size: 120,
          width: 1,
          height: 1,
          url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
          downloadUrl: "/api/media/img_pdf_page_1/download",
        },
      }),
    });
  });

  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page.locator(".pdf-page-canvas")).toHaveCount(1);
  await showAskPane(page);
  await page.locator("#readerToolMenuButton").click();
  await page.getByRole("button", { name: "Add page", exact: true }).click();

  await expect.poll(() => uploads.length).toBe(1);
  expect(uploads[0].fileName).toMatch(/deepseek-v4-page-1\.png$/);
  expect(uploads[0].mimeType).toBe("image/png");
  expect(uploads[0].data).toMatch(/^data:image\/png;base64,/);
  await expect(page.locator("#readerAttachmentTray .ask-attachment-preview.is-image img")).toHaveAttribute("alt", "deepseek-v4-page-1.png");
});

test("reader manual context compaction updates the popover and adds a divider", async ({ page }) => {
  let compressionCount = 0;
  let lastCompressedAt = "";
  let compressRequest = null;
  let releaseCompress;
  const compressGate = new Promise((resolve) => {
    releaseCompress = resolve;
  });
  await installReaderFixtures(page, {
    contextStatus: () => ({
      context: {
        provider: "openai",
        model: "gpt-5.5",
        contextLength: 128000,
        tokensUsed: compressionCount ? 64000 : 112000,
        estimatedRequestTokens: compressionCount ? 64000 : 118000,
        messageTokens: compressionCount ? 30000 : 50000,
        instructionTokens: 4000,
        toolSchemaTokens: compressionCount ? 30000 : 64000,
        actualUsageAvailable: !compressionCount,
        usageUpdatedAt: compressionCount ? "" : "2026-05-15T11:20:00.000Z",
        thresholdTokens: 102400,
        thresholdPercent: 80,
        percentFull: compressionCount ? 50 : 88,
        messageCount: compressionCount ? 7 : 6,
        compactionEnabled: true,
        compressionCount,
        lastCompressedAt,
        summaryAvailable: compressionCount > 0,
      },
    }),
  });
  await ignoreMissingFavicon(page);
  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 1");
  await installAgentMocks(page);
  await page.route("**/api/chat/compress", async (route) => {
    compressRequest = route.request().postDataJSON();
    await compressGate;
    compressionCount = 1;
    lastCompressedAt = "2026-05-15T11:30:00.000Z";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        compressed: true,
        context: {
          provider: "openai",
          model: "gpt-5.5",
          contextLength: 128000,
          tokensUsed: 64000,
          estimatedRequestTokens: 64000,
          messageTokens: 30000,
          instructionTokens: 4000,
          toolSchemaTokens: 30000,
          actualUsageAvailable: false,
          usageUpdatedAt: "",
          thresholdTokens: 102400,
          thresholdPercent: 80,
          percentFull: 50,
          messageCount: 7,
          compactionEnabled: true,
          compressionCount,
          lastCompressedAt,
          summaryAvailable: true,
        },
        message: {
          role: "divider",
          text: "Context compacted. Earlier conversation was summarized.",
          metadata: {
            type: "context_compaction",
            focus: "tags only",
          },
        },
      }),
    });
  });

  await showAskPane(page);
  await page.evaluate(() => {
    setCurrentChatSessionId("e2e-session");
  });

  await page.locator("#readerContextButton").click();
  await expect(page.locator("#readerContextPopover")).toBeVisible();
  await expect(page.locator("#readerContextPopover")).toContainText("88% full");
  await expect(page.locator("#readerContextPopover")).toContainText("112k / 128k context used");
  await expect(page.locator("#readerContextPopover")).not.toContainText("Estimated request:");
  await expect(page.locator("#readerContextPopover")).not.toContainText("Instructions 4k");
  await expect(page.locator("#readerContextPopover")).not.toContainText("Threshold");
  await expect(page.locator("#readerContextButton")).not.toHaveClass(/is-warning/);
  await page.locator("#readerContextCompactFocus").fill("tags only");
  await page.locator("[data-context-action='compact']").click();
  await expect(page.locator("[data-context-action='compact']")).toHaveText("Compacting");
  await expect(page.locator(".ask-context-compaction-divider.is-running")).toContainText("Compacting context");
  await expect(page.locator(".ask-context-compaction-spinner")).toBeVisible();

  releaseCompress();

  await expect(page.locator("#readerContextPopover")).toContainText("Context compacted.");
  await expect(page.locator("#readerContextPopover")).toContainText("1 compacted");
  await expect(page.locator("#readerContextPopover")).toContainText("50% full");
  await expect(page.locator("#readerContextPopover")).not.toContainText("Estimated request:");
  await expect(page.locator(".ask-context-compaction-divider.is-running")).toHaveCount(0);
  await expect(page.locator(".ask-message-divider")).toContainText("Context compacted");
  await expect(page.locator(".ask-message-divider")).not.toContainText("Earlier conversation was summarized");
  expect(compressRequest).toMatchObject({
    sessionId: "e2e-session",
    focus: "tags only",
    noteId: E2E_NOTE_ID,
  });
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

test("reader chat renders LaTeX math in assistant messages", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.evaluate(() => {
    readerState.chatMessages = [{
      role: "assistant",
      text: "欧拉公式是：\n\\[\ne^{ix}=\\cos x+i\\sin x\n\\]\n其中 \\(i^2=-1\\)。",
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  const bubble = page.locator(".ask-message-assistant .ask-bubble");
  await expect(bubble.locator(".katex")).toHaveCount(2);
  await expect(bubble.locator(".chat-math-block")).toBeVisible();
  await expect(bubble).not.toContainText("\\[");
  await expect(bubble).not.toContainText("\\]");
});

test("reader chat renders markdown blockquotes", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.evaluate(() => {
    readerState.chatMessages = [{
      role: "assistant",
      text: "当然，这段可以译为：\n\n> 第一段引用。\n>\n> 第二段引用，包含 **重点**。",
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  const bubble = page.locator(".ask-message-assistant .ask-bubble");
  const quote = bubble.locator("blockquote");
  await expect(quote).toBeVisible();
  await expect(quote).toContainText("第一段引用");
  await expect(quote).toContainText("第二段引用");
  await expect(quote.locator("strong")).toHaveText("重点");
  await expect(quote.locator("strong")).toHaveCSS("font-weight", "600");
  await expect(bubble).not.toContainText("> 第一段引用");
});

test("reader chat renders context compaction markers", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.evaluate(() => {
    readerState.contextStatus = normalizeContextStatus({
      provider: "openai",
      model: "gpt-5.5",
      contextLength: 128000,
      tokensUsed: 64000,
      actualUsageAvailable: true,
      percentFull: 50,
      messageCount: 12,
      compactionEnabled: true,
      compressionCount: 3,
      summaryAvailable: true,
    });
    readerState.contextPopoverOpen = true;
    renderReaderContextControls();
  });
  await expect(page.locator("#readerContextPopover")).toContainText("Session compacted 3 times");
  await expect(page.locator("#readerContextPopover")).toContainText("Accuracy may degrade. Consider starting a new chat.");

  await page.evaluate(() => {
    readerState.chatMessages = [{
      role: "assistant",
      text: "压缩后继续回答。",
      runTrace: {
        status: "completed",
        events: [{
          type: "context_compressed",
          message: "Compressed long session context before model call.",
          data: { before_message_count: 98, after_message_count: 24 },
        }],
      },
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  await expect(page.locator(".ask-context-compaction-divider")).toContainText("Context compacted");

  await page.evaluate(() => {
    readerState.chatMessages = [
      { role: "user", text: "Microcompact 解释一下" },
      {
        role: "assistant",
        text: "压缩后继续回答。",
        runTrace: {
          status: "completed",
          events: [{
            type: "context_compressed",
            message: "Compressed long session context before model call.",
            data: { before_message_count: 98, after_message_count: 24 },
          }],
        },
      },
    ];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  await expect(page.locator(".ask-context-compaction-divider")).toHaveCount(1);
  await expect(page.locator(".ask-context-compaction-divider")).toContainText("Context compacted");
  const compactionOrder = await page.locator("#readerChatMessages > .ask-context-compaction-divider, #readerChatMessages > .ask-message").evaluateAll((nodes) => (
    nodes.map((node) => node.classList.contains("ask-context-compaction-divider") ? "compact" : node.textContent?.trim() || "")
  ));
  expect(compactionOrder[0]).toBe("compact");
  expect(compactionOrder[1]).toContain("Microcompact 解释一下");

  await page.evaluate(() => {
    readerState.chatMessages = [{ role: "user", text: "Microcompact 解释一下" }];
    readerState.chatPendingBySession.__draft_chat_session__ = true;
    readerState.chatProgressBySession.__draft_chat_session__ = {
      status: "running",
      detail: "Compacting context",
      events: [{
        type: "context_compressing",
        detail: "Compacting context",
        data: {},
      }],
    };
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  await expect(page.locator(".ask-context-compaction-divider.is-running")).toContainText("Compacting context");
  await expect(page.locator(".ask-context-compaction-spinner")).toBeVisible();
});

test("reader chat linkifies adjacent Chinese parenthetical URLs separately", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.evaluate(() => {
    readerState.chatMessages = [{
      role: "assistant",
      text: "来源链接：https://platform.openai.com/docs/models（跳转到https://developers.openai.com/api/docs/models）。",
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  const links = page.locator(".ask-message-assistant .ask-bubble a");
  await expect(links).toHaveCount(2);
  await expect(links.nth(0)).toHaveAttribute("href", "https://platform.openai.com/docs/models");
  await expect(links.nth(0)).toHaveText("https://platform.openai.com/docs/models");
  await expect(links.nth(1)).toHaveAttribute("href", "https://developers.openai.com/api/docs/models");
  await expect(links.nth(1)).toHaveText("https://developers.openai.com/api/docs/models");
});

test("reader note renders LaTeX math in generated HTML notes", async ({ page }) => {
  await openFixtureReader(page);

  const notePage = page.locator("#notePage");
  await expect(notePage.locator(".note-math-inline .katex")).toHaveCount(2);
  await expect(notePage.locator(".note-math-block .katex")).toHaveCount(1);
  await expect(notePage).not.toContainText("\\(");
  await expect(notePage).not.toContainText("\\]");
  await expect(notePage.locator("pre code")).toContainText("$not_rendered$");
});

test("reader chat tool activity shows view and preview with real diff line numbers", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.evaluate(() => {
    readerState.toolDiffs = {
      "snapshot-e2e": {
        snapshotId: "snapshot-e2e",
        files: [{
          path: "resources/Paper-html/e2e-deepseek-v4.html",
          diff: [
            "resources/Paper-html/e2e-deepseek-v4.html@@ -74,14 +74,6 @@ <h4>5.2.5. Sandbox Infrastructure</h4>",
            " <h3>5.3. Standard Benchmark Evaluation</h3>",
            "-<h4>5.3.1. Evaluation Setup</h4>",
            " <h4 id=\"5.4.1--chinese-writing\">5.4.1. Chinese Writing</h4>"
          ].join("\n")
        }]
      }
    };
    readerState.toolDiffOpen = { "message-0:snapshot-e2e:0": true };
    readerState.chatMessages = [{
      role: "assistant",
      text: "已更新。",
      toolActivity: [{
        name: "write_note",
        sessionId: "session-e2e",
        snapshotId: "snapshot-e2e",
        noteId: "",
        undoable: true,
        changedFiles: [{
          path: "resources/Paper-html/e2e-deepseek-v4.html",
          beforeBytes: 200,
          afterBytes: 160
        }],
        message: "Tool completed: write_note"
      }]
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  const actions = page.locator(".ask-tool-activity-actions button");
  await expect(actions).toHaveText(["View", "Preview", "Undo"]);
  await page.evaluate(() => {
    readerState.toolSnapshots = [{ snapshotId: "snapshot-e2e", canUndo: false, canRedo: false, undoable: true }];
    renderReaderChatMessages({ forceScrollToBottom: false });
  });
  await expect(actions.filter({ hasText: "Undo" })).toBeDisabled();
  await page.evaluate(() => {
    readerState.toolSnapshots = [{ snapshotId: "snapshot-e2e", canUndo: true, canRedo: false, undoable: true }];
    renderReaderChatMessages({ forceScrollToBottom: false });
  });
  await page.evaluate(() => {
    readerState.toolUndoStates["snapshot-e2e"] = "undoing";
    renderReaderChatMessages({ forceScrollToBottom: false });
  });
  await expect(actions).toHaveText(["View", "Preview", "Undo"]);
  const firstContextLineNumbers = await page.locator(".ask-tool-diff-row.is-context").first().locator(".ask-tool-diff-line").allTextContents();
  expect(firstContextLineNumbers).toEqual(["74", "74"]);
  await expect(page.locator(".ask-tool-diff-line", { hasText: "1" })).toHaveCount(0);
});

test("reader chat tool activity view jumps to the changed note heading", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.evaluate(() => {
    const noteId = currentChatNoteId();
    const beforeSections = Array.from({ length: 32 }, (_, index) => (
      `<h2>Filler ${index + 1}</h2><p>${"Long spacer text. ".repeat(16)}</p>`
    )).join("");
    const afterSections = Array.from({ length: 12 }, (_, index) => (
      `<h2>Tail ${index + 1}</h2><p>${"More spacer text. ".repeat(16)}</p>`
    )).join("");
    elements.notePage.innerHTML = `${beforeSections}<h2 id="jump-target">Jump Target</h2><p>Changed content.</p>${afterSections}`;
    if (typeof window.buildNoteMenu === "function") window.buildNoteMenu(elements.notePage);
    mountReaderNoteMenu();
    elements.notePane.scrollTop = 0;
    window.refreshCurrentNoteAfterToolUndo = async () => {};
    refreshCurrentNoteAfterToolUndo = window.refreshCurrentNoteAfterToolUndo;
    readerState.chatMessages = [{
      role: "assistant",
      text: "已更新。",
      toolActivity: [{
        name: "write_note",
        sessionId: "session-e2e",
        snapshotId: "snapshot-view-target",
        noteId,
        heading: "Jump Target",
        position: "append",
        addedHeadings: ["Jump Target"],
        undoable: true,
        changedFiles: [{
          path: "resources/Paper-html/e2e-deepseek-v4.html",
          beforeBytes: 200,
          afterBytes: 260
        }],
        message: "Updated HTML note section using append."
      }]
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  await page.getByRole("button", { name: "View", exact: true }).click();
  await expect.poll(() => page.evaluate(() => elements.notePane.scrollTop)).toBeGreaterThan(500);
  await expect.poll(() => page.evaluate(() => {
    const heading = Array.from(elements.notePage.querySelectorAll("h1, h2, h3, h4"))
      .find((node) => node.textContent.trim() === "Jump Target");
    const paneRect = elements.notePane.getBoundingClientRect();
    return Math.round(heading.getBoundingClientRect().top - paneRect.top);
  })).toBeLessThan(190);
});

test("reader chat tool activity shows first-line diff line numbers", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.evaluate(() => {
    readerState.toolDiffs = {
      "snapshot-e2e-snippet": {
        snapshotId: "snapshot-e2e-snippet",
        files: [{
          path: "resources/Paper-html/e2e-deepseek-v4.html",
          diff: [
            "@@ -1,5 +1,4 @@",
            " <h4 id=\"5.4.2--search\">5.4.2. Search</h4>",
            "-<h4 id=\"5.4.4--code-agent\">5.4.4. Code Agent</h4>",
            " <h2>6. Conclusion, Limitations, and Future Directions</h2>"
          ].join("\n")
        }]
      }
    };
    readerState.toolDiffOpen = { "message-0:snapshot-e2e-snippet:0": true };
    readerState.chatMessages = [{
      role: "assistant",
      text: "已更新。",
      toolActivity: [{
        name: "write_note",
        sessionId: "session-e2e",
        snapshotId: "snapshot-e2e-snippet",
        noteId: "",
        undoable: true,
        changedFiles: [{
          path: "resources/Paper-html/e2e-deepseek-v4.html",
          beforeBytes: 200,
          afterBytes: 160
        }],
        message: "Tool completed: write_note"
      }]
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  });

  await expect(page.locator(".ask-tool-activity-actions button")).toHaveText(["View", "Preview", "Undo"]);
  const diffRows = page.locator(".ask-tool-diff-row");
  await expect(diffRows).toHaveCount(4);
  await expect(diffRows.nth(1).locator(".ask-tool-diff-line")).toHaveText(["1", "1"]);
  await expect(diffRows.nth(2).locator(".ask-tool-diff-line")).toHaveText(["2", ""]);
  await expect(diffRows.nth(3).locator(".ask-tool-diff-line")).toHaveText(["3", "2"]);
});

test("reader chat preview expands only the clicked tool activity", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  await page.route("**/api/chat/tool-snapshot-diff**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        sessionId: "session-e2e",
        snapshotId: "shared-snapshot",
        files: [{
          path: "resources/Paper-html/e2e-deepseek-v4.html",
          diff: [
            "@@ -4,3 +4,4 @@",
            " <h2>Overview</h2>",
            "+<p>Added once.</p>"
          ].join("\n")
        }]
      })
    });
  });

  const toolActivity = {
    name: "write_note",
    sessionId: "session-e2e",
    snapshotId: "shared-snapshot",
    noteId: "",
    undoable: true,
    changedFiles: [{
      path: "resources/Paper-html/e2e-deepseek-v4.html",
      beforeBytes: 200,
      afterBytes: 240
    }],
    message: "Tool completed: write_note"
  };
  await page.evaluate((activity) => {
    readerState.toolDiffs = {};
    readerState.toolDiffOpen = {};
    readerState.chatMessages = [
      { role: "assistant", text: "第一次。", toolActivity: [activity] },
      { role: "assistant", text: "第二次。", toolActivity: [activity] }
    ];
    renderReaderChatMessages({ forceScrollToBottom: true });
  }, toolActivity);

  const firstActivity = page.locator(".ask-tool-activity-item").nth(0);
  const secondActivity = page.locator(".ask-tool-activity-item").nth(1);
  await firstActivity.getByRole("button", { name: "Preview" }).click();

  await expect(firstActivity.locator(".ask-tool-diff")).toHaveCount(1);
  await expect(secondActivity.locator(".ask-tool-diff")).toHaveCount(0);
});

test("reader chat shows only the final note edit card for repeated same-file writes", async ({ page }) => {
  await openFixtureReader(page);
  const askToggle = page.getByRole("button", { name: "Toggle Ask panel" });
  if ((await askToggle.getAttribute("aria-expanded")) !== "true") {
    await askToggle.click();
  }

  const requestedSnapshots = [];
  await page.route("**/api/chat/tool-snapshot-diff**", async (route) => {
    const url = new URL(route.request().url());
    const snapshotId = url.searchParams.get("snapshotId") || "";
    requestedSnapshots.push(snapshotId);
    const index = Number(snapshotId.match(/-(\d+)$/)?.[1] || 0);
    const added = index % 2 === 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        sessionId: "session-e2e",
        snapshotId,
        files: [{
          path: "resources/Paper-html/e2e-deepseek-v4.html",
          diff: [
            "@@ -20,2 +20,2 @@",
            " <h2>Section</h2>",
            added ? `+<p>Added by ${snapshotId}</p>` : `-<p>Removed by ${snapshotId}</p>`
          ].join("\n")
        }]
      })
    });
  });

  const activities = Array.from({ length: 5 }, (_, index) => ({
    name: "write_note",
    sessionId: "session-e2e",
    snapshotId: `snapshot-e2e-${index + 1}`,
    noteId: "",
    undoable: true,
    changedFiles: [{
      path: "resources/Paper-html/e2e-deepseek-v4.html",
      beforeBytes: 200 + index,
      afterBytes: 201 + index
    }],
    message: `Tool completed: write_note ${index + 1}`
  }));

  await page.evaluate((toolActivity) => {
    readerState.chatMessages = [{
      role: "assistant",
      text: "已加好了。",
      toolActivity
    }];
    renderReaderChatMessages({ forceScrollToBottom: true });
  }, activities);

  await expect(page.locator(".ask-tool-activity-item")).toHaveCount(1);
  await expect(page.locator(".ask-tool-activity-actions button")).toHaveText(["View", "Preview", "Undo"]);
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.locator(".ask-tool-diff")).toHaveCount(1);
  await expect(page.locator(".ask-tool-diff-file")).toHaveCount(5);
  await expect(page.locator(".ask-tool-diff-step-count")).toHaveText([
    "Change 1 / 5",
    "Change 2 / 5",
    "Change 3 / 5",
    "Change 4 / 5",
    "Change 5 / 5"
  ]);
  await expect(page.locator(".ask-tool-diff-row.is-added")).toHaveCount(3);
  await expect(page.locator(".ask-tool-diff-row.is-removed")).toHaveCount(2);
  const changeToggles = page.locator("[data-tool-diff-collapse]");
  await expect(changeToggles).toHaveCount(5);
  await expect(changeToggles.nth(1)).toHaveAttribute("aria-expanded", "true");
  await changeToggles.nth(1).click();
  await expect(page.locator(".ask-tool-diff-file").nth(1)).toHaveClass(/is-collapsed/);
  await expect(page.locator(".ask-tool-diff-file").nth(1).locator(".ask-tool-diff-viewer")).toHaveCount(0);
  await expect(page.locator(".ask-tool-diff-row.is-added")).toHaveCount(3);
  await expect(page.locator(".ask-tool-diff-row.is-removed")).toHaveCount(1);
  await expect(changeToggles.nth(1)).toHaveAttribute("aria-expanded", "false");
  await changeToggles.nth(1).click();
  await expect(page.locator(".ask-tool-diff-file").nth(1)).not.toHaveClass(/is-collapsed/);
  await expect(page.locator(".ask-tool-diff-row.is-added")).toHaveCount(3);
  await expect(page.locator(".ask-tool-diff-row.is-removed")).toHaveCount(2);
  expect(requestedSnapshots).toEqual([
    "snapshot-e2e-1",
    "snapshot-e2e-2",
    "snapshot-e2e-3",
    "snapshot-e2e-4",
    "snapshot-e2e-5"
  ]);
  await expect(page.locator("[data-tool-toggle]")).toHaveAttribute("data-tool-toggle", "snapshot-e2e-5");
  await expect(page.locator("[data-tool-toggle]")).toHaveAttribute(
    "data-tool-toggle-snapshots",
    "snapshot-e2e-5,snapshot-e2e-4,snapshot-e2e-3,snapshot-e2e-2,snapshot-e2e-1"
  );
  await page.evaluate(() => {
    readerState.toolUndoStates["snapshot-e2e-1|snapshot-e2e-2|snapshot-e2e-3|snapshot-e2e-4|snapshot-e2e-5"] = "undone";
    renderReaderChatMessages({ forceScrollToBottom: false });
  });
  await expect(page.locator("[data-tool-toggle]")).toHaveAttribute("data-tool-toggle", "snapshot-e2e-1");
  await expect(page.locator("[data-tool-toggle]")).toHaveAttribute(
    "data-tool-toggle-snapshots",
    "snapshot-e2e-1,snapshot-e2e-2,snapshot-e2e-3,snapshot-e2e-4,snapshot-e2e-5"
  );
});

test("reader PDF zoom keeps immediate user scroll instead of snapping back", async ({ page }) => {
  await installStubPdfJs(page, {
    pageCount: 12,
    delayedZoomPage: 6,
    delayedZoomMs: 280,
    zoomHeightExtraByPage: { 6: 320 },
  });
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);

  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page).toHaveTitle("Paper Reader");
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 12");
  await expect(page.locator("#zoomLabel")).toHaveText("215%");

  const pageInput = page.locator("#pdfPageInput");
  await pageInput.fill("7");
  await pageInput.press("Enter");
  await expect(pageInput).toHaveValue("7");

  const viewer = page.locator("#pdfViewer");
  const beforeZoomScrollTop = await viewer.evaluate((element) => element.scrollTop);
  await page.locator("#zoomIn").click();
  await expect(page.locator("#zoomLabel")).toHaveText("225%");
  await viewer.evaluate((element) => {
    element.scrollTop += 1200;
    element.dispatchEvent(new Event("scroll"));
    element.scrollTop += 1200;
    element.dispatchEvent(new Event("scroll"));
    element.scrollTop += 1200;
    element.dispatchEvent(new Event("scroll"));
  });
  const afterUserScrollState = await viewer.evaluate((element) => {
    const anchor = element.scrollTop + Math.max(64, Math.min(180, Math.round(element.clientHeight * 0.18)));
    const pages = Array.from(element.querySelectorAll(".pdf-page")).map((page) => ({
      page: Number(page.dataset.page),
      top: page.offsetTop,
      bottom: page.offsetTop + page.offsetHeight,
    }));
    const current = pages.find((page) => page.top <= anchor && page.bottom >= anchor) || null;
    return {
      scrollTop: element.scrollTop,
      currentPage: current?.page || null,
    };
  });

  await page.waitForFunction(() => !document.querySelector("#pdfViewer .pdf-page[data-rendering='true']"));
  await expect.poll(async () => Number(await pageInput.inputValue())).toBeGreaterThanOrEqual(8);

  const scrollState = await viewer.evaluate((element) => {
    const anchor = element.scrollTop + Math.max(64, Math.min(180, Math.round(element.clientHeight * 0.18)));
    const pages = Array.from(element.querySelectorAll(".pdf-page")).map((page) => ({
      page: Number(page.dataset.page),
      top: page.offsetTop,
      bottom: page.offsetTop + page.offsetHeight,
    }));
    const current = pages.find((page) => page.top <= anchor && page.bottom >= anchor) || null;
    return {
      scrollTop: element.scrollTop,
      currentPage: current?.page || null,
    };
  });

  expect(scrollState.scrollTop).toBeGreaterThan(beforeZoomScrollTop + 1000);
  expect(scrollState.scrollTop).toBeGreaterThanOrEqual(afterUserScrollState.scrollTop - 1);
  expect(scrollState.currentPage).toBeGreaterThanOrEqual(afterUserScrollState.currentPage);
});

test("reader PDF zoom keeps immediate partial scroll within the same page", async ({ page }) => {
  await installStubPdfJs(page, { pageCount: 12, delayedZoomPage: 7, delayedZoomMs: 280 });
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);

  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await expect(page.locator("#pdfPageTotal")).toHaveText("/ 12");

  const pageInput = page.locator("#pdfPageInput");
  await pageInput.fill("7");
  await pageInput.press("Enter");
  await expect(pageInput).toHaveValue("7");

  const viewer = page.locator("#pdfViewer");
  const beforeZoomScrollTop = await viewer.evaluate((element) => element.scrollTop);
  await page.locator("#zoomIn").click();
  await expect(page.locator("#zoomLabel")).toHaveText("225%");
  await viewer.evaluate((element) => {
    element.scrollTop += 420;
    element.dispatchEvent(new Event("scroll"));
  });

  await page.waitForFunction(() => !document.querySelector("#pdfViewer .pdf-page[data-rendering='true']"));

  const scrollState = await viewer.evaluate((element) => ({
    scrollTop: element.scrollTop,
    pageInputValue: document.querySelector("#pdfPageInput")?.value || null,
  }));

  expect(scrollState.scrollTop).toBeGreaterThan(beforeZoomScrollTop + 250);
  expect(scrollState.pageInputValue).toBe("7");
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

test("reader sticky note markers can be dragged and undone", async ({ page }) => {
  const saves = [];
  await openFixtureReader(page);
  await page.unroute("**/api/annotations");
  await page.route("**/api/annotations", async (route) => {
    if (route.request().method() === "POST") {
      saves.push(route.request().postDataJSON());
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ok: true }) });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await installPdfTextFixture(page);

  await page.evaluate(() => {
    pdfState.annotations = [normalizeAnnotation({
      id: "draggable-sticky-note",
      type: "note",
      page: 8,
      x: 0.14,
      y: 0.2,
      w: 0.02,
      h: 0.02,
      color: "yellow",
      comment: "Drag me",
      quote: "",
    })];
    renderAllAnnotations();
    renderAnnotationList();
  });

  const marker = page.locator(".pdf-annotation-note[data-annotation-id='draggable-sticky-note']");
  const before = await marker.boundingBox();
  expect(before).toBeTruthy();

  await page.evaluate(({ startX, startY, endX, endY }) => {
    const item = document.querySelector(".pdf-annotation-note[data-annotation-id='draggable-sticky-note']");
    item.dispatchEvent(new PointerEvent("pointerdown", {
      bubbles: true,
      button: 0,
      pointerId: 1,
      clientX: startX,
      clientY: startY,
    }));
    window.dispatchEvent(new PointerEvent("pointermove", {
      bubbles: true,
      button: 0,
      pointerId: 1,
      clientX: endX,
      clientY: endY,
    }));
    window.dispatchEvent(new PointerEvent("pointerup", {
      bubbles: true,
      button: 0,
      pointerId: 1,
      clientX: endX,
      clientY: endY,
    }));
  }, {
    startX: before.x + before.width / 2,
    startY: before.y + before.height / 2,
    endX: before.x + before.width / 2 + 72,
    endY: before.y + before.height / 2 + 44,
  });

  await expect(page.locator("#annotationUndo")).toBeEnabled();
  await expect.poll(() => saves.length).toBe(1);

  const after = await marker.boundingBox();
  expect(after.x).toBeGreaterThan(before.x + 40);
  expect(after.y).toBeGreaterThan(before.y + 20);
  expect(saves[0]).toMatchObject({
    noteId: E2E_NOTE_ID,
    annotations: [expect.objectContaining({ id: "draggable-sticky-note", type: "note", page: 8 })],
  });
  expect(saves[0].annotations[0].x).toBeGreaterThan(0.14);
  expect(saves[0].annotations[0].y).toBeGreaterThan(0.2);

  await page.locator("#annotationUndo").click();
  const undone = await marker.boundingBox();
  expect(Math.abs(undone.x - before.x)).toBeLessThanOrEqual(3);
  expect(Math.abs(undone.y - before.y)).toBeLessThanOrEqual(3);
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

test("reader sends selected PDF text as chat context", async ({ page }) => {
  await openFixtureReader(page);
  const { requests } = await installAgentMocks(page);
  await installPdfTextFixture(page);
  await showAskPane(page);

  await page.evaluate(() => {
    const span = Array.from(document.querySelectorAll(".pdf-page[data-page='8'] .textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    span.scrollIntoView({ block: "center", inline: "center" });
    const range = document.createRange();
    range.selectNodeContents(span);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  });

  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected: 1 word");
  await expect(page.locator(".ask-selected-text-chip")).not.toContainText("stochastic");
  await expect(page.locator(".ask-selected-text-chip")).toHaveAttribute("data-selected-text-preview", /stochastic/);
  await expect(page.locator(".ask-selected-text-chip")).not.toContainText("p.");

  await page.locator("#readerChatInput").click();
  await page.keyboard.type("输入不会被选区抢走");
  await expect(page.locator("#readerChatInput")).toHaveValue("输入不会被选区抢走");
  await page.evaluate(() => {
    window.getSelection()?.removeAllRanges();
    document.dispatchEvent(new Event("selectionchange"));
  });
  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");
  await expect(page.locator(".ask-selected-text-chip")).toHaveAttribute("data-selected-text-preview", /stochastic/);
  await expect(page.locator(".pdf-selection-rect").first()).toBeVisible();
  await page.locator("#readerChatInput").dblclick();
  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");
  await expect(page.locator(".pdf-selection-rect").first()).toBeVisible();
  await page.locator("#readerChatInput").click({ clickCount: 3 });
  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");
  await expect(page.locator(".pdf-selection-rect").first()).toBeVisible();
  const chipHandle = await page.locator(".ask-selected-text-chip").elementHandle();
  await page.evaluate(() => {
    schedulePdfSelectionOverlayRender();
    schedulePdfSelectionOverlayRender();
  });
  await page.waitForTimeout(80);
  expect(await page.locator(".ask-selected-text-chip").evaluate((node, previous) => node === previous, chipHandle)).toBe(true);
  await page.locator("[data-selected-text-remove]").click();
  await expect(page.locator(".ask-selected-text-chip")).toHaveCount(0);
  await expect(page.locator(".pdf-selection-rect")).toHaveCount(0);

  await page.evaluate(() => {
    const span = Array.from(document.querySelectorAll(".pdf-page[data-page='8'] .textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    const range = document.createRange();
    range.selectNodeContents(span);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  });
  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");

  await page.locator(".pdf-page").first().dispatchEvent("pointerdown", { bubbles: true });
  await page.evaluate(() => {
    window.getSelection()?.removeAllRanges();
    document.dispatchEvent(new Event("selectionchange"));
  });
  await expect(page.locator(".ask-selected-text-chip")).toHaveCount(0);
  await expect(page.locator(".pdf-selection-rect")).toHaveCount(0);

  await page.evaluate(() => {
    document.activeElement?.blur?.();
    const span = Array.from(document.querySelectorAll(".pdf-page[data-page='8'] .textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    const range = document.createRange();
    range.selectNodeContents(span);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  });
  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");
  await page.locator("#readerChatInput").click();
  await page.locator("#readerChatInput").fill("解释我选中的这段");

  await page.evaluate(() => {
    document.activeElement?.blur?.();
    window.getSelection()?.removeAllRanges();
    document.dispatchEvent(new Event("selectionchange"));
  });
  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");

  await page.evaluate(() => {
    const span = Array.from(document.querySelectorAll(".pdf-page[data-page='8'] .textLayer span[role='presentation']"))
      .find((entry) => (entry.textContent || "").includes("stochastic"));
    const range = document.createRange();
    range.selectNodeContents(span);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  });
  await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");

  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.locator("#askPane")).toContainText("DeepSeek V4");
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].selectionText).toContain("stochastic");
  expect(requests[0].context.selectionText).toContain("stochastic");
  expect(requests[0].context.selection_text).toContain("stochastic");
  await expect(page.locator(".ask-user-selected-text-badge")).toContainText("Text selected: 1 word");
  await expect(page.locator(".ask-user-selected-text-badge")).not.toContainText("p.");
  await expect(page.locator(".ask-user-selected-text-badge")).toHaveAttribute("data-selected-text-preview", /stochastic/);
  await expect(page.locator(".ask-selected-text-chip")).toHaveCount(0);
});

test("reader highlight and underline annotations keep selected PDF text", async ({ page }) => {
  await openFixtureReader(page);
  await installPdfTextFixture(page);
  await showAskPane(page);

  for (const type of ["highlight", "underline"]) {
    await page.evaluate((annotationType) => {
      const pageElement = document.querySelector(".pdf-page[data-page='8']");
      const span = Array.from(pageElement.querySelectorAll(".textLayer span[role='presentation']"))
        .find((entry) => (entry.textContent || "").includes("stochastic"));
      span.scrollIntoView({ block: "center", inline: "center" });
      const range = document.createRange();
      range.selectNodeContents(span);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
      pdfState.mode = annotationType;
      finishSelectionAnnotation(pageElement, annotationType);
    }, type);

    await page.waitForFunction((annotationType) => (
      pdfState.annotations.some((entry) => entry.type === annotationType && entry.quote.includes("stochastic"))
    ), type);
    await expect(page.locator(".ask-selected-text-chip")).toContainText("Text selected");
    await expect(page.locator(".ask-selected-text-chip")).toHaveAttribute("data-selected-text-preview", /stochastic/);
    await expect(page.locator(".pdf-selection-rect").first()).toBeVisible();
    expect(await page.evaluate(() => window.getSelection()?.toString())).toContain("stochastic");

    await page.evaluate(() => {
      pdfState.annotations = [];
      renderAllAnnotations();
    });
  }
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
  await expect(page.getByRole("button", { name: /Generate file/ })).toHaveCount(0);
  await page.locator(".ask-tool-submenu-trigger", { hasText: "Generate file" }).hover();
  await page.getByRole("menuitemradio", { name: /Markdown/ }).click();
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
  await page.locator(".ask-tool-submenu-trigger", { hasText: "Generate file" }).hover();
  await page.getByRole("menuitemradio", { name: /Markdown/ }).click();
  await page.locator("[data-generation-mode-remove]").click();
  await askInput.fill("普通聊天");
  await page.getByRole("button", { name: "Send" }).click();
  expect(requests.at(-1).fileGeneration).toBeUndefined();
  expect(requests.at(-1).imageGeneration).toBeUndefined();
});

test("reader disables image generation for Codex Spark", async ({ page }) => {
  await ignoreMissingFavicon(page);
  await installReaderFixtures(page);
  await page.route("**/api/model/providers", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        defaultProvider: "codex-oauth",
        defaultModel: "gpt-5.3-codex-spark",
        modelConnectionConfigured: true,
        providers: [{
          name: "codex-oauth",
          displayName: "Codex OAuth",
          configured: true,
          ready: true,
          model: "gpt-5.3-codex-spark",
          selectedModel: "gpt-5.3-codex-spark",
          defaultModel: "gpt-5.5",
          capabilities: {
            supportsTools: true,
            supportsVision: true,
            supportsImageGeneration: true,
            supportsWebSearch: true,
          },
          models: [{
            value: "gpt-5.3-codex-spark",
            label: "GPT-5.3 Codex Spark",
            shortLabel: "5.3 spark",
            capabilities: {
              supportsTools: true,
              supportsVision: false,
              supportsImageGeneration: false,
              supportsWebSearch: false,
              supportsReasoningOff: false,
              imageInputMode: "unsupported",
            },
          }],
        }],
      }),
    });
  });

  await page.goto(`/reader.html?id=${E2E_NOTE_ID}`);
  await page.waitForFunction(() => typeof window.setAskPaneVisible === "function");
  await page.evaluate(() => window.setAskPaneVisible(true));
  await expect(page.locator("#readerLayout")).not.toHaveClass(/is-ask-pane-hidden/);
  await page.waitForFunction(() => typeof window.setReaderToolMenuOpen === "function");
  await page.evaluate(() => window.setReaderToolMenuOpen(true));
  await expect(page.locator("#readerToolPopover")).toBeVisible();
  const generateImage = page.locator("[data-tool-action='generate-image']");
  await expect(generateImage).toBeDisabled();
  await expect(generateImage).toHaveAttribute("title", /does not support image generation/);
  const addScreenshot = page.locator("[data-tool-action='add-screenshot']");
  await expect(addScreenshot).toBeDisabled();
  await expect(addScreenshot).toHaveAttribute("title", /does not support image input/);
  await generateImage.click({ force: true });
  await expect(page.locator("#readerAttachmentTray")).toBeHidden();
});
