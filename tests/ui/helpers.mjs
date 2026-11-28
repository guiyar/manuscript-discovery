// Shared helpers: open the real page in jsdom against a real server, and wait on conditions
// rather than fixed sleeps.
import { JSDOM } from "jsdom";

export const BASE = process.env.UI_BASE_URL;
export const BASE_NO_KJV = process.env.UI_BASE_URL_NO_KJV;
if (!BASE) throw new Error("Set UI_BASE_URL to a running server (tests/test_ui.py does this for you).");

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function waitFor(fn, { timeout = 15000, every = 40, what = "the condition" } = {}) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const result = await fn();
    if (result) return result;
    await sleep(every);
  }
  throw new Error(`timed out waiting for ${what}`);
}

export const $ = (w, id) => w.document.getElementById(id);
export const vals = (w) => ["c1", "v1", "c2", "v2"].map((i) => $(w, i).value).join("/");
export const problems = (w) => ($(w, "problems").hidden ? "" : $(w, "problems").textContent);
export const previewImages = (w) => [...$(w, "pages").querySelectorAll("img")];
export const fire = (w, el, type = "input") => el.dispatchEvent(new w.Event(type, { bubbles: true }));
export const spacingRadios = (w) => [...w.document.querySelectorAll("input[name=line_spacing]")];

/**
 * The page and Node's fetch live in different worlds: jsdom has its own AbortController, and
 * Node 24's fetch refuses its signal ("Expected signal to be an instance of AbortSignal").
 * A real browser has a single AbortSignal, so only this harness needs the bridge: abort a Node
 * controller when the page's signal aborts. Without it every live-preview request, which is
 * cancellable, throws before it is sent.
 */
function nodeSignal(signal) {
  if (!signal) return undefined;
  const controller = new AbortController();
  if (signal.aborted) controller.abort();
  else signal.addEventListener("abort", () => controller.abort(), { once: true });
  return controller.signal;
}

/** Open the page. `window.__previews` counts /api/preview requests; `__lastPreview` is the latest URL. */
export async function open(query = "", base = BASE) {
  const dom = await JSDOM.fromURL(new URL(query, base).href, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(w) {
      w.__previews = 0;
      w.__lastPreview = "";
      w.fetch = (u, o = {}) => {
        const url = String(u);
        if (url.startsWith("/api/preview?")) { w.__previews++; w.__lastPreview = url; }
        return fetch(new URL(url, w.location.href), { ...o, signal: nodeSignal(o.signal) });
      };
    },
  });
  const w = dom.window;
  await waitFor(() => $(w, "book").options.length > 0 || $(w, "status").classList.contains("error"), { what: "the page to load" });
  return w;
}

export const optionsOf = (w, id) => [...$(w, `${id}-list`).querySelectorAll("[role=option]")];

/** Choose a translation as a person would: type to narrow the list, click the option, wait for the page to react. */
export async function pick(w, id, label) {
  const el = $(w, id);
  el.focus();
  el.value = label;
  fire(w, el);
  const option = await waitFor(() => optionsOf(w, id).find((o) => o.textContent === label), { what: `${label} in the list` });
  option.click();
  await waitFor(() => !$(w, "status").textContent.startsWith("Loading"), { what: `${label} to load` });
}

export async function type(w, id, value) {
  $(w, id).value = value;
  fire(w, $(w, id));
}
