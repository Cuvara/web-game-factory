// The console executor: a generic INTENT RUNNER over a portal's publication-profile flow
// (core/reference/publication/<id>.yaml `submission.flow`). One Playwright test that reads a
// FLOW file the publish adapter (scripts/wgf_publish/adapters/console.py) wrote - every
// locator ladder, every value, every url already resolved from the profile and the job -
// drives the console phase by phase, and writes a RESULT file the adapter maps to an
// outcome. No model decides anything here; the runner never invents a value.
//
// Phases, in order (a phase with nothing to do is recorded as skipped):
//   session        open the console in a FRESH, EPHEMERAL context (no storage state in or out)
//                  and wait for a PERSON to log in when it is not logged in
//   find_game      the recorded id, the config ids, the idempotency key, the exact title -
//                  in the profile's order - in the console's games list
//   status_gate    the game's own status: a pending review stops the visit (review-pending)
//   create_game    only when find_game matched nothing and the job allows it; then the ids
//                  the portal issues (identity.issued_on_create): one the build does not
//                  carry yet stops the visit before any upload (ids-issued)
//   upload_build   the one package
//   fill_metadata  listing fields, per-locale intents once per locale
//   upload_media   icon, cover, screenshots: the input's `accept` and `multiple` checked
//   human_fields   what a person must do: reported, never acted on
//   save_draft     save, post-condition read back
//   request_review ONLY when the job carries submit_confirmed (a person decided `submit`),
//                  live, every human field done, not already requested: once, profile
//                  locator only, never adaptive
//   verify         the portal's own status text
//
// A submit-confirmation visit (submit_confirmed) uploads nothing: it finds the game, checks
// its status, and requests review once. Irreversible actions never share a visit with the
// upload.
//
// Locators: per intent a ladder, tried in order - role+name > label > placeholder > exact
// text > stable attribute > css > xpath; the first rung that resolves to exactly one visible
// element wins and is recorded. Never coordinates. A ladder that matches nothing or several
// elements, or a failed post-condition, ends the run with a `drift` result naming the intent
// (resolveDrift is the hook the bounded adaptive mode will fill; today it says `stop`).
//
// Login: when the console is not logged in - the profile's session markers, or else a page
// off the allowed origins, a password, CAPTCHA or one-time-code field - the run writes
// WAITING_FOR_HUMAN_LOGIN to its state file and stdout and polls until the authenticated
// console is detected (or login_timeout_ms; or the window is closed). The same wait covers
// a CAPTCHA, second factor or anti-bot check shown mid-flow. While a person drives the
// window, and for the console's own redirect to a login page before the first login, requests
// to other origins (an identity provider) are let through; otherwise every request outside
// allowed_origins is aborted. Nothing types a password or a code, nothing
// answers a challenge, nothing reads or saves cookies or storage, and no screenshot is
// taken on a page that is not the logged-in console.
//
// Every action and every waiting period is one line in actions.jsonl.

import { test, type Browser, type BrowserContext, type Locator, type Page, type Request } from "@playwright/test";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { pathToFileURL } from "node:url";

type Loc = {
  role?: string; name?: string; exact?: boolean; label?: string; placeholder?: string;
  text?: string; testid?: string; css?: string; xpath?: string; index?: number;
};
type Ladder = Loc[];
type Expect = {
  url_matches?: string; value_equals?: string; visible?: Ladder; text_contains?: string;
  status_in?: string[];
};
type FileRef = { path: string; name: string; sha256: string };
type Intent = {
  id: string; phase: string; class: "reversible" | "irreversible" | "human";
  action?: string; target?: Ladder; url?: string; value?: string; value_public?: boolean;
  value_sha256?: string; files?: FileRef[]; locale?: string | null; optional?: boolean;
  multiple?: boolean; expect?: Expect; note?: string;
};
type Candidate = { source: string; id?: string };
type Flow = {
  portal: string; step: string; console_url: string; allowed_origins: string[];
  out_dir: string; actions_log: string; state_file: string; headless: boolean;
  test_human: string | null; login_timeout_ms: number; poll_ms: number;
  mode: "dry-run" | "live"; changes_allowed: boolean; submit_confirmed: boolean;
  allow_create: boolean;
  session: { logged_in?: Ladder; login?: Ladder; captcha?: Ladder; two_factor?: Ladder;
             anti_bot?: Ladder; authenticated_url?: string };
  identity: { list_url?: string; game_url?: string; row?: Ladder; row_title?: Ladder;
              row_id?: { attr?: string; within?: Ladder }; page_id?: Ladder;
              issued_on_create: { key: string; read: Ladder; attr?: string }[];
              candidates: Candidate[]; build_ids: Record<string, string>; title: string | null;
              pending_ids?: string[] };
  status: { read?: Ladder; error?: Ladder; states: string[]; submitted_states: string[];
            pending_states: string[]; live_states: string[]; approved_states: string[];
            rejected_states: string[] };
  intents: Intent[];
  plan: Record<string, unknown>;
  timeouts: { action: number; navigation: number; upload: number };
};

