const root = document.querySelector('#app');
let csrf = '', me = null, survey = null, filling = null, listSkip = 0;
let reusableEditing=null, reusableBase=null, reusableSkip=0, reusableArchived=false, reusableVersionSkip=0, reusableDetail=null, lastIntent=null, reusableName="";
let questionView=null, activeQuestion=0, editorDirty=false, pickerState=null, area='surveys', workspaceRequest=0;
const token = document.body.dataset.token;
const kinds = {single:'单选题',multiple:'多选题',text:'文本填空',number:'数字填空'};
const e = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = (s,n=document)=>n.querySelector(s);
const $$ = (s,n=document)=>[...n.querySelectorAll(s)];
const uid = ()=>crypto.randomUUID().replaceAll('-','');
const selected = (a,b)=>a===b?' selected':'';
function notice(message){const n=$('#notice');n.textContent=message;n.hidden=false;clearTimeout(notice.timer);notice.timer=setTimeout(()=>n.hidden=true,7000);}
// 统一把接口错误转为页面异常，并保留状态码供调用方判断。
async function api(path, method = 'GET', data) {
  const response = await fetch(path, {
    method,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401 && me) {
      me = null;
      account();
      auth();
    }
    const message = typeof body.detail === 'string'
      ? body.detail
      : (body.detail || []).map(issue => `${issue.loc?.slice(1).join('.')}: ${issue.msg}`).join('\n');
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return body;
}
function account(){
  $('#account').innerHTML=me?`<nav class="main-nav" aria-label="主导航"><button data-action="list" ${area==='surveys'?'aria-current="page"':''}>我的问卷</button><button data-action="rq-list" ${area==='questions'?'aria-current="page"':''}>题目中心</button><button data-action="mg-banks" ${area==='banks'?'aria-current="page"':''}>个人题库</button></nav>${moreMenu(`<span class="menu-label">${e(me.username)}</span><button data-action="logout">退出登录</button>`,e(me.username))}`:'<span class="muted">登录后创建或填写问卷</span>';
}
function setArea(value){workspaceRequest++;area=value;account();}
function moreMenu(content,label='更多'){return `<details class="menu"><summary>${label}<span aria-hidden="true"> ▾</span></summary><div class="menu-popover">${content}</div></details>`;}
function questionTabs(shared=false){return `<div class="tabs" aria-label="题目中心"><button data-action="rq-list" class="${shared?'':'active'}">我的题目</button><button data-action="mg-shared" class="${shared?'active':''}">共享给我</button></div>`;}
function markDirty(){editorDirty=true;const el=$('#save-state');if(el){el.textContent='有未保存的修改';el.className='muted dirty';}}
function leaveEditor(){return !editorDirty||confirm('有未保存的修改，离开后将丢失。确认离开？');}
function auth(){workspaceRequest++;questionView=null;editorDirty=false;root.innerHTML=`<section class="card auth"><span class="badge">欢迎使用</span><h1>${token?'登录后继续填写':'登录问卷工作台'}</h1><p class="muted">使用自己的账号管理问卷与查看结果。</p><form id="auth-form"><label><span>用户名</span><input name="username" required minlength="2" maxlength="40" autocomplete="username"></label><label><span>密码 · 至少 8 位</span><input name="password" type="password" required minlength="8" maxlength="128" autocomplete="current-password"></label><div class="actions"><button class="primary" type="submit">登录</button><button type="button" data-action="register">注册账号</button></div></form><p class="muted">${token?'匿名仅向问卷创建者隐藏账号；系统仍需登录以限制填写次数。':'首次使用请先注册，再登录。'}</p></section>`;}
async function boot(){const s=await api('/api/session');csrf=s.csrf;me=s.user;account();if(!me)return auth();if(token)return startFill(token);await list();}
function localTime(value){if(!value)return '';const d=new Date(new Date(value).toLocaleString('en-US',{timeZone:'Asia/Shanghai'}));return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;}
function dateLabel(value){return value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'不限时间';}
async function list(){
  reusableEditing=null;questionView=null;editorDirty=false;filling=null;survey=null;setArea('surveys');
  const request=workspaceRequest,items=await api(`/api/surveys?skip=${listSkip}&limit=12`);
  if(request!==workspaceRequest)return;
  root.innerHTML=`<div class="hero"><div><span class="eyebrow">问卷工作台</span><h1>我的问卷</h1><p class="muted">编辑草稿、分发链接，查看收集到的回答。</p></div><button class="primary" data-action="new">＋ 新建问卷</button></div><div class="survey-grid">${items.map(s=>`<article class="card"><span class="badge ${s.status}">${{draft:'草稿',published:'已发布',closed:'已关闭'}[s.status]}</span><h2>${e(s.title)}</h2><p class="prewrap muted">${e(s.description.slice(0,100))||'暂无说明'}</p><p class="muted">截止：${e(dateLabel(s.deadline))}</p><div class="actions"><button class="primary" data-action="edit" data-id="${s.id}">${s.status==='draft'?'继续编辑':'管理问卷'}</button><button data-action="stats" data-id="${s.id}">查看统计</button>${s.status==='published'?moreMenu(`<button data-action="copy" data-token="${s.token}">复制填写链接</button><a href="/survey/${s.token}" class="button">打开填写页面</a>`):''}</div></article>`).join('')}</div>${!items.length?'<div class="card empty"><h2>还没有问卷</h2><p class="muted">新建一份问卷，或先在题目中心准备常用题。</p></div>':''}<div class="pagination"><button data-action="list-prev" ${listSkip===0?'disabled':''}>上一页</button><button data-action="list-next" ${items.length<12?'disabled':''}>下一页</button></div>`;
}
function metadataFields(s){return `<div class="grid"><label><span>问卷标题</span><input name="title" value="${e(s.title)}" maxlength="200"></label><label><span>截止时间 · 北京时间，留空为不限</span><input type="datetime-local" name="deadline" value="${localTime(s.deadline)}"></label></div><label><span>问卷说明</span><textarea name="description" maxlength="5000">${e(s.description)}</textarea></label>`;}
function renderEditor(){
  reusableEditing=null;questionView=null;setArea('surveys');const s=survey,locked=s.status!=='draft';
  root.innerHTML=`<div class="breadcrumb"><button data-action="list">我的问卷</button><span> / ${locked?'管理问卷':'编辑草稿'}</span></div><div class="hero"><div><span class="badge ${s.status}">${{draft:'草稿',published:'已发布',closed:'已关闭'}[s.status]}</span><h1>${e(s.title)}</h1><p class="muted">${locked?'题目与填写设置已冻结；标题、说明和截止时间仍可修改。':'点击题目展开编辑；选入的正式版本内容只读，可独立配置必答和跳转。'}</p></div></div>
  ${locked?`<section class="card"><p class="prewrap">${e(s.description)||'暂无说明'}</p><p class="muted">截止：${e(dateLabel(s.deadline))} · ${s.allowAnonymous?'允许匿名':'实名填写'} · ${s.allowMultiple?'可多次提交':'每账号限一份'}</p><div class="actions"><button class="primary" data-action="stats" data-id="${s.id}">查看统计</button>${s.status==='published'?`<button data-action="copy" data-token="${s.token}">复制填写链接</button>${moreMenu('<button class="danger" data-action="close">关闭问卷（不可重开）</button>')}`:'<span class="muted">已关闭，不能重开</span>'}</div><details class="metadata-edit"><summary>修改基本信息</summary><div id="metadata">${metadataFields(s)}<div class="actions"><button data-action="save">保存基本信息</button><span id="save-state" class="muted">${editorDirty?'有未保存的修改':'基本信息已保存'}</span></div></div></details></section>`:
  `<div class="editor-toolbar"><span id="save-state" class="${editorDirty?'dirty':'saved'}">${editorDirty?'有未保存的修改':'草稿已保存'}</span><div class="actions compact"><button data-action="save">保存草稿</button><button data-action="preview">预览</button><button class="primary" data-action="publish">发布</button></div></div><section class="card" id="metadata">${metadataFields(s)}<details class="settings"><summary>填写设置 · ${s.allowAnonymous?'允许匿名':'实名'} · ${s.allowMultiple?'可多次提交':'每账号一份'}</summary><label><input type="checkbox" name="allowAnonymous" ${s.allowAnonymous?'checked':''}> 允许匿名（仍需登录）</label><label><input type="checkbox" name="allowMultiple" ${s.allowMultiple?'checked':''}> 允许同一账号多次填写</label></details></section>`}
  <div class="section-title"><h2>问卷题目 <span class="muted">${s.questions.length} 题</span></h2>${!locked?'<button data-action="rq-picker">＋ 添加题目</button>':''}</div><div id="questions">${s.questions.map((q,i)=>questionEditor(q,i,locked)).join('')}</div>${!s.questions.length?'<section class="card empty"><p>尚无题目，点击“添加题目”开始。</p></section>':''}`;
}
function questionEditor(q,i,locked,contentOnly=false){
  const v=q.validation||{},title=`第 ${i+1} 题 · ${e(q.title)}`;
  if(locked)return `<section class="card"><div class="section-title"><h2>${title}</h2><span class="badge">${q.required?'必答':'选填'}</span></div>${renderVersionContent({content:q},false)}${q.jumpRules.length?`<p class="muted">${q.jumpRules.length} 条跳转规则 · 首条命中生效</p>`:''}<div class="actions">${q.sourceVersionId?`<button data-action="mg-stats" data-id="${q.sourceVersionId}">此版本跨卷统计</button>`:''}${moreMenu(`<button data-action="rq-export" data-index="${i}">另存为可复用题目</button>${q.sourceVersionId?`<button data-action="mg-usage" data-id="${q.sourceVersionId}">使用情况</button>`:''}`)}</div>${q.jumpRules.length?`<details><summary>查看跳转规则</summary>${q.jumpRules.map((r,j)=>`<p>规则 ${j+1}：${r.conditions.map(c=>`${e(c.op)} ${e(answerText(q,c.value))}`).join(' 且 ')} → ${r.target==='END'?'提交确认':`第 ${survey.questions.findIndex(x=>x.id===r.target)+1} 题`}</p>`).join('')}</details>`:''}</section>`;
  return `<${contentOnly?'section':'details'} class="question" data-index="${i}" ${!contentOnly&&activeQuestion===i?'open':''}>${contentOnly?'':`<summary class="question-summary"><span><strong>${title}</strong><span class="muted">${e(kinds[q.kind])} · ${q.required?'必答':'选填'}${q.sourceVersionId?' · 固定版本':''}${q.jumpRules.length?` · ${q.jumpRules.length} 条跳转`:''}</span></span><span class="expand-label">编辑 ▾</span></summary>`}<div class="question-body">${!contentOnly?`<div class="section-title"><span class="muted">${q.sourceVersionId?'复用题目：版本内容只读，卷内设置可编辑。':'普通题目：直接编辑当前问卷内容。'}</span>${moreMenu(`<button data-action="up" data-index="${i}" ${i===0?'disabled':''}>上移</button><button data-action="down" data-index="${i}" ${i===survey.questions.length-1?'disabled':''}>下移</button><button data-action="rq-export" data-index="${i}">另存为可复用题目</button>${q.sourceVersionId?`<button data-action="rq-upgrade-picker" data-index="${i}">主动换版</button><button data-action="mg-stats" data-id="${q.sourceVersionId}">此版本跨卷统计</button><button data-action="mg-usage" data-id="${q.sourceVersionId}">使用情况</button>`:''}<button class="danger" data-action="remove-question" data-index="${i}">移除此位置</button>`)}</div>`:''}
  <fieldset ${q.sourceVersionId?'disabled':''}><div class="grid"><label><span>题干 · 填写者看到的文字</span><input name="qtitle" value="${e(q.title)}" maxlength="500"></label><label><span>题型</span><select name="kind" data-index="${i}">${Object.entries(kinds).map(([k,n])=>`<option value="${k}"${selected(k,q.kind)}>${n}</option>`).join('')}</select></label></div>${['single','multiple'].includes(q.kind)?`<div class="options">${q.options.map((o,j)=>`<label class="condition" data-option="${j}"><input name="option-label" aria-label="选项 ${j+1}" value="${e(o.label)}" maxlength="200"><button data-action="remove-option" data-index="${i}" data-option="${j}" type="button">移除</button></label>`).join('')}</div><button data-action="add-option" data-index="${i}">添加选项</button>`:''}${q.kind==='multiple'?bounds('minChoices','最少选择','maxChoices','最多选择',v,'number')+'<p class="muted">恰好 N 项：最少和最多均填 N。选填题未答时不检查数量。</p>':''}${q.kind==='text'?bounds('minLength','最少字数','maxLength','最多字数',v,'number'):''}${q.kind==='number'?bounds('minimum','最小值','maximum','最大值',v,'text')+`<label><input name="integer" type="checkbox" ${v.integer?'checked':''}> 仅允许整数</label>`:''}</fieldset>
  ${!contentOnly?`<label><input name="required" type="checkbox" ${q.required?'checked':''}> 必须回答</label>${q.kind!=='text'?`<details class="settings" ${q.jumpRules.length?'open':''}><summary>跳转设置${q.jumpRules.length?` · ${q.jumpRules.length} 条规则`:' · 默认进入下一题'}</summary><p class="help">按顺序首条命中，未命中进入下一题。“结束”进入提交确认，不会自动提交。</p>${q.jumpRules.map((r,j)=>ruleEditor(q,r,i,j)).join('')}<button data-action="add-rule" data-index="${i}">添加跳转规则</button></details>`:''}`:''}</div></${contentOnly?'section':'details'}>`;
}
function bounds(a,al,b,bl,v,type){return `<div class="number-pair"><label><span>${al} · 可留空</span><input type="${type}" name="${a}" value="${e(v[a])}"></label><label><span>${bl} · 可留空</span><input type="${type}" name="${b}" value="${e(v[b])}"></label></div>`;}
function ruleEditor(q,r,i,j){const ops=q.kind==='single'?{eq:'选中'}:q.kind==='multiple'?{any:'包含任一',all:'包含全部'}:{eq:'等于',ne:'不等于',gt:'大于',gte:'大于等于',lt:'小于',lte:'小于等于'};return `<div class="rule" data-rule="${j}"><strong>规则 ${j+1} · 条件同时满足</strong>${r.conditions.map((c,k)=>`<div class="condition" data-condition="${k}"><select name="op" aria-label="条件运算">${Object.entries(ops).map(([op,label])=>`<option value="${op}"${selected(op,c.op)}>${label}</option>`).join('')}</select>${q.kind==='number'?`<input name="condition-value" aria-label="比较数值" value="${e(c.value)}">`:`<select name="condition-value" aria-label="条件选项" ${q.kind==='multiple'?'multiple':''}>${(q.kind==='multiple'?(Array.isArray(c.value)?c.value:[]):[c.value]).filter(v=>!q.options.some(o=>o.id===v)).map(v=>`<option value="${e(v)}" selected>无效选项，请重新选择</option>`).join('')}${q.options.map(o=>`<option value="${o.id}" ${q.kind==='multiple'?(Array.isArray(c.value)&&c.value.includes(o.id)?'selected':''):selected(c.value,o.id)}>${e(o.label)}</option>`).join('')}</select>`}<button data-action="remove-condition" data-index="${i}" data-rule="${j}" data-condition="${k}">移除条件</button></div>`).join('')}<button data-action="add-condition" data-index="${i}" data-rule="${j}">添加 AND 条件</button><label><span>命中后前往</span><select name="target">${r.target!=='END'&&!survey.questions.slice(i+1).some(x=>x.id===r.target)?`<option value="${e(r.target)}" selected>无效目标，请重新选择</option>`:''}<option value="END"${selected(r.target,'END')}>结束 → 提交确认</option>${survey.questions.slice(i+1).map((x,k)=>`<option value="${x.id}"${selected(r.target,x.id)}>第 ${i+k+2} 题 ${e(x.title)}</option>`).join('')}</select></label><button class="danger" data-action="remove-rule" data-index="${i}" data-rule="${j}">删除规则</button></div>`;}
function collectContent(q,n){q.title=$('[name=qtitle]',n).value;$$('[name=option-label]',n).forEach((x,j)=>q.options[j].label=x.value);q.validation={};for(const k of ['minChoices','maxChoices','minLength','maxLength','minimum','maximum']){const el=$(`[name=${k}]`,n);if(el&&el.value!=='')q.validation[k]=['minimum','maximum'].includes(k)?el.value:Number(el.value);}q.validation.integer=$('[name=integer]',n)?.checked||false;}
function collect(){
  if(reusableEditing){reusableName=reusableEditing.name;collectContent(survey.questions[0],$('.question'));return;}
  if(!survey||!$('#metadata'))return;
  const m=$('#metadata');survey.title=$('[name=title]',m).value;survey.description=$('[name=description]',m).value;const d=$('[name=deadline]',m).value;survey.deadline=d?`${d}:00+08:00`:null;
  if(survey.status!=='draft')return;
  survey.allowAnonymous=$('[name=allowAnonymous]',m).checked;survey.allowMultiple=$('[name=allowMultiple]',m).checked;
  $$('.question').forEach((n,i)=>{const q=survey.questions[i];if(!q.sourceVersionId)collectContent(q,n);q.required=$('[name=required]',n).checked;
    q.jumpRules=$$('.rule',n).map(r=>({target:$('[name=target]',r).value,conditions:$$('.condition[data-condition]',r).map(c=>({op:$('[name=op]',c).value,value:q.kind==='multiple'?$$('[name=condition-value] option:checked',c).map(o=>o.value):$('[name=condition-value]',c).value}))}));
  });
}
async function intent(path,method,data,field='operationKey'){
  const signature=JSON.stringify([path,method,data]);
  if(!lastIntent||lastIntent.signature!==signature)lastIntent={signature,key:uid()};
  const result=await api(path,method,{...data,[field]:lastIntent.key});lastIntent=null;return result;
}
async function save({quiet = false} = {}) {
  collect();
  const data = {
    title: survey.title,
    description: survey.description,
    deadline: survey.deadline,
    editRevision: survey.editRevision,
  };
  if (survey.status === 'draft') {
    Object.assign(data, {
      allowAnonymous: survey.allowAnonymous,
      allowMultiple: survey.allowMultiple,
      questions: survey.questions,
    });
    survey = await intent(`/api/surveys/${survey.id}`, 'PUT', data);
  } else {
    survey = await api(`/api/surveys/${survey.id}/metadata`, 'PATCH', data);
  }
  editorDirty=false;renderEditor();
  if (!quiet) notice('问卷草稿或基本信息已保存');
}
async function startFill(t,preview=false){const data=preview?(await api(`/api/surveys/${survey.id}/preview`,'POST',{answers:[]})).survey:await api(`/api/fill/${t}`);filling={survey:data,token:t,preview,answers:{},path:[data.questions[0].id],current:data.questions[0].id,key:uid()};renderFill();}
function answerText(q,value){if(value===null||value===undefined)return '未填写';if(q.kind==='single')return q.options.find(o=>o.id===value)?.label||'';if(q.kind==='multiple')return value.map(x=>q.options.find(o=>o.id===x)?.label||'').join('、');return value;}
function renderFill(){$('#notice').hidden=true;const f=filling,s=f.survey,q=s.questions.find(x=>x.id===f.current),a=q?f.answers[q.id]:null;root.innerHTML=`<div class="narrow"><div class="hero"><div><span class="badge">${f.preview?'草稿预览 · 不保存答卷':'填写问卷'}</span><h1>${e(s.title)}</h1><p class="prewrap muted">${e(s.description)}</p></div>${f.preview?'<button data-action="end-preview">退出预览</button>':''}</div>${q?`<section class="card"><span class="badge">第 ${s.questions.indexOf(q)+1} 题 / 共 ${s.questions.length} 题</span><h2>${e(q.title)} ${q.required?'<span class="muted">必答</span>':'<span class="muted">选填</span>'}</h2><p class="muted">${e(constraintText(q))}</p><div id="answer">${q.kind==='single'||q.kind==='multiple'?q.options.map(o=>`<label class="choice"><input type="${q.kind==='single'?'radio':'checkbox'}" name="value" value="${o.id}" ${q.kind==='single'?(a===o.id?'checked':''):(Array.isArray(a)&&a.includes(o.id)?'checked':'')}><span>${e(o.label)}</span></label>`).join(''):q.kind==='text'?`<textarea name="value" maxlength="5000" aria-label="填写回答">${e(a)}</textarea>`:`<input name="value" inputmode="decimal" value="${e(a)}" aria-label="填写数字">`}</div><div class="actions">${f.path.length>1?'<button data-action="back-answer">上一题</button>':''}<button class="primary" data-action="next-answer">下一步</button></div></section>`:`<section class="card"><h2>确认后再提交</h2><p class="muted">尚未保存答卷。请核对本次回答；需要调整时可以返回修改。</p>${f.path.map(id=>{const x=s.questions.find(y=>y.id===id);return `<div class="statline"><div><strong>${e(x.title)}</strong><div class="prewrap">${e(answerText(x,f.answers[id]))}</div></div><button data-action="revise" data-id="${id}">修改</button></div>`;}).join('')}<label><input id="anonymous" type="checkbox" ${s.allowAnonymous?'checked':'disabled'}> 匿名填写</label><p class="muted">${s.allowAnonymous?'匿名时创建者看不到你的账号，系统内部仍保留关联以限制次数。':'此问卷不允许匿名，创建者可看到账号名。'}</p><div class="actions"><button class="primary" data-action="submit-answer">${f.preview?'完成预览（不提交）':'确认提交'}</button></div></section>`}</div>`;}
function constraintText(q){const v=q.validation;if(q.kind==='multiple')return `可选数量：${v.minChoices??0} 至 ${v.maxChoices??q.options.length} 项`;if(q.kind==='text')return `去除首尾空白后 ${v.minLength??0} 至 ${v.maxLength??5000} 字`;if(q.kind==='number')return `${v.integer?'整数':'数字'}，范围 ${v.minimum??'不限'} 至 ${v.maximum??'不限'}`;return '请选择一个选项';}
function revise(id){const f=filling,at=f.path.indexOf(id);for(const x of f.path.slice(at+1))delete f.answers[x];f.path=f.path.slice(0,at+1);f.current=id;renderFill();}
async function nextAnswer(){const f=filling,q=f.survey.questions.find(x=>x.id===f.current);let value;if(q.kind==='single')value=$('[name=value]:checked')?.value??null;else if(q.kind==='multiple')value=$$('[name=value]:checked').map(x=>x.value);else value=$('[name=value]').value;const answers={...f.answers,[q.id]:value};const body={answers:Object.entries(answers).map(([questionId,value])=>({questionId,value}))};const result=f.preview?(await api(`/api/surveys/${survey.id}/preview`,'POST',body)).walk:await api(`/api/fill/${f.token}/walk`,'POST',body);f.answers=answers;f.path=result.path;f.current=result.nextQuestionId;renderFill();}
async function statistics(id){questionView=null;editorDirty=false;setArea('surveys');survey=await api(`/api/surveys/${id}`);const data=await api(`/api/surveys/${id}/stats`);root.innerHTML=`<div class="hero"><div><span class="badge">回答统计</span><h1>${e(survey.title)}</h1><p class="muted">份数按成功提交计；账号数去重，不代表现实人数。跳过与未答不计入该题；同一账号改选不同选项会分别计数，各选项账号数不可相加。数字平均值按有效答卷计算。</p></div><button data-action="list">返回列表</button></div><section class="card"><span class="big-number">${data.total}</span> 份答卷 · ${data.respondentCount} 个填写账号</section>${data.questions.map(q=>`<section class="card"><h2>${e(q.title)}</h2><p class="muted">有效回答 ${q.answered} 份 · ${q.respondentCount} 个账号${q.kind==='number'?` · 平均值 ${e(q.average??'暂无数据')}`:''}</p>${q.options?q.options.map(o=>`<div class="statline"><span>${e(o.label)}</span><strong>${o.count} 份 · ${o.respondentCount} 个账号</strong></div>`).join(''):`<div id="contents-${q.questionId}">${contents(q)}</div>`}</section>`).join('')}`;}
function contents(q){return `<div class="scroll"><table><thead><tr><th>内容</th><th>填写者</th><th>提交时间</th></tr></thead><tbody>${q.contents.map(r=>`<tr><td class="prewrap">${e(r.value)}</td><td>${e(r.author)}</td><td>${e(dateLabel(r.submittedAt))}</td></tr>`).join('')}</tbody></table></div>${!q.contents.length?'<p class="muted">暂无填写内容</p>':''}<div class="actions"><button data-action="content-page" data-id="${q.questionId}" data-skip="${Math.max(0,q.skip-q.limit)}" ${q.skip===0?'disabled':''}>上一页</button><button data-action="content-page" data-id="${q.questionId}" data-skip="${q.skip+q.limit}" ${q.hasMore?'':'disabled'}>下一页</button></div>`;}
function newCondition(q){return {op:q.kind==='multiple'?'any':'eq',value:q.kind==='number'?'0':q.kind==='multiple'?[q.options[0]?.id??'']:q.options[0]?.id??''};}
document.addEventListener('submit',async ev=>{ev.preventDefault();if(ev.target.id!=='auth-form')return;const b=$('button[type=submit]',ev.target);b.disabled=true;try{const d=new FormData(ev.target);await api('/api/login','POST',Object.fromEntries(d));await boot();}catch(err){if(pickerState&&$('#picker-message')){$('#picker-message').textContent=err.message;$('#picker-message').className='error';}else notice(err.message);}finally{b.disabled=false;}});
document.addEventListener('input',ev=>{if(ev.target.closest('#metadata,.question'))markDirty();});
document.addEventListener('change',ev=>{if(ev.target.closest('#metadata,.question'))markDirty();if(ev.target.name!=='kind')return;collect();const q=survey.questions[Number(ev.target.dataset.index)];if(q.sourceVersionId)return;q.kind=ev.target.value;q.validation={};q.jumpRules=[];q.options=['single','multiple'].includes(q.kind)?[{id:uid(),label:'选项 A'},{id:uid(),label:'选项 B'}]:[];if(reusableEditing)renderReusableEditor();else renderEditor();});
document.addEventListener('click',async ev=>{const b=ev.target.closest('[data-action]');if(!b||b.disabled)return;const action=b.dataset.action,i=Number(b.dataset.index),j=Number(b.dataset.rule);b.disabled=true;try{
  const leaving=['list','rq-list','mg-shared','mg-banks','logout','edit','new','stats','mg-stats','mg-usage','rq-detail','rq-edit','rq-branch','ui-question-tab','ui-version','ui-shared-detail','ui-back-question'];
  if(leaving.includes(action)&&!pickerState&&!leaveEditor())return;
  if(action.startsWith('ui-')){
    const currentPicker=action.startsWith('ui-picker-')?pickerState:null;
    if(currentPicker?.busy)return;
    if(currentPicker)currentPicker.busy=true;
    try{await workspaceAction(action,b);}finally{if(currentPicker)currentPicker.busy=false;}
    return;
  }
  if(action.startsWith('mg-')){await managementAction(action,b);return;}
  if(action.startsWith('rq-')){await reusableAction(action,b);return;}
  if(action==='register'){const form=$('#auth-form');if(!form.reportValidity())return;await api('/api/register','POST',Object.fromEntries(new FormData(form)));notice('注册成功，现在可以登录');}
  else if(action==='logout'){await api('/api/logout','POST',{});me=null;account();auth();}
  else if(action==='list'){listSkip=0;await list();}
  else if(action==='list-next'||action==='list-prev'){listSkip+=action==='list-next'?12:-12;await list();}
  else if(action==='new'){editorDirty=false;activeQuestion=0;survey=await api('/api/surveys','POST',{title:'未命名问卷'});renderEditor();}
  else if(action==='edit'){editorDirty=false;activeQuestion=0;survey=await api(`/api/surveys/${b.dataset.id}`);renderEditor();}
  else if(action==='save')await save();
  else if(action==='publish'){await save();if(!confirm('发布后题目与填写设置将冻结，确认发布？'))return;survey=await api(`/api/surveys/${survey.id}/publish`,'POST',{editRevision:survey.editRevision});renderEditor();notice('问卷已发布，可以复制链接');}
  else if(action==='close'){if(!confirm('关闭后不能重开，确认关闭？'))return;survey=await api(`/api/surveys/${survey.id}/close`,'POST',{editRevision:survey.editRevision});renderEditor();notice('问卷已关闭');}
  else if(action==='preview'){await save();await startFill('',true);}
  else if(action==='end-preview'){filling=null;renderEditor();}
  else if(action==='copy'){await navigator.clipboard.writeText(`${location.origin}/survey/${b.dataset.token}`);notice('链接已复制');}
  else if(action==='stats')await statistics(b.dataset.id);
  else if(action==='content-page'){const q=await api(`/api/surveys/${survey.id}/questions/${b.dataset.id}/stats?skip=${b.dataset.skip}&limit=20`);$(`#contents-${q.questionId}`).innerHTML=contents(q);}
  else if(action==='next-answer')await nextAnswer();
  else if(action==='back-answer')revise(filling.path[filling.path.length-2]);
  else if(action==='revise')revise(b.dataset.id);
  else if(action==='submit-answer'){if(filling.preview){notice('预览完成，未保存任何答卷');filling=null;renderEditor();return;}await api(`/api/fill/${filling.token}/submit`,'POST',{answers:Object.entries(filling.answers).map(([questionId,value])=>({questionId,value})),submissionKey:filling.key,anonymous:$('#anonymous').checked});root.innerHTML='<div class="narrow card empty"><span class="badge">提交成功</span><h1>感谢你的回答</h1><p class="muted">本次答卷已保存。</p><a class="button" href="/">返回工作台</a></div>';}
  else {collect();markDirty();activeQuestion=Number.isFinite(i)?i:survey.questions.length;const q=survey.questions[i];
    if(action==='add-question')survey.questions.push({id:uid(),kind:'single',title:'新的问题',required:true,options:[{id:uid(),label:'选项 A'},{id:uid(),label:'选项 B'}],validation:{},jumpRules:[]});
    else if(action==='remove-question'){if(!confirm('移除题目后需检查指向它的跳转规则，继续？'))return;survey.questions.splice(i,1);activeQuestion=Math.max(0,i-1);}
    else if(action==='up'||action==='down'){const k=i+(action==='up'?-1:1);[survey.questions[i],survey.questions[k]]=[survey.questions[k],survey.questions[i]];activeQuestion=k;}
    else if(action==='add-option')q.options.push({id:uid(),label:'新选项'});
    else if(action==='remove-option')q.options.splice(Number(b.dataset.option),1);
    else if(action==='add-rule')q.jumpRules.push({conditions:[newCondition(q)],target:'END'});
    else if(action==='remove-rule')q.jumpRules.splice(j,1);
    else if(action==='add-condition')q.jumpRules[j].conditions.push(newCondition(q));
    else if(action==='remove-condition')q.jumpRules[j].conditions.splice(Number(b.dataset.condition),1);
    if(reusableEditing)renderReusableEditor();else renderEditor();}
}catch(err){notice(err.message);}finally{b.disabled=false;}});
boot().catch(err=>{root.innerHTML='<div class="card"><h1>暂时无法打开问卷</h1><p id="load-error"></p><a href="/">返回工作台</a></div>';$('#load-error').textContent=err.message;});


async function requestText(label,value=''){
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.className='card';
    dialog.innerHTML=`<form id="text-dialog-form"><label><span>${e(label)}</span><input name="dialog-value" value="${e(value)}" maxlength="200" required autofocus></label><div class="actions"><button type="submit" class="primary">确定</button><button type="button" name="cancel">取消</button></div></form>`;
    const finish=result=>{dialog.close();dialog.remove();resolve(result);};
    dialog.querySelector('form').addEventListener('submit',ev=>{ev.preventDefault();finish(dialog.querySelector('input').value);});
    dialog.querySelector('[name=cancel]').addEventListener('click',()=>finish(null));
    dialog.addEventListener('cancel',ev=>{ev.preventDefault();finish(null);});
    document.body.append(dialog);dialog.showModal();
  });
}

