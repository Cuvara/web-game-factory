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
// elements, or a failed post-condition, ends the run with a `drift` result naming the intent.
//
// Bounded adaptive mode (docs/portal-publishing-architecture.md 2.6), only when the flow
// says `adaptive.enabled` (the profile allows it AND the installation enabled it AND a
// resolver agent is configured), and only for a REVERSIBLE intent outside session,
// find_game, status_gate and request_review: the run pauses, takes a redacted accessibility
// snapshot of the logged-in console page (roles, names, labels, states; input values
// masked; never on a login, CAPTCHA, second-factor or anti-bot page), writes it with the
// intent to drift-request.json and waits for drift-response.json - the browser process
// never runs a model. Every proposal (resolve | dismiss | navigate | stop) is checked HERE
// before anything is done with it: exactly one visible enabled element; an allowed origin
// and the intent's page; a role that fits the intent's own action; an accessible name in the
// intent's `names`; nothing in the deny vocabulary; no value from the resolver; the budget.
// A refused proposal stops the visit like any drift, the proposal and every check recorded.
// After acting, the post-condition is checked exactly as for a profile locator, and a
// failure is never adapted again. An irreversible intent never adapts: the resolver's
// proposal is asked for only as a suggestion a person reads (drift-irreversible).
// What worked is written to drift.json as a proposed profile change; nothing edits a profile.
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
  multiple?: boolean; expect?: Expect; note?: string; names?: string[]; page?: string;
};
type Adaptive = {
  enabled: boolean; unavailable: string | null; request_path: string; response_path: string;
  drift_path: string; response_timeout_ms: number; max_per_intent: number;
  max_per_visit: number; dismissable: string[]; deny: string[];
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
              candidates: Candidate[]; build_ids: Record<string, string>; title: string | null };
  status: { read?: Ladder; error?: Ladder; states: string[]; submitted_states: string[];
            pending_states: string[]; live_states: string[]; approved_states: string[];
            rejected_states: string[] };
  intents: Intent[];
  plan: Record<string, unknown>;
  timeouts: { action: number; navigation: number; upload: number };
  adaptive?: Adaptive;
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
  adaptive: { enabled: false, used: 0, acted: 0, refused: 0, suggestions: 0 },
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

// A drift stops the visit. On an irreversible intent, with the adaptive mode on, the resolver
// is asked for a SUGGESTION a person reads before correcting the profile - never acted on.
async function drift(it: Intent, reason: string, extra: Record<string, unknown> = {}): Promise<never> {
  const suggestion = it.class === "irreversible" && ADAPT.enabled ? await suggest(it, reason) : null;
  result.phases[it.phase] = { outcome: "drift", intent: it.id, detail: reason };
  return finish("drift", { phase: it.phase, intent: it.id, class: it.class, reason, resolution: "stop",
                           code: it.class === "irreversible" ? "drift-irreversible" : "drift",
                           ...(suggestion ? { suggestion } : {}), ...extra });
}

// -- the bounded adaptive mode ------------------------------------------------------------------

const ADAPT: Adaptive = flow.adaptive ?? {
  enabled: false, unavailable: "the flow carries no adaptive block", request_path: "", response_path: "",
  drift_path: "", response_timeout_ms: 0, max_per_intent: 0, max_per_visit: 0, dismissable: [], deny: [],
};
result.adaptive.enabled = ADAPT.enabled;
// Phases that choose the session, the game or the review request: never adaptive.
const NEVER_ADAPTIVE = new Set(["session", "check_session", "find_game", "status_gate", "read_status",
                                "request_review"]);
