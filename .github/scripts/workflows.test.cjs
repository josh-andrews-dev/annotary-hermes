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
    permissions: /^permissions:\n((?: {2}.*\n)*)/m.exec(yml)[1].trim().split(/\n\s*/),
    runs: [...yml.matchAll(/^\s+(?:- )?run:/gm)].length,
  };
}

test("the size check takes its workflow from the default branch and its script from the base", () => {
  assert.deepEqual(workflow("size.yml"), {
    triggers: ["pull_request_target"],
    refs: ["${{ github.event.pull_request.base.sha }}"],
    permissions: ["contents: read"],
    runs: 0,
  });
});

test("the size comment takes both from the default branch", () => {
  const w = workflow("size-comment.yml");
  assert.deepEqual([w.triggers, w.refs, w.permissions], [["pull_request_target"], ["${{ github.event.repository.default_branch }}"],
    ["contents: read", "pull-requests: write"]]);
});
