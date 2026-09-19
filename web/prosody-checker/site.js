const routeTitles = {
  home: "诗矩 · 中文诗词创作空间",
  chat: "AI 对话 · 诗矩",
  prosody: "格律检测 · 诗矩",
  forum: "诗友论坛 · 诗矩",
};

const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);
const navLinks = [...document.querySelectorAll(".site-nav [data-route-link]")];
const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector(".site-nav");
const mainContent = document.querySelector("#main-content");
const siteStatus = document.querySelector("#site-status");
let statusTimer;

function announce(message) {
  window.clearTimeout(statusTimer);
  siteStatus.textContent = message;
  siteStatus.classList.add("is-visible");
  statusTimer = window.setTimeout(() => {
    siteStatus.classList.remove("is-visible");
    siteStatus.textContent = "";
  }, 2600);
}

function closeNavigation() {
  navToggle.setAttribute("aria-expanded", "false");
  siteNav.classList.remove("is-open");
}

function showRoute(route, options = {}) {
  const resolvedRoute = views.has(route) ? route : "home";
  for (const [name, view] of views) view.hidden = name !== resolvedRoute;
  for (const link of navLinks) {
    const isCurrent = link.dataset.routeLink === resolvedRoute;
    if (isCurrent) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.body.dataset.currentView = resolvedRoute;
  document.title = routeTitles[resolvedRoute];
  closeNavigation();
  if (options.scroll !== false) window.scrollTo({ top: 0, behavior: "auto" });
  if (options.focus) mainContent.focus({ preventScroll: true });
}

function routeFromHash() {
  return window.location.hash.slice(1).split("/")[0] || "home";
}

navToggle.addEventListener("click", () => {
  const open = navToggle.getAttribute("aria-expanded") !== "true";
  navToggle.setAttribute("aria-expanded", String(open));
  siteNav.classList.toggle("is-open", open);
});

document.querySelector(".site-header").addEventListener("keydown", (event) => {
  if (event.key === "Escape" && navToggle.getAttribute("aria-expanded") === "true") {
    closeNavigation();
    navToggle.focus();
  }
});

siteNav.addEventListener("click", (event) => {
  if (event.target.closest("a")) closeNavigation();
});

window.addEventListener("hashchange", () => {
  if (window.location.hash === "#main-content") return;
  showRoute(routeFromHash(), { focus: true });
});

document.querySelectorAll("[data-open-register]").forEach((button) => {
  button.addEventListener("click", () => {
    if (window.location.hash !== "#home") window.location.hash = "home";
    showRoute("home", { scroll: false });
    document.querySelector("#register").scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => document.querySelector("#register-phone").focus(), 350);
  });
});

document.querySelectorAll("[data-demo-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const labels = { login: "登录功能将在后续接入。", publish: "发帖功能将在后续接入。" };
    announce(labels[button.dataset.demoAction] ?? "此功能目前仅作样式展示。");
  });
});

const registerForm = document.querySelector("#register-form");
const registerPhone = document.querySelector("#register-phone");
const registerStatus = document.querySelector("#register-status");

document.querySelector("#send-code").addEventListener("click", () => {
  if (!registerPhone.value.trim()) {
    registerStatus.textContent = "请先输入手机号。";
    registerPhone.focus();
    return;
  }
  registerStatus.textContent = "样式演示：当前不会发送真实验证码。";
});

registerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  registerStatus.textContent = "注册流程尚未接入，当前仅展示表单样式。";
});

const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const chatThread = document.querySelector("#chat-thread");
const initialThreadMarkup = chatThread.innerHTML;

function appendMessage(text, role) {
  const article = document.createElement("article");
  article.className = `chat-message chat-message--${role}`;
  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "诗";
    article.append(avatar);
  }
  const content = document.createElement("div");
  content.className = "message-content";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  content.append(paragraph);
  article.append(content);
  chatThread.append(article);
  chatThread.scrollTop = chatThread.scrollHeight;
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) {
    chatInput.focus();
    return;
  }
  appendMessage(message, "user");
  chatInput.value = "";
  appendMessage("这是前端演示回复。后续接入生成逻辑后，诗矩会在这里继续与你推敲。", "assistant");
});

