import { evaluateGeneratedPoem } from "./prosody-evaluation.js?v=1";

const routeTitles = {
  home: "诗矩 · 中文诗词创作空间",
  chat: "AI 对话 · 诗矩",
  prosody: "格律检测 · 诗矩",
  forum: "诗友论坛 · 诗矩",
  profile: "个人中心 · 诗矩",
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
  if (resolvedRoute === "profile" && currentUser) loadProfileData();
  if (!prosodyInspector.hidden) closeProsodyInspector();
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
    if (button.dataset.demoAction === "login") {
      document.querySelector("#login-dialog").showModal();
      document.querySelector("#login-username").focus();
      return;
    }
    const labels = { publish: "发帖功能将在后续接入。" };
    announce(labels[button.dataset.demoAction] ?? "此功能目前仅作样式展示。");
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
    authToken = payload.token;
    currentUser = payload.user;
    localStorage.setItem("shiju_token", authToken);
    updateAuthUi();
    document.querySelector("#login-dialog").close();
    status.textContent = "";
    await loadConversations({ restore: true });
    await loadProfileData();
    announce(`欢迎回来，${currentUser.display_name}`);
  } catch (error) { status.textContent = error.message; }
});
document.querySelector("#logout-button").addEventListener("click", async () => {
  try { await apiFetch("/v1/auth/logout", { method: "POST" }); } catch { /* local token is still cleared */ }
  clearJobProgressPolls();
  clearConversationRefresh();
  authToken = ""; currentUser = null; currentConversationId = null;
  localStorage.removeItem("shiju_token"); updateAuthUi(); announce("已退出登录。");
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
const chatSubmit = chatForm.querySelector("button[type='submit']");
const agentStatus = document.querySelector("#agent-status");
const initialThreadMarkup = chatThread.innerHTML;
let chatSessionId = null;
let activeChatRequest = null;
let chatBusy = false;
const activeJobPolls = new Map();
let conversationRefreshTimer = null;
let conversationLoadVersion = 0;
let activeConversationEvents = null;

async function loadConversations({ restore = false } = {}) {
  if (!currentUser) return;
  try {
    const payload = await apiFetch("/v1/conversations");
    const list = document.querySelector("#conversation-list");
    list.innerHTML = "";
    if (!payload.items.length) { list.innerHTML = "<p>还没有历史对话</p>"; return; }
    const heading = document.createElement("p"); heading.textContent = "历史对话"; list.append(heading);
    payload.items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button"; button.textContent = item.title || "新建对话"; button.dataset.conversationId = item.id;
      if (item.id === currentConversationId) button.setAttribute("aria-current", "true");
      list.append(button);
    });
    if (restore) {
      const savedId = localStorage.getItem(`shiju_conversation_${currentUser.id}`);
      const target = payload.items.find((item) => item.id === savedId) || payload.items[0];
      if (target) await openConversation(target.id);
    }
  } catch { /* 登录状态可能已过期，发送消息时会提示 */ }
}

async function openConversation(conversationId) {
  if (!requireLogin()) return;
  const loadVersion = ++conversationLoadVersion;
  const payload = await apiFetch(`/v1/conversations/${encodeURIComponent(conversationId)}`);
  if (loadVersion !== conversationLoadVersion) return;
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
  document.querySelectorAll("#conversation-list button").forEach((button) => button.toggleAttribute("aria-current", button.dataset.conversationId === payload.id));
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

function createPoemHandscroll(poem, { resultLabel = "", showTime = false, evaluationPending = false } = {}) {
  const value = parsePoemFields(poem);
  const article = document.createElement("article");
  article.className = `poem-handscroll${isSongCi(value) ? " poem-handscroll--ci" : ""}`;

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
  heading.append(kind, title, seal);

  const evaluation = value.evaluation;
  const scorePanel = document.createElement("div");
  scorePanel.className = "poem-score";
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
    scorePanel.append(scoreBook, scoreGrid);
  } else {
    scorePanel.classList.add("poem-score--pending");
    scorePanel.textContent = evaluationPending ? "格律评分中" : "暂无评分";
  }

  const verses = document.createElement("div");
  verses.className = "poem-handscroll__verses";
  const stanzas = poemStanzas(value.content);
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
  paper.append(heading, scorePanel, verses);

  const scoreFooter = document.createElement("footer");
  scoreFooter.className = "poem-handscroll__footer poem-handscroll__footer--score";
  const inspect = document.createElement("button");
  inspect.type = "button";
  inspect.className = "poem-score__inspect";
  inspect.textContent = evaluation ? "格律评分" : (evaluationPending ? "评分中" : "暂无评分");
  inspect.disabled = !evaluation;
  if (evaluation) inspect.addEventListener("click", () => openProsodyInspector(evaluation, value.title));
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
  scoreFooter.append(inspect, flags);
  paper.append(scoreFooter);

  if (showTime && value.created_at) {
    const time = document.createElement("time");
    time.dateTime = new Date(value.created_at * 1000).toISOString();
    time.textContent = new Date(value.created_at * 1000).toLocaleString("zh-CN");
    scoreFooter.prepend(time);
  }

  article.append(leftRoller, paper, rightRoller);
  return article;
}

