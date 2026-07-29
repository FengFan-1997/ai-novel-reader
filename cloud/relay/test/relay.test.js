import assert from "node:assert/strict";
import test from "node:test";

test("relay package exposes a production start command", async () => {
  const packageJson = await import("../package.json", { with: { type: "json" } });
  assert.equal(packageJson.default.scripts.start, "node server.js");
  assert.equal(packageJson.default.private, true);
});