const flow: Flow = JSON.parse(fs.readFileSync(process.env.WGF_PUBLISH_FLOW!, "utf-8"));
const resultPath = process.env.WGF_PUBLISH_RESULT!;
const ACTION_TEXT = "log in in the opened browser window; handle CAPTCHA/2FA yourself";
const RESUME_TEXT = "the console's authenticated page is detected";
const GENERIC = {
  password: "input[type=password]",
  captcha: ["iframe[src*=captcha i]", "iframe[title*=captcha i]",
            "iframe[src*='challenges.cloudflare.com']", ".g-recaptcha", ".h-captcha",
            ".cf-turnstile"].join(", "),
  otp: ["input[autocomplete=one-time-code]", "input[name*=otp i]", "input[name*=totp i]"].join(", "),
};
const PHASES = ["session", "find_game", "status_gate", "create_game", "upload_build",
                "fill_metadata", "upload_media", "human_fields", "save_draft",
                "request_review", "verify"];
// Profile phases the runner folds into its own.
const PHASE_OF: Record<string, string> = { check_session: "session", read_status: "status_gate" };

type HumanField = { id: string; note: string | null; url: string | null; done: boolean };
const result = {
  outcome: "running" as string,
  stop: null as null | Record<string, unknown>,
  phase_reached: null as string | null,
  phases: {} as Record<string, Record<string, unknown>>,
  found_game: null as null | { id: string; title: string | null; status_text: string | null; source: string },
  created: false,
  created_ids: {} as Record<string, string>,
  game_id: null as string | null,
  uploaded: false,
  saved: false,
  request_attempted: false,
  requested: false,
  already_requested: false,
  status_before: null as string | null,
  status_text: null as string | null,
  human_fields: [] as HumanField[],
  absent: [] as string[],
  login_handoffs: [] as Record<string, unknown>[],
  plan: flow.plan || {},
  refused: [] as string[],
  errors: [] as string[],
  actions: 0,
};

class Stop extends Error {}

const now = () => new Date().toISOString();
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const fold = (s: string | null | undefined) => (s ?? "").trim().toLocaleLowerCase();
const sha256 = (data: string | Buffer) => "sha256:" + crypto.createHash("sha256").update(data).digest("hex");

function write() {
  fs.mkdirSync(path.dirname(resultPath), { recursive: true });
  fs.writeFileSync(resultPath + ".tmp", JSON.stringify(result, null, 2));
  fs.renameSync(resultPath + ".tmp", resultPath);
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

function allowed(url: string): boolean {
  try {
    const origin = new URL(url).origin;
    return flow.allowed_origins.some((o) => origin === new URL(o).origin);
  } catch {
    return false;
  }
}

function absolute(url: string): string {
  return new URL(url, flow.console_url).toString();
}

// The state file and the stdout marker the adapter relays as step progress.
function announce(state: string, fields: Record<string, unknown>) {
  const record = { state, portal: flow.portal, step: flow.step, ...fields, at: now() };
  fs.mkdirSync(path.dirname(flow.state_file), { recursive: true });
  fs.writeFileSync(flow.state_file + ".tmp", JSON.stringify(record, null, 2));
  fs.renameSync(flow.state_file + ".tmp", flow.state_file);
  console.log("WGF_PUBLISH_STATE " + JSON.stringify(record));
}

let seq = 0;
function logAction(entry: Record<string, unknown>) {
  seq += 1;
  result.actions = seq;
  const line = { seq, portal: flow.portal, adaptive: false, human_intervention: false,
                 at: now(), ...entry };
  fs.mkdirSync(path.dirname(flow.actions_log), { recursive: true });
  fs.appendFileSync(flow.actions_log, JSON.stringify(line) + "\n");
}

// -- locators ---------------------------------------------------------------------------------

function rungOf(l: Loc): string {
  if (l.role !== undefined) return "role";
  if (l.label !== undefined) return "label";
  if (l.placeholder !== undefined) return "placeholder";
  if (l.text !== undefined) return "text";
  if (l.testid !== undefined) return "attribute";
  if (l.css !== undefined) return "css";
  return "xpath";
}

function build(scope: Page | Locator, l: Loc): Locator {
  let loc: Locator;
  if (l.role !== undefined) {
    loc = scope.getByRole(l.role as Parameters<Page["getByRole"]>[0],
                          l.name !== undefined ? { name: l.name, exact: l.exact ?? true } : {});
  } else if (l.label !== undefined) loc = scope.getByLabel(l.label, { exact: true });
  else if (l.placeholder !== undefined) loc = scope.getByPlaceholder(l.placeholder, { exact: true });
  else if (l.text !== undefined) loc = scope.getByText(l.text, { exact: true });
  else if (l.testid !== undefined) loc = scope.getByTestId(l.testid);
  else if (l.css !== undefined) loc = scope.locator(l.css);
  else loc = scope.locator(`xpath=${l.xpath}`);
  return l.index !== undefined ? loc.nth(l.index) : loc;
}

// The elements a locator resolves to: visible ones, or - for a file input, which consoles
// often hide behind a styled button - attached ones.
async function elements(loc: Locator, visibleOnly: boolean, max = 20): Promise<Locator[]> {
  const out: Locator[] = [];
  let n = 0;
  try {
    n = Math.min(await loc.count(), max);
  } catch {
    return out;
  }
  for (let i = 0; i < n; i++) {
    const one = loc.nth(i);
    try {
      if (!visibleOnly || (await one.isVisible())) out.push(one);
    } catch { /* detached mid-read */ }
  }
  return out;
}

type Resolved = { el: Locator; rung: string; locator: Loc; position: number };

async function resolveOnce(scope: Page | Locator, ladder: Ladder, visibleOnly = true):
    Promise<{ one: Resolved | null; counts: number[] }> {
  const counts: number[] = [];
  for (let i = 0; i < ladder.length; i++) {
    const found = await elements(build(scope, ladder[i]), visibleOnly);
    counts.push(found.length);
    if (found.length === 1) {
      return { one: { el: found[0], rung: rungOf(ladder[i]), locator: ladder[i], position: i }, counts };
    }
  }
  return { one: null, counts };
}

async function resolve(scope: Page | Locator, ladder: Ladder, timeout: number, visibleOnly = true) {
  const deadline = Date.now() + timeout;
  let last = await resolveOnce(scope, ladder, visibleOnly);
  while (!last.one && Date.now() < deadline) {
    await sleep(200);
    last = await resolveOnce(scope, ladder, visibleOnly);
  }
  return last;
}

// Any rung with at least one visible element (markers, not targets: uniqueness not needed).
async function present(scope: Page | Locator, ladder: Ladder | undefined): Promise<boolean> {
  for (const l of ladder || []) {
    if ((await elements(build(scope, l), true, 5)).length > 0) return true;
  }
  return false;
}

async function presentCss(p: Page, css: string): Promise<boolean> {
  return (await elements(p.locator(css), true, 5)).length > 0;
}

async function readText(el: Locator, attr?: string): Promise<string> {
  if (attr) return ((await el.getAttribute(attr)) ?? "").trim();
  const tag = await el.evaluate((e) => e.tagName.toLowerCase());
  if (tag === "input" || tag === "textarea" || tag === "select") return (await el.inputValue()).trim();
  return (await el.innerText()).trim();
}

// The element's role and accessible name, for the action log. Never an input's value.
async function describe(el: Locator): Promise<{ role: string; name: string } | null> {
  try {
    return await el.evaluate((e) => {
      const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, 80);
      const tag = e.tagName.toLowerCase();
      const type = (e.getAttribute("type") || "").toLowerCase();
      const role = e.getAttribute("role") || (tag === "button" || ["submit", "button"].includes(type) ? "button"
        : tag === "a" ? "link" : tag === "textarea" ? "textbox" : tag === "select" ? "combobox"
        : tag === "input" ? (type === "file" ? "file" : type === "checkbox" ? "checkbox" : "textbox") : tag);
      const labels = (e as HTMLInputElement).labels;
      const name = clean(e.getAttribute("aria-label"))
        || (labels && labels.length ? clean(Array.from(labels).map((l) => l.innerText).join(" ")) : "")
        || clean(e.getAttribute("placeholder"))
        || (tag === "input" ? "" : clean((e as HTMLElement).innerText));
      return { role, name };
    });
  } catch {
    return null;
  }
}

