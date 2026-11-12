"use strict";
// The size workflows run nothing of the pull request: a pull request's own copy of size-report.cjs
// or of the workflow could pass its own growth. `ci` runs the head's copy under these tests instead.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

function workflow(file) {
  const yml = fs.readFileSync(path.join(__dirname, "../workflows", file), "utf8");
  return {
    triggers: [...yml.matchAll(/^ {2}([a-z_]+):\s*$/gm)].filter((m) => yml.lastIndexOf("\non:", m.index) > yml.lastIndexOf("\njobs:", m.index)).map((m) => m[1]),
    refs: [...yml.matchAll(/^\s+ref:\s*(.+?)\s*$/gm)].map((m) => m[1]),
  };
}

test("the size check takes its workflow from the default branch and its script from the base", () => {
  const w = workflow("size.yml");
  assert.ok(w.triggers.includes("pull_request_target"), w.triggers.join(", "));
  assert.deepEqual(w.refs, ["${{ github.event.pull_request.base.sha }}"]);
});

test("the size comment takes both from the default branch", () => {
  assert.deepEqual(workflow("size-comment.yml"), { triggers: ["pull_request_target"], refs: ["${{ github.event.repository.default_branch }}"] });
});