// The roles an element may have for each action an adaptive resolution may take.
const ROLES_FOR: Record<string, string[]> = {
  fill: ["textbox"], select: ["combobox", "listbox"], upload: ["file"], click: ["button", "link"],
};
const GAME_PHASES = new Set(["upload_build", "fill_metadata", "upload_media", "save_draft"]);
const LOC_KEYS = ["role", "name", "exact", "label", "placeholder", "text", "testid", "css", "xpath"];
const LOC_PRIMARY = ["role", "label", "placeholder", "text", "testid", "css", "xpath"];
const adaptiveCount: Record<string, number> = {};
const driftEntries: Record<string, unknown>[] = [];
let driftSeq = 0;

const norm = (s: string | null | undefined) => fold(s).replace(/\s+/g, " ").replace(/[\s:*]+$/, "");
const intentKey = (it: Intent) => (it.locale ? `${it.id}:${it.locale}` : it.id);

// The first deny word that starts a word of `text`, case-folded (wgflib.publication's rule).
function denyHit(text: string | null | undefined): string | null {
  const t = fold(text);
  if (!t) return null;
  for (const w of ADAPT.deny) {
    const word = fold(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    if (word && new RegExp(`(?<![\\p{L}\\p{N}_])${word}`, "u").test(t)) return w;
  }
  return null;
}

function writeDrift() {
  if (!ADAPT.drift_path) return;
  fs.mkdirSync(path.dirname(ADAPT.drift_path), { recursive: true });
  const doc = { portal: flow.portal, step: flow.step, at: now(), entries: driftEntries };
  fs.writeFileSync(ADAPT.drift_path + ".tmp", JSON.stringify(doc, null, 2));
  fs.renameSync(ADAPT.drift_path + ".tmp", ADAPT.drift_path);
}

function adaptiveGate(it: Intent): string | null {
  if (!ADAPT.enabled) return ADAPT.unavailable || "the adaptive mode is off";
  if (it.class !== "reversible") return `${it.class} intents never adapt`;
  if (NEVER_ADAPTIVE.has(it.phase)) return `the ${it.phase} phase never adapts (it chooses the session, the game or the review request)`;
  if (!it.action || !(it.action in ROLES_FOR || it.action === "navigate")) return `a ${it.action ?? "missing"} action is never resolved adaptively`;
  if (it.action !== "navigate" && !(it.names && it.names.length)) return "the intent has no accepted names (`names`) to check a proposal against";
  if (result.adaptive.used >= ADAPT.max_per_visit) return `the visit's adaptive budget is spent (${ADAPT.max_per_visit})`;
  if ((adaptiveCount[intentKey(it)] ?? 0) >= ADAPT.max_per_intent) return `the intent's adaptive budget is spent (${ADAPT.max_per_intent})`;
  return null;
}

function pathOf(url: string): string {
  try { return new URL(url).pathname; } catch { return ""; }
}

type Snap = { url: string; path: string; nodes: Record<string, unknown>[]; sha256: string };

// Roles, names, labels and states of what the page shows. Input values are `<value>` or "";
// hidden and password inputs are left out; no cookie, header or network traffic is read.
// Never on a page that is not the logged-in console on an allowed origin.
async function snapshotPage(): Promise<Snap | null> {
  if (!allowed(page.url()) || !(await authState(page)).ok) return null;
  let nodes: Record<string, unknown>[];
  try {
    nodes = await page.evaluate(() => {
      const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, 80);
      const out: Record<string, unknown>[] = [];
      const sel = "a, button, input, textarea, select, label, h1, h2, h3, [role], dialog, [aria-label], [data-testid]";
      for (const e of Array.from(document.querySelectorAll(sel))) {
        if (out.length >= 300) break;
        const el = e as HTMLElement;
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute("type") || "").toLowerCase();
        if (type === "hidden" || type === "password") continue;
        const style = getComputedStyle(el);
        const box = el.getBoundingClientRect();
        const visible = box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
        if (!visible && !(tag === "input" && type === "file")) continue;
        const control = tag === "input" || tag === "textarea" || tag === "select";
        const buttonInput = tag === "input" && ["submit", "button", "reset"].includes(type);
        const role = el.getAttribute("role") || (tag === "button" || buttonInput ? "button"
          : tag === "a" ? "link" : tag === "textarea" ? "textbox"
          : tag === "select" ? ((el as HTMLSelectElement).multiple ? "listbox" : "combobox")
          : tag === "input" ? (type === "file" ? "file" : type === "checkbox" ? "checkbox" : type === "radio" ? "radio" : "textbox")
          : tag);
        const node: Record<string, unknown> = { role, tag };
        const aria = clean(el.getAttribute("aria-label"));
        if (aria) node.name = aria;
        const labels = (el as HTMLInputElement).labels;
        if (labels && labels.length) node.labels = Array.from(labels).map((l) => clean(l.innerText)).filter(Boolean);
        const placeholder = clean(el.getAttribute("placeholder"));
        if (placeholder) node.placeholder = placeholder;
        if (!control) node.text = clean(el.innerText);
        if (buttonInput) node.text = clean((el as HTMLInputElement).value);
        if (type) node.type = type;
        for (const [key, attr] of [["testid", "data-testid"], ["name_attr", "name"], ["id", "id"]]) {
          const v = clean(el.getAttribute(attr));
          if (v) node[key] = v;
        }
        if (control && !buttonInput) node.value = (el as HTMLInputElement).value ? "<value>" : "";
        if (type === "checkbox" || type === "radio") node.checked = (el as HTMLInputElement).checked;
        if ((el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true") node.disabled = true;
        if (!visible) node.visible = false;
        out.push(node);
      }
      return out;
    });
  } catch {
    return null;
  }
  const url = bare(page.url());
  return { url, path: pathOf(page.url()), nodes, sha256: sha256(JSON.stringify({ url, nodes })) };
}

function postConditionOf(it: Intent): Record<string, unknown> | null {
  if (!it.expect) return null;
  const e: Record<string, unknown> = { ...it.expect };
  if (e.value_equals !== undefined) e.value_equals = "<the intent's value>";
  return e;
}

// One request, one answer, through two files: the browser process never runs a model.
async function askResolver(it: Intent, why: string, snap: Snap, suggestionOnly: boolean): Promise<Record<string, unknown>> {
  driftSeq += 1;
  const seq = driftSeq;
  const request = {
    seq, portal: flow.portal, at: now(), suggestion_only: suggestionOnly,
    intent: { id: it.id, phase: it.phase, class: it.class, action: it.action ?? null, locale: it.locale ?? null,
              expected_roles: ROLES_FOR[it.action ?? ""] ?? [], names: it.names ?? [],
              failed_ladder: it.target ?? [], post_condition: postConditionOf(it), page: it.page ?? null },
    why, page: { url: snap.url, path: snap.path }, snapshot: snap.nodes, snapshot_sha256: snap.sha256,
    dismissable: ADAPT.dismissable,
    allowed: suggestionOnly ? ["resolve", "stop"]
      : it.action === "navigate" ? ["dismiss", "navigate", "stop"] : ["resolve", "dismiss", "navigate", "stop"],
    budget: { intent: ADAPT.max_per_intent - (adaptiveCount[intentKey(it)] ?? 0),
              visit: ADAPT.max_per_visit - result.adaptive.used },
  };
  fs.rmSync(ADAPT.response_path, { force: true });
  fs.mkdirSync(path.dirname(ADAPT.request_path), { recursive: true });
  fs.writeFileSync(ADAPT.request_path + ".tmp", JSON.stringify(request, null, 2));
  fs.renameSync(ADAPT.request_path + ".tmp", ADAPT.request_path);
  console.log(`WGF_PUBLISH_DRIFT_REQUEST seq=${seq} intent=${it.id}`);
  const deadline = Date.now() + ADAPT.response_timeout_ms;
  let beat = Date.now();
  for (;;) {
    if (fs.existsSync(ADAPT.response_path)) {
      try {
        const answer = JSON.parse(fs.readFileSync(ADAPT.response_path, "utf-8"));
        if (answer && answer.seq === seq) {
          const p = answer.proposal;
          if (p && typeof p === "object" && !Array.isArray(p) && typeof p.kind === "string") return p;
          return { kind: "stop", reason: "malformed resolver response" };
        }
      } catch { /* written as we read: read again */ }
    }
    if (Date.now() > deadline) {
      return { kind: "stop", reason: `no resolver answer within ${Math.round(ADAPT.response_timeout_ms / 1000)} s` };
    }
    if (Date.now() - beat >= 15_000) {
      beat = Date.now();
      console.log(`WGF_PUBLISH_DRIFT_REQUEST still waiting seq=${seq} intent=${it.id}`);
    }
    await sleep(200);
  }
}

type Info = { role: string; type: string; names: string[]; text: string; disabled: boolean };

// The element's role, every name it goes by (aria-label, labels, placeholder, title, text),
// and whether it is disabled. Never an input's value.
async function inspect(el: Locator): Promise<Info | null> {
  try {
    const info = await el.evaluate((e) => {
      const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim().slice(0, 120);
      const tag = e.tagName.toLowerCase();
      const type = (e.getAttribute("type") || "").toLowerCase();
      const control = tag === "input" || tag === "textarea" || tag === "select";
      const buttonInput = tag === "input" && ["submit", "button", "reset"].includes(type);
      const role = e.getAttribute("role") || (tag === "button" || buttonInput ? "button"
        : tag === "a" ? "link" : tag === "textarea" ? "textbox"
        : tag === "select" ? ((e as HTMLSelectElement).multiple ? "listbox" : "combobox")
        : tag === "input" ? (type === "file" ? "file" : type === "checkbox" ? "checkbox" : type === "radio" ? "radio"
                             : type === "password" ? "password" : type === "hidden" ? "hidden" : "textbox")
        : tag);
      const names: string[] = [clean(e.getAttribute("aria-label"))];
      for (const id of (e.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean)) {
        names.push(clean(document.getElementById(id)?.textContent));
      }
      const labels = (e as HTMLInputElement).labels;
      if (labels) for (const l of Array.from(labels)) names.push(clean(l.innerText));
      names.push(clean(e.getAttribute("placeholder")), clean(e.getAttribute("title")));
      const text = control ? (buttonInput ? clean((e as HTMLInputElement).value) : "") : clean((e as HTMLElement).innerText);
      names.push(text);
      const disabled = (e as HTMLButtonElement).disabled === true || e.getAttribute("aria-disabled") === "true";
      return { role, type, names: names.filter(Boolean), text, disabled };
    });
    if (!info.disabled && !(await el.isEnabled())) info.disabled = true;
    return info;
  } catch {
    return null;
  }
}

function locatorProblem(raw: unknown): string | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return "the locator is not an object";
  const loc = raw as Record<string, unknown>;
  const unknown = Object.keys(loc).filter((k) => !LOC_KEYS.includes(k));
  if (unknown.length) return `the locator carries ${unknown.join(", ")} (never an index, coordinates or a script)`;
  const primary = LOC_PRIMARY.filter((k) => k in loc);
  if (primary.length !== 1) return "the locator names exactly one rung";
  if (("name" in loc || "exact" in loc) && primary[0] !== "role") return "`name` and `exact` go with `role` only";
  for (const [k, v] of Object.entries(loc)) {
    if (k === "exact" ? typeof v !== "boolean" : typeof v !== "string" || !v.trim()) return `locator ${k} is malformed`;
  }
  return null;
}

