const state={tab:'chat',kind:'questions',category:'전체',query:'',visible:12,data:{questions:[],templates:[]}};
const panels=document.querySelectorAll('[data-panel]');
const navItems=document.querySelectorAll('[data-tab]');
const messages=document.querySelector('#messages');
const input=document.querySelector('#questionInput');

function switchTab(tab){
  state.tab=tab;
  panels.forEach(panel=>panel.classList.toggle('active',panel.dataset.panel===tab));
  navItems.forEach(button=>button.classList.toggle('active',button.dataset.tab===tab));
  window.scrollTo({top:0,behavior:'smooth'});
}
navItems.forEach(button=>button.addEventListener('click',()=>switchTab(button.dataset.tab)));
document.querySelector('[data-tab-link]').addEventListener('click',event=>{event.preventDefault();switchTab('chat')});

function escapeHtml(value){const node=document.createElement('div');node.textContent=value;return node.innerHTML}
function addUserMessage(text){
  messages.insertAdjacentHTML('beforeend',`<article class="message user"><div class="bubble"><p>${escapeHtml(text)}</p></div></article>`);
  messages.scrollTop=messages.scrollHeight;
}
function addTyping(){
  messages.insertAdjacentHTML('beforeend','<article class="message assistant" id="typing"><div class="avatar">M</div><div class="bubble"><div class="typing"><i></i><i></i><i></i></div></div></article>');
  messages.scrollTop=messages.scrollHeight;
}
function addAnswer(result){
  document.querySelector('#typing')?.remove();
  const candidates=result.candidates.map(item=>`<div class="candidate">${item.rank}. ${escapeHtml(item.template_id)} · 유사도 ${Number(item.score).toFixed(3)}</div>`).join('');
  messages.insertAdjacentHTML('beforeend',`<article class="message assistant"><div class="avatar">M</div><div class="bubble"><p>${escapeHtml(result.recommended_answer)}</p><div class="response-meta"><span class="tag">${escapeHtml(result.selected_template_id)}</span><span class="tag">${result.latency_ms} ms</span><span class="tag">전문가 검토 필요</span></div><details class="details"><summary>추천 후보 보기</summary>${candidates}</details></div></article>`);
  messages.scrollTop=messages.scrollHeight;
}
function addError(){
  document.querySelector('#typing')?.remove();
  messages.insertAdjacentHTML('beforeend','<article class="message assistant"><div class="avatar">M</div><div class="bubble"><p>답변을 불러오지 못했습니다. 서버 상태를 확인한 뒤 다시 시도해 주세요.</p></div></article>');
}
async function sendQuestion(text){
  const question=text.trim();if(!question)return;
  addUserMessage(question);input.value='';input.style.height='auto';addTyping();
  const send=document.querySelector('.send');send.disabled=true;
  try{
    const response=await fetch('/recommend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:question,top_k:3})});
    if(!response.ok)throw new Error('request failed');
    addAnswer(await response.json());
  }catch(error){addError()}finally{send.disabled=false;input.focus()}
}
document.querySelector('#chatForm').addEventListener('submit',event=>{event.preventDefault();sendQuestion(input.value)});
input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendQuestion(input.value)}});
input.addEventListener('input',()=>{input.style.height='auto';input.style.height=`${Math.min(input.scrollHeight,110)}px`});
messages.addEventListener('click',event=>{if(event.target.matches('.suggestions button'))sendQuestion(event.target.textContent)});
document.querySelector('#clearChat').addEventListener('click',()=>{messages.innerHTML='<article class="message assistant"><div class="avatar">M</div><div class="bubble"><p>새 대화를 시작할게요. 어떤 상표 질문이 궁금하신가요?</p></div></article>'});

function currentItems(){
  const search=state.query.toLowerCase();
  return state.data[state.kind].filter(item=>{
    const categoryMatches=state.category==='전체'||item.category===state.category;
    const haystack=Object.values(item).flat(2).join(' ').toLowerCase();
    return categoryMatches&&haystack.includes(search);
  });
}
function renderFilters(){
  const categories=['전체',...new Set(state.data[state.kind].map(item=>item.category))];
  document.querySelector('#categoryFilters').innerHTML=categories.map(category=>`<button class="${category===state.category?'active':''}" data-category="${escapeHtml(category)}">${escapeHtml(category)}</button>`).join('');
}
function renderData(){
  const items=currentItems();
  const visible=items.slice(0,state.visible);
  const html=visible.map(item=>{
    const question=state.kind==='questions';
    const title=question?item.query:item.representative_query;
    const body=question?item.reference_answer:item.answer;
    const id=question?item.case_id:item.template_id;
    const tags=question?[item.style,...item.expected_template_ids]:item.source_ids;
    return `<article class="data-card"><div class="card-top"><span class="card-id">${escapeHtml(id)}</span><span class="category">${escapeHtml(item.category)}</span></div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p><div class="card-foot">${tags.map(tag=>`<span class="tag">${escapeHtml(tag)}</span>`).join('')}</div></article>`;
  }).join('');
  document.querySelector('#dataGrid').innerHTML=html||'<div class="loading">조건에 맞는 데이터가 없습니다.</div>';
  const loadMore=document.querySelector('#loadMore');loadMore.hidden=state.visible>=items.length;loadMore.textContent=`더 보기 · ${state.visible}/${items.length}`;
}
document.querySelectorAll('[data-dataset]').forEach(button=>button.addEventListener('click',()=>{
  state.kind=button.dataset.dataset;state.category='전체';state.visible=12;
  document.querySelectorAll('[data-dataset]').forEach(item=>item.classList.toggle('active',item===button));renderFilters();renderData();
}));
document.querySelector('#categoryFilters').addEventListener('click',event=>{if(!event.target.dataset.category)return;state.category=event.target.dataset.category;state.visible=12;renderFilters();renderData()});
document.querySelector('#datasetSearch').addEventListener('input',event=>{state.query=event.target.value;state.visible=12;renderData()});
document.querySelector('#loadMore').addEventListener('click',()=>{state.visible+=12;renderData()});

async function initialize(){
  try{
    const [health,datasets]=await Promise.all([fetch('/health'),fetch('/datasets')]);
    if(!health.ok||!datasets.ok)throw new Error('initialization failed');
    const healthData=await health.json();state.data=await datasets.json();
    document.querySelector('#engineStatus').textContent=`${healthData.engine.backend.toUpperCase()} 엔진 준비됨`;
    document.querySelector('#questionCount').textContent=state.data.questions.length;
    document.querySelector('#templateCount').textContent=state.data.templates.length;
    renderFilters();renderData();
  }catch(error){document.querySelector('.status-dot').classList.add('offline');document.querySelector('#engineStatus').textContent='서버 연결 안 됨';document.querySelector('#dataGrid').innerHTML='<div class="loading">데이터를 불러오지 못했습니다.</div>'}
}
initialize();
