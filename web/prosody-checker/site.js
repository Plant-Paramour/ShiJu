import { evaluateGeneratedPoem } from "./prosody-evaluation.js?v=1";

const routeTitles = {
  home: "诗矩 · 中文诗词创作空间",
  chat: "AI 对话 · 诗矩",
  prosody: "格律检测 · 诗矩",
  forum: "诗友论坛 · 诗矩",
  "forum-thread": "主题讨论 · 诗矩",
  "forum-compose": "发布话题 · 诗矩",
  notifications: "通知 · 诗矩",
  "public-profile": "用户主页 · 诗矩",
  profile: "个人中心 · 诗矩",
  admin: "管理后台 · 诗矩",
};

const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);
const navLinks = [...document.querySelectorAll(".site-nav [data-route-link]")];
const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector(".site-nav");
const drawerBackdrop = document.querySelector("#drawer-backdrop");
const leftDrawer = document.querySelector("#site-left-drawer");
const rightDrawer = document.querySelector("#site-right-drawer");
const mainContent = document.querySelector("#main-content");
const siteStatus = document.querySelector("#site-status");
let statusTimer;
let authToken = localStorage.getItem("shiju_token") || "";
let currentUser = null;
let currentConversationId = null;
const activeEvaluations = new Map();
const failedEvaluations = new Set();
const prosodyInspector = document.querySelector("#prosody-inspector");
const prosodyInspectorBody = document.querySelector("#prosody-inspector-body");

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
  closeDrawers();
}

function closeDrawers() {
  for (const drawer of [leftDrawer, rightDrawer]) {
    drawer?.classList.remove("is-open");
    drawer?.setAttribute("aria-hidden", "true");
  }
  drawerBackdrop?.classList.remove("is-visible");
  if (drawerBackdrop) drawerBackdrop.hidden = true;
  navToggle?.setAttribute("aria-expanded", "false");
  document.body.classList.remove("has-open-drawer");
}

function openDrawer(drawer) {
  if (!drawer) return;
  closeDrawers();
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  if (drawer === leftDrawer) navToggle?.setAttribute("aria-expanded", "true");
  document.body.classList.add("has-open-drawer");
  if (drawerBackdrop) {
    drawerBackdrop.hidden = false;
    requestAnimationFrame(() => drawerBackdrop.classList.add("is-visible"));
  }
  drawer.querySelector("[data-drawer-close]")?.focus();
}

function showRoute(route, options = {}) {
  const resolvedRoute = route === "home" && currentUser ? "chat" : (views.has(route) ? route : "home");
  if (route === "home" && currentUser && window.location.hash !== "#chat") window.history.replaceState(null, "", "#chat");
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
  if (resolvedRoute === "profile" && currentUser) loadProfileData();
  if (resolvedRoute === "forum") loadForumData();
  if (resolvedRoute === "forum-thread") loadThreadPage();
  if (resolvedRoute === "forum-compose") loadComposePage();
  if (resolvedRoute === "notifications") loadNotifications();
  if (resolvedRoute === "public-profile") loadPublicProfile();
  if (resolvedRoute === "admin") loadAdminData();
  if (!prosodyInspector.hidden) closeProsodyInspector();
}

function routeFromHash() {
  const parts = window.location.hash.slice(1).split("/");
  if (parts[0] === "forum" && parts[1] === "thread") return "forum-thread";
  if (parts[0] === "forum" && parts[1] === "compose") return "forum-compose";
  if (parts[0] === "user" && parts[1]) return "public-profile";
  return parts[0] || "home";
}

navToggle.addEventListener("click", () => {
  const open = leftDrawer.classList.contains("is-open");
  if (open) closeDrawers();
  else openDrawer(leftDrawer);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && (navToggle.getAttribute("aria-expanded") === "true" || leftDrawer.classList.contains("is-open") || rightDrawer.classList.contains("is-open"))) {
    closeNavigation();
  }
});

siteNav.addEventListener("click", (event) => {
  if (event.target.closest("a")) closeNavigation();
});

document.querySelectorAll("[data-drawer-close]").forEach((button) => button.addEventListener("click", closeDrawers));
drawerBackdrop?.addEventListener("click", closeDrawers);
document.querySelectorAll("[data-drawer-route]").forEach((link) => link.addEventListener("click", () => closeDrawers()));

document.querySelector("#login-button").addEventListener("click", () => {
  if (currentUser) {
    loadDrawerNotifications();
    openDrawer(rightDrawer);
    return;
  }
  openDrawer(rightDrawer);
});

document.querySelectorAll("[data-profile-drawer-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!currentUser) {
      closeDrawers();
      requireLogin();
      return;
    }
    const tab = button.dataset.profileDrawerTab;
    document.querySelectorAll("[data-profile-tab]").forEach((item) => item.classList.toggle("is-active", item.dataset.profileTab === tab));
    document.querySelectorAll("[data-profile-panel]").forEach((panel) => { panel.hidden = panel.dataset.profilePanel !== tab; });
    closeDrawers();
    window.location.hash = "profile";
  });
});
document.querySelector("#drawer-login-action")?.addEventListener("click", () => {
  closeDrawers();
  document.querySelector("#login-dialog").showModal();
  document.querySelector("#login-username").focus();
});
document.querySelector("#drawer-logout-action")?.addEventListener("click", () => { closeDrawers(); logout(); });

window.addEventListener("hashchange", () => {
  if (window.location.hash === "#main-content") return;
  showRoute(routeFromHash(), { focus: true });
});

document.querySelectorAll("[data-open-register]").forEach((button) => {
  button.addEventListener("click", () => {
    if (document.querySelector("#login-dialog").open) document.querySelector("#login-dialog").close();
    if (window.location.hash !== "#home") window.location.hash = "home";
    showRoute("home", { scroll: false });
    document.querySelector("#register").scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => document.querySelector("#register-phone").focus(), 350);
  });
});

document.querySelectorAll("[data-demo-action]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.demoAction === "login") {
      document.querySelector("#login-dialog").showModal();
      document.querySelector("#login-username").focus();
      return;
    }
    if (button.dataset.demoAction === "publish") openThreadDialog();
  });
});

document.querySelector("#login-cancel").addEventListener("click", () => document.querySelector("#login-dialog").close());
document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.querySelector("#login-status");
  status.textContent = "登录中……";
  try {
    const payload = await apiFetch("/v1/auth/login", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ username: document.querySelector("#login-username").value.trim(), password: document.querySelector("#login-password").value }),
    });
    authGeneration++;
    authToken = payload.token;
    currentUser = payload.user;
    localStorage.setItem("shiju_token", authToken);
    updateAuthUi();
    document.querySelector("#login-dialog").close();
    status.textContent = "";
    await loadConversations({ restore: true });
    await loadProfileData();
    if (routeFromHash() === "home") window.location.hash = "chat";
    announce(`欢迎回来，${currentUser.display_name}`);
  } catch (error) { status.textContent = error.message; }
});
async function logout() {
  const buttons = [document.querySelector("#logout-button"), document.querySelector("#profile-logout-button")].filter(Boolean);
  buttons.forEach((button) => { button.disabled = true; });
  try { await apiFetch("/v1/auth/logout", { method: "POST" }); } catch { /* local token is still cleared */ }
  clearJobProgressPolls();
  clearConversationRefresh();
  authToken = ""; currentUser = null; currentConversationId = null; chatSessionId = null; profilePoems = []; profileCollections = [];
  localStorage.removeItem("shiju_token"); resetAuthenticatedUi(); updateAuthUi(); window.location.hash = "home"; announce("已退出登录。");
  buttons.forEach((button) => { button.disabled = false; });
}

document.querySelector("#logout-button").addEventListener("click", logout);

const registerForm = document.querySelector("#register-form");
const registerPhone = document.querySelector("#register-phone");
const registerPassword = document.querySelector("#register-password");
const registerStatus = document.querySelector("#register-status");

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  registerStatus.textContent = "注册中……";
  try {
    const payload = await apiFetch("/v1/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: registerPhone.value.trim(), password: registerPassword.value }) });
    authGeneration++; authToken = payload.token; currentUser = payload.user; localStorage.setItem("shiju_token", authToken); updateAuthUi(); await loadProfileData(); registerStatus.textContent = "注册成功"; window.location.hash = "chat"; announce(`欢迎加入，${currentUser.display_name}`);
  } catch (error) { registerStatus.textContent = error.message; }
});

document.querySelector("#profile-logout-button")?.addEventListener("click", logout);

const avatarCropDialog = document.querySelector("#avatar-crop-dialog");
const avatarCropForm = document.querySelector("#avatar-crop-form");
const avatarCropCanvas = document.querySelector("#avatar-crop-canvas");
const avatarCropZoom = document.querySelector("#avatar-crop-zoom");
const avatarCropZoomValue = document.querySelector("#avatar-crop-zoom-value");
const avatarCropImage = new Image();
const avatarCropState = { objectUrl: "", file: null, centerX: 0, centerY: 0, pointerId: null, lastX: 0, lastY: 0 };

function avatarCropBounds() {
  const zoom = Number(avatarCropZoom.value) || 1;
  const sourceSize = Math.min(avatarCropImage.naturalWidth, avatarCropImage.naturalHeight) / zoom;
  return {
    zoom,
    sourceSize,
    minX: sourceSize / 2,
    maxX: avatarCropImage.naturalWidth - sourceSize / 2,
    minY: sourceSize / 2,
    maxY: avatarCropImage.naturalHeight - sourceSize / 2,
  };
}

function clampAvatarCropCenter() {
  const bounds = avatarCropBounds();
  avatarCropState.centerX = Math.min(bounds.maxX, Math.max(bounds.minX, avatarCropState.centerX || avatarCropImage.naturalWidth / 2));
  avatarCropState.centerY = Math.min(bounds.maxY, Math.max(bounds.minY, avatarCropState.centerY || avatarCropImage.naturalHeight / 2));
}

function drawAvatarCrop() {
  if (!avatarCropImage.naturalWidth) return;
  clampAvatarCropCenter();
  const { sourceSize } = avatarCropBounds();
  const context = avatarCropCanvas.getContext("2d");
  context.clearRect(0, 0, avatarCropCanvas.width, avatarCropCanvas.height);
  context.imageSmoothingQuality = "high";
  context.drawImage(avatarCropImage, avatarCropState.centerX - sourceSize / 2, avatarCropState.centerY - sourceSize / 2, sourceSize, sourceSize, 0, 0, avatarCropCanvas.width, avatarCropCanvas.height);
  avatarCropZoomValue.textContent = `${Math.round(Number(avatarCropZoom.value) * 100)}%`;
}

function closeAvatarCrop() {
  if (avatarCropDialog.open) avatarCropDialog.close();
  if (avatarCropState.objectUrl) URL.revokeObjectURL(avatarCropState.objectUrl);
  avatarCropState.objectUrl = ""; avatarCropState.file = null; avatarCropImage.removeAttribute("src");
}

document.querySelector("#profile-avatar-input")?.addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  const status = document.querySelector("#profile-status");
  if (!file) return;
  if (![/^image\/jpeg$/, /^image\/png$/, /^image\/webp$/].some((pattern) => pattern.test(file.type)) || file.size > 2 * 1024 * 1024) {
    status.textContent = "请选择 2MB 以内的 JPG、PNG 或 WebP 图片。"; event.target.value = ""; return;
  }
  closeAvatarCrop();
  avatarCropState.file = file;
  avatarCropState.objectUrl = URL.createObjectURL(file);
  avatarCropImage.onload = () => { avatarCropState.centerX = avatarCropImage.naturalWidth / 2; avatarCropState.centerY = avatarCropImage.naturalHeight / 2; avatarCropZoom.value = "1"; drawAvatarCrop(); avatarCropDialog.showModal(); };
  avatarCropImage.onerror = () => { status.textContent = "图片无法读取，请重新选择。"; closeAvatarCrop(); };
  avatarCropImage.src = avatarCropState.objectUrl;
  event.target.value = "";
});

avatarCropZoom?.addEventListener("input", drawAvatarCrop);
avatarCropCanvas?.addEventListener("pointerdown", (event) => { avatarCropState.pointerId = event.pointerId; avatarCropState.lastX = event.clientX; avatarCropState.lastY = event.clientY; avatarCropCanvas.setPointerCapture(event.pointerId); });
avatarCropCanvas?.addEventListener("pointermove", (event) => {
  if (avatarCropState.pointerId !== event.pointerId) return;
  const bounds = avatarCropBounds(); const rect = avatarCropCanvas.getBoundingClientRect();
  avatarCropState.centerX -= (event.clientX - avatarCropState.lastX) * bounds.sourceSize / rect.width;
  avatarCropState.centerY -= (event.clientY - avatarCropState.lastY) * bounds.sourceSize / rect.height;
  avatarCropState.lastX = event.clientX; avatarCropState.lastY = event.clientY; drawAvatarCrop();
});
avatarCropCanvas?.addEventListener("pointerup", (event) => { if (avatarCropState.pointerId === event.pointerId) avatarCropState.pointerId = null; });
avatarCropCanvas?.addEventListener("pointercancel", () => { avatarCropState.pointerId = null; });
document.querySelector("#avatar-crop-close")?.addEventListener("click", closeAvatarCrop);
document.querySelector("#avatar-crop-cancel")?.addEventListener("click", closeAvatarCrop);
avatarCropDialog?.addEventListener("cancel", closeAvatarCrop);
avatarCropForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!avatarCropState.file || !avatarCropImage.naturalWidth) return;
  const status = document.querySelector("#profile-status"); const confirm = document.querySelector("#avatar-crop-confirm");
  confirm.disabled = true; status.textContent = "头像上传中……";
  try {
    const blob = await new Promise((resolve, reject) => avatarCropCanvas.toBlob((value) => value ? resolve(value) : reject(new Error("裁剪失败，请重试。")), "image/jpeg", 0.9));
    currentUser = await apiFetch("/v1/profile/me/avatar", { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob });
    closeAvatarCrop(); updateAuthUi(); status.textContent = "头像已更新。"; announce("头像已更新");
  } catch (error) { status.textContent = error.message; }
  finally { confirm.disabled = false; }
});

const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const chatThreadScroll = document.querySelector("#chat-thread-scroll");
const chatThread = document.querySelector("#chat-thread");
const chatWelcome = document.querySelector("#chat-welcome");
const chatLayout = document.querySelector(".chat-layout");
const conversationSearch = document.querySelector("#conversation-search");
const conversationSearchInput = document.querySelector("#conversation-search-input");
const poemScrollContentMaxWidth = 684;
function syncChatContentWidth() {
  if (!chatThreadScroll || !chatLayout) return;
  const available = chatThreadScroll.clientWidth;
  const width = window.matchMedia("(max-width: 760px)").matches
    ? Math.max(0, available - 36)
    : Math.min(poemScrollContentMaxWidth, Math.max(0, available - 48));
  chatLayout.style.setProperty("--chat-content-width", `${width}px`);
}
syncChatContentWidth();
new ResizeObserver(syncChatContentWidth).observe(chatThreadScroll);
window.addEventListener("resize", syncChatContentWidth);
const chatSubmit = chatForm.querySelector("button[type='submit']");
const agentStatus = document.querySelector("#agent-status");
const initialThreadMarkup = chatThread.innerHTML;
let chatSessionId = null;
let activeChatRequest = null;
let chatBusy = false;
const activeJobPolls = new Map();
let conversationRefreshTimer = null;
let conversationLoadVersion = 0;
let authGeneration = 0;
let activeConversationEvents = null;