// -- the browser ------------------------------------------------------------------------------

let context: BrowserContext;
let page: Page;
let disconnected = false;
let humanDriving = false;
// Until the person has reached the console once, a top-level navigation may leave the allowed
// origins: a console commonly redirects to its identity provider's login page.
let sessionReady = false;

type AuthState = { ok: true } | { ok: false; kind: string; reason: string };

async function authState(p: Page): Promise<AuthState> {
  const url = p.url();
  const s = flow.session || {};
  try {
    if (!allowed(url)) {
      return { ok: false, kind: "login", reason: `the page is outside the console's allowed origins (${bare(url) || "blank"})` };
    }
    if ((await present(p, s.captcha)) || (await presentCss(p, GENERIC.captcha))) {
      return { ok: false, kind: "captcha", reason: "a CAPTCHA is shown" };
    }
    if (await present(p, s.anti_bot)) return { ok: false, kind: "anti-bot", reason: "an anti-bot check is shown" };
    if ((await present(p, s.two_factor)) || (await presentCss(p, GENERIC.otp))) {
      return { ok: false, kind: "two-factor", reason: "a one-time code is asked" };
    }
    if ((await present(p, s.login)) || (await presentCss(p, GENERIC.password))) {
      return { ok: false, kind: "login", reason: "the console shows its login form" };
    }
    if (s.authenticated_url && !new RegExp(s.authenticated_url).test(bare(url))) {
      return { ok: false, kind: "login", reason: `the url does not match the authenticated console (${s.authenticated_url})` };
    }
    if (s.logged_in && !(await present(p, s.logged_in))) {
      return { ok: false, kind: "login", reason: "the console's logged-in marker is not shown" };
    }
  } catch {
    return { ok: false, kind: "login", reason: "the page could not be read" };
  }
  return { ok: true };
}

// Wait for the person. Returns when the authenticated console is detected; ends the run
// (login_timeout / login_abandoned) otherwise. Never acts on the page.
let testHuman: null | ((p: Page, c: BrowserContext, why: Record<string, unknown>) => Promise<void>) = null;

