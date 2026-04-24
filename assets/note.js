(function () {
  function slugify(text, index) {
    const slug = String(text || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "-")
      .replace(/^-+|-+$/g, "");
    return slug || `section-${index + 1}`;
  }

  function buildNoteMenu(root) {
    const scope = root || document;
    const body = scope.querySelector(".note-body");
    const menu = scope.querySelector("[data-note-menu]");
    const menuShell = scope.querySelector(".note-menu");
    if (!body || !menu || !menuShell) return;

    const headings = Array.from(body.querySelectorAll("h2, h3"));
    menu.innerHTML = "";
    menuShell.hidden = headings.length === 0;

    headings.forEach((heading, index) => {
      if (!heading.id) heading.id = slugify(heading.textContent, index);
      const link = document.createElement("a");
      link.href = `#${heading.id}`;
      link.className = `note-menu-link note-menu-link-${heading.tagName.toLowerCase()}`;
      link.textContent = heading.textContent.trim() || `Section ${index + 1}`;
      menu.appendChild(link);
    });
  }

  window.buildNoteMenu = buildNoteMenu;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => buildNoteMenu(document));
  } else {
    buildNoteMenu(document);
  }
}());
