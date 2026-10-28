/* Run with NODE_PATH pointing to a Playwright installation. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const out = path.resolve('logs/web-review-qa');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless:true,
    ...(process.env.WEB_BROWSER_EXECUTABLE ? {executablePath:process.env.WEB_BROWSER_EXECUTABLE} : {})});
  try {
    for (const [name,width,height] of [['phone',390,844],['ipad',820,1180],['desktop',1440,1000]]) {
      const context = await browser.newContext({viewport:{width,height},deviceScaleFactor:1});
      const page = await context.newPage();
      const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.goto(process.env.WEB_REVIEW_URL || 'http://127.0.0.1:8081/',{waitUntil:'domcontentloaded'});
      await page.locator('#daily-view h1').waitFor({timeout:60000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${name}: horizontal overflow`);
      await page.screenshot({path:path.join(out,`${name}-daily.png`),fullPage:true});
      await page.locator('.tabs [data-tab="watch"]').click();
      await page.locator('#stock-code').fill('605287');
      await page.locator('#watch-form button').click();
      assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('stock-review.watch.v1'))[0]),'605287');
      await page.reload();
      await page.locator('#daily-view h1').waitFor({timeout:60000});
      assert.equal(await page.locator('#watch-count').innerText(),'1');
      await page.locator('.tabs [data-tab="watch"]').click();
      await page.locator('#watch-view .stock-link').click();
      await page.locator('#stock-content .stock-hero').waitFor({timeout:60000});
      await page.locator('#price-chart canvas').first().waitFor({timeout:15000});
      await page.waitForTimeout(300);
      const nonblank=await page.locator('#price-chart canvas').evaluateAll(canvases=>canvases.some(canvas=>{
        const ctx=canvas.getContext('2d'); if(!ctx)return false;
        const {data}=ctx.getImageData(0,0,canvas.width,canvas.height);let colors=0;
        for(let i=0;i<data.length;i+=16)if(data[i+3]>0 && Math.max(data[i],data[i+1],data[i+2])-Math.min(data[i],data[i+1],data[i+2])>30)colors++;
        return colors>30;
      }));
      assert.ok(nonblank,`${name}: chart blank`);
      assert.equal(await page.locator('#stock-dialog').evaluate(el=>el.scrollWidth>el.clientWidth),false);
      await page.screenshot({path:path.join(out,`${name}-stock.png`)});
      await page.locator('#close-stock').click();
      await page.locator('.tabs [data-tab="performance"]').click();
      await page.locator('#performance-view h1').waitFor({timeout:60000});
      await page.screenshot({path:path.join(out,`${name}-performance.png`),fullPage:true});
      await page.locator('#report-date').selectOption('20260626');
      await page.locator('.tabs [data-tab="daily"]').click();
      await page.locator('#daily-view .overview .eyebrow').filter({hasText:'2026-06-26'}).waitFor({timeout:60000});
      assert.ok((await page.locator('.mode').innerText()).includes('暂停新增推荐'));
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:path.join(out,`${name}-historical.png`),fullPage:true});
      assert.deepEqual(errors,[],`${name}: browser errors`);
      console.log(`${name}: layout, watch persistence, nonblank chart, strategy view, date switch passed`);
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
