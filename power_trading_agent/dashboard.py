"""Offline, dependency-free decision and review views. No network or execution API."""
import html
import json


METRICS = {
    "max_price_shock_cost_cny": ("价格冲击成本", "Price shock cost", "元 / CNY"),
    "max_hourly_deviation_mwh": ("最大单小时偏差", "Hourly deviation", "MWh"),
    "max_daily_deviation_mwh": ("最大单日偏差合计", "Daily absolute deviation", "MWh"),
    "max_assessment_fee_cny": ("合成偏差费用", "Synthetic deviation fee", "元 / CNY"),
    "max_forecast_unhedged_mwh": ("最大预测持仓缺口", "Forecast position gap", "MWh"),
    "max_gross_outflow_cny": ("正向结算支出代理量", "Gross outflow proxy", "元 / CNY"),
    "max_incremental_loss_cny": ("全期新增损失", "Period incremental loss", "元 / CNY"),
    "max_daily_incremental_loss_cny": ("最大单日新增损失", "Daily incremental loss", "元 / CNY"),
    "max_abs_k_deviation": ("申报系数偏离 1", "Coefficient deviation", "比例 / ratio"),
}
STATUS = {"eligible": "研究限额内 / Within research limits", "breached": "超限 / Breached",
          "needs_limits": "限额未齐 / Limits missing"}


def _safe_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(
        ">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _e(value):
    return html.escape(str(value), quote=True)


def _n(value):
    return "—" if value is None else "{:,.2f}".format(value)


CSS = """:root{color-scheme:light;--ink:#233a57;--muted:#5e7896;--blue:#295fca;--line:#dce5ef;--bg:#f1f5fa}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif}
header{background:var(--ink);color:white;padding:32px max(24px,calc((100vw - 1180px)/2))}header p{color:#c6d5e9;max-width:850px}
h1{font-size:30px;letter-spacing:-.7px;line-height:1.3;margin:8px 0}h2{font-size:20px;margin:0 0 16px}h3{font-size:17px;margin:0 0 12px}
.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase}.wrap{max-width:1228px;margin:auto;padding:28px 24px 50px}
.notice{padding:16px 20px;border-left:4px solid #b8771d;background:#fff7e8;margin-bottom:24px}.section,.card{background:white;border:1px solid var(--line);border-radius:10px;padding:24px;margin-bottom:24px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.grid .card{margin:0}.value{font-size:26px;font-variant-numeric:tabular-nums;letter-spacing:-.5px}
.muted,small{color:var(--muted)}.two{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(300px,1fr);gap:24px}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;color:var(--muted);font-weight:500}td,th{padding:13px 12px;border-bottom:1px solid var(--line);white-space:nowrap}td:first-child small{display:block}td.num{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:#2b7460}.bad{color:#ae4244}.warn{color:#b8771d}.pill{padding:3px 9px;background:#eaf0f7;border-radius:5px;font-size:12px;display:inline-block}
.toolbar{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:16px 0}.toolbar label{flex:1;min-width:200px}label{display:block;font-size:13px;color:var(--muted);margin:12px 0 6px}
input,select,textarea,button{font:inherit}input,select,textarea{display:block;width:100%;background:white;color:var(--ink);border:1px solid #b8c8db;border-radius:5px;padding:9px 11px;margin-top:6px}textarea{min-height:88px;resize:vertical}
button{border:0;border-radius:5px;background:var(--blue);color:white;padding:10px 16px;cursor:pointer}button:disabled{background:#d6dfeb;color:#5e7896;cursor:not-allowed}a{color:var(--blue)}:focus-visible{outline:3px solid #b8771d;outline-offset:3px}
.tabs{display:flex;gap:8px}.tabs button{background:#e8eff9;color:var(--blue)}.tabs button[aria-pressed=true]{background:var(--blue);color:white}
svg{display:block;width:100%;height:auto;min-height:160px}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px}.swatch{display:inline-block;width:18px;height:3px;vertical-align:middle;margin-right:5px}footer{font-size:12px;color:var(--muted);overflow-wrap:anywhere}code{font-size:12px;overflow-wrap:anywhere}ul{padding-left:22px}.space{margin-top:24px}
@media(max-width:800px){.grid,.two{grid-template-columns:1fr}.wrap{padding:18px 12px}.section,.card{padding:18px}header{padding:24px 18px}h1{font-size:26px}.value{font-size:23px}.tabs{flex-wrap:wrap}}
"""


def _shell(title, subtitle, body, data=None, script=""):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; '
            'connect-src \'none\'; base-uri \'none\'; form-action \'none\'">'
            '<title>' + _e(title) + '</title><style>' + CSS + '</style></head><body>'
            '<header><div class="eyebrow">Power trading · Research workspace</div><h1>' + _e(title)
            + '</h1><p>' + _e(subtitle) + '</p></header><main class="wrap">' + body
            + '</main>' + ('<script id="data" type="application/json">' + _safe_json(data) + '</script>' if data else '')
            + ('<script>' + script + '</script>' if script else '') + '</body></html>')


