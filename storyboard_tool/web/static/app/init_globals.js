// Bootstrap globals before the static APP import chain (see main_module.js).
// Uses top-level await so dialogs/canvas_color/scene3d_app load after el exists.

import * as utils from "../core/utils.js";
import { state, dialogState, contextMenuState, canvasColorState } from "../core/state.js";
import { buildEl } from "../core/dom.js";

const el = buildEl();
Object.assign(globalThis, utils, { state, dialogState, contextMenuState, canvasColorState, el });

import * as dispatch from "../core/dispatch.js";
import * as api from "../core/api.js";
Object.assign(globalThis, dispatch, api);

const [dialogs, canvasColor, scene3dApp] = await Promise.all([
  import("../dialogs.js"),
  import("../canvas_color.js"),
  import("../scene3d_app.js"),
]);

Object.assign(globalThis, dialogs, canvasColor, scene3dApp);