function seedQuestion(){return {id:'content',kind:'single',title:'新的问题',required:false,options:[{id:uid(),label:'选项 A'},{id:uid(),label:'选项 B'}],validation:{},jumpRules:[]};}
function pureContent(q){return Object.fromEntries(['kind','title','options','validation'].map(k=>[k,q[k]]));}
async function reusableList(){
  reusableEditing=null;questionView=null;editorDirty=false;filling=null;setArea('questions');
  const request=workspaceRequest,rows=await api(`/api/reusable-questions?archived=${reusableArchived}&skip=${reusableSkip}&limit=12`);
  if(request!==workspaceRequest)return;
  root.innerHTML=`<div class="hero"><div><span class="eyebrow">可复用题目</span><h1>题目中心</h1><p class="muted">把常用题独立保存，按准确版本选入问卷。</p></div><button data-action="rq-new" class="primary">＋ 新建题目</button></div>${questionTabs()}<div class="list-toolbar"><span class="muted">${reusableArchived?'已归档题目':'我的题目'}</span><button data-action="rq-archived">${reusableArchived?'查看未归档':'查看已归档'}</button></div><div class="item-list">${rows.map(q=>`<section class="list-row"><div><h2>${e(q.name)}</h2><p class="muted">${q.pendingSave?'保存待完成':q.latestVersion?`最新正式版 V${q.latestVersion.versionNo} · 题干：${e(q.latestVersion.content.title)}`:'尚无正式版'}${q.draft?' · 有草稿':''}</p></div><div class="actions compact"><button data-action="rq-detail" data-id="${q.id}">打开题目</button>${moreMenu(`<button data-action="ui-rename" data-id="${q.id}">重命名</button><button data-action="rq-archive" data-id="${q.id}">${q.archived?'取消归档':'归档'}</button>`)}</div></section>`).join('')||'<div class="empty">此列表暂无题目。</div>'}</div><div class="pagination"><button data-action="rq-prev" ${reusableSkip?'':'disabled'}>上一页</button><button data-action="rq-next" ${rows.length===12?'':'disabled'}>下一页</button></div>`;
}
async function reusableEditor(id,version=null){setArea('questions');const request=workspaceRequest,q=await api(`/api/reusable-questions/${id}`);if(request!==workspaceRequest)return;if(q.pendingSave){await reusableDetailPage(id);notice('请先完成中断保存');return;}editorDirty=false;questionView=null;reusableEditing=q;reusableName=q.name;const draft=version?{baseVersionId:version.id,content:version.content}:q.draft||{baseVersionId:q.latestVersion?.id??null,content:q.latestVersion?.content??pureContent(seedQuestion())};reusableBase=draft.baseVersionId;survey={questions:[{id:'content',...structuredClone(draft.content),required:false,jumpRules:[]}]};renderReusableEditor();}
function renderReusableEditor(){
  root.innerHTML=`<div class="breadcrumb"><button data-action="rq-list">题目中心</button><span> / </span><button data-action="ui-back-question" data-id="${reusableEditing.id}">${e(reusableEditing.name)}</button><span> / 编辑内容</span></div><div class="hero"><div><h1>编辑题目内容</h1><p class="muted">管理名称：${e(reusableEditing.name)} · ${reusableBase?'基于已有版本编辑':'准备首版'}。必答和跳转在具体问卷中设置。</p></div></div><div class="editor-toolbar"><span id="save-state" class="${editorDirty?'dirty':'muted'}">${editorDirty?'有未保存的修改':reusableEditing.draft?'已载入草稿':'尚未保存本次编辑'}</span><div class="actions compact"><button data-action="rq-draft">保存草稿</button><button class="primary" data-action="rq-version">保存正式新版本</button></div></div><p class="help">正式版本保存后内容固定。本次保存将产生新版本，已有版本和问卷保持不变；修改管理名称请返回题目详情。</p>${questionEditor(survey.questions[0],0,false,true)}`;
}
async function reusableDetailPage(id,versionId=null,tab='content'){
  reusableEditing=null;editorDirty=false;setArea('questions');
  const request=workspaceRequest;
  const model=await api(`/api/reusable-questions/${id}`);
  const rows=await api(`/api/reusable-questions/${id}/versions?skip=${reusableVersionSkip}&limit=20`);
  const version=versionId?rows.find(v=>v.id===versionId)||await api(`/api/question-versions/${versionId}`):model.latestVersion;
  if(request!==workspaceRequest)return;
  reusableDetail=model;
  questionView={id,vid:version?.id,version,owned:true,tab,rows};
  renderQuestionWorkspace();await loadQuestionPanel();
}
async function sharedDetail(vid,tab='content'){
  reusableEditing=null;editorDirty=false;setArea('questions');
  const request=workspaceRequest,version=await api(`/api/question-versions/${vid}`);
  if(request!==workspaceRequest)return;
  questionView={id:version.questionId,vid,version,owned:false,tab,rows:[version]};
  renderQuestionWorkspace();await loadQuestionPanel();
}
function renderQuestionWorkspace(){
  const q=questionView,v=q.version,owner=q.owned,model=owner?reusableDetail:null;
  const tabs={content:'内容与版本',usage:'使用情况',stats:'跨问卷统计',...(owner?{shares:'共享管理'}:{})};
  root.innerHTML=`<div class="breadcrumb"><button data-action="${owner?'rq-list':'mg-shared'}">题目中心</button><span> / ${owner?'我的题目':'共享给我'}</span></div><div class="hero"><div><span class="eyebrow">${owner?'题目管理名称':'共享题目 · 仅此授权版本'}</span><h1>${e(owner?model.name:v.content.title)}</h1><p class="muted">${owner?'管理名称用于分类查找；下方版本题干才是填写者看到的内容。':'来源关系不授予其他版本或他人问卷的访问权。'}</p></div>${owner?moreMenu(`<button data-action="ui-rename" data-id="${q.id}">重命名管理名称</button><button data-action="rq-archive" data-id="${q.id}">${model.archived?'取消归档':'归档题目'}</button>`):''}</div>
  ${model?.pendingSave?`<section class="help"><strong>有中断的版本保存</strong><p>${e(model.pendingSave.content?.title??'预留损坏，需要核查备份')}</p><button data-action="rq-recover" data-id="${q.id}" ${model.pendingSave.needsRepair?'disabled':''}>完成中断保存</button></section>`:''}
  <div class="version-bar"><label>当前准确版本 ${owner&&v?`<select id="workspace-version" aria-label="当前准确版本">${[...(q.rows.some(x=>x.id===v.id)?[]:[v]),...q.rows].map(x=>`<option value="${x.id}" ${selected(x.id,v.id)}>V${x.versionNo} · ${e(x.content.title)}</option>`).join('')}</select>`:`<strong>${v?'V'+v.versionNo:'尚无正式版本'}</strong>`}</label>${owner?`<span class="muted">${model.archived?'已归档 · 不能新选用':model.draft?'有未正式保存的草稿':'正式内容只读'}</span>`:''}</div>
  <div class="tabs" role="tablist" aria-label="题目详情">${Object.entries(tabs).map(([k,label])=>`<button role="tab" aria-selected="${q.tab===k}" class="${q.tab===k?'active':''}" data-action="ui-question-tab" data-tab="${k}" ${!v&&k!=='content'?'disabled':''}>${label}</button>`).join('')}</div><div id="question-panel" role="tabpanel"></div>`;
}
async function loadQuestionPanel(){
  const q=questionView,v=q.version;
  if(q.tab==='usage')return usagePage(q.owned?q.id:q.vid,q.owned);
  if(q.tab==='stats')return crossPage(q.vid);
  if(q.tab==='shares')return sharesPage(q.vid);
  $('#question-panel').innerHTML=`<section class="card">${v?`${renderVersionContent(v)}<div class="actions">${q.owned?`<button class="primary" data-action="rq-branch" data-id="${v.id}">基于此版编辑</button>`:`<button class="primary" data-action="mg-derive" data-id="${v.id}">派生为我的题目</button>`}<button data-action="mg-bank-add" data-id="${v.id}">加入题库</button>${q.owned?moreMenu(`<button data-action="rq-restore" data-id="${v.id}">用此版内容生成新版本</button><button data-action="mg-derive" data-id="${v.id}">派生为另一个题目</button>`):''}</div><details class="source-details"><summary data-action="ui-source" data-id="${v.id}">查看来源关系</summary><div class="version-history" hidden></div></details>`:'<h2>尚无正式版本</h2><p>先编辑内容，再保存正式版本供问卷选用。</p>'}${q.owned?`<div class="draft-note"><span>${reusableDetail.draft?'本题目有已保存草稿，可继续编辑。':'可从已有草稿或最新正式版开始编辑。'}</span><button data-action="rq-edit" data-id="${q.id}">${reusableDetail.draft?'继续编辑草稿':'编辑最新内容'}</button></div>`:''}</section>${q.owned&&q.rows.length?`<details class="card version-list"><summary>版本记录 · 当前页 ${q.rows.length} 版</summary>${q.rows.map(x=>`<div class="list-row"><div><strong>V${x.versionNo} · ${e(x.content.title)}</strong><p class="muted">${x.parentVersionId?'基于已有版本创建':'首版 / 派生起点'}${x.id===q.vid?' · 当前查看':''}</p></div><button data-action="ui-version" data-id="${x.id}">查看此版</button></div>`).join('')}<div class="pagination"><button data-action="rq-version-prev" ${reusableVersionSkip?'':'disabled'}>上一页版本</button><button data-action="rq-version-next" ${q.rows.length===20?'':'disabled'}>下一页版本</button></div></details>`:''}`;
}
function renderVersionContent(v,showTitle=true){
  const c=v.content;
  return `<div class="version-content">${v.versionNo?`<span class="badge">V${v.versionNo} · ${e(kinds[c.kind])}</span>`:`<p class="muted">${e(kinds[c.kind])}</p>`}${showTitle?`<h2>${e(c.title)}</h2>`:''}${c.options.length?`<ol class="option-preview">${c.options.map(o=>`<li>${e(o.label)}</li>`).join('')}</ol>`:''}<p class="muted">校验：${e(constraintText(c))}</p></div>`;
}
// 选题弹窗保留背景编辑上下文；只有实际选入时才保存并调用新增/换版接口。
async function picker(qid=null,localId=null,skip=0){
  collect();pickerState={qid,localId,skip,source:'mine',added:0,required:true};
  const dialog=document.createElement('dialog');dialog.id='question-picker';dialog.className='picker-dialog';
  dialog.innerHTML='<div id="picker-content"><div class="dialog-head"><h2>选择题目</h2><button data-action="ui-picker-close">关闭</button></div><div id="picker-message" role="status">正在载入…</div></div>';
  dialog.addEventListener('cancel',ev=>{ev.preventDefault();closePicker();});
  document.body.append(dialog);dialog.showModal();await renderPicker();
}
function closePicker(){const dialog=$('#question-picker');if(dialog){dialog.close();dialog.remove();}pickerState=null;}
async function renderPicker(){
  const p=pickerState,local=p.localId,skip=p.skip,limit=p.qid?20:12;
  let rows,bankName='';
  if(p.qid)rows=await availableVersions(p.qid,skip);
  else if(p.source==='shared')rows=await api(`/api/shared-question-versions?skip=${skip}&limit=12`);
  else if(p.source==='banks'&&p.bank){const bank=await api(`/api/question-banks/${p.bank}`);bankName=bank.name;rows=await api(`/api/question-banks/${p.bank}/items?skip=${skip}&limit=12`);}
  else rows=await api(`/api/${p.source==='banks'?'question-banks':'reusable-questions'}?skip=${skip}&limit=12`);
  // Esc 或“完成”可能在读取列表期间关闭弹窗，迟到结果不可写入已移除节点。
  if(pickerState!==p||!$('#picker-content'))return;
  $('#picker-content').innerHTML=`<div class="dialog-head"><div><h2>${local?'主动换版':'添加问卷题目'}</h2><p class="muted">${local?'仅选择同一题目的其他版本；保留当前卷内位置。':'每次选入产生独立位置，可连续加入同一版本。'}</p></div><button data-action="ui-picker-close">${local?'取消':'完成'}</button></div>${!local?`<div class="tabs">${Object.entries({new:'新建普通题',mine:'我的题目',shared:'共享给我',banks:'个人题库'}).map(([k,n])=>`<button data-action="ui-picker-source" data-source="${k}" class="${p.source===k?'active':''}">${n}</button>`).join('')}</div><label><input type="checkbox" id="rq-required" ${p.required?'checked':''}> 新位置必须回答</label>`:''}<div id="picker-message" role="status">${p.message?e(p.message):p.added?`本次已加入 ${p.added} 个独立位置。`:'请选择题目和准确版本。'}</div>${(p.qid&&!local)||p.bank?`<button class="text-button" data-action="ui-picker-back">← ${p.bank?'返回题库列表':'返回题目列表'}</button><p class="muted">${e(bankName)}</p>`:''}<div class="picker-rows">${rows.map(x=>{
    const v=p.qid?x:p.source==='shared'?x.version:p.bank?x.version:null;
    if(v){const count=survey.questions.filter(q=>q.sourceVersionId===v.id).length;return `<section class="list-row"><div><strong>V${v.versionNo} · ${e(v.content.title)}</strong><p class="muted">${e(kinds[v.content.kind])}${count?` · 本卷已用 ${count} 次`:''}${x.selectable===false?' · 当前不能新选用':''}</p><details><summary>内容预览</summary>${renderVersionContent(v)}</details></div><button class="primary" data-action="ui-picker-add" data-id="${v.id}" ${x.selectable===false?'disabled':''}>${local?'换为此版':count?'再次加入':'加入'}</button></section>`;}
    if(p.bank)return '<section class="list-row"><p>来源不可访问，不能新选用。</p></section>';
    return `<section class="list-row"><div><strong>${e(x.name)}</strong>${p.source==='mine'?`<p class="muted">${x.latestVersion?'最新 V'+x.latestVersion.versionNo:'尚无正式版'}</p>`:''}</div><button data-action="ui-picker-open" data-id="${x.id}" ${p.source==='mine'&&!x.latestVersion?'disabled':''}>${p.source==='banks'?'打开题库':'选择版本'}</button></section>`;
  }).join('')||'<div class="empty">暂无可选内容。可切换来源，或先保存一个正式题目版本。</div>'}</div>${pageButtons('ui-picker-page',skip,limit,rows.length===limit)}`;
}
async function reusableAction(action,b){
  if(action==='rq-list'){reusableSkip=0;await reusableList();}
  else if(action==='rq-prev'||action==='rq-next'){reusableSkip+=action==='rq-next'?12:-12;await reusableList();}
  else if(action==='rq-archived'){reusableArchived=!reusableArchived;reusableSkip=0;await reusableList();}
  else if(action==='rq-new'){const name=await requestText('题目管理名称','常用题目');if(!name)return;const q=await intent('/api/reusable-questions','POST',{name},'creationKey');await reusableEditor(q.id);}
  else if(action==='rq-edit')await reusableEditor(b.dataset.id);
  else if(action==='rq-detail'){reusableVersionSkip=0;await reusableDetailPage(b.dataset.id);}
  else if(action==='rq-version-prev'||action==='rq-version-next'){reusableVersionSkip+=action==='rq-version-next'?20:-20;await reusableDetailPage(reusableDetail.id,questionView?.vid,questionView?.tab||'content');}
  else if(action==='rq-branch'){const v=await api(`/api/question-versions/${b.dataset.id}`);await reusableEditor(v.questionId,v);}
  else if(action==='rq-draft'||action==='rq-version'){
    collect();const content=pureContent(survey.questions[0]),name=reusableEditing.name;
    if(action==='rq-draft'){reusableEditing=await api(`/api/reusable-questions/${reusableEditing.id}`,'PATCH',{name,draft:{baseVersionId:reusableBase,content},editRevision:reusableEditing.editRevision});editorDirty=false;renderReusableEditor();notice('草稿已保存，正式版本未改变');}
    else {const id=reusableEditing.id;if(name.trim()!==reusableEditing.name)reusableEditing=await api(`/api/reusable-questions/${id}`,'PATCH',{name,editRevision:reusableEditing.editRevision});await intent(`/api/reusable-questions/${id}/versions`,'POST',{content,baseVersionId:reusableBase,editRevision:reusableEditing.editRevision},'creationKey');reusableVersionSkip=0;await reusableDetailPage(id);notice('新版本已保存，问卷保持原版本');}
  }
  else if(action==='rq-restore'){if(!confirm('将内容恢复为一个新版本，已有问卷不会改版。继续？'))return;const q=await api(`/api/reusable-questions/${reusableDetail.id}`);await intent(`/api/reusable-questions/${q.id}/restore`,'POST',{versionId:b.dataset.id,editRevision:q.editRevision},'creationKey');reusableVersionSkip=0;await reusableDetailPage(q.id);}
  else if(action==='rq-recover'){const q=await api(`/api/reusable-questions/${b.dataset.id}`);if(!q.pendingSave){await reusableDetailPage(q.id);return;}await api(`/api/reusable-questions/${q.id}/recover-save`,'POST',{operationId:q.pendingSave.operationId,editRevision:q.editRevision});await reusableDetailPage(q.id);notice('中断保存已完成');}
  else if(action==='rq-archive'){const inside=questionView;const q=await api(`/api/reusable-questions/${b.dataset.id}`);await api(`/api/reusable-questions/${q.id}`,'PATCH',{archived:!q.archived,editRevision:q.editRevision});if(inside)await reusableDetailPage(q.id,inside.vid,inside.tab);else await reusableList();}
  else if(action==='rq-history-next') {
    const history = await api(`/api/question-versions/${b.dataset.id}/history`);
    b.closest('.version-history').insertAdjacentHTML('beforeend', renderHistory(history));
    b.remove();
  }
  else if(action==='rq-export')await exportReusable(Number(b.dataset.index));
  else if(action==='rq-picker')await picker();
  else if(action==='rq-upgrade-picker'){const i=Number(b.dataset.index);collect();await picker(survey.questions[i].sourceQuestionId,survey.questions[i].id);}

}


