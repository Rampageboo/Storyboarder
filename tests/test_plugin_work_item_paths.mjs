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