RISK_SCRIPT = r"""
const data=JSON.parse(document.getElementById('data').textContent), R=data.report, M=data.metrics;
const $=id=>document.getElementById(id), fmt=x=>x==null?'未填写 / Unset':Number(x).toLocaleString('zh-CN',{maximumFractionDigits:2});
let profileId='steady';
function cell(row,text,cls=''){const c=document.createElement('td');c.textContent=text;c.className=cls;row.appendChild(c);return c}
function option(select,value,text){const o=document.createElement('option');o.value=value;o.textContent=text;select.appendChild(o)}
function current(){return R.profile_results.find(p=>p.profile_id===profileId)}
function name(id){const p=R.plans.find(p=>p.plan_id===id);return p?p.name:'无可用方案 / None'}
function status(s){return data.status[s]||s}
function check(id){return current().checks.find(c=>c.plan_id===id)}
function refresh(){
  document.querySelectorAll('[data-profile]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.profile===profileId)));
  const p=R.profiles.find(p=>p.id===profileId), result=current();
  $('eligible-count').textContent=result.admissible_plan_ids.length+' / '+R.plans.length;
  $('reference').textContent='中心成本最低：'+name(result.reference_choices.central_min_cost)+'；最小最大后悔值：'+name(result.reference_choices.minimax_regret);
  $('plans-body').replaceChildren();
  R.plans.forEach(plan=>{const row=document.createElement('tr'),c=check(plan.plan_id);cell(row,plan.name);cell(row,fmt(plan.central_cost_cny),'num');cell(row,fmt(plan.metrics.max_incremental_loss_cny),'num');cell(row,status(c.status),c.status==='eligible'?'ok':c.status==='breached'?'bad':'warn');cell(row,c.violations.length?c.violations.map(v=>M[v.metric][0]).join('、'):c.missing_limits.length?'缺 '+c.missing_limits.length+' 项限额':'全部已设指标通过');$('plans-body').appendChild(row)});
  const chosen=R.plans.find(p=>p.plan_id===$('plan').value)||R.plans[0], c=check(chosen.plan_id);
  $('metrics-body').replaceChildren();
  Object.entries(M).forEach(([key,label])=>{const row=document.createElement('tr'),limit=p.limits[key],bad=c.violations.some(v=>v.metric===key);cell(row,label[0]+' / '+label[1]);cell(row,fmt(chosen.metrics[key])+' '+label[2],'num');cell(row,fmt(limit),'num');const witness=chosen.metric_witnesses[key], scenario=R.scenarios.items.find(s=>s.scenario_id===witness.scenario_id);cell(row,scenario?scenario.label:'固定结构 / Fixed structure');cell(row,limit==null?'待填写':bad?'超限':'通过',limit==null?'warn':bad?'bad':'ok');$('metrics-body').appendChild(row)});
  $('draft-plan').replaceChildren();option($('draft-plan'),'','请明确选择方案 / Choose explicitly');
  R.plans.filter(p=>result.admissible_plan_ids.includes(p.plan_id)).forEach(p=>option($('draft-plan'),p.plan_id,p.name));
  draw();validateDraft();
}
function draw(){
  const p=R.plans.find(p=>p.plan_id===$('plan').value)||R.plans[0],s=R.scenarios.items.find(s=>s.scenario_id===$('scenario').value)||R.scenarios.items[0];
  const aggregate=a=>R.context.period_type==='month'?Array.from({length:a.length/24},(_,i)=>a.slice(i*24,i*24+24).reduce((x,y)=>x+y,0)):a;
  const series=[aggregate(R.context.f),aggregate(p.q),aggregate(s.l)], colors=['#5e7896','#295fca','#b8771d'];
  const all=series.flat(),min=Math.min(0,...all),max=Math.max(1,...all),w=780,h=240,pad=40,n=series[0].length;
  const svg=$('curve');svg.replaceChildren();
  function node(tag,attrs,text){const x=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>x.setAttribute(k,String(v)));if(text!=null)x.textContent=text;svg.appendChild(x)}
  for(let j=0;j<4;j++){const y=pad+(h-2*pad)*j/3;node('line',{x1:pad,y1:y,x2:w-pad,y2:y,stroke:'#dce5ef'});node('text',{x:2,y:y+4,fill:'#5e7896','font-size':11},fmt(max-(max-min)*j/3))}
  series.forEach((a,i)=>node('polyline',{points:a.map((v,j)=>(pad+j*(w-2*pad)/(n-1))+','+(h-pad-(v-min)*(h-2*pad)/(max-min))).join(' '),fill:'none',stroke:colors[i],'stroke-width':2.5}));
  node('text',{x:pad,y:h-8,fill:'#5e7896','font-size':12},R.context.period_type==='month'?'1 日 → '+n+' 日 · 每日合计 MWh':'00 时 → 23 时 · 每小时 MWh');
  const row=p.scenario_results.find(x=>x.scenario_id===s.scenario_id);
  $('scenario-cost').textContent='该场景成本 '+fmt(row.cost_cny)+' 元；相对 k=1 节约 '+fmt(row.incremental_gain_cny)+' 元（负数表示多花）。';
}
function validateDraft(){const p=$('draft-plan').value,ok=p&&current().admissible_plan_ids.includes(p)&&$('actor').value.trim()&&$('reason').value.trim()&&$('selected-at').value.trim();$('download').disabled=!ok}
document.querySelectorAll('[data-profile]').forEach(b=>b.addEventListener('click',()=>{profileId=b.dataset.profile;refresh()}));
R.plans.forEach(p=>option($('plan'),p.plan_id,p.name));R.scenarios.items.forEach(s=>option($('scenario'),s.scenario_id,s.label));
$('plan').addEventListener('change',refresh);$('scenario').addEventListener('change',draw);
['draft-plan','actor','reason','selected-at'].forEach(id=>$(id).addEventListener('input',validateDraft));
$('selected-at').value=R.context.origin;
$('download').addEventListener('click',()=>{
  const request={report_hash:R.report_hash,profile_id:profileId,plan_id:$('draft-plan').value,actor:$('actor').value.trim(),reason:$('reason').value.trim(),selected_at:$('selected-at').value.trim()};
  const t=Date.parse(request.selected_at);if(!Number.isFinite(t)||t<Date.parse(R.context.origin)||t>=Date.parse(R.context.hours[0])){$('draft-status').textContent='选择时间须在信息冻结后、交付开始前，且须带时区。';return}
  const blob=new Blob([JSON.stringify(request,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='choice-request.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
  $('draft-status').textContent='已导出研究选择草稿。需通过 decide 命令复核；尚未申报或成交。';
});
refresh();
"""