// The page the intent acts on: the profile's `page` pattern; else, on a game's own phases,
// that game's page; else the origin check alone.
function expectedPage(it: Intent): { ok: boolean; detail: string } {
  const here = pathOf(page.url());
  if (it.page) {
    let re: RegExp;
    try { re = new RegExp(it.page); } catch { return { ok: false, detail: `the intent's page pattern ${it.page} does not compile` }; }
    return { ok: re.test(here), detail: `${here} against ${it.page}` };
  }
  const gameId = result.game_id || result.found_game?.id;
  if (GAME_PHASES.has(it.phase) && flow.identity.game_url && gameId) {
    const want = pathOf(absolute(flow.identity.game_url.replace("{id}", encodeURIComponent(gameId))));
    return { ok: here === want || here.startsWith(want + "/"), detail: `${here} against the game's page ${want}` };
  }
  return { ok: true, detail: `${here}: no page pattern for ${it.phase}; the origin check holds` };
}

type CheckRow = { check: string; ok: boolean; detail?: string };
type Verdict = { ok: boolean; checks: CheckRow[]; el: Locator | null; element: Record<string, unknown> | null; url: string | null };

// Every check the design names, run on the live page by the executor itself; each recorded.
async function validateProposal(it: Intent, p: Record<string, unknown>): Promise<Verdict> {
  const checks: CheckRow[] = [];
  const add = (check: string, ok: boolean, detail?: string) => {
    checks.push(detail !== undefined ? { check, ok, detail } : { check, ok });
    return ok;
  };
  const verdict = (el: Locator | null = null, element: Record<string, unknown> | null = null, url: string | null = null): Verdict =>
    ({ ok: checks.every((c) => c.ok), checks, el, element, url });
  const kind = String(p.kind);
  const kinds = it.action === "navigate" ? ["dismiss", "navigate"] : ["resolve", "dismiss", "navigate"];
  add("kind", kinds.includes(kind), `${kind} for a ${it.action} intent`);
  add("no-value", !("value" in p), "value" in p ? "the resolver supplied a value: a value only ever comes from the job" : undefined);
  add("same-action", p.action === undefined || p.action === it.action,
      p.action === undefined ? undefined : `the intent's action is ${it.action}, the proposal's ${String(p.action)}`);
  add("origin", allowed(page.url()), bare(page.url()) || "blank");
  const pg = expectedPage(it);
  add("page", pg.ok, pg.detail);
  if (kind === "navigate") {
    const raw = typeof p.path === "string" ? p.path : "";
    let url = "";
    if (/^\/(?!\/)/.test(raw) && !/[\\\s]/.test(raw)) {
      try { url = new URL(raw, page.url()).toString(); } catch { url = ""; }
    }
    add("navigate-path", url !== "" && allowed(url), url ? bare(url) : `${JSON.stringify(raw)} is not a path on this console`);
    if (it.page && url) {
      let ok = false;
      try { ok = new RegExp(it.page).test(pathOf(url)); } catch { ok = false; }
      add("navigate-page", ok, `${pathOf(url)} against ${it.page}`);
    }
    return verdict(null, null, url || null);
  }
  if (!["resolve", "dismiss"].includes(kind)) return verdict();
  const shape = locatorProblem(p.locator);
  if (!add("locator", shape === null, shape ?? undefined)) return verdict();
  const loc = p.locator as Loc;
  const locTexts = Object.entries(loc).filter(([k]) => k !== "exact" && k !== "role").map(([, v]) => String(v));
  const found = await elements(build(page, loc), !(kind === "resolve" && it.action === "upload"));
  if (!add("unique", found.length === 1, `${found.length} element(s)`)) {
    const hit = locTexts.map(denyHit).find((h) => h);
    add("deny", !hit, hit ? `the locator names ${JSON.stringify(hit)} (deny vocabulary)` : undefined);
    return verdict();
  }
  const el = found[0];
  const info = await inspect(el);
  if (!add("element", info !== null, info ? undefined : "the element could not be read")) return verdict();
  add("enabled", !info!.disabled, info!.disabled ? "the element is disabled" : undefined);
  if (kind === "resolve") {
    const roles = ROLES_FOR[it.action ?? ""] ?? [];
    add("role", roles.includes(info!.role), `${info!.role} for ${it.action} (needs ${roles.join(" or ") || "nothing adaptive"})`);
    const vocab = (it.names ?? []).map(norm);
    const named = info!.names.find((n) => vocab.includes(norm(n)));
    add("names", named !== undefined, named !== undefined ? JSON.stringify(named)
        : `none of ${JSON.stringify(info!.names)} is one of ${JSON.stringify(it.names ?? [])}`);
  } else {
    add("role", ["button", "link"].includes(info!.role), `${info!.role} to dismiss (needs button or link)`);
    const vocab = ADAPT.dismissable.map(norm);
    const named = info!.names.find((n) => vocab.includes(norm(n)));
    add("dismissable", named !== undefined, named !== undefined ? JSON.stringify(named)
        : `none of ${JSON.stringify(info!.names)} is dismissable (${ADAPT.dismissable.join(", ")})`);
  }
  const hit = [...info!.names, info!.text, ...locTexts].map(denyHit).find((h) => h);
  add("deny", !hit, hit ? `matches the deny vocabulary (${hit})` : undefined);
  return verdict(el, { role: info!.role, name: info!.names[0] ?? "" });
}

