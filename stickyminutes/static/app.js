// Extras only: every page works without this file.

// The Appearance choice on the Settings page. theme.js applies it on every page.
function setUpTheme() {
  const section = document.querySelector("[data-theme-settings]");
  if (!section) return;
  const root = document.documentElement;
  section.hidden = false;
  section.querySelectorAll('input[name="theme"]').forEach((choice) => {
    choice.checked = choice.value === (root.dataset.theme || "system");
    choice.addEventListener("change", () => {
      try {
        if (choice.value === "system") {
          delete root.dataset.theme;
          localStorage.removeItem("stickyminutes-theme");
        } else {
          root.dataset.theme = choice.value;
          localStorage.setItem("stickyminutes-theme", choice.value);
        }
      } catch (error) {
        // Storage can be blocked. The theme still changes for this page.
      }
    });
  });
}

// The ☰ button on phones.
function setUpMenu() {
  const button = document.querySelector("[data-menu-button]");
  const menu = document.getElementById(button && button.getAttribute("aria-controls"));
  if (!button || !menu) return;
  button.hidden = false;
  const setOpen = (open) => {
    button.setAttribute("aria-expanded", open);
    menu.classList.toggle("is-open", open);
  };
  button.addEventListener("click", () => setOpen(button.getAttribute("aria-expanded") !== "true"));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
}

// <details> menus (the account menu) close on an outside click or Escape.
function setUpPopovers() {
  const menus = () => document.querySelectorAll("details[data-popover][open]");
  document.addEventListener("click", (event) => {
    menus().forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    menus().forEach((menu) => {
      menu.open = false;
      menu.querySelector("summary").focus();
    });
  });
}

// "Are you sure?" in the app's own look (the browser's confirm box can't be styled).
// Answers true or false. Its main button says what the action does ("Delete meeting", "Run again").
let confirmDialog = null;
function ask(question, action, style) {
  const danger = style === "button-danger";
  if (typeof HTMLDialogElement !== "function") return Promise.resolve(confirm(question));
  if (!confirmDialog) {
    confirmDialog = document.createElement("dialog");
    confirmDialog.className = "confirm-dialog";
    confirmDialog.innerHTML =
      '<form method="dialog"><p class="confirm-question" id="confirm-question"></p>' +
      '<div class="form-actions"><button class="button button-quiet" value="cancel">Cancel</button>' +
      '<button class="button" value="ok" data-confirm-ok></button></div></form>';
    confirmDialog.setAttribute("aria-labelledby", "confirm-question");
    // A click on the dimmed page around it is a Cancel.
    confirmDialog.addEventListener("click", (event) => {
      if (event.target === confirmDialog) confirmDialog.close("cancel");
    });
    document.body.append(confirmDialog);
  }
  const ok = confirmDialog.querySelector("[data-confirm-ok]");
  confirmDialog.querySelector(".confirm-question").textContent = question;
  ok.textContent = action || "OK";
  ok.className = style ? `button ${style}` : "button";
  confirmDialog.classList.toggle("is-danger", danger);
  confirmDialog.returnValue = "";
  confirmDialog.showModal();
  // Deleting: Cancel has the focus, so Enter is the safe choice. Otherwise the action has it.
  (danger ? confirmDialog.querySelector('[value="cancel"]') : ok).focus();
  return new Promise((resolve) => {
    confirmDialog.addEventListener("close", () => resolve(confirmDialog.returnValue === "ok"), { once: true });
  });
}

// The words and colour of the button that was pressed, for the dialog's own button:
// red for a delete; otherwise the usual main button.
function actionOf(button) {
  const styles = ["button-danger"];
  return {
    action: button ? button.textContent.replace(/\s+/g, " ").trim() : "",
    style: (button && styles.find((style) => button.classList.contains(style))) || "",
  };
}

function setUpConfirm() {
  const approved = new WeakSet();
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      if (approved.has(form)) return approved.delete(form);
      event.preventDefault();
      const submitter = event.submitter || form.querySelector('[type="submit"]');
      const { action, style } = actionOf(submitter);
      if (await ask(form.dataset.confirm, action, style)) {
        approved.add(form);
        form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
      }
    });
  });
  // One button of a form that needs asking first (Delete, beside Save).
  document.querySelectorAll("button[data-confirm-button]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      if (approved.has(button)) return approved.delete(button);
      event.preventDefault();
      const { action, style } = actionOf(button);
      if (await ask(button.dataset.confirmButton, action, style)) {
        approved.add(button);
        button.click();
      }
    });
  });
}

