const HAN_CHAR = /[\u3400-\u9fff]/u;
const CLAUSE_SEPARATOR = /[，,。.！!？?、；;：:\n\r]+/u;

export const TONE_PING = "平";
export const TONE_ZE = "仄";
export const TONE_FLEX = "中";

export function buildLexicon(rawData) {
  const characters = new Map();
  for (const [part, toneGroups] of Object.entries(rawData)) {
    for (const [toneName, values] of Object.entries(toneGroups)) {
      const tone = toneName.includes("平") ? TONE_PING : TONE_ZE;
      for (const char of values) {
        let entry = characters.get(char);
        if (!entry) {
          entry = {
            tones: new Set(),
            parts: new Set(),
            partsByTone: new Map([[TONE_PING, new Set()], [TONE_ZE, new Set()]]),
            readings: new Set(),
          };
          characters.set(char, entry);
        }
        entry.tones.add(tone);
        entry.parts.add(part);
        entry.partsByTone.get(tone).add(part);
        entry.readings.add(tone + ":" + part);
      }
    }
  }
  return {
    lookup(char) {
      const entry = characters.get(char);
      if (!entry) {
        return {
          tones: new Set(),
          parts: new Set(),
          partsByTone: new Map([[TONE_PING, new Set()], [TONE_ZE, new Set()]]),
          readings: new Set(),
          polyphonic: false,
        };
      }
      return {
        tones: entry.tones,
        parts: entry.parts,
        partsByTone: entry.partsByTone,
        readings: entry.readings,
        polyphonic: entry.readings.size > 1,
      };
    },
  };
}

export function parsePoem(text) {
  const markerIndex = text.indexOf("[content]");
  const content = markerIndex >= 0 ? text.slice(markerIndex + 9) : text;
  return content
    .trim()
    .split(CLAUSE_SEPARATOR)
    .map((part) => [...part].filter((char) => HAN_CHAR.test(char)).join(""))
    .filter(Boolean);
}

function percentage(value) {
  return Math.round(value * 10000) / 100;
}

function key(lineIndex, charIndex) {
  return lineIndex + ":" + charIndex;
}

function toneLabel(tones) {
  if (tones.size === 0) return TONE_FLEX;
  if (tones.size === 1) return [...tones][0];
  return TONE_PING + "/" + TONE_ZE;
}

function annotateLines(lines, lexicon, errors, expectedByPosition = new Map()) {
  return lines.map((text, lineIndex) => ({
    text,
    characters: [...text].map((char, charIndex) => {
      const entry = lexicon.lookup(char);
      return {
        char,
        tone: toneLabel(entry.tones),
        tones: [...entry.tones],
        polyphonic: entry.polyphonic,
        error: errors.has(key(lineIndex, charIndex)),
        expected: expectedByPosition.get(key(lineIndex, charIndex)) ?? null,
      };
    }),
  }));
}

function scoreRhymeGroups(
  lines,
  groups,
  lexicon,
  toneByGroup = new Map(),
  options = {},
) {
  const strictPolyphonic = Boolean(options.strictPolyphonic);
  const details = [];
  for (let groupIndex = 0; groupIndex < groups.length; groupIndex += 1) {
    const positions = groups[groupIndex];
    const expectedTone = toneByGroup.get(groupIndex);
    const endings = [];
    const counts = new Map();
    for (const lineIndex of positions) {
      const line = lines[lineIndex];
      if (!line) continue;
      const char = [...line].at(-1);
      const entry = lexicon.lookup(char);
      let parts;
      if (strictPolyphonic) {
        const readings = [...entry.readings].map((reading) => {
          const separator = reading.indexOf(":");
          return { tone: reading.slice(0, separator), part: reading.slice(separator + 1) };
        });
        const uniqueParts = new Set(readings.map((reading) => reading.part));
        const allTonesMatch = !expectedTone
          || readings.every((reading) => reading.tone === expectedTone);
        parts = readings.length && allTonesMatch && uniqueParts.size === 1
          ? uniqueParts
          : new Set();
      } else {
        parts = expectedTone
          ? entry.partsByTone.get(expectedTone) ?? new Set()
          : entry.parts;
      }
      endings.push({ lineIndex, char, parts: [...parts] });
      for (const part of parts) counts.set(part, (counts.get(part) ?? 0) + 1);
    }
    let dominantPart = null;
    let dominantCount = 0;
    for (const [part, count] of counts) {
      if (count > dominantCount) {
        dominantPart = part;
        dominantCount = count;
      }
    }
    details.push({
      positions,
      endings,
      dominantPart,
      matchCount: dominantCount,
      totalCount: endings.length,
      score: endings.length ? dominantCount / endings.length : 0,
    });
  }
  const score = details.length
    ? details.reduce((sum, group) => sum + group.score, 0) / details.length
    : 0;
  return { score, details };
}