function ladderWhy(counts: number[]): string {
  return counts.some((c) => c > 1) ? `the locator ladder matches several elements (${counts.join(", ")})`
                                    : "no rung of the locator ladder matches a visible element";
}

type Adapted = Resolved & { adaptive?: Record<string, unknown> };

// Ask, check, and either hand back an element for the SAME intent (resolve), or dismiss one
// overlay / navigate within the console and try the profile's own ladder again. Ends the
// visit (drift) on a stop, a refusal, or a spent budget. Returns "navigated" for a navigate
// intent whose page was reached adaptively.
async function adapt(it: Intent, why: string, counts: number[] | null): Promise<Adapted | "navigated"> {
  let reason = why;
  for (;;) {
    const gate = adaptiveGate(it);
    if (gate) return drift(it, reason, { adaptive: { used: false, reason: gate } });
    const snap = await snapshotPage();
    if (!snap) {
      return drift(it, reason, { adaptive: { used: false, reason: "no snapshot: the page is not the logged-in console on an allowed origin" } });
    }
    adaptiveCount[intentKey(it)] = (adaptiveCount[intentKey(it)] ?? 0) + 1;
    result.adaptive.used += 1;
    const proposal = await askResolver(it, reason, snap, false);
    const record: Record<string, unknown> = {
      intent: it.id, locale: it.locale ?? null, phase: it.phase, class: it.class, action: it.action,
      failed_ladder: it.target ?? [], ladder_counts: counts, why: reason, url: snap.url,
      snapshot_sha256: snap.sha256, proposal, checks: [], outcome: null, worked: null, at: now(),
    };
    driftEntries.push(record);
    const line: Record<string, unknown> = {
      phase: it.phase, intent: it.id, class: it.class, locale: it.locale ?? null,
      action: `adaptive-${String(proposal.kind)}`, adaptive: true, source: "adaptive",
      snapshot_sha256: snap.sha256, proposal, started_at: now(),
    };
    if (proposal.kind === "stop") {
      record.outcome = "stopped";
      writeDrift();
      logAction({ ...line, result: "stopped", acted: false, reason: proposal.reason, ended_at: now() });
      return drift(it, `${reason}; the resolver stopped: ${String(proposal.reason)}`,
                   { resolution: "stop", adaptive: { used: true, proposal } });
    }
    const v = await validateProposal(it, proposal);
    record.checks = v.checks;
    if (!v.ok) {
      result.adaptive.refused += 1;
      record.outcome = "refused";
      writeDrift();
      logAction({ ...line, result: "refused", acted: false, checks: v.checks, ended_at: now() });
      const failed = v.checks.filter((c) => !c.ok).map((c) => c.check);
      return drift(it, `${reason}; the resolver's ${String(proposal.kind)} was refused (${failed.join(", ")})`,
                   { resolution: "refused", adaptive: { used: true, proposal, checks: v.checks } });
    }
    if (proposal.kind === "resolve") {
      record.outcome = "accepted";
      writeDrift();
      const loc = proposal.locator as Loc;
      return { el: v.el!, rung: rungOf(loc), locator: loc, position: -1,
               adaptive: { snapshot_sha256: snap.sha256, proposal, checks: v.checks, entry: record } };
    }
    try {
      if (proposal.kind === "dismiss") {
        await v.el!.click();
        await settle();
      } else {
        await page.goto(v.url!, { waitUntil: "domcontentloaded" });
        const state = await settledAuth(flow.timeouts.action);
        if (!state.ok) await waitForHuman(it.phase, state);
      }
    } catch (e) {
      record.outcome = "action-failed";
      writeDrift();
      const message = e instanceof Error ? e.message.split("\n")[0] : String(e);
      logAction({ ...line, result: "error", acted: true, checks: v.checks, reason: message, ended_at: now() });
      return stopVisit(it.phase, "action-failed", `${it.id}: the adaptive ${String(proposal.kind)} failed (${message})`, { intent: it.id });
    }
    result.adaptive.acted += 1;
    record.outcome = "acted";
    if (proposal.kind === "navigate") record.worked_path = pathOf(page.url());
    writeDrift();
    logAction({ ...line, result: "ok", acted: true, checks: v.checks, element: v.element,
                url: bare(page.url()), ended_at: now() });
    if (it.action === "navigate") return "navigated";
    const r = await resolve(page, it.target || [], flow.timeouts.action, it.action !== "upload");
    if (r.one) return { ...r.one, adaptive: { via: proposal.kind, snapshot_sha256: snap.sha256, proposal, entry: record, profile_locator: true } };
    reason = `after the adaptive ${String(proposal.kind)}, ${ladderWhy(r.counts)}`;
    counts = r.counts;
  }
}

