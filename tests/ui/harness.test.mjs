// Guards the harness itself: the page's fetch must accept the page's own AbortSignal and honour it.
// Node 24 rejects jsdom's AbortSignal outright, which silently broke every live-preview test.
import assert from "node:assert/strict";
import http from "node:http";
import { test } from "node:test";
import { open } from "./helpers.mjs";

test("a request carrying the page's AbortSignal is accepted, and aborting it cancels the request", async () => {
  // A server that accepts connections and never answers, so the request is certainly in flight.
  const silent = http.createServer(() => {});
  await new Promise((resolve) => silent.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${silent.address().port}/`;
  try {
    const w = await open();

    const inFlight = new w.AbortController();
    const request = w.fetch(url, { signal: inFlight.signal });
    setTimeout(() => inFlight.abort(), 50);
    await assert.rejects(request, { name: "AbortError" });

    const already = new w.AbortController();
    already.abort();
    await assert.rejects(w.fetch(url, { signal: already.signal }), { name: "AbortError" });
  } finally {
    silent.closeAllConnections();
    silent.close();
  }
});
