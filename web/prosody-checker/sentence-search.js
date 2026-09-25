import { buildLexicon, formatMeterTemplate } from "./core.js?v=8";

const books = { Xinyun: "Xinyun.json", Pinshui: "Pinshui.json", Cilin: "Cilin.json", Tongyun: "Tongyun.json" };
const bookCache = new Map();
const meterCache = new Map();
const $ = (selector) => document.querySelector(selector);
const han = /[\u3400-\u9fff]/gu;
const toneSymbols = new Set(["平", "仄", "中", "多"]);
const clean = (value) => (value.match(han) || []).join("");
const splitSentences = (value) => value
  // 除汉字、空白和顿号外的符号均视为分句标志。
  .split(/[^\p{Script=Han}\s、]+/u)
  .map((part) => clean(part))
  .filter(Boolean);
const asset = (folder, file) => new URL(`../../${folder}/${file}`, import.meta.url);
async function json(url) { const response = await fetch(url); if (!response.ok) throw new Error("数据加载失败：" + response.status); return response.json(); }
async function lexicon(book) { if (!bookCache.has(book)) bookCache.set(book, json(asset("Rhyme", books[book])).then(buildLexicon)); return bookCache.get(book); }
async function meter(file) { if (!meterCache.has(file)) meterCache.set(file, json(asset("Songci_Meter", file))); return meterCache.get(file); }
async function catalog() { if (!window.__sentenceCatalog) window.__sentenceCatalog = json(asset("Songci_Meter", "index.json")); return window.__sentenceCatalog; }

const type = $("#sentence-poem-type");
const length = $("#sentence-length");
const cipai = $("#sentence-cipai");
const variant = $("#sentence-variant");
const stanza = $("#sentence-stanza");
const line = $("#sentence-line");
const pattern = $("#sentence-pattern");
const template = $("#sentence-template");
const songciFields = [...document.querySelectorAll(".sentence-songci-only")];
let selectedTemplate = "";
let selectedTemplateSource = "";

