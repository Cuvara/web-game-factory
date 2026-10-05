// The read-only console observer: one Playwright test that opens a portal's developer
// console in a FRESH, EPHEMERAL browser context, waits for a PERSON to log in in that window,
// and then records what the console shows while the person moves through it. It reads a
// CONFIG file scripts/wgf_publish/observe.py wrote and writes a state file and one record per
// observed page under the config's out_dir; observe.py turns those into index.json and
// summary.md. Copied into a temporary directory and run with `pnpm exec playwright test` in
// the game checkout under wgflib.procs; it never lives in a committed game path.
//
// What it never does, by construction:
//   - act on a page: there is no pointer, keyboard, file or form call in this file; the one
//     navigation is opening the console url once, before anyone has logged in;
//   - load or save a session: the context is created with no storage state and closed at
//     the end; there is no persistent profile and no cookie or storage read;
//   - record a login, CAPTCHA or second-factor page, or a page outside allowed_origins;
//   - record an input's value: values are masked in the snapshot, inputs are masked in the
//     screenshot, and the form inventory reads attributes, never values.
// test_publish_observe.py checks the first two against this file's source.

import { test, type Page } from "@playwright/test";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { pathToFileURL } from "node:url";

type Config = {
  portal: string;
  console_url: string;
  allowed_origins: string[];
  authenticated_url: string | null;
  login_timeout_ms: number;
  max_ms: number;
  poll_ms: number;
  stable_ms: number;
  out_dir: string;
  headless: boolean;
  test_human: string | null;
};

const cfg: Config = JSON.parse(fs.readFileSync(process.env.WGF_OBSERVE_CONFIG!, "utf-8"));
const PAGES = path.join(cfg.out_dir, "pages");
const EMAIL_SOURCE = String.raw`[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`;
const EMAIL = new RegExp(EMAIL_SOURCE, "g");
const ACTION = "log in in the opened browser window; handle CAPTCHA/2FA yourself";
const LOGIN_MARKERS = {
  password: "input[type=password]",
  captcha: [
    "iframe[src*=captcha i]", "iframe[title*=captcha i]", "iframe[src*='challenges.cloudflare.com']",
    "[id*=captcha i]", "[class*=captcha i]", ".g-recaptcha", ".h-captcha", ".cf-turnstile",
  ].join(", "),
  otp: [
    "input[autocomplete=one-time-code]", "input[name*=otp i]", "input[id*=otp i]",
    "input[name*=totp i]", "input[name*=twofactor i]", "input[name*=two_factor i]",
  ].join(", "),
};

type State = {
  portal: string;
  step: "observe";
  status: string;
  url: string | null;
  reason: string;
  action: string | null;
  resume: string | null;
  started_at: string;
  updated_at: string;
  authenticated_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
  pages_recorded: number;
  history: { status: string; at: string; url: string | null }[];
};

const now = () => new Date().toISOString();
const state: State = {
  portal: cfg.portal,
  step: "observe",
  status: "STARTING",
  url: null,
  reason: "the browser is starting",
  action: null,
  resume: null,
  started_at: now(),
  updated_at: now(),
  authenticated_at: null,
  ended_at: null,
  end_reason: null,
  pages_recorded: 0,
  history: [],
};

function writeState() {
  fs.mkdirSync(cfg.out_dir, { recursive: true });
  state.updated_at = now();
  const file = path.join(cfg.out_dir, "state.json");
  fs.writeFileSync(file + ".tmp", JSON.stringify(state, null, 2));
  fs.renameSync(file + ".tmp", file);
}

function transition(status: string, url: string | null, reason: string, action: string | null,
                    resume: string | null) {
  state.status = status;
  state.url = url;
  state.reason = reason;
  state.action = action;
  state.resume = resume;
  state.history.push({ status, at: now(), url });
  writeState();
  const parts = [status, `portal=${cfg.portal}`, "step=observe", `url=${url ?? "-"}`,
                 `reason=${JSON.stringify(reason)}`];
  if (action) parts.push(`action=${JSON.stringify(action)}`);
  if (resume) parts.push(`resume=${JSON.stringify(resume)}`);
  console.log(parts.join(" "));
}

// Origin and path only: a query or fragment can carry a token, a code or an email.
function bare(url: string): string {
  try {
    const u = new URL(url);
    return u.protocol === "about:" || u.protocol === "data:" ? u.protocol : u.origin + u.pathname;
  } catch {
    return "";
  }
}

function onAllowedOrigin(url: string): boolean {
  try {
    const origin = new URL(url).origin;
    return cfg.allowed_origins.some((o) => origin === new URL(o).origin);
  } catch {
    return false;
  }
}

