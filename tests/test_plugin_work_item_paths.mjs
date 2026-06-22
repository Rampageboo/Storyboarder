import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const context = { URL };
vm.createContext(context);
vm.runInContext(readFileSync(new URL("../photoshop_uxp_plugin/work_item_paths.js", import.meta.url), "utf8"), context);

const {
  normalizeNativePath,
  sameNativePath,
  findWorkItemByNativePath,
  deriveActiveWorkKey,
  filterKnownOpenWorkKeys,
  displayPerspectiveIndex,
  scene2DPerspectiveOptions,
  shouldPreserveManualMode,
  formatShotDisplayLabel,
  setWorkItems,
  getWorkItems,
  shotWorkItemById,
  shotDisplayLabel,
} = context;

const pluginContext = {
  project_root: "C:/Project",
  work_items: [
    {
      kind: "scene2d",
      key: "scene2d:scene-a:persp-a",
      scene_id: "scene-a",
      perspective_id: "persp-a",
      source_file_path: "scenes2d/scene-a/perspectives/persp-a/source.psd",
      source_native_path: "C:/Project/scenes2d/scene-a/perspectives/persp-a/source.psd",
    },
    {
      kind: "scene2d",
      key: "scene2d:scene-b:persp-b",
      scene_id: "scene-b",
      perspective_id: "persp-b",
      source_file_path: "scenes2d/scene-b/perspectives/persp-b/source.psd",
      source_native_path: "C:/Project/scenes2d/scene-b/perspectives/persp-b/source.psd",
    },
    {
      kind: "shot",
      key: "shot:shot_001",
      shot_id: "shot_001",
      source_file_path: "shots/shot_001/shot_001.psd",
      source_native_path: "C:/Project/shots/shot_001/shot_001.psd",
    },
  ],
};

test("normalizes slashes, file URLs, and drive-letter case", () => {
  assert.equal(
    normalizeNativePath("file:///C:/Project/scenes2d/scene-a/perspectives/persp-a/source.psd"),
    "c:/Project/scenes2d/scene-a/perspectives/persp-a/source.psd",
  );
  assert.ok(sameNativePath(
    "C:\\Project\\scenes2d\\scene-a\\perspectives\\persp-a\\source.psd",
    "c:/Project/scenes2d/scene-a/perspectives/persp-a/source.psd",
  ));
});

test("matches identical source.psd tabs only by full native path", () => {
  assert.equal(
    findWorkItemByNativePath("C:/Project/scenes2d/scene-a/perspectives/persp-a/source.psd", pluginContext)?.key,
    "scene2d:scene-a:persp-a",
  );
  assert.equal(
    findWorkItemByNativePath("C:/Project/scenes2d/scene-b/perspectives/persp-b/source.psd", pluginContext)?.key,
    "scene2d:scene-b:persp-b",
  );
  assert.notEqual(
    findWorkItemByNativePath("C:/Project/scenes2d/scene-a/perspectives/persp-a/source.psd", pluginContext)?.key,
    findWorkItemByNativePath("C:/Project/scenes2d/scene-b/perspectives/persp-b/source.psd", pluginContext)?.key,
  );
});

test("does not treat filename-only source.psd or unrelated PSDs as matches", () => {
  assert.equal(findWorkItemByNativePath("source.psd", pluginContext), null);
  assert.equal(findWorkItemByNativePath("C:/Project/unrelated/source.psd", pluginContext), null);
});

test("falls back to project root plus source_file_path when native path is absent", () => {
  const contextWithoutNative = {
    project_root: pluginContext.project_root,
    work_items: [
      {
        kind: "scene2d",
        key: "scene2d:scene-a:persp-a",
        source_file_path: "scenes2d/scene-a/perspectives/persp-a/source.psd",
      },
    ],
  };
  assert.equal(
    findWorkItemByNativePath("C:/Project/scenes2d/scene-a/perspectives/persp-a/source.psd", contextWithoutNative)?.key,
    "scene2d:scene-a:persp-a",
  );
});

test("derives and filters work keys without accepting stale keys", () => {
  assert.equal(deriveActiveWorkKey({ key: "scene2d:scene-a:persp-a" }), "scene2d:scene-a:persp-a");
  assert.deepEqual(
    Array.from(filterKnownOpenWorkKeys(
      ["scene2d:scene-a:persp-a", "scene2d:anything:anything", "scene2d:scene-a:persp-a"],
      new Set(["scene2d:scene-a:persp-a"]),
    )),
    ["scene2d:scene-a:persp-a"],
  );
});

test("displays first perspective as one-based 1 / N", () => {
  assert.equal(displayPerspectiveIndex(1, 4), "1 / 4");
  assert.equal(displayPerspectiveIndex(4, 4), "4 / 4");
});

