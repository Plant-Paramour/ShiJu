import {
  buildLexicon,
  evaluateBestTangForm,
  evaluateHaiku,
  evaluatePailv,
  evaluateSongci,
} from "./core.js?v=7";

export const RHYME_BOOKS = {
  Xinyun: { file: "Xinyun.json", name: "中华新韵" },
  Pinshui: { file: "Pinshui.json", name: "平水韵" },
  Cilin: { file: "Cilin.json", name: "词林正韵" },
  Tongyun: { file: "Tongyun.json", name: "中华通韵" },
};

const lexiconCache = new Map();
const meterCache = new Map();

function assetUrl(folder, filename) {
  return new URL(`../../${folder}/${filename}`, import.meta.url);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`数据加载失败：${response.status}`);
  return response.json();
}

export async function getLexicon(bookId) {
  const book = RHYME_BOOKS[bookId];
  if (!book) throw new Error(`不支持的韵书：${bookId}`);
  if (!lexiconCache.has(bookId)) {
    lexiconCache.set(bookId, fetchJson(assetUrl("Rhyme", book.file)).then(buildLexicon));
  }
  return lexiconCache.get(bookId);
}

async function getMeter(formName) {
  if (!meterCache.has(formName)) {
    meterCache.set(formName, fetchJson(assetUrl("Songci_Meter", `${formName}.json`)));
  }
  return meterCache.get(formName);
}

function comprehensiveScore(result) {
  return (result.structureScore + result.tonalScore + result.rhymeScore) / 3;
}

function summary(item) {
  return {
    rhyme_book_id: item.rhymeBookId,
    rhyme_book_name: RHYME_BOOKS[item.rhymeBookId].name,
    type: item.type,
    form_name: item.formName,
    score: Number(item.score.toFixed(2)),
    structure_score: item.result.structureScore,
    tonal_score: item.result.tonalScore,
    rhyme_score: item.result.rhymeScore,
  };
}

function selectBest(candidates, preferredBook) {
  candidates.sort((left, right) => right.score - left.score
    || Number(right.rhymeBookId === preferredBook) - Number(left.rhymeBookId === preferredBook)
    || right.result.structureScore - left.result.structureScore);
  return candidates[0];
}

function finalEvaluation(best, candidates) {
  best.result.stats = best.result.stats || {};
  best.result.stats.comprehensiveScore = best.score;
  best.result.stats.autoMatched = true;
  return {
    version: 1,
    evaluated_at: Date.now() / 1000,
    rhyme_book_id: best.rhymeBookId,
    rhyme_book_name: RHYME_BOOKS[best.rhymeBookId].name,
    type: best.type,
    form_name: best.formName,
    comprehensive_score: Number(best.score.toFixed(2)),
    structure_score: best.result.structureScore,
    tonal_score: best.result.tonalScore,
    rhyme_score: best.result.rhymeScore,
    result: best.result,
    alternatives: candidates.map(summary),
  };
}

function currentTangForm(formName = "") {
  if (/排律/.test(formName)) return { type: "pailv" };
  return {
    type: "tang",
    charCount: /五言/.test(formName) ? 5 : 7,
    form: /律诗/.test(formName) ? "lvshi" : "jueju",
  };
}

export async function evaluateBestTangAcrossBooks(text, options = {}, current = {}) {
  const candidates = [];
  for (const rhymeBookId of Object.keys(RHYME_BOOKS)) {
    const lexicon = await getLexicon(rhymeBookId);
    const best = evaluateBestTangForm(text, lexicon, options, current);
    for (const candidate of best.candidates) {
      candidates.push({
        ...candidate,
        rhymeBookId,
        formName: candidate.type === "pailv"
          ? `${candidate.result.stats.charCount === 5 ? "五" : "七"}言排律`
          : `${candidate.charCount === 5 ? "五" : "七"}言${candidate.form === "lvshi" ? "律诗" : "绝句"}`,
      });
    }
  }
  const best = selectBest(candidates, current.rhymeBookId);
  return { ...best, candidates, evaluation: finalEvaluation(best, candidates) };
}

export async function evaluateGeneratedPoem(text, request = {}) {
  const options = {
    strictPolyphonic: request.strict_polyphonic !== false,
    polyphonicMode: request.strict_polyphonic === false ? "permissive" : "strict",
    allowAoJiu: Boolean(request.task_options?.allow_aojiu),
  };
  const preferredBook = request.rhyme_dict_name || "Xinyun";
  const meterType = request.meter_type || "唐诗";

  if (meterType === "唐诗" || meterType === "排律") {
    const best = await evaluateBestTangAcrossBooks(
      text,
      options,
      { ...currentTangForm(request.form_name), rhymeBookId: preferredBook },
    );
    return best.evaluation;
  }

  const candidates = [];
  for (const rhymeBookId of Object.keys(RHYME_BOOKS)) {
    const lexicon = await getLexicon(rhymeBookId);
    let result;
    let formName = request.form_name || meterType;
    let type = meterType === "汉俳" ? "haiku" : "songci";
    if (meterType === "汉俳") {
      result = evaluateHaiku(text, lexicon, options);
    } else {
      const meter = await getMeter(request.form_name);
      const variantName = request.task_options?.variant_name || meter.default_variant;
      const variant = meter.variants.find((item) => item.name === variantName) || meter.variants[0];
      result = evaluateSongci(text, variant, lexicon, options);
      formName = `${meter.name} · ${variant.name}`;
    }
    candidates.push({
      type,
      formName,
      rhymeBookId,
      result,
      score: comprehensiveScore(result),
    });
  }
  const best = selectBest(candidates, preferredBook);
  return finalEvaluation(best, candidates);
}