function renderSelectableTemplate(value) {
  const box = $("#inferred-template");
  const target = box.querySelector("strong");
  target.replaceChildren();
  [...value].forEach((symbol) => {
    if (symbol !== "多") {
      target.append(document.createTextNode(symbol));
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "多";
    button.title = "点击切换为平或仄";
    button.dataset.tone = "多";
    button.addEventListener("click", () => {
      button.dataset.tone = button.dataset.tone === "平" ? "仄" : button.dataset.tone === "仄" ? "多" : "平";
      button.textContent = button.dataset.tone;
      selectedTemplate = [...target.childNodes].map((node) => node.nodeType === Node.TEXT_NODE ? node.textContent : node.dataset.tone).join("");
    });
    target.append(button);
  });
  selectedTemplate = value;
  selectedTemplateSource = $("#match-text").value.trim();
  box.hidden = false;
}

function repetitionMarks(variant, stanzaNumber, stanzaLines) {
  const chars = new Map(); const lines = new Map();
  for (const group of variant.repetition_groups || []) for (const position of group.positions || []) {
    if (Number(position.stanza) !== stanzaNumber) continue;
    const startLine = Number(position.start?.[0]); const endLine = Number(position.end?.[0]);
    const startChar = Number(position.start?.[1]); const endChar = Number(position.end?.[1]);
    for (let line = startLine; line <= endLine; line += 1) {
      lines.set(line, group.type || "叠字");
      const from = line === startLine ? startChar : 1; const to = line === endLine ? endChar : ([...(stanzaLines[line - 1] || "").replace(/[、/]/g, "")].length);
      for (let char = from; char <= to; char += 1) chars.set(line + ":" + char, group.type || "叠字");
    }
  }
  return { chars, lines };
}

const rhymePalette = ["#9f3028", "#2b6e8a", "#6d4b8a", "#a45b2a", "#26745c", "#8a4d68", "#7a6425", "#35658f", "#8b3f5f", "#4c6f3b"];
function rhymeColor(group) {
  return rhymePalette[(Number(group) - 1) % rhymePalette.length];
}

function closeMeterDrawer() {
  const drawer = $("#meter-drawer"); drawer.classList.remove("is-open"); drawer.setAttribute("aria-hidden", "true");
  $("#drawer-backdrop")?.classList.remove("is-visible"); if ($("#drawer-backdrop")) $("#drawer-backdrop").hidden = true;
  document.body.classList.remove("has-open-drawer");
}

function openMeterDrawer(item) {
  const drawer = $("#meter-drawer"); const content = $("#meter-drawer-content"); $("#meter-drawer-title").textContent = item.name; content.replaceChildren();
  const variant = item.meterData.variants.find((entry) => entry.name === item.variant) || item.meterData.variants[0];
  const description = document.createElement("p"); description.className = "meter-drawer__description"; description.textContent = "变体：" + variant.name + "。" + (variant.variants_description || ""); content.append(description);
  const rhymeGroups = [...new Set(Object.values(variant).filter((value) => value && typeof value === "object").flatMap((stanza) => Object.keys(stanza).filter((key) => /^rhyme_\d+_positions$/.test(key)).map((key) => Number(key.match(/\d+/)[0]))))].sort((a, b) => a - b);
  const legend = document.createElement("p"); legend.className = "meter-drawer__legend";
  rhymeGroups.forEach((group) => { const item = document.createElement("span"); const swatch = document.createElement("i"); swatch.className = "swatch"; swatch.style.color = rhymeColor(group); item.append(swatch, "第" + group + "组韵"); legend.append(item); });
  const repeatLegend = document.createElement("span"); repeatLegend.innerHTML = "<u>重复范围</u>"; legend.append(repeatLegend);
  const hitLegend = document.createElement("span"); hitLegend.innerHTML = "<mark>检索命中</mark>"; legend.append(hitLegend); content.append(legend);
  for (const [stanzaIndex, stanza] of Object.entries(variant).filter(([key]) => /^stanza\d+$/.test(key))) {
    const stanzaNumber = Number(stanzaIndex.replace("stanza", "")); const section = document.createElement("section"); section.className = "meter-drawer__stanza";
    const label = document.createElement("div"); label.className = "meter-drawer__stanza-label"; label.textContent = stanzaNumber === 1 ? "上阙" : "第" + stanzaNumber + "阙"; section.append(label);
    const rhymeByLine = new Map(Object.entries(stanza).filter(([key]) => /^rhyme_\d+_positions$/.test(key)).flatMap(([key, positions]) => positions.map((line) => [line, Number(key.match(/\d+/)[0])])));
    const marks = repetitionMarks(variant, stanzaNumber, stanza.lines || []);
    (stanza.lines || []).forEach((pattern, lineIndex) => {
      const lineNumber = lineIndex + 1; const row = document.createElement("div"); row.className = "meter-drawer__line";
      if (stanzaIndex === item.stanzaKey && lineIndex >= item.lineIndex && lineIndex < item.lineIndex + item.partCount) row.classList.add("is-hit");
      if (marks.lines.has(lineNumber)) row.classList.add("is-repeat");
      [...pattern.replace(/[、/]/g, "")].forEach((symbol, charIndex, chars) => {
        const span = document.createElement("span"); span.className = "meter-drawer__char"; span.textContent = symbol;
        if (charIndex === chars.length - 1 && rhymeByLine.has(lineNumber)) { const group = rhymeByLine.get(lineNumber); span.classList.add("rhyme-" + group); span.style.color = rhymeColor(group); span.style.backgroundColor = rhymeColor(group) + "1f"; }
        if (marks.chars.has(lineNumber + ":" + (charIndex + 1))) span.classList.add("is-repeat");
        row.append(span);
      });
      if (rhymeByLine.has(lineNumber)) { const group = rhymeByLine.get(lineNumber); const badge = document.createElement("small"); badge.className = "meter-drawer__badge rhyme-" + group; badge.style.color = rhymeColor(group); badge.textContent = "韵" + group; row.append(badge); }
      if (marks.lines.has(lineNumber)) { const badge = document.createElement("small"); badge.className = "meter-drawer__badge is-repeat"; badge.textContent = marks.lines.get(lineNumber); row.append(badge); }
      section.append(row);
    }); content.append(section);
  }
  drawer.classList.add("is-open"); drawer.setAttribute("aria-hidden", "false"); document.body.classList.add("has-open-drawer");
  const backdrop = $("#drawer-backdrop"); if (backdrop) { backdrop.hidden = false; requestAnimationFrame(() => backdrop.classList.add("is-visible")); }
}

$("#meter-drawer [data-meter-drawer-close]").addEventListener("click", closeMeterDrawer);
$("#drawer-backdrop")?.addEventListener("click", closeMeterDrawer);

function patternsFor(poemType, chars) {
  if (poemType === "wuyan") chars = 5;
  if (poemType === "qiyan") chars = 7;
  if (poemType === "pailv") return chars === 5 ? ["平平仄仄平", "仄仄仄平平", "仄仄平平仄", "平平仄仄平"] : ["平平仄仄仄平平", "仄仄平平仄仄平", "仄仄平平平仄仄", "平平仄仄仄平平"];
  return chars === 5 ? ["平平仄仄平", "仄仄仄平平", "仄仄平平仄", "平平仄仄平"] : ["平平仄仄仄平平", "仄仄平平仄仄平", "仄仄平平平仄仄", "平平仄仄仄平平"];
}
function toneForChar(char, bookLexicon, mode = "automatic") {
  const tones = bookLexicon.lookup(char).tones;
  if (!tones.size) return "多";
  if (mode === "strict" && tones.size > 1) return "多";
  return tones.size > 1 ? "多" : [...tones][0];
}
function inferTemplate(text, bookLexicon, mode, includeBreaks = true) {
  // 平仄模板本身不是待查韵书的汉字，直接保留用户输入。
  const symbols = clean(text);
  if (symbols && [...symbols].every((char) => toneSymbols.has(char))) {
    return [...text].map((char) => /\s/u.test(char) ? "" : char).join("");
  }
  return [...text].map((char) => {
    if (/\p{Script=Han}/u.test(char)) return toneForChar(char, bookLexicon, mode);
    return /\s/u.test(char) ? "" : char;
  }).join("");
}
function isToneTemplate(chars) {
  return chars.length > 0 && chars.every((char) => toneSymbols.has(char));
}
function templateToneMatches(inputTone, expectedTone) {
  // “多”和“中”均表示当前位置不限定唯一平仄。
  return inputTone === "多" || inputTone === "中" || expectedTone === "中" || inputTone === expectedTone;
}
function userBreakPositions(text) {
  const positions = []; let count = 0;
  for (const char of text) { if (char === "/") positions.push(count); else if (/\p{Script=Han}/u.test(char)) count += 1; }
  return positions;
}
function scoreSentence(text, expected, bookLexicon, options = {}) {
  const inputParts = splitSentences(text); const expectedParts = expected.split(/[、\/]/u).map((part) => part.replace(/\s/g, "")).filter(Boolean);
  const chars = [...inputParts.join("")]; const target = [...expectedParts.join("")];
  const compared = Math.min(chars.length, target.length); let matched = 0; const mismatches = new Set();
  const inputIsTemplate = isToneTemplate(chars);
  for (let i = 0; i < compared; i += 1) {
    const toneMatches = inputIsTemplate
      ? templateToneMatches(chars[i], target[i])
      : (() => {
        const tones = bookLexicon.lookup(chars[i]).tones;
        if (target[i] === "中") return true;
        return options.polyphonic === "strict" ? tones.size === 1 && tones.has(target[i]) : tones.has(target[i]);
      })();
    if (toneMatches) matched += 1; else mismatches.add(i);
  }
  const lengthScore = chars.length === target.length ? 1 : Math.max(0, 1 - Math.abs(chars.length - target.length) / Math.max(chars.length, target.length, 1));
  const shapeExact = inputParts.length === expectedParts.length && inputParts.every((part, index) => part.length === expectedParts[index].length);
  const expectedBreaks = []; let offset = 0;
  for (const part of expectedParts) { offset += [...part].length; expectedBreaks.push(offset); }
  expectedBreaks.pop();
  const userBreaks = userBreakPositions(text);
  const breakErrors = options.respectBreaks === false ? 0 : userBreaks.filter((position) => !expectedBreaks.includes(position)).length;
  const baseScore = (matched / Math.max(target.length, 1)) * 0.85 + lengthScore * 0.15;
  const score = Math.max(0, baseScore - breakErrors * 0.1);
  return { chars, target, matched, total: target.length, mismatches, shapeExact, breakCount: (expected.match(/[、\/]/gu) || []).length, breakErrors, score };
}
function renderVerdict(result, expected) {
  const box = $("#sentence-verdict"); box.hidden = false; box.className = "sentence-verdict " + (result.score >= 0.99 ? "is-pass" : "is-warn");
  box.replaceChildren(); const title = document.createElement("strong"); title.textContent = result.score >= 0.99 ? "符合格律" : "有待调整";
  const template = document.createElement("div"); template.className = "sentence-verdict-template"; let toneIndex = 0;
  for (const symbol of expected.replace(/\s/g, "")) {
    if (symbol === "、" || symbol === "/") { template.append(symbol); continue; }
    const mark = document.createElement("span"); mark.textContent = symbol;
    if (result.mismatches.has(toneIndex)) mark.className = "is-error";
    template.append(mark); toneIndex += 1;
  }
  const detail = document.createElement("p"); detail.textContent = `匹配 ${result.matched}/${result.total} 字（${Math.round(result.score * 100)}%）`;
  box.append(title, template, detail);
}
async function loadSongciOptions() {
  const items = await catalog();
  // 提前并行建立词牌模板请求，避免匹配时按 821 个词牌逐个等待网络响应。
  void Promise.allSettled(items.map((item) => meter(item.file)));
  cipai.replaceChildren(); items.forEach((item) => cipai.add(new Option(`${item.name}　${item.char_count}字`, item.file)));
  await updateVariants();
}
async function updateVariants() {
  if (type.value !== "songci" || !cipai.value) return;
  const data = await meter(cipai.value); variant.replaceChildren(); (data.variants || []).forEach((item) => variant.add(new Option(item.name, item.name)));
  variant.value = data.default_variant || variant.options[0]?.value || ""; await updateLines();
}
async function updateLines() {
  if (type.value !== "songci") return;
  const data = await meter(cipai.value); const selected = data.variants.find((item) => item.name === variant.value) || data.variants[0];
  const stanzas = selected ? Object.keys(selected).filter((key) => /^stanza\d+$/.test(key)) : []; stanza.replaceChildren(); stanzas.forEach((_, index) => stanza.add(new Option(index === 0 ? "上阙" : `第${index + 1}阙`, String(index))));
  await updatePattern(selected);
}
async function updatePattern(selected) {
  if (type.value !== "songci") { const expected = patternsFor(type.value, Number(length.value))[0]; pattern.textContent = expected; template.hidden = false; return; }
  const stanzaData = selected?.[`stanza${Number(stanza.value) + 1}`] || selected?.stanza1; line.replaceChildren(); (stanzaData?.lines || []).forEach((_, index) => line.add(new Option(`第${index + 1}句`, String(index))));
  const expected = stanzaData?.lines?.[Number(line.value) || 0] || "—"; pattern.textContent = expected; template.hidden = false;
}
function refreshType() { const isSongci = type.value === "songci"; const fixedLength = type.value === "wuyan" || type.value === "qiyan"; songciFields.forEach((field) => { field.hidden = !isSongci; }); $("#sentence-length-field").hidden = isSongci || fixedLength; if (!isSongci) updatePattern(); else updateVariants(); }

$("#sentence-check-button").addEventListener("click", async () => { const text = $("#sentence-text").value.trim(); const status = $("#sentence-check-status"); if (!splitSentences(text).length) { status.textContent = "请输入一句或两句中文"; return; } status.textContent = "判断中……"; try { const book = await lexicon($("#sentence-rhyme-book").value); let expected; if (type.value === "songci") { const data = await meter(cipai.value); const selected = data.variants.find((item) => item.name === variant.value) || data.variants[0]; expected = selected[`stanza${Number(stanza.value) + 1}`]?.lines?.[Number(line.value) || 0] || ""; } else expected = patternsFor(type.value, Number(length.value))[0]; renderVerdict(scoreSentence(text, expected, book), expected); status.textContent = ""; } catch (error) { status.textContent = error.message; } });

$("#match-button").addEventListener("click", async () => { const text = $("#match-text").value.trim(); const status = $("#match-status"); const output = $("#match-results"); const inputParts = splitSentences(text); if (!inputParts.length) { status.textContent = "请输入一句或两句中文"; return; } status.textContent = "正在遍历词牌……"; output.hidden = true; try { const book = await lexicon($("#match-rhyme-book").value); const items = await catalog(); const options = { respectBreaks: $("#match-respect-breaks").checked, polyphonic: $("#match-polyphonic").value }; const inferred = $("#inferred-template"); inferred.hidden = false; inferred.querySelector("strong").textContent = inferTemplate(text, book, options.polyphonic); const results = []; for (const item of items) { const data = await meter(item.file); for (const v of data.variants || []) for (const key of Object.keys(v).filter((name) => /^stanza\\d+$/.test(name))) { const lines = v[key].lines || []; for (let i = 0; i < lines.length; i += 1) { const expected = lines[i]; const scored = scoreSentence(text, expected, book, options); if (!$("#match-exclude-breaks").checked || !scored.breakCount) results.push({ name: data.name, variant: v.name, place: `${key === "stanza1" ? "上阙" : "下阙"}第${i + 1}句`, expected, score: scored.score, breaks: scored.breakCount, shape: scored.shapeExact }); if (inputParts.length === 2 && i + 1 < lines.length) { const combined = `${lines[i]}、${lines[i + 1]}`; const combinedScore = scoreSentence(text, combined, book, options); if (!$("#match-exclude-breaks").checked || !combinedScore.breakCount) results.push({ name: data.name, variant: v.name, place: `${key === "stanza1" ? "上阙" : "下阙"}第${i + 1}-${i + 2}句`, expected: combined, score: combinedScore.score, breaks: combinedScore.breakCount, shape: combinedScore.shapeExact }); } } } } const sort = $("#match-sort").value; results.sort((a, b) => sort === "score" ? b.score - a.score : sort === "breaks" ? a.breaks - b.breaks || b.score - a.score : Number(b.shape) - Number(a.shape) || a.breaks - b.breaks || b.score - a.score); const exact = results.filter((item) => item.score >= 0.999); const shown = (exact.length ? exact : results).slice(0, 30); output.replaceChildren(); const heading = document.createElement("p"); heading.className = "match-summary"; heading.textContent = exact.length ? `找到 ${exact.length} 个 100% 匹配结果` : "没有 100% 匹配，以下为最接近的句式"; output.append(heading); shown.forEach((item) => { const row = document.createElement("article"); row.className = "match-item"; row.innerHTML = `<div><strong>${item.name}</strong><span>${item.variant} · ${item.place}</span></div><b>${Math.round(item.score * 100)}%</b><code>${$("#match-exclude-breaks").checked ? item.expected.replace(/[、/]/g, "") : item.expected}</code>`; output.append(row); }); output.hidden = false; status.textContent = `已检索 ${results.length} 条句式`; } catch (error) { status.textContent = error.message; } });

document.querySelectorAll("[data-sentence-tab]").forEach((button) => button.addEventListener("click", () => { const selected = button.dataset.sentenceTab; document.querySelectorAll("[data-sentence-tab]").forEach((item) => { const active = item === button; item.classList.toggle("is-active", active); item.setAttribute("aria-selected", String(active)); }); document.querySelectorAll("[data-sentence-panel]").forEach((panel) => { panel.hidden = panel.dataset.sentencePanel !== selected; }); }));
// 词牌匹配的候选模板统一并行加载，避免串行请求导致结果区长时间为空。
document.addEventListener("click", async (event) => {
  if (!event.target.closest("#match-button")) return;
  const text = $("#match-text").value.trim(); const parts = splitSentences(text);
  if (!parts.length || parts.length >= 3) return;
  event.preventDefault(); event.stopImmediatePropagation();
  const status = $("#match-status"); const output = $("#match-results"); status.textContent = "正在遍历词牌……"; output.hidden = true;
  try {
    const book = await lexicon($("#match-rhyme-book").value); const items = await catalog();
    const options = { respectBreaks: $("#match-respect-breaks").checked, polyphonic: $("#match-polyphonic").value };
    const generatedTemplate = inferTemplate(text, book, options.polyphonic);
    if (selectedTemplateSource !== text) renderSelectableTemplate(generatedTemplate);
    const queryText = selectedTemplate;
    const loaded = await Promise.allSettled(items.map(async (item) => ({ item, data: await meter(item.file) }))); const results = [];
    for (const result of loaded) {
      if (result.status !== "fulfilled") continue;
      const { data } = result.value;
      for (const v of data.variants || []) for (const key of Object.keys(v).filter((name) => /^stanza\d+$/.test(name))) {
        const lines = v[key].lines || [];
        const rhymePositions = Object.keys(v[key]).filter((name) => /^rhyme_\d+_positions$/.test(name)).flatMap((name) => v[key][name] || []);
        const punctuationFor = (lineIndex) => rhymePositions.includes(lineIndex) ? "。" : "，";
        for (let i = 0; i < lines.length; i += 1) {
          const expected = lines[i]; const scored = scoreSentence(queryText, expected, book, options);
          if (parts.length === 1) results.push({ name: data.name, variant: v.name, place: (key === "stanza1" ? "上阙" : "下阙") + "第" + (i + 1) + "句", expected, displayExpected: (i === 0 ? "" : punctuationFor(i)) + expected + punctuationFor(i + 1), score: scored.score, breaks: scored.breakCount, shape: scored.shapeExact, intra: false, meterData: data, stanzaKey: key, lineIndex: i, partCount: 1 });
          if (parts.length === 2 && i + 1 < lines.length) {
            const combined = lines[i] + "、" + lines[i + 1]; const combinedScore = scoreSentence(queryText, combined, book, options);
            results.push({ name: data.name, variant: v.name, place: (key === "stanza1" ? "上阙" : "下阙") + "第" + (i + 1) + "-" + (i + 2) + "句", expected: combined, displayExpected: (i === 0 ? "" : punctuationFor(i)) + lines[i] + punctuationFor(i + 1) + lines[i + 1] + punctuationFor(i + 2), score: combinedScore.score, breaks: combinedScore.breakCount, shape: combinedScore.shapeExact, intra: i > 0 && rhymePositions.includes(i), meterData: data, stanzaKey: key, lineIndex: i, partCount: 2 });
          }
        }
      }
    }
    const sort = $("#match-sort").value;
    results.sort((a, b) => sort === "score" ? b.score - a.score : sort === "breaks" ? a.breaks - b.breaks || b.score - a.score : sort === "intra" ? Number(b.intra) - Number(a.intra) || Number(b.shape) - Number(a.shape) || b.score - a.score : Number(b.shape) - Number(a.shape) || a.breaks - b.breaks || b.score - a.score);
    const exact = results.filter((item) => item.shape && item.score >= 0.999); const shown = (exact.length ? exact : results).slice(0, 30);
    output.replaceChildren(); const heading = document.createElement("p"); heading.className = "match-summary"; heading.textContent = exact.length ? "找到 " + exact.length + " 个 100% 匹配结果" : "没有 100% 匹配，以下为最接近的句式"; output.append(heading);
    shown.forEach((item) => { const row = document.createElement("article"); row.className = "match-item"; row.tabIndex = 0; row.setAttribute("role", "button"); row.innerHTML = "<div><strong>" + item.name + "</strong><span>" + item.variant + " · " + item.place + "</span></div><b>" + Math.round(item.score * 100) + "%</b><code>" + (item.displayExpected || item.expected) + "</code>"; row.addEventListener("click", () => openMeterDrawer(item)); row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openMeterDrawer(item); } }); output.append(row); });
    output.hidden = false; status.textContent = "已检索 " + results.length + " 条句式";
  } catch (error) { status.textContent = error.message; }
}, true);