async function loadConversations({ restore = false } = {}) {
  if (!currentUser) { document.querySelector("#conversation-list").innerHTML = "<p>登录后查看历史对话</p>"; return; }
  const generation = authGeneration;
  try {
    const payload = await apiFetch("/v1/conversations");
    if (generation !== authGeneration) return;
    const list = document.querySelector("#conversation-list");
    list.innerHTML = "";
    if (!payload.items.length) { list.innerHTML = "<p>还没有历史对话</p>"; return; }
    const heading = document.createElement("p"); heading.textContent = "历史对话"; list.append(heading);
    payload.items.forEach((item) => {
      const row = document.createElement("div"); row.className = "conversation-row";
      const button = document.createElement("button"); button.type = "button"; button.textContent = item.title || "新建对话"; button.dataset.conversationId = item.id;
      if (item.id === currentConversationId) button.setAttribute("aria-current", "true");
      const rename = document.createElement("button"); rename.type = "button"; rename.className = "conversation-rename"; rename.dataset.renameConversation = item.id; rename.title = "修改对话名称"; rename.setAttribute("aria-label", `修改对话名称：${item.title || "新建对话"}`); rename.textContent = "改名";
      const archive = document.createElement("button"); archive.type = "button"; archive.className = "conversation-archive"; archive.dataset.archiveConversation = item.id; archive.title = "归档对话"; archive.setAttribute("aria-label", `归档对话：${item.title || "新建对话"}`); archive.textContent = "归档";
      row.append(button, rename, archive); list.append(row);
    });
    if (restore) {
      const savedId = localStorage.getItem(`shiju_conversation_${currentUser.id}`);
      const target = payload.items.find((item) => item.id === savedId) || payload.items[0];
      if (target) await openConversation(target.id);
    }
    filterConversations();
  } catch { /* 登录状态可能已过期，发送消息时会提示 */ }
}

async function openConversation(conversationId) {
  if (!requireLogin()) return;
  const loadVersion = ++conversationLoadVersion;
  const payload = await apiFetch(`/v1/conversations/${encodeURIComponent(conversationId)}`);
  if (loadVersion !== conversationLoadVersion || !currentUser) return;
  clearJobProgressPolls();
  if (activeConversationEvents) activeConversationEvents.abort();
  clearConversationRefresh();
  currentConversationId = payload.id; chatSessionId = payload.id;
  localStorage.setItem(`shiju_conversation_${currentUser.id}`, payload.id);
  chatThread.innerHTML = "";
  payload.messages.forEach(appendPersistedMessage);
  const jobs = await loadConversationJobs(payload);
  if (loadVersion !== conversationLoadVersion) return;
  jobs.forEach((job) => startJobProgress(job.job_id, job));
  document.querySelectorAll("#conversation-list button[data-conversation-id]").forEach((button) => button.toggleAttribute("aria-current", button.dataset.conversationId === payload.id));
  agentStatus.textContent = "已连接";
  if (payload.messages.some((message) => message.status === "pending")) {
    scheduleConversationRefresh(payload.id);
  }
}

async function loadConversationJobs(conversation) {
  try {
    const payload = await apiFetch(`/v1/poetry/jobs?conversation_id=${encodeURIComponent(conversation.id)}`);
    return payload.items || [];
  } catch (error) {
    if (error.status !== 404) throw error;
    const ids = new Set();
    conversation.messages.forEach((message) => {
      for (const match of String(message.content).matchAll(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi)) ids.add(match[0]);
    });
    const jobs = await Promise.all([...ids].map((id) => apiFetch(`/v1/poetry/jobs/${id}`).catch(() => null)));
    return jobs.filter(Boolean);
  }
}

function appendPersistedMessage(message) {
  const state = message.status === "pending" ? "pending" : message.status === "failed" ? "error" : "";
  const article = appendMessage(message.content, message.role, state);
  article.dataset.messageId = message.id;
  article.dataset.messageStatus = message.status || "completed";
  if (message.job_id) startJobProgress(message.job_id);
  else if (message.role === "assistant" && message.status === "completed" && claimsJobSubmission(message.content)) {
    appendUnverifiedJobNotice(message.id);
  }
  return article;
}

function claimsJobSubmission(text) {
  return /(已提交|进入队列|等待\s*Worker|等待生成)/i.test(String(text));
}

function appendUnverifiedJobNotice(messageId) {
  if (chatThread.querySelector(`[data-unverified-message-id="${messageId}"]`)) return;
  const details = document.createElement("details");
  details.className = "job-progress job-progress--error";
  details.open = true;
  details.dataset.unverifiedMessageId = messageId || "current";
  details.innerHTML = "<summary>生成任务未创建</summary><p class=\"job-progress__status\">Agent 提到了提交，但服务端没有找到真实 job_id。请重新确认生成；系统不会再把口头回复当作已提交。</p>";
  chatThread.append(details);
}

function clearConversationRefresh() {
  if (conversationRefreshTimer) window.clearTimeout(conversationRefreshTimer);
  conversationRefreshTimer = null;
}

function scheduleConversationRefresh(conversationId) {
  clearConversationRefresh();
  conversationRefreshTimer = window.setTimeout(() => refreshConversationMessages(conversationId), 1500);
}

async function refreshConversationMessages(conversationId) {
  if (currentConversationId !== conversationId) return;
  try {
    const payload = await apiFetch(`/v1/conversations/${encodeURIComponent(conversationId)}/messages`);
    let hasPending = false;
    payload.items.forEach((message) => {
      hasPending ||= message.status === "pending";
      const article = chatThread.querySelector(`[data-message-id="${message.id}"]`);
      if (!article) {
        appendPersistedMessage(message);
        return;
      }
      if (article.dataset.messageStatus !== message.status || article.querySelector(".message-content p")?.textContent !== normalizeAssistantText(message.content)) {
        const state = message.status === "pending" ? "pending" : message.status === "failed" ? "error" : "";
        replaceMessage(article, message.content, state);
        article.dataset.messageStatus = message.status || "completed";
      }
      if (message.job_id) startJobProgress(message.job_id);
    });
    if (hasPending) scheduleConversationRefresh(conversationId);
  } catch {
    scheduleConversationRefresh(conversationId);
  }
}

let profilePoems = [];
let ownedPoems = [];
let favoritePoems = [];
let profileCollections = [];

function parsePoemFields(poem) {
  const raw = String(poem.content || "");
  const protocol = raw.match(/\[title\]\s*([\s\S]*?)\s*\[content\]\s*([\s\S]*)/i);
  return { ...poem, title: protocol?.[1]?.trim() || poem.title || "未命名诗作", content: protocol?.[2]?.trim() || raw };
}

function poemStanzas(content) {
  return String(content || "")
    .trim()
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph
      .split(/\n+/)
      .flatMap((line) => line.match(/[^，。！？；!?]+[，。！？；!?]?/g) || [line])
      .map((line) => line.trim())
      .filter(Boolean))
    .filter((stanza) => stanza.length);
}

function isSongCi(poem) {
  return [poem.work_type, poem.meter_type, poem.form_name]
    .filter(Boolean)
    .some((value) => /宋词|词牌|词$/.test(String(value)));
}

function isTangPoem(poem) {
  return [poem.work_type, poem.meter_type, poem.form_name]
    .filter(Boolean)
    .some((value) => /唐诗|律诗|绝句|排律|五言|七言/.test(String(value)));
}

const poemTextMeasurer = document.createElement("canvas").getContext("2d");

function updatePoemLayout(article) {
  const verses = article.querySelector(".poem-handscroll__verses");
  const lines = [...article.querySelectorAll(".poem-handscroll__line")];
  if (!verses || !lines.length || !verses.clientWidth) return;
  const versesStyle = getComputedStyle(verses);
  const lineStyle = getComputedStyle(lines[0]);
  poemTextMeasurer.font = lineStyle.font;
  const lineWidths = lines.map((line) => poemTextMeasurer.measureText(line.textContent).width);
  const horizontalNaturalWidth = Math.max(...[...article.querySelectorAll(".poem-handscroll__stanza")].map((stanza) => {
    const stanzaWidths = [...stanza.querySelectorAll(".poem-handscroll__line")]
      .map((line) => poemTextMeasurer.measureText(line.textContent).width);
    if (!article.classList.contains("poem-handscroll--tang")) return Math.max(...stanzaWidths);
    let widestRow = 0;
    for (let index = 0; index < stanzaWidths.length; index += 2) {
      widestRow = Math.max(widestRow, (stanzaWidths[index] || 0) + (stanzaWidths[index + 1] || 0));
    }
    return widestRow;
  }));
  const horizontalWidth = Math.min(article.clientWidth || article.parentElement?.clientWidth || 855, 855);
  const horizontalWidthRatio = horizontalNaturalWidth / horizontalWidth;
  const vertical = horizontalWidthRatio > 2 / 3;
  article.classList.toggle("poem-handscroll--vertical", vertical);

  const contentWidth = verses.clientWidth - parseFloat(versesStyle.paddingLeft) - parseFloat(versesStyle.paddingRight);
  const widestLine = Math.max(...lineWidths);
  article.classList.toggle("poem-handscroll--paired", !vertical && article.classList.contains("poem-handscroll--tang") && widestLine * 2 <= contentWidth);
}

const poemLayoutObserver = typeof ResizeObserver === "function"
  ? new ResizeObserver((entries) => entries.forEach(({ target }) => updatePoemLayout(target)))
  : null;

function scoreText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2).replace(/\.00$/, "") : "--";
}

function violationMessages(result = {}) {
  return (result.violations || []).map((item) =>
    `第 ${Number(item.lineIndex) + 1} 句第 ${Number(item.charIndex) + 1} 字“${item.char}”：${item.rule}，应${item.required}。`);
}

function decisionMessages(result = {}) {
  const polyphonic = (result.polyphonicDecisions || []).map((item) => item.message);
  const aoJiu = (result.aoJiu?.details || []).map((item) => item.message);
  if (!polyphonic.length && !aoJiu.length) return ["未发现需要人工复核的多音字或拗救判定。"];
  return [...polyphonic, ...aoJiu];
}

function appendInspectorList(parent, headingText, items, emptyText) {
  const section = document.createElement("section");
  const heading = document.createElement("h3");
  heading.textContent = headingText;
  section.append(heading);
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "prosody-inspector__empty";
    empty.textContent = emptyText;
    section.append(empty);
  } else {
    const list = document.createElement("ul");
    items.forEach((item) => {
      const row = document.createElement("li");
      row.textContent = item;
      list.append(row);
    });
    section.append(list);
  }
  parent.append(section);
}

function openProsodyInspector(evaluation, title = "评分详情") {
  if (!evaluation?.result) return;
  const result = evaluation.result;
  document.querySelector("#prosody-inspector-title").textContent = title;
  prosodyInspectorBody.replaceChildren();

  const meta = document.createElement("div");
  meta.className = "prosody-inspector__meta";
  const form = document.createElement("strong");
  form.textContent = evaluation.form_name || "智能选式";
  const book = document.createElement("span");
  book.textContent = evaluation.rhyme_book_name || evaluation.rhyme_book_id || "未标注韵书";
  meta.append(form, book);

  const scores = document.createElement("dl");
  scores.className = "prosody-inspector__scores";
  [
    ["综合", evaluation.comprehensive_score],
    ["结构", evaluation.structure_score],
    ["平仄", evaluation.tonal_score],
    ["押韵", evaluation.rhyme_score],
  ].forEach(([label, value]) => {
    const group = document.createElement("div");
    const term = document.createElement("dt"); term.textContent = label;
    const description = document.createElement("dd"); description.textContent = scoreText(value);
    group.append(term, description); scores.append(group);
  });
  prosodyInspectorBody.append(meta, scores);

  appendInspectorList(prosodyInspectorBody, "结构提示", result.issues || [], "结构符合所选诗式。");
  appendInspectorList(prosodyInspectorBody, "不可救平仄错误", violationMessages(result), "未发现不可救的平仄错误。");
  appendInspectorList(prosodyInspectorBody, "多音字与拗救", decisionMessages(result), "未发现需要人工复核的判定。");

  if (Array.isArray(result.lines) && result.lines.length) {
    const section = document.createElement("section");
    const heading = document.createElement("h3"); heading.textContent = "逐字平仄";
    const lines = document.createElement("div"); lines.className = "prosody-inspector__lines";
    result.lines.forEach((line, index) => {
      const row = document.createElement("div");
      const text = document.createElement("p"); text.textContent = `${index + 1}. ${line.text || (line.characters || []).map((item) => item.char).join("")}`;
      const tones = document.createElement("p"); tones.className = "prosody-inspector__tones";
      tones.textContent = (line.characters || []).map((item) => item.tone || "·").join(" ");
      row.append(text, tones); lines.append(row);
    });
    section.append(heading, lines); prosodyInspectorBody.append(section);
  }

  const rhymeGroups = (result.rhymeGroups || []).map((group, index) => {
    const endings = (group.endings || []).map((ending) => ending.char).join("、") || "无";
    return `第 ${index + 1} 韵组：${endings}；主韵部 ${group.dominantPart || "未识别"}`;
  });
  appendInspectorList(prosodyInspectorBody, "押韵详情", rhymeGroups, "未形成可识别的韵组。");
  prosodyInspector.hidden = false;
  document.body.classList.add("has-prosody-inspector");
  document.querySelector("#prosody-inspector-close").focus();
}

function closeProsodyInspector() {
  prosodyInspector.hidden = true;
  document.body.classList.remove("has-prosody-inspector");
}

document.querySelector("#prosody-inspector-close").addEventListener("click", closeProsodyInspector);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !prosodyInspector.hidden) closeProsodyInspector();
});

