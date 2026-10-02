// The deterministic console executor: one Playwright test that drives a portal's developer
// console through fixed phases, from a FLOW file the publish adapter wrote, and writes a
// RESULT file the adapter reads. No model decides anything here; every selector, URL and
// marker is data from core/reference/publication/<id>.yaml and the adapter, and every phase
// ends in one of a few named outcomes. This file is copied into the checkout's release/
// scratch directory by scripts/wgf_publish/browser.py and run with `pnpm exec playwright
// test` under wgflib.procs; it never lives in a committed path.
//
// Phases (in order; a phase that does not end `ok` stops the run and the result says why):
//   authenticate   open the console with the captured storage state; is the session live?
//                  -> ok | login_required | captcha | two_factor | error
//   find_existing  look for a draft carrying the idempotency key -> ok (found or not)
//   upload         when none was found: create the draft, set the file, wait for the upload
//                  to be acknowledged, read the draft id -> ok | error | timeout
//   configure      fill the listing fields and save -> ok | error
//   submit         ONLY when the flow says `submit: true`: click submit once, wait for the
//                  acknowledgement -> ok | error
//   verify         read the portal's own status text back -> ok (with the text) | error
//
// Screenshots are taken only on console pages after a known navigation, never on a login
// page or a challenge. Every request to an origin outside `allowed_origins` is aborted.

import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

type Flow = {
  console_url: string;
  allowed_origins: string[];
  storage_state: string | null;
  output_dir: string;
  phases: string[];
  submit: boolean;
  key: string;
  package: string | null;
  metadata: Record<string, string>;
  selectors: Record<string, string>;
  timeouts: { action: number; navigation: number; upload: number };
};

type PhaseResult = {
  outcome: string;
  detail?: string;
  draft_id?: string | null;
  found?: boolean;
  status_text?: string;
  url?: string;
  screenshot?: string;
  text?: string;
};

const flowPath = process.env.WGF_PUBLISH_FLOW!;
const resultPath = process.env.WGF_PUBLISH_RESULT!;
const flow: Flow = JSON.parse(fs.readFileSync(flowPath, "utf-8"));
const result: { phases: Record<string, PhaseResult>; refused: string[]; errors: string[] } = {
  phases: {},
  refused: [],
  errors: [],
};

function write() {
  fs.mkdirSync(path.dirname(resultPath), { recursive: true });
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2));
}

function sel(name: string): string | undefined {
  const value = flow.selectors[name];
  return value && value.length ? value : undefined;
}

function allowed(url: string): boolean {
  try {
    const origin = new URL(url).origin;
    return flow.allowed_origins.some((o) => origin === new URL(o).origin);
  } catch {
    return false;
  }
}