let draggedPriority = null;
function syncPrimaryPriority() { const first = document.querySelector("#match-priority-list [data-priority]"); const select = $("#match-sort"); if (first && select) select.value = first.dataset.priority; }
document.querySelectorAll("#match-priority-list li").forEach((item) => {
  item.addEventListener("dragstart", () => { draggedPriority = item; item.classList.add("is-dragging"); });
  item.addEventListener("dragend", () => { item.classList.remove("is-dragging"); draggedPriority = null; });
  item.addEventListener("dragover", (event) => { event.preventDefault(); if (!draggedPriority || draggedPriority === item) return; const rect = item.getBoundingClientRect(); item.parentElement.insertBefore(draggedPriority, event.clientX < rect.left + rect.width / 2 ? item : item.nextSibling); });
});
syncPrimaryPriority();
type.addEventListener("change", refreshType); length.addEventListener("change", updatePattern); cipai.addEventListener("change", updateVariants); variant.addEventListener("change", updateLines); stanza.addEventListener("change", async () => { const data = await meter(cipai.value); const selected = data.variants.find((item) => item.name === variant.value) || data.variants[0]; await updatePattern(selected); }); line.addEventListener("change", updateLines);
loadSongciOptions().catch((error) => { $("#sentence-check-status").textContent = error.message; }); refreshType();

