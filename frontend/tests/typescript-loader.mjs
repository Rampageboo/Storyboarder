// Use the application's existing TypeScript dependency; no test framework or build output.
import { readFile } from 'node:fs/promises'
import ts from 'typescript'
export async function load(url, context, nextLoad) {
  if (!url.endsWith('.ts')) return nextLoad(url, context)
  const source = await readFile(new URL(url), 'utf8')
  return { format: 'module', shortCircuit: true, source: ts.transpileModule(source,
    { compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext } }).outputText }
}
