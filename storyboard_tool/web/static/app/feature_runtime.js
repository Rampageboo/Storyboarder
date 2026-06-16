// Shared runtime for feature ES modules loaded after init_globals.js.

export { state, dialogState, contextMenuState, canvasColorState } from "../core/state.js";

/** Always reads current DOM refs from globalThis.el (avoids stale/null snapshots). */
export const el = new Proxy(
  {},
  {
    get(_target, prop) {
      if (prop === "then") return undefined;
      const dom = globalThis.el;
      if (!dom || typeof prop !== "string") return undefined;
      const value = dom[prop];
      return typeof value === "function" ? value.bind(dom) : value;
    },
  }
);

/** Lazy access to functions published on globalThis by prior scripts. */
export const $ = new Proxy(Object.create(null), {
  get(_target, prop) {
    if (prop === "then") return undefined;
    return globalThis[prop];
  },
});