def risk_html(report):
    c = report["context"]
    body = '''<div class="notice"><strong>合成研究 / Synthetic research</strong>：演示阈值不是经营限额。正式考核规则、交易平台、保证金与资金到账时序尚未接入；“研究限额内”不代表实盘可执行。压力场景未赋概率，不代表穷尽风险。</div>
    <div class="grid"><div class="card"><small>决策周期 / Period</small><div class="value">PERIOD</div><p>TYPE</p></div><div class="card"><small>压力情景 × 候选方案</small><div class="value">COUNTS</div><p>只使用冻结时点可知输入</p></div><div class="card"><small>当前档位研究限额内方案</small><div class="value" id="eligible-count"></div><p>限额未齐时不提供新选择</p></div></div>
    <section class="section space"><h2>01 · 选择风险档位 / Risk appetite</h2><div class="tabs"><button data-profile="conservative" aria-pressed="false">保守 / Conservative</button><button data-profile="steady" aria-pressed="true">稳健 / Steady</button><button data-profile="aggressive" aria-pressed="false">激进 / Aggressive</button></div><p class="muted">档位由一整套指标限额构成。不同指标可能反映同一冲击，不能相加。参考方案仅供比较，最终由你选择。</p><p id="reference"></p><div class="scroll"><table><thead><tr><th>方案 / Plan</th><th>中心成本 / CNY</th><th>最坏新增损失 / CNY</th><th>状态</th><th>原因</th></tr></thead><tbody id="plans-body"></tbody></table></div></section>
    <section class="section"><h2>02 · 查看场景与限额 / Stress & limits</h2><div class="toolbar"><label>查看候选方案 / Inspect plan<select id="plan"></select></label><label>查看压力场景 / Inspect scenario<select id="scenario"></select></label></div><div class="legend"><span><i class="swatch" style="background:#5e7896"></i>预测用电 F</span><span><i class="swatch" style="background:#295fca"></i>申报电量 Q</span><span><i class="swatch" style="background:#b8771d"></i>场景用电 L</span></div><svg id="curve" viewBox="0 0 780 240" role="img" aria-label="预测、申报和压力场景电量对比"></svg><p id="scenario-cost"></p><div class="scroll"><table><thead><tr><th>维度指标 / Dimension</th><th>该方案最坏值</th><th>当前档位限额</th><th>最坏场景 / Witness</th><th>检查</th></tr></thead><tbody id="metrics-body"></tbody></table></div><p class="muted">上表是全场景最坏值，不随查看场景改变。金额默认按整个决策周期；“单日”取最差的一天。持仓缺口为 max|F−H|，各候选共同承担；支出代理量不等于保证金需求。考核目前仅模拟 |Q−L|×合成费率。</p></section>
    <section class="section"><h2>03 · 记录你的判断 / Your decision</h2><div class="two"><div><label>明确选择当前档位下的方案<select id="draft-plan"></select></label><label>决策人 / Actor<input id="actor" autocomplete="off" placeholder="填写姓名或研究身份"></label><label>选择时间 / Selected at<input id="selected-at" placeholder="YYYY-MM-DDTHH:mm:ss+08:00"></label><label>理由、重点风险与预案 / Rationale<textarea id="reason" placeholder="为什么接受这些风险？出现哪些信号时需要重新评估？"></textarea></label><button id="download" disabled>导出选择草稿 / Export draft</button><p id="draft-status" aria-live="polite"></p></div><div><h3>选择前看清三个问题</h3><ol><li>哪些指标靠近或超过限额？</li><li>最差场景里，成本、电量和费用如何变化？</li><li>依赖哪些预测与规则？缺失信息是否足以改变决策？</li></ol><p class="muted">导出的是本地研究草稿。记录不验证身份或历史时间，也不会下单。修改输入或限额后应重新生成风险报告。</p><p class="muted">本页无事后实际量价。复盘页独立生成，避免事后信息混入当时判断。</p></div></div></section>
    <footer>信息冻结 / Origin：ORIGIN<br>报告指纹 / Report hash：HASH</footer>'''
    body = body.replace("PERIOD", _e(c["period"])).replace("TYPE", "日前研究 / Day-ahead research" if c["period_type"] == "day" else "月度研究视图 / Monthly research horizon")
    body = body.replace("COUNTS", str(len(report["scenarios"]["items"])) + " × " + str(len(report["plans"])))
    body = body.replace("ORIGIN", _e(c["origin"])).replace("HASH", _e(report["report_hash"]))
    return _shell("风控决策台 / Risk workspace", "先看风险的不同维度，再决定可以承担什么。", body,
                  {"report": report, "metrics": METRICS, "status": STATUS}, RISK_SCRIPT)


