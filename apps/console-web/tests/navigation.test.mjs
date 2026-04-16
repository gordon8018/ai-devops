import test from "node:test";
import assert from "node:assert/strict";

import { consoleNavItems } from "../lib/navigation.mjs";

test("console navigation exposes the governance section", () => {
  assert.deepEqual(
    consoleNavItems.map((item) => item.id),
    ["mission-control", "task-workspace", "releases", "incidents", "evals", "governance"],
  );
  assert.equal(consoleNavItems[0].href, "/");
  assert.equal(consoleNavItems[1].href, "/work-items");
  assert.equal(consoleNavItems[5].href, "/governance");
});