document.addEventListener("click", (event) => {
  if (event.target.closest("#match-button") && $("#match-respect-breaks").checked && !$("#match-text").value.includes("/")) {
    event.preventDefault();
    event.stopImmediatePropagation();
    $("#match-status").textContent = '请手动用斜杠"/"标记断句';
  }
}, true);

let breakToastTimer;
$("#match-respect-breaks").addEventListener("change", (event) => {
  if (!event.target.checked || $("#match-text").value.includes("/")) return;
  event.target.checked = false;
  const toast = $("#site-status");
  toast.textContent = '请先用斜杠"/"标记断句';
  toast.classList.add("is-visible");
  window.clearTimeout(breakToastTimer);
  breakToastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 4000);
});

document.addEventListener("click", async (event) => {
  if (!event.target.closest("#match-button")) return;
  const text = $("#match-text").value.trim(); const parts = splitSentences(text);
  if (parts.length < 3) return;
  event.preventDefault(); event.stopImmediatePropagation();
  const status = $("#match-status"); const output = $("#match-results"); status.textContent = "正在匹配多句句式……"; output.hidden = true;
  try {
    const book = await lexicon($("#match-rhyme-book").value); const items = await catalog(); const options = { respectBreaks: $("#match-respect-breaks").checked, polyphonic: $("#match-polyphonic").value }; const results = [];
    $("#inferred-template").hidden = false; $("#inferred-template strong").textContent = inferTemplate(text, book, options.polyphonic);
    for (const item of items) { const data = await meter(item.file); for (const v of data.variants || []) for (const key of Object.keys(v).filter((name) => /^stanza\d+$/.test(name))) { const lines = v[key].lines || []; for (let i = 0; i + parts.length <= lines.length; i += 1) { const expected = lines.slice(i, i + parts.length).join("、"); const scored = scoreSentence(text, expected, book, options); results.push({ name: data.name, variant: v.name, place: `${key === "stanza1" ? "上阙" : "下阙"}第${i + 1}-${i + parts.length}句`, expected, score: scored.score, breaks: scored.breakCount, shape: scored.shapeExact }); } } }
    results.sort((a, b) => Number(b.shape) - Number(a.shape) || b.score - a.score || a.breaks - b.breaks); const exact = results.filter((item) => item.score >= 0.999); const shown = (exact.length ? exact : results).slice(0, 30); output.replaceChildren(); const heading = document.createElement("p"); heading.className = "match-summary"; heading.textContent = exact.length ? `找到 ${exact.length} 个 100% 匹配结果` : "没有 100% 匹配，以下为最接近的句式"; output.append(heading); shown.forEach((item) => { const row = document.createElement("article"); row.className = "match-item"; row.innerHTML = `<div><strong>${item.name}</strong><span>${item.variant} · ${item.place}</span></div><b>${Math.round(item.score * 100)}%</b><code>${item.expected}</code>`; output.append(row); }); output.hidden = false; status.textContent = `已检索 ${results.length} 条多句句式`;
  } catch (error) { status.textContent = error.message; }
}, true);