// An irreversible intent's drift: the resolver's proposal, asked for and recorded as a
// suggestion only. Nothing is checked against the page because nothing is ever done with it.
async function suggest(it: Intent, reason: string): Promise<Record<string, unknown> | null> {
  if (result.adaptive.used >= ADAPT.max_per_visit) return null;
  const snap = await snapshotPage();
  if (!snap) return null;
  result.adaptive.used += 1;
  result.adaptive.suggestions += 1;
  const proposal = await askResolver(it, reason, snap, true);
  driftEntries.push({
    intent: it.id, locale: it.locale ?? null, phase: it.phase, class: it.class, action: it.action,
    failed_ladder: it.target ?? [], why: reason, url: snap.url, snapshot_sha256: snap.sha256,
    proposal, checks: [], outcome: "suggestion", worked: null, at: now(),
  });
  writeDrift();
  logAction({ phase: it.phase, intent: it.id, class: it.class, action: `adaptive-${String(proposal.kind)}`,
              adaptive: true, source: "adaptive", snapshot_sha256: snap.sha256, proposal,
              result: "suggestion", acted: false });
  return { proposal, snapshot_sha256: snap.sha256, url: snap.url,
           note: "a suggestion only, never acted on: a person verifies it and corrects the profile" };
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

function entryFor(it: Intent): Record<string, unknown> {
  const entry: Record<string, unknown> = {
    phase: it.phase, intent: it.id, class: it.class, action: it.action, locale: it.locale ?? null,
    source: "profile", started_at: now(),
  };
  if (it.value_sha256) entry.value_sha256 = it.value_sha256;
  if (it.value_public && it.value !== undefined) entry.value = it.value;
  if (it.files) entry.files = it.files.map((f) => ({ name: f.name, sha256: f.sha256 }));
  return entry;
}

async function runIntent(it: Intent): Promise<string | null> {
  await ensureSession(it.phase);
  const entry = entryFor(it);
  const timeout = it.phase === "upload_build" ? flow.timeouts.upload : flow.timeouts.navigation;

  if (it.action === "navigate") {
    const pre = await shot(`${it.id}-pre`);
    await goto(it.url!, it.phase);
    let post = await checkExpect(it, null, timeout);
    entry.url = bare(page.url());
    entry.result = post.ok ? "ok" : "post-condition-failed";
    entry.post_condition = post;
    entry.screenshots = { pre, post: await shot(`${it.id}-post`) };
    entry.ended_at = now();
    logAction(entry);
    if (!post.ok) {
      await adapt(it, `post-condition failed: ${post.detail}`, null);
      post = await checkExpect(it, null, timeout);
      const again = { ...entryFor(it), adaptive: true, source: "adaptive", url: bare(page.url()),
                      result: post.ok ? "ok" : "post-condition-failed", post_condition: post, ended_at: now() };
      logAction(again);
      const record = driftEntries[driftEntries.length - 1];
      if (record) record.outcome = post.ok ? "ok" : "post-condition-failed";
      writeDrift();
      if (!post.ok) {
        await drift(it, `post-condition failed after the adaptive navigate: ${post.detail}`,
                    { resolution: "post-condition-failed" });
      }
    }
    return null;
  }

  const visibleOnly = it.action !== "upload";
  let r = await resolve(page, it.target || [], flow.timeouts.action, visibleOnly);
  if (!r.one && !(await authState(page)).ok) {
    await ensureSession(it.phase); // a challenge shown mid-flow: the person answers it
    r = await resolve(page, it.target || [], flow.timeouts.action, visibleOnly);
  }
  if (r.one) return await act(it, r.one, timeout);
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
  const adapted = await adapt(it, ladderWhy(r.counts), r.counts);
  return await act(it, adapted as Adapted, timeout);
}

// Act on the element a profile ladder (or an adaptive resolution) found, then check the
// post-condition. A reversible intent's failed post-condition may adapt once; an adaptive
// resolution's failed post-condition never adapts again.
async function act(it: Intent, target: Adapted, timeout: number): Promise<string | null> {
  const entry = entryFor(it);
  const viaResolve = !!target.adaptive && !target.adaptive.profile_locator;
  const el = target.el;
  if (viaResolve) {
    entry.adaptive = true;
    entry.source = "adaptive";
    entry.snapshot_sha256 = target.adaptive!.snapshot_sha256;
    entry.proposal = target.adaptive!.proposal;
    entry.checks = target.adaptive!.checks;
  }
  entry.locator = target.locator;
  entry.rung = target.rung;
  entry.ladder_position = target.position;
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
  if (viaResolve) {
    entry.acted = true;
    result.adaptive.acted += 1;
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
  const record = target.adaptive?.entry as Record<string, unknown> | undefined;
  if (record && viaResolve) {
    record.outcome = post.ok ? "ok" : "post-condition-failed";
    record.post_condition = post;
    if (post.ok) record.worked = target.locator;
    writeDrift();
  }
  if (!post.ok) {
    if (it.class === "irreversible") {
      // Clicked once; what the portal did is not what the profile says it does. Never again.
      return stopVisit(it.phase, "ambiguous-portal-state",
                       `${it.id} was clicked but ${post.detail}: a person reads the portal`, { intent: it.id });
    }
    if (target.adaptive) {
      return drift(it, `post-condition failed after an adaptive resolution: ${post.detail}; never adapted twice`,
                   { resolution: "post-condition-failed" });
    }
    const adapted = await adapt(it, `post-condition failed: ${post.detail}`, null);
    return await act(it, adapted as Adapted, timeout);
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
  const adaptiveMs = flow.adaptive?.enabled ? (flow.adaptive.max_per_visit + 1) * (flow.adaptive.response_timeout_ms + flow.timeouts.navigation) : 0;
  test.setTimeout(flow.login_timeout_ms * 4 + flow.timeouts.upload + flow.timeouts.navigation * 40 + adaptiveMs);
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