function stanzaKeys(variant) {
  return Object.keys(variant)
    .filter((name) => /^stanza\d+$/.test(name))
    .sort((a, b) => Number(a.slice(6)) - Number(b.slice(6)));
}

export function flattenMeter(variant) {
  const clauses = [];
  const rhymeGroups = new Map();
  const stanzaEnds = [];
  for (const stanzaKey of stanzaKeys(variant)) {
    const stanza = variant[stanzaKey];
    const lineToClauses = [];
    for (const rawPattern of stanza.lines ?? []) {
      const clauseIndices = [];
      for (const subPattern of rawPattern.split("、")) {
        const pattern = subPattern.replace(/[\/\s]/g, "");
        if (!pattern) continue;
        clauseIndices.push(clauses.length);
        clauses.push({ pattern, rawPattern: subPattern });
      }
      lineToClauses.push(clauseIndices);
    }
    for (const [name, positions] of Object.entries(stanza)) {
      const match = /^rhyme_(\d+)_positions$/.exec(name);
      if (!match || !Array.isArray(positions)) continue;
      const groupId = Number(match[1]);
      const group = rhymeGroups.get(groupId) ?? [];
      for (const position of positions) {
        const mapped = lineToClauses[position - 1];
        if (mapped?.length) group.push(mapped.at(-1));
      }
      rhymeGroups.set(groupId, group);
    }
    if (clauses.length) stanzaEnds.push(clauses.length - 1);
  }
  return {
    clauses,
    rhymeGroups: [...rhymeGroups.entries()]
      .sort(([left], [right]) => left - right)
      .map(([id, positions]) => ({ id, positions })),
    stanzaEnds,
  };
}

export function formatMeterTemplate(variant) {
  return stanzaKeys(variant).map((stanzaKey) => ({
    name: stanzaKey,
    lines: (variant[stanzaKey].lines ?? []).map((line) => line.replaceAll("/", "")),
  }));
}

export function evaluateSongci(text, variant, lexicon, options = {}) {
  const strictPolyphonic = Boolean(options.strictPolyphonic);
  const lines = parsePoem(text);
  const meter = flattenMeter(variant);
  const errors = new Set();
  const expected = new Map();
  const issues = [];
  let matching = 0;
  let total = 0;
  const common = Math.min(lines.length, meter.clauses.length);
  let structurallyCorrect = 0;

  for (let lineIndex = 0; lineIndex < common; lineIndex += 1) {
    const line = [...lines[lineIndex]];
    const pattern = [...meter.clauses[lineIndex].pattern];
    if (line.length !== pattern.length) {
      issues.push("第 " + (lineIndex + 1) + " 句应为 " + pattern.length
        + " 字，实际为 " + line.length + " 字");
      continue;
    }
    structurallyCorrect += 1;
    for (let charIndex = 0; charIndex < line.length; charIndex += 1) {
      const required = pattern[charIndex];
      const positionKey = key(lineIndex, charIndex);
      expected.set(positionKey, required);
      total += 1;
      const tones = lexicon.lookup(line[charIndex]).tones;
      const toneMatches = strictPolyphonic
        ? tones.size > 0 && [...tones].every((tone) => tone === required)
        : tones.has(required);
      if (required === TONE_FLEX || toneMatches) matching += 1;
      else errors.add(positionKey);
    }
  }
  if (lines.length < meter.clauses.length) {
    issues.push("缺少 " + (meter.clauses.length - lines.length) + " 句");
  } else if (lines.length > meter.clauses.length) {
    issues.push("多出 " + (lines.length - meter.clauses.length) + " 句");
  }

  const rhyme = scoreRhymeGroups(
    lines,
    meter.rhymeGroups.map((group) => group.positions),
    lexicon,
    new Map(),
    options,
  );
  return {
    kind: "songci",
    structureScore: percentage(meter.clauses.length
      ? structurallyCorrect / meter.clauses.length
      : 0),
    tonalScore: percentage(total ? matching / total : 0),
    rhymeScore: percentage(rhyme.score),
    lines: annotateLines(lines, lexicon, errors, expected),
    errors,
    issues,
    rhymeGroups: rhyme.details,
    stats: { matchingTones: matching, totalTones: total },
    meter,
  };
}

