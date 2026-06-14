(function () {
  const ALL_CATEGORY_ID = "all";
  const UNCATEGORIZED_ID = "uncategorized";

  function normalizeText(value) {
    return String(value || "").trim();
  }

  function normalizeTags(value) {
    if (!Array.isArray(value)) return [];
    return value.map((tag) => normalizeText(tag)).filter(Boolean);
  }

  function normalizeResourceHref(value) {
    const href = normalizeText(value);
    if (!href) return "";
    if (href.startsWith("resources/")) return href;
    if (href.startsWith("Papers/") || href.startsWith("Paper-html/") || href.startsWith("Paper-annotations/")) {
      return `resources/${href}`;
    }
    return href;
  }

  function finiteNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function defaultUniqueId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  function sanitizeLibrary(rawLibrary, options = {}) {
    const uniqueId = typeof options.uniqueId === "function" ? options.uniqueId : defaultUniqueId;
    const raw = rawLibrary && typeof rawLibrary === "object" ? rawLibrary : {};
    const rawCategories = Array.isArray(raw.categories) ? raw.categories : [];
    const categoryMap = new Map();

    rawCategories.forEach((category, index) => {
      const id = normalizeText(category.id) || uniqueId("category");
      if (categoryMap.has(id)) return;
      categoryMap.set(id, {
        id,
        name: normalizeText(category.name) || "Untitled",
        parentId: normalizeText(category.parentId) || null,
        order: finiteNumber(category.order, index),
        system: Boolean(category.system)
      });
    });

    categoryMap.set(ALL_CATEGORY_ID, {
      id: ALL_CATEGORY_ID,
      name: "All Notes",
      parentId: null,
      order: 0,
      system: true
    });
    categoryMap.set(UNCATEGORIZED_ID, {
      id: UNCATEGORIZED_ID,
      name: "Uncategorized",
      parentId: null,
      order: 1,
      system: true
    });

    const categories = Array.from(categoryMap.values()).map((category) => {
      if (category.id === ALL_CATEGORY_ID) return { ...category, parentId: null, order: 0, system: true };
      if (category.id === UNCATEGORIZED_ID) return { ...category, parentId: null, order: 1, system: true };
      return category;
    });

    const validIds = new Set(categories.map((category) => category.id));
    categories.forEach((category) => {
      if (category.parentId && !validIds.has(category.parentId)) category.parentId = null;
      if (category.parentId === ALL_CATEGORY_ID || category.parentId === UNCATEGORIZED_ID) category.parentId = null;
    });

    const topLevelIds = new Set(categories.filter((category) => category.parentId === null).map((category) => category.id));
    categories.forEach((category) => {
      if (category.parentId && !topLevelIds.has(category.parentId)) category.parentId = null;
    });

    const childMap = new Map();
    categories.forEach((category) => {
      const key = category.parentId || "root";
      if (!childMap.has(key)) childMap.set(key, []);
      childMap.get(key).push(category);
    });

    childMap.forEach((group) => {
      group.sort((left, right) => left.order - right.order || left.name.localeCompare(right.name));
      group.forEach((category, index) => {
        if (category.parentId === null) {
          if (category.id === ALL_CATEGORY_ID) category.order = 0;
          else if (category.id === UNCATEGORIZED_ID) category.order = 1;
          else category.order = Math.max(index, 2);
        } else {
          category.order = index;
        }
      });
    });

    const parentIdsWithChildren = new Set(categories.filter((category) => category.parentId).map((category) => category.parentId));
    const leafIds = new Set(categories.filter((category) => !parentIdsWithChildren.has(category.id)).map((category) => category.id));
    const rawNotes = Array.isArray(raw.notes) ? raw.notes : [];
    const notes = rawNotes.map((note, index) => {
      const requestedCategoryId = normalizeText(note.categoryId);
      return {
        id: normalizeText(note.id) || uniqueId(`note-${index + 1}`),
        title: normalizeText(note.title) || "Untitled Note",
        href: normalizeResourceHref(note.href),
        htmlHref: normalizeResourceHref(note.htmlHref),
        pdfStorageKey: normalizeText(note.pdfStorageKey),
        sourceUrl: normalizeText(note.sourceUrl),
        date: normalizeText(note.date),
        order: finiteNumber(note.order, index),
        categoryId: leafIds.has(requestedCategoryId) ? requestedCategoryId : UNCATEGORIZED_ID,
        venue: normalizeText(note.venue),
        summary: normalizeText(note.summary),
        tags: normalizeTags(note.tags)
      };
    }).filter((note) => note.id);

    return { categories, notes };
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function getApiUrl(path) {
    return window.location.protocol === "file:"
      ? `http://localhost:8765${path}`
      : path;
  }

  window.PaperNotesModel = {
    ALL_CATEGORY_ID,
    UNCATEGORIZED_ID,
    normalizeText,
    normalizeTags,
    normalizeResourceHref,
    sanitizeLibrary,
    escapeHtml,
    getApiUrl
  };
}());