// A select that saves itself (a role, a filter): no Save button needed.
function setUpAutoSubmit() {
  document.querySelectorAll("[data-auto-submit]").forEach((control) => {
    const button = control.form.querySelector("[data-auto-submit-button]");
    if (button) button.hidden = true;
    control.addEventListener("change", () => control.form.requestSubmit());
  });
}

// The Copy button beside a link.
function setUpCopy() {
  document.querySelectorAll("[data-copy]").forEach((button) => {
    const field = document.getElementById(button.dataset.copy);
    button.hidden = false;
    button.addEventListener("click", async () => {
      field.select();
      try {
        await navigator.clipboard.writeText(field.value);
      } catch (error) {
        document.execCommand("copy");
      }
      button.textContent = "Copied";
      setTimeout(() => (button.textContent = "Copy"), 1500);
    });
  });
}

// Messages fade away after a few seconds (errors stay; data-toast-wait sets a longer time);
// the clock starts again while the mouse or keyboard is on a message. Every message can be closed.
function setUpToasts() {
  const leave = (toast) => {
    toast.classList.add("is-leaving");
    setTimeout(() => toast.remove(), 400);
  };
  document.querySelectorAll(".toast").forEach((toast) => {
    const close = toast.querySelector("[data-toast-close]");
    close.hidden = false;
    close.addEventListener("click", () => leave(toast));
    if (!toast.hasAttribute("data-toast-fade")) return;
    const wait = Number(toast.dataset.toastWait) || 6000;
    let timer = setTimeout(() => leave(toast), wait);
    const hold = () => clearTimeout(timer);
    const resume = () => {
      if (toast.matches(":hover") || toast.contains(document.activeElement)) return;
      clearTimeout(timer);
      timer = setTimeout(() => leave(toast), 4000);
    };
    toast.addEventListener("mouseenter", hold);
    toast.addEventListener("focusin", hold);
    toast.addEventListener("mouseleave", resume);
    toast.addEventListener("focusout", () => setTimeout(resume));
  });
}

// A Save button sleeps (grey) until something in its form changes.
function setUpWatchChanges() {
  document.querySelectorAll("button[data-watch-changes]").forEach((button) => {
    const form = button.form;
    if (!form) return;
    button.classList.add("is-idle");
    const wake = () => button.classList.remove("is-idle");
    form.addEventListener("input", wake);
    form.addEventListener("change", wake);
  });
}

// While a summary runs, ask the server how it is going every 2 seconds; reload when it is done.
// (Without JavaScript the page says to reload it.)
function setUpStatusWatch() {
  const box = document.querySelector("[data-status-url]");
  if (!box) return;
  const words = box.querySelector("[data-status-words]");
  let misses = 0;
  const check = async () => {
    try {
      const response = await fetch(box.dataset.statusUrl, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(String(response.status));
      const state = await response.json();
      misses = 0;
      if (state.finished) return window.location.reload();
      if (words && state.attempts > 1) words.textContent = `Checking and fixing the notes (try ${state.attempts})...`;
    } catch (error) {
      misses += 1; // a lost connection: keep asking, a little slower
    }
    setTimeout(check, misses ? 5000 : 2000);
  };
  setTimeout(check, 2000);
}

// An evidence chip ("Line 12") lights up that transcript line and scrolls to it.
function setUpLineLinks() {
  document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-line-link]");
    if (!link) return;
    const line = document.getElementById(`line-${link.dataset.lineLink}`);
    if (!line) return;
    event.preventDefault();
    document.querySelectorAll(".lines li.is-lit").forEach((lit) => lit.classList.remove("is-lit"));
    line.classList.add("is-lit");
    line.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    history.replaceState(null, "", `#line-${link.dataset.lineLink}`);
  });
}

// Startup: every part looks for its own elements and does nothing if they aren't on the page.
const setUps = [setUpToasts, setUpWatchChanges, setUpTheme, setUpMenu, setUpPopovers, setUpConfirm,
  setUpAutoSubmit, setUpCopy, setUpStatusWatch, setUpLineLinks];
document.addEventListener("DOMContentLoaded", () => setUps.forEach((setUp) => setUp()));