function expectedLineBase(globalBase, lineIndex) {
  return lineIndex % 4 === 1 || lineIndex % 4 === 2
    ? (globalBase === TONE_PING ? TONE_ZE : TONE_PING)
    : globalBase;
}

function opposite(tone) {
  return tone === TONE_PING ? TONE_ZE : TONE_PING;
}

function forcedTone(entry, tone) {
  return entry.tones.size === 1 && entry.tones.has(tone);
}

function tonesFit(entry, allowedTones, strictPolyphonic) {
  if (entry.tones.size === 0) return false;
  return strictPolyphonic
    ? [...entry.tones].every((tone) => allowedTones.has(tone))
    : [...entry.tones].some((tone) => allowedTones.has(tone));
}

function ruleCanUseTone(entry, tone, strictPolyphonic) {
  return strictPolyphonic ? entry.tones.has(tone) : forcedTone(entry, tone);
}

function rescueHasTone(entry, tone, strictPolyphonic) {
  if (entry.tones.size === 0) return false;
  return strictPolyphonic
    ? [...entry.tones].every((item) => item === tone)
    : entry.tones.has(tone);
}

function detectRhymeTone(lines, lexicon) {
  const endings = lines
    .filter((line, index) => (index + 1) % 2 === 0 && line)
    .map((line) => lexicon.lookup([...line].at(-1)).tones);
  const ping = endings.filter((tones) => tones.has(TONE_PING)).length;
  const ze = endings.filter((tones) => tones.has(TONE_ZE)).length;
  return ping >= ze ? TONE_PING : TONE_ZE;
}

function scoreTangTones(lines, charCount, globalBase, rhymeTone, lexicon, options = {}) {
  const strictPolyphonic = Boolean(options.strictPolyphonic);
  const allowAoJiu = Boolean(options.allowAoJiu);
  const errors = new Set();
  const expected = new Map();
  const violations = [];
  let total = 0;

  function reject(lineIndex, charIndex, rule, required, actualChar) {
    errors.add(key(lineIndex, charIndex));
    violations.push({ lineIndex, charIndex, rule, required, char: actualChar });
  }

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const chars = [...lines[lineIndex]];
    if (chars.length !== charCount) continue;
    total += chars.length;
    const lineBase = expectedLineBase(globalBase, lineIndex);
    const isEven = (lineIndex + 1) % 2 === 0;
    const endTone = isEven ? rhymeTone : lineIndex === 0 ? null : opposite(rhymeTone);
    const endEntry = lexicon.lookup(chars.at(-1));
    const canEndPing = endTone !== TONE_ZE
      && rescueHasTone(endEntry, TONE_PING, strictPolyphonic);
    const checks = [[1, lineBase], [3, opposite(lineBase)]];
    if (charCount === 7) checks.push([5, lineBase]);

    for (const [charIndex, required] of checks) {
      const entry = lexicon.lookup(chars[charIndex]);
      expected.set(key(lineIndex, charIndex), required);
      const allowedTones = new Set([required]);
      const pingBaseRescue = lineBase === TONE_PING
        && charIndex === 3
        && ruleCanUseTone(lexicon.lookup(chars[0]), TONE_ZE, strictPolyphonic)
        && ruleCanUseTone(lexicon.lookup(chars[2]), TONE_ZE, strictPolyphonic);
      const zeBaseRescue = lineBase === TONE_ZE
        && charCount === 7
        && charIndex === 5
        && ruleCanUseTone(lexicon.lookup(chars[2]), TONE_ZE, strictPolyphonic)
        && ruleCanUseTone(lexicon.lookup(chars[4]), TONE_ZE, strictPolyphonic);
      if (allowAoJiu && canEndPing && (pingBaseRescue || zeBaseRescue)) {
        allowedTones.add(TONE_PING);
      }
      if (entry.tones.size && !tonesFit(entry, allowedTones, strictPolyphonic)) {
        reject(lineIndex, charIndex, "二四六分明", required, chars[charIndex]);
      }
    }

    const endingEntries = chars.slice(-3).map((char) => lexicon.lookup(char));
    for (const tone of [TONE_PING, TONE_ZE]) {
      if (endingEntries.every((entry) => ruleCanUseTone(entry, tone, strictPolyphonic))) {
        reject(lineIndex, chars.length - 1, "三连同", "非三连" + tone, chars.at(-1));
      }
    }

    if (endTone) {
      const endIndex = chars.length - 1;
      const entry = lexicon.lookup(chars[endIndex]);
      expected.set(key(lineIndex, endIndex), endTone);
      if (entry.tones.size
        && !tonesFit(entry, new Set([endTone]), strictPolyphonic)) {
        reject(lineIndex, endIndex, "末字收束", endTone, chars[endIndex]);
      }
    }

    const firstCanPing = lineIndex === 0
      && rescueHasTone(endEntry, TONE_PING, strictPolyphonic);
    if (endTone === TONE_PING || firstCanPing) {
      if (lineBase === TONE_PING) {
        const left = lexicon.lookup(chars[0]);
        const right = lexicon.lookup(chars[2]);
        const rescue = lexicon.lookup(chars[3]);
        if (ruleCanUseTone(left, TONE_ZE, strictPolyphonic)
          && ruleCanUseTone(right, TONE_ZE, strictPolyphonic)
          && !rescueHasTone(rescue, TONE_PING, strictPolyphonic)) {
          reject(lineIndex, 1, "孤平", "避免仄平仄", chars[1]);
        }
      } else if (charCount === 7) {
        const left = lexicon.lookup(chars[2]);
        const right = lexicon.lookup(chars[4]);
        const rescue = lexicon.lookup(chars[5]);
        if (ruleCanUseTone(left, TONE_ZE, strictPolyphonic)
          && ruleCanUseTone(right, TONE_ZE, strictPolyphonic)
          && !rescueHasTone(rescue, TONE_PING, strictPolyphonic)) {
          reject(lineIndex, 3, "孤平", "避免仄平仄", chars[3]);
        }
      }
    }
  }

  return {
    score: total ? (total - errors.size) / total : 0,
    errors,
    expected,
    violations,
    total,
  };
}