function createPoemHandscroll(poem, { resultLabel = "", showTime = false, evaluationPending = false, shareable = true } = {}) {
  const value = parsePoemFields(poem);
  const article = document.createElement("article");
  const stanzas = poemStanzas(value.content);
  const songCi = isSongCi(value);
  article.className = `poem-handscroll${songCi ? " poem-handscroll--ci" : isTangPoem(value) ? " poem-handscroll--tang" : " poem-handscroll--single-column"}`;

  const leftRoller = document.createElement("span");
  leftRoller.className = "poem-handscroll__roller poem-handscroll__roller--left";
  leftRoller.setAttribute("aria-hidden", "true");
  const rightRoller = document.createElement("span");
  rightRoller.className = "poem-handscroll__roller poem-handscroll__roller--right";
  rightRoller.setAttribute("aria-hidden", "true");

  const paper = document.createElement("div");
  paper.className = "poem-handscroll__paper";
  const heading = document.createElement("header");
  heading.className = "poem-handscroll__heading";
  const kind = document.createElement("p");
  kind.textContent = resultLabel || [value.work_type, value.form_name].filter(Boolean).join(" · ") || "诗词";
  const title = document.createElement("h3");
  title.textContent = value.title;
  const seal = document.createElement("span");
  seal.className = "poem-handscroll__seal";
  seal.setAttribute("aria-hidden", "true");
  seal.textContent = "诗矩";
  const evaluation = value.evaluation;
  const scorePanel = document.createElement("div");
  scorePanel.className = "poem-score";
  const scoreTop = document.createElement("div"); scoreTop.className = "poem-score__top";
  const inspect = document.createElement("button");
  inspect.type = "button"; inspect.className = "poem-score__inspect";
  inspect.textContent = evaluation ? "格律评分" : (evaluationPending ? "评分中" : "暂无评分");
  inspect.disabled = !evaluation;
  if (evaluation) inspect.addEventListener("click", () => openProsodyInspector(evaluation, value.title));
  if (evaluation) {
    const scoreBook = document.createElement("span");
    scoreBook.className = "poem-score__book";
    scoreBook.textContent = evaluation.rhyme_book_name || evaluation.rhyme_book_id || "韵书未标注";
    const scoreGrid = document.createElement("dl");
    [["结构", evaluation.structure_score], ["平仄", evaluation.tonal_score], ["押韵", evaluation.rhyme_score]].forEach(([label, score]) => {
      const group = document.createElement("div");
      const term = document.createElement("dt"); term.textContent = label;
      const description = document.createElement("dd"); description.textContent = scoreText(score);
      group.append(term, description); scoreGrid.append(group);
    });
    scoreTop.append(inspect, scoreBook); scorePanel.append(scoreTop, scoreGrid);
  } else {
    scorePanel.classList.add("poem-score--pending");
    scoreTop.append(inspect); scorePanel.append(scoreTop);
  }

  const verses = document.createElement("div");
  verses.className = "poem-handscroll__verses";
  (stanzas.length ? stanzas : [["正文尚未生成"]]).forEach((lines) => {
    const stanza = document.createElement("p");
    stanza.className = "poem-handscroll__stanza";
    lines.forEach((line) => {
      const verse = document.createElement("span");
      verse.className = "poem-handscroll__line";
      verse.textContent = line;
      stanza.append(verse);
    });
    verses.append(stanza);
  });
  paper.append(heading, verses);

  const scoreFooter = document.createElement("footer");
  scoreFooter.className = "poem-handscroll__footer poem-handscroll__footer--score";
  const footerActions = document.createElement("div");
  footerActions.className = "poem-handscroll__footer-actions";
  const flags = document.createElement("div");
  flags.className = "poem-score__flags";
  const violations = evaluation ? violationMessages(evaluation.result) : [];
  const decisions = evaluation ? decisionMessages(evaluation.result) : [];
  [["×", violations.length ? violations : ["未发现不可救的平仄错误。"], "标准平仄检查"], ["?", decisions, "多音字与拗救判定"]].forEach(([symbol, messages, label]) => {
    const flag = document.createElement("button");
    flag.type = "button"; flag.className = "poem-score__flag"; flag.textContent = symbol;
    flag.setAttribute("aria-label", label); flag.disabled = !evaluation;
    const tooltip = document.createElement("span"); tooltip.className = "poem-score__tooltip";
    (messages || []).forEach((message) => { const line = document.createElement("span"); line.textContent = message; tooltip.append(line); });
    flag.append(tooltip); flags.append(flag);
  });
  heading.append(seal, kind, scorePanel, title);
  if (shareable) {
    const share = document.createElement("button");
    share.type = "button"; share.className = "poem-score__inspect"; share.textContent = "分享诗作";
    share.addEventListener("click", async () => {
      let poemId = value.id || "";
      if (!poemId && currentUser) {
        await loadPoems();
        poemId = profilePoems.find((poem) => parsePoemFields(poem).title === value.title && parsePoemFields(poem).content === value.content)?.id || "";
      }
      sessionStorage.setItem("shiju_share_poem", JSON.stringify({ id: poemId, title: value.title, content: value.content, work_type: value.work_type, form_name: value.form_name }));
      window.location.hash = "forum/compose";
    });
    footerActions.append(share);
  }

  if (showTime && value.created_at) {
    const time = document.createElement("time");
    time.dateTime = new Date(value.created_at * 1000).toISOString();
    time.textContent = `创建于 ${new Date(value.created_at * 1000).toLocaleString("zh-CN")}`;
    scoreFooter.append(time);
  }
  scoreFooter.append(footerActions);
  scoreFooter.append(flags);
  paper.append(scoreFooter);

  article.append(leftRoller, paper, rightRoller);
  poemLayoutObserver?.observe(article);
  requestAnimationFrame(() => updatePoemLayout(article));
  return article;
}

function poemCard(poem) {
  const value = parsePoemFields(poem);
  const article = createPoemHandscroll(value, { showTime: true });
  article.dataset.poemId = value.id;
  const actions = document.createElement("div"); actions.className = "poem-card__actions";
  const favorite = document.createElement("button"); favorite.type = "button"; favorite.dataset.poemAction = "favorite"; favorite.title = value.favorite ? "取消收藏" : "收藏"; favorite.setAttribute("aria-label", favorite.title); favorite.textContent = value.favorite ? "★" : "☆";
  const collect = document.createElement("button"); collect.type = "button"; collect.dataset.poemAction = "collect"; collect.textContent = "加入合集";
  const publish = document.createElement("button"); publish.type = "button"; publish.dataset.poemAction = "public"; publish.textContent = value.is_public ? "取消公开" : "公开诗作";
  const remove = document.createElement("button"); remove.type = "button"; remove.dataset.poemAction = "delete"; remove.textContent = "删除";
  actions.append(favorite, collect);
  if (value.author_id === currentUser?.id) actions.append(publish, remove);
  article.querySelector(".poem-handscroll__footer-actions").append(actions);
  return article;
}

function renderPoemList(container, poems, emptyText) {
  container.replaceChildren();
  if (!poems.length) { const empty = document.createElement("p"); empty.className = "empty-state"; empty.textContent = emptyText; container.append(empty); return; }
  container.append(...poems.map(poemCard));
}

async function loadPoems() {
  if (!currentUser) return;
  const generation = authGeneration;
  const [ownedPayload, favoritePayload] = await Promise.all([apiFetch("/v1/profile/poems"), apiFetch("/v1/profile/poems?favorite=true")]);
  if (generation !== authGeneration) return;
  ownedPoems = ownedPayload.items || [];
  favoritePoems = favoritePayload.items || [];
  const merged = new Map(); [...ownedPoems, ...favoritePoems].forEach((poem) => merged.set(poem.id, poem)); profilePoems = [...merged.values()];
  const type = document.querySelector("#profile-work-type")?.value || "";
  renderPoemList(document.querySelector("#poem-list"), ownedPoems.filter((poem) => !type || poem.work_type === type), "暂无诗作记录。完成一次格律生成后，作品会自动归档到这里。");
  renderPoemList(document.querySelector("#favorite-list"), favoritePoems, "还没有收藏作品。");
  document.querySelector("#profile-poem-count").textContent = ownedPoems.length;
  document.querySelector("#profile-favorite-count").textContent = favoritePoems.length;
  profilePoems.filter((poem) => !poem.evaluation && poem.job_id && poem.candidate_ordinal).forEach(async (poem) => {
    const key = `${poem.job_id}:${poem.candidate_ordinal}`;
    if (activeEvaluations.has(key) || failedEvaluations.has(key)) return;
    try {
      const job = await apiFetch(`/v1/poetry/jobs/${encodeURIComponent(poem.job_id)}/state`);
      const candidate = (job.candidates || []).find((item) => Number(item.ordinal) === Number(poem.candidate_ordinal));
      if (candidate) ensureCandidateEvaluation(job, candidate, job.request || poem, () => {});
    } catch (error) {
      failedEvaluations.add(key);
      console.warn("历史作品评分补算失败", error);
    }
  });
}

async function loadProfileData() {
  if (!currentUser) return;
  const generation = authGeneration;
  try {
    const [collections, conversations, following] = await Promise.all([
      apiFetch("/v1/profile/poem-collections"), apiFetch("/v1/conversations?include_deleted=true"), apiFetch("/v1/forum/following"), loadPoems(),
    ]);
    if (generation !== authGeneration) return;
    profileCollections = collections.items || [];
    const collectionList = document.querySelector("#collection-list"); collectionList.replaceChildren();
    if (!profileCollections.length) collectionList.innerHTML = '<p class="empty-state">还没有作品合集。</p>';
    else profileCollections.forEach((item) => {
      const row = document.createElement("article"); row.className = "profile-row"; row.dataset.collectionId = item.id;
      row.innerHTML = `<div><strong></strong><span></span></div><button type="button" data-collection-action="delete">删除</button>`;
      row.querySelector("strong").textContent = item.name; row.querySelector("span").textContent = `${item.count} 首作品`; collectionList.append(row);
    });
    renderArchive((conversations.items || []).filter((item) => item.deleted_at));
    renderUserRows(document.querySelector("#following-list"), following.items || [], true);
  } catch (error) { announce(`个人中心加载失败：${error.message}`); }
}

function renderArchive(items) {
  const list = document.querySelector("#archive-list"); list.replaceChildren();
  if (!items.length) { list.innerHTML = '<p class="empty-state">暂无归档对话。</p>'; return; }
  items.forEach((item) => {
    const row = document.createElement("article"); row.className = "profile-row"; row.dataset.conversationId = item.id;
    row.innerHTML = '<div><strong></strong><span></span></div><button type="button" data-archive-action="restore">恢复到聊天</button>';
    row.querySelector("strong").textContent = item.title; row.querySelector("span").textContent = `归档于 ${new Date(item.deleted_at * 1000).toLocaleString("zh-CN")}`; list.append(row);
  });
}

document.querySelectorAll("[data-profile-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    const tab = button.dataset.profileTab;
    document.querySelectorAll("[data-profile-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
    document.querySelectorAll("[data-profile-panel]").forEach((panel) => { panel.hidden = panel.dataset.profilePanel !== tab; });
    if (currentUser) loadProfileData();
  });
});

document.querySelector("#profile-work-type")?.addEventListener("change", () => loadPoems());

document.querySelector("#poem-list")?.parentElement?.addEventListener("click", handleProfileAction);
document.querySelector("#favorite-list")?.parentElement?.addEventListener("click", handleProfileAction);
document.querySelector("#collection-list")?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-collection-action='delete']"); if (!button) return;
  const row = button.closest("[data-collection-id]");
  if (!window.confirm("删除这个合集？作品本身不会被删除。")) return;
  await apiFetch(`/v1/profile/poem-collections/${row.dataset.collectionId}`, { method: "DELETE" }); await loadProfileData();
});

