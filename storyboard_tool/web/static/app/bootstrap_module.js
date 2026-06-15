// ES module bootstrap: load migrated leaf modules and bridge exports to globalThis
// for classic APP_SCRIPTS. Runs in parallel with main.js; main.js waits on
// __bootstrapModuleReady before core/canvas_size.js and app.js.

import * as dialogs from "../dialogs.js";
import * as canvasColor from "../canvas_color.js";
import * as scene3dApp from "../scene3d_app.js";

Object.assign(globalThis, dialogs, canvasColor, scene3dApp);
globalThis.__bootstrapModuleReady = true;
