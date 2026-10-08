// Scoped geometry verification. Uses the project's installed TypeScript compiler.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')

const source = fs.readFileSync(path.join(__dirname, '../frontend/src/utils/comicLayout.ts'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const context = { exports: {} }
vm.runInNewContext(compiled, context)
const { resizePanel, splitPanel, snapCoordinate, comicGridSize } = context.exports
const plain = value => JSON.parse(JSON.stringify(value))
let checks = 0
const equal = (actual, expected) => { assert.deepEqual(plain(actual), expected); checks++ }
const rect = { x: 100, y: 150, width: 200, height: 300 }
const page = { width: 640, height: 960 }
for (const handle of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']) {
  const expected = {
    x: handle.includes('w') ? 110 : 100,
    y: handle.includes('n') ? 170 : 150,
    width: handle.includes('w') ? 190 : handle.includes('e') ? 210 : 200,
    height: handle.includes('n') ? 280 : handle.includes('s') ? 320 : 300,
  }
  equal(resizePanel(rect, handle, 10, 20, page), expected)
}
equal(resizePanel(rect, 'nw', -10000, -10000, page), { x: 0, y: 0, width: 300, height: 450 })
equal(resizePanel(rect, 'se', 10000, 10000, page), { x: 100, y: 150, width: 540, height: 810 })
equal(resizePanel(rect, 'nw', 10000, 10000, page), { x: 284, y: 434, width: 16, height: 16 })
equal(resizePanel(rect, 'se', -10000, -10000, page), { x: 100, y: 150, width: 16, height: 16 })
equal(resizePanel(rect, 'e', 10.4, 0, page), { x: 100, y: 150, width: 210, height: 300 })
equal(splitPanel(rect, 'horizontal', 24, 'ltr'), [
  { x: 100, y: 150, width: 200, height: 138 },
  { x: 100, y: 312, width: 200, height: 138 },
])
const halves = [
  { x: 100, y: 150, width: 88, height: 300 },
  { x: 212, y: 150, width: 88, height: 300 },
]
equal(splitPanel(rect, 'vertical', 24, 'ltr'), halves)
equal(splitPanel(rect, 'vertical', 24, 'rtl'), [...halves].reverse())
equal(splitPanel({ x: 0, y: 0, width: 201, height: 201 }, 'vertical', 24, 'ltr'), [
  { x: 0, y: 0, width: 88, height: 201 },
  { x: 112, y: 0, width: 89, height: 201 },
])
equal(splitPanel({ ...rect, width: 55 }, 'vertical', 24, 'ltr'), null)
equal(splitPanel({ ...rect, height: 55 }, 'horizontal', 24, 'rtl'), null)
equal(splitPanel({ ...rect, width: 56 }, 'vertical', 24, 'ltr'), [
  { x: 100, y: 150, width: 16, height: 300 },
  { x: 140, y: 150, width: 16, height: 300 },
])
equal(comicGridSize, 24)
equal(snapCoordinate(35, true), 24)
equal(snapCoordinate(36, true), 48)
equal(snapCoordinate(35.4, false), 35)
equal(snapCoordinate(35.6, false), 36)
console.log(`${checks} comic geometry checks passed`)
