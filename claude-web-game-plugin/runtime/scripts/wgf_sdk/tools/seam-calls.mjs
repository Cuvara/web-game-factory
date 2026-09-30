#!/usr/bin/env node
// The game's calls on its integration seam, read by the TypeScript compiler.
//
//     node seam-calls.mjs <game repository>
//
// Run by the Factory's `sdk` step (scripts/wgf_sdk/integrate.py) with the TypeScript the game
// repository itself installs. A call is a seam call when the checker resolves the called
// method to the GameIntegration interface declared in src/game/integration.ts - whatever the
// receiver is named or wherever it came from (a parameter, a context object, a field). A
// placement id is the argument's string-literal type, so a `const` name, an `as const`
// member or a literal union resolves exactly, and a computed id is reported as unresolved.
// Comments are not code. Files under src/platform/ (the wiring) are not the game's calls.
//
// Prints one JSON object: {"scanner": "typescript", "version", "calls": [{"method",
// "placements": [ids] | null, "argument", "where"}]}. Exit 3 when the repository has no
// TypeScript to read it with; exit 4 when its tsconfig cannot be read.

import { createRequire } from "node:module";
import { join, relative, resolve, sep } from "node:path";

const METHODS = new Set([
  "gameplayStart",
  "gameplayStop",
  "canOfferRewarded",
  "rewarded",
  "interstitial",
  "track",
  "load",
  "save",
]);
const PLACEMENT_METHODS = new Set(["canOfferRewarded", "rewarded", "interstitial"]);
const CONTRACT = "src/game/integration.ts";

const repo = resolve(process.argv[2] ?? ".");
let ts;
try {
  ts = createRequire(join(repo, "package.json"))("typescript");
} catch (error) {
  console.log(JSON.stringify({ error: "typescript-unavailable", detail: String(error) }));
  process.exit(3);
}

const rel = (file) => relative(repo, file).split(sep).join("/");
const configPath = ts.findConfigFile(repo, ts.sys.fileExists, "tsconfig.json");
const problems = [];
const parsed =
  configPath &&
  ts.getParsedCommandLineOfConfigFile(
    configPath,
    {},
    { ...ts.sys, onUnRecoverableConfigFileDiagnostic: (d) => problems.push(String(d.messageText)) },
  );
if (!parsed) {
  console.log(JSON.stringify({ error: "tsconfig-unreadable", detail: problems.join("; ") }));
  process.exit(4);
}

const program = ts.createProgram({
  rootNames: parsed.fileNames,
  options: { ...parsed.options, noEmit: true },
  projectReferences: parsed.projectReferences,
});
const checker = program.getTypeChecker();

function fromContract(symbol) {
  const declarations = symbol?.declarations ?? [];
  return declarations.some((d) => rel(d.getSourceFile().fileName) === CONTRACT);
}

function isSeamMethod(access) {
  if (fromContract(checker.getSymbolAtLocation(access.name))) return true;
  // A receiver whose type implements the contract without naming it at the call site.
  const type = checker.getTypeAtLocation(access.expression);
  const property = type && checker.getPropertyOfType(type, access.name.text);
  return fromContract(property);
}

function placementsOf(argument) {
  if (!argument) return null;
  const type = checker.getTypeAtLocation(argument);
  const members = type.isUnion() ? type.types : [type];
  const values = members.map((t) => (t.isStringLiteral() ? t.value : null));
  return values.every((v) => typeof v === "string") && values.length > 0 ? values : null;
}

const calls = [];
for (const file of program.getSourceFiles()) {
  const path = rel(file.fileName);
  if (!path.startsWith("src/") || path.startsWith("src/platform/") || path === CONTRACT) continue;
  const visit = (node) => {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      METHODS.has(node.expression.name.text) &&
      isSeamMethod(node.expression)
    ) {
      const method = node.expression.name.text;
      const argument = node.arguments[0];
      const line = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
      calls.push({
        method,
        placements: PLACEMENT_METHODS.has(method) ? placementsOf(argument) : null,
        argument: argument ? argument.getText(file) : "",
        where: `${path}:${line}`,
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
}

console.log(JSON.stringify({ scanner: "typescript", version: ts.version, calls }));