function selectGlobalBase(lines, charCount, rhymeTone, lexicon, options) {
  const firstSecond = lines[0]?.[1];
  let candidates = firstSecond ? [...lexicon.lookup(firstSecond).tones] : [];
  if (!candidates.length) candidates = [TONE_PING, TONE_ZE];
  let best = null;
  for (const candidate of candidates) {
    const result = scoreTangTones(lines, charCount, candidate, rhymeTone, lexicon, options);
    if (!best || result.score > best.result.score) best = { tone: candidate, result };
  }
  return best;
}

function evaluateTangLike(text, charCount, expectedLineCount, lexicon, kind, options = {}) {
  const lines = parsePoem(text);
  const issues = [];
  let structureMismatches = 0;
  for (let index = 0; index < lines.length; index += 1) {
    if ([...lines[index]].length !== charCount) {
      structureMismatches += 1;
      issues.push("第 " + (index + 1) + " 句应为 " + charCount
        + " 字，实际为 " + [...lines[index]].length + " 字");
    }
  }
  if (expectedLineCount !== null && lines.length !== expectedLineCount) {
    issues.push("应为 " + expectedLineCount + " 句，实际为 " + lines.length + " 句");
  }
  if (kind === "pailv" && (lines.length < 10 || lines.length % 2 !== 0)) {
    issues.push("排律应为不少于十句的偶数句");
  }

  let structure = (lines.length - structureMismatches) / Math.max(lines.length, 1);
  const invalidLineCount = expectedLineCount !== null
    ? lines.length !== expectedLineCount
    : lines.length < 10 || lines.length % 2 !== 0;
  if (invalidLineCount) structure = Math.min(structure, 0.5);

  const rhymeTone = detectRhymeTone(lines, lexicon);
  const selected = selectGlobalBase(lines, charCount, rhymeTone, lexicon, options);
  const tonal = selected?.result ?? {
    score: 0,
    errors: new Set(),
    expected: new Map(),
    violations: [],
    total: 0,
  };
  const rhymePositions = [];
  for (let index = 1; index < lines.length; index += 2) rhymePositions.push(index);
  if (lines[0]) {
    const firstEnd = lexicon.lookup([...lines[0]].at(-1));
    if (firstEnd.tones.has(rhymeTone)) rhymePositions.unshift(0);
  }
  const rhyme = scoreRhymeGroups(
    lines,
    [rhymePositions],
    lexicon,
    new Map([[0, rhymeTone]]),
    options,
  );

  return {
    kind,
    structureScore: percentage(structure),
    tonalScore: percentage(tonal.score),
    rhymeScore: percentage(rhyme.score),
    lines: annotateLines(lines, lexicon, tonal.errors, tonal.expected),
    errors: tonal.errors,
    issues,
    rhymeGroups: rhyme.details,
    violations: tonal.violations,
    stats: {
      matchingTones: tonal.total - tonal.errors.size,
      totalTones: tonal.total,
      globalBase: selected?.tone ?? null,
      rhymeTone,
      charCount,
    },
  };
}

