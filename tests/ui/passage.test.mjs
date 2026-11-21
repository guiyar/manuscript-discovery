// The passage is the user's, not the translation's: choosing between translations must never move it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { $, fire, open, pick, previewImages, problems, sleep, vals, waitFor } from "./helpers.mjs";

test("first visit: KJV Genesis 1:1–2:3, continuous text, previewing by itself", async (t) => {
  const w = await open("");
  await t.test("the defaults", () => {
    assert.equal($(w, "t1").value, "King James Version (KJV)");
    assert.equal($(w, "book").value, "GEN");
    assert.equal(vals(w), "1/1/2/3");
    assert.equal($(w, "paragraphs").checked, false, "paragraph breaks are off by default");
    assert.ok($(w, "poetry").checked && $(w, "line_numbers").checked && $(w, "notes").checked);
    assert.equal(problems(w), "");
  });
  await t.test("the state is written to the URL", () => {
    assert.match(w.location.search, /book=GEN/);
    assert.match(w.location.search, /paragraphs=0/);
  });
  await t.test("a preview appears without pressing anything", async () => {
    await waitFor(() => previewImages(w).length >= 1, { what: "the preview" });
  });
  await t.test("the text view is the titled passage as one continuous block", async () => {
    $(w, "viewText").click();
    await waitFor(() => !$(w, "text").hidden && $(w, "text").textContent.length > 0, { what: "the text view" });
    const text = $(w, "text").textContent;
    assert.ok(text.startsWith("Genesis 1:1–2:3\n\nIn the beginning God created"), text.slice(0, 80));
    const body = text.split("\n—")[0].trim().split("\n\n");
    assert.equal(body.length, 2, "title, then a single block of text");
  });
});

test("switching translations never resets the passage", async (t) => {
  const w = await open("?t1=eng-kjv2006&book=EPH&c1=1&v1=2&c2=2&v2=3");
  assert.equal(vals(w), "1/2/2/3");
  assert.equal($(w, "book").value, "EPH");
  assert.equal(problems(w), "");
  assert.equal($(w, "download").disabled, false);

  await t.test("to Greek: passage kept, the translation's own book name shown", async () => {
    await pick(w, "t1", "Greek Textus Receptus (TR)");
    assert.equal(vals(w), "1/2/2/3");
    assert.equal($(w, "book").value, "EPH");
    assert.equal($(w, "book").selectedOptions[0].textContent, "Ἐφεσίους");
    assert.equal(problems(w), "");
  });

  await t.test("to a translation too short for it: still not reset, and says exactly what is missing", async () => {
    await pick(w, "t1", "Tiny Version (TNY)");
    assert.equal(vals(w), "1/2/2/3");
    assert.match(problems(w), /Tiny Version has 1 chapters of Ephesians/);
    assert.equal($(w, "download").disabled, true);
  });

  await t.test("no preview is requested for a passage that cannot be set", async () => {
    const before = w.__previews;
    await sleep(1200);
    assert.equal(w.__previews, before);
  });

  await t.test("back to the first: valid again, passage intact", async () => {
    await pick(w, "t1", "King James Version (KJV)");
    assert.equal(vals(w), "1/2/2/3");
    assert.equal(problems(w), "");
    assert.equal($(w, "download").disabled, false);
  });

  await t.test("fitting the passage is an explicit action, and only then does it change", async () => {
    await pick(w, "t1", "Tiny Version (TNY)");
    assert.equal(vals(w), "1/2/2/3");
    const fit = [...$(w, "problems").querySelectorAll("button")][0];
    assert.match(fit?.textContent ?? "", /Fit/);
    fit.click();
    assert.equal(vals(w), "1/2/1/3");
    assert.equal(problems(w), "");
  });
});

test("a book the translation lacks stays selected, flagged, with the verses untouched", async () => {
  const w = await open("?t1=eng-kjv2006&book=GEN&c1=2&v1=2&c2=2&v2=3");
  assert.equal(vals(w), "2/2/2/3");
  assert.equal(problems(w), "");
  await pick(w, "t1", "Tiny Version (TNY)");
  assert.equal($(w, "book").value, "GEN");
  assert.match($(w, "book").selectedOptions[0].textContent, /not in this translation/);
  assert.match(problems(w), /Tiny Version does not contain Genesis/);
  assert.equal(vals(w), "2/2/2/3");
});

test("choosing a different book is a new passage, and the state lives in the URL", async () => {
  const w = await open("?t1=eng-kjv2006&book=GEN&c1=2&v1=2&c2=2&v2=3");
  $(w, "book").value = "PSA";
  fire(w, $(w, "book"), "change");
  assert.equal(vals(w), "1/1//");
  assert.match(w.location.search, /book=PSA/);
  assert.match(w.location.search, /t1=eng-kjv2006/);
});

test("a parallel pair is checked against both translations", async () => {
  const w = await open("?t1=eng-kjv2006&t2=tiny&book=EPH&c1=1&v1=1&c2=2&v2=");
  assert.match(problems(w), /Tiny Version has 1 chapters/);
});