async function handleProfileAction(event) {
  const button = event.target.closest("[data-poem-action]"); if (!button) return;
  const card = button.closest("[data-poem-id]"); const poemId = card?.dataset.poemId; if (!poemId) return;
  try {
    if (button.dataset.poemAction === "favorite") await apiFetch(`/v1/profile/poems/${poemId}/favorite`, { method: button.textContent === "★" ? "DELETE" : "POST" });
    if (button.dataset.poemAction === "delete") { if (!window.confirm("删除这首作品？")) return; await apiFetch(`/v1/profile/poems/${poemId}`, { method: "DELETE" }); }
    if (button.dataset.poemAction === "public") await apiFetch(`/v1/profile/poems/${poemId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_public: button.textContent !== "取消公开" }) });
    if (button.dataset.poemAction === "collect") {
      if (!profileCollections.length) { announce("请先新建一个作品合集。"); return; }
      const choice = window.prompt(`输入合集名称：\n${profileCollections.map((item) => item.name).join("、")}`);
      const collection = profileCollections.find((item) => item.name === choice);
      if (!collection) { announce("未找到对应合集。"); return; }
      await apiFetch(`/v1/profile/poem-collections/${collection.id}/items`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ poem_id: poemId }) });
    }
    await loadProfileData();
  } catch (error) { announce(`操作失败：${error.message}`); }
}

document.querySelector("#new-collection-button")?.addEventListener("click", async () => {
  const name = window.prompt("合集名称"); if (!name?.trim()) return;
  try { await apiFetch("/v1/profile/poem-collections", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) }); await loadProfileData(); } catch (error) { announce(`创建合集失败：${error.message}`); }
});

document.querySelector("#archive-list")?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-archive-action='restore']"); if (!button) return;
  const id = button.closest("[data-conversation-id]").dataset.conversationId;
  try { await apiFetch(`/v1/conversations/${id}/restore`, { method: "POST" }); await loadConversations(); await loadProfileData(); announce("对话已恢复"); } catch (error) { announce(`恢复失败：${error.message}`); }
});

document.querySelector("#change-password-form")?.addEventListener("submit", async (event) => {
  event.preventDefault(); const status = document.querySelector("#password-status"); status.textContent = "更新中……";
  try { await apiFetch("/v1/auth/change-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ old_password: document.querySelector("#old-password").value, new_password: document.querySelector("#new-password").value }) }); status.textContent = "密码已更新。"; event.target.reset(); } catch (error) { status.textContent = error.message; }
});

function normalizeAssistantText(text) {
  return String(text)
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^```.*$/gm, "")
    .trim();
}

function authHeaders(extra = {}) {
  return authToken ? { ...extra, Authorization: `Bearer ${authToken}` } : extra;
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, { ...options, headers: authHeaders(options.headers || {}) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(responseError(payload, response.status));
    error.status = response.status;
    throw error;
  }
  return payload;
}

function requireLogin() {
  if (authToken) return true;
  document.querySelector("#login-dialog").showModal();
  document.querySelector("#login-username").focus();
  return false;
}

function updateAuthUi() {
  const accountLabel = document.querySelector("#account-entry-label");
  if (accountLabel) accountLabel.textContent = currentUser ? currentUser.display_name : "登录 / 注册";
  document.querySelector("#logout-button").hidden = true;
  document.querySelector("#profile-logout-button").hidden = !currentUser;
  document.querySelector("#drawer-login-action").hidden = Boolean(currentUser);
  document.querySelector("#drawer-logout-action").hidden = !currentUser;
  document.querySelector("#home-nav-link").hidden = Boolean(currentUser);
  document.querySelector(".site-brand").href = currentUser ? "#forum" : "#home";
  document.querySelector("#chat-user-status").textContent = currentUser ? `已登录：${currentUser.display_name}` : "未登录，请先登录";
  document.querySelector("#profile-user-label").textContent = currentUser ? `${currentUser.display_name} 的创作档案` : "登录后查看你生成的全部诗词。";
  const displayName = document.querySelector("#profile-display-name");
  const bio = document.querySelector("#profile-bio");
  if (displayName) displayName.value = currentUser?.display_name || "";
  if (bio) bio.value = currentUser?.bio || "";
  const notifyReactions = document.querySelector("#profile-notify-reactions");
  if (notifyReactions) notifyReactions.checked = currentUser?.notify_on_reaction !== false;
  setUserAvatar(document.querySelector("#profile-avatar-preview"), currentUser);
  setUserAvatar(document.querySelector("#header-avatar"), currentUser);
  setUserAvatar(document.querySelector("#drawer-avatar"), currentUser);
  const drawerName = document.querySelector("#drawer-user-name");
  const drawerHandle = document.querySelector("#drawer-user-handle");
  if (drawerName) drawerName.textContent = currentUser?.display_name || "访客";
  if (drawerHandle) drawerHandle.textContent = currentUser ? `@${currentUser.username}` : "登录后管理创作";
  const adminLink = document.querySelector("#admin-nav-link");
  if (adminLink) adminLink.hidden = currentUser?.role !== "admin";
}

function setUserAvatar(element, user) {
  if (!element) return;
  element.replaceChildren();
  const url = user?.avatar_url;
  if (url && /^\/media\/avatars\/[\w.-]+$/.test(url)) {
    const img = document.createElement("img"); img.src = url; img.alt = ""; element.append(img);
  } else element.textContent = (user?.display_name || user?.username || "诗").slice(0, 1);
}

function resetAuthenticatedUi() {
  authGeneration++;
  conversationLoadVersion++;
  if (activeConversationEvents) activeConversationEvents.abort();
  if (activeChatRequest) activeChatRequest.abort();
  chatBusy = false;
  chatThread.innerHTML = initialThreadMarkup;
  chatInput.value = "";
  chatLayout.classList.remove("is-sidebar-collapsed");
  conversationSearch.hidden = true;
  conversationSearchInput.value = "";
  document.querySelector("#conversation-list").innerHTML = "<p>登录后查看历史对话</p>";
  for (const selector of ["#poem-list", "#favorite-list", "#collection-list", "#archive-list", "#notification-list", "#following-list", "#user-search-results", "#thread-page-content", "#compose-preview", "#reply-poem-preview", "#compose-poem-preview"]) document.querySelector(selector)?.replaceChildren();
  document.querySelector("#compose-form").reset();
  const headerBadge = document.querySelector("#header-notification-badge");
  if (headerBadge) { headerBadge.hidden = true; headerBadge.textContent = ""; }
  window.forumComposePoemIds = []; window.forumReplyPoemIds = [];
  ownedPoems = []; favoritePoems = []; profilePoems = []; profileCollections = [];
  notificationItems = [];
  sessionStorage.removeItem("shiju_share_poem");
}

async function loadCurrentUser() {
  if (!authToken) return updateAuthUi();
  try { currentUser = await apiFetch("/v1/auth/me"); }
  catch { authToken = ""; localStorage.removeItem("shiju_token"); resetAuthenticatedUi(); }
  updateAuthUi();
  if (currentUser) {
    if (routeFromHash() === "home") showRoute("chat", { scroll: false });
    await loadConversations({ restore: true }); await loadProfileData();
    try { const notices = await apiFetch("/v1/forum/notifications?limit=5"); await renderDrawerNotifications(notices); } catch { /* forum notification store may not exist on an older database */ }
    if (routeFromHash() === "admin") await loadAdminData();
  }
}

function appendMessage(text, role, state = "") {
  const article = document.createElement("article");
  article.className = `chat-message chat-message--${role}`;
  if (state) article.classList.add(`chat-message--${state}`);
  const avatar = document.createElement("div");
  avatar.className = `message-avatar message-avatar--${role}`;
  avatar.setAttribute("aria-hidden", "true");
  if (role === "assistant") {
    const image = document.createElement("img");
    image.src = new URL("./ai-avatar.svg", import.meta.url).href;
    image.alt = "";
    avatar.append(image);
  } else setUserAvatar(avatar, currentUser);
  const content = document.createElement("div");
  content.className = "message-content";
  const paragraph = document.createElement("p");
  paragraph.textContent = role === "assistant" ? normalizeAssistantText(text) : text;
  content.append(paragraph);
  if (role === "assistant") article.append(avatar, content);
  else article.append(content, avatar);
  chatThread.append(article);
  chatThreadScroll.scrollTop = chatThreadScroll.scrollHeight;
  return article;
}

function filterConversations() {
  const query = conversationSearchInput?.value.trim().toLocaleLowerCase() || "";
  document.querySelectorAll("#conversation-list .conversation-row").forEach((row) => {
    const title = row.querySelector("button[data-conversation-id]")?.textContent?.trim().toLocaleLowerCase() || "";
    row.hidden = Boolean(query && !title.includes(query));
  });
}

function hideChatWelcome() {
  if (chatWelcome) chatWelcome.hidden = true;
}

function replaceMessage(article, text, state = "") {
  const content = article.querySelector(".message-content p");
  content.textContent = normalizeAssistantText(text);
  article.classList.remove("chat-message--pending", "chat-message--error");
  if (state) article.classList.add(`chat-message--${state}`);
  chatThreadScroll.scrollTop = chatThreadScroll.scrollHeight;
}

function appendProposalEditor(prepared) {
  if (!prepared?.proposal_id || chatThread.querySelector(`[data-proposal-id="${prepared.proposal_id}"]`)) return;
  const proposal = prepared.proposal || {};
  const panel = document.createElement("details");
  panel.className = "proposal-editor";
  panel.dataset.proposalId = prepared.proposal_id;
  panel.open = true;

  const summary = document.createElement("summary");
  summary.textContent = prepared.kind === "rewrite" ? "重写提示词（可修改）" : "创作提示词（可修改）";
  const body = document.createElement("div");
  body.className = "proposal-editor__body";
  const meta = document.createElement("p");
  const form = [proposal.meter_type, proposal.form_name].filter(Boolean).join(" · ");
  meta.textContent = `${form || "诗词生成方案"}。以下是 Agent 已选择的实际生成参数，可直接修改后提交。`;

  const promptLabel = document.createElement("label");
  promptLabel.textContent = "实际发送给诗词生成器的提示词";
  const prompt = document.createElement("textarea");
  prompt.rows = 5;
  prompt.value = prepared.editable_prompt || "";
  promptLabel.append(prompt);

  if (prepared.kind === "rewrite" && proposal.original_text) {
    const originalLabel = document.createElement("label");
    originalLabel.textContent = `原诗（固定上下文；重写第 ${proposal.target_line_numbers?.join("、") || "指定"} 句）`;
    const original = document.createElement("textarea");
    original.rows = 5; original.value = proposal.original_text; original.readOnly = true;
    original.setAttribute("aria-label", "原诗固定上下文");
    originalLabel.append(original);
    body.append(originalLabel);
  }

  const config = document.createElement("div");
  config.className = "proposal-editor__config";
  const field = (labelText, control) => {
    const label = document.createElement("label");
    const text = document.createElement("span"); text.textContent = labelText;
    label.append(text, control); config.append(label);
    return control;
  };

  const count = document.createElement("select");
  for (let value = 1; value <= 5; value += 1) {
    const option = document.createElement("option");
    option.value = String(value); option.textContent = String(value);
    option.selected = value === Number(prepared.candidate_count || proposal.candidate_count || 1);
    count.append(option);
  }
  field("候选数量", count);

  const meterType = document.createElement("select");
  ["唐诗", "宋词", "汉俳", "排律"].forEach((name) => meterType.add(new Option(name, name, false, name === proposal.meter_type)));
  field("诗体", meterType);
  const formName = document.createElement("input");
  formName.type = "text"; formName.value = proposal.form_name || ""; formName.required = true;
  formName.setAttribute("list", "poetry-form-suggestions");
  field("篇式 / 词牌", formName);

  const rhymeBook = document.createElement("select");
  [["Xinyun", "中华新韵"], ["Pinshui", "平水韵"], ["Cilin", "词林正韵"], ["Tongyun", "中华通韵"]].forEach(([value, label]) => {
    rhymeBook.add(new Option(label, value, false, value === (proposal.rhyme_dict_name || "Xinyun")));
  });
  field("生成韵书", rhymeBook);

  const polyphonic = document.createElement("select");
  polyphonic.add(new Option("严格判定", "strict", false, proposal.strict_polyphonic !== false));
  polyphonic.add(new Option("放行多音", "permissive", false, proposal.strict_polyphonic === false));
  field("多音字", polyphonic);

  const numLines = document.createElement("input");
  numLines.type = "number"; numLines.min = "4"; numLines.max = "128"; numLines.step = "2";
  numLines.value = proposal.num_lines || ""; numLines.placeholder = "按篇式自动";
  const numLinesLabel = field("句数", numLines).closest("label");

  const allowAoJiu = document.createElement("input");
  allowAoJiu.type = "checkbox"; allowAoJiu.checked = Boolean(proposal.task_options?.allow_aojiu);
  const aoJiuLabel = document.createElement("label");
  aoJiuLabel.className = "proposal-editor__check";
  const aoJiuText = document.createElement("span"); aoJiuText.textContent = "允许拗救";
  aoJiuLabel.append(allowAoJiu, aoJiuText); config.append(aoJiuLabel);

  const updateConditionalFields = () => {
    numLinesLabel.hidden = meterType.value !== "排律";
    aoJiuLabel.hidden = !["唐诗", "排律"].includes(meterType.value);
  };
  meterType.addEventListener("change", updateConditionalFields);
  updateConditionalFields();

  const actions = document.createElement("div");
  actions.className = "proposal-editor__actions";
  const state = document.createElement("span");
  state.className = "proposal-editor__state";
  state.textContent = "修改后将直接进入本地模型";
  const submit = document.createElement("button");
  submit.type = "button"; submit.className = "primary-button";
  submit.textContent = prepared.kind === "rewrite" ? "提交重写" : "提交生成";
  submit.addEventListener("click", async () => {
    if (!currentConversationId) {
      state.textContent = "对话正在保存，请稍候再提交。";
      return;
    }
    const requirement = prompt.value.trim();
    if (!requirement || !formName.value.trim()) {
      state.textContent = "提示词和篇式不能为空。";
      return;
    }
    submit.disabled = true;
    state.textContent = "正在提交本地模型……";
    try {
      const taskOptions = { ...(proposal.task_options || {}) };
      if (["唐诗", "排律"].includes(meterType.value)) taskOptions.allow_aojiu = allowAoJiu.checked;
      else delete taskOptions.allow_aojiu;
      const payload = await apiFetch(`/v1/agent/proposals/${encodeURIComponent(prepared.proposal_id)}/submit`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          conversation_id: currentConversationId,
          requirement,
          candidate_count: Number(count.value),
          meter_type: meterType.value,
          form_name: formName.value.trim(),
          rhyme_dict_name: rhymeBook.value,
          strict_polyphonic: polyphonic.value === "strict",
          num_lines: numLines.value ? Number(numLines.value) : null,
          task_options: taskOptions,
        }),
      });
      panel.querySelectorAll("textarea, input, select, button").forEach((control) => { control.disabled = true; });
      panel.classList.add("is-submitted");
      state.textContent = "已提交，开始生成。";
      submit.textContent = "已提交";
      startJobProgress(payload.job_id, payload);
    } catch (error) {
      submit.disabled = false;
      state.textContent = `提交失败：${error.message}`;
    }
  });
  actions.append(state, submit);
  body.prepend(meta, promptLabel);
  body.append(config, actions);
  panel.append(summary, body);
  chatThread.append(panel);
  chatThreadScroll.scrollTop = chatThreadScroll.scrollHeight;
}

function setChatBusy(busy) {
  chatBusy = busy;
  chatForm.setAttribute("aria-busy", String(busy));
  chatInput.disabled = busy;
  chatSubmit.disabled = busy;
  chatSubmit.textContent = busy ? "等待" : "发送";
}

function responseError(payload, status) {
  if (typeof payload?.detail === "string") return payload.detail;
  return `请求失败（${status}）`;
}

function clearJobProgressPolls() {
  activeJobPolls.forEach((control) => control.stop());
  activeJobPolls.clear();
}

const candidateStatusLabels = {
  queued: "等待生成",
  running: "正在生成",
  retrying: "重新尝试",
  succeeded: "生成完成",
  failed: "生成失败",
};

function appendCandidateMeta(list, label, value) {
  if (value === undefined || value === null || value === "") return;
  const group = document.createElement("div");
  const term = document.createElement("dt"); term.textContent = label;
  const description = document.createElement("dd"); description.textContent = value;
  group.append(term, description); list.append(group);
}

function candidateDetail(candidate, wasOpen = false) {
  const status = candidate.status || "queued";
  const item = document.createElement("details");
  item.className = "job-progress__candidate";
  item.dataset.status = status;
  item.dataset.candidateOrdinal = candidate.ordinal;
  item.open = status === "running" || wasOpen;

  const summary = document.createElement("summary");
  const name = document.createElement("span");
  name.className = "job-progress__candidate-name";
  name.textContent = `候选 ${candidate.ordinal}`;
  const state = document.createElement("span");
  state.className = "job-progress__candidate-state";
  state.textContent = candidateStatusLabels[status] || status;
  const attempt = document.createElement("span");
  attempt.className = "job-progress__candidate-attempt";
  attempt.textContent = `第 ${candidate.attempt || 1} 次尝试`;
  summary.append(name, state, attempt);

  const body = document.createElement("div");
  body.className = "job-progress__candidate-body";
  const meta = document.createElement("dl");
  meta.className = "job-progress__candidate-meta";
  appendCandidateMeta(meta, "生成状态", candidateStatusLabels[status] || status);
  appendCandidateMeta(meta, "尝试次数", candidate.attempt || 1);
  appendCandidateMeta(meta, "题目", candidate.title);
  if (candidate.started_at) appendCandidateMeta(meta, "开始时间", new Date(candidate.started_at * 1000).toLocaleTimeString("zh-CN"));
  if (candidate.finished_at) appendCandidateMeta(meta, "完成时间", new Date(candidate.finished_at * 1000).toLocaleTimeString("zh-CN"));
  body.append(meta);

  const output = candidate.content || candidate.partial_text || "尚未生成正文。";
  const outputSection = document.createElement("section");
  const outputHeading = document.createElement("h4"); outputHeading.textContent = candidate.content ? "生成正文" : "实时片段";
  const outputText = document.createElement("pre"); outputText.textContent = output;
  outputSection.append(outputHeading, outputText); body.append(outputSection);

  if (candidate.raw_text && candidate.raw_text.trim() !== output.trim()) {
    const rawSection = document.createElement("section");
    const rawHeading = document.createElement("h4"); rawHeading.textContent = "模型原始输出";
    const rawText = document.createElement("pre"); rawText.textContent = candidate.raw_text;
    rawSection.append(rawHeading, rawText); body.append(rawSection);
  }
  if (candidate.error) {
    const error = document.createElement("p");
    error.className = "job-progress__candidate-error";
    error.textContent = `失败原因：${candidate.error}`;
    body.append(error);
  }

  item.append(summary, body);
  return item;
}

async function ensureCandidateEvaluation(job, candidate, requestMeta, onComplete) {
  if (candidate.evaluation || candidate.status !== "succeeded" || !candidate.content) return;
  const key = `${job.job_id}:${candidate.ordinal}`;
  if (activeEvaluations.has(key) || failedEvaluations.has(key)) return;
  const operation = (async () => {
    try {
      const evaluation = await evaluateGeneratedPoem(candidate.content, requestMeta);
      const saved = await apiFetch(`/v1/poetry/jobs/${encodeURIComponent(job.job_id)}/candidates/${candidate.ordinal}/evaluation`, {
        method: "PUT",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ evaluation }),
      });
      candidate.evaluation = saved.evaluation;
      await loadPoems();
      onComplete();
    } catch (error) {
      failedEvaluations.add(key);
      console.warn("候选格律评分失败", error);
      onComplete();
    } finally {
      activeEvaluations.delete(key);
    }
  })();
  activeEvaluations.set(key, operation);
}

function renderAvailableScrolls(container, job, requestMeta) {
  const candidates = (job.candidates || []).filter((candidate) => candidate.status === "succeeded" && candidate.content);
  const works = candidates.length
    ? candidates
    : job.status === "succeeded" && job.result?.candidates?.length
      ? job.result.candidates.map((candidate, index) => ({ ...candidate, ordinal: index + 1, status: "succeeded" }))
      : job.status === "succeeded" && job.result?.full_text
        ? [{ content: job.result.full_text, ordinal: 1, status: "succeeded" }]
        : [];
  if (!works.length) return;

  let list = container.querySelector(".job-progress__scrolls");
  if (!list) {
    const heading = document.createElement("div");
    heading.className = "job-progress__results-heading";
    const eyebrow = document.createElement("span"); eyebrow.textContent = "卷轴成稿";
    const title = document.createElement("h3"); title.textContent = "生成诗稿";
    heading.append(eyebrow, title); container.append(heading);
    list = document.createElement("div");
    list.className = "job-progress__scrolls";
    container.append(list);
  }

  works.forEach((work, index) => {
    const ordinal = Number(work.ordinal || index + 1);
    const value = {
      ...requestMeta,
      ...work,
      created_at: work.created_at ?? job.created_at ?? requestMeta.created_at,
      content: work.content || work.text || work.full_text || work.display_text || "",
    };
    const key = `${job.job_id}:${ordinal}`;
    const evaluationState = value.evaluation?.evaluated_at || (activeEvaluations.has(key) ? "pending" : failedEvaluations.has(key) ? "failed" : "none");
    const existing = list.querySelector(`[data-candidate-ordinal="${ordinal}"]`);
    if (!existing || existing.dataset.evaluationState !== String(evaluationState)) {
      const scroll = createPoemHandscroll(value, {
        resultLabel: `候选 ${ordinal}`,
        showTime: true,
        evaluationPending: !value.evaluation && !failedEvaluations.has(key),
      });
      scroll.dataset.candidateOrdinal = String(ordinal);
      scroll.dataset.evaluationState = String(evaluationState);
      if (existing) existing.replaceWith(scroll);
      else list.append(scroll);
    }
    ensureCandidateEvaluation(job, work, requestMeta, () => renderAvailableScrolls(container, job, requestMeta));
  });
}

