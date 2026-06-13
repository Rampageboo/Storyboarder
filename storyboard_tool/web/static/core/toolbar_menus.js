function closeToolbarMenus(except = null) {
  document.querySelectorAll("details.toolbar-menu[open]").forEach((details) => {
    if (details !== except) details.open = false;
  });
}

function bindToolbarMenus() {
  const menus = document.querySelectorAll("details.toolbar-menu");
  if (!menus.length) return;

  menus.forEach((details) => {
    details.addEventListener("toggle", () => {
      if (details.open) closeToolbarMenus(details);
    });
  });

  document.addEventListener(
    "click",
    (event) => {
      const menu = event.target.closest("details.toolbar-menu");
      if (menu) {
        const action = event.target.closest(".toolbar-menu-panel button, .toolbar-menu-panel .theme-option");
        if (action) {
          window.setTimeout(() => {
            menu.open = false;
          }, 0);
        }
        return;
      }
      closeToolbarMenus();
    },
    true
  );

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeToolbarMenus();
  });

  window.addEventListener("blur", () => closeToolbarMenus());
}