let bankReturn=null, sharedSkip=0, bankArchived=false, bankCurrent=null, crossCurrent=null, crossSelected=null, usageCurrent=null;

async function availableVersions(qid, skip = 0) {
  try {
    return await api(`/api/reusable-questions/${qid}/versions?skip=${skip}&limit=20`);
  } catch (error) {
    // 仅在本人题目系列不可访问时尝试共享版本，登录或服务异常继续向上传递。
    if (error.status !== 404) throw error;
    const shared = await api(`/api/shared-question-versions?questionId=${encodeURIComponent(qid)}&skip=${skip}&limit=20`);
    return shared.map(item => item.version);
  }
}
function pageButtons(action,skip,limit,more,extra=''){return `<div class="actions"><button data-action="${action}" data-skip="${Math.max(0,skip-limit)}" ${extra} ${skip?'':'disabled'}>上一页</button><button data-action="${action}" data-skip="${skip+limit}" ${extra} ${more?'':'disabled'}>下一页</button></div>`;}
async function sharedPage(skip=0){
  sharedSkip=skip;questionView=null;reusableEditing=null;editorDirty=false;setArea('questions');
  const request=workspaceRequest,rows=await api(`/api/shared-question-versions?skip=${skip}&limit=12`);
  if(request!==workspaceRequest)return;
  root.innerHTML=`<div class="hero"><div><span class="eyebrow">可复用题目</span><h1>题目中心</h1><p class="muted">共享只开放指定版本；撤销后已有问卷继续有效。</p></div></div>${questionTabs(true)}<div class="item-list">${rows.map(x=>`<section class="list-row"><div><h2>${e(x.version.content.title)}</h2><p class="muted">V${x.version.versionNo} · ${e(kinds[x.version.content.kind])} · 共享者 ${e(x.owner)}</p></div><button data-action="ui-shared-detail" data-id="${x.version.id}">查看题目</button></section>`).join('')||'<div class="empty">暂无有效共享版本。</div>'}</div>${pageButtons('mg-shared',skip,12,rows.length===12)}`;
}
function workspacePanel(tab,vid,html){
  if(questionView?.tab===tab&&(!vid||questionView.vid===vid))$('#question-panel').innerHTML=html;
  else {questionView=null;root.innerHTML=html;}
}
async function sharesPage(vid,skip=0){
  const request=workspaceRequest,rows=await api(`/api/question-versions/${vid}/shares?skip=${skip}&limit=20`);
  if(request!==workspaceRequest)return;
  reusableEditing=null;
  workspacePanel('shares',vid,`<section class="card"><h2>授权当前版本</h2><p class="muted">仅共享此版题目，不开放问卷与答案。撤销不影响此前保存的草稿和自有派生题。</p><div class="inline-form"><label><span>接收者用户名</span><input id="share-username" maxlength="40" placeholder="输入已注册账号"></label><button class="primary" data-action="mg-grant" data-id="${vid}">授权此版</button></div></section><div class="item-list">${rows.map(x=>`<section class="list-row"><div><strong>${e(x.username)}</strong><p class="muted">${x.active?'有效共享':'已撤销'}</p></div><button ${x.active?'class="danger"':''} data-action="mg-share-change" data-id="${vid}" data-user="${x.recipientId}" data-revision="${x.editRevision}" data-active="${!x.active}">${x.active?'撤销共享':'重新授权'}</button></section>`).join('')||'<div class="empty">此版本尚未共享。</div>'}</div>${pageButtons('mg-shares',skip,20,rows.length===20,`data-id="${vid}"`)}`);
}