def risk_markdown(report):
    c = report["context"]
    lines = ["# 多维风控 / Multidimensional risk", "", "合成研究；正式规则未接入 / Synthetic only; formal rules not connected.",
             "", "周期 / Period: " + c["period"], "", "Origin: " + c["origin"], "",
             "| 档位 / Profile | 限额内方案 / Eligible plans |", "|---|---:|"]
    lines += ["| {} | {} |".format(p["profile_id"], len(p["admissible_plan_ids"])) for p in report["profile_results"]]
    lines += ["", "每项独立检查；指标不得相加。默认限额未填写时禁止新选择。",
              "Each metric is checked independently; overlapping metrics must not be added. Missing limits block new choices.",
              "", "Report hash: " + report["report_hash"]]
    return "\n".join(lines) + "\n"


def review_html(review):
    r = review
    chosen, hindsight = r["chosen_outcome"], r["hindsight_best"]
    cards = [("当时选择 / Chosen plan", chosen), ("当时参考 / Frozen minimax reference", r["ex_ante_references"].get("minimax_regret")),
             ("事后参照 / Hindsight candidate", hindsight)]
    body = '<div class="notice"><strong>复盘看决策质量，也看结果 / Process and outcome</strong>：事后低成本方案仅来自当时冻结的限额内候选集。差距不等于当时可赚的钱，也不能单凭一次输赢判断决策好坏。</div><div class="grid">'
    for title, outcome in cards:
        body += '<div class="card"><small>' + _e(title) + '</small><div class="value">' + (_n(outcome["cost_cny"]) + ' 元' if outcome else '无可比方案') + '</div><p>' + (_e(outcome["name"]) if outcome else '原候选集中没有限额内方案') + '</p></div>'
    dc = r["decision_context"]
    body += '</div><section class="section space"><h2>当时的判断 / Original rationale</h2><p>信息冻结：' + _e(dc["origin"]) + '<br>选择时间：' + _e(dc["selected_at"]) + '<br>档位 / Profile：' + _e(dc["profile_id"]) + '；决策人 / Actor：' + _e(dc["actor"]) + '</p><p><strong>原始理由 / Rationale：</strong>' + _e(dc["reason"]) + '</p><p class="muted">身份和历史时间为调用者声明，尚无独立认证。原始输入与限额可通过同目录归档及风险报告指纹核对。</p></section>'
    body += '<section class="section"><h2>01 · 同口径比较 / Like-for-like outcomes</h2><div class="scroll"><table><thead><tr><th>视角</th><th>候选方案</th><th>实际量价下成本 / CNY</th><th>相对 k=1 节约 / CNY</th></tr></thead><tbody>'
    rows = [("当时选择 / Chosen", chosen), ("基准 / Baseline", r["baseline_outcome"])]
    rows += [("当时中心成本最低 / Frozen central", r["ex_ante_references"].get("central_min_cost")), ("当时最小最大后悔值 / Frozen minimax", r["ex_ante_references"].get("minimax_regret")), ("事后候选最优 / Hindsight", hindsight)]
    for title, outcome in rows:
        if outcome:
            body += '<tr><td>' + _e(title) + '</td><td>' + _e(outcome["name"]) + '</td><td class="num">' + _n(outcome["cost_cny"]) + '</td><td class="num">' + _n(outcome["incremental_gain_cny"]) + '</td></tr>'
    body += '</tbody></table></div><p>选择时的限额状态：' + _e(STATUS.get(r["process_integrity"]["choice_admissibility"], "unknown")) + '。执行记录：' + ('未提供，不能把选择称为实际成交。' if r["execution_status"] == "not_provided" else '已提供，来源未独立认证；执行成本 ' + _n(r["execution_outcome"]["cost_cny"]) + ' 元。') + '</p>'
    if hindsight:
        body += '<p>与事后参照成本差：' + _n(hindsight["gap_to_chosen_cny"]) + ' 元。' + ('选择也属于同一比较集合。' if hindsight["chosen_in_comparison_set"] else '历史选择不在限额内集合，不能把此差额称为同集合后悔值。') + '</p>'
    body += '</section><section class="section"><h2>02 · 成本怎样变化 / Cost bridge</h2><p class="muted">按固定顺序替换：预测中心 → 实际负荷 → 实际日前价 → 实际实时价 → 提供的执行量。顺序会影响分项，不能当作独立因果贡献。</p><div class="scroll"><table><thead><tr><th>替换项</th><th>成本变动 / CNY</th><th>替换后成本 / CNY</th></tr></thead><tbody>'
    factors = {"actual_load": "实际负荷 / Actual load", "actual_da_price": "实际日前价 / Actual DA", "actual_rt_price": "实际实时价 / Actual RT", "provided_execution_q": "提供的执行量 / Provided execution"}
    for step in r["cost_bridge"]["steps"]:
        body += '<tr><td>' + _e(factors.get(step["factor"], step["factor"])) + '</td><td class="num">' + _n(step["delta_cost_cny"]) + '</td><td class="num">' + _n(step["after_cost_cny"]) + '</td></tr>'
    body += '</tbody></table></div><p>合计变化：' + _n(r["cost_bridge"]["total_change_cny"]) + ' 元；对账误差：' + _n(r["cost_bridge"]["reconciliation_error_cny"]) + ' 元。</p></section>'
    d = r["forecast_diagnostics"]
    body += '<div class="two"><section class="section"><h2>03 · 预测与场景盲区</h2><p>负荷 MAE：' + _n(d["load_mae_mwh"]) + ' MWh；价差 MAE：' + _n(d["spread_mae_cny_per_mwh"]) + ' 元/MWh。</p><ul>'
    labels = {"load": "负荷 / Load", "da": "日前价 / DA", "rt": "实时价 / RT", "spread": "价差 / Spread"}
    for key, value in r["scenario_coverage"]["variables"].items():
        body += '<li>' + labels[key] + '：' + str(value["outside_count"]) + ' / ' + str(value["total_count"]) + ' 小时超出原场景边界。</li>'
    body += '</ul><p class="muted">这是逐小时边界检查，未检验整条轨迹相关性，也不是概率校准。</p></section><section class="section"><h2>04 · 把发现变成下一次实验</h2><ol><li>先保留原决策信息与理由，区分预测问题、策略问题、执行问题。</li><li>提出一个具体改动，冻结候选版本、基准与验收指标。</li><li>在复盘数据可知之后登记实验，用后续未看过的周期检验。</li><li>日前按日积累；月度每个交易组合、每月保留一个复盘版本参与实验登记。</li></ol><p class="muted">复盘建议尚未验证，不会自动替换策略。月度目前沿用合成结算研究口径，未实现正式月度市场流程。</p></section></div>'
    body += '<footer>周期 / Period：' + _e(r["period"]) + '<br>复盘数据可知时间：' + _e(r["review_data_available_time"]) + '<br>Review hash：' + _e(r["review_hash"]) + '</footer>'
    return _shell("决策复盘 / Decision review", "用事后结果理解损益，用当时信息评价决策；改进交给后续验证。", body)


def review_markdown(review):
    return ("# 决策复盘 / Decision review\n\n"
            "周期 / Period: " + review["period"] + "\n\n"
            "当时选择的实际量价成本 / Chosen-plan cost on observed outcomes: " + _n(review["chosen_outcome"]["cost_cny"]) + " CNY\n\n"
            "执行记录 / Execution: " + review["execution_status"] + "\n\n"
            "事后参照仅限冻结候选集，不是未来可达目标 / Hindsight is limited to frozen admissible candidates, not an achievable future target.\n\n"
            "Review hash: " + review["review_hash"] + "\n")
