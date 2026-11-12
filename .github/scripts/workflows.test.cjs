"use strict";
// The size workflows run only a trusted copy of size-report.cjs: a pull request's own copy could
// pass its own growth. `ci` runs the head's copy under these tests instead.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

function checkoutRefs(file) {
  const yml = fs.readFileSync(path.join(__dirname, "../workflows", file), "utf8");
  return [...yml.matchAll(/^\s+ref:\s*(.+?)\s*$/gm)].map((m) => m[1]);
}

test("the size check loads its script from the pull request's base", () => {
  assert.deepEqual(checkoutRefs("size.yml"), ["${{ github.event.pull_request.base.sha }}"]);
});

test("the size comment loads its script from the default branch", () => {
  assert.deepEqual(checkoutRefs("size-comment.yml"), ["${{ github.event.repository.default_branch }}"]);
});
