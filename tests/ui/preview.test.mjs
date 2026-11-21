// The live preview: low-resolution PNGs, debounced, cancelled when stale, and tied to the options.
import assert from "node:assert/strict";
import { test } from "node:test";
import { $, BASE, fire, open, previewImages, problems, sleep, spacingRadios, type, waitFor } from "./helpers.mjs";

test("the preview is a real, screen-resolution PNG and follows changes without a button", async (t) => {
  const w = await open("");
  await waitFor(() => previewImages(w).length >= 1, { what: "the first preview" });

  await t.test("exactly one request for the first view", () => assert.equal(w.__previews, 1));

  await t.test("the page image is served as a low-resolution PNG, not a print-quality one", async () => {
    const src = previewImages(w)[0].getAttribute("src");
    assert.match(src, /^\/api\/preview\/[0-9a-f]{32}\/1\.png$/);
    const res = await fetch(new URL(src, BASE));
    assert.equal(res.status, 200);
    assert.match(res.headers.get("cache-control"), /immutable/);
    const png = Buffer.from(await res.arrayBuffer());
    assert.equal(png.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
    assert.ok(png.readUInt32BE(16) < 1000, `A4 at print resolution would be 2480 px wide, got ${png.readUInt32BE(16)}`);
  });

  await t.test("ten rapid edits cause exactly one new request (debounced)", async () => {
    const before = w.__previews;
    for (let i = 0; i < 10; i++) { await type(w, "title", `T${i}`); await sleep(40); }
    await waitFor(() => w.__previews === before + 1, { what: "the debounced request" });
    await sleep(900);
    assert.equal(w.__previews, before + 1, "no further requests after the debounce fired");
  });

  await t.test("an invalid passage asks for nothing, and the last good preview stays up", async () => {
    await type(w, "title", "");
    await waitFor(() => w.__previews >= 3, { what: "the title reset to preview" });
    await sleep(700);
    const before = w.__previews;
    await type(w, "v1", "99");
    await waitFor(() => problems(w) !== "", { what: "the problem message" });
    await sleep(1000);
    assert.equal(w.__previews, before);
    assert.ok(previewImages(w).length >= 1, "the previous preview is still shown");
    await type(w, "v1", "1");
  });

  await t.test("the Text view shows the plain text, and Page brings the typeset page back", async () => {
    $(w, "viewText").click();
    await waitFor(() => !$(w, "text").hidden && $(w, "text").textContent.startsWith("Genesis"), { what: "the text view" });
    $(w, "viewPage").click();
    await waitFor(() => !$(w, "pages").hidden, { what: "the page view" });
  });
});

test("line spacing belongs to 'Space for notes'", async (t) => {
  const w = await open("");
  await waitFor(() => previewImages(w).length >= 1, { what: "the first preview" });
  const [normal, double] = spacingRadios(w);

  await t.test("1.5 lines by default", () => {
    assert.deepEqual(spacingRadios(w).map((r) => r.value), ["1.5", "2"]);
    assert.ok(normal.checked && !double.checked);
    assert.equal($(w, "spacingBox").disabled, false);
  });

  await t.test("choosing double reaches the preview request and the URL", async () => {
    double.checked = true;
    fire(w, double);
    await waitFor(() => w.__lastPreview.includes("line_spacing=2"), { what: "a preview request for double spacing" });
    assert.match(w.location.search, /line_spacing=2/);
  });

  await t.test("unticking 'Space for notes' disables the choice; ticking again restores it", () => {
    $(w, "notes").checked = false;
    fire(w, $(w, "notes"));
    assert.ok($(w, "spacingBox").disabled && spacingRadios(w).every((r) => r.matches(":disabled")));
    $(w, "notes").checked = true;
    fire(w, $(w, "notes"));
    assert.ok(!$(w, "spacingBox").disabled && double.checked, "enabled again, with the choice remembered");
  });

  await t.test("a shared link restores double spacing", async () => {
    const other = await open("?t1=eng-kjv2006&book=GEN&c1=1&line_spacing=2");
    assert.ok(spacingRadios(other)[1].checked);
  });
});