function poemCard(poem) {
  const value = parsePoemFields(poem);
  const article = createPoemHandscroll(value, { showTime: true });
  article.dataset.poemId = value.id;
  const actions = document.createElement("div"); actions.className = "poem-card__actions";
  const favorite = document.createElement("button"); favorite.type = "button"; favorite.dataset.poemAction = "favorite"; favorite.title = value.favorite ? "取消收藏" : "收藏"; favorite.setAttribute("aria-label", favorite.title); favorite.textContent = value.favorite ? "★" : "☆";
  const collect = document.createElement("button"); collect.type = "button"; collect.dataset.poemAction = "collect"; collect.textContent = "加入合集";
  const remove = document.createElement("button"); remove.type = "button"; remove.dataset.poemAction = "delete"; remove.textContent = "删除";
  actions.append(favorite, collect, remove);
  let footer = article.querySelector(".poem-handscroll__footer");
  if (!footer) {
    footer = document.createElement("footer");
    footer.className = "poem-handscroll__footer";
    article.querySelector(".poem-handscroll__paper").append(footer);
  }
  footer.append(actions);
  return article;
}

function renderPoemList(container, poems, emptyText) {
  container.replaceChildren();
  if (!poems.length) { const empty = document.createElement("p"); empty.className = "empty-state"; empty.textContent = emptyText; container.append(empty); return; }
  container.append(...poems.map(poemCard));
}

async function loadPoems() {
  if (!currentUser) return;
  const payload = await apiFetch("/v1/profile/poems"); profilePoems = payload.items || [];
  const type = document.querySelector("#profile-work-type")?.value || "";
  renderPoemList(document.querySelector("#poem-list"), profilePoems.filter((poem) => !type || poem.work_type === type), "暂无诗作记录。完成一次格律生成后，作品会自动归档到这里。");
  renderPoemList(document.querySelector("#favorite-list"), profilePoems.filter((poem) => poem.favorite), "还没有收藏作品。");
  document.querySelector("#profile-poem-count").textContent = profilePoems.length;
  document.querySelector("#profile-favorite-count").textContent = profilePoems.filter((poem) => poem.favorite).length;
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
  try {
    const [collections, folders, conversations] = await Promise.all([
      apiFetch("/v1/profile/poem-collections"), apiFetch("/v1/conversation-folders"), apiFetch("/v1/conversations?include_deleted=true"), loadPoems(),
    ]);
    profileCollections = collections.items || [];
    const collectionList = document.querySelector("#collection-list"); collectionList.replaceChildren();
    if (!profileCollections.length) collectionList.innerHTML = '<p class="empty-state">还没有作品合集。</p>';
    else profileCollections.forEach((item) => {
      const row = document.createElement("article"); row.className = "profile-row"; row.dataset.collectionId = item.id;
      row.innerHTML = `<div><strong></strong><span></span></div><button type="button" data-collection-action="delete">删除</button>`;
      row.querySelector("strong").textContent = item.name; row.querySelector("span").textContent = `${item.count} 首作品`; collectionList.append(row);
    });
    renderFolderManager(folders.items || [], (conversations.items || []).filter((item) => !item.deleted_at));
    renderTrash((conversations.items || []).filter((item) => item.deleted_at));
  } catch (error) { announce(`个人中心加载失败：${error.message}`); }
}

function renderFolderManager(folders, conversations) {
  const list = document.querySelector("#folder-list"); list.replaceChildren();
  folders.forEach((folder) => {
    const row = document.createElement("article"); row.className = "profile-row";
    const count = conversations.filter((item) => item.folder_id === folder.id).length;
    row.innerHTML = `<div><strong></strong><span></span></div>`; row.querySelector("strong").textContent = folder.name; row.querySelector("span").textContent = `${count} 个对话`; list.append(row);
  });
  conversations.forEach((conversation) => {
    const row = document.createElement("article"); row.className = "profile-row profile-row--conversation"; row.dataset.conversationId = conversation.id;
    const text = document.createElement("div"); const name = document.createElement("strong"); name.textContent = conversation.title; text.append(name);
    const select = document.createElement("select"); select.dataset.conversationFolder = conversation.id; select.append(new Option("未分类", "")); folders.forEach((folder) => select.append(new Option(folder.name, folder.id))); select.value = conversation.folder_id || "";
    const remove = document.createElement("button"); remove.type = "button"; remove.dataset.conversationAction = "delete"; remove.textContent = "移至回收站";
    row.append(text, select, remove); list.append(row);
  });
  if (!list.children.length) list.innerHTML = '<p class="empty-state">还没有文件夹或对话。</p>';
}

