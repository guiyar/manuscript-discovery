// A library without the first-visit translation must still open cleanly.
import assert from "node:assert/strict";
import { test } from "node:test";
import { $, BASE_NO_KJV, open, vals } from "./helpers.mjs";

test("without the KJV, a first visit falls back to the first translation's first chapter", { skip: !BASE_NO_KJV }, async () => {
  const w = await open("", BASE_NO_KJV);
  assert.notEqual($(w, "t1").value, "", "a translation was chosen");
  assert.notEqual($(w, "book").value, "", "a book was chosen");
  assert.equal(vals(w), "1/1//");
  assert.doesNotMatch($(w, "problems").textContent, /Choose/);
});
