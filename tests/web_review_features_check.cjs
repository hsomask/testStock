/* Synthetic presentation coverage. Does not create production report artifacts. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.WEB_BROWSER_EXECUTABLE});
  fs.mkdirSync('logs/web-review-qa',{recursive:true});
  try{
    for(const [name,width,height] of [['phone',390,844],['ipad',820,1180]]){
      const context=await browser.newContext({viewport:{width,height}});
      const page=await context.newPage();const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/api/**',async route=>{
        const response=await route.fetch();const type=response.headers()['content-type']||'';
        if(!type.includes('application/json'))return route.fulfill({response});
        const value=await response.json();const url=route.request().url();
        if(url.endsWith('/api/dates'))value.publication={trade_date:'20261028',status:'failed'};
        if(url.includes('/api/daily/')){
          const event={id:'fixture',title:'半导体行业消息（测试样例）',source:'测试来源',
            url:'https://example.com/evidence',published_at:'2026-10-21T16:00:00+08:00',
            late_collected:true,after_close:true,association:'仅为测试线索，不代表因果'};
          value.market_events=[event];value.market_events_status='available';
          value.themes=[{name:'半导体',level:'观察',reasons:['板块承接需核对'],events:[event]}];
          value.interpretation={status:'available',market_read:{width_impact:'测试：市场宽度需要结合涨跌家数判断',
            profit_detail:'测试：短线活跃不等于所有股票都上涨'},risk_board:['测试风险']};
        }
        if(url.includes('/api/strategies/'))value.correction={status:'available',summary:{total:12,downgraded:8,
          kept_candidate:4,pit_avoided:3,false_negative:2,downgraded_avg_return:-.01,kept_candidate_avg_return:.02,
          sample_status:'样本不足'},window_dates:['20261020','20261021'],min_coverage:.9,
          note:'测试审计，不代表因果改善或实盘收益',by_reason:[{reason_group:'追高风险',sample_count:8,avg_next_1d_return:-.01}],
          by_version:[{version:'fixture-v1',sample_count:12}],generated_at:'2026-10-22T21:00:00'};
        await route.fulfill({response,json:value});
      });
      await page.goto((process.env.WEB_REVIEW_URL||'http://127.0.0.1:8081/')+'?date=20260626');
      await page.getByRole('heading',{name:'怎样理解今天的行情'}).waitFor({timeout:60000});
      assert.equal(await page.locator('#report-date').inputValue(),'20260626');
      assert.match(await page.locator('#notice').textContent(), /更新失败.*最近已发布报告/);
      await page.getByRole('heading',{name:'市场发生了什么'}).waitFor();
      assert.ok(await page.getByText('事后补充证据',{exact:false}).count()>0);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:`logs/web-review-qa/${name}-features-fixture.png`,fullPage:true});
      await page.locator('[data-tab="performance"]').first().click();
      await page.getByRole('heading',{name:'纠偏复盘'}).waitFor({timeout:60000});
      assert.ok(await page.getByText('样本不足',{exact:false}).count()>0);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:`logs/web-review-qa/${name}-correction-fixture.png`,fullPage:true});
      await page.route('**/api/daily/*', async route=>{
        const response=await route.fetch();
        const value=await response.json();
        value.market_events=[];value.market_events_status='expired';
        await route.fulfill({response,json:value});
      });
      await page.reload();
      await page.getByText('新闻缓存已过期（仅保留7个自然日），不以新消息替代历史证据。',{exact:true}).waitFor({timeout:60000});
      assert.deepEqual(errors,[]);await context.close();
      console.log(`${name}: interpretation, market sources, correction, dated email link passed (synthetic fixtures)`);
    }
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