function renderTrash(items) {
  const list = document.querySelector("#trash-list"); list.replaceChildren();
  if (!items.length) { list.innerHTML = '<p class="empty-state">回收站为空。</p>'; return; }
  items.forEach((item) => {
    const row = document.createElement("article"); row.className = "profile-row"; row.dataset.conversationId = item.id;
    row.innerHTML = `<div><strong></strong><span></span></div><div class="profile-row__actions"><button type="button" data-trash-action="restore">恢复</button><button type="button" data-trash-action="permanent">永久删除</button></div>`;
    row.querySelector("strong").textContent = item.title; row.querySelector("span").textContent = `删除于 ${new Date(item.deleted_at * 1000).toLocaleString("zh-CN")}`; list.append(row);
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

document.querySelector("#new-folder-button")?.addEventListener("click", async () => {
  const name = window.prompt("文件夹名称"); if (!name?.trim()) return;
  try { await apiFetch("/v1/conversation-folders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() }) }); await loadProfileData(); } catch (error) { announce(`创建文件夹失败：${error.message}`); }
});

document.querySelector("#folder-list")?.addEventListener("change", async (event) => {
  const select = event.target.closest("[data-conversation-folder]"); if (!select) return;
  try { await apiFetch(`/v1/conversations/${select.dataset.conversationFolder}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(select.value ? { folder_id: select.value } : { clear_folder: true }) }); await loadProfileData(); } catch (error) { announce(`移动对话失败：${error.message}`); }
});

document.querySelector("#folder-list")?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-conversation-action='delete']"); if (!button) return;
  const row = button.closest("[data-conversation-id]");
  try { await apiFetch(`/v1/conversations/${row.dataset.conversationId}`, { method: "DELETE" }); await loadProfileData(); } catch (error) { announce(`删除对话失败：${error.message}`); }
});

document.querySelector("#trash-list")?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-trash-action]"); if (!button) return;
  const row = button.closest("[data-conversation-id]"); const id = row.dataset.conversationId;
  try { const path = button.dataset.trashAction === "restore" ? `/v1/conversations/${id}/restore` : `/v1/conversations/${id}/permanent`; if (button.dataset.trashAction === "permanent" && !window.confirm("永久删除这个对话？")) return; await apiFetch(path, { method: button.dataset.trashAction === "restore" ? "POST" : "DELETE" }); await loadProfileData(); } catch (error) { announce(`回收站操作失败：${error.message}`); }
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
  document.querySelector("#login-button").hidden = Boolean(currentUser);
  document.querySelector("#logout-button").hidden = !currentUser;
  document.querySelector("#chat-user-status").textContent = currentUser ? `已登录：${currentUser.display_name}` : "未登录，请先登录";
  document.querySelector("#profile-user-label").textContent = currentUser ? `${currentUser.display_name} 的创作档案` : "登录后查看你生成的全部诗词。";
}

async function loadCurrentUser() {
  if (!authToken) return updateAuthUi();
  try { currentUser = await apiFetch("/v1/auth/me"); }
  catch { authToken = ""; localStorage.removeItem("shiju_token"); }
  updateAuthUi();
  if (currentUser) { await loadConversations({ restore: true }); await loadProfileData(); }
}

function appendMessage(text, role, state = "") {
  const article = document.createElement("article");
  article.className = `chat-message chat-message--${role}`;
  if (state) article.classList.add(`chat-message--${state}`);
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
  paragraph.textContent = role === "assistant" ? normalizeAssistantText(text) : text;
  content.append(paragraph);
  article.append(content);
  chatThread.append(article);
  chatThread.scrollTop = chatThread.scrollHeight;
  return article;
}

function replaceMessage(article, text, state = "") {
  const content = article.querySelector(".message-content p");
  content.textContent = normalizeAssistantText(text);
  article.classList.remove("chat-message--pending", "chat-message--error");
  if (state) article.classList.add(`chat-message--${state}`);
  chatThread.scrollTop = chatThread.scrollHeight;
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
  chatThread.scrollTop = chatThread.scrollHeight;
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
      content: work.content || work.text || work.full_text || work.display_text || "",
    };
    const key = `${job.job_id}:${ordinal}`;
    const evaluationState = value.evaluation?.evaluated_at || (activeEvaluations.has(key) ? "pending" : failedEvaluations.has(key) ? "failed" : "none");
    const existing = list.querySelector(`[data-candidate-ordinal="${ordinal}"]`);
    if (!existing || existing.dataset.evaluationState !== String(evaluationState)) {
      const scroll = createPoemHandscroll(value, {
        resultLabel: `候选 ${ordinal}`,
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
  chatThread.append(details); chatThread.scrollTop = chatThread.scrollHeight;
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

document.querySelector("#conversation-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-conversation-id]");
  if (!button) return;
  try { await openConversation(button.dataset.conversationId); }
  catch (error) { announce(`无法打开对话：${error.message}`); }
});

loadCurrentUser();

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
