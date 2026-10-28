/* Public data stays read-only; personal watch codes stay in this browser. */
"use strict";
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const finite = (v) => typeof v === "number" && Number.isFinite(v);
const fmt = (v, n=0) => finite(v) ? v.toLocaleString("zh-CN", {minimumFractionDigits:n, maximumFractionDigits:n}) : "—";
const pct = (v) => finite(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}%` : "—";
const dateLabel = (d) => /^\d{8}$/.test(d || "") ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}` : d || "—";
const trendClass = (v) => finite(v) ? (v>0 ? "up" : v<0 ? "down" : "") : "";
const icon = (name) => `<i data-lucide="${name}"></i>`;
const storageKey = "stock-review.watch.v1";
const state = {day:null,data:null,tab:"daily",watch:[],request:0,stockRequest:0,chart:null,stockCode:null};
const trackingText = {continued:"层级延续",layer_changed:"层级变化",not_selected:"未再次入选",new:"本日入选",unknown:"连续性待核验"};
function icons(){window.lucide?.createIcons();}
function notice(message=""){ $("#notice").textContent=message; $("#notice").hidden=!message; }
function loadWatch(){
  try { const raw=JSON.parse(localStorage.getItem(storageKey)||"[]"); state.watch=Array.isArray(raw)? [...new Set(raw.filter(c=>typeof c==="string" && /^\d{6}$/.test(c)))].slice(0,50):[]; }
  catch {state.watch=[];notice("无法读取本地关注名单，当前名单为空。");}
}
function saveWatch(next){
  try {localStorage.setItem(storageKey,JSON.stringify(next));state.watch=next;renderWatch();renderDaily();return true;}
  catch {notice("浏览器未能保存关注名单，请检查存储设置。");return false;}
}
function toggleWatch(code){
  if(!/^\d{6}$/.test(code))return;
  if(!state.watch.includes(code)&&state.watch.length>=50){notice("关注名单最多保留50只。");return;}
  saveWatch(state.watch.includes(code)?state.watch.filter(c=>c!==code):[...state.watch,code]);
  document.querySelectorAll(`[data-watch="${code}"]`).forEach(button=>{
    button.classList.toggle("saved",state.watch.includes(code));
    button.setAttribute("aria-pressed",String(state.watch.includes(code)));
    button.title=state.watch.includes(code)?"取消关注":"加入关注";
    button.setAttribute("aria-label",button.title);
  });
}
async function api(path){
  const response=await fetch(path,{signal:AbortSignal.timeout(45000)});
  const value=await response.json();
  if(!response.ok)throw new Error(value.message||"数据暂不可用");
  return value;
}
function stockCard(row){
  const saved=state.watch.includes(row.code), ref=!!row.reference_only;
  return `<article class="stock"><div class="stock-head"><button class="stock-link" data-stock="${esc(row.code)}"><strong>${esc(row.name||row.code)}</strong><small>${esc(row.code)} · ${esc(row.primary_direction||"方向未记录")}</small></button><div class="stock-price ${trendClass(row.pct_chg)}"><b>${fmt(row.close,2)}</b><small>${pct(row.pct_chg)}${ref?" · 历史":""}</small></div><button class="icon ${saved?"saved":""}" data-watch="${esc(row.code)}" title="${saved?"取消关注":"加入关注"}" aria-label="${saved?"取消关注":"加入关注"}" aria-pressed="${saved}">${icon("star")}</button></div>
  <div class="stock-tags"><span>${esc(trackingText[row.tracking_state]||row.source_layer||"个人关注")}</span><span>${esc(row.board_scope==="research_only"?"创业板 · 当前不可交易":row.source_layer||"待核验")}</span>${saved?"<span>已关注</span>":""}</div>
  <p class="stock-reason">${esc(row.display_reason||row.reason||row.entry_reason||"查看行情与历次判断。")}</p>
  <div class="stock-bottom"><span>${esc((row.strategies||[row.strategy]).filter(Boolean).join(" / ")||"未记录系统策略")}</span><button class="text-button" data-stock="${esc(row.code)}">看依据 ${icon("arrow-up-right")}</button></div></article>`;
}
function sectionTitle(title, symbol, suffix=""){return `<div class="section-head"><h2 class="section-title">${icon(symbol)}${title}</h2>${suffix}</div>`;}
function eventList(events){
  return `<ul class="evidence-list">${events.map(e=>`<li><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ${icon("external-link")}</a><p>${esc(e.source)} · ${esc(e.published_at.slice(0,16).replace("T"," "))}${e.after_close?" · 盘后发布，不解释当日盘中走势":""}${e.late_collected?" · 事后补充证据":""}</p><p>${esc(e.association)}</p></li>`).join("")}</ul>`;
}
function correctionSection(c){
  if(c?.status!=="available")return `<h2>纠偏复盘</h2><p class="empty">所选日期没有可用的纠偏审计，不用其他日期代替。</p>`;
  c={...c,note:[c.comparison_note,c.note].filter(Boolean).join(" ")};
  const s=c.summary||{}, ret=v=>pct(finite(v)?v*100:null);
  return `<h2>纠偏复盘</h2><p class="source-note">${esc(c.note)}</p><p>样本 ${fmt(s.total)} · 原审计样本标记：${esc(s.sample_status||"未记录")} · 最低覆盖要求 ${finite(c.min_coverage)?fmt(c.min_coverage*100)+"%":"未记录"}</p><div class="table-wrap"><table><thead><tr><th>分组</th><th>样本</th><th>平均T+1</th></tr></thead><tbody><tr><td>被降级</td><td>${fmt(s.downgraded)}</td><td>${ret(s.downgraded_avg_return)}</td></tr><tr><td>保留候选</td><td>${fmt(s.kept_candidate)}</td><td>${ret(s.kept_candidate_avg_return)}</td></tr></tbody></table></div><p>原规则标记：避险 ${fmt(s.pit_avoided)} 条；错过机会 ${fmt(s.false_negative)} 条。两者均为事后分类，不是实际交易盈亏。</p><details><summary>降级原因与版本</summary>${c.by_reason.map(r=>`<p>${esc(r.reason_group)} · ${fmt(r.sample_count)} 条 · T+1 ${ret(r.avg_next_1d_return)}</p>`).join("")}${c.by_version.map(r=>`<p>版本 ${esc(r.version)} · ${fmt(r.sample_count)} 条</p>`).join("")}<p>窗口：${c.window_dates.map(dateLabel).map(esc).join("、")||"未记录"}</p><p>产物生成时间：${esc(c.generated_at||"未记录")}，事后补算不能视为当日已知结论。</p></details>`;
}
function renderDaily(){
  if(!state.data)return;
  const d=state.data,m=d.market, up=m.up_count,down=m.down_count;
  const breadth=finite(up)&&finite(down)&&up+down>0;
  const reasonList=Array.isArray(d.restrictions.reasons)?d.restrictions.reasons:[];
  const differences=d.market_changes.map(c=>({up_count:"上涨家数",down_count:"下跌家数",limit_up:"涨停家数",limit_down:"跌停家数"}[c.field]+` ${c.change>0?"+":""}${c.change}`)).join(" · ");
  const watchRows=state.watch.slice(0,6).map(code=>d.tracking.find(r=>r.code===code)||{code});
  const featured=d.featured.filter(r=>!state.watch.includes(r.code));
  const scope=d.market_scope==="candidate_snapshot"?"当前仅有候选快照；全市场宽度和板块榜缺失。":d.market_scope==="missing"?"当日市场摘要尚未取得。":d.market_scope==="partial_market"?"当日市场摘要不完整，缺失项不补写。":"收盘后报告";
  const issues=Array.isArray(d.quality.issues)?d.quality.issues:[];
  $("#daily-view").innerHTML=`<section class="overview"><div class="eyebrow"><span class="dot"></span>${esc(dateLabel(state.day))} · ${esc(scope)}</div><div class="overview-head"><h1>${esc(m.status||"等待市场数据")}</h1><span class="mode">${esc(d.mode.name||"模式待核验")} · ${d.new_recommendations_allowed?"按条件观察":"暂停新增推荐"}</span></div><p class="summary">${esc(m.summary||d.mode.summary||(d.mode.code==="empty"?"已保存的交易模式为空仓。保留历史跟踪，今日不新增推荐。":"已有数据不足以生成完整市场结论。"))}</p>
  <div class="metrics"><div class="metric"><span class="metric-label">市场评分</span><div class="metric-value">${fmt(m.score,1)}<small>原规则评分 / 100</small></div></div><div class="metric"><span class="metric-label">上涨 / 下跌</span><div class="metric-value"><span class="up">${fmt(up)}</span> <span class="quiet">/</span> <span class="down">${fmt(down)}</span></div></div><div class="metric"><span class="metric-label">涨停 / 跌停</span><div class="metric-value"><span class="up">${fmt(m.limit_up)}</span> <span class="quiet">/</span> <span class="down">${fmt(m.limit_down)}</span></div></div><div class="metric"><span class="metric-label">短线情绪</span><div class="metric-value">${esc(d.sentiment.stage||"—")}<small>情绪评分 ${fmt(d.sentiment.score,1)}</small></div></div></div>
  ${breadth?`<div class="breadth"><span class="up">上涨 ${fmt(up)} 家</span><div class="breadth-bar"><div class="breadth-up" style="width:${100*up/(up+down)}%"></div><div class="breadth-down" style="width:${100*down/(up+down)}%"></div></div><span class="down">下跌 ${fmt(down)} 家</span></div>`:""}
  <p class="source-note">${esc(differences?`较 ${dateLabel(d.comparison_date)}：${differences}`:"缺少可比较的相邻交易日全市场摘要，不展示日间增减。")}</p></section>
  <div class="two-columns"><section class="section">${sectionTitle("今天值得注意","scan-eye")}<ul class="evidence-list">${reasonList.length?reasonList.slice(0,3).map(x=>`<li><p>${esc(x)}</p></li>`).join(""):`<li><b>先看行情事实</b><p>${esc(d.market_scope==="full_market"?"市场结构见上方；尚无额外的事件归因证据。":"目前只有候选快照中的市场状态，缺少判断全市场结构的完整数据。")}</p></li>`}<li><b>事件原因尚未确认</b><p>${d.events?.length?"下方消息仅作为核对线索，尚未建立因果关系。":"当日跟踪股票尚无可用消息缓存，不将技术风险提示当作涨跌原因。"}</p></li></ul></section>
  <section class="section">${sectionTitle("板块线索","layers-2")}${d.themes.length?d.themes.slice(0,3).map(t=>`<div class="theme-row"><div class="theme-line"><strong>${esc(t.name)}</strong><small>${esc(t.level)}</small></div><details><summary>展开当日依据</summary><p>${esc(t.beginner_explain)}</p><ul>${(Array.isArray(t.reasons)?t.reasons:[]).map(r=>`<li>${esc(r)}</li>`).join("")}</ul><p>${esc(t.sustainability_risk)}</p>${t.events?.length?`<p>以下标题提及板块名称，仅为检索线索，不是因果归因。</p>${eventList(t.events)}`:"<p class='quiet'>现有资讯中未匹配到板块名称，不代表没有相关事件。</p>"}</details></div>`).join(""):"<p class='empty'>当日板块摘要缺失，暂不从候选股票反推市场主线。</p>"}</section></div>
  <section class="section">${sectionTitle("市场发生了什么","newspaper")}${d.market_events?.length?`${eventList(d.market_events.slice(0,3))}<details><summary>更多市场消息</summary>${eventList(d.market_events.slice(3,10))}</details><p class='source-note'>按发布时间排列的财经快讯，不是影响程度排名；新闻出现不代表它导致了行情变化。</p>`:`<p class='empty'>${d.market_events_status==="expired"?"新闻缓存已过期（仅保留7个自然日），不以新消息替代历史证据。":d.market_events_status==="empty"?"已检索，所选日期范围内没有可用消息。":d.market_events_status==="failed"?"资讯采集失败，行情和原报告仍可阅读。":"所选日期还没有可用的市场资讯缓存。"}</p>`}</section>
  ${d.events?.length?`<section class="section">${sectionTitle("跟踪股票的新闻线索","newspaper")}${eventList(d.events.slice(0,3))}</section>`:""}
  <section class="section">${sectionTitle("我的关注","star",`<button class="text-button" data-tab="watch">管理关注 ${icon("arrow-right")}</button>`)}${watchRows.length?`<div class="stocks">${watchRows.map(stockCard).join("")}</div>`:"<p class='empty'>还没有关注的股票。<button class='text-button' data-tab='watch'>添加股票代码</button></p>"}</section>
  <section class="section">${sectionTitle("系统重点跟踪","radar",`<small>${d.new_recommendations_allowed?"延续跟踪与当日机会":"跟踪复盘 · 非新增推荐"}</small>`)}${featured.length?`<div class="stocks">${featured.map(stockCard).join("")}</div>`:`<p class="empty">${d.new_recommendations_allowed?"暂无符合展示条件的跟踪股票。":"当前没有可延续展示的跟踪记录，今日不新增推荐。"}</p>`}
  <details><summary>完整当日记录 · ${d.candidates.length} 只</summary><p class="quiet">包含观察、条件不满足和回避记录，不等于推荐名单。</p><div class="stocks">${d.candidates.map(stockCard).join("")}</div></details></section>
  <section class="section">${sectionTitle("昨日判断，今天怎样","history")}${d.recap.available?`<div class="recap-grid"><div><strong>${d.recap.continued}</strong><span>最终层级延续</span></div><div><strong>${d.recap.changed}</strong><span>最终层级变化</span></div><div><strong>${d.recap.not_selected}</strong><span>未再次入选</span></div></div><p class="source-note">对比 ${esc(dateLabel(d.comparison_date))}。层级延续不等于逻辑已兑现，未再次入选也不直接等于失效。</p>`:"<p class='empty'>缺少前一交易日记录，暂不统计判断变化。</p>"}</section>
  <section class="section">${sectionTitle("公开明细导出","download")}<div class="stock-actions"><a class="text-button" href="/api/export/${state.day}/md">${icon("file-text")}Markdown 明细</a><a class="text-button" href="/api/export/${state.day}/xlsx">${icon("sheet")}Excel 明细</a></div><p class="source-note">导出本页全部公开候选，不替代原邮件的审计附录和板块趋势Excel。</p></section>
  <details class="section"><summary>数据状态与限制</summary><p>摘要：${esc(d.sources.summary)} · 候选快照：${esc(d.sources.snapshots)} · 决策：${esc(d.decision_status)}</p>${issues.map(x=>`<p>${esc(x)}</p>`).join("")}<p>事件线索仅来自已采集缓存；纠偏审计是观察统计，不是因果对照。</p></details>`;
  const interpretation=d.interpretation;
  if(interpretation?.status==="available"){
    const m=interpretation.market_read;
    $("#daily-view .overview").insertAdjacentHTML("afterend",`<section class="section">${sectionTitle("怎样理解今天的行情","book-open")}<p>${esc(m.width_impact||"市场宽度解读未记录。")}</p><p>${esc(m.profit_detail||"赚钱效应解读未记录。")}</p><p>${esc(m.mode_summary||"")}</p><details><summary>原报告风险依据</summary>${(Array.isArray(interpretation.risk_board)?interpretation.risk_board:[]).map(r=>`<p>${esc(r)}</p>`).join("")}</details><p class="source-note">沿用当日报告的规则解读，不代表已证实的新闻驱动原因。</p></section>`);
  }
  icons();
}
function renderWatch(){
  $("#watch-count").textContent=state.watch.length;
  const rows=state.watch.map(code=>state.data?.tracking.find(r=>r.code===code)||{code});
  $("#watch-view").innerHTML=`<div class="eyebrow">个人关注</div><h1>持续看，而不是每天重选</h1><form class="watch-form" id="watch-form"><label class="sr-only" for="stock-code">六位股票代码</label><input id="stock-code" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" placeholder="六位股票代码" required><button class="primary" type="submit">${icon("plus")}添加关注</button></form><p class="quiet">保存在此浏览器；手机与iPad分别添加。清除网站数据会清除名单。</p><section class="section"><div class="stocks">${rows.map(stockCard).join("")}</div>${rows.length?"":"<p class='empty'>添加几只你希望持续理解的股票。</p>"}</section>`;
  icons();
}
async function showTab(tab){
  if(!["daily","watch","performance"].includes(tab))return;
  state.tab=tab;
  for(const name of ["daily","watch","performance"])$(`#${name}-view`).hidden=name!==tab;
  document.querySelectorAll(".tabs button").forEach(b=>{b.classList.toggle("active",b.dataset.tab===tab);b.setAttribute("aria-current",b.dataset.tab===tab?"page":"false");});
  if(tab==="watch")renderWatch();
  if(tab==="performance")await renderPerformance();
}
async function renderPerformance(){
  const day=state.day;
  if(!day)return;
  $("#performance-view").innerHTML="<div class='loading'>正在读取正式评价…</div>";
  try{
    const data=await api(`/api/strategies/${day}`);
    if(day!==state.day)return;
    $("#performance-view").innerHTML=`<div class="eyebrow">${esc(dateLabel(day))} · 正式评价</div><h1>把结果放在证据里看</h1><p class="summary">${esc(data.definition||"正式评价数据暂不可用。")}</p><section class="section"><div class="table-wrap"><table><thead><tr><th>策略</th><th>有效 / 总信号</th><th>平均T+1</th><th>上涨比例</th></tr></thead><tbody>${data.rows.map(r=>`<tr><td>${esc(r.strategy)}</td><td>${r.evaluated} / ${r.total}</td><td class="${trendClass(r.avg_return)}">${pct(finite(r.avg_return)?r.avg_return*100:null)}</td><td>${finite(r.win_rate)?fmt(r.win_rate*100,1)+"%":"—"}</td></tr>`).join("")}</tbody></table></div>${data.rows.length?"":"<p class='empty'>没有符合日期及质量条件的样本。</p>"}</section><section class="section">${correctionSection(data.correction)}</section>`;
  }catch(e){$("#performance-view").innerHTML=`<p class="empty">${esc(e.message)} <button class="text-button" data-tab="performance">重试</button></p>`;}
}
async function loadDaily(){
  const id=++state.request, day=state.day;
  state.data=null;
  $("#daily-view").innerHTML="<div class='loading'>正在读取收盘记录…</div>";
  $("#refresh").disabled=true;
  try{
    const data=await api(`/api/daily/${day}`);
    if(id!==state.request)return;
    state.data=data;renderDaily();renderWatch();
    if(state.tab==="performance")await renderPerformance();
  }catch(e){if(id===state.request)$("#daily-view").innerHTML=`<p class='empty'>${esc(e.message)} <button class='text-button' data-retry='daily'>重新读取</button></p>`;}
  finally{if(id===state.request)$("#refresh").disabled=false;}
}
function closeStock(){state.stockRequest++;state.stockCode=null;state.chart?.remove();state.chart=null;$("#stock-dialog").close();}
async function openStock(code){
  const id=++state.stockRequest;
  state.stockCode=code;state.chart?.remove();state.chart=null;
  $("#stock-title").textContent=`${code} · 个股复盘`;
  $("#stock-content").innerHTML="<div class='loading'>正在读取行情与历次判断…</div>";
  if(!$("#stock-dialog").open)$("#stock-dialog").showModal();
  try{
    const data=await api(`/api/stock/${code}?date=${state.day}`);
    if(id!==state.stockRequest)return;
    const r=data.current, saved=state.watch.includes(code);
    $("#stock-title").textContent=`${data.name||code} · 个股复盘`;
    $("#stock-content").innerHTML=`<div class="stock-hero"><div><div class="eyebrow">${esc(code)} · ${esc(dateLabel(state.day))}</div><h3>${esc(data.name||"暂无名称")}</h3><p class="quiet">${data.board_scope==="research_only"?"创业板 · 当前不可交易，仅研究观察":data.board_scope==="unsupported"?"不在系统推荐范围":"沪深主板"}</p></div><button class="icon ${saved?"saved":""}" data-watch="${code}" title="${saved?"取消关注":"加入关注"}" aria-label="${saved?"取消关注":"加入关注"}" aria-pressed="${saved}">${icon("star")}</button></div>
    <div id="price-chart" class="chart"></div><div class="chart-credit"><a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView Lightweight Charts™</a></div><p class="source-note">行情截至 ${esc(data.latest_bar_date||"暂无")}。${esc(data.price_basis_note)}</p>
    <section class="detail-section"><h3>今天发生了什么</h3>${data.explanations.length?data.explanations.map(x=>`<p>${esc(x)}</p>`).join(""):"<p>当日没有可用的个股快照，暂不解释当日涨跌。</p>"}<p class="quiet">${esc(data.event_note)}</p></section>
    ${data.events.length?`<section class="detail-section"><h3>相关消息与证据</h3>${eventList(data.events.slice(0,3))}${data.events.length>3?`<details><summary>其余 ${data.events.length-3} 条线索</summary>${eventList(data.events.slice(3))}</details>`:""}</section>`:""}
    <section class="detail-section"><h3>原来的入选逻辑</h3><p>${esc(data.review?.conclusion)}</p><p class="source-note">依据日期 ${esc(dateLabel(data.review?.reference_date))}</p>${(data.review?.original_reasons||[]).map(item=>`<p><b>${esc(item.strategy||"策略未记录")}</b> · ${esc(item.layer||"层级未记录")}<br>${esc(item.reason||"理由未记录")}</p>`).join("")}<p class="quiet">当前层级：${esc(r?.source_layer||"未记录")}。${esc(r?.display_reason||r?.reason||"")}</p></section>
    <section class="detail-section"><h3>风险与反证</h3><p>${esc(r?.risk_reasons||"缺少当日风险记录，不能据此认定没有风险。")}</p></section>
    <section class="detail-section"><h3>后续观察条件</h3><div class="price-grid"><div><span>原观察区间</span><b>${fmt(r?.observe_low,2)} ~ ${fmt(r?.observe_high,2)}</b></div><div><span>原失效价</span><b>${fmt(r?.invalid_price,2)}</b></div><div><span>原压力位</span><b>${fmt(r?.pressure_price,2)}</b></div></div><p class="source-note">参考日期 ${esc(dateLabel(state.day))}；沿用当日保存结果，不是实时买卖指令。跨期有效性尚未核验。</p></section>
    <section class="detail-section"><h3>历次判断与兑现</h3><p class="source-note">只显示截至所选日期已记录的正式评价；未成熟或未记录不计为失败。</p>${data.history.length?`<ol class="timeline">${data.history.slice(0,30).map(h=>`<li><small>${esc(h.trade_date)} · ${esc(h.strategy)}</small><p><b>${esc(h.source_layer||"层级未记录")}</b> · ${esc(h.display_reason||h.entry_reason||"原因未记录")}</p><small>${h.evaluation?`信号T+1 ${pct(finite(h.evaluation.next_1d_return)?h.evaluation.next_1d_return*100:null)} · T+3 ${pct(finite(h.evaluation.next_3d_return)?h.evaluation.next_3d_return*100:null)} · 当批覆盖 ${finite(h.evaluation.coverage_1d)?fmt(h.evaluation.coverage_1d*100,1)+"%":"未知"}`:"评价尚未成熟或未记录"}</small></li>`).join("")}</ol>`:"<p class='quiet'>暂没有历史判断记录。</p>"}</section>`;
    icons();
    if(data.review?.next_checks)$("#stock-content").insertAdjacentHTML("beforeend",`<section class="detail-section"><h3>下次复盘核对</h3><ul>${data.review.next_checks.map(t=>`<li>${esc(t)}</li>`).join("")}</ul></section>`);
    const validBars=data.bars.filter(b=>[b.open,b.high,b.low,b.close].every(finite)&&b.low>0&&b.high>=Math.max(b.open,b.close)&&b.low<=Math.min(b.open,b.close));
    if(validBars.length && window.LightweightCharts){
      state.chart=LightweightCharts.createChart($("#price-chart"),{autoSize:true,layout:{textColor:"#64736c",background:{color:"#ffffff"}},grid:{vertLines:{color:"#f2f5f3"},horzLines:{color:"#edf1ee"}},rightPriceScale:{borderColor:"#dce4df"},timeScale:{borderColor:"#dce4df"},localization:{locale:"zh-CN"}});
      const series=state.chart.addSeries(LightweightCharts.CandlestickSeries,{upColor:"#b74043",downColor:"#197557",wickUpColor:"#b74043",wickDownColor:"#197557",borderVisible:false});
      series.setData(validBars.map(({time,open,high,low,close})=>({time,open,high,low,close})));
      state.chart.timeScale().fitContent();
    }else{$("#price-chart").innerHTML="<p class='empty'>没有可展示的K线记录。</p>";}
  }catch(e){if(id===state.stockRequest)$("#stock-content").innerHTML=`<p class="empty">${esc(e.message)}</p><button class="text-button" data-stock="${code}">重试</button>`;}
}
document.addEventListener("click",(event)=>{
  const b=event.target.closest("button");if(!b)return;
  if(b.dataset.tab)showTab(b.dataset.tab);
  if(b.dataset.stock)openStock(b.dataset.stock);
  if(b.dataset.watch)toggleWatch(b.dataset.watch);
  if(b.dataset.retry==="daily")loadDaily();
});
document.addEventListener("submit",(event)=>{
  if(event.target.id!=="watch-form")return;event.preventDefault();
  const code=new FormData(event.target).get("code").trim();
  if(!/^\d{6}$/.test(code)){notice("请输入六位股票代码。");return;}
  if(state.watch.includes(code)){notice("这只股票已经在关注名单中。");return;}
  toggleWatch(code);
});
$("#close-stock").addEventListener("click",closeStock);
$("#stock-dialog").addEventListener("cancel",(event)=>{event.preventDefault();closeStock();});
$("#refresh").addEventListener("click",loadDaily);
$("#report-date").addEventListener("change",(e)=>{closeStock();state.day=e.target.value;loadDaily();});
window.addEventListener("storage",(event)=>{if(event.key===storageKey){loadWatch();renderWatch();renderDaily();}});
async function init(){
  icons();loadWatch();renderWatch();
  try{
    const data=await api("/api/dates");
    const publication=data.publication;
    if(publication?.trade_date){
      const label={running:"正在更新",success:"分析已发布",partial:"部分数据可用，暂停新增推荐",failed:"更新失败，保留最近已发布报告",deferred:"更新待完成"}[publication.status];
      if(label)notice(`${dateLabel(publication.trade_date)}：${label}。请核对当前报告日期。`);
    }
    if(!data.dates.length){$("#daily-view").innerHTML="<p class='empty'>尚未找到可用的复盘日期。</p>";return;}
    const requested=new URLSearchParams(location.search).get("date");
    state.day=data.dates.includes(requested)?requested:data.dates[0];$("#report-date").innerHTML=data.dates.map(d=>`<option value="${esc(d)}">${esc(dateLabel(d))}</option>`).join("");$("#report-date").value=state.day;$("#report-date").disabled=false;
    if(requested&&!data.dates.includes(requested))notice("链接指定日期暂不可用，当前展示最近可用日期，请核对日期。");
    if(data.database_status!=="available")notice("数据库暂不可用，当前仅展示本机已有报告。");
    await loadDaily();
  }catch(e){$("#daily-view").innerHTML=`<p class='empty'>${esc(e.message)}，请刷新页面重试。</p>`;}
}
init();
