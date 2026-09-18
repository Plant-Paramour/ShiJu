import {
  buildLexicon,
  evaluateHaiku,
  evaluatePailv,
  evaluateSongci,
  evaluateTang,
  formatMeterTemplate,
} from "./core.js?v=4";

const RHYME_BOOKS = {
  Xinyun: "Xinyun.json",
  Pinshui: "Pinshui.json",
  Cilin: "Cilin.json",
  Tongyun: "Tongyun.json",
};

const METER_FILES = [
  "浣溪沙.json",
  "南乡子.json",
  "水调歌头.json",
  "桂枝香.json",
  "渔家傲.json",
  "谢池春.json",
];

const elements = {
  workspace: document.querySelector("#workspace"),
  form: document.querySelector("#checker-form"),
  typeInputs: [...document.querySelectorAll("[name='poem-type']")],
  rhymeBook: document.querySelector("#rhyme-book"),
  tangOptions: document.querySelector("#tang-options"),
  songciOptions: document.querySelector("#songci-options"),
  tangLength: document.querySelector("#tang-length"),
  tangForm: document.querySelector("#tang-form"),
  cipai: document.querySelector("#cipai"),
  variant: document.querySelector("#variant"),
  polyphonicInputs: [...document.querySelectorAll("[name='polyphonic-mode']")],
  allowAoJiu: document.querySelector("#allow-aojiu"),
  aoJiuControl: document.querySelector("#aojiu-control"),
  meterTemplate: document.querySelector("#meter-template"),
  templateContent: document.querySelector("#template-content"),
  poemText: document.querySelector("#poem-text"),
  button: document.querySelector("#check-button"),
  status: document.querySelector("#form-status"),
  resultPanel: document.querySelector("#result-panel"),
  resultMeta: document.querySelector("#result-meta"),
  structureScore: document.querySelector("#structure-score"),
  tonalScore: document.querySelector("#tonal-score"),
  rhymeScore: document.querySelector("#rhyme-score"),
  issues: document.querySelector("#issues"),
  lineResults: document.querySelector("#line-results"),
  rhymeResults: document.querySelector("#rhyme-results"),
};

const lexiconCache = new Map();
const meterCache = new Map();

function assetUrl(folder, filename) {
  return new URL("../../" + folder + "/" + filename, import.meta.url);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("数据加载失败：" + response.status);
  return response.json();
}

async function getLexicon(name) {
  if (!lexiconCache.has(name)) {
    const promise = fetchJson(assetUrl("Rhyme", RHYME_BOOKS[name])).then(buildLexicon);
    lexiconCache.set(name, promise);
  }
  return lexiconCache.get(name);
}

async function getMeter(filename) {
  if (!meterCache.has(filename)) {
    meterCache.set(filename, fetchJson(assetUrl("Songci_Meter", filename)));
  }
  return meterCache.get(filename);
}

function selectedType() {
  return elements.typeInputs.find((input) => input.checked).value;
}

function evaluationOptions() {
  return {
    strictPolyphonic: elements.polyphonicInputs.find((input) => input.checked).value
      === "strict",
    allowAoJiu: elements.allowAoJiu.checked,
  };
}

async function loadMeterCatalog() {
  const meters = await Promise.all(METER_FILES.map((filename) => getMeter(filename)));
  elements.cipai.replaceChildren();
  meters.forEach((meter, index) => {
    const option = new Option(meter.name, METER_FILES[index]);
    elements.cipai.add(option);
  });
  await updateVariants();
}

async function updateVariants() {
  const meter = await getMeter(elements.cipai.value);
  elements.variant.replaceChildren();
  for (const variant of meter.variants ?? []) {
    elements.variant.add(new Option(variant.name, variant.name));
  }
  if (meter.default_variant) elements.variant.value = meter.default_variant;
  renderTemplate();
}

function currentVariant() {
  const meterPromise = meterCache.get(elements.cipai.value);
  return Promise.resolve(meterPromise).then((meter) =>
    meter.variants.find((variant) => variant.name === elements.variant.value));
}

async function renderTemplate() {
  if (selectedType() !== "songci") return;
  const variant = await currentVariant();
  elements.templateContent.replaceChildren();
  for (const stanza of formatMeterTemplate(variant)) {
    const stanzaElement = document.createElement("div");
    stanzaElement.className = "template-stanza";
    for (const line of stanza.lines) {
      const lineElement = document.createElement("span");
      lineElement.className = "template-line";
      lineElement.textContent = line;
      stanzaElement.append(lineElement);
    }
    elements.templateContent.append(stanzaElement);
  }
}

function updateTypeView() {
  const type = selectedType();
  elements.tangOptions.hidden = type !== "tang";
  elements.songciOptions.hidden = type !== "songci";
  elements.meterTemplate.hidden = type !== "songci";
  elements.allowAoJiu.disabled = type === "songci";
  elements.aoJiuControl.classList.toggle("disabled", type === "songci");
  elements.status.textContent = "";
  if (type === "songci") renderTemplate();
}

