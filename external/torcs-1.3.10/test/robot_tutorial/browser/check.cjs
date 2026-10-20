// Copyright (C) 2026 Bernhard Wymann. GPL-2.0-or-later.
// Offline rendering and real clipboard checks against freshly generated documentation.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {pathToFileURL} = require('node:url');
const {parseArgs} = require('node:util');
const {createHash} = require('node:crypto');
const {values} = parseArgs({options: {html: {type: 'string'}, 'work-root': {type: 'string'}, help: {type: 'boolean'}}});
if (values.help || !values.html || !values['work-root']) {
  console.log('Usage: node check.cjs --html <fresh Doxygen output> --work-root <existing artifact parent>');
  process.exit(values.help ? 0 : 2);
}
const output = fs.realpathSync(values.html);
const work = fs.mkdtempSync(path.join(fs.realpathSync(values['work-root']), 'browser-'));
const source = path.resolve(__dirname, '../../../src/doc/robot_tutorial');
const hashFile = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const report = {status: 'running', html: output, pages: [], copies: 0, inputs: {},
  checker: hashFile(__filename), lockfile: hashFile(path.join(__dirname, 'package-lock.json'))};
const normalize = text => text.replace(/\s+/g, ' ').trim();
const server = http.createServer((req, res) => {
  try {
    const target = path.resolve(output, '.' + decodeURIComponent(new URL(req.url, 'http://localhost').pathname));
    assert(target.startsWith(output + path.sep));
    const types = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg'};
    res.setHeader('Content-Type', types[path.extname(target)] || 'application/octet-stream');
    res.end(fs.readFileSync(target));
  } catch { res.statusCode = 404; res.end(); }
});