async function waitForHuman(phase: string, why: { kind: string; reason: string }) {
  const handoff: Record<string, unknown> = {
    at: now(), url: bare(page.url()), reason: why.reason, kind: why.kind, phase,
    action: ACTION_TEXT, resume: RESUME_TEXT, resolved_at: null, outcome: null,
  };
  result.login_handoffs.push(handoff);
  write();
  announce("WAITING_FOR_HUMAN_LOGIN", { url: handoff.url, reason: why.reason, kind: why.kind,
                                        phase, action: ACTION_TEXT, resume: RESUME_TEXT });
  logAction({ phase, intent: null, action: "wait-for-human-login", human_intervention: true,
              result: "waiting", reason: why.reason, kind: why.kind, url: handoff.url });
  humanDriving = true;
  if (flow.test_human && flow.headless) {
    // The test's stand-in for the person (scripts/tests), accepted only headless.
    if (!testHuman) testHuman = (await import(pathToFileURL(flow.test_human).href)).default;
    void Promise.resolve(testHuman!(page, context, { phase, kind: why.kind }))
      .catch((e: unknown) => console.log(`test human: ${e}`));
  }
  const deadline = Date.now() + flow.login_timeout_ms;
  let beat = Date.now();
  try {
    for (;;) {
      const open = context.pages().filter((p) => !p.isClosed());
      if (disconnected || open.length === 0) {
        handoff.outcome = "window-closed";
        announce("LOGIN_ABANDONED", { url: handoff.url, reason: "the window was closed before the console was reached", phase });
        logAction({ phase, intent: null, action: "wait-for-human-login", human_intervention: true,
                    result: "window-closed", url: handoff.url });
        return finish("login_abandoned", { phase, code: why.kind, reason: "the window was closed before the console was reached" });
      }
      for (const p of open.slice().reverse()) {
        if ((await authState(p)).ok) {
          page = p;
          handoff.resolved_at = now();
          handoff.outcome = "resolved";
          announce("AUTHENTICATED", { url: bare(p.url()), reason: "the console's authenticated page is shown", phase });
          logAction({ phase, intent: null, action: "wait-for-human-login", human_intervention: true,
                      result: "resolved", url: bare(p.url()) });
          write();
          return;
        }
      }
      if (Date.now() > deadline) {
        handoff.outcome = "timeout";
        const reason = `no authenticated console page within ${Math.round(flow.login_timeout_ms / 1000)} s`;
        announce("LOGIN_TIMEOUT", { url: handoff.url, reason, phase });
        logAction({ phase, intent: null, action: "wait-for-human-login", human_intervention: true,
                    result: "timeout", url: handoff.url });
        return finish("login_timeout", { phase, code: why.kind, reason });
      }
      if (Date.now() - beat >= 15_000) {
        beat = Date.now();
        // Output keeps the step's hung-child watchdog quiet while a person logs in.
        console.log(`WAITING_FOR_HUMAN_LOGIN still waiting portal=${flow.portal} phase=${phase}`);
      }
      await sleep(flow.poll_ms);
    }
  } finally {
    humanDriving = false;
  }
}

async function ensureSession(phase: string) {
  const state = await authState(page);
  if (!state.ok) await waitForHuman(phase, state);
}

// After a navigation, a console may take a moment to show its logged-in marker.
async function settledAuth(timeout: number): Promise<AuthState> {
  const deadline = Date.now() + timeout;
  let state = await authState(page);
  while (!state.ok && Date.now() < deadline) {
    await sleep(250);
    state = await authState(page);
  }
  return state;
}

async function settle() {
  try {
    await page.waitForLoadState("domcontentloaded", { timeout: flow.timeouts.navigation });
  } catch { /* still loading: the post-condition decides */ }
}

async function goto(url: string, phase: string) {
  const target = absolute(url);
  if (!allowed(target)) {
    return finish("error", { phase, code: "profile", reason: `the profile names a url outside the allowed origins (${bare(target)})` });
  }
  await page.goto(target, { waitUntil: "domcontentloaded" });
  const state = await settledAuth(flow.timeouts.action);
  if (!state.ok) await waitForHuman(phase, state);
}

// Before and after each action, on the logged-in console only; inputs of a password type masked.
async function shot(name: string): Promise<{ path: string; sha256: string } | null> {
  if (!(await authState(page)).ok) return null;
  const file = path.join(flow.out_dir, "frames", `${String(seq + 1).padStart(3, "0")}-${name}.png`);
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const buffer = await page.screenshot({ path: file, fullPage: false, mask: [page.locator("input[type=password]")] });
    return { path: file, sha256: sha256(buffer) };
  } catch {
    return null;
  }
}

async function readStatus(timeout = flow.timeouts.action): Promise<string> {
  if (!flow.status.read) return "";
  const r = await resolve(page, flow.status.read, timeout);
  if (!r.one) return "";
  try {
    return await readText(r.one.el);
  } catch {
    return "";
  }
}

async function portalError(): Promise<string | null> {
  if (!flow.status.error || !(await present(page, flow.status.error))) return null;
  const r = await resolveOnce(page, flow.status.error);
  try {
    return r.one ? await readText(r.one.el) : "the console shows an error";
  } catch {
    return "the console shows an error";
  }
}

// -- stopping -----------------------------------------------------------------------------------

function finish(outcome: string, stop: Record<string, unknown> | null): never {
  result.outcome = outcome;
  result.stop = stop;
  write();
  throw new Stop(outcome);
}

function stopVisit(phase: string, code: string, reason: string, extra: Record<string, unknown> = {}): never {
  result.phases[phase] = { outcome: "stopped", code, detail: reason };
  return finish("stopped", { phase, code, reason, ...extra });
}