async function shot(page: Page, name: string): Promise<string> {
  fs.mkdirSync(flow.output_dir, { recursive: true });
  const file = path.join(flow.output_dir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  return file;
}

async function visible(page: Page, name: string, timeout = 1500): Promise<boolean> {
  const s = sel(name);
  if (!s) return false;
  try {
    return await page.locator(s).first().isVisible({ timeout });
  } catch {
    return false;
  }
}

async function textOf(page: Page, name: string): Promise<string> {
  const s = sel(name);
  if (!s) return "";
  const locator = page.locator(s).first();
  await locator.waitFor({ state: "visible", timeout: flow.timeouts.action });
  return (await locator.innerText()).trim();
}

// The draft's own page, when the adapter names one (status_url) and the run is not on it:
// a draft found in the list is acted on from its page, like one just uploaded.
async function onDraftPage(page: Page, draftId: string | null) {
  const statusUrl = sel("status_url");
  if (!statusUrl || !draftId) return;
  const target = statusUrl.replace("{id}", draftId);
  if (page.url().split("#")[0] !== target) {
    await page.goto(target, { waitUntil: "domcontentloaded" });
  }
}

function fail(phase: string, outcome: string, detail: string) {
  result.phases[phase] = { outcome, detail };
  result.errors.push(`${phase}: ${outcome}: ${detail}`);
  write();
}

test("publication console flow", async ({ browser }) => {
  test.setTimeout(flow.timeouts.upload + flow.timeouts.navigation * 4);
  const context: BrowserContext = await browser.newContext(
    flow.storage_state ? { storageState: flow.storage_state } : {},
  );
  await context.route("**/*", (route) => {
    const url = route.request().url();
    if (allowed(url) || url.startsWith("data:") || url.startsWith("about:")) return route.continue();
    result.refused.push(url);
    return route.abort("blockedbyclient");
  });
  const page = await context.newPage();
  page.setDefaultTimeout(flow.timeouts.action);
  page.setDefaultNavigationTimeout(flow.timeouts.navigation);
  let draftId: string | null = null;
  let found = false;

  try {
    for (const phase of flow.phases) {
      if (phase === "authenticate") {
        await page.goto(flow.console_url, { waitUntil: "domcontentloaded" });
        if (await visible(page, "captcha")) return fail(phase, "captcha", "a CAPTCHA is shown; a person solves it");
        if (await visible(page, "two_factor")) return fail(phase, "two_factor", "a second factor is asked; a person answers it");
        if (await visible(page, "login_form")) return fail(phase, "login_required", "the console shows its login form: the captured session is absent or expired");
        if (!(await visible(page, "logged_in", flow.timeouts.action))) {
          return fail(phase, "error", `neither the console (${sel("logged_in")}) nor its login form appeared at ${page.url()}`);
        }
        result.phases[phase] = { outcome: "ok", url: page.url() };
        write();
      } else if (phase === "find_existing") {
        const url = sel("drafts_url") || flow.console_url;
        await page.goto(url, { waitUntil: "domcontentloaded" });
        if (await visible(page, "login_form")) return fail(phase, "login_required", "the session expired while listing drafts");
        const rows = page.locator(sel("draft_row") || "[data-draft]");
        const count = await rows.count();
        for (let i = 0; i < count; i++) {
          const row = rows.nth(i);
          const text = (await row.innerText()).trim();
          const attr = await row.getAttribute(sel("draft_id_attr") || "data-id");
          if (text.includes(flow.key) || (attr && attr === flow.key)) {
            found = true;
            draftId = attr || text;
            break;
          }
        }
        const screenshot = await shot(page, "find-existing");
        result.phases[phase] = { outcome: "ok", found, draft_id: draftId, screenshot, url: page.url() };
        write();
      } else if (phase === "upload") {
        if (found) {
          result.phases[phase] = { outcome: "ok", detail: "skipped: a draft with this key exists", draft_id: draftId };
          write();
          continue;
        }
        if (!flow.package) return fail(phase, "error", "no package to upload");
        await page.goto(sel("new_draft_url") || flow.console_url, { waitUntil: "domcontentloaded" });
        if (await visible(page, "login_form")) return fail(phase, "login_required", "the session expired before the upload");
        const nameInput = sel("name_input");
        if (nameInput) await page.locator(nameInput).first().fill(flow.key);
        const fileInput = sel("file_input");
        if (!fileInput) return fail(phase, "error", "the adapter names no file_input selector");
        await page.locator(fileInput).first().setInputFiles(flow.package);
        const button = sel("upload_button");
        if (button) await page.locator(button).first().click();
        const done = sel("upload_done");
        const uploadError = sel("upload_error");
        if (done) {
          // Acknowledged, or refused: whichever the console shows first.
          let settled = page.locator(done).first();
          if (uploadError) settled = settled.or(page.locator(uploadError).first());
          try {
            await settled.waitFor({ state: "visible", timeout: flow.timeouts.upload });
          } catch (e) {
            return fail(phase, "timeout", `the upload was not acknowledged within ${flow.timeouts.upload} ms (${done})`);
          }
        }
        if (await visible(page, "upload_error")) {
          return fail(phase, "error", `the console reports an upload error: ${await textOf(page, "upload_error")}`);
        }
        draftId = sel("draft_id") ? await textOf(page, "draft_id") : null;
        const screenshot = await shot(page, "uploaded");
        result.phases[phase] = { outcome: "ok", draft_id: draftId, screenshot, url: page.url() };
        write();
      } else if (phase === "configure") {
        await onDraftPage(page, draftId);
        for (const [field, value] of Object.entries(flow.metadata || {})) {
          const s = sel(`field_${field}`);
          if (s) await page.locator(s).first().fill(value);
        }
        const save = sel("save_button");
        if (save) {
          await page.locator(save).first().click();
          const saved = sel("saved");
          if (saved) await page.locator(saved).first().waitFor({ state: "visible" });
        }
        result.phases[phase] = { outcome: "ok", url: page.url() };
        write();
      } else if (phase === "submit") {
        if (!flow.submit) {
          result.phases[phase] = { outcome: "skipped", detail: "dry run: the submit was not clicked" };
          write();
          continue;
        }
        const button = sel("submit_button");
        if (!button) return fail(phase, "error", "the adapter names no submit_button selector");
        await onDraftPage(page, draftId);
        const locator = page.locator(button).first();
        await locator.waitFor({ state: "visible" });
        await locator.click(); // once
        const done = sel("submit_done");
        if (done) {
          try {
            await page.locator(done).first().waitFor({ state: "visible", timeout: flow.timeouts.navigation });
          } catch (e) {
            return fail(phase, "error", `the submit was clicked but not acknowledged (${done}); the portal state must be read by a person`);
          }
        }
        const screenshot = await shot(page, "submitted");
        result.phases[phase] = { outcome: "ok", screenshot, url: page.url() };
        write();
      } else if (phase === "verify") {
        const statusUrl = sel("status_url");
        if (statusUrl && draftId) {
          await page.goto(statusUrl.replace("{id}", draftId), { waitUntil: "domcontentloaded" });
        }
        if (await visible(page, "login_form")) return fail(phase, "login_required", "the session expired before the state could be read");
        let statusText = "";
        try {
          statusText = await textOf(page, "status_text");
        } catch (e) {
          return fail(phase, "error", `the status text (${sel("status_text")}) did not appear at ${page.url()}`);
        }
        const screenshot = await shot(page, "verify");
        result.phases[phase] = { outcome: "ok", status_text: statusText, draft_id: draftId, screenshot, url: page.url() };
        write();
      } else {
        return fail(phase, "error", `unknown phase ${phase}`);
      }
    }
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    result.errors.push(message);
    write();
    throw e;
  } finally {
    await context.close();
    write();
  }
  expect(result.errors).toEqual([]);
});
