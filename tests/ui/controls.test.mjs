// The form's controls: translations in language sets, chapter and verse selectors, the section
// order, collapsible settings, and the drawer used on small screens.
import assert from "node:assert/strict";
import { test } from "node:test";
import { $, fire, open, optionsOf, pick, problems, waitFor } from "./helpers.mjs";

const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent("keydown", { key: k, bubbles: true }));
const values = (w, id) => [...$(w, id).options].map((o) => o.value);

test("the translation list is in language sets, sorted, and choosing from it works", async (t) => {
  const w = await open("");
  const input = $(w, "t1"), list = $(w, "t1-list");
  input.focus();
  await waitFor(() => optionsOf(w, "t1").length > 1, { what: "the list" });

  await t.test("grouped by language, languages and translations both sorted", () => {
    const groups = [...list.querySelectorAll("[role=group]")];
    const names = groups.map((g) => g.getAttribute("aria-label"));
    assert.ok(names.includes("English") && names.includes("Greek") && names.includes("Chinese"));
    assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b)));
    const english = groups.find((g) => g.getAttribute("aria-label") === "English");
    assert.deepEqual([...english.querySelectorAll("[role=option]")].map((o) => o.textContent),
      ["King James Version (KJV)", "Tiny Version (TNY)"]);
  });

  await t.test("the current choice is marked", () => {
    const marked = optionsOf(w, "t1").filter((o) => o.getAttribute("aria-selected") === "true");
    assert.deepEqual(marked.map((o) => o.textContent), ["King James Version (KJV)"]);
  });

  await t.test("typing narrows it", async () => {
    input.value = "greek";
    fire(w, input);
    await waitFor(() => optionsOf(w, "t1").length === 1, { what: "the narrowed list" });
    assert.equal(optionsOf(w, "t1")[0].textContent, "Greek Textus Receptus (TR)");
  });

  await t.test("Escape closes it and puts the current choice back", () => {
    key(w, input, "Escape");
    assert.equal(list.hidden, true);
    assert.equal(input.value, "King James Version (KJV)");
  });

  await t.test("the keyboard chooses too", async () => {
    input.value = "tiny";
    fire(w, input);
    await waitFor(() => optionsOf(w, "t1").map((o) => o.textContent).join() === "Tiny Version (TNY)", { what: "tiny" });
    key(w, input, "Enter");
    await waitFor(() => input.value === "Tiny Version (TNY)", { what: "the choice" });
    await waitFor(() => /t1=tiny/.test(w.location.search), { what: "the choice in the URL" });
  });
});

test("emptying the parallel translation removes it; text that was not chosen is undone", async () => {
  const w = await open("?t1=eng-kjv2006&book=GEN&c1=1");
  await pick(w, "t2", "Tiny Version (TNY)");
  assert.match(w.location.search, /t2=tiny/);
  const t2 = $(w, "t2");
  t2.focus();
  t2.value = "";
  fire(w, t2);
  t2.blur();
  await waitFor(() => !/t2=/.test(w.location.search), { what: "the parallel translation to go" });

  const t1 = $(w, "t1");
  t1.focus();
  t1.value = "something nobody chose";
  fire(w, t1);
  t1.blur();
  assert.equal(t1.value, "King James Version (KJV)");
  assert.match(w.location.search, /t1=eng-kjv2006/);
});

test("chapter and verse are selectors listing what exists", async (t) => {
  const w = await open("?t1=eng-kjv2006&book=GEN&c1=1&v1=1&c2=2&v2=3");

  await t.test("the numbers that are there, with 'same' and 'end' for the optional ones", () => {
    assert.deepEqual(values(w, "c1"), ["1", "2"]);
    assert.deepEqual(values(w, "c2"), ["", "1", "2"]);
    assert.deepEqual(values(w, "v1"), ["1", "2", "3"]);          // Genesis 1 has 3 verses
    assert.deepEqual(values(w, "v2"), ["", "1", "2", "3", "4"]);   // the range ends in chapter 2, which has 4
    assert.equal($(w, "c2").options[0].textContent, "same");
    assert.equal($(w, "v2").options[0].textContent, "end");
  });

  await t.test("changing chapter lists that chapter's verses and keeps the verse inside it", () => {
    $(w, "c1").value = "2";
    fire(w, $(w, "c1"));
    assert.deepEqual(values(w, "v1"), ["1", "2", "3", "4"]);
    $(w, "v1").value = "4";
    fire(w, $(w, "v1"));
    $(w, "c1").value = "1";
    fire(w, $(w, "c1"));
    assert.equal($(w, "v1").value, "3", "clamped to the last verse of chapter 1");
  });

  await t.test("with a parallel translation only numbers both have are offered", async () => {
    const both = await open("?t1=eng-kjv2006&t2=tiny&book=EPH&c1=1&v1=1");
    assert.deepEqual(values(both, "c1"), ["1"]);   // Tiny's Ephesians has one chapter, the KJV's has two
    assert.equal(problems(both), "");
  });

  await t.test("a number from a shared link that is not there is kept and reported, not lost", async () => {
    const odd = await open("?t1=eng-kjv2006&book=GEN&c1=1&v1=99");
    assert.equal($(odd, "v1").value, "99");
    assert.match(problems(odd), /has 3 verses, not 99/);
  });
});