chatThread.addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (!button) return;
  chatInput.value = button.dataset.prompt;
  chatInput.focus();
});

document.querySelector("#new-chat").addEventListener("click", () => {
  chatThread.innerHTML = initialThreadMarkup;
  chatInput.value = "";
  chatInput.focus();
});

document.querySelectorAll(".conversation-list button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".conversation-list button").forEach((item) => item.removeAttribute("aria-current"));
    button.setAttribute("aria-current", "true");
    announce("历史对话目前仅作列表样式展示。");
  });
});

document.querySelectorAll(".forum-categories button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".forum-categories button").forEach((item) => item.setAttribute("aria-pressed", "false"));
    button.setAttribute("aria-pressed", "true");
    announce(`已切换到“${button.textContent}”样式状态。`);
  });
});

function setupInkLandscape() {
  const canvas = document.querySelector("#ink-landscape");
  const hero = canvas.closest(".home-hero");
  const context = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let offset = 0;
  let frame;

  function seeded(index) {
    const value = Math.sin(index * 931.17 + 17.31) * 43758.5453;
    return value - Math.floor(value);
  }

  function drawMountain(width, height, base, amplitude, alpha, phase) {
    context.beginPath();
    context.moveTo(-40, height);
    context.lineTo(-40, base);
    for (let x = -40; x <= width + 40; x += 36) {
      const wave = Math.sin((x + phase + offset) / 118) * amplitude;
      const detail = Math.sin((x + phase) / 43) * amplitude * 0.26;
      context.lineTo(x, base - wave - detail);
    }
    context.lineTo(width + 40, height);
    context.closePath();
    context.fillStyle = `rgba(35, 34, 31, ${alpha})`;
    context.fill();
  }

  function draw() {
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#eee8d8";
    context.fillRect(0, 0, width, height);

    context.lineWidth = 0.55;
    for (let index = 0; index < Math.min(700, Math.round(width * height / 1500)); index += 1) {
      const x = seeded(index) * width;
      const y = seeded(index + 900) * height;
      const length = 3 + seeded(index + 1700) * 13;
      context.strokeStyle = `rgba(82, 72, 56, ${0.018 + seeded(index + 2100) * 0.022})`;
      context.beginPath();
      context.moveTo(x, y);
      context.lineTo(x + length, y + seeded(index + 3300) * 2 - 1);
      context.stroke();
    }

    drawMountain(width, height, height * 0.58, height * 0.12, 0.09, 30);
    drawMountain(width, height, height * 0.69, height * 0.15, 0.14, 170);
    drawMountain(width, height, height * 0.82, height * 0.11, 0.21, 315);

    context.strokeStyle = "rgba(32, 31, 29, 0.23)";
    context.lineCap = "round";
    for (let index = 0; index < 7; index += 1) {
      const y = height * (0.79 + index * 0.022);
      context.lineWidth = 1 + index * 0.55;
      context.beginPath();
      context.moveTo(width * 0.47 + offset * 0.5, y);
      context.bezierCurveTo(width * 0.62, y - 11, width * 0.78, y + 8, width * 1.04, y - 4);
      context.stroke();
    }
  }

  const observer = new ResizeObserver(draw);
  observer.observe(hero);

  hero.addEventListener("pointermove", (event) => {
    if (reduceMotion.matches) return;
    const rect = hero.getBoundingClientRect();
    offset = ((event.clientX - rect.left) / rect.width - 0.5) * 16;
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(draw);
  });

  hero.addEventListener("pointerleave", () => {
    offset = 0;
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(draw);
  });

  draw();
}

showRoute(routeFromHash(), { scroll: false });
setupInkLandscape();