function appendCharacterRow(container, characters, property) {
  const row = document.createElement("div");
  row.className = property === "char" ? "poem-line" : "tone-line";
  for (const item of characters) {
    const span = document.createElement("span");
    span.className = property;
    if (item.polyphonic) span.classList.add("polyphonic");
    if (item.error) span.classList.add("error");
    if (property === "tone" && item.tone.includes("/")) span.classList.add("multi-label");
    span.textContent = property === "char" ? item.char : item.tone;
    if (item.expected) span.title = "此处要求：" + item.expected;
    row.append(span);
  }
  container.append(row);
}

function resultMeta(result, type, variant) {
  if (type === "songci") {
    return elements.cipai.selectedOptions[0].text + " · " + variant.name
      + " · " + (variant.rhyme_type || "未标注韵式");
  }
  if (type === "tang") {
    const form = elements.tangForm.value === "jueju" ? "绝句" : "律诗";
    return result.stats.charCount + "言" + form + " · "
      + (result.stats.globalBase ?? "未定") + "起 · "
      + result.stats.rhymeTone + "韵";
  }
  if (type === "pailv") {
    return result.stats.charCount + "言排律 · "
      + (result.stats.globalBase ?? "未定") + "起 · "
      + result.stats.rhymeTone + "韵";
  }
  return "五七五俳句";
}

function renderResult(result, type, variant) {
  elements.structureScore.textContent = result.structureScore.toFixed(2).replace(/\.00$/, "");
  elements.tonalScore.textContent = result.tonalScore.toFixed(2).replace(/\.00$/, "");
  elements.rhymeScore.textContent = result.rhymeScore.toFixed(2).replace(/\.00$/, "");
  elements.resultMeta.textContent = resultMeta(result, type, variant);

  elements.issues.replaceChildren();
  elements.issues.hidden = result.issues.length === 0;
  if (result.issues.length) {
    for (const issue of result.issues) {
      const div = document.createElement("div");
      div.textContent = issue;
      elements.issues.append(div);
    }
  }

  elements.lineResults.replaceChildren();
  result.lines.forEach((line) => {
    const row = document.createElement("div");
    row.className = "result-line";
    appendCharacterRow(row, line.characters, "char");
    appendCharacterRow(row, line.characters, "tone");
    elements.lineResults.append(row);
  });

  elements.rhymeResults.replaceChildren();
  result.rhymeGroups.forEach((group, index) => {
    const line = document.createElement("div");
    line.className = "rhyme-group";
    const endings = group.endings.map((ending) => ending.char).join("、") || "无";
    const label = document.createElement("span");
    label.textContent = "第 " + (index + 1) + " 韵组：" + endings + "；主韵部 ";
    const part = document.createElement("strong");
    part.textContent = group.dominantPart ?? "未识别";
    line.append(label, part);
    elements.rhymeResults.append(line);
  });

  elements.resultPanel.hidden = false;
  elements.workspace.classList.add("has-result");
}

async function runCheck(event) {
  event.preventDefault();
  elements.status.textContent = "";
  const text = elements.poemText.value.trim();
  if (!text) {
    elements.status.textContent = "请先粘贴诗词正文";
    elements.poemText.focus();
    return;
  }

  elements.button.disabled = true;
  elements.button.textContent = "检查中";
  try {
    const type = selectedType();
    const lexicon = await getLexicon(elements.rhymeBook.value);
    const options = evaluationOptions();
    let result;
    let variant = null;
    if (type === "songci") {
      variant = await currentVariant();
      result = evaluateSongci(text, variant, lexicon, options);
    } else if (type === "tang") {
      result = evaluateTang(text, {
        charCount: Number(elements.tangLength.value),
        form: elements.tangForm.value,
        ...options,
      }, lexicon);
    } else if (type === "pailv") {
      result = evaluatePailv(text, lexicon, options);
    } else {
      result = evaluateHaiku(text, lexicon, options);
    }
    renderResult(result, type, variant);
  } catch (error) {
    elements.status.textContent = error instanceof Error ? error.message : "检查失败";
  } finally {
    elements.button.disabled = false;
    elements.button.textContent = "开始检查";
  }
}

elements.typeInputs.forEach((input) => input.addEventListener("change", updateTypeView));
elements.cipai.addEventListener("change", updateVariants);
elements.variant.addEventListener("change", renderTemplate);
elements.form.addEventListener("submit", runCheck);

try {
  await loadMeterCatalog();
  updateTypeView();
  getLexicon(elements.rhymeBook.value);
} catch (error) {
  elements.status.textContent = error instanceof Error ? error.message : "初始化失败";
}