async function banksPage(skip=0,purpose=null,vid=null){
  questionView=null;editorDirty=false;reusableEditing=null;setArea('banks');
  const request=workspaceRequest,adding=purpose==='add',rows=await api(`/api/question-banks?archived=${adding?'false':bankArchived}&skip=${skip}&limit=12`);
  if(request!==workspaceRequest)return;
  root.innerHTML=`<div class="hero"><div><span class="eyebrow">个人分类</span><h1>${adding?'选择加入的题库':'个人题库'}</h1><p class="muted">分类、换版和归档不会修改任何已有问卷。</p></div>${adding?'<button data-action="mg-bank-cancel">取消并返回</button>':'<button class="primary" data-action="mg-bank-new">＋ 新建题库</button>'}</div>${!adding?`<div class="list-toolbar"><span class="muted">${bankArchived?'已归档分类':'我的分类'}</span><button data-action="mg-bank-archived">${bankArchived?'查看未归档':'查看已归档'}</button></div>`:''}<div class="item-list">${rows.map(b=>`<section class="list-row"><div><h2>${e(b.name)}</h2><p class="muted">${b.archived?'已归档':'个人分类'}</p></div><div class="actions compact">${adding?`<button class="primary" data-action="mg-bank-confirm" data-id="${b.id}" data-version="${vid}">加入此库</button>`:`<button data-action="mg-bank-items" data-id="${b.id}">打开题库</button>${moreMenu(`<button data-action="mg-bank-name" data-id="${b.id}">重命名</button><button data-action="mg-bank-archive" data-id="${b.id}">${b.archived?'取消归档':'归档'}</button>`)}`}</div></section>`).join('')||'<div class="empty">暂无题库，请先在个人题库新建。</div>'}</div>${pageButtons('mg-banks',skip,12,rows.length===12,`data-purpose="${purpose??''}" data-version="${vid??''}"`)}`;
}
async function bankItemsPage(bid,skip=0){
  questionView=null;editorDirty=false;reusableEditing=null;setArea('banks');
  const request=workspaceRequest,bank=await api(`/api/question-banks/${bid}`);
  const rows=await api(`/api/question-banks/${bid}/items?skip=${skip}&limit=12`);
  if(request!==workspaceRequest)return;
  bankCurrent=bank;
  root.innerHTML=`<div class="breadcrumb"><button data-action="mg-banks">个人题库</button><span> / ${e(bankCurrent.name)}</span></div><div class="hero"><div><h1>${e(bankCurrent.name)}${bankCurrent.archived?'（已归档）':''}</h1><p class="muted">从题目详情的“加入题库”添加分类关联；同一题目在本库固定一个版本。</p></div></div><div class="item-list">${rows.map(x=>`<section class="list-row"><div><h2>${x.accessible?`V${x.version.versionNo} · ${e(x.version.content.title)}`:'来源不可访问'}</h2><p class="muted">${x.selectable?'选题时使用此准确版本':'当前不能新选用；原问卷不受影响'}</p>${x.accessible?`<details><summary>查看题目内容</summary>${renderVersionContent(x.version)}</details>`:''}</div>${moreMenu(`<button data-action="mg-item-upgrade" data-id="${x.id}" data-question="${x.questionId}" data-revision="${x.editRevision}" ${bankCurrent.archived?'disabled':''}>主动换版</button><button class="danger" data-action="mg-item-remove" data-id="${x.id}" data-revision="${x.editRevision}">移除分类关联</button>`)}</section>`).join('')||'<div class="empty">本库暂无题目。</div>'}</div>${pageButtons('mg-bank-items',skip,12,rows.length===12,`data-id="${bid}"`)}`;
}
async function usagePage(id,series=false,skip=0){
  const request=workspaceRequest;usageCurrent={id,series};const data=await api(`/api/${series?'reusable-questions':'question-versions'}/${id}/usages?skip=${skip}&limit=20`);
  if(request!==workspaceRequest)return;
  const inWorkspace=questionView?.tab==='usage';
  const versionLabels=new Map((questionView?.rows||[]).map(v=>[v.id,`V${v.versionNo}`]));
  workspacePanel('usage',null,`${inWorkspace?'':`<div class="breadcrumb"><button data-action="rq-list">题目中心</button></div>`}<section class="card"><div class="section-title"><div><h2>使用情况</h2><p class="muted">只显示本人管理的问卷${series?'，包含本题目的所有版本':'，仅当前准确版本'}。</p></div>${questionView?.owned?`<div class="actions compact"><button data-action="ui-usage-scope" data-series="false" ${series?'':'disabled'}>当前版本</button><button data-action="ui-usage-scope" data-series="true" ${series?'disabled':''}>全部版本</button></div>`:''}</div>${data.items.map(x=>`<div class="list-row"><div><h3>${e(x.title)}</h3><p class="muted">${{draft:'草稿',published:'已发布',closed:'已关闭'}[x.status]} · ${versionLabels.get(x.versionId)||(series?'其他历史版本（展开标识核对）':'此固定版本')} · ${x.occurrenceCount} 个独立位置</p><details><summary>版本与位置标识</summary><p class="muted">版本：${e(x.versionId)}<br>位置：${x.questionIds.map(e).join('、')}</p></details></div><button data-action="edit" data-id="${x.surveyId}">管理问卷</button></div>`).join('')||'<p class="muted">本人暂无使用位置。</p>'}${pageButtons('mg-usage-page',skip,20,data.hasMore)}</section>`);
}
function crossQuery(){const p=new URLSearchParams();if(crossSelected!==null)for(const id of crossSelected)p.append('surveyId',id);return p;}
async function crossPage(vid,reset=true){
  const request=workspaceRequest;
  if(reset){crossSelected=null;crossCurrent={vid};}const params=crossQuery();const data=await api(`/api/question-versions/${vid}/stats?${params}`);
  if(request!==workspaceRequest)return;
  crossCurrent={...crossCurrent,vid,data};
  const embedded=questionView?.tab==='stats'&&questionView.vid===vid;
  workspacePanel('stats',vid,`${embedded?'':`<div class="breadcrumb"><button data-action="rq-list">题目中心</button></div><h1>${e(data.title)} · 跨问卷统计</h1>`}<p class="muted">范围：此准确版本、本人相关问卷。重复位置分别计条数，账号在整个范围去重；匿名不显示身份。</p>${embedded?'':`<details><summary>快照版本标识</summary><p class="muted">${e(vid)}</p></details>`}<section class="card"><div class="metrics"><div><strong>${data.answerCount}</strong><span>条有效回答</span></div><div><strong>${data.responseCount}</strong><span>份答卷</span></div><div><strong>${data.respondentCount}</strong><span>个去重账号</span></div></div><p>当前包含 ${data.surveyIds.length} 份相关问卷${crossSelected===null?'（全部本人相关问卷）':'（已筛选）'}</p><button data-action="mg-scope">选择问卷范围</button><button data-action="mg-scope-all">恢复全部范围</button></section>${data.kind==='number'?`<section class="card"><p>平均 ${e(data.average??'暂无')} · 最小 ${e(data.minimum??'暂无')} · 最大 ${e(data.maximum??'暂无')}</p></section>`:''}${data.options.map(o=>`<section class="card"><h2>${e(o.label)}</h2><p>${o.answerCount} 条 · ${o.responseCount} 份 · ${o.respondentCount} 个账号</p></section>`).join('')}<div id="cross-detail"></div><div id="cross-distribution"></div>`);
  if(['text','number'].includes(data.kind))await crossRows('contents',0);
  if(data.kind==='number')await crossRows('distribution',0);
}
async function crossRows(type,skip){
  const request=workspaceRequest,vid=crossCurrent.vid;
  const p=crossQuery();p.set('skip',skip);p.set('limit',20);const data=await api(`/api/question-versions/${crossCurrent.vid}/${type}?${p}`);
  if(request!==workspaceRequest||vid!==crossCurrent.vid)return;
  const distribution=type==='distribution';const panel=distribution?'#cross-distribution':'#cross-detail';
  if(!$(panel))return;
  $(panel).innerHTML=`<section class="card"><h2>${distribution?'数字分布':'有效回答明细'}</h2><div class="scroll"><table><thead><tr>${distribution?'<th>数值</th><th>回答条数</th>':'<th>问卷 / 位置</th><th>值</th><th>填写者</th><th>时间</th>'}</tr></thead><tbody>${data.items.map(x=>distribution?`<tr><td>${e(x.value)}</td><td>${x.answerCount}</td></tr>`:`<tr data-entry="${e(x.entryId)}"><td>${e(x.surveyTitle)}<details><summary>位置标识</summary><span class="muted">${e(x.questionId)}</span></details></td><td class="prewrap">${e(x.value)}</td><td>${e(x.author)}</td><td>${e(dateLabel(x.submittedAt))}</td></tr>`).join('')}</tbody></table></div>${!data.items.length?'<p>暂无有效回答。</p>':''}${pageButtons('mg-cross-page',skip,20,data.hasMore,`data-type="${type}"`)}</section>`;
}
async function managementAction(action,b){
  const id=b.dataset.id,skip=Number(b.dataset.skip||0);
  if(action==='mg-shared')await sharedPage(skip);
  else if(action==='mg-derive'){const v=await api(`/api/question-versions/${id}`);const name=await requestText('派生题目的管理名称',v.content.title);if(!name)return;const q=await intent(`/api/question-versions/${id}/derive`,'POST',{name},'creationKey');await reusableDetailPage(q.id);notice('已创建本人独立题目，来源关系保留');}
  else if(action==='mg-shares')await sharesPage(id,skip);
  else if(action==='mg-grant'){await api(`/api/question-versions/${id}/shares`,'POST',{username:$('#share-username').value});await sharesPage(id);}
  else if(action==='mg-share-change'){await api(`/api/question-versions/${id}/shares/${b.dataset.user}`,b.dataset.active==='true'?'PUT':'DELETE',{editRevision:Number(b.dataset.revision)});await sharesPage(id);}
  else if(action==='mg-banks')await banksPage(skip,b.dataset.purpose||null,b.dataset.version||null);
  else if(action==='mg-bank-add'){bankReturn=bankReturnContext(b);bankArchived=false;await banksPage(0,'add',id);}
  else if(action==='mg-bank-confirm'){await api(`/api/question-banks/${id}/items`,'POST',{versionId:b.dataset.version});await returnFromBankSelection();notice('已加入题库，已返回原题目页面');}
  else if(action==='mg-bank-cancel')await returnFromBankSelection();
  else if(action==='mg-bank-new'){const name=await requestText('题库名称');if(!name)return;await api('/api/question-banks','POST',{name});await banksPage();}
  else if(action==='mg-bank-archived'){bankArchived=!bankArchived;await banksPage();}
  else if(action==='mg-bank-name'||action==='mg-bank-archive'){const bank=await api(`/api/question-banks/${id}`);let change;if(action==='mg-bank-name'){const name=await requestText('题库名称',bank.name);if(!name)return;change={name};}else change={archived:!bank.archived};await api(`/api/question-banks/${id}`,'PATCH',{...change,editRevision:bank.editRevision});await banksPage();}
  else if(action==='mg-bank-items')await bankItemsPage(id,skip);
  else if(action==='mg-item-remove'){await api(`/api/question-banks/${bankCurrent.id}/items/${id}`,'DELETE',{editRevision:Number(b.dataset.revision)});await bankItemsPage(bankCurrent.id);}
  else if(action==='mg-item-upgrade'){const rows=await availableVersions(b.dataset.question,skip);root.innerHTML=`<h1>条目主动换版</h1><p>仅更新本库条目，不改变其他题库或问卷。</p><button data-action="mg-bank-items" data-id="${bankCurrent.id}">返回条目</button>${rows.map(v=>`<section class="card">${renderVersionContent(v)}<button data-action="mg-item-version" data-id="${id}" data-version="${v.id}" data-revision="${b.dataset.revision}">条目换为此版</button></section>`).join('')}${pageButtons('mg-item-upgrade',skip,20,rows.length===20,`data-id="${id}" data-question="${b.dataset.question}" data-revision="${b.dataset.revision}"`)}`;}
  else if(action==='mg-item-version'){await api(`/api/question-banks/${bankCurrent.id}/items/${id}`,'PATCH',{versionId:b.dataset.version,editRevision:Number(b.dataset.revision)});await bankItemsPage(bankCurrent.id);}
  else if(action==='mg-usage'||action==='mg-series-usage')await usagePage(id,action==='mg-series-usage');
  else if(action==='mg-usage-page')await usagePage(usageCurrent.id,usageCurrent.series,skip);
  else if(action==='mg-stats')await crossPage(id);
  else if(action==='mg-cross-page')await crossRows(b.dataset.type,skip);
  else if(action==='mg-scope'){const u=await api(`/api/question-versions/${crossCurrent.vid}/usages?skip=${skip}&limit=20`);if(!$('#scope-box'))(questionView?$('#question-panel'):root).insertAdjacentHTML('beforeend','<section class="card" id="scope-box"><h2>选择本人问卷</h2><p>取消的问卷不纳入本次计算；至少选一份。跨页选择会保留。</p><div id="scope-items"></div><div id="scope-pages"></div><button data-action="mg-scope-apply">应用选中范围</button></section>');const known=new Set($$('[name=scope-survey]').map(x=>x.value));$('#scope-items').insertAdjacentHTML('beforeend',u.items.filter(x=>!known.has(x.surveyId)).map(x=>`<label><input name="scope-survey" type="checkbox" value="${x.surveyId}" ${(crossSelected??crossCurrent.data.surveyIds).includes(x.surveyId)?'checked':''}> ${e(x.title)}</label>`).join(''));$('#scope-pages').innerHTML=u.hasMore?`<button data-action="mg-scope" data-skip="${skip+20}">加载更多问卷</button>`:'';}
  else if(action==='mg-scope-apply')await applyCrossScope();
  else if(action==='mg-scope-all')await crossPage(crossCurrent.vid);
}


