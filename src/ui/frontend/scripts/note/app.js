(function () {
  function slugify(text, index) {
    const slug = String(text || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9\u4e00-\u9fff]+/gi, "-")
      .replace(/^-+|-+$/g, "");
    return slug || `section-${index + 1}`;
  }

  function headingLevel(heading) {
    return Number(heading.tagName.replace("H", ""));
  }

  function headingText(heading) {
    const clone = heading.cloneNode(true);
    clone.querySelectorAll(".note-heading-toggle").forEach((button) => button.remove());
    return clone.textContent.trim();
  }

  function sectionNodesForHeading(heading) {
    const level = headingLevel(heading);
    const nodes = [];
    let sibling = heading.nextElementSibling;
    while (sibling) {
      if (/^H[2-4]$/.test(sibling.tagName) && headingLevel(sibling) <= level) break;
      nodes.push(sibling);
      sibling = sibling.nextElementSibling;
    }
    return nodes;
  }

  function setHeadingCollapsed(heading, collapsed) {
    heading.classList.toggle("is-collapsed", collapsed);
    heading.setAttribute("aria-expanded", collapsed ? "false" : "true");
    sectionNodesForHeading(heading).forEach((node) => {
      node.hidden = collapsed;
    });
  }

  function setupCollapsibleHeadings(headings) {
    headings.forEach((heading) => {
      if (!heading.classList.contains("note-heading")) {
        heading.classList.add("note-heading");
        heading.setAttribute("aria-expanded", "true");
      }

      if (!heading.querySelector(".note-heading-toggle")) {
        const button = document.createElement("button");
        button.className = "note-heading-toggle";
        button.type = "button";
        button.setAttribute("aria-label", `Toggle ${headingText(heading) || "section"}`);
        button.setAttribute("aria-hidden", "true");
        heading.append(button);
      }

      if (!heading.dataset.collapseReady) {
        heading.addEventListener("click", (event) => {
          if (event.target.closest("a")) return;
          setHeadingCollapsed(heading, !heading.classList.contains("is-collapsed"));
        });
        heading.dataset.collapseReady = "true";
      }
    });
  }

  function buildNoteMenu(root) {
    const scope = root || document;
    const body = scope.querySelector(".note-body");
    const menu = scope.querySelector("[data-note-menu]");
    const menuShell = scope.querySelector(".note-menu");
    if (!body || !menu || !menuShell) return;

    if (!menuShell.querySelector(".note-menu-tabs")) {
      const tabs = document.createElement("div");
      tabs.className = "note-menu-tabs";
      menuShell.prepend(tabs);
    }

    if (!menuShell.querySelector(".note-menu-collapse")) {
      const collapse = document.createElement("button");
      collapse.className = "note-menu-collapse";
      collapse.type = "button";
      collapse.setAttribute("aria-label", "Toggle note outline");
      collapse.textContent = "☰";
      collapse.addEventListener("click", () => {
        menuShell.classList.toggle("is-open");
      });
      menuShell.querySelector(".note-menu-tabs").appendChild(collapse);
    }

    if (!menuShell.dataset.outlineReady) {
      document.addEventListener("click", (event) => {
        if (!event.target.closest(".note-menu")) menuShell.classList.remove("is-open");
      });
      menuShell.dataset.outlineReady = "true";
    }

    const headings = Array.from(body.querySelectorAll("h2, h3, h4"));
    const collapse = menuShell.querySelector(".note-menu-collapse");
    menu.innerHTML = "";
    menuShell.hidden = false;
    menu.hidden = headings.length === 0;
    menuShell.classList.toggle("has-headings", headings.length > 0);
    if (collapse) {
      collapse.disabled = headings.length === 0;
      collapse.setAttribute("aria-disabled", headings.length === 0 ? "true" : "false");
      collapse.title = headings.length > 0 ? "Open outline" : "";
    }
    if (headings.length === 0) menuShell.classList.remove("is-open");

    headings.forEach((heading, index) => {
      const title = headingText(heading);
      if (!heading.id) heading.id = slugify(title, index);
      const link = document.createElement("a");
      link.href = `#${heading.id}`;
      link.className = `note-menu-link note-menu-link-${heading.tagName.toLowerCase()}`;
      link.textContent = title || `Section ${index + 1}`;
      menu.appendChild(link);
    });

    setupCollapsibleHeadings(headings);
  }

  window.buildNoteMenu = buildNoteMenu;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => buildNoteMenu(document));
  } else {
    buildNoteMenu(document);
  }
}());