// The hook the bounded adaptive mode (docs/portal-publishing-architecture.md 2.6) will fill:
// given the drifted intent and a redacted snapshot of the page, propose a resolution under the
// executor's checks. Today nothing adapts: the visit stops, and a person corrects the profile.
export async function resolveDrift(_intent: Intent, _snapshot: unknown): Promise<"stop"> {
  return "stop";
}

async function drift(it: Intent, reason: string, extra: Record<string, unknown> = {}): Promise<never> {
  const resolution = it.class === "reversible" ? await resolveDrift(it, null) : "stop";
  result.phases[it.phase] = { outcome: "drift", intent: it.id, detail: reason };
  return finish("drift", { phase: it.phase, intent: it.id, class: it.class, reason, resolution,
                           code: it.class === "irreversible" ? "drift-irreversible" : "drift", ...extra });
}

// -- intents ------------------------------------------------------------------------------------

type Check = { ok: boolean; checks: string[]; detail: string };

async function checkOnce(e: Expect, el: Locator | null): Promise<Check> {
  const failed: string[] = [];
  if (e.url_matches && !new RegExp(e.url_matches).test(bare(page.url()))) {
    failed.push(`url ${bare(page.url())} does not match ${e.url_matches}`);
  }
  if (e.value_equals !== undefined) {
    let value: string | null = null;
    try {
      value = el ? (await el.inputValue()).replace(/\r\n/g, "\n") : null;
    } catch { value = null; }
    if (value !== e.value_equals.replace(/\r\n/g, "\n")) failed.push("the field does not hold the value");
  }
  if (e.visible && !(await present(page, e.visible))) failed.push("the expected element is not shown");
  if (e.text_contains !== undefined) {
    let body = "";
    try { body = await page.locator("body").innerText(); } catch { body = ""; }
    if (!body.includes(e.text_contains)) failed.push(`the page does not say ${JSON.stringify(e.text_contains)}`);
  }
  if (e.status_in) {
    const status = await readStatus(1000);
    if (!e.status_in.map(fold).includes(fold(status))) failed.push(`status ${JSON.stringify(status)} is not one of ${e.status_in.join(", ")}`);
  }
  return { ok: failed.length === 0, checks: Object.keys(e), detail: failed.join("; ") };
}

async function checkExpect(it: Intent, el: Locator | null, timeout: number): Promise<Check> {
  const e = it.expect;
  if (!e) return { ok: true, checks: [], detail: "" };
  const deadline = Date.now() + timeout;
  let last = await checkOnce(e, el);
  while (!last.ok && Date.now() < deadline) {
    await sleep(250);
    last = await checkOnce(e, el);
  }
  return last;
}

const MIME: Record<string, string> = {
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
  ".gif": "image/gif", ".svg": "image/svg+xml", ".zip": "application/zip", ".mp4": "video/mp4",
  ".webm": "video/webm",
};

function accepts(accept: string, file: string): boolean {
  const ext = path.extname(file).toLowerCase();
  const mime = MIME[ext] || "";
  return accept.split(",").map((a) => a.trim().toLowerCase()).filter(Boolean).some((a) =>
    a === ext || a === mime || (a.endsWith("/*") && mime.startsWith(a.slice(0, -1))));
}

