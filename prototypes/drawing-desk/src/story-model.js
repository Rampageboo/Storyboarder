/** In-memory prototype data. Branches are endings until explicitly connected. */
export const INITIAL_SHOTS = [
  {
    id: "01",
    title: "末班站台",
    image: "/assets/station.png",
    duration: 3,
    x: 150,
    y: 0,
  },
  {
    id: "02",
    title: "钟声响起",
    image: "/assets/station.png",
    duration: 2,
    x: 150,
    y: 130,
  },
  {
    id: "03",
    title: "陌生人出现",
    image: "/assets/dialogue.png",
    duration: 3,
    x: 0,
    y: 260,
  },
  {
    id: "04",
    title: "暗中观察",
    image: "/assets/dialogue.png",
    duration: 2,
    x: 0,
    y: 390,
  },
  {
    id: "05",
    title: "走向月台",
    image: "/assets/station.png",
    duration: 3,
    x: 0,
    y: 520,
  },
  {
    id: "06",
    title: "站台对话",
    image: "/assets/dialogue.png",
    duration: 4,
    x: 150,
    y: 260,
  },
  {
    id: "07",
    title: "车厢谜团",
    image: "/assets/train.png",
    duration: 3,
    x: 150,
    y: 390,
  },
  {
    id: "08",
    title: "转身离开",
    image: "/assets/station.png",
    duration: 3,
    x: 300,
    y: 260,
  },
  {
    id: "09",
    title: "停下脚步",
    image: "/assets/dialogue.png",
    duration: 2,
    x: 300,
    y: 390,
  },
  {
    id: "10",
    title: "最后一班车",
    image: "/assets/train.png",
    duration: 4,
    x: 150,
    y: 650,
  },
];

export const INITIAL_EDGES = [
  ["01", "02"],
  ["02", "03"],
  ["03", "04"],
  ["04", "05"],
  ["05", "10"],
  ["02", "06"],
  ["06", "07"],
  ["07", "10"],
  ["02", "08"],
  ["08", "09"],
  ["09", "10"],
].map(([source, target]) => ({ id: `${source}-${target}`, source, target }));

export const INITIAL_ROUTES = [
  { id: "main", name: "主角线", shotIds: ["01", "02", "06", "07", "10"] },
  {
    id: "parallel",
    name: "陌生人线",
    shotIds: ["01", "02", "03", "04", "05", "10"],
  },
  {
    id: "alternate",
    name: "备选走向",
    shotIds: ["01", "02", "08", "09", "10"],
  },
];

/** Resolve every route entry in order; dangling references are an error. */
export function getRouteShots(shots, route) {
  if (!Array.isArray(shots) || !Array.isArray(route?.shotIds)) {
    throw new TypeError("Shots and route.shotIds must be arrays.");
  }
  const byId = new Map(shots.map((shot) => [shot.id, shot]));
  return route.shotIds.map((id) => {
    if (!byId.has(id)) throw new Error(`Unknown shot: ${id}`);
    return byId.get(id);
  });
}

/** Fork the selected route (or first match) without mutating the source graph. */
export function addBranch(state, options) {
  if (
    !Array.isArray(state?.shots) ||
    !Array.isArray(state?.edges) ||
    !Array.isArray(state?.routes)
  ) {
    throw new TypeError(
      "A story graph requires shots, edges, and routes arrays.",
    );
  }
  const { shots, edges, routes } = state;
  const { fromId, title, routeId: selectedRouteId } = options ?? {};
  if (typeof title !== "string" || !title.trim())
    throw new Error("Branch title is required.");
  const parent = shots.find((shot) => shot.id === fromId);
  if (!parent) throw new Error(`Unknown parent shot: ${fromId}`);
  const sourceRoute =
    selectedRouteId === undefined
      ? routes.find((route) => route.shotIds.includes(fromId))
      : routes.find((route) => route.id === selectedRouteId);
  if (selectedRouteId !== undefined && !sourceRoute) {
    throw new Error(`Unknown route: ${selectedRouteId}`);
  }
  if (!sourceRoute) throw new Error(`Parent shot has no route: ${fromId}`);
  if (!sourceRoute.shotIds.includes(fromId)) {
    throw new Error(
      `Parent shot ${fromId} is not in route: ${selectedRouteId}`,
    );
  }
  const prefix = sourceRoute.shotIds.slice(
    0,
    sourceRoute.shotIds.indexOf(fromId) + 1,
  );
  getRouteShots(shots, { shotIds: prefix });

  let nextNumber =
    Math.max(
      0,
      ...shots.map((shot) => (/^\d+$/.test(shot.id) ? Number(shot.id) : 0)),
    ) + 1;
  let shotId = String(nextNumber).padStart(2, "0");
  while (shots.some((shot) => shot.id === shotId))
    shotId = String(++nextNumber).padStart(2, "0");
  let routeId = `branch-${shotId}`;
  for (let suffix = 2; routes.some((route) => route.id === routeId); suffix++) {
    routeId = `branch-${shotId}-${suffix}`;
  }
  let edgeId = `${fromId}-${shotId}`;
  for (let suffix = 2; edges.some((edge) => edge.id === edgeId); suffix++) {
    edgeId = `${fromId}-${shotId}-${suffix}`;
  }
  const y = parent.y + 130;
  let x = parent.x + 150;
  while (shots.some((shot) => shot.x === x && shot.y === y)) x += 150;
  const newShot = {
    id: shotId,
    title: title.trim(),
    image: parent.image,
    duration: 3,
    x,
    y,
  };
  return {
    shots: [...shots, newShot],
    edges: [...edges, { id: edgeId, source: fromId, target: shotId }],
    routes: [
      ...routes,
      { id: routeId, name: title.trim(), shotIds: [...prefix, shotId] },
    ],
    routeId,
    shotId,
  };
}