function startJobProgress(jobId, initialJob = null) {
  if (!jobId || !authToken) return;
  if (activeJobPolls.has(jobId) || chatThread.querySelector(`[data-job-id="${jobId}"]`)) return;
  const details = document.createElement("details");
  details.className = "job-progress"; details.open = true;
  details.dataset.jobId = jobId;
  details.innerHTML = "<summary><span>诗词生成进度</span><span class=\"job-progress__count\">0 / 0</span></summary><p class=\"job-progress__status\">任务已提交，等待 Worker……</p><div class=\"job-progress__candidates\"></div><div class=\"job-progress__results\" aria-live=\"polite\"></div>";
  chatThread.append(details); chatThreadScroll.scrollTop = chatThreadScroll.scrollHeight;
  const statusNode = details.querySelector(".job-progress__status");
  const resultsNode = details.querySelector(".job-progress__results");
  const countNode = details.querySelector(".job-progress__count");
  const candidatesNode = details.querySelector(".job-progress__candidates");
  let timer = null;
  let stopped = false;
  let settled = false;
  const archivedOrdinals = new Set();
  let requestMeta = initialJob?.request || {};
  const render = async (job) => {
    if (stopped) return true;
    if (job.request) requestMeta = job.request;
    const labels = {
      queued: job.waiting_for_worker ? "未检测到生成 Worker，任务正在等待……" : "已进入生成队列……",
      running: "模型生成中……",
      succeeded: "生成完成",
      failed: "生成失败",
    };
    statusNode.textContent = labels[job.status] || job.status;
    countNode.textContent = `${job.completed ?? job.result?.candidates?.length ?? 0} / ${job.total ?? job.request?.candidate_count ?? 0}`;
    if (Array.isArray(job.candidates)) {
      const openCandidates = new Set([...candidatesNode.querySelectorAll("details[open]")].map((item) => item.dataset.candidateOrdinal));
      candidatesNode.replaceChildren(...job.candidates.map((candidate) => candidateDetail(candidate, openCandidates.has(String(candidate.ordinal)))));
      const completedOrdinals = job.candidates.filter((candidate) => candidate.status === "succeeded").map((candidate) => candidate.ordinal);
      const hasNewCandidate = completedOrdinals.some((ordinal) => !archivedOrdinals.has(ordinal));
      completedOrdinals.forEach((ordinal) => archivedOrdinals.add(ordinal));
      if (hasNewCandidate && currentUser) loadPoems();
    }
    renderAvailableScrolls(resultsNode, job, requestMeta);
    if (job.status === "succeeded") {
      activeJobPolls.delete(jobId);
      if (!settled) {
        settled = true;
        await loadPoems();
      }
      return true;
    }
    if (job.status === "failed") {
      const error = document.createElement("p");
      error.className = "job-progress__failure";
      error.textContent = job.error?.message || "任务失败";
      resultsNode.replaceChildren(error);
      activeJobPolls.delete(jobId);
      settled = true;
      return true;
    }
    return false;
  };
  const poll = async (knownJob = null) => {
    try {
      const job = knownJob || await apiFetch(`/v1/poetry/jobs/${encodeURIComponent(jobId)}/state`);
      if (await render(job)) return;
      if (!stopped) timer = window.setTimeout(() => poll(), 1800);
    } catch (error) {
      statusNode.textContent = `进度查询失败，稍后重试：${error.message}`;
      if (!stopped) timer = window.setTimeout(() => poll(), 3000);
    }
  };
  activeJobPolls.set(jobId, {
    stop() { stopped = true; if (timer) window.clearTimeout(timer); },
  });
  poll(initialJob);
  startJobEventStream(jobId, render);
}

async function startJobEventStream(jobId, render) {
  if (!authToken || !window.ReadableStream) return;
  const controller = new AbortController();
  try {
    const response = await fetch(`/v1/poetry/jobs/${encodeURIComponent(jobId)}/events?after=0`, { headers: authHeaders(), signal: controller.signal });
    if (!response.ok || !response.body) return;
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n"); buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk.split("\n").find((part) => part.startsWith("data:")); if (!line) continue;
        try { await render(await apiFetch(`/v1/poetry/jobs/${encodeURIComponent(jobId)}/state`)); } catch { /* polling remains the fallback */ }
      }
    }
  } catch { /* SSE 断开后由快照轮询兜底 */ }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (chatBusy) return;
  if (!requireLogin()) return;
  const message = chatInput.value.trim();
  if (!message) {
    chatInput.focus();
    return;
  }
  hideChatWelcome();
  appendMessage(message, "user");
  chatInput.value = "";
  chatInput.style.height = "";
  const waitingMessage = appendMessage("正在斟酌……", "assistant", "pending");
  const requestConversationId = currentConversationId;
  const requestController = new AbortController();
  activeChatRequest = requestController;
  setChatBusy(true);
  agentStatus.textContent = "思考中";

  try {
    const response = await fetch("/v1/agent/chat/stream", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ message, session_id: chatSessionId, conversation_id: currentConversationId }),
      signal: requestController.signal,
    });
    if (!response.ok) { const payload = await response.json().catch(() => ({})); throw new Error(responseError(payload, response.status)); }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let reply = ""; let responseConversationId = requestConversationId; const jobs = [];
    const consume = async () => {
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true }); const blocks = buffer.split("\n\n"); buffer = blocks.pop() || "";
        for (const block of blocks) {
          const event = block.match(/^event:\s*(.+)$/m)?.[1]; const dataLine = block.match(/^data:\s*(.*)$/m)?.[1]; if (!dataLine) continue;
          let data = {}; try { data = JSON.parse(dataLine); } catch { continue; }
          if (event === "turn.started") {
            responseConversationId = data.conversation_id || responseConversationId;
            if (data.conversation_id && currentConversationId === requestConversationId) {
              currentConversationId = data.conversation_id;
              if (currentUser) localStorage.setItem(`shiju_conversation_${currentUser.id}`, currentConversationId);
            }
          }
          if (event === "assistant.delta") { reply += data.text || ""; replaceMessage(waitingMessage, reply); }
          if (event === "tool.started") agentStatus.textContent = `调用工具：${data.name || "处理中"}`;
          if (event === "tool.completed") {
            agentStatus.textContent = "工具结果已返回";
            if ((data.name === "prepare_generation" || data.name === "prepare_rewrite") && data.output?.ok) {
              appendProposalEditor(data.output.result);
            }
          }
          if (event === "job.submitted") jobs.push(data);
          if (event === "turn.completed") responseConversationId = data.conversation_id || responseConversationId;
          if (event === "turn.failed") throw new Error(data.error || "Agent 执行失败");
        }
      }
    };
    await consume();
    const stillViewingRequest = currentConversationId === requestConversationId || currentConversationId === responseConversationId;
    if (stillViewingRequest) {
      currentConversationId = responseConversationId;
      if (currentConversationId && currentUser) localStorage.setItem(`shiju_conversation_${currentUser.id}`, currentConversationId);
      replaceMessage(waitingMessage, reply || "暂时无法回复。", reply ? "" : "error");
      agentStatus.textContent = "已连接";
      jobs.forEach((job) => startJobProgress(job.job_id, job));
    }
    await loadConversations();
  } catch (error) {
    if (error.name === "AbortError") return;
    replaceMessage(waitingMessage, `暂时无法回复：${error.message}`, "error");
    agentStatus.textContent = "连接异常";
  } finally {
    if (activeChatRequest === requestController) {
      activeChatRequest = null;
      setChatBusy(false);
      chatInput.focus();
    }
  }
});

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

chatInput.addEventListener("input", () => {
  chatInput.style.height = "auto";
  chatInput.style.height = `${Math.min(chatInput.scrollHeight, 140)}px`;
});

chatThread.addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (!button) return;
  chatInput.value = button.dataset.prompt;
  chatInput.focus();
});

document.querySelector("#conversation-search-toggle")?.addEventListener("click", () => {
  const open = conversationSearch.hidden;
  conversationSearch.hidden = !open;
  if (open) conversationSearchInput.focus();
  else { conversationSearchInput.value = ""; filterConversations(); }
});
conversationSearchInput?.addEventListener("input", filterConversations);
document.querySelector("#chat-sidebar-toggle")?.addEventListener("click", () => {
  chatLayout.classList.add("is-sidebar-collapsed");
  document.querySelector("#chat-sidebar-reopen").focus();
});
document.querySelector("#chat-sidebar-reopen")?.addEventListener("click", () => {
  chatLayout.classList.remove("is-sidebar-collapsed");
  document.querySelector("#chat-sidebar-toggle").focus();
});

document.querySelector("#new-chat").addEventListener("click", () => {
  if (!requireLogin()) return;
  activeChatRequest?.abort();
  clearJobProgressPolls();
  clearConversationRefresh();
  conversationLoadVersion += 1;
  activeChatRequest = null;
  chatSessionId = null;
  currentConversationId = null;
  closeProsodyInspector();
  localStorage.removeItem(`shiju_conversation_${currentUser.id}`);
  setChatBusy(false);
  chatThread.innerHTML = initialThreadMarkup;
  chatInput.value = "";
  chatInput.style.height = "";
  agentStatus.textContent = "待连接";
  chatInput.focus();
  announce("已新建对话。");
});

function beginConversationRename(row, conversationId) {
  if (!row || row.classList.contains("is-renaming")) return;
  const titleButton = row.querySelector("button[data-conversation-id]");
  const currentTitle = titleButton?.textContent?.trim() || "新建对话";
  row.classList.add("is-renaming");
  titleButton.hidden = true;
  row.querySelector("[data-rename-conversation]")?.setAttribute("hidden", "true");
  row.querySelector("[data-archive-conversation]")?.setAttribute("hidden", "true");
  const input = document.createElement("input");
  input.className = "conversation-rename-input";
  input.value = currentTitle;
  input.maxLength = 120;
  input.setAttribute("aria-label", "新的对话名称");
  const save = document.createElement("button");
  save.type = "button"; save.className = "conversation-rename-save"; save.dataset.saveConversation = conversationId; save.textContent = "保存";
  const cancel = document.createElement("button");
  cancel.type = "button"; cancel.className = "conversation-rename-cancel"; cancel.dataset.cancelConversation = conversationId; cancel.textContent = "取消";
  row.prepend(input); row.append(save, cancel);
  input.focus(); input.select();
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); save.click(); }
    if (event.key === "Escape") { event.preventDefault(); cancel.click(); }
  });
}

function cancelConversationRename(row) {
  if (!row) return;
  const input = row.querySelector(".conversation-rename-input");
  const titleButton = row.querySelector("button[data-conversation-id]");
  input?.remove();
  row.querySelector("[data-save-conversation]")?.remove();
  row.querySelector("[data-cancel-conversation]")?.remove();
  titleButton.hidden = false;
  row.querySelector("[data-rename-conversation]")?.removeAttribute("hidden");
  row.querySelector("[data-archive-conversation]")?.removeAttribute("hidden");
  row.classList.remove("is-renaming");
}

async function saveConversationRename(row, conversationId) {
  const input = row?.querySelector(".conversation-rename-input");
  const title = input?.value.trim();
  if (!title) { announce("请输入对话名称。"); input?.focus(); return; }
  const save = row.querySelector("[data-save-conversation]");
  save.disabled = true;
  try {
    const updated = await apiFetch(`/v1/conversations/${encodeURIComponent(conversationId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    const titleButton = row.querySelector("button[data-conversation-id]");
    titleButton.textContent = updated.title || title;
    titleButton.setAttribute("aria-label", `打开对话：${updated.title || title}`);
    row.querySelector("[data-rename-conversation]")?.setAttribute("aria-label", `修改对话名称：${updated.title || title}`);
    cancelConversationRename(row);
    announce("对话名称已更新。");
  } catch (error) {
    save.disabled = false;
    announce(`修改名称失败：${error.message}`);
  }
}

document.querySelector("#conversation-list").addEventListener("click", async (event) => {
  const rename = event.target.closest("[data-rename-conversation]");
  if (rename) { beginConversationRename(rename.closest(".conversation-row"), rename.dataset.renameConversation); return; }
  const saveRename = event.target.closest("[data-save-conversation]");
  if (saveRename) { await saveConversationRename(saveRename.closest(".conversation-row"), saveRename.dataset.saveConversation); return; }
  const cancelRename = event.target.closest("[data-cancel-conversation]");
  if (cancelRename) { cancelConversationRename(cancelRename.closest(".conversation-row")); return; }
  const archive = event.target.closest("[data-archive-conversation]");
  if (archive) { pendingArchiveId = archive.dataset.archiveConversation; document.querySelector("#archive-dialog").showModal(); return; }
  const button = event.target.closest("button[data-conversation-id]");
  if (!button) return;
  try { await openConversation(button.dataset.conversationId); }
  catch (error) { announce(`无法打开对话：${error.message}`); }
});

const forumState = { sections: [], sectionId: "", threadId: "", page: 1, replyParentId: "" };

function formatForumTime(value) {
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function forumAvatar(user, className = "thread-avatar") {
  const avatar = document.createElement("div"); avatar.className = className; setUserAvatar(avatar, user); return avatar;
}

function openThreadDialog() {
  if (!requireLogin()) return;
  window.location.hash = "forum/compose";
}

function renderForumCategories() {
  const container = document.querySelector("#forum-categories");
  container.replaceChildren();
  forumState.sections.forEach((section) => {
    const button = document.createElement("button");
    button.type = "button"; button.textContent = section.name;
    button.setAttribute("aria-pressed", String(section.id === forumState.sectionId));
    button.addEventListener("click", () => { forumState.sectionId = section.id; forumState.page = 1; renderForumCategories(); loadForumThreads(); });
    container.append(button);
  });
}

function renderForumThreads(payload) {
  const list = document.querySelector("#thread-list");
  list.replaceChildren();
  const section = forumState.sections.find((item) => item.id === forumState.sectionId);
  document.querySelector("#forum-section-description").textContent = section?.description || "";
  if (!payload.items?.length) { list.innerHTML = '<p class="empty-state">这个分区还没有主题，发布第一篇吧。</p>'; return; }
  payload.items.forEach((thread) => {
    const article = document.createElement("article");
    article.className = `thread-row${thread.is_pinned ? " thread-row--featured" : ""}`;
    article.tabIndex = 0; article.dataset.threadId = thread.id;
    const mark = thread.is_pinned ? document.createElement("div") : profileLink(thread.author, forumAvatar(thread.author), "thread-list-author");
    if (thread.is_pinned) { mark.className = "thread-mark"; mark.textContent = "置"; mark.setAttribute("aria-hidden", "true"); }
    const content = document.createElement("div"); content.className = "thread-content";
    const meta = document.createElement("div"); meta.className = "thread-meta";
    const author = document.createElement("a"); author.href = `#user/${encodeURIComponent(thread.author.id)}`; author.textContent = thread.author.display_name;
    meta.append(author, document.createTextNode(` · ${formatForumTime(thread.updated_at)}`));
    if (thread.last_reply_author) {
      const last = document.createElement("a"); last.href = `#user/${encodeURIComponent(thread.last_reply_author.id)}`; last.textContent = thread.last_reply_author.display_name;
      meta.append(document.createTextNode(" · 最后回复 "), last, document.createTextNode(` ${formatForumTime(thread.last_reply_at)}`));
    }
    const title = document.createElement("h2"); const link = document.createElement("a"); link.href = `#forum/thread/${thread.id}`; link.textContent = thread.title; title.append(link);
    const excerpt = document.createElement("p"); excerpt.textContent = String(thread.content || "").slice(0, 140);
    content.append(meta, title, excerpt);
    const stats = document.createElement("div"); stats.className = "thread-stats"; const count = document.createElement("strong"); count.textContent = thread.reply_count; const label = document.createElement("span"); label.textContent = `回复 · ${thread.view_count || 0} 浏览`; stats.append(count, label);
    if (thread.tags?.length) { const tags = document.createElement("div"); tags.className = "thread-tags"; tags.textContent = thread.tags.map((tag) => `#${tag}#`).join(" "); content.append(tags); }
    article.append(mark, content, stats); list.append(article);
    article.addEventListener("click", (event) => { if (event.target.closest("a")) return; window.location.hash = `forum/thread/${encodeURIComponent(thread.id)}`; });
    article.addEventListener("keydown", (event) => { if (event.key === "Enter") window.location.hash = `forum/thread/${encodeURIComponent(thread.id)}`; });
  });
  const pagination = document.createElement("div"); pagination.className = "forum-pagination";
  const previous = document.createElement("button"); previous.type = "button"; previous.className = "quiet-button"; previous.textContent = "上一页"; previous.disabled = payload.page <= 1; previous.addEventListener("click", () => { forumState.page -= 1; loadForumThreads(); });
  const next = document.createElement("button"); next.type = "button"; next.className = "quiet-button"; next.textContent = "下一页"; next.disabled = payload.page >= payload.pages; next.addEventListener("click", () => { forumState.page += 1; loadForumThreads(); });
  const label = document.createElement("span"); label.textContent = `${payload.page} / ${Math.max(payload.pages || 1, 1)}`; pagination.append(previous, label, next); list.append(pagination);
}