async function runIntent(it: Intent): Promise<string | null> {
  await ensureSession(it.phase);
  const entry: Record<string, unknown> = {
    phase: it.phase, intent: it.id, class: it.class, action: it.action, locale: it.locale ?? null,
    source: "profile", started_at: now(),
  };
  if (it.value_sha256) entry.value_sha256 = it.value_sha256;
  if (it.value_public && it.value !== undefined) entry.value = it.value;
  if (it.files) entry.files = it.files.map((f) => ({ name: f.name, sha256: f.sha256 }));
  const timeout = it.phase === "upload_build" ? flow.timeouts.upload : flow.timeouts.navigation;

  if (it.action === "navigate") {
    const pre = await shot(`${it.id}-pre`);
    await goto(it.url!, it.phase);
    const post = await checkExpect(it, null, timeout);
    entry.url = bare(page.url());
    entry.result = post.ok ? "ok" : "post-condition-failed";
    entry.post_condition = post;
    entry.screenshots = { pre, post: await shot(`${it.id}-post`) };
    entry.ended_at = now();
    logAction(entry);
    if (!post.ok) await drift(it, `post-condition failed: ${post.detail}`);
    return null;
  }

  const visibleOnly = it.action !== "upload";
  let r = await resolve(page, it.target || [], flow.timeouts.action, visibleOnly);
  if (!r.one && !(await authState(page)).ok) {
    await ensureSession(it.phase); // a challenge shown mid-flow: the person answers it
    r = await resolve(page, it.target || [], flow.timeouts.action, visibleOnly);
  }
  if (!r.one) {
    const several = r.counts.some((c) => c > 1);
    if (it.optional && !several) {
      entry.result = "absent";
      entry.ended_at = now();
      logAction(entry);
      result.absent.push(it.locale ? `${it.id}:${it.locale}` : it.id);
      return null;
    }
    entry.result = "drift";
    entry.ladder_counts = r.counts;
    entry.ended_at = now();
    logAction(entry);
    const why = several ? `the locator ladder matches several elements (${r.counts.join(", ")})`
                        : "no rung of the locator ladder matches a visible element";
    return await drift(it, why);
  }
  const el = r.one.el;
  entry.locator = r.one.locator;
  entry.rung = r.one.rung;
  entry.ladder_position = r.one.position;
  entry.element = await describe(el);
  const pre = await shot(`${it.id}-pre`);
  let read: string | null = null;
  if (it.class === "irreversible") result.request_attempted = true;
  try {
    if (it.action === "click") {
      await el.click();
      await settle();
    } else if (it.action === "fill") {
      await el.fill(it.value ?? "");
    } else if (it.action === "select") {
      await el.selectOption(it.value ?? "");
    } else if (it.action === "upload") {
      const files = it.files || [];
      const accept = (await el.getAttribute("accept")) || "";
      const multiple = await el.evaluate((e) => (e as HTMLInputElement).multiple === true);
      const refused = accept ? files.filter((f) => !accepts(accept, f.path)).map((f) => f.name) : [];
      if (!files.length || refused.length || (files.length > 1 && !multiple)) {
        const reason = !files.length ? "no file to upload"
          : refused.length ? `the console accepts ${accept}, not ${refused.join(", ")}`
          : `${files.length} files for an input that takes one`;
        entry.result = "refused";
        entry.reason = reason;
        entry.ended_at = now();
        logAction(entry);
        return stopVisit(it.phase, "invalid-media", `${it.id}: ${reason}`, { intent: it.id });
      }
      await el.setInputFiles(files.map((f) => f.path));
    } else if (it.action === "read") {
      read = await readText(el);
      entry.read = read;
    }
  } catch (e) {
    entry.result = "error";
    entry.reason = e instanceof Error ? e.message.split("\n")[0] : String(e);
    entry.ended_at = now();
    logAction(entry);
    if (it.class === "irreversible") {
      return stopVisit(it.phase, "ambiguous-portal-state",
                       `${it.id} was attempted and failed (${entry.reason}): whether the portal took it is unknown`, { intent: it.id });
    }
    return stopVisit(it.phase, "action-failed", `${it.id}: ${entry.reason}`, { intent: it.id });
  }
  const error = await portalError();
  if (error !== null) {
    entry.result = "portal-error";
    entry.portal_error = error;
    entry.screenshots = { pre, post: await shot(`${it.id}-post`) };
    entry.ended_at = now();
    logAction(entry);
    return stopVisit(it.phase, "portal-error", `${it.id}: the console reports: ${error}`, { intent: it.id });
  }
  let post = await checkExpect(it, it.action === "click" ? null : el, timeout);
  if (!post.ok && !(await authState(page)).ok) {
    await ensureSession(it.phase);
    post = await checkExpect(it, it.action === "click" ? null : el, timeout);
  }
  entry.result = post.ok ? "ok" : "post-condition-failed";
  entry.post_condition = post;
  entry.screenshots = { pre, post: await shot(`${it.id}-post`) };
  entry.ended_at = now();
  logAction(entry);
  if (!post.ok) {
    if (it.class === "irreversible") {
      // Clicked once; what the portal did is not what the profile says it does. Never again.
      return stopVisit(it.phase, "ambiguous-portal-state",
                       `${it.id} was clicked but ${post.detail}: a person reads the portal`, { intent: it.id });
    }
    await drift(it, `post-condition failed: ${post.detail}`);
  }
  return read;
}

function intentsOf(phase: string): Intent[] {
  return flow.intents.filter((it) => (PHASE_OF[it.phase] || it.phase) === phase && it.class !== "human");
}

async function runPhase(phase: string): Promise<(string | null)[]> {
  const out: (string | null)[] = [];
  for (const it of intentsOf(phase)) out.push(await runIntent(it));
  return out;
}

function reached(phase: string, detail: Record<string, unknown> = {}) {
  result.phases[phase] = { outcome: "ok", ...detail };
  result.phase_reached = phase;
  write();
}

function skipped(phase: string, detail: string) {
  result.phases[phase] = { outcome: "skipped", detail };
  write();
}

// -- phases -------------------------------------------------------------------------------------

async function phaseSession() {
  await page.goto(flow.console_url, { waitUntil: "domcontentloaded" }).catch(() => undefined);
  const state = await settledAuth(flow.timeouts.action);
  if (!state.ok) await waitForHuman("session", state);
  sessionReady = true;
  await runPhase("session");
  reached("session", { url: bare(page.url()) });
}

type Row = { id: string | null; title: string | null; text: string; status: string | null };

async function readRows(): Promise<Row[]> {
  const id = flow.identity;
  const deadline = Date.now() + flow.timeouts.action;
  let found: Locator[] = [];
  for (;;) {
    for (const l of id.row || []) {
      found = await elements(build(page, l), true, 500);
      if (found.length) break;
    }
    if (found.length || Date.now() > deadline) break;
    await sleep(250);
  }
  const states = new Set(flow.status.states.map(fold));
  const rows: Row[] = [];
  for (const row of found) {
    let rowId: string | null = null;
    if (id.row_id?.attr) rowId = await row.getAttribute(id.row_id.attr);
    else if (id.row_id?.within) {
      const r = await resolveOnce(row, id.row_id.within);
      rowId = r.one ? await readText(r.one.el) : null;
    }
    let title: string | null = null;
    for (const l of id.row_title || []) {
      const els = await elements(build(row, l), true);
      if (els.length) { title = (await els[0].innerText()).trim(); break; }
    }
    const text = (await row.innerText()).trim();
    const cells = await row.locator("*").evaluateAll((all) =>
      all.filter((e) => e.children.length === 0).map((e) => (e as HTMLElement).innerText.trim()));
    const status = cells.find((c) => states.has(fold(c))) ?? null;
    rows.push({ id: rowId, title, text, status });
  }
  return rows;
}

