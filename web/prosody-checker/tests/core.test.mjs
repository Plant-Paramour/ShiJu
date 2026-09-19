import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  buildLexicon,
  evaluateBestTangForm,
  evaluateHaiku,
  evaluatePailv,
  evaluateSongci,
  evaluateTang,
  flattenMeter,
  formatMeterTemplate,
  parsePoem,
} from "../core.js";

const lexicon = buildLexicon({
  一东: {
    平声: ["山", "春", "花", "风", "重"],
  },
  二冬: {
    仄声: ["雨", "夜", "月", "重"],
  },
});

const pinshuiLexicon = buildLexicon(JSON.parse(readFileSync(
  new URL("../../../Rhyme/Pinshui.json", import.meta.url),
  "utf8",
)));

test("parsePoem accepts punctuation, newlines, and generated output markers", () => {
  assert.deepEqual(
    parsePoem("[title]测试\n[content]春山，夜雨。\n花月"),
    ["春山", "夜雨", "花月"],
  );
});

test("buildLexicon marks characters with multiple tone/rhyme readings", () => {
  assert.deepEqual([...lexicon.lookup("重").tones].sort(), ["仄", "平"]);
  assert.equal(lexicon.lookup("重").polyphonic, true);
  assert.equal(lexicon.lookup("山").polyphonic, false);
});

test("polyphonic characters pass when at least one reading is valid", () => {
  const variant = {
    name: "测试体",
    stanza1: { lines: ["平"] },
  };
  const result = evaluateSongci("重", variant, lexicon);
  assert.equal(result.tonalScore, 100);
  assert.equal(result.lines[0].characters[0].polyphonic, true);
  assert.equal(result.lines[0].characters[0].error, false);
});

test("strict polyphonic mode rejects a character with an illegal reading", () => {
  const variant = {
    name: "测试体",
    stanza1: { lines: ["平"] },
  };
  const result = evaluateSongci("重", variant, lexicon, { strictPolyphonic: true });
  assert.equal(result.tonalScore, 0);
  assert.equal(result.lines[0].characters[0].error, true);
});

test("strict polyphonic mode requires every reading to share the rhyme part", () => {
  const variant = {
    name: "测试体",
    stanza1: {
      rhyme_1_positions: [1, 2],
      lines: ["中", "中"],
    },
  };
  const permissive = evaluateSongci("山，重", variant, lexicon);
  const strict = evaluateSongci(
    "山，重",
    variant,
    lexicon,
    { strictPolyphonic: true },
  );
  assert.equal(permissive.rhymeScore, 100);
  assert.equal(strict.rhymeScore, 50);
});

test("automatic polyphonic mode resolves tone and rhyme part from context", () => {
  const variant = {
    name: "测试体",
    stanza1: {
      rhyme_1_positions: [1, 2],
      lines: ["平", "中"],
    },
  };
  const result = evaluateSongci(
    "重，山",
    variant,
    lexicon,
    { polyphonicMode: "automatic" },
  );
  const character = result.lines[0].characters[0];

  assert.equal(result.tonalScore, 100);
  assert.equal(result.rhymeScore, 100);
  assert.equal(character.tone, "平");
  assert.equal(character.selectedTone, "平");
  assert.equal(character.selectedPart, "一东");
  assert.equal(character.decisionReason, "若属一东韵部，则符合本组押韵要求");
});

test("Songci follows the paper tonal and dominant-rhyme formulas", () => {
  const variant = {
    name: "测试体",
    number_of_stanzas: 1,
    stanza1: {
      num_lines: 2,
      rhyme_1_positions: [1, 2],
      lines: ["中平", "仄中"],
    },
  };
  const result = evaluateSongci("雨夜，山春", variant, lexicon);
  assert.equal(result.structureScore, 100);
  assert.equal(result.tonalScore, 50);
  assert.equal(result.rhymeScore, 50);
  assert.equal(result.errors.size, 2);
});

test("Songci structure score uses correct clauses over template clauses", () => {
  const variant = {
    name: "测试体",
    stanza1: { lines: ["中平", "仄中"] },
  };
  assert.equal(evaluateSongci("山春", variant, lexicon).structureScore, 50);
  assert.equal(evaluateSongci("山春，夜", variant, lexicon).structureScore, 50);
});

