import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const NativeAbortController = globalThis.AbortController;
  class GlobalScopeAbortControllerGuard {
    constructor() {
      throw new Error("THREE_MUST_NOT_INITIALIZE_IN_WORKER_GLOBAL_SCOPE");
    }
  }

  let worker;
  try {
    globalThis.AbortController = GlobalScopeAbortControllerGuard;
    ({ default: worker } = await import(workerUrl.href));
  } finally {
    globalThis.AbortController = NativeAbortController;
  }

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

async function sha256(relativePath) {
  const bytes = await readFile(new URL(relativePath, root));
  return createHash("sha256").update(bytes).digest("hex").toUpperCase();
}

test("worker starts without evaluating Three.js in global scope", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /Loading review engine/);
});

test("keeps controlled model bytes unchanged", async () => {
  const expected = {
    "public/workcore_internal_layout.glb": "2585CC253B20C663BFDE42307AE35300966188167919B8DB9B392465CF31A065",
    "public/workcore_r14_cafe.glb": "C70EEF34781C5EE12F8F0593FDBDB6571074DD7A0D3E8EEB6C9F879F3D0EEA6D",
    "public/workcore_r14_focus.glb": "8C5AAA2ADD514F9BA95493CD416A6A4B9459CC7152157EE07DB59E63037DE673",
    "public/workcore_r14_follow.glb": "2AEF75CEA3805C6828842205EAC6F251D5D1C2B159A173984BA1B15EF5AC1893",
    "public/workcore_r14_ride.glb": "E0C4B02E1390182CDB85835D2C611BD1DDF87445B71987C0B02C7FE8E40CAB13",
  };

  for (const [file, hash] of Object.entries(expected)) {
    assert.equal(await sha256(file), hash, file);
  }
});

test("locks the key interaction and provenance invariants in source", async () => {
  const source = await readFile(new URL("app/r14-experience.tsx", root), "utf8");
  const clientBoundary = await readFile(new URL("app/r14-client.tsx", root), "utf8");
  const page = await readFile(new URL("app/page.tsx", root), "utf8");

  assert.match(clientBoundary, /ssr:\s*false/);
  assert.match(clientBoundary, /import\("\.\/r14-experience"\)/);
  assert.match(page, /R14Client/);
  assert.doesNotMatch(page, /r14-experience/);
  assert.match(source, /摇杆始终位于右扶手顶端/);
  assert.match(source, /BLENDER VISUAL COMPOSITE · NO STEP \/ MOTION \/ PRODUCTION CLAIM/);
  assert.match(source, /E6-DFR3 HISTORICAL PACKAGING SUBSET · NOT CURRENT R14/);
  assert.match(source, /LEFT_QI_FLUSH_USABLE_FIELD_176X86/);
  assert.match(source, /footrestSlide\.position/);
  assert.match(source, /\(1 - motion\.footrest\) \* 0\.22/);
  assert.match(source, /name\.toLowerCase\(\) === "service_rear_flush_door"/);
  assert.doesNotMatch(source, /obstacle_handle_positive_latch.*SLIDE_A04/s);
  assert.match(source, /activeState === "focus" \? "cafe" : "focus"/);
  assert.match(source, /applyProductState\("ride"\)/);
});