async function phaseFindGame() {
  await runPhase("find_game");
  const id = flow.identity;
  const recorded = id.candidates.filter((c) => c.source !== "title" && c.source !== "idempotency-key" && c.id);
  if (!id.list_url || !id.row) {
    if (recorded.length && id.game_url) {
      const c = recorded[0];
      result.found_game = { id: c.id!, title: null, status_text: null, source: c.source };
      logAction({ phase: "find_game", intent: null, action: "find", result: "recorded", source: c.source });
      return reached("find_game", { found: true, source: c.source });
    }
    return stopVisit("find_game", "ambiguous-portal-state",
                     "the publication profile names no games list (identity.list_url and identity.row): whether the game already exists cannot be read, so nothing is created");
  }
  await goto(id.list_url, "find_game");
  const rows = await readRows();
  let match: { row: Row; source: string } | null = null;
  for (const c of id.candidates) {
    let row: Row | undefined;
    if (c.source === "title") row = rows.find((r) => r.title !== null && fold(r.title) === fold(c.id));
    else if (c.source === "idempotency-key") row = rows.find((r) => r.id === c.id || (!!c.id && r.text.includes(c.id)));
    else row = rows.find((r) => r.id !== null && r.id === c.id);
    if (row) { match = { row, source: c.source }; break; }
  }
  logAction({ phase: "find_game", intent: null, action: "find", url: bare(page.url()), rows: rows.length,
              result: match ? "matched" : "none", source: match?.source ?? null,
              screenshots: { post: await shot("find-game") } });
  if (match) {
    result.found_game = { id: match.row.id ?? "", title: match.row.title, status_text: match.row.status, source: match.source };
    if (match.source === "title") {
      return stopVisit("find_game", "duplicate-candidate",
                       `the console lists a game titled ${JSON.stringify(match.row.title)} (${match.row.id ?? "no id"}) this title never recorded: a person links it or abandons`);
    }
    return reached("find_game", { found: true, source: match.source, id: match.row.id });
  }
  if (recorded.length) {
    return stopVisit("find_game", "ambiguous-portal-state",
                     `the recorded game ${recorded.map((c) => c.id).join(", ")} is not in the console's list`);
  }
  reached("find_game", { found: false, rows: rows.length });
}

const inList = (s: string | null, list: string[]) => s !== null && list.map(fold).includes(fold(s));

async function phaseStatusGate() {
  const game = result.found_game;
  if (!game) return skipped("status_gate", "no game found: nothing to gate");
  if (flow.identity.game_url && game.id) {
    await goto(flow.identity.game_url.replace("{id}", encodeURIComponent(game.id)), "status_gate");
  }
  await runPhase("status_gate");
  const status = flow.status.read ? await readStatus() : (game.status_text ?? "");
  result.status_before = status;
  logAction({ phase: "status_gate", intent: null, action: "read", read: status, result: "ok",
              url: bare(page.url()) });
  const requested = inList(status, flow.status.pending_states) || inList(status, flow.status.submitted_states)
    || inList(status, flow.status.live_states) || inList(status, flow.status.approved_states);
  if (flow.submit_confirmed) {
    if (requested) result.already_requested = true;
    return reached("status_gate", { status });
  }
  if (inList(status, flow.status.pending_states)) {
    return stopVisit("status_gate", "review-pending",
                     `the game is ${JSON.stringify(status)}: nothing is uploaded over a pending review, and nothing cancels it`);
  }
  reached("status_gate", { status });
}

async function readPageId(): Promise<string | null> {
  if (!flow.identity.page_id) return null;
  const r = await resolve(page, flow.identity.page_id, flow.timeouts.action);
  return r.one ? await readText(r.one.el) : null;
}

async function phaseCreateGame() {
  if (result.found_game) return skipped("create_game", "the game exists");
  if (flow.submit_confirmed) {
    return stopVisit("create_game", "ambiguous-portal-state",
                     "a submit-confirmation visit found no game to request review for");
  }
  if (!flow.allow_create) {
    return stopVisit("create_game", "ambiguous-portal-state", "no game was found and this visit may not create one");
  }
  if (!flow.changes_allowed) {
    return stopVisit("create_game", "dry-run", "dry run: no game was found; the visit would create one");
  }
  if (!intentsOf("create_game").length) {
    return stopVisit("create_game", "manual-create", "the profile has no create_game intents: a person creates the game");
  }
  await runPhase("create_game");
  result.created = true;
  for (const issued of flow.identity.issued_on_create || []) {
    const r = await resolve(page, issued.read, flow.timeouts.action);
    const value = r.one ? await readText(r.one.el, issued.attr) : "";
    logAction({ phase: "create_game", intent: null, action: "read", issued: issued.key,
                result: value ? "ok" : "unreadable", locator: r.one?.locator ?? null, rung: r.one?.rung ?? null });
    if (!value) {
      return stopVisit("create_game", "ambiguous-portal-state",
                       `the game was created but the ${issued.key} the portal issued could not be read: a person records it`);
    }
    result.created_ids[issued.key] = value;
  }
  result.game_id = result.created_ids.external_game_id || (await readPageId());
  write();
  const missing = Object.keys(result.created_ids).filter((k) => flow.identity.build_ids[k] !== result.created_ids[k]);
  if (missing.length) {
    return stopVisit("create_game", "ids-issued",
                     `the portal issued ${missing.join(", ")} on create, which the build does not carry yet: rebuild with them before anything is uploaded`);
  }
  reached("create_game", { created: true, game_id: result.game_id });
}