async function loadForumThreads() {
  if (!forumState.sectionId) return;
  const query = document.querySelector("#forum-search-input").value.trim();
  try {
    const sort = document.querySelector("#forum-sort")?.value || "latest";
    const [payload, hotPayload] = await Promise.all([
      apiFetch(`/v1/forum/sections/${encodeURIComponent(forumState.sectionId)}/threads?page=${forumState.page}&limit=30&sort=${sort}${query ? `&q=${encodeURIComponent(query)}` : ""}`),
      apiFetch(`/v1/forum/sections/${encodeURIComponent(forumState.sectionId)}/threads?page=1&limit=5&sort=hot`),
    ]);
    renderForumThreads(payload);
    const section = forumState.sections.find((item) => item.id === forumState.sectionId);
    document.querySelector("#forum-stats").innerHTML = `<div><dt>主题</dt><dd>${payload.total ?? 0}</dd></div><div><dt>回复</dt><dd>${section?.reply_count ?? 0}</dd></div><div><dt>分区</dt><dd>${forumState.sections.length}</dd></div>`;
    const hotList = document.querySelector("#forum-hot-list"); hotList.replaceChildren();
    if (!hotPayload.items?.length) hotList.innerHTML = "<li>暂无热门讨论</li>";
    else hotPayload.items.forEach((thread) => { const item = document.createElement("li"); const link = document.createElement("a"); link.href = `#forum/thread/${thread.id}`; link.textContent = thread.title; item.append(link); hotList.append(item); });
  } catch (error) { document.querySelector("#thread-list").innerHTML = `<p class="empty-state">论坛加载失败：${error.message}</p>`; }
}

async function loadForumData() {
  try {
    const payload = await apiFetch("/v1/forum/sections"); forumState.sections = payload.items || [];
    if (!forumState.sections.some((item) => item.id === forumState.sectionId)) forumState.sectionId = forumState.sections[0]?.id || "";
    renderForumCategories(); await loadForumThreads();
  } catch (error) { document.querySelector("#thread-list").innerHTML = `<p class="empty-state">无法连接论坛：${error.message}</p>`; }
}

function renderForumMarkdown(value) {
  const escaped = String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const blocks = escaped.replace(/```([\s\S]*?)```/g, (_match, code) => `<pre><code>${code.trim()}</code></pre>`);
  return blocks.split(/\n\n+/).map((block) => {
    if (block.startsWith("<pre>")) return block;
    if (/^>/.test(block)) return `<blockquote>${block.replace(/^>\s?/gm, "")}</blockquote>`;
    const lines = block.split("\n").map((line) => line.replace(/^###\s+/, "<strong>").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*(.+?)\*/g, "<em>$1</em>").replace(/`([^`]+)`/g, "<code>$1</code>"));
    return `<p>${lines.join("<br>")}</p>`;
  }).join("");
}

const poemPickerState = { source: "owned", allItems: [], items: [], selected: null, onConfirm: null, query: "" };

async function poemPickerItems(source) {
  if (source === "owned") return ownedPoems;
  if (source === "favorites") return favoritePoems;
  const groups = await Promise.all(profileCollections.map(async (collection) => {
    const payload = await apiFetch(`/v1/profile/poem-collections/${encodeURIComponent(collection.id)}/items`);
    return (payload.items || []).map((poem) => ({ ...poem, collection_name: collection.name }));
  }));
  return [...new Map(groups.flat().map((poem) => [poem.id, poem])).values()];
}

function renderPoemPicker() {
  const list = document.querySelector("#poem-picker-list"); list.replaceChildren();
  const status = document.querySelector("#poem-picker-status");
  const confirm = document.querySelector("#poem-picker-confirm");
  if (!poemPickerState.items.length) {
    list.innerHTML = '<p class="empty-state">这里还没有可分享的诗作。</p>';
    status.textContent = "暂无诗作"; confirm.disabled = true; return;
  }
  const wheel = document.createElement("div"); wheel.className = "poem-picker-wheel";
  poemPickerState.items.forEach((poem) => {
    const option = document.createElement("div"); option.className = "poem-picker-option"; option.tabIndex = 0; option.setAttribute("role", "button"); option.setAttribute("aria-pressed", String(poemPickerState.selected?.id === poem.id));
    const scroll = createPoemHandscroll(poem, { shareable: false }); option.append(scroll);
    const choose = (event) => { if (event.target.closest("button") && event.type === "click") return; poemPickerState.selected = poem; renderPoemPicker(); requestAnimationFrame(() => document.querySelector(`.poem-picker-option[aria-pressed='true']`)?.scrollIntoView({ block: "center" })); };
    option.addEventListener("click", choose); option.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(event); } });
    wheel.append(option);
  });
  list.append(wheel);
  status.textContent = poemPickerState.selected ? `已选择《${poemPickerState.selected.title}》` : `${poemPickerState.items.length} 首 · 滚动翻阅后点击选择`;
  confirm.disabled = !poemPickerState.selected;
}

async function openPoemPicker(onConfirm, preferredPoem = null) {
  if (!requireLogin()) return;
  if (!ownedPoems.length && !favoritePoems.length) await loadPoems();
  if (!profileCollections.length) {
    const collections = await apiFetch("/v1/profile/poem-collections"); profileCollections = collections.items || [];
  }
  poemPickerState.source = "owned"; poemPickerState.allItems = await poemPickerItems("owned"); poemPickerState.items = poemPickerState.allItems; poemPickerState.selected = null; poemPickerState.onConfirm = onConfirm; poemPickerState.query = "";
  document.querySelector("#poem-picker-search").value = "";
  if (preferredPoem?.id) {
    poemPickerState.selected = poemPickerState.items.find((poem) => poem.id === preferredPoem.id) || null;
  }
  document.querySelectorAll("[data-poem-source]").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.poemSource === "owned")));
  renderPoemPicker(); document.querySelector("#poem-picker-dialog").showModal();
}

function renderEditorPoems(container, ids) {
  if (!container) return;
  container.replaceChildren();
  ids.map((id) => profilePoems.find((poem) => poem.id === id)).filter(Boolean).forEach((poem) => container.append(createPoemHandscroll(poem)));
  container.hidden = !container.children.length;
}

function updateComposePreview() {
  const preview = document.querySelector("#compose-preview");
  preview.innerHTML = renderForumMarkdown(document.querySelector("#compose-content").value);
}

function bindEditorTools(root = document) {
  root.querySelectorAll("[data-empty-emoji]").forEach((button) => { if (button.dataset.bound) return; button.dataset.bound = "true"; button.addEventListener("click", () => announce("表情功能将在后续开放")); });
}

bindEditorTools();

document.querySelectorAll("[data-poem-source]").forEach((tab) => tab.addEventListener("click", async () => {
  poemPickerState.source = tab.dataset.poemSource; poemPickerState.allItems = await poemPickerItems(poemPickerState.source); poemPickerState.query = document.querySelector("#poem-picker-search").value; poemPickerState.items = poemPickerState.query ? poemPickerState.allItems.filter((poem) => `${poem.title}\n${poem.content}`.includes(poemPickerState.query)) : poemPickerState.allItems; poemPickerState.selected = null;
  document.querySelectorAll("[data-poem-source]").forEach((item) => item.setAttribute("aria-selected", String(item === tab))); renderPoemPicker();
}));
document.querySelector("#poem-picker-search")?.addEventListener("input", (event) => {
  poemPickerState.query = event.target.value;
  poemPickerState.items = poemPickerState.query ? poemPickerState.allItems.filter((poem) => `${poem.title}\n${poem.content}`.includes(poemPickerState.query)) : poemPickerState.allItems;
  if (poemPickerState.selected && !poemPickerState.items.some((poem) => poem.id === poemPickerState.selected.id)) poemPickerState.selected = null;
  renderPoemPicker();
});
document.querySelector("#poem-picker-close")?.addEventListener("click", () => document.querySelector("#poem-picker-dialog").close());
document.querySelector("#poem-picker-confirm")?.addEventListener("click", () => {
  if (!poemPickerState.selected) return;
  poemPickerState.onConfirm?.(poemPickerState.selected); document.querySelector("#poem-picker-dialog").close();
});

function forumReactionButtons(targetType, targetId, value = {}) {
  const wrap = document.createElement("div"); wrap.className = "forum-reactions";
  [["like", "赞", value.like_count || 0, value.liked_by_me], ["question", "？", value.question_count || 0, value.questioned_by_me]].forEach(([type, label, count, active]) => {
    const button = document.createElement("button"); button.type = "button"; button.dataset.reactionType = type; button.className = active ? "is-active" : ""; button.textContent = `${label} ${count}`;
    button.addEventListener("click", async () => { if (!requireLogin()) return; try { const result = await apiFetch(`/v1/forum/${targetType}/${targetId}/reaction`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reaction_type: type }) }); wrap.querySelectorAll("[data-reaction-type]").forEach((item) => { const kind = item.dataset.reactionType; item.classList.toggle("is-active", Boolean(result.mine?.[kind])); item.textContent = `${kind === "like" ? "赞" : "？"} ${result.counts?.[kind] ?? 0}`; }); } catch (error) { announce(error.message); } }); wrap.append(button);
  });
  return wrap;
}

function profileLink(user, child, className = "") {
  const link = document.createElement("a"); link.href = `#user/${encodeURIComponent(user.id)}`; link.className = className; link.append(child); return link;
}

function replyInteractionTotal(reply) {
  return Number(reply.like_count || 0) + Number(reply.question_count || 0);
}

function collectReplyDescendants(reply, children, result = [], visited = new Set()) {
  const nested = children.get(reply.id) || [];
  nested.forEach((child) => {
    if (visited.has(child.id)) return;
    visited.add(child.id);
    result.push(child);
    collectReplyDescendants(child, children, result, visited);
  });
  return result;
}

function createReplyArticle(reply) {
  const item = document.createElement("article"); item.className = "thread-detail__reply";
  const avatar = profileLink(reply.author, forumAvatar(reply.author, "thread-reply-avatar"), "thread-author-link");
  const replyBody = document.createElement("div"); replyBody.className = "thread-reply-body";
  const meta = document.createElement("div"); meta.className = "thread-reply-meta";
  const author = document.createElement("a"); author.href = `#user/${encodeURIComponent(reply.author.id)}`; author.textContent = reply.author.display_name;
  const time = document.createElement("time"); time.dateTime = new Date(reply.created_at * 1000).toISOString(); time.textContent = formatForumTime(reply.created_at);
  const floor = document.createElement("span"); floor.textContent = `#${reply.floor_no || ""}`;
  meta.append(author, document.createTextNode(" · "), time, document.createTextNode(" · "), floor);
  if (reply.parent_author) { const target = document.createElement("span"); target.className = "thread-reply-target"; target.textContent = `回复 ${reply.parent_author.display_name}`; meta.append(target); }
  const text = document.createElement("div"); text.className = "thread-reply-content";
  (reply.poems || []).forEach((poem) => text.append(createPoemHandscroll(poem, { shareable: false, showTime: true })));
  const markdown = document.createElement("div"); markdown.innerHTML = renderForumMarkdown(reply.content); text.append(markdown);
  const actions = document.createElement("div"); actions.className = "thread-reply-actions";
  const respond = document.createElement("button"); respond.type = "button"; respond.className = "text-button"; respond.textContent = "回复";
  respond.addEventListener("click", () => {
    const activeThread = document.querySelector("[data-view='forum-thread']:not([hidden])");
    forumState.replyParentId = reply.id;
    activeThread.querySelector("#thread-reply-parent").value = reply.id;
    const label = activeThread.querySelector("#thread-reply-target-label");
    label.dataset.replyId = reply.id;
    label.querySelector("span").textContent = `正在回复 ${reply.author.display_name} · #${reply.floor_no}`;
    label.hidden = false;
    activeThread.querySelector("#thread-reply-content").focus();
  });
  actions.append(respond, forumReactionButtons("replies", reply.id, reply));
  if (currentUser?.id === reply.author.id) {
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "text-button text-button--danger"; remove.textContent = "删除";
    remove.addEventListener("click", async () => { if (!window.confirm("删除这条回复？")) return; await apiFetch(`/v1/forum/replies/${reply.id}`, { method: "DELETE" }); await loadThreadPage(); announce("回复已删除"); }); actions.append(remove);
  }
  replyBody.append(meta, text, actions); item.append(avatar, replyBody);
  return item;
}