export function evaluateTang(text, options, lexicon) {
  const charCount = Number(options.charCount);
  const lineCount = options.form === "jueju" ? 4 : 8;
  return evaluateTangLike(text, charCount, lineCount, lexicon, "tang", options);
}

export function evaluatePailv(text, lexicon, options = {}) {
  const lines = parsePoem(text);
  const validLengths = lines
    .map((line) => [...line].length)
    .filter((length) => length === 5 || length === 7);
  const charCount = validLengths.length
    ? (validLengths.filter((length) => length === 5).length > validLengths.length / 2 ? 5 : 7)
    : 7;
  return evaluateTangLike(text, charCount, null, lexicon, "pailv", options);
}

export function evaluateHaiku(text, lexicon, options = {}) {
  const strictPolyphonic = Boolean(options.strictPolyphonic);
  const allowAoJiu = Boolean(options.allowAoJiu);
  const lines = parsePoem(text);
  const expectedLengths = [5, 7, 5];
  const errors = new Set();
  const issues = [];
  let total = 0;
  let structurallyCorrect = 0;

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const chars = [...lines[lineIndex]];
    const expectedLength = expectedLengths[lineIndex];
    if (expectedLength === undefined) {
      issues.push("多出第 " + (lineIndex + 1) + " 行");
      continue;
    }
    if (chars.length !== expectedLength) {
      issues.push("第 " + (lineIndex + 1) + " 行应为 " + expectedLength
        + " 字，实际为 " + chars.length + " 字");
      continue;
    }
    structurallyCorrect += 1;
    total += chars.length;
    const ending = chars.slice(-3).map((char) => lexicon.lookup(char));
    for (const tone of [TONE_PING, TONE_ZE]) {
      if (ending.every((entry) => ruleCanUseTone(entry, tone, strictPolyphonic))) {
        errors.add(key(lineIndex, chars.length - 1));
      }
    }
    for (let index = 1; index < chars.length - 1; index += 1) {
      const left = lexicon.lookup(chars[index - 1]);
      const center = lexicon.lookup(chars[index]);
      const right = lexicon.lookup(chars[index + 1]);
      const isolated = ruleCanUseTone(left, TONE_ZE, strictPolyphonic)
        && ruleCanUseTone(center, TONE_PING, strictPolyphonic)
        && ruleCanUseTone(right, TONE_ZE, strictPolyphonic);
      const leftRescue = index >= 2
        && rescueHasTone(lexicon.lookup(chars[index - 2]), TONE_PING, strictPolyphonic);
      const rightRescue = index + 2 < chars.length
        && rescueHasTone(lexicon.lookup(chars[index + 2]), TONE_PING, strictPolyphonic);
      if (isolated && !(allowAoJiu && (leftRescue || rightRescue))) {
        errors.add(key(lineIndex, index));
      }
    }
  }
  if (lines.length < 3) issues.push("缺少 " + (3 - lines.length) + " 行");
  const rhyme = scoreRhymeGroups(lines, [[0, 1, 2]], lexicon, new Map(), options);
  return {
    kind: "haiku",
    structureScore: percentage(structurallyCorrect / expectedLengths.length),
    tonalScore: percentage(total ? (total - errors.size) / total : 0),
    rhymeScore: percentage(rhyme.score),
    lines: annotateLines(lines, lexicon, errors),
    errors,
    issues,
    rhymeGroups: rhyme.details,
    stats: { matchingTones: total - errors.size, totalTones: total },
  };
}