test("filters perspective selector options to the active scene group", () => {
  const options = scene2DPerspectiveOptions([
    {
      kind: "scene2d",
      key: "scene2d:scene-a:persp-a",
      scene_id: "scene-a",
      perspective_id: "persp-a",
      scene_title: "Scene A",
      perspective_title: "Main",
      perspective_type: "psd",
    },
    {
      kind: "scene2d",
      key: "scene2d:scene-b:persp-b",
      scene_id: "scene-b",
      perspective_id: "persp-b",
      scene_title: "Scene B",
      perspective_title: "Other",
      perspective_type: "image",
    },
    { kind: "shot", shot_id: "shot_001" },
  ], "scene-b");

  assert.deepEqual(JSON.parse(JSON.stringify(options)), [
    {
      key: "scene2d:scene-b:persp-b",
      scene_id: "scene-b",
      perspective_id: "persp-b",
      scene_title: "Scene B",
      perspective_title: "Other",
      perspective_type: "image",
    },
  ]);
});

test("preserves only explicit manual connection modes during bridge failures", () => {
  assert.equal(shouldPreserveManualMode("manual-project"), true);
  assert.equal(shouldPreserveManualMode("manual-folder"), true);
  assert.equal(shouldPreserveManualMode("linked"), false);
  assert.equal(shouldPreserveManualMode("disconnected"), false);
  assert.equal(shouldPreserveManualMode("folder-error"), false);
});

// ── formatShotDisplayLabel (Part 2) ─────────────────────────────────────────

test("formatShotDisplayLabel — title present returns index. title", () => {
  assert.equal(formatShotDisplayLabel({ index: 1, shot_title: "Copy" }), "1. Copy");
});

test("formatShotDisplayLabel — empty title returns index. Untitled shot", () => {
  assert.equal(formatShotDisplayLabel({ index: 16, shot_title: "" }), "16. Untitled shot");
});

test("formatShotDisplayLabel — whitespace title treated as empty", () => {
  assert.equal(formatShotDisplayLabel({ index: 3, shot_title: "   " }), "3. Untitled shot");
});

test("formatShotDisplayLabel — null title treated as empty", () => {
  assert.equal(formatShotDisplayLabel({ index: 5, shot_title: null }), "5. Untitled shot");
});

test("formatShotDisplayLabel — no shot_title key treated as empty", () => {
  assert.equal(formatShotDisplayLabel({ index: 7 }), "7. Untitled shot");
});

test("formatShotDisplayLabel — multi-word title", () => {
  assert.equal(
    formatShotDisplayLabel({ index: 16, shot_title: "Look at the moon" }),
    "16. Look at the moon",
  );
});

// ── setWorkItems / getWorkItems / shotWorkItemById ───────────────────────────

test("getWorkItems returns empty array initially after reset", () => {
  setWorkItems([]);
  assert.equal(getWorkItems().length, 0);
});

test("setWorkItems stores items and getWorkItems retrieves them", () => {
  setWorkItems([
    { kind: "shot", shot_id: "abc", index: 1, shot_title: "A", count: 2, previous_key: "", next_key: "shot:def" },
    { kind: "shot", shot_id: "def", index: 2, shot_title: "B", count: 2, previous_key: "shot:abc", next_key: "" },
  ]);
  assert.equal(getWorkItems().length, 2);
  setWorkItems([]);
});

test("setWorkItems ignores non-array input and resets to empty", () => {
  setWorkItems("not an array");
  assert.equal(getWorkItems().length, 0);
});

test("shotWorkItemById finds item by shot_id", () => {
  setWorkItems([{ kind: "shot", shot_id: "abc123", index: 1, shot_title: "A" }]);
  const item = shotWorkItemById("abc123");
  assert.ok(item, "item should be found");
  assert.equal(item.shot_id, "abc123");
  setWorkItems([]);
});

test("shotWorkItemById returns null for unknown id", () => {
  setWorkItems([{ kind: "shot", shot_id: "abc123", index: 1, shot_title: "A" }]);
  assert.equal(shotWorkItemById("zzz"), null);
  setWorkItems([]);
});

// ── shotDisplayLabel ─────────────────────────────────────────────────────────

test("shotDisplayLabel uses work item when available", () => {
  setWorkItems([{ kind: "shot", shot_id: "aaa", index: 5, shot_title: "Action", count: 10,
    previous_key: "", next_key: "" }]);
  assert.equal(shotDisplayLabel("aaa", 4, "Action"), "5. Action");
  setWorkItems([]);
});

test("shotDisplayLabel falls back to array index when shot_id not in work items", () => {
  setWorkItems([]);
  assert.equal(shotDisplayLabel("unknown", 0, "Backup"), "1. Backup");
});

test("shotDisplayLabel fallback with empty title shows Untitled shot", () => {
  setWorkItems([]);
  assert.equal(shotDisplayLabel("x", 2, ""), "3. Untitled shot");
});

// ── option value must be canonical key, not the label ───────────────────────

test("option value stays as shot_id while label is human-readable", () => {
  const shotId = "71cca9b8deadbeef";
  setWorkItems([{ kind: "shot", shot_id: shotId, index: 16, shot_title: "", count: 58,
    previous_key: "", next_key: "" }]);
  const optionValue = shotId;
  const optionText = shotDisplayLabel(shotId, 15, "");
  assert.equal(optionValue, shotId);
  assert.equal(optionText, "16. Untitled shot");
  assert.notEqual(optionValue, optionText);
  setWorkItems([]);
});
