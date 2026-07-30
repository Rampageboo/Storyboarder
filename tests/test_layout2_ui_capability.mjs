import assert from "node:assert/strict";
import test from "node:test";

import { canConvertProjectToLayout2 } from "../frontend/src/projectCapabilities.ts";

test("Convert visibility follows the backend capability", () => {
  assert.equal(canConvertProjectToLayout2(null), false);
  assert.equal(canConvertProjectToLayout2({ can_convert_to_layout2: false }), false);
  assert.equal(canConvertProjectToLayout2({ can_convert_to_layout2: true }), true);
  assert.equal(canConvertProjectToLayout2({ layout: 1 }), false);
});
