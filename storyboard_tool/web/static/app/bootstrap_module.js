// ES module bootstrap: Layer2 core (utils/state/dom) plus migrated leaf modules.
// Bridges exports to globalThis for classic APP_SCRIPTS. main.js waits on
// __bootstrapModuleReady before loading any classic script.

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
globalThis.__bootstrapModuleReady = true;