async function applyCrossScope() {
  const loaded = new Set($$('[name=scope-survey]').map(input => input.value));
  const previous = crossSelected ?? crossCurrent.data.surveyIds;
  const selected = $$('[name=scope-survey]:checked').map(input => input.value);
  // 保留尚未加载到当前表单页的选择，避免翻页保存时丢失。
  const chosen = [...new Set([...previous.filter(id => !loaded.has(id)), ...selected])];
  if (chosen.length > 100) throw new Error('筛选最多100份问卷；也可恢复全部范围');
  if (!chosen.length) throw new Error('请至少选择一份问卷');
  crossSelected = chosen;
  await crossPage(crossCurrent.vid, false);
}


function renderHistory(history) {
  return history.nodes.map(node => node.accessible
    ? `<section class="history-node">${renderVersionContent(node.version)}</section>`
    : '<p>来源不可访问</p>').join('')
    + (history.hasMore ? `<button data-action="rq-history-next" data-id="${history.nextVersionId}">继续查看来源</button>` : '');
}


// Commands that change presentation only; all writes still use the existing API contracts.
async function workspaceAction(action,b){
  if(action==='ui-back-question')await reusableDetailPage(b.dataset.id);
  else if(action==='ui-shared-detail')await sharedDetail(b.dataset.id);
  else if(action==='ui-question-tab'){
    workspaceRequest++;questionView.tab=b.dataset.tab;renderQuestionWorkspace();await loadQuestionPanel();
  }else if(action==='ui-version')await reusableDetailPage(questionView.id,b.dataset.id,questionView.tab);
  else if(action==='ui-rename'){
    const q=await api(`/api/reusable-questions/${b.dataset.id}`),name=await requestText('管理名称（不改变版本题干）',q.name);
    if(!name||name.trim()===q.name)return;
    await api(`/api/reusable-questions/${q.id}`,'PATCH',{name,editRevision:q.editRevision});
    if(questionView)await reusableDetailPage(q.id,questionView.vid,questionView.tab);else await reusableList();
    notice('管理名称已更新；版本题干保持原样');
  }else if(action==='ui-source'){
    const panel=b.nextElementSibling;
    if(!panel.hidden)return;
    const h=await api(`/api/question-versions/${b.dataset.id}/history`);
    panel.innerHTML=renderHistory(h);panel.hidden=false;
  }else if(action==='ui-usage-scope')await usagePage(b.dataset.series==='true'?questionView.id:questionView.vid,b.dataset.series==='true');
  else if(action==='ui-picker-close')closePicker();
  else if(action==='ui-picker-source'){
    pickerState.required=$('#rq-required')?.checked??true;
    if(b.dataset.source==='new'){
      collect();const q=seedQuestion();q.id=uid();q.required=pickerState.required;survey.questions.push(q);activeQuestion=survey.questions.length-1;markDirty();closePicker();renderEditor();return;
    }
    Object.assign(pickerState,{source:b.dataset.source,qid:null,bank:null,skip:0,message:''});await renderPicker();
  }else if(action==='ui-picker-open'){
    pickerState.required=$('#rq-required')?.checked??true;
    if(pickerState.source==='banks')pickerState.bank=b.dataset.id;else pickerState.qid=b.dataset.id;
    pickerState.skip=0;await renderPicker();
  }else if(action==='ui-picker-back'){
    pickerState.required=$('#rq-required')?.checked??true;pickerState.bank=null;pickerState.qid=null;pickerState.skip=0;await renderPicker();
  }else if(action==='ui-picker-page'){
    pickerState.required=$('#rq-required')?.checked??true;pickerState.skip=Number(b.dataset.skip);await renderPicker();
  }else if(action==='ui-picker-add'){
    const p=pickerState;p.required=$('#rq-required')?.checked??true;
    // Validation and authorization happen on the existing whole-save and dedicated write paths.
    await save({quiet:true});
    survey=await intent(p.localId?`/api/surveys/${survey.id}/questions/${p.localId}/upgrade`:`/api/surveys/${survey.id}/question-instances`,'POST',{versionId:b.dataset.id,editRevision:survey.editRevision,...(p.localId?{}:{required:p.required})});
    editorDirty=false;activeQuestion=p.localId?survey.questions.findIndex(q=>q.id===p.localId):survey.questions.length-1;renderEditor();
    if(p.localId){closePicker();notice('本位置已换版，卷内位置ID保持不变');}
    else {p.added++;p.message=`已保存并加入第 ${survey.questions.length} 题；本次共加入 ${p.added} 个位置。可以继续选题，或点“完成”。`;await renderPicker();}
  }
}