async function present(page: Page, selector: string): Promise<boolean> {
  try {
    const all = page.locator(selector);
    const count = Math.min(await all.count(), 10);
    for (let i = 0; i < count; i++) if (await all.nth(i).isVisible()) return true;
  } catch {
    return true; // a page that cannot be read is not a page that may be recorded
  }
  return false;
}

// Why a page is not (yet) the authenticated console, or null when it is.
async function notAuthenticated(page: Page): Promise<string | null> {
  const url = page.url();
  if (!onAllowedOrigin(url)) return `the page is outside the console's allowed origins (${bare(url) || "blank"})`;
  if (await present(page, LOGIN_MARKERS.password)) return "a password field is shown";
  if (await present(page, LOGIN_MARKERS.captcha)) return "a CAPTCHA or anti-bot check is shown";
  if (await present(page, LOGIN_MARKERS.otp)) return "a one-time code is asked";
  if (cfg.authenticated_url && !new RegExp(cfg.authenticated_url).test(bare(url))) {
    return `the url does not match the authenticated page (${cfg.authenticated_url})`;
  }
  return null;
}

// The form inventory, read from the DOM. Attributes and visible text only: no input's
// value, no checked/selected option, nothing from storage.
function inventory() {
  const clean = (s: string | null | undefined, n = 200) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, n);
  const shown = (el: Element) => {
    const r = (el as HTMLElement).getBoundingClientRect();
    const st = getComputedStyle(el as HTMLElement);
    return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  };
  const textOf = (el: Element) => clean((el as HTMLElement).innerText ?? el.textContent);
  const byIds = (ids: string | null) =>
    clean((ids || "").split(/\s+/).map((id) => document.getElementById(id)).filter(Boolean)
      .map((e) => textOf(e as Element)).join(" "));
  const labelOf = (el: Element) => {
    const labels = (el as HTMLInputElement).labels;
    return labels && labels.length ? clean(Array.from(labels).map((l) => textOf(l)).join(" ")) : "";
  };
  const nameOf = (el: Element) => {
    const aria = clean(el.getAttribute("aria-label"));
    if (aria) return aria;
    const by = byIds(el.getAttribute("aria-labelledby"));
    if (by) return by;
    const tag = el.tagName.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (tag === "input" && ["submit", "button", "reset"].includes(type)) {
        return clean(el.getAttribute("value")) || type;
      }
      return labelOf(el) || clean(el.getAttribute("title")) || clean(el.getAttribute("placeholder"));
    }
    return textOf(el) || clean(el.getAttribute("title")) || clean(el.getAttribute("alt"));
  };
  const headings = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6, [role=heading]"));
  const headingOf = (el: Element) => {
    let last = "";
    for (const h of headings) {
      if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) last = textOf(h);
      else break;
    }
    return last;
  };
  const implicitRole = (el: Element) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (tag === "textarea") return "textbox";
    if (tag === "select") return el.hasAttribute("multiple") ? "listbox" : "combobox";
    return ({ checkbox: "checkbox", radio: "radio", range: "slider", number: "spinbutton",
              search: "searchbox", file: "button", submit: "button", button: "button",
              reset: "button", image: "button" } as Record<string, string>)[type] || "textbox";
  };
  const attrs = (el: Element) => ({
    testid: el.getAttribute("data-testid") || el.getAttribute("data-test") || el.getAttribute("data-qa") || null,
    name: el.getAttribute("name"),
    id: el.id || null,
  });
  const forms = Array.from(document.forms);
  const fields = Array.from(document.querySelectorAll("input, textarea, select"))
    .filter((el) => (el.getAttribute("type") || "").toLowerCase() !== "hidden")
    .map((el) => {
      const tag = el.tagName.toLowerCase();
      const num = (a: string) => (el.hasAttribute(a) ? Number(el.getAttribute(a)) : null);
      return {
        tag,
        role: el.getAttribute("role") || implicitRole(el),
        accessible_name: nameOf(el),
        label: labelOf(el),
        placeholder: el.getAttribute("placeholder"),
        type: tag === "input" ? (el.getAttribute("type") || "text").toLowerCase() : tag,
        required: el.hasAttribute("required") || el.getAttribute("aria-required") === "true",
        disabled: el.hasAttribute("disabled"),
        readonly: el.hasAttribute("readonly"),
        maxlength: num("maxlength"),
        minlength: num("minlength"),
        pattern: el.getAttribute("pattern"),
        accept: el.getAttribute("accept"),
        multiple: el.hasAttribute("multiple"),
        options: tag === "select" ? Array.from((el as HTMLSelectElement).options).map((o) => clean(o.text)) : null,
        ...attrs(el),
        heading: headingOf(el),
        form: (el as HTMLInputElement).form ? forms.indexOf((el as HTMLInputElement).form!) : null,
        visible: shown(el),
      };
    });
  const buttons = Array.from(document.querySelectorAll(
    "button, [role=button], input[type=submit], input[type=button], input[type=reset]"))
    .map((el) => ({ accessible_name: nameOf(el), type: el.getAttribute("type"), disabled: el.hasAttribute("disabled") ||
                    el.getAttribute("aria-disabled") === "true", ...attrs(el), heading: headingOf(el),
                    visible: shown(el) }));
  const links = Array.from(document.querySelectorAll("a[href]")).map((el) => {
    let href = "";
    try {
      const u = new URL((el as HTMLAnchorElement).href);
      href = u.origin + u.pathname;
    } catch { /* not a url */ }
    return { accessible_name: nameOf(el), href, visible: shown(el) };
  });
  const statuses: { text: string; source: string }[] = [];
  const seen = new Set<string>();
  const addStatus = (text: string, source: string) => {
    if (text && text.length <= 80 && !seen.has(source + text)) {
      seen.add(source + text);
      statuses.push({ text, source });
    }
  };
  for (const el of Array.from(document.querySelectorAll(
    "[role=status], [data-status], [class*=status i], [class*=badge i], [class*=chip i], [class*=pill i]"))) {
    if (shown(el)) addStatus(textOf(el), "badge");
  }
  for (const table of Array.from(document.querySelectorAll("table"))) {
    const headers = Array.from(table.querySelectorAll("th")).map((th) => textOf(th));
    const col = headers.findIndex((h) => /status|state|статус|состояние/i.test(h));
    if (col < 0) continue;
    for (const row of Array.from(table.querySelectorAll("tr"))) {
      const cell = row.querySelectorAll("td")[col];
      if (cell) addStatus(textOf(cell), `table:${headers[col]}`);
    }
  }
  return {
    title: clean(document.title),
    headings: headings.filter(shown).map((h) => ({ level: Number(h.tagName.slice(1)) || Number(h.getAttribute("aria-level")) || null,
                                                     text: textOf(h) })),
    forms: forms.map((f, i) => ({ index: i, accessible_name: nameOf(f) || null, heading: headingOf(f),
                                  method: (f.getAttribute("method") || "get").toLowerCase() })),
    fields,
    buttons,
    links,
    statuses,
  };
}