test("Songci templates preserve flexible 中 positions", () => {
  const variant = {
    name: "测试体",
    number_of_stanzas: 1,
    stanza1: { lines: ["中平/中仄"] },
  };
  assert.deepEqual(formatMeterTemplate(variant)[0].lines, ["中平中仄"]);
  assert.equal(flattenMeter(variant).clauses[0].pattern, "中平中仄");
});

test("Tang evaluator uses the requested length and form", () => {
  const result = evaluateTang(
    "山春山夜山春花，雨夜雨山雨夜山。山春山夜山春花，雨夜雨山雨夜山。",
    { charCount: 7, form: "jueju" },
    lexicon,
  );
  assert.equal(result.lines.length, 4);
  assert.equal(result.stats.charCount, 7);
  assert.equal(result.structureScore, 100);
  assert.equal(result.issues.length, 0);
  assert.ok(result.tonalScore >= 0 && result.tonalScore <= 100);
  assert.ok(result.rhymeScore >= 0 && result.rhymeScore <= 100);
});

test("Tang structure score follows the paper line-count cap", () => {
  const result = evaluateTang(
    "山春山夜山春花，雨夜雨山雨夜山。",
    { charCount: 7, form: "jueju" },
    lexicon,
  );
  assert.equal(result.structureScore, 50);
});

test("smart form selection chooses jueju, lvshi, and pailv by comprehensive score", () => {
  const fiveJueju = Array(4).fill("春山夜雨花").join("\n");
  const sevenLvshi = Array(8).fill("山春山夜山春花").join("\n");
  const fivePailv = Array(10).fill("春山夜雨花").join("\n");

  const jueju = evaluateBestTangForm(fiveJueju, lexicon);
  const lvshi = evaluateBestTangForm(sevenLvshi, lexicon, {}, { type: "pailv" });
  const pailv = evaluateBestTangForm(fivePailv, lexicon, {}, {
    type: "tang",
    charCount: 5,
    form: "lvshi",
  });

  assert.deepEqual([jueju.type, jueju.charCount, jueju.form], ["tang", 5, "jueju"]);
  assert.deepEqual([lvshi.type, lvshi.charCount, lvshi.form], ["tang", 7, "lvshi"]);
  assert.deepEqual([pailv.type, pailv.result.stats.charCount], ["pailv", 5]);
});

test("Haiku checks the fixed 5-7-5 structure", () => {
  const result = evaluateHaiku("春山夜雨花\n春山夜雨花月风\n夜雨花月山", lexicon);
  assert.equal(result.issues.length, 0);
  assert.equal(result.lines.length, 3);
  assert.equal(result.structureScore, 100);
});

test("Pailv accepts ten equal-length lines without extra options", () => {
  const text = Array(10).fill("春山夜雨花").join("\n");
  const result = evaluatePailv(text, lexicon);
  assert.equal(result.stats.charCount, 5);
  assert.equal(result.lines.length, 10);
  assert.equal(result.issues.length, 0);
  assert.equal(result.structureScore, 100);
});

test("Pailv reports the even-position error without cascading a false isolated level", () => {
  const lines = Array(15).fill("山春山夜山春花");
  lines.push("夜春雨花月山风");
  const result = evaluatePailv(lines.join("\n"), lexicon);
  const lastLine = result.lines.at(-1).characters;

  assert.equal(lastLine[1].tone, "平");
  assert.equal(lastLine[1].expected, "平");
  assert.equal(lastLine[1].error, false);
  assert.equal(lastLine[3].tone, "平");
  assert.equal(lastLine[3].expected, "仄");
  assert.equal(lastLine[3].error, true);
  assert.deepEqual(
    result.violations
      .filter((item) => item.lineIndex === 15)
      .map((item) => [item.charIndex, item.rule]),
    [[3, "二四六分明"]],
  );
});

test("Pailv never treats a rhyming-line even position as isolated-level rescue", () => {
  const lines = Array(15).fill("山春山夜山春花");
  lines.push("夜春雨花月山风");
  const result = evaluatePailv(lines.join("\n"), lexicon, { allowAoJiu: true });
  const lastLine = result.lines.at(-1).characters;

  assert.equal(lastLine[1].error, false);
  assert.equal(lastLine[3].error, true);
});