async function phaseUpload() {
  if (flow.submit_confirmed) return skipped("upload_build", "a submit-confirmation visit uploads nothing");
  if (!flow.changes_allowed) {
    return stopVisit("upload_build", "dry-run", "dry run: the visit stops before the upload");
  }
  const pending = flow.identity.pending_ids || [];
  if (pending.length && !result.created) {
    // A game found here whose issued ids nobody recorded: the build cannot carry them yet.
    return stopVisit("upload_build", "ambiguous-portal-state",
                     `the game was found but the ${pending.join(", ")} the portal issued are not recorded: a person records them, the build is made again`);
  }
  if (!intentsOf("upload_build").length) {
    return stopVisit("upload_build", "manual-upload", "the profile has no upload_build intents: a person uploads the build");
  }
  await runPhase("upload_build");
  result.uploaded = true;
  if (!result.game_id) result.game_id = (await readPageId()) || result.found_game?.id || null;
  reached("upload_build", { game_id: result.game_id });
}

async function phaseRun(phase: string) {
  if (flow.submit_confirmed) return skipped(phase, "a submit-confirmation visit changes nothing on the draft");
  const intents = intentsOf(phase);
  if (!intents.length) return skipped(phase, "the profile has no intent for it");
  await runPhase(phase);
  if (phase === "save_draft") result.saved = true;
  reached(phase, { intents: intents.length });
}

async function phaseHumanFields() {
  for (const it of flow.intents.filter((x) => x.class === "human")) {
    const done = it.expect ? (await checkOnce(it.expect, null)).ok : false;
    result.human_fields.push({ id: it.id, note: it.note ?? null, url: it.url ? bare(absolute(it.url)) : null, done });
  }
  const pending = result.human_fields.filter((h) => !h.done).map((h) => h.id);
  logAction({ phase: "human_fields", intent: null, action: "report", result: pending.length ? "pending" : "done",
              pending });
  reached("human_fields", { pending });
}

async function phaseRequestReview() {
  if (!flow.submit_confirmed) return skipped("request_review", "not confirmed: a person decides `submit` after the upload");
  if (flow.mode !== "live") return skipped("request_review", "dry run");
  if (result.human_fields.some((h) => !h.done)) return skipped("request_review", "a person has fields to complete first");
  if (result.already_requested) return skipped("request_review", `already requested (status ${JSON.stringify(result.status_before)})`);
  if (!intentsOf("request_review").length) {
    return stopVisit("request_review", "manual-request", "the profile has no request_review intent: a person requests review");
  }
  await runPhase("request_review");
  result.requested = true;
  reached("request_review", {});
}

async function phaseVerify() {
  const reads = (await runPhase("verify")).filter((x): x is string => x !== null);
  const status = reads.length ? reads[reads.length - 1] : await readStatus();
  result.status_text = status;
  reached("verify", { status_text: status });
}

// -- the test -------------------------------------------------------------------------------------

function loginRedirect(request: Request): boolean {
  if (sessionReady || !page) return false;
  try {
    return request.isNavigationRequest() && request.frame() === page.mainFrame();
  } catch {
    return false; // a service worker's request has no frame
  }
}

test("publication console flow", async ({ browser }: { browser: Browser }) => {
  test.setTimeout(flow.login_timeout_ms * 4 + flow.timeouts.upload + flow.timeouts.navigation * 40);
  context = await browser.newContext(); // fresh: no storage state in, none out
  browser.on("disconnected", () => { disconnected = true; });
  await context.route("**/*", (route) => {
    const url = route.request().url();
    if (humanDriving || loginRedirect(route.request()) || allowed(url) || /^(data|about|blob):/.test(url)) return route.continue();
    result.refused.push(bare(url));
    return route.abort("blockedbyclient");
  });
  page = await context.newPage();
  page.setDefaultTimeout(flow.timeouts.action);
  page.setDefaultNavigationTimeout(flow.timeouts.navigation);
  fs.mkdirSync(flow.out_dir, { recursive: true });
  try {
    await phaseSession();
    await phaseFindGame();
    await phaseStatusGate();
    await phaseCreateGame();
    await phaseUpload();
    await phaseRun("fill_metadata");
    await phaseRun("upload_media");
    await phaseHumanFields();
    await phaseRun("save_draft");
    await phaseRequestReview();
    await phaseVerify();
    result.outcome = "completed";
    write();
  } catch (e) {
    if (!(e instanceof Stop)) {
      const message = e instanceof Error ? e.message.split("\n")[0] : String(e);
      result.errors.push(message);
      result.outcome = "error";
      result.stop = { phase: PHASES.find((p) => !(p in result.phases)) ?? null, code: "error", reason: message };
      write();
    }
  } finally {
    await context.close().catch(() => undefined); // nothing of the session survives
    announce("ENDED", { outcome: result.outcome, phase: result.phase_reached });
    write();
  }
});