// Every current value of a field, held in this process only to mask it in the snapshot.
function fieldValues() {
  const values: string[] = [];
  for (const el of Array.from(document.querySelectorAll("input, textarea, select, [contenteditable]"))) {
    const v = (el as HTMLInputElement).value ?? (el as HTMLElement).innerText;
    if (typeof v === "string" && v.trim()) values.push(v);
  }
  return values;
}

const VALUE_ROLES = /^(\s*- (?:textbox|searchbox|combobox|spinbutton|slider|listbox)\b(?:\s+"(?:[^"\\]|\\.)*")?(?:\s+\[[^\]]*\])*)(:\s*.+)$/;

function maskSnapshot(snapshot: string, values: string[]): string {
  let out = snapshot.split("\n").map((line) => {
    const m = VALUE_ROLES.exec(line);
    if (m) return `${m[1]}: <value>`;
    return line.replace(/^(\s*- \/value:\s*).+$/, "$1<value>")
      .replace(/^(\s*- \/url:\s*)([^?#\s]*)[?#]\S*$/, "$1$2");
  }).join("\n");
  for (const v of values.sort((a, b) => b.length - a.length)) {
    if (v.length >= 3) out = out.split(v).join("<value>");
  }
  return out.replace(EMAIL, "<email>");
}

function scrubEmails<T>(value: T): T {
  return JSON.parse(JSON.stringify(value).replace(EMAIL, "<email>"));
}

const recorded = new Set<string>();
let counter = 0;

async function capture(page: Page, trigger: string) {
  const url = page.url();
  if (!onAllowedOrigin(url)) return;
  if (await notAuthenticated(page)) return; // never a login, CAPTCHA or 2FA page
  let inv, snapshot, values: string[];
  try {
    inv = scrubEmails(await page.evaluate(inventory));
    values = await page.evaluate(fieldValues);
    snapshot = maskSnapshot(await page.locator("body").ariaSnapshot({ timeout: 5000 }), values);
  } catch {
    return; // navigated away mid-read: the next navigation records it
  }
  values = [];
  const where = bare(url);
  const hash = crypto.createHash("sha256").update(JSON.stringify({ where, inv, snapshot })).digest("hex");
  if (recorded.has(hash)) return;
  recorded.add(hash);
  counter += 1;
  const id = String(counter).padStart(3, "0");
  fs.mkdirSync(PAGES, { recursive: true });
  let screenshot: string | null = `pages/${id}.png`;
  try {
    await page.screenshot({
      path: path.join(cfg.out_dir, screenshot),
      fullPage: false,
      mask: [page.locator("input, textarea, select, [contenteditable]"), page.getByText(new RegExp(EMAIL_SOURCE))],
    });
  } catch {
    screenshot = null;
  }
  const record = { id, url: where, trigger, observed_at: now(), dom_hash: `sha256:${hash}`,
                   screenshot, aria_snapshot: snapshot, ...inv };
  fs.writeFileSync(path.join(PAGES, `${id}.json`), JSON.stringify(record, null, 2));
  state.pages_recorded = counter;
  state.url = where;
  writeState();
  console.log(`OBSERVED portal=${cfg.portal} page=${id} url=${where} fields=${inv.fields.length} trigger=${trigger}`);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

test("observe a console", async ({ browser }) => {
  test.setTimeout(cfg.login_timeout_ms + cfg.max_ms + 120_000);
  const context = await browser.newContext(); // fresh: no storage state in, none out
  let disconnected = false;
  browser.on("disconnected", () => { disconnected = true; });
  const navigated = new Set<Page>();
  const lastCapture = new Map<Page, number>();
  const watch = (p: Page) => {
    p.on("framenavigated", (frame) => { if (frame === p.mainFrame()) navigated.add(p); });
  };
  context.on("page", watch);
  const page = await context.newPage();
  try {
    try {
      await page.goto(cfg.console_url, { waitUntil: "domcontentloaded", timeout: 60_000 });
    } catch { /* the person can still navigate the window */ }
    let why = (await notAuthenticated(page)) ?? "the console has not been reached yet";
    transition("WAITING_FOR_HUMAN_LOGIN", bare(page.url()), why, ACTION,
               "the console's authenticated page is detected");
    if (cfg.test_human && cfg.headless) {
      // The test's stand-in for the person (test_publish_observe.py), never set by a user.
      const human = await import(pathToFileURL(cfg.test_human).href);
      void Promise.resolve(human.default(page, context)).catch((e: unknown) => console.log(`test human: ${e}`));
    }
    const loginDeadline = Date.now() + cfg.login_timeout_ms;
    let observeDeadline = 0;
    let authenticated = false;
    let lastUrl = state.url;
    for (;;) {
      const open = context.pages().filter((p) => !p.isClosed());
      if (disconnected || open.length === 0) {
        if (!authenticated) {
          transition("LOGIN_ABANDONED", lastUrl, "the window was closed before the console was reached", null, null);
        } else {
          state.end_reason = "window_closed";
        }
        break;
      }
      if (!authenticated) {
        for (const p of open) {
          const reason = await notAuthenticated(p);
          if (reason === null) {
            authenticated = true;
            state.authenticated_at = now();
            observeDeadline = Date.now() + cfg.max_ms;
            transition("AUTHENTICATED", bare(p.url()), "the console's authenticated page is shown", null, null);
            for (const q of open) navigated.add(q);
            break;
          }
          if (p === open[open.length - 1]) why = reason;
        }
        if (!authenticated) {
          const where = bare(open[open.length - 1].url());
          if (where !== lastUrl || why !== state.reason) {
            lastUrl = where;
            state.url = where;
            state.reason = why;
            writeState();
          }
          if (Date.now() > loginDeadline) {
            transition("LOGIN_TIMEOUT", where, `no authenticated console page within ${Math.round(cfg.login_timeout_ms / 1000)} s`, null, null);
            break;
          }
          await sleep(cfg.poll_ms);
          continue;
        }
      }
      if (Date.now() > observeDeadline) {
        state.end_reason = "max_minutes";
        break;
      }
      for (const p of open) {
        const due = navigated.has(p) ? "navigation"
          : Date.now() - (lastCapture.get(p) ?? 0) >= cfg.stable_ms ? "stable" : null;
        if (!due) continue;
        navigated.delete(p);
        if (due === "navigation") {
          try { await p.waitForLoadState("domcontentloaded", { timeout: 10_000 }); } catch { /* still loading */ }
        }
        lastCapture.set(p, Date.now());
        await capture(p, due);
      }
      await sleep(cfg.poll_ms);
    }
  } finally {
    await context.close().catch(() => undefined); // nothing of the session survives
    if (state.status === "AUTHENTICATED") {
      state.ended_at = now();
      transition("ENDED", state.url, state.end_reason === "max_minutes" ? "the observation time ran out"
                 : "the person closed the window", null, null);
    } else {
      state.ended_at = state.ended_at ?? now();
      writeState();
    }
  }
});