(async () => {
  let browser;
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch();
    const context = await browser.newContext({permissions: ['clipboard-read', 'clipboard-write']});
    const page = await context.newPage();
    const external = [], errors = [];
    await page.route(/^https?:/, route => {
      if (route.request().url().startsWith(base + '/')) return route.continue();
      external.push(route.request().url());
      return route.abort();
    });
    page.on('pageerror', error => errors.push(error.message));
    for (const name of fs.readdirSync(source).filter(n => n.endsWith('.md')).sort()) {
      const text = fs.readFileSync(path.join(source, name), 'utf8');
      const anchor = text.match(/^# .*?\{#([^}]+)\}/m)[1];
      const file = anchor + '.html';
      report.inputs[file] = hashFile(path.join(output, file));
      report.inputs[name] = hashFile(path.join(source, name));
      // First load over file://, with every network origin blocked except our unused test server.
      await page.goto(pathToFileURL(path.join(output, file)).href);
      if (/\\f[$\[{]/.test(text)) {
        await page.waitForFunction(() => window.MathJax?.startup?.document && document.querySelector('mjx-container'));
        await page.evaluate(() => MathJax.startup.promise);
        assert(await page.locator('mjx-container[jax="SVG"]').count() > 0, file);
      }
      assert.equal(await page.locator('[data-mml-node="merror"]').count(), 0, file);
      await page.waitForFunction(() => [...document.querySelectorAll('.contents img')].every(i => i.complete && i.naturalWidth > 0));
      for (const frame of page.frames().filter(f => f.url().endsWith('.svg'))) await frame.waitForSelector('svg');
      for (const width of [1280, 1024]) {
        await page.setViewportSize({width, height: 1000});
        const overflow = await page.locator('.contents .formula-card, .contents object, .contents img, .contents .formulaDsp mjx-container').evaluateAll(items => items.filter(e =>
          e.getBoundingClientRect().width > e.closest('.contents').getBoundingClientRect().width + 1 ||
          (e.classList.contains('formula-card') && e.scrollWidth > e.clientWidth + 1)).map(e => e.outerHTML.slice(0, 160)));
        assert.deepEqual(overflow, [], file + ' overflow at ' + width);
      }
      const expected = [...text.matchAll(/```[^\n]*\n([\s\S]*?)```/g)].map(m => m[1]);
      if (expected.length) {
        assert.equal(await page.locator('.contents .fragment .clipboard').count(), expected.length, file + ' file:// buttons');
        await page.goto(base + '/' + file);
        const buttons = page.locator('.contents .fragment .clipboard');
        await buttons.first().waitFor();
        assert.equal(await buttons.count(), expected.length, file);
        for (let i = 0; i < expected.length; ++i) {
          // Clear it first: an old clipboard value must never satisfy a new copy check.
          await page.evaluate(() => navigator.clipboard.writeText(''));
          await buttons.nth(i).click();
          await page.waitForFunction(() => navigator.clipboard.readText().then(text => text.length > 0));
          assert.equal(normalize(await page.evaluate(() => navigator.clipboard.readText())), normalize(expected[i]), name + ' block ' + i);
          report.copies++;
        }
      }
      assert.deepEqual(external, [], file + ' external dependency');
      assert.deepEqual(errors, [], file + ' JavaScript errors');
      report.pages.push(file);
      console.log('PASS:', file);
    }
    // Shared header changes must also preserve formulas in the existing API.
    for (const file of ['class_discrete_policy.html', '_math_functions_8h.html']) {
      await page.goto(pathToFileURL(path.join(output, file)).href);
      await page.waitForFunction(() => window.MathJax?.startup?.document && document.querySelector('mjx-container'));
      await page.evaluate(() => MathJax.startup.promise);
      assert(await page.locator('mjx-container[jax="SVG"]').count() > 0, file);
      assert.equal(await page.locator('[data-mml-node="merror"]').count(), 0, file);
    }
    // Actual navigation, including the API entry and student rebuild loop.
    await page.goto(base + '/robot_tutorial.html');
    await page.locator('.contents a[href="robot_tutorial_setup.html"]').last().click();
    await page.locator('.contents a[href="robot_tutorial_linux.html"]').click();
    await page.locator('.contents a').filter({hasText: 'Chapter 1'}).click();
    await page.locator('.contents a').filter({hasText: 'Rebuild on Linux'}).click();
    assert(page.url().endsWith('robot_tutorial_linux.html#robot_tutorial_linux_rebuild'));
    await page.locator('.contents a[href="robot_tutorial.html#robot_tutorial_feedback"]').first().click();
    assert(page.url().endsWith('robot_tutorial.html#robot_tutorial_feedback'));
    for (const file of ['texture-pit-scene-hires.png', 'multi-scene-hires.png']) assert(fs.existsSync(path.join(output, file)));
    for (const name of fs.readdirSync(path.join(source, 'images')).filter(n => n.endsWith('.svg'))) {
      await page.goto(pathToFileURL(path.join(source, 'images', name)).href);
      const outside = await page.locator('text').evaluateAll(nodes => nodes.filter(n => {
        const r = n.getBoundingClientRect(), s = n.ownerSVGElement.getBoundingClientRect();
        return r.left < s.left - 1 || r.right > s.right + 1 || r.top < s.top - 1 || r.bottom > s.bottom + 1;
      }).map(n => n.textContent));
      assert.deepEqual(outside, [], name + ' text outside SVG');
      if (name === 'speed-profile.svg') await page.screenshot({path: path.join(work, 'speed-profile.png')});
    }
    assert.deepEqual(external, []);
    assert.deepEqual(errors, []);
    report.status = 'passed';
    console.log(`PASS: ${report.pages.length} pages; ${report.copies} actual clipboard copies; offline math, layouts, navigation and SVG bounds.`);
  } catch (error) {
    report.status = 'failed'; report.error = String(error); process.exitCode = 1; console.error(error);
  } finally {
    if (browser) await browser.close();
    server.close();
    fs.writeFileSync(path.join(work, 'report.json'), JSON.stringify(report, null, 2));
    console.log('Artifacts:', work);
  }
})();