function replyNode(reply, children, threadId, depth = 0) {
  const details = document.createElement("details");
  details.className = `thread-reply-floor${depth ? " thread-reply-floor--nested" : ""}`;
  details.id = `reply-${reply.id}`; details.open = true;
  const summary = document.createElement("summary"); summary.className = "thread-reply-summary";
  summary.append(forumAvatar(reply.author, "thread-reply-avatar"));
  const summaryText = document.createElement("span"); summaryText.textContent = `${reply.author.display_name}：${String(reply.content || "分享了一首诗作").replace(/\s+/g, " ").slice(0, 42)}`; summary.append(summaryText);
  details.append(summary, createReplyArticle(reply));
  const nested = children.get(reply.id) || [];
  if (nested.length) { const group = document.createElement("div"); group.className = "thread-reply-children"; nested.forEach((child) => group.append(replyNode(child, children, threadId, depth + 1))); details.append(group); }
  return details;
}

function createMobileReplyPreview(reply) {
  const preview = document.createElement("article");
  preview.className = "thread-reply-preview";
  preview.id = `reply-${reply.id}`;
  const author = document.createElement("strong"); author.textContent = reply.author?.display_name || "诗友";
  const copy = document.createElement("p"); copy.textContent = String(reply.content || "分享了一首诗作").replace(/\s+/g, " ").slice(0, 100);
  const stats = document.createElement("span"); stats.className = "thread-reply-preview__stats";
  stats.textContent = `赞 ${reply.like_count || 0} · ？ ${reply.question_count || 0}`;
  preview.append(author, copy, stats);
  return preview;
}

function createMobileExpandedReply(reply, children, threadId, depth = 0) {
  const node = document.createElement("div");
  node.className = `thread-reply-mobile-node${depth ? " thread-reply-mobile-node--nested" : ""}`;
  node.id = `reply-${reply.id}`;
  node.append(createReplyArticle(reply));
  const nested = children.get(reply.id) || [];
  if (nested.length) {
    const group = document.createElement("div"); group.className = "thread-reply-mobile-children thread-reply-mobile-children--expanded";
    [...nested].sort((left, right) => replyInteractionTotal(right) - replyInteractionTotal(left)).forEach((child) => group.append(createMobileExpandedReply(child, children, threadId, depth + 1)));
    node.append(group);
  }
  return node;
}

function createMobileReplyNode(reply, children, threadId, depth = 0) {
  const node = document.createElement("div");
  node.className = `thread-reply-mobile-node${depth ? " thread-reply-mobile-node--nested" : ""}`;
  node.id = `reply-${reply.id}`;
  node.append(createReplyArticle(reply));
  const nested = children.get(reply.id) || [];
  const descendants = collectReplyDescendants(reply, children);
  if (!descendants.length) return node;

  const group = document.createElement("div"); group.className = "thread-reply-mobile-children";
  const ranked = descendants.sort((left, right) => replyInteractionTotal(right) - replyInteractionTotal(left) || Number(right.created_at || 0) - Number(left.created_at || 0));
  const preview = document.createElement("div"); preview.className = "thread-reply-mobile-preview";
  ranked.slice(0, 2).forEach((child) => preview.append(createMobileReplyPreview(child)));
  group.append(preview);
  if (ranked.length >= 2) {
    const remaining = document.createElement("button");
    remaining.type = "button";
    remaining.className = "thread-reply-mobile-more";
    remaining.textContent = ranked.length === 2 ? "查看完整评论" : `查看剩余 ${ranked.length - 2} 条回复`;
    remaining.addEventListener("click", () => {
      group.replaceChildren();
      [...nested].sort((left, right) => replyInteractionTotal(right) - replyInteractionTotal(left) || Number(right.created_at || 0) - Number(left.created_at || 0)).forEach((child) => group.append(createMobileExpandedReply(child, children, threadId, depth + 1)));
    }, { once: true });
    group.append(remaining);
  }
  node.append(group);
  return node;
}

async function loadThreadPage() {
  const match = window.location.hash.match(/^#forum\/thread\/([^/]+)/); const id = match ? decodeURIComponent(match[1]) : ""; if (!id) return;
  const threadBackLink = document.querySelector("#thread-back-link");
  if (threadBackLink) {
    const fromNotifications = notificationFromThread();
    threadBackLink.href = fromNotifications ? "#notifications" : "#forum";
    threadBackLink.textContent = fromNotifications ? "← 返回通知" : "← 返回论坛";
  }
  const container = document.querySelector("#thread-page-content"); container.innerHTML = '<p class="empty-state">正在加载主题……</p>'; forumState.threadId = id; forumState.replyParentId = "";
  try {
    const [thread, replies] = await Promise.all([apiFetch(`/v1/forum/threads/${encodeURIComponent(id)}`), apiFetch(`/v1/forum/threads/${encodeURIComponent(id)}/replies?limit=100`)]);
    container.replaceChildren();
    const heading = document.createElement("header"); heading.className = "thread-page-heading";
    const authorRow = document.createElement("div"); authorRow.className = "thread-author-row";
    const authorCopy = document.createElement("div"); const authorName = document.createElement("a"); authorName.href = `#user/${thread.author.id}`; authorName.textContent = thread.author.display_name;
    const authorTime = document.createElement("span"); authorTime.textContent = `${thread.section_name} · ${formatForumTime(thread.created_at)}`; authorCopy.append(authorName, authorTime);
    authorRow.append(profileLink(thread.author, forumAvatar(thread.author, "thread-author-avatar"), "thread-author-link"), authorCopy);
    const title = document.createElement("h1"); title.id = "thread-page-title"; title.textContent = thread.title;
    const byline = document.createElement("p"); byline.className = "thread-detail__byline"; byline.textContent = `浏览 ${thread.view_count || 0} · 回复 ${thread.reply_count || 0}`; heading.append(authorRow, title, byline);

    const body = document.createElement("article"); body.className = "thread-post thread-post--main";
    (thread.poems || []).forEach((poem) => body.append(createPoemHandscroll(poem, { shareable: false, showTime: true })));
    const markdown = document.createElement("div"); markdown.className = "thread-post-copy"; markdown.innerHTML = renderForumMarkdown(thread.content); body.append(markdown, forumReactionButtons("threads", id, thread));
    const controls = document.createElement("div"); controls.className = "thread-page-actions";
    const follow = document.createElement("button"); follow.type = "button"; follow.className = "quiet-button"; follow.textContent = thread.following ? "取消关注" : "关注主题";
    follow.addEventListener("click", async () => { if (!requireLogin()) return; await apiFetch(`/v1/forum/threads/${id}/follow`, { method: thread.following ? "DELETE" : "POST" }); thread.following = !thread.following; follow.textContent = thread.following ? "取消关注" : "关注主题"; }); controls.append(follow);
    if (currentUser?.id === thread.author.id) { const remove = document.createElement("button"); remove.type = "button"; remove.className = "quiet-button quiet-button--danger"; remove.textContent = "删除主题"; remove.addEventListener("click", async () => { if (!window.confirm("删除这个主题及其讨论？")) return; await apiFetch(`/v1/forum/threads/${id}`, { method: "DELETE" }); window.location.hash = "forum"; announce("主题已删除"); }); controls.append(remove); }

    const replyHeading = document.createElement("h2"); replyHeading.className = "thread-detail__replies-heading"; replyHeading.textContent = `讨论（${replies.total || 0}）`;
    const replyList = document.createElement("div"); replyList.className = "thread-detail__replies";
    const byId = new Map((replies.items || []).map((reply) => [reply.id, reply])); const children = new Map();
    (replies.items || []).forEach((reply) => { if (!reply.parent_reply_id) return; if (!children.has(reply.parent_reply_id)) children.set(reply.parent_reply_id, []); children.get(reply.parent_reply_id).push(reply); });
    const mobileThread = window.matchMedia("(max-width: 760px)").matches;
    (replies.items || []).filter((reply) => !reply.parent_reply_id || !byId.has(reply.parent_reply_id)).forEach((reply) => replyList.append((mobileThread ? createMobileReplyNode : replyNode)(reply, children, id)));

    const form = document.createElement("form"); form.className = "thread-reply-form";
    form.innerHTML = '<input type="hidden" id="thread-reply-parent"><div id="thread-reply-target-label" class="reply-target-label" hidden><span></span><button type="button" aria-label="取消回复目标" title="取消回复">×</button></div><textarea id="thread-reply-content" rows="5" maxlength="20000" required placeholder="写下你的回应……"></textarea><div id="reply-poem-preview" class="editor-poem-preview" hidden></div><div class="editor-actions editor-actions--split"><div class="editor-tools"><button type="button" class="editor-tool" id="thread-reply-share" aria-label="分享诗作" title="分享诗作">+</button><button type="button" class="editor-tool" data-empty-emoji aria-label="表情" title="表情功能暂未开放">:-)</button></div><span class="form-status" id="thread-reply-draft-status"></span><button type="submit" class="primary-button">发送回复</button></div><p class="form-status" id="thread-reply-status"></p>';
    form.querySelector("#thread-reply-target-label button").addEventListener("click", () => { forumState.replyParentId = ""; form.querySelector("#thread-reply-parent").value = ""; delete form.querySelector("#thread-reply-target-label").dataset.replyId; form.querySelector("#thread-reply-target-label").hidden = true; });
    form.querySelector("#thread-reply-share").addEventListener("click", () => openPoemPicker((poem) => { window.forumReplyPoemIds = [poem.id]; renderEditorPoems(form.querySelector("#reply-poem-preview"), window.forumReplyPoemIds); announce(`已选择《${poem.title}》`); }));
    bindEditorTools(form);
    if (currentUser) {
      const replyDraft = (await apiFetch("/v1/forum/drafts?kind=reply")).items?.find((draft) => draft.thread_id === id);
      if (replyDraft) form.querySelector("#thread-reply-content").value = replyDraft.content || "";
      form.querySelector("#thread-reply-content").addEventListener("input", (event) => {
        window.clearTimeout(event.target._draftTimer);
        event.target._draftTimer = window.setTimeout(() => apiFetch("/v1/forum/drafts", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "reply", thread_id: id, content: event.target.value }) }).then(() => { form.querySelector("#thread-reply-draft-status").textContent = "草稿已保存"; }).catch((error) => { form.querySelector("#thread-reply-draft-status").textContent = error.message; }), 700);
      });
    }
    form.addEventListener("submit", async (event) => { event.preventDefault(); if (!requireLogin()) return; const content = form.querySelector("#thread-reply-content").value.trim(); const parentReplyId = forumState.replyParentId || form.querySelector("#thread-reply-target-label").dataset.replyId || null; try { await apiFetch(`/v1/forum/threads/${id}/replies`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, parent_reply_id: parentReplyId, poem_ids: window.forumReplyPoemIds || [] }) }); window.forumReplyPoemIds = []; forumState.replyParentId = ""; await loadThreadPage(); announce("回复已发送"); } catch (error) { form.querySelector("#thread-reply-status").textContent = error.message; } });
    container.append(heading, body, controls, replyHeading, replyList, form);
    const anchorMatch = window.location.hash.match(/\/reply\/([^/?]+)(?:\?|$)/);
    if (anchorMatch) requestAnimationFrame(() => document.querySelector(`#reply-${CSS.escape(decodeURIComponent(anchorMatch[1]))}`)?.scrollIntoView({ block: "center" }));
  } catch (error) { container.innerHTML = `<p class="empty-state">无法打开主题：${error.message}</p>`; }
}

async function loadComposePage() {
  if (!requireLogin()) return;
  const select = document.querySelector("#compose-section"); if (!select.options.length) { const payload = await apiFetch("/v1/forum/sections"); (payload.items || []).forEach((section) => select.add(new Option(section.name, section.id))); if (forumState.sectionId) select.value = forumState.sectionId; }
  const form = document.querySelector("#compose-form");
  const draft = (await apiFetch("/v1/forum/drafts?kind=thread")).items?.[0];
  if (draft && !form.querySelector("#compose-title").value && !form.querySelector("#compose-content").value) {
    form.querySelector("#compose-title").value = draft.title || "";
    form.querySelector("#compose-content").value = draft.content || "";
    form.querySelector("#compose-tags").value = (draft.tags || []).map((tag) => `#${tag}#`).join(" ");
    if (draft.section_id && [...select.options].some((option) => option.value === draft.section_id)) select.value = draft.section_id;
    updateComposePreview();
  }
  const shared = sessionStorage.getItem("shiju_share_poem");
  if (shared) {
    const value = JSON.parse(shared); if (!profilePoems.length) await loadPoems();
    const poem = profilePoems.find((item) => item.id === value.id) || profilePoems.find((item) => item.title === value.title && item.content === value.content);
    if (poem) { window.forumComposePoemIds = [poem.id]; renderEditorPoems(document.querySelector("#compose-poem-preview"), window.forumComposePoemIds); updateComposePreview(); }
    else announce("这首诗作尚未保存，请在生成完成后再分享。");
    sessionStorage.removeItem("shiju_share_poem");
  }
}

let notificationItems = [];

function notificationCopy(type) {
  return {
    reply: "回复了你的主题",
    thread_followed: "在你关注的主题中发表了新回复",
    reaction_like: "赞了你的内容",
    reaction_question: "对你的内容表示疑惑",
    report_resolved: "处理了你的举报",
  }[type] || "有一条新通知";
}

function notificationDestination(item) {
  if (!item.thread_id) return "notifications";
  const threadId = encodeURIComponent(item.thread_id);
  const replyPath = item.reply_id ? `/reply/${encodeURIComponent(item.reply_id)}` : "";
  return `forum/thread/${threadId}${replyPath}?from=notifications`;
}

function notificationFromThread() {
  return new URLSearchParams(window.location.hash.split("?")[1] || "").get("from") === "notifications";
}

async function openNotification(item) {
  try {
    if (!item.read_at) {
      await apiFetch(`/v1/forum/notifications/read?notification_id=${encodeURIComponent(item.id)}`, { method: "POST" });
      item.read_at = Date.now() / 1000;
    }
    if (item.thread_id) window.location.hash = notificationDestination(item);
    else await loadNotifications();
  } catch (error) { announce(`通知处理失败：${error.message}`); }
}

function renderNotificationList(items = notificationItems) {
  const list = document.querySelector("#notification-list");
  if (!list) return;
  list.replaceChildren();
  const visibleItems = items;
  if (!visibleItems.length) {
    const empty = document.createElement("p"); empty.className = "empty-state";
    empty.textContent = "暂无通知。";
    list.append(empty); return;
  }
  visibleItems.forEach((item) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `notification-row${item.read_at ? "" : " is-unread"}`;
    const actor = { display_name: item.actor_display_name || "有人", username: item.actor_username, avatar_url: item.actor_avatar_url };
    row.append(forumAvatar(actor, "notification-row__avatar"));

    const body = document.createElement("span"); body.className = "notification-row__body";
    const title = document.createElement("span"); title.className = "notification-row__title";
    const name = document.createElement("strong"); name.textContent = actor.display_name;
    const action = document.createElement("span"); action.textContent = notificationCopy(item.notification_type);
    title.append(name, action);
    const originalContent = item.payload?.content || item.content || "";
    const excerpt = document.createElement("span"); excerpt.className = "notification-row__excerpt"; excerpt.textContent = originalContent;
    const meta = document.createElement("span"); meta.className = "notification-row__meta";
    const time = document.createElement("time"); time.dateTime = new Date(Number(item.created_at) * 1000).toISOString(); time.textContent = formatForumTime(item.created_at);
    const target = document.createElement("span"); target.textContent = item.thread_id ? "查看讨论" : "查看详情";
    meta.append(time, target); body.append(title); if (originalContent) body.append(excerpt); body.append(meta); row.append(body);
    row.addEventListener("click", () => openNotification(item));
    list.append(row);
  });
}

