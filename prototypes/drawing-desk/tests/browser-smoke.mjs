import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium } from 'file:///C:/Users/JieYin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const qa = path.join(root, '.qa');
await mkdir(qa, { recursive: true });
const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
const context = await browser.newContext({ viewport: { width: 1487, height: 1058 }, acceptDownloads: true });
const page = await context.newPage();
const errors = [];
const results = [];
page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
page.on('console', message => { if (message.type() === 'error') errors.push(`console: ${message.text()} (${message.location().url})`); });
page.on('response', response => { if (response.status() >= 400) errors.push(`HTTP ${response.status()}: ${response.url()}`); });
const go = async () => {
  await page.goto('http://127.0.0.1:4173/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => !document.querySelector('.drawing-canvas-notice'));
};
const ink = () => page.locator('.drawing-canvas-ink').evaluate(canvas => canvas.toDataURL());
const background = () => page.locator('.drawing-canvas-background').evaluate(canvas => canvas.toDataURL());
const selected = () => page.locator('.route-card[aria-current="true"]').getAttribute('aria-label');
const routeIds = () => page.locator('.route-card b').allTextContents();
async function check(name, fn) {
  try { await go(); await fn(); results.push({ name, passed: true }); console.log(`PASS ${name}`); }
  catch (error) { results.push({ name, passed: false, error: error.stack }); console.error(`FAIL ${name}: ${error.message}`); await page.screenshot({ path: path.join(qa, `failure-${results.length}.png`), fullPage: true }); }
}

try {
  await check('initial UI and reference-size screenshots', async () => {
    assert.match(await selected(), /镜头 06/);
    assert.equal(await page.getByRole('combobox', { name: '当前路线' }).inputValue(), 'main');
    assert.equal(await page.locator('.shot-node').count(), 10);
    assert.deepEqual(await routeIds(), ['01', '02', '06', '07', '10']);
    await page.waitForTimeout(750);
    await page.screenshot({ path: path.join(qa, 'initial-v3.png'), fullPage: true });
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.waitForTimeout(750);
    await page.screenshot({ path: path.join(qa, 'desktop1366-v3.png'), fullPage: true });
    await page.setViewportSize({ width: 900, height: 900 });
    await page.waitForTimeout(750);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'no horizontal document overflow at 900px');
    await page.screenshot({ path: path.join(qa, 'narrow-v3.png'), fullPage: true });
    await page.setViewportSize({ width: 1487, height: 1058 });
    await page.getByRole('navigation', { name: '工作区' }).getByRole('button', { name: '地图', exact: true }).click();
    await page.waitForTimeout(750);
    await page.screenshot({ path: path.join(qa, 'map-v3.png'), fullPage: true });
  });

  await check('canvas real stroke, undo, redo and per-shot preservation', async () => {
    const blank = await ink();
    const box = await page.locator('.drawing-canvas-ink').boundingBox();
    await page.mouse.move(box.x + box.width * .25, box.y + box.height * .5);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * .65, box.y + box.height * .6, { steps: 15 });
    await page.mouse.up();
    const drawn = await ink();
    assert.notEqual(drawn, blank, 'stroke changes rendered canvas pixels');
    assert.match(await page.locator('.canvas-status').innerText(), /1 笔/);
    await page.getByRole('button', { name: '撤销笔迹', exact: true }).click();
    assert.equal(await ink(), blank);
    await page.getByRole('button', { name: '重做笔迹', exact: true }).click();
    assert.equal(await ink(), drawn);
    await page.getByRole('button', { name: /选择镜头 07/ }).click();
    assert.equal(await ink(), blank);
    await page.getByRole('button', { name: /选择镜头 06/ }).click();
    assert.equal(await ink(), drawn);
  });

  await check('alternate route and branch-at-merge preserve selected prefix', async () => {
    await page.getByRole('combobox', { name: '当前路线' }).selectOption('alternate');
    assert.deepEqual(await routeIds(), ['01', '02', '08', '09', '10']);
    await page.getByRole('button', { name: /选择镜头 10/ }).click();
    await page.getByRole('button', { name: '新建分支', exact: true }).click();
    await page.getByRole('textbox', { name: '新分支名称' }).fill('浏览器验证分支');
    await page.getByRole('button', { name: '创建分支', exact: true }).click();
    assert.deepEqual(await routeIds(), ['01', '02', '08', '09', '10', '11']);
    assert.match(await selected(), /镜头 11/);
    await page.getByRole('combobox', { name: '当前路线' }).selectOption('main');
    assert.deepEqual(await routeIds(), ['01', '02', '06', '07', '10']);
  });

  await check('graph click and keyboard selection plus per-shot prompt ownership', async () => {
    const prompt = page.getByRole('textbox', { name: '创意提示词' });
    const initial = await prompt.inputValue();
    await prompt.fill('镜头06专属测试提示词');
    await page.getByRole('button', { name: /选择故事镜头 08/ }).click();
    assert.match(await selected(), /镜头 08/);
    assert.equal(await page.getByRole('combobox', { name: '当前路线' }).inputValue(), 'alternate');
    assert.notEqual(await prompt.inputValue(), '镜头06专属测试提示词');
    await prompt.fill('镜头08专属测试提示词');
    await page.getByRole('button', { name: /选择故事镜头 06/ }).focus();
    await page.keyboard.press('Enter');
    assert.match(await selected(), /镜头 06/);
    assert.equal(await prompt.inputValue(), '镜头06专属测试提示词');
    await page.getByRole('button', { name: /选择故事镜头 07/ }).focus();
    await page.keyboard.press('Space');
    assert.match(await selected(), /镜头 07/);
    assert.notEqual(await prompt.inputValue(), '镜头06专属测试提示词');
    assert.notEqual(await prompt.inputValue(), '镜头08专属测试提示词');
    await page.getByRole('button', { name: /选择故事镜头 08/ }).click();
    assert.equal(await prompt.inputValue(), '镜头08专属测试提示词');
  });

  await check('graph drag changes placement without changing route order', async () => {
    const ids = await routeIds();
    await page.getByRole('navigation', { name: '工作区' }).getByRole('button', { name: '地图', exact: true }).click();
    await page.waitForTimeout(300);
    const node = page.locator('.react-flow__node[data-id="06"]');
    const before = await node.evaluate(el => el.style.transform);
    const box = await node.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 65, box.y + box.height / 2 + 25, { steps: 12 });
    await page.mouse.up();
    assert.notEqual(await node.evaluate(el => el.style.transform), before);
    assert.deepEqual(await routeIds(), ids);
    const after = await node.evaluate(el => el.style.transform);
    await page.getByRole('button', { name: /选择镜头 07/ }).click();
    assert.equal(await node.evaluate(el => el.style.transform), after, 'node location persists through shot selection');
    assert.deepEqual(await routeIds(), ids);
  });

  await check('playback progression, pause and stop on shot selection', async () => {
    await page.getByRole('button', { name: /选择镜头 01/ }).click();
    await page.getByRole('button', { name: '播放路线', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.route-card[aria-current="true"]')?.getAttribute('aria-label')?.includes('镜头 02'), { timeout: 5000 });
    await page.getByRole('button', { name: '暂停', exact: true }).click();
    const paused = await selected();
    await page.waitForTimeout(2300);
    assert.equal(await selected(), paused);
    await page.getByRole('button', { name: '播放路线', exact: true }).click();
    await page.getByRole('button', { name: /选择镜头 07/ }).click();
    assert.equal(await page.getByRole('button', { name: '暂停', exact: true }).count(), 0);
    await page.waitForTimeout(3200);
    assert.match(await selected(), /镜头 07/);
  });

  await check('candidate adoption, visibility and per-shot layer ownership', async () => {
    const original = await background();
    await page.locator('.candidate').nth(1).getByRole('button').click();
    await page.waitForFunction(() => !document.querySelector('.drawing-canvas-notice'));
    const accepted = await background();
    assert.notEqual(accepted, original);
    assert.equal(await page.locator('.candidate.accepted').count(), 1);
    await page.getByRole('tab', { name: '图层', exact: true }).click();
    await page.getByRole('button', { name: '切换采纳图层可见性' }).click();
    await page.waitForFunction(() => !document.querySelector('.drawing-canvas-notice'));
    assert.equal(await background(), original);
    await page.getByRole('button', { name: '切换草图可见性' }).click();
    await page.waitForFunction(() => !document.querySelector('.drawing-canvas-notice'));
    const hidden = await background();
    assert.notEqual(hidden, original);
    await page.getByRole('button', { name: '切换采纳图层可见性' }).click();
    await page.waitForFunction(() => !document.querySelector('.drawing-canvas-notice'));
    assert.equal(await background(), accepted);
    await page.getByRole('button', { name: /选择镜头 01/ }).click();
    assert.equal(await page.getByRole('button', { name: '切换采纳图层可见性' }).isDisabled(), true);
    await page.getByRole('button', { name: /选择镜头 06/ }).click();
    await page.waitForFunction(() => !document.querySelector('.drawing-canvas-notice'));
    assert.equal(await background(), accepted);
  });

  await check('pausing on the final shot retains that shot', async () => {
    await page.getByRole('button', { name: /选择镜头 07/ }).click();
    await page.getByRole('button', { name: '播放路线', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.route-card[aria-current="true"]')?.getAttribute('aria-label')?.includes('镜头 10'));
    await page.getByRole('button', { name: '暂停', exact: true }).click();
    assert.match(await selected(), /镜头 10/);
    await page.waitForTimeout(500);
    assert.match(await selected(), /镜头 10/);
  });

  await check('import pauses playback and keeps the initiating shot as candidate owner', async () => {
    await page.getByRole('button', { name: '播放路线', exact: true }).click();
    const choosing = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: '导入', exact: true }).click();
    const chooser = await choosing;
    await page.waitForTimeout(4300);
    assert.match(await selected(), /镜头 06/);
    assert.equal(await page.getByRole('button', { name: '暂停', exact: true }).count(), 0);
    await chooser.setFiles(path.join(root, 'public/assets/train.png'));
    await page.waitForFunction(() => document.querySelectorAll('.candidate').length === 3);
    assert.match(await page.locator('.candidate').last().innerText(), /train.png/);
    await page.getByRole('button', { name: /选择镜头 07/ }).click();
    assert.equal(await page.locator('.candidate').count(), 2);
    await page.getByRole('button', { name: /选择镜头 06/ }).click();
    assert.equal(await page.locator('.candidate').count(), 3);
  });

  await check('PNG download is a real full-resolution image', async () => {
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: '导出当前画面 PNG' }).click();
    const download = await downloading;
    assert.equal(download.suggestedFilename(), 'storyboard-06.png');
    const destination = path.join(qa, download.suggestedFilename());
    await download.saveAs(destination);
    const png = await readFile(destination);
    assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    assert.equal(png.readUInt32BE(16), 1672);
    assert.equal(png.readUInt32BE(20), 941);
    assert.ok(png.length > 10000);
  });

  await check('modal focus containment, Escape and focus restoration', async () => {
    const trigger = page.getByRole('button', { name: '生成候选', exact: true });
    await trigger.click();
    const dialog = page.getByRole('dialog');
    assert.equal(await dialog.count(), 1);
    assert.ok(await dialog.evaluate(el => el.contains(document.activeElement)), 'opening modal moves focus inside');
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab');
      assert.ok(await dialog.evaluate(el => el.contains(document.activeElement)), 'Tab stays within modal');
    }
    await page.keyboard.press('Escape');
    assert.equal(await dialog.count(), 0);
    assert.ok(await trigger.evaluate(el => el === document.activeElement), 'Escape restores original trigger focus');
    await page.getByRole('button', { name: '新建分支', exact: true }).click();
    assert.ok(await page.getByRole('textbox', { name: '新分支名称' }).evaluate(el => el === document.activeElement));
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog').count(), 0);
  });

  results.push({ name: 'browser page, console and HTTP errors', passed: errors.length === 0, errors });
  console.log(`${errors.length ? 'FAIL' : 'PASS'} browser page, console and HTTP errors: ${errors.length}`);
} finally {
  await writeFile(path.join(qa, 'browser-smoke-results.json'), JSON.stringify({ results }, null, 2));
  await browser.close();
}
console.log(`${results.filter(result => result.passed).length}/${results.length} browser checks passed`);
if (results.some(result => !result.passed)) process.exitCode = 1;