test("the form's sections: Passage, Translation, Download, then Settings", async () => {
  const w = await open("");
  const doc = w.document;
  const form = $(w, "form");
  assert.deepEqual([...form.querySelectorAll("legend.heading")].map((l) => l.textContent), ["Passage", "Translation"]);
  const before = (a, b) => Boolean(a.compareDocumentPosition(b) & w.Node.DOCUMENT_POSITION_FOLLOWING);
  const [passage, translation] = form.querySelectorAll("fieldset");
  const settings = form.querySelector("details");
  assert.ok(before(passage, translation) && before(translation, $(w, "download")) && before(w.document.getElementById("download"), settings));
  assert.match(form.querySelector("header p").textContent, /^Biblical passages set as clean manuscripts for study\.$/);
  assert.ok(doc.querySelector("main").textContent.indexOf("Biblical passages") < 0, "the subtitle lives in the drawer");
});

test("Settings collapses, and Page inside it collapses on its own", async () => {
  const w = await open("");
  const [settings, page] = $(w, "form").querySelectorAll("details");
  assert.equal(settings.querySelector("summary").textContent.trim(), "Settings");
  assert.equal(page.querySelector("summary").textContent.trim(), "Page");
  assert.ok(settings.contains(page));
  assert.ok(settings.open && !page.open, "Settings starts open, Page closed");
  page.open = true;
  settings.open = false;
  assert.ok(page.open, "Page keeps its own state");
  for (const id of ["paper", "size", "title"]) assert.ok(page.contains($(w, id)));
  for (const id of ["paragraphs", "poetry", "line_numbers", "notes", "colophon"]) assert.ok(settings.contains($(w, id)));
});

test("on small screens the form is a drawer, and the download button is separate and fixed", async (t) => {
  const w = await open("");
  const form = $(w, "form");
  const state = () => [form.hasAttribute("data-open"), $(w, "backdrop").hidden, $(w, "menu").getAttribute("aria-expanded")];
  assert.deepEqual(state(), [false, true, "false"]);

  await t.test("the menu button opens it", () => {
    $(w, "menu").click();
    assert.deepEqual(state(), [true, false, "true"]);
  });
  await t.test("Escape closes it", () => {
    key(w, w.document, "Escape");
    assert.deepEqual(state(), [false, true, "false"]);
  });
  await t.test("so do the backdrop and the close button", () => {
    $(w, "menu").click();
    $(w, "backdrop").click();
    assert.deepEqual(state(), [false, true, "false"]);
    $(w, "menu").click();
    $(w, "closeMenu").click();
    assert.deepEqual(state(), [false, true, "false"]);
  });
  await t.test("the fixed download button is outside the drawer, and both stay in step", async () => {
    assert.ok(!form.contains($(w, "downloadFloat")) && form.contains($(w, "download")));
    assert.equal($(w, "download").disabled || $(w, "downloadFloat").disabled, false);
    await pick(w, "t1", "Tiny Version (TNY)");   // no Genesis: nothing to download
    assert.ok($(w, "download").disabled && $(w, "downloadFloat").disabled);
  });
});

test("the view switch and the status float over the preview", async () => {
  const w = await open("");
  const preview = $(w, "pages").parentElement;
  for (const el of [$(w, "status"), $(w, "viewPage").parentElement]) assert.ok(preview.contains(el));
});