async function loadNotifications() {
  if (!requireLogin()) return;
  try {
    const payload = await apiFetch("/v1/forum/notifications");
    notificationItems = payload.items || [];
    renderNotificationList();
    await renderDrawerNotifications(payload);
  } catch (error) {
    const list = document.querySelector("#notification-list");
    if (list) list.innerHTML = `<p class="empty-state">无法加载通知：${error.message}</p>`;
  }
}

async function renderDrawerNotifications(payload) {
  const badge = document.querySelector("#header-notification-badge");
  const unread = Number(payload?.unread || 0);
  if (badge) { badge.textContent = unread > 99 ? "99+" : String(unread); badge.hidden = unread < 1; }
  const list = document.querySelector("#drawer-notification-list");
  if (!list) return;
  list.replaceChildren();
  const items = (payload?.items || []).slice(0, 3);
  if (!items.length) { list.innerHTML = '<p class="drawer-empty">暂无新通知</p>'; return; }
  items.forEach((item) => {
    const row = document.createElement("button"); row.type = "button"; row.className = `drawer-notification${item.read_at ? "" : " is-unread"}`;
    const actor = item.actor_display_name || "有人";
    const copy = document.createElement("span"); copy.className = "drawer-notification__copy";
    const title = document.createElement("strong"); title.textContent = `${actor} ${notificationCopy(item.notification_type)}`;
    const originalContent = item.payload?.content || item.content || "";
    const excerpt = document.createElement("small"); excerpt.className = "drawer-notification__excerpt"; excerpt.textContent = originalContent;
    copy.append(title); if (originalContent) copy.append(excerpt);
    const time = document.createElement("time"); time.textContent = formatForumTime(item.created_at);
    row.append(copy, time);
    row.addEventListener("click", () => { closeDrawers(); openNotification(item); });
    list.append(row);
  });
}

async function loadDrawerNotifications() {
  if (!currentUser) { renderDrawerNotifications({ items: [], unread: 0 }); return; }
  try { await renderDrawerNotifications(await apiFetch("/v1/forum/notifications?limit=5")); } catch { renderDrawerNotifications({ items: [], unread: 0 }); }
}

async function loadPublicProfile() {
  const match = window.location.hash.match(/^#user\/([^/]+)/); if (!match) return;
  const container = document.querySelector("#public-profile-content");
  try {
    const user = await apiFetch(`/v1/forum/users/${encodeURIComponent(decodeURIComponent(match[1]))}`);
    container.replaceChildren();
    const heading = document.createElement("header"); heading.className = "public-profile-heading";
    const avatar = forumAvatar(user, "user-avatar user-avatar--large");
    const identity = document.createElement("div"); const eyebrow = document.createElement("p"); eyebrow.className = "eyebrow"; eyebrow.textContent = "诗友主页";
    const title = document.createElement("h1"); title.id = "public-profile-title"; title.textContent = user.display_name || user.username;
    const signature = document.createElement("p"); signature.className = "public-profile-signature"; signature.textContent = user.bio || "这位诗友还没有写下签名。";
    const meta = document.createElement("p"); meta.className = "public-profile-meta"; meta.textContent = `@${user.username} · ${formatForumTime(user.created_at)} 加入 · ${user.following_count || 0} 关注 · ${user.follower_count || 0} 粉丝`;
    identity.append(eyebrow, title, signature, meta); heading.append(avatar, identity); container.append(heading);

    const section = (label, count) => { const node = document.createElement("section"); node.className = "public-profile-section"; const h2 = document.createElement("h2"); h2.textContent = `${label}（${count}）`; node.append(h2); container.append(node); return node; };
    const poems = section("公开作品", user.poems?.length || 0);
    if (user.poems?.length) user.poems.forEach((poem) => poems.append(createPoemHandscroll(poem, { shareable: false, showTime: true })));
    else poems.insertAdjacentHTML("beforeend", '<p class="empty-state">暂未公开诗作。</p>');
    const threads = section("发布的主题", user.threads?.length || 0); const threadList = document.createElement("div"); threadList.className = "public-activity-list";
    (user.threads || []).forEach((thread) => { const link = document.createElement("a"); link.href = `#forum/thread/${thread.id}`; link.innerHTML = `<strong></strong><span>${formatForumTime(thread.created_at)} · ${thread.view_count || 0} 浏览</span>`; link.querySelector("strong").textContent = thread.title; threadList.append(link); });
    threads.append(threadList); if (!user.threads?.length) threads.insertAdjacentHTML("beforeend", '<p class="empty-state">暂未发布主题。</p>');
    const replies = section("参与的讨论", user.replies?.length || 0); const replyList = document.createElement("div"); replyList.className = "public-activity-list";
    (user.replies || []).forEach((reply) => { const link = document.createElement("a"); link.href = `#forum/thread/${reply.thread_id}/reply/${reply.id}`; const strong = document.createElement("strong"); strong.textContent = `${reply.thread_title} · #${reply.floor_no}`; const excerpt = document.createElement("span"); excerpt.textContent = `${String(reply.content).replace(/\s+/g, " ").slice(0, 90)} · ${formatForumTime(reply.created_at)}`; link.append(strong, excerpt); replyList.append(link); });
    replies.append(replyList); if (!user.replies?.length) replies.insertAdjacentHTML("beforeend", '<p class="empty-state">暂未参与讨论。</p>');
  } catch (error) { container.innerHTML = `<p class="empty-state">无法加载用户资料：${error.message}</p>`; }
}

function composeTags() { return [...document.querySelector("#compose-tags").value.matchAll(/#([^#\s]+)#/g)].map((match) => match[1]); }

async function saveComposeDraft() {
  try {
    await apiFetch("/v1/forum/drafts", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "thread", section_id: document.querySelector("#compose-section").value, title: document.querySelector("#compose-title").value, content: document.querySelector("#compose-content").value, tags: composeTags() }) });
    document.querySelector("#draft-status").textContent = "草稿已保存";
  } catch (error) { document.querySelector("#draft-status").textContent = error.message; }
}

document.querySelector("#compose-form")?.addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; const section = document.querySelector("#compose-section").value; try { const created = await apiFetch(`/v1/forum/sections/${section}/threads`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: document.querySelector("#compose-title").value.trim(), content: document.querySelector("#compose-content").value.trim(), tags: composeTags(), poem_ids: window.forumComposePoemIds || [] }) }); window.forumComposePoemIds = []; form.reset(); document.querySelector("#compose-poem-preview").replaceChildren(); document.querySelector("#compose-poem-preview").hidden = true; document.querySelector("#compose-preview").replaceChildren(); document.querySelector("#draft-status").textContent = ""; announce("主题已发布"); window.location.hash = `forum/thread/${created.id}`; } catch (error) { document.querySelector("#draft-status").textContent = error.message; } });
document.querySelector("#share-poem-button")?.addEventListener("click", () => openPoemPicker((poem) => { window.forumComposePoemIds = [poem.id]; renderEditorPoems(document.querySelector("#compose-poem-preview"), window.forumComposePoemIds); updateComposePreview(); announce(`已选择《${poem.title}》`); }));
document.querySelectorAll("#compose-title, #compose-tags, #compose-section, #compose-content").forEach((input) => input.addEventListener(input.tagName === "SELECT" ? "change" : "input", () => { if (input.id === "compose-content") updateComposePreview(); window.clearTimeout(document.querySelector("#compose-form")._draftTimer); document.querySelector("#draft-status").textContent = "保存中……"; document.querySelector("#compose-form")._draftTimer = window.setTimeout(saveComposeDraft, 700); }));
document.querySelectorAll("[data-editor-tab]").forEach((tab) => tab.addEventListener("click", () => { document.querySelectorAll("[data-editor-tab]").forEach((item) => item.classList.toggle("is-active", item === tab)); const preview = tab.dataset.editorTab === "preview"; document.querySelector("#compose-content").hidden = preview; document.querySelector("#compose-preview").hidden = !preview; }));
document.querySelector("#mark-notifications-read")?.addEventListener("click", async () => { await apiFetch("/v1/forum/notifications/read", { method: "POST" }); await loadNotifications(); });
document.querySelector("#forum-publish-button").addEventListener("click", openThreadDialog);

let pendingArchiveId = null;
document.querySelector("#archive-dialog").addEventListener("close", async (event) => {
  if (event.target.returnValue !== "confirm" || !pendingArchiveId) { pendingArchiveId = null; return; }
  const id = pendingArchiveId; pendingArchiveId = null;
  try { await apiFetch(`/v1/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }); if (currentConversationId === id) { currentConversationId = null; chatSessionId = null; chatThread.innerHTML = initialThreadMarkup; } await loadConversations(); await loadProfileData(); announce("对话已归档"); } catch (error) { announce(`归档失败：${error.message}`); }
});

function renderUserRows(container, users, following = false) {
  container.replaceChildren();
  if (!users.length) { container.innerHTML = `<p class="empty-state">${following ? "还没有关注诗友。" : "没有找到用户。"}</p>`; return; }
  users.filter((user) => user.id !== currentUser?.id).forEach((user) => {
    const row = document.createElement("article"); row.className = "profile-row";
    const text = document.createElement("div"); const name = document.createElement("a"); name.href = `#user/${encodeURIComponent(user.id)}`; const strong = document.createElement("strong"); strong.textContent = user.display_name || user.username; name.append(strong); const username = document.createElement("span"); username.textContent = `@${user.username}`; text.append(name, username);
    const button = document.createElement("button"); button.type = "button"; button.textContent = following ? "取消关注" : "关注";
    button.addEventListener("click", async () => { try { await apiFetch(`/v1/forum/users/${user.id}/follow`, { method: following ? "DELETE" : "POST" }); await loadProfileData(); announce(following ? "已取消关注。" : "已关注诗友。"); } catch (error) { announce(error.message); } });
    row.append(text, button); container.append(row);
  });
}

document.querySelector("#user-search-input")?.addEventListener("input", (event) => {
  const query = event.target.value.trim(); window.clearTimeout(event.target.searchTimer);
  if (!query) { document.querySelector("#user-search-results").replaceChildren(); return; }
  event.target.searchTimer = window.setTimeout(async () => { try { const payload = await apiFetch(`/v1/forum/users/search?q=${encodeURIComponent(query)}&limit=20`); renderUserRows(document.querySelector("#user-search-results"), payload.items || [], false); } catch (error) { announce(error.message); } }, 250);
});
document.querySelector("#forum-search-input").addEventListener("input", () => { window.clearTimeout(forumState.searchTimer); forumState.searchTimer = window.setTimeout(loadForumThreads, 260); });
document.querySelector("#forum-sort")?.addEventListener("change", () => { forumState.page = 1; loadForumThreads(); });

async function loadAdminData() {
  if (!currentUser) { if (!authToken) requireLogin(); return; }
  if (currentUser.role !== "admin") { announce("只有管理员可以进入管理后台。"); window.location.hash = "forum"; return; }
  try {
    const [stats, users, reports, sections] = await Promise.all([apiFetch("/v1/admin/stats"), apiFetch("/v1/admin/users?limit=100"), apiFetch("/v1/admin/reports?report_status=open"), apiFetch("/v1/forum/sections")]);
    const statsNode = document.querySelector("#admin-stats"); statsNode.replaceChildren(); Object.entries(stats).forEach(([key, value]) => { const item = document.createElement("div"); item.className = "admin-stat"; const valueNode = document.createElement("strong"); valueNode.textContent = value; const label = document.createElement("span"); label.textContent = { users: "用户", forum_sections: "分区", forum_threads: "主题", forum_replies: "回复", forum_reports: "举报" }[key] || key; item.append(valueNode, label); statsNode.append(item); });
    const userList = document.querySelector("#admin-user-list"); userList.replaceChildren(); (users.items || []).forEach((user) => { const row = document.createElement("tr"); const name = document.createElement("td"); name.textContent = `${user.display_name}（${user.username}）`; const role = document.createElement("td"); const select = document.createElement("select"); ["user", "admin"].forEach((value) => select.add(new Option(value === "admin" ? "管理员" : "用户", value))); select.value = user.role; select.disabled = user.username === "admin" || user.id === currentUser.id; select.addEventListener("change", async () => { try { await apiFetch(`/v1/admin/users/${user.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: select.value }) }); announce("用户角色已更新。"); } catch (error) { announce(error.message); select.value = user.role; } }); role.append(select); const created = document.createElement("td"); created.textContent = formatForumTime(user.created_at); const actions = document.createElement("td"); if (user.username !== "admin" && user.id !== currentUser.id) { const button = document.createElement("button"); button.className = "text-button"; button.type = "button"; button.textContent = "删除"; button.addEventListener("click", async () => { if (!window.confirm(`删除用户 ${user.username}？`)) return; try { await apiFetch(`/v1/admin/users/${user.id}`, { method: "DELETE" }); await loadAdminData(); } catch (error) { announce(error.message); } }); actions.append(button); } row.append(name, role, created, actions); userList.append(row); });
    const reportList = document.querySelector("#admin-report-list"); reportList.replaceChildren(); if (!reports.items?.length) reportList.innerHTML = '<p class="empty-state">暂无待处理举报。</p>'; else reports.items.forEach((report) => { const item = document.createElement("article"); item.className = "admin-report"; const text = document.createElement("p"); text.textContent = `${report.reason} · ${report.reporter_username}`; const button = document.createElement("button"); button.className = "text-button"; button.type = "button"; button.textContent = "标记已处理"; button.addEventListener("click", async () => { await apiFetch(`/v1/admin/reports/${report.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "resolved", note: "管理员已审核" }) }); await loadAdminData(); }); item.append(text, button); reportList.append(item); });
    const sectionList = document.querySelector("#admin-section-list"); sectionList.replaceChildren(); (sections.items || []).forEach((section) => { const row = document.createElement("article"); row.className = "profile-row"; const text = document.createElement("div"); const name = document.createElement("strong"); name.textContent = section.name; const slug = document.createElement("span"); slug.textContent = `${section.slug} · ${section.thread_count} 个主题`; text.append(name, slug); const actions = document.createElement("div"); actions.className = "profile-row__actions"; const lock = document.createElement("button"); lock.type = "button"; lock.textContent = section.is_locked ? "解除锁定" : "锁定"; lock.addEventListener("click", async () => { try { await apiFetch(`/v1/admin/sections/${section.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_locked: !section.is_locked }) }); await loadAdminData(); } catch (error) { announce(error.message); } }); actions.append(lock); row.append(text, actions); sectionList.append(row); });
  } catch (error) { announce(`管理数据加载失败：${error.message}`); }
}

document.querySelector("#admin-refresh").addEventListener("click", loadAdminData);
document.querySelector("#admin-section-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await apiFetch("/v1/admin/sections", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: document.querySelector("#admin-section-name").value.trim(), slug: document.querySelector("#admin-section-slug").value.trim(), description: "", sort_order: forumState.sections.length * 10 + 10 }) }); event.target.reset(); await loadAdminData(); announce("分区已创建。"); } catch (error) { announce(error.message); } });
document.querySelector("#profile-form").addEventListener("submit", async (event) => { event.preventDefault(); if (!requireLogin()) return; const status = document.querySelector("#profile-status"); status.textContent = "保存中……"; try { currentUser = await apiFetch("/v1/profile/me", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name: document.querySelector("#profile-display-name").value.trim(), bio: document.querySelector("#profile-bio").value.trim(), notify_on_reaction: document.querySelector("#profile-notify-reactions").checked }) }); updateAuthUi(); status.textContent = "已保存"; } catch (error) { status.textContent = error.message; } });

loadCurrentUser();

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

showRoute(window.location.hash ? routeFromHash() : "chat", { scroll: false });
setupInkLandscape();