document.addEventListener('change',async ev=>{
  if(ev.target.id==='workspace-version'){
    try{$('#question-panel').innerHTML='<p class="muted">正在切换版本…</p>';await reusableDetailPage(questionView.id,ev.target.value,questionView.tab);}catch(err){notice(err.message);}
  }
});
document.addEventListener('toggle',ev=>{
  const detail=ev.target;
  if(!detail.matches?.('details.question')||!detail.open)return;
  activeQuestion=Number(detail.dataset.index);
  $$('#questions>details.question').forEach(other=>{if(other!==detail)other.open=false;});
},true);
document.addEventListener('click',ev=>{
  $$('details.menu[open]').forEach(menu=>{if(!menu.contains(ev.target)||ev.target.closest('[data-action]'))menu.open=false;});
});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape')$$('details.menu[open]').forEach(menu=>menu.open=false);});
window.addEventListener('beforeunload',ev=>{if(editorDirty){ev.preventDefault();ev.returnValue='';}});

async function exportReusable(index) {
  // 先完成确认，再保存草稿，取消不会产生保存操作。
  collect();
  const name = await requestText('可复用题目的管理名称', survey.questions[index].title);
  if (!name || !confirm('这里只保存题目内容；旧答案仍仅在原问卷统计中，不会自动计入该可复用题目的跨问卷统计。必答和跳转需在新卷另配。继续？')) {
    notice('已取消另存，未创建可复用题目');
    return;
  }
  if (survey.status === 'draft') await save({quiet:true});
  await intent(`/api/surveys/${survey.id}/questions/${survey.questions[index].id}/save-as-reusable`, 'POST', {name});
  notice('题目已另存；旧答案仍仅在原问卷统计中');
}

function bankReturnContext(button) {
  // 记住准确版本与页签；来源版本不可见时不能借返回动作扩大授权。
  if(questionView)return {page:questionView.owned?'question':'shared-detail',id:questionView.id,vid:questionView.vid,tab:questionView.tab,skip:reusableVersionSkip};
  if (button.closest('#mg-history') || $('h1')?.textContent === '共享给我') return {page:'shared',skip:sharedSkip};
  return reusableDetail && $('h1')?.textContent.includes('版本历史')
    ? {page:'question',id:reusableDetail.id,skip:reusableVersionSkip}
    : {page:'questions',skip:reusableSkip};
}

async function returnFromBankSelection() {
  const target = bankReturn;
  bankReturn = null;
  if (target?.page === 'question') {
    reusableVersionSkip = target.skip;
    await reusableDetailPage(target.id,target.vid,target.tab);
  } else if(target?.page==='shared-detail'){
    await sharedDetail(target.vid,target.tab);
  } else if (target?.page === 'shared') {
    await sharedPage(target.skip);
  } else {
    await reusableList();
  }
}