const toneLine = (pattern) => pattern.replaceAll("P", "山").replaceAll("Z", "雨");
const pailvPatterns = [
  "PPZZPPZ", "PZZPPZP", "PZZPPZZ", "PPZZZPP",
  "PPZZPPZ", "PZZPPZP", "PZZPPZZ", "PPZZZPP",
  "PPZZPPZ", "PZZPPZP", "PZZPPZZ", "PPZZZPP",
  "PPZZPPZ", "PZZPPZP", "PZZPPZZ", "PPZZZPP",
];

test("Pailv still reports an isolated fourth-position level when it is the only non-rhyme level", () => {
  const patterns = [...pailvPatterns];
  patterns[1] = "ZZZPZZP";
  const result = evaluatePailv(
    patterns.map(toneLine).join("\n"),
    lexicon,
  );

  assert.equal(
    result.violations.some((item) => item.lineIndex === 1 && item.rule === "孤平"),
    true,
  );
});

test("Pailv accepts six-ao fifth-position self rescue and non-rhyming triple oblique", () => {
  const patterns = [...pailvPatterns];
  patterns[12] = "PPZZPZZ";
  const result = evaluatePailv(
    patterns.map(toneLine).join("\n"),
    lexicon,
    { allowAoJiu: true },
  );

  assert.equal(result.violations.some((item) => item.lineIndex === 12), false);
});

test("Pailv requires the following line to rescue unresolved major ao", () => {
  const rescued = [...pailvPatterns];
  rescued[12] = "PPZZZZZ";
  rescued[13] = "PZZPPZP";
  const accepted = evaluatePailv(
    rescued.map(toneLine).join("\n"),
    lexicon,
    { allowAoJiu: true },
  );
  assert.equal(accepted.violations.some((item) => [12, 13].includes(item.lineIndex)), false);

  const unrescued = [...rescued];
  unrescued[13] = "PZZPZZP";
  const rejected = evaluatePailv(
    unrescued.map(toneLine).join("\n"),
    lexicon,
    { allowAoJiu: true },
  );
  assert.equal(
    rejected.violations.some(
      (item) => item.lineIndex === 13 && item.charIndex === 4 && item.rule === "对句相救",
    ),
    true,
  );
});

test("Pailv accepts the special fifth-sixth position exchange only on non-rhyming lines", () => {
  const patterns = [...pailvPatterns];
  patterns[14] = "PZPPZPZ";
  const result = evaluatePailv(
    patterns.map(toneLine).join("\n"),
    lexicon,
    { allowAoJiu: true },
  );

  assert.equal(result.violations.some((item) => item.lineIndex === 14), false);
});

test("月夜 marks both five-character self-rescue exchanges", () => {
  const result = evaluateTang(
    "今夜鄜州月，闺中只独看。遥怜小儿女，未解忆长安。"
      + "香雾云鬟湿，清辉玉臂寒。何时倚虚幌，双照泪痕干。",
    { charCount: 5, form: "lvshi", allowAoJiu: true },
    pinshuiLexicon,
  );

  assert.equal(result.violations.length, 0);
  assert.deepEqual(
    result.aoJiu.details
      .filter((item) => item.rule === "特拗交换")
      .map((item) => item.message),
    [
      "第 3 句“小儿”平仄互换，符合本句自救。",
      "第 7 句“倚虚”平仄互换，符合本句自救。",
    ],
  );
  assert.deepEqual(result.lines[2].characters[2].roles, ["ao"]);
  assert.deepEqual(result.lines[2].characters[3].roles, ["rescue"]);
});

test("江南春 marks 十 and 烟 as a cross-line rescue pair", () => {
  const result = evaluateTang(
    "千里莺啼绿映红，水村山郭酒旗风。南朝四百八十寺，多少楼台烟雨中。",
    { charCount: 7, form: "jueju", allowAoJiu: true },
    pinshuiLexicon,
  );
  const crossRescue = result.aoJiu.details.find((item) => item.rule === "对句相救");

  assert.equal(result.violations.length, 0);
  assert.equal(
    crossRescue.message,
    "第 3 句第 6 字“十”拗，第 4 句第 5 字“烟”救，符合对句相救。",
  );
  assert.deepEqual(result.lines[2].characters[5].roles, ["ao"]);
  assert.deepEqual(result.lines[3].characters[4].roles, ["rescue"]);
});

