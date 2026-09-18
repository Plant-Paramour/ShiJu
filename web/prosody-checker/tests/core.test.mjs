import test from "node:test";
import assert from "node:assert/strict";

import {
  buildLexicon,
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

test("Pailv does not cascade a fourth-position error into a false isolated-level error", () => {
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

test("Pailv can allow a recognized aojiu pattern", () => {
  const lines = Array(15).fill("山春山夜山春花");
  lines.push("夜春雨花月山风");
  const result = evaluatePailv(lines.join("\n"), lexicon, { allowAoJiu: true });
  const lastLine = result.lines.at(-1).characters;

  assert.equal(lastLine[1].error, false);
  assert.equal(lastLine[3].error, false);
  assert.equal(result.violations.some((item) => item.lineIndex === 15), false);
});
