import test from "node:test";
import assert from "node:assert/strict";
import {
  INITIAL_SHOTS,
  INITIAL_EDGES,
  INITIAL_ROUTES,
  getRouteShots,
  addBranch,
} from "../src/story-model.js";

const initialState = () =>
  structuredClone({
    shots: INITIAL_SHOTS,
    edges: INITIAL_EDGES,
    routes: INITIAL_ROUTES,
  });

test("initial routes resolve in order and every route transition has an edge", () => {
  assert.equal(INITIAL_SHOTS.length, 10);
  for (const route of INITIAL_ROUTES) {
    assert.deepEqual(
      getRouteShots(INITIAL_SHOTS, route).map((shot) => shot.id),
      route.shotIds,
    );
    route.shotIds.slice(1).forEach((id, index) => {
      assert.ok(
        INITIAL_EDGES.some(
          (edge) => edge.source === route.shotIds[index] && edge.target === id,
        ),
      );
    });
  }
  assert.deepEqual(
    INITIAL_EDGES.filter((edge) => edge.source === "02")
      .map((edge) => edge.target)
      .sort(),
    ["03", "06", "08"],
  );
  assert.equal(INITIAL_EDGES.filter((edge) => edge.target === "10").length, 3);
});

test("route resolution refuses missing references instead of silently skipping them", () => {
  assert.throws(
    () => getRouteShots(INITIAL_SHOTS, { shotIds: ["01", "missing"] }),
    /Unknown shot/,
  );
  assert.throws(() => getRouteShots(undefined, INITIAL_ROUTES[0]), TypeError);
  assert.throws(() => getRouteShots(INITIAL_SHOTS, undefined), TypeError);
  assert.deepEqual(getRouteShots(INITIAL_SHOTS, { shotIds: [] }), []);
});

test("new branch inherits its source route prefix and ends without an automatic merge", () => {
  const result = addBranch(initialState(), {
    fromId: "04",
    title: "  跟随陌生人  ",
  });
  const route = result.routes.find((route) => route.id === result.routeId);
  assert.deepEqual(route.shotIds, ["01", "02", "03", "04", result.shotId]);
  assert.equal(route.name, "跟随陌生人");
  assert.equal(
    result.shots.find((shot) => shot.id === result.shotId).image,
    "/assets/dialogue.png",
  );
  assert.ok(
    result.edges.some(
      (edge) => edge.source === "04" && edge.target === result.shotId,
    ),
  );
  assert.ok(!result.edges.some((edge) => edge.source === result.shotId));
});

test("shared parent chooses the first existing route deterministically", () => {
  const result = addBranch(initialState(), { fromId: "10", title: "尾声" });
  assert.deepEqual(result.routes.at(-1).shotIds, [
    ...INITIAL_ROUTES[0].shotIds,
    result.shotId,
  ]);
});

test("branching at a merge preserves the explicitly selected route prefix", () => {
  const result = addBranch(initialState(), {
    fromId: "10",
    title: "备选尾声",
    routeId: "alternate",
  });
  assert.deepEqual(result.routes.at(-1).shotIds, [
    "01",
    "02",
    "08",
    "09",
    "10",
    result.shotId,
  ]);
});

test("explicit unknown or mismatching routes are rejected instead of falling back", () => {
  assert.throws(
    () =>
      addBranch(initialState(), {
        fromId: "10",
        title: "尾声",
        routeId: "missing",
      }),
    /Unknown route/,
  );
  assert.throws(
    () =>
      addBranch(initialState(), {
        fromId: "06",
        title: "分支",
        routeId: "alternate",
      }),
    /not in route/,
  );
});

test("repeated branches remain unique, do not overlap siblings, and can themselves branch", () => {
  const first = addBranch(initialState(), { fromId: "02", title: "方案 A" });
  const second = addBranch(first, { fromId: "02", title: "方案 A" });
  assert.notEqual(first.shotId, second.shotId);
  assert.notEqual(first.routeId, second.routeId);
  for (const items of [second.shots, second.edges, second.routes]) {
    assert.equal(new Set(items.map((item) => item.id)).size, items.length);
  }
  const siblingA = second.shots.find((shot) => shot.id === first.shotId);
  const siblingB = second.shots.find((shot) => shot.id === second.shotId);
  assert.notDeepEqual([siblingA.x, siblingA.y], [siblingB.x, siblingB.y]);
  const third = addBranch(second, { fromId: first.shotId, title: "继续 A" });
  assert.deepEqual(third.routes.at(-1).shotIds, [
    "01",
    "02",
    first.shotId,
    third.shotId,
  ]);
});

test("branch validation rejects incomplete input, blank titles, and unknown or unrouted parents", () => {
  assert.throws(() => addBranch(), TypeError);
  assert.throws(() => addBranch(initialState()), /title/i);
  for (const title of ["", "   ", null, 42]) {
    assert.throws(
      () => addBranch(initialState(), { fromId: "02", title }),
      /title/i,
    );
  }
  assert.throws(
    () => addBranch(initialState(), { fromId: "missing", title: "新分支" }),
    /Unknown parent/,
  );
  const unrouted = initialState();
  unrouted.routes = [];
  assert.throws(
    () => addBranch(unrouted, { fromId: "02", title: "新分支" }),
    /no route/,
  );
});

test("adding a branch does not mutate the input graph or existing route arrays", () => {
  const state = initialState();
  const before = structuredClone(state);
  const freeze = (object) => {
    Object.freeze(object);
    Object.values(object).forEach((value) => {
      if (value && typeof value === "object") freeze(value);
    });
  };
  freeze(state);
  const result = addBranch(state, { fromId: "02", title: "独立结尾" });
  assert.deepEqual(state, before);
  assert.notEqual(result.shots, state.shots);
  assert.notEqual(result.edges, state.edges);
  assert.notEqual(result.routes, state.routes);
});