test("夜泊水村 marks cross-line rescue and the 泊船 self rescue", () => {
  const result = evaluateTang(
    "腰间羽箭久凋零，太息燕然未勒铭。老子犹堪绝大漠，诸君何至泣新亭。"
      + "一身报国有万死，双鬓向人无再青。记取江湖泊船处，卧闻新雁落寒汀。",
    { charCount: 7, form: "lvshi", allowAoJiu: true },
    pinshuiLexicon,
  );

  assert.equal(result.violations.length, 0);
  assert.equal(
    result.aoJiu.details.some((item) => item.rule === "对句相救"
      && item.message.includes("“万”") && item.message.includes("“无”")),
    true,
  );
  assert.equal(
    result.aoJiu.details.some((item) => item.rule === "一字两救"),
    false,
  );
  assert.deepEqual(result.lines[5].characters[2].roles, []);
  assert.equal(
    result.aoJiu.details.some((item) => item.rule === "特拗交换"
      && item.message.includes("“泊船”")),
    true,
  );
  assert.deepEqual(result.lines[4].characters[5].roles, ["ao"]);
  assert.deepEqual(result.lines[5].characters[4].roles, ["rescue"]);
  assert.deepEqual(result.lines[6].characters[4].roles, ["ao"]);
  assert.deepEqual(result.lines[6].characters[5].roles, ["rescue"]);
});

test("登高按多音字读法判断长字造成的孤平", () => {
  const text = "风急天高猿啸哀，渚清沙白鸟飞回。"
    + "无边落木萧萧下，不尽长江滚滚来。";
  const permissive = evaluateTang(
    text,
    { charCount: 7, form: "jueju", allowAoJiu: false },
    pinshuiLexicon,
  );
  const strict = evaluateTang(
    text,
    { charCount: 7, form: "jueju", allowAoJiu: false, strictPolyphonic: true },
    pinshuiLexicon,
  );

  assert.equal(permissive.violations.length, 0);
  assert.equal(permissive.lines[3].characters[2].polyphonic, true);
  assert.equal(
    strict.violations.some((item) => item.lineIndex === 3
      && item.charIndex === 3 && item.rule === "孤平"),
    true,
  );

  const automatic = evaluateTang(
    text,
    {
      charCount: 7,
      form: "jueju",
      allowAoJiu: false,
      polyphonicMode: "automatic",
    },
    pinshuiLexicon,
  );
  assert.equal(automatic.lines[3].characters[2].selectedTone, "平");
  assert.equal(automatic.lines[3].characters[2].decisionReason, "若为仄声，则本句犯孤平");
});

test("闺怨 marks 数花 as a seven-character self-rescue exchange", () => {
  const result = evaluateTang(
    "新妆宜面下朱楼，深锁春光一院愁。"
      + "行到中庭数花朵，蜻蜓飞上玉搔头。",
    { charCount: 7, form: "jueju", allowAoJiu: true },
    pinshuiLexicon,
  );

  assert.equal(result.violations.length, 0);
  assert.equal(result.lines[2].characters[2].polyphonic, true);
  assert.equal(result.lines[2].characters[2].tone.includes("平"), true);
  assert.equal(
    result.aoJiu.details.some((item) => item.rule === "特拗交换"
      && item.message === "第 3 句“数花”平仄互换，符合本句自救。"),
    true,
  );
  assert.deepEqual(result.lines[2].characters[4].roles, ["ao"]);
  assert.deepEqual(result.lines[2].characters[5].roles, ["rescue"]);

  const automatic = evaluateTang(
    "新妆宜面下朱楼，深锁春光一院愁。"
      + "行到中庭数花朵，蜻蜓飞上玉搔头。",
    {
      charCount: 7,
      form: "jueju",
      allowAoJiu: true,
      polyphonicMode: "automatic",
    },
    pinshuiLexicon,
  );
  assert.equal(automatic.lines[2].characters[2].selectedTone, "平");
  assert.equal(
    automatic.lines[2].characters[2].decisionReason,
    "若为仄声，则本句特拗自救不成立",
  );
});
