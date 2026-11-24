/* ---------- helpers ---------- */
const $=(s,e=document)=>e.querySelector(s), $$=(s,e=document)=>[...e.querySelectorAll(s)];
const esc=v=>v==null?'':String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const qs=o=>{const p=new URLSearchParams();for(const[k,v]of Object.entries(o||{}))if(v!==''&&v!=null)p.set(k,v);const s=p.toString();return s?'?'+s:''};
let ME=null,CATS=[],CACHE={};
async function api(method,url,body){
  const o={method,credentials:'same-origin',headers:{}};
  if(body instanceof FormData)o.body=body;else if(body!==undefined){o.headers['Content-Type']='application/json';o.body=JSON.stringify(body)}
  let r,j;try{r=await fetch(url,o);j=await r.json()}catch(e){throw new Error('Cannot reach the server. Check that python app.py is still running.')}
  if(r.status===401&&ME&&!url.endsWith('/login')){ME=null;showAuth('Your session ended. Please log in again.')}
  if(!r.ok||j.ok===false){const e=new Error(j.error||'Something went wrong.');e.data=j;throw e}
  return j;
}
const GET=(u,q)=>api('GET',u+qs(q)),POST=(u,b)=>api('POST',u,b===undefined?{}:b),PUT=(u,b)=>api('PUT',u,b),DEL=u=>api('DELETE',u);
const D=s=>s?new Date(String(s).replace(' ','T')+(String(s).length===10?'T00:00':'')):null;
const fD=s=>s?D(s).toLocaleDateString('en-CA',{month:'short',day:'numeric',year:'numeric'}):'';
const fT=s=>D(s).toLocaleTimeString('en-CA',{hour:'numeric',minute:'2-digit'});
const fDT=s=>s?`${fD(s)}, ${fT(s)}`:'';
const fRange=(a,b)=>`${fD(a)}, ${fT(a)} to ${fT(b)}`;
const localISO=d=>{const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`};
const todayISO=()=>localISO(new Date()).slice(0,10);
const pill=s=>`<span class="pill s-${esc(String(s).split(' ')[0])}">${esc(s)}</span>`;
const tag=n=>n<0?'<span class="tag hot">Expired</span>':n===0?'<span class="tag hot">Today</span>':`<span class="tag ${n<=3?'hot':n<=7?'warn':'ok'}">${n} day${n>1?'s':''}</span>`;
const initials=n=>(n||'?').split(/\s+/).slice(0,2).map(w=>w[0]).join('').toUpperCase();
const avatar=(n,pic,sm)=>`<span class="av ${sm?'sm':''}">${esc(initials(n))}${pic?`<img src="/static/${esc(pic)}" alt="" onerror="this.remove()">`:''}</span>`;
const head=(t,s,a)=>`<header class="ph"><div><h1>${t}</h1>${s?`<p>${s}</p>`:''}</div><div class="pa">${a||''}</div></header>`;
const emptyBox=(t,s)=>`<div class="empty"><b>${t}</b><span>${s||''}</span></div>`;
const errBox=e=>`<div class="empty bad"><b>${esc(e.message)}</b></div>`;
const opts=(arr,sel,ph)=>(ph!=null?`<option value="">${ph}</option>`:'')+arr.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(sel??'')?'selected':''}>${esc(t)}</option>`).join('');
const F=(label,name,o={})=>`<label class="f ${o.cls||''}"><span>${label}</span>${
  o.type==='select'?`<select name="${name}" ${o.req?'required':''}>${o.options}</select>`:
  o.type==='textarea'?`<textarea name="${name}" rows="${o.rows||2}" ${o.req?'required':''} placeholder="${esc(o.ph)}">${esc(o.value)}</textarea>`:
  `<input name="${name}" type="${o.type||'text'}" value="${esc(o.value)}" placeholder="${esc(o.ph)}" ${o.req?'required':''} ${o.attrs||''}>`}${o.hint?`<small>${o.hint}</small>`:''}</label>`;
function toast(m,err){const t=document.createElement('div');t.className='toast'+(err?' err':'');t.textContent=m;$('#toasts').append(t);setTimeout(()=>t.remove(),err?6000:3500)}
const refresh=()=>route();

function modal(title,html,onsubmit,o={}){
  const d=$('#dlg');d.className=o.wide?'wide':'';
  d.innerHTML=`<form class="mform"><header><h3>${title}</h3><button type="button" class="x" data-act="close" aria-label="Close">×</button></header><div class="mbody">${html}</div><p class="merr" hidden></p><footer><button type="button" class="btn ghost" data-act="close">${onsubmit?'Cancel':'Close'}</button>${onsubmit?`<button class="btn">${o.submit||'Save'}</button>`:''}</footer></form>`;
  const f=$('form',d);
  if(onsubmit)f.onsubmit=async e=>{e.preventDefault();const b=$('footer .btn:last-child',f),er=$('.merr',f);b.disabled=true;er.hidden=true;
    try{await onsubmit(Object.fromEntries(new FormData(f)),f);d.close()}catch(x){er.textContent=x.message;er.hidden=false;b.disabled=false;er.scrollIntoView({block:'nearest'})}};
  d.showModal();
}
const ask=(msg)=>confirm(msg);
async function guard(fn){try{await fn()}catch(e){toast(e.message,1)}}

/* ---------- auth screen ---------- */
const DEMO=[['Coordinator','harsh.rana1@student.kpu.ca'],['Volunteer','jackson@surreyfoodbank.test'],['Donor','guildford.fresh.market@donor.test'],['Recipient','maria.gonzalez@recipient.test'],['Pending recipient','tom.baker@recipient.test']];
function showAuth(msg){
  document.body.classList.remove('nav-open');
  $('#root').innerHTML=`<div class="auth"><section class="hero">
    <div>
      <div style="display:inline-block;padding:4px 12px;border-radius:99px;background:rgba(240,180,41,0.18);color:var(--gold);font-weight:700;font-size:12px;letter-spacing:0.04em;text-transform:uppercase;margin-bottom:14px;border:1px solid rgba(240,180,41,0.35)">Surrey Community Food Bank</div>
      <h1>Food in. Food out. Nothing wasted.</h1>
      <p>Donors drop off, volunteers pack, coordinators keep the shelves honest, and families pick up on time.</p>
    </div>
    <div class="hero-showcase">
      <div class="hero-card">
        <img src="/static/images/volunteers/istockphoto-1408430485-612x612.jpg" alt="Donation Intake">
        <div class="hero-caption"><b>Intake & Sorting</b><span>Fresh food processed daily</span></div>
      </div>
      <div class="hero-card">
        <img src="/static/images/volunteers/istockphoto-1448547403-612x612.jpg" alt="Community Volunteers">
        <div class="hero-caption"><b>Our Volunteers</b><span>Coordinating shifts & hampers</span></div>
      </div>
      <div class="hero-card">
        <img src="/static/images/volunteers/istockphoto-1456994996-612x612.jpg" alt="Hamper Distribution">
        <div class="hero-caption"><b>Fair Distribution</b><span>Serving local households</span></div>
      </div>
    </div>
    <div class="tags" aria-hidden="true"><div><span>Yogurt</span><i class="tag hot">2 days</i></div><div><span>Spaghetti</span><i class="tag ok">13 days</i></div><div><span>Bread</span><i class="tag warn">5 days</i></div></div>
  </section>
  <section class="panel"><div class="box">
  <div class="tabs" role="tablist"><button role="tab" aria-selected="true" data-tab="in">Log in</button><button role="tab" aria-selected="false" data-tab="up">Create account</button></div>
  ${msg?`<p class="merr" style="margin:0 0 14px">${esc(msg)}</p>`:''}
  <form id="login"><h2>Welcome back</h2>${F('Email','email',{type:'email',req:1,attrs:'autocomplete="username"'})}${F('Password','password',{type:'password',req:1,attrs:'autocomplete="current-password"'})}<p class="merr" id="lerr" hidden style="margin:0 0 12px"></p><button class="btn" style="width:100%">Log in</button>
  <details class="demo"><summary>Demo accounts</summary><p style="margin:8px 0 0">Password for all: <b>Password123!</b></p><div>${DEMO.map(([l,e])=>`<button type="button" class="chip" data-demo="${e}">${l}</button>`).join('')}</div></details></form>
  <form id="reg" hidden><h2>Create your account</h2>
  ${F('I am a','role',{type:'select',req:1,options:opts([['Donor','Donor, I give food'],['Recipient','Recipient, I need food']],'Recipient')})}
  <div class="grid2">${F('Full name or organization','name',{req:1})}${F('Phone','phone',{req:1,ph:'604-555-0123'})}</div>
  ${F('Email','email',{type:'email',req:1})}${F('Password','password',{type:'password',req:1,attrs:'minlength="8" autocomplete="new-password"',hint:'At least 8 characters.'})}
  <fieldset class="fs" id="fs-Donor" disabled hidden>${F('Donor type','donor_type',{type:'select',options:opts([['Individual','Individual'],['Business','Business'],['Organization','Organization']])})}</fieldset>
  <fieldset class="fs" id="fs-Recipient">${F('Household size','household_size',{type:'number',req:1,attrs:'min="1" max="30"',value:1})}${F('Dietary restrictions or allergies','dietary',{type:'textarea',req:1,ph:'Write "None" if there are none'})}${F('Emergency contact','emergency_contact',{req:1,ph:'Name and phone number'})}
  <p class="mut" style="margin-top:-4px;font-size:14px">A coordinator reviews every recipient registration before hampers can be requested.</p></fieldset>
  <p class="merr" id="rerr" hidden style="margin:0 0 12px"></p><button class="btn" style="width:100%">Create account</button></form></div></section></div>`;
  $$('[data-tab]').forEach(b=>b.onclick=()=>{const up=b.dataset.tab==='up';$$('[data-tab]').forEach(x=>x.setAttribute('aria-selected',x===b));$('#login').hidden=up;$('#reg').hidden=!up});
  $$('[data-demo]').forEach(b=>b.onclick=()=>{$('#login [name=email]').value=b.dataset.demo;$('#login [name=password]').value='Password123!'});
  const swap=()=>{const r=$('#reg [name=role]').value;['Donor','Recipient'].forEach(x=>{const s=$('#fs-'+x);s.hidden=s.disabled=x!==r})};
  $('#reg [name=role]').onchange=swap;swap();
  const fail=(id,e)=>{const p=$(id);p.textContent=e.message;p.hidden=false};
  $('#login').onsubmit=async e=>{e.preventDefault();$('#lerr').hidden=true;try{await POST('/api/login',Object.fromEntries(new FormData(e.target)));await boot()}catch(x){fail('#lerr',x)}};
  $('#reg').onsubmit=async e=>{e.preventDefault();$('#rerr').hidden=true;const v=Object.fromEntries(new FormData(e.target));
    try{await POST('/api/register',v);await POST('/api/login',{email:v.email,password:v.password});await boot();toast('Account created. Welcome!')}catch(x){fail('#rerr',x)}};
}

/* ---------- shell + routing ---------- */
const NAV={
  Donor:[['home','Home'],['donations','My donations'],['profile','My account']],
  Recipient:[['home','Home'],['hampers','My hampers'],['profile','My account']],
  Volunteer:[['home','Today'],['distributions','Distributions'],['inventory','Inventory'],['donations','Donations'],['shifts','My shifts'],['profile','My account']],
  Coordinator:[['home','Overview'],['recipients','Recipients'],['accounts','Accounts'],['shifts','Shifts'],['inventory','Inventory'],['distributions','Pickups'],['reports','Reports'],['ai','AI and alerts'],['profile','My account']]};
async function boot(){try{const r=await GET('/api/me');ME=r.user;CATS=r.categories;shell()}catch(e){ME=null;showAuth()}}
function shell(){
  $('#root').innerHTML=`<div class="app"><aside id="side"><div class="brand">Surrey Community<br>Food Bank</div><nav aria-label="Main">${NAV[ME.role].map(([id,l])=>`<a href="#/${id}" data-p="${id}">${l}</a>`).join('')}</nav>
  <div class="me">${avatar(ME.name,ME.picture)}<div><b>${esc(ME.name)}</b><span>${ME.role}</span></div><button class="lo" data-act="logout">Log out</button></div></aside>
  <div class="scrim" data-act="menu"></div><main><button class="burger" data-act="menu">Menu</button><div id="main"></div></main></div>`;
  route();
}
async function route(){
  if(!ME)return;
  const ids=NAV[ME.role].map(n=>n[0]);let p=(location.hash.match(/^#\/(\w+)/)||[])[1];if(!ids.includes(p))p='home';
  $$('nav a').forEach(a=>a.dataset.p===p?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current'));
  document.body.classList.remove('nav-open');
  const m=$('#main');m.innerHTML='<p class="mut">Loading…</p>';
  try{await PAGES[ME.role][p]()}catch(e){m.innerHTML=head('Something went wrong')+errBox(e)}
}
addEventListener('hashchange',()=>{window.scrollTo(0,0);route()});

/* ---------- reusable list page ---------- */
async function listPage(o){
  $('#main').innerHTML=head(o.title,o.sub,o.actions)+`<form id="flt" class="flt">${o.filters||''}<button class="btn sm">Search</button><button type="button" class="btn ghost sm" id="clr">Clear</button></form><div id="res">Loading…</div>`;
  const load=async()=>{try{const r=await o.fetch(Object.fromEntries(new FormData($('#flt'))));$('#res').innerHTML=o.render(r)||emptyBox(o.empty||'Nothing found','Try a different search.')}catch(e){$('#res').innerHTML=errBox(e)}};
  $('#flt').onsubmit=e=>{e.preventDefault();load()};$('#clr').onclick=()=>{$('#flt').reset();load()};await load();
}
const dateFilters=`${F('From date','from',{type:'date'})}${F('To date','to',{type:'date'})}`;
const catSel=()=>F('Category','category_id',{type:'select',options:opts(CATS.map(c=>[c.id,c.name]),'','All categories')});
const itemsList=a=>a&&a.length?`<ul class="il">${a.map(i=>`<li>${esc(i.item)} <b>×${i.qty}</b> ${esc(i.unit)}</li>`).join('')}</ul>`:'<span class="mut">No items yet</span>';

/* ---------- dashboards ---------- */
const riskTable=a=>a.length?`<div class="tw"><table class="t"><tbody>${a.map(i=>`<tr><td>${esc(i.name)}</td><td>${i.qty} ${esc(i.unit)}</td><td class="act">${tag(i.days_left)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="note">Nothing is close to expiring.</p>';
async function donorHome(){
  const d=await GET('/api/dashboard');
  $('#main').innerHTML=head(`Hello, ${esc(ME.name)}`,'Thank you for giving. Bring food to the food bank and a volunteer will record it. It shows up in your history right away.',`<a class="btn" href="#/donations">See my donations</a>`)+
  `<div class="stats"><div class="stat"><b>${d.donations}</b><span>Donations</span></div><div class="stat"><b>${d.item_lines}</b><span>Item lines given</span></div><div class="stat"><b>${d.last_donation?fD(d.last_donation):'None yet'}</b><span>Last donation</span></div></div>`;
}
async function recipientHome(){
  const d=await GET('/api/dashboard');let body='';
  if(d.approval==='Pending')body=`<div class="banner"><b>Waiting for approval</b>A coordinator is reviewing your registration. You can request a hamper once it is approved.</div>`;
  else if(d.approval==='Rejected')body=`<div class="banner red"><b>Registration not approved</b>Please contact the food bank to talk about your registration.</div>`;
  else{
    const n=d.next;
    body=(n?`<div class="banner green"><b>Your next pickup: ${fDT(n.pickup)}</b>Status: ${esc(n.status)}. Please arrive within 30 minutes of your time, or a coordinator will follow up.</div>`:
    `<div class="card pad"><h3>Request a hamper</h3><p class="mut">Choose when you can pick it up. A volunteer will pack it for your household.</p><form id="req" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">${F('Pickup date and time','pickup',{type:'datetime-local',req:1,attrs:`min="${localISO(new Date(Date.now()+36e5))}"`,cls:'',value:''})}<button class="btn" style="margin-bottom:14px">Request pickup</button></form></div>`)+
    `<div class="stats"><div class="stat"><b>${d.received}</b><span>Hampers received</span></div><div class="stat"><b>${d.household}</b><span>People in your household</span></div></div>`;
  }
  $('#main').innerHTML=head(`Hello, ${esc(ME.name)}`)+body;
  const r=$('#req');if(r)r.onsubmit=e=>{e.preventDefault();guard(async()=>{const x=await POST('/api/recipient/pickups',Object.fromEntries(new FormData(r)));toast(x.msg);refresh()})};
}
async function volHome(){
  const d=await GET('/api/dashboard');
  $('#main').innerHTML=head(`Hello, ${esc(ME.name)}`,'Your shifts and the pickups waiting for you.',`<a class="btn gold" href="#/distributions">Open distributions</a>`)+
  `<div class="two"><div><h3 class="sec" style="margin-top:0">My next shifts</h3><div class="card">${d.shifts.length?`<div class="tw"><table class="t"><tbody>${d.shifts.map(s=>`<tr><td><b>${esc(s.task)}</b><br><span class="mut">${fRange(s.start,s.end)}</span></td></tr>`).join('')}</tbody></table></div>`:'<p class="note">No upcoming shifts.</p>'}</div>
  <h3 class="sec">Use these first</h3><div class="card">${riskTable(d.at_risk)}</div></div>
  <div><h3 class="sec" style="margin-top:0">Pickups to handle</h3><div class="card">${d.pickups.length?`<div class="tw"><table class="t"><tbody>${d.pickups.map(p=>`<tr><td><b>${esc(p.recipient)}</b><br><span class="mut">${fDT(p.pickup)}</span></td><td>${pill(p.status)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="note">No open pickups for your shifts.</p>'}</div></div></div>`;
}
async function coHome(){
  const d=await GET('/api/dashboard');
  $('#main').innerHTML=head('Overview','What needs a coordinator today.',`<a class="btn ghost" href="#/ai">Run AI check</a>`)+
  `<div class="stats"><a class="stat ${d.pending?'gold':''}" href="#/recipients"><b>${d.pending}</b><span>Registrations to review</span></a>
  <a class="stat ${d.late?'alert':''}" href="#/distributions"><b>${d.late}</b><span>Missed or delayed, last 14 days</span></a>
  <a class="stat ${d.unassigned?'gold':''}" href="#/distributions"><b>${d.unassigned}</b><span>Pickups without a shift</span></a>
  <div class="stat"><b>${d.upcoming}</b><span>Scheduled pickups</span></div><a class="stat" href="#/inventory"><b>${d.in_stock}</b><span>Item lines in stock</span></a>
  <div class="stat ${d.waiting?'alert':''}"><b>${d.waiting}</b><span>Expired, waiting for the AI check</span></div></div>
  <div class="two"><div><h3 class="sec" style="margin-top:0">Expiring within 3 days</h3><div class="card">${riskTable(d.at_risk)}</div></div>
  <div><h3 class="sec" style="margin-top:0">Latest missed or delayed pickups</h3><div class="card">${d.late_list.length?`<div class="tw"><table class="t"><tbody>${d.late_list.map(p=>`<tr><td><b>${esc(p.recipient)}</b><br><span class="mut">${fDT(p.pickup)}</span></td><td>${pill(p.status)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="note">All pickups are on track.</p>'}</div></div></div>`;
}

/* ---------- donations history ---------- */
const donCard=d=>`<article class="card"><div class="ch"><div><b>${esc(d.donor)}</b><span class="mut">${fDT(d.date)}${d.collected_by?`, received by ${esc(d.collected_by)}`:''}</span></div><div style="display:flex;gap:8px;align-items:center"><span class="mut">${d.items.length} item${d.items.length>1?'s':''}</span>${(ME.role==='Volunteer'||ME.role==='Coordinator')?`<button class="btn ghost sm" data-act="editDon" data-id="${d.id}">Edit</button>`:''}</div></div>
 <div class="tw"><table class="t"><thead><tr><th>Item</th><th>Category</th><th>Quantity</th><th>Expires</th></tr></thead><tbody>${d.items.map(i=>`<tr><td>${esc(i.item)}</td><td>${esc(i.category)}</td><td>${i.qty} ${esc(i.unit)}</td><td>${fD(i.expires)}</td></tr>`).join('')}</tbody></table></div>${d.notes?`<p class="note">${esc(d.notes)}</p>`:''}</article>`;
const donRow=()=>`<div class="irow"><input name="name" placeholder="Item, e.g. Black beans 540 mL" required aria-label="Item name"><select name="category_id" required aria-label="Category">${opts(CATS.map(c=>[c.id,c.name]),'','Category')}</select><input name="quantity" type="number" min="0.01" step="any" placeholder="Qty" required aria-label="Quantity"><input name="unit" list="units" placeholder="Unit" required aria-label="Unit"><input name="expiration_date" type="date" min="${todayISO()}" required aria-label="Expiry date"><button type="button" class="x" data-act="delrow" aria-label="Remove item">×</button></div>`;
const rowsOf=(f,sel)=>$$(sel,f).map(r=>Object.fromEntries($$('[name]',r).map(x=>[x.name,x.value])));
async function donationsPage(){
  const vol=ME.role==='Volunteer',donor=ME.role==='Donor';
  await listPage({title:donor?'My donations':'Donations received',sub:donor?'Everything you have given. Search by date or category.':'Every donation recorded, with who gave it and which volunteer received it.',
    actions:vol?`<button class="btn gold" data-act="newDonation">Record a donation</button>`:'',
    filters:(donor?'':F('Donor name','donor'))+dateFilters+catSel(),
    fetch:q=>GET(donor?'/api/donor/donations':'/api/donations',q),render:r=>r.donations.length?r.donations.map(donCard).join(''):'',empty:donor?'No donations yet':'No donations found',});
}
async function editDonation(id){
  const {donors}=await GET('/api/donors');
  const {donation:d}=await GET('/api/donations/'+id);
  modal('Edit donation record',`${F('Donor','donor_id',{type:'select',req:1,options:opts(donors.map(x=>[x.id,`${x.name} (${x.type})`]),d.donor_id)})}${F('Donation date and time','date_time',{type:'datetime-local',req:1,value:d.date?d.date.replace(' ','T'):''})}${F('Notes (optional)','notes',{value:d.notes||''})}`,
    async(v)=>{const r=await PUT('/api/donations/'+id,{donor_id:v.donor_id,date_time:v.date_time,notes:v.notes});toast(r.msg);refresh()},{submit:'Update donation'});
}

async function newDonation(){

  const {donors}=await GET('/api/donors');
  modal('Record a donation',`${F('Donor','donor_id',{type:'select',req:1,options:opts(donors.map(d=>[d.id,`${d.name} (${d.type})`]),'','Choose the donor')})}${F('Notes (optional)','notes',{})}
  <div class="sec" style="margin-top:4px">Items received</div><div id="rows">${donRow()}</div><button type="button" class="btn ghost sm" data-act="addDon">Add another item</button>`,
  async(v,f)=>{const r=await POST('/api/donations',{donor_id:v.donor_id,notes:v.notes,items:rowsOf(f,'.irow')});toast(r.msg);refresh()},{wide:1,submit:'Save donation'});
}

/* ---------- inventory ---------- */
async function invPage(){
  const vol=ME.role==='Volunteer';
  await listPage({title:'Inventory',sub:'Food on the shelf, soonest expiry first. A red tag means 3 days or less.',
    actions:vol?`<button class="btn gold" data-act="newDonation">Record a donation</button>`:`<button class="btn ghost" data-act="cats">Manage categories</button>`,
    filters:`${F('Item name','q')}${catSel()}${F('Expires on or before','expires_before',{type:'date'})}${F('Min quantity','qty_min',{type:'number',attrs:'min="0" step="any"'})}${F('Max quantity','qty_max',{type:'number',attrs:'min="0" step="any"'})}${F('Show','status',{type:'select',options:opts([['available','In stock'],['expired','Expired (waste)'],['all','Everything']])})}`,
    fetch:async q=>{const r=await GET('/api/inventory',q);CACHE.items=r.items;return r},
    render:r=>r.items.length?`<div class="card"><div class="tw"><table class="t"><thead><tr><th>Item</th><th>Category</th><th>Quantity</th><th>Expires</th><th>Donated by</th>${vol?'<th></th>':''}</tr></thead><tbody>${r.items.map(i=>`<tr><td><b>${esc(i.name)}</b></td><td>${esc(i.category)}</td><td>${i.qty} ${esc(i.unit)}</td><td>${tag(i.days_left)} <span class="mut">${fD(i.expires)}</span></td><td>${esc(i.donor)}</td>${vol?`<td class="act">${i.status==='Expired'?'<span class="mut">Locked</span>':`<button class="btn ghost sm" data-act="editItem" data-id="${i.id}">Edit</button><button class="btn danger sm" data-act="delItem" data-id="${i.id}">Delete</button>`}</td>`:''}</tr>`).join('')}</tbody></table></div></div>`:'',empty:'No items match'});
}
function editItem(id){
  const i=CACHE.items.find(x=>x.id==id);
  modal('Edit item',`${F('Name','name',{value:i.name,req:1})}${F('Category','category_id',{type:'select',req:1,options:opts(CATS.map(c=>[c.id,c.name]),i.category_id)})}<div class="grid2">${F('Quantity on shelf','quantity',{type:'number',value:i.qty,req:1,attrs:'min="0" step="any"'})}${F('Unit','unit',{value:i.unit,req:1,attrs:'list="units"'})}</div>${F('Expiry date','expiration_date',{type:'date',value:i.expires,req:1})}`,
  async v=>{const r=await PUT('/api/inventory/'+id,v);toast(r.msg);refresh()});
}
async function cats(){
  const draw=async()=>{const {categories}=await GET('/api/categories');CATS=categories;
    $('#catbody').innerHTML=`<div class="tw"><table class="t"><tbody>${categories.map(c=>`<tr><td><b>${esc(c.name)}</b></td><td class="mut">${c.items} item line${c.items==1?'':'s'}</td><td class="act"><button class="btn ghost sm" data-act="renCat" data-id="${c.id}" data-name="${esc(c.name)}">Rename</button><button class="btn danger sm" data-act="delCat" data-id="${c.id}">Delete</button></td></tr>`).join('')}</tbody></table></div>`};
  modal('Inventory categories',`<div id="catbody"></div><form id="catf" style="display:flex;gap:8px;margin-top:14px"><input name="name" placeholder="New category name" required aria-label="New category name"><button class="btn">Add</button></form>`);
  await draw();CACHE.drawCats=draw;
  $('#catf').onsubmit=e=>{e.preventDefault();guard(async()=>{await POST('/api/categories',Object.fromEntries(new FormData(e.target)));e.target.reset();await draw()})};
}

/* ---------- distributions ---------- */
let STOCK=[];
const stockOpts=sel=>`<option value="">Choose an item</option>`+STOCK.map(i=>`<option value="${i.id}" data-max="${i.max}" ${i.id==sel?'selected':''}>${esc(i.name)}: ${i.max} ${esc(i.unit)}${i.expires?`, expires ${fD(i.expires)}`:''}</option>`).join('');
const dRow=(sel,q)=>`<div class="irow d"><select name="item_id" required aria-label="Item">${stockOpts(sel)}</select><input name="quantity" type="number" min="0.01" step="any" value="${q||''}" placeholder="Qty" required aria-label="Quantity"><button type="button" class="x" data-act="delrow" aria-label="Remove item">×</button></div>`;
async function distPage(){
  const vol=ME.role==='Volunteer';
  await listPage({title:vol?'Distributions':'Pickups',sub:vol?'Hampers for the shifts you are assigned to. Mark each pickup as fulfilled, delayed or missed.':'Every scheduled and past pickup. Move unassigned pickups onto a shift.',
    actions:vol?`<button class="btn gold" data-act="newDist">New distribution</button>`:'',
    filters:`${F('Recipient name','recipient')}${F('Status','status',{type:'select',options:opts(['Scheduled','Fulfilled','Delayed','Missed'].map(s=>[s,s]),'','Any status')})}${dateFilters}${vol?'':`<label class="chk2"><input type="checkbox" name="unassigned" value="1"> Needs a shift</label>`}`,
    fetch:async q=>{const r=await GET('/api/distributions',q);CACHE.dist=r.distributions;return r},
    render:r=>r.distributions.length?`<div class="card"><div class="tw"><table class="t"><thead><tr><th>Pickup</th><th>Recipient</th><th>Hamper</th><th>Status</th><th>Shift</th><th></th></tr></thead><tbody>${r.distributions.map(d=>{
      const open=d.status==='Scheduled'||d.status==='Delayed';
      return `<tr><td>${fDT(d.pickup)}</td><td><b>${esc(d.recipient)}</b><br><span class="mut">Household of ${d.household}. ${esc(d.dietary||'')}</span></td><td>${itemsList(d.items)}</td><td>${pill(d.status)}${d.given_by?`<br><span class="mut">by ${esc(d.given_by)}</span>`:''}</td><td>${d.shift_task?`${esc(d.shift_task)}<br><span class="mut">${fDT(d.shift_start)}</span>`:'<span class="mut">None</span>'}</td>
      <td class="act">${vol?`${d.status!=='Missed'?`<button class="btn ghost sm" data-act="editDist" data-id="${d.id}">${d.items.length?'Edit':'Pack hamper'}</button>`:''}${open?`<button class="btn sm" data-act="status" data-id="${d.id}" data-s="Fulfilled">Fulfilled</button>${d.status==='Scheduled'?`<button class="btn ghost sm" data-act="status" data-id="${d.id}" data-s="Delayed">Delayed</button>`:''}<button class="btn danger sm" data-act="status" data-id="${d.id}" data-s="Missed">Missed</button>`:''}<button class="btn danger sm" data-act="delDist" data-id="${d.id}">Delete</button>`:
      open?`<button class="btn ghost sm" data-act="assignShift" data-id="${d.id}">${d.shift_id?'Change shift':'Assign shift'}</button>`:''}</td></tr>`}).join('')}</tbody></table></div></div>`:'',empty:'No pickups found'});
}
async function distModal(id){
  const d=id?CACHE.dist.find(x=>x.id==id):null;
  const [inv,sh,rc]=await Promise.all([GET('/api/inventory',{status:'available'}),GET('/api/shifts'),d?{recipients:[]}:GET('/api/recipients/approved')]);
  STOCK=inv.items.map(i=>({id:i.id,name:i.name,unit:i.unit,expires:i.expires,max:i.qty}));
  (d?.items||[]).forEach(it=>{const s=STOCK.find(x=>x.id==it.item_id);if(s)s.max=+(s.max+it.qty).toFixed(2);else STOCK.push({id:it.item_id,name:it.item,unit:it.unit,expires:'',max:it.qty})});
  const now=localISO(new Date(Date.now()-12*36e5)).replace('T',' ');
  const shifts=sh.shifts.filter(s=>s.end>=now.slice(0,16)||(d&&s.id===d.shift_id)).reverse();
  const first=d?.items?.length?d.items.map(i=>dRow(i.item_id,i.qty)).join(''):dRow();
  modal(d?`Hamper for ${esc(d.recipient)}`:'New distribution',
   (d?`<p class="mut" style="margin-top:0">Household of ${d.household}. Dietary needs: <b>${esc(d.dietary||'None')}</b></p>`:
    `${F('Recipient','recipient_id',{type:'select',req:1,options:rc.recipients.map(r=>`<option value="${r.id}" data-diet="${esc(r.dietary||'None')}" data-hh="${r.household}">${esc(r.name)}</option>`).join('').replace(/^/,'<option value="">Choose a recipient</option>')})}<p class="note" id="diet" hidden style="padding:8px 12px;border-radius:8px;margin:-6px 0 14px"></p>`)+
   `<div class="grid2">${F('Shift','shift_id',{type:'select',req:1,options:opts(shifts.map(s=>[s.id,`${s.task}, ${fDT(s.start)}`]),d?.shift_id,'Choose a shift')})}${F('Pickup date and time','pickup',{type:'datetime-local',req:1,value:d?d.pickup.replace(' ','T'):localISO(new Date())})}</div>
    ${d?'':F('Status','status',{type:'select',options:opts([['Scheduled','Scheduled (pickup later)'],['Fulfilled','Fulfilled (handing out now)']])})}
    <div class="sec" style="margin-top:4px">Items in the hamper</div><div id="rows">${first}</div><button type="button" class="btn ghost sm" data-act="addDist">Add another item</button>`,
   async(v,f)=>{const items=rowsOf(f,'.irow');const body={shift_id:v.shift_id,pickup:v.pickup,items};
     const r=d?await PUT('/api/distributions/'+id,body):await POST('/api/distributions',{...body,recipient_id:v.recipient_id,status:v.status});toast(r.msg);refresh()},{wide:1,submit:'Save hamper'});
}
async function assignShift(id){
  const {shifts}=await GET('/api/shifts');const d=CACHE.dist.find(x=>x.id==id);
  modal('Assign pickup to a shift',`<p class="mut" style="margin-top:0">${esc(d.recipient)}, pickup ${fDT(d.pickup)}</p>${F('Shift','shift_id',{type:'select',options:opts(shifts.filter(s=>s.end>=localISO(new Date()).replace('T',' ')).reverse().map(s=>[s.id,`${s.task}, ${fDT(s.start)} (${s.volunteers.map(v=>v.name).join(', ')})`]),d.shift_id,'Choose a shift')})}`,
  async v=>{const r=await POST(`/api/distributions/${id}/shift`,{shift_id:v.shift_id});toast(r.msg);refresh()});
}

/* ---------- shifts ---------- */
let VOLS=[];
async function shiftsPage(){
  const co=ME.role==='Coordinator',r=await GET('/api/shifts');CACHE.shifts=r.shifts;VOLS=r.volunteers;
  const up=r.shifts.filter(s=>s.end>=r.now).reverse(),past=r.shifts.filter(s=>s.end<r.now);
  const tbl=l=>l.length?`<div class="card"><div class="tw"><table class="t"><thead><tr><th>When</th><th>Task</th><th>Volunteers</th><th>Pickups</th>${co?'<th></th>':''}</tr></thead><tbody>${l.map(s=>`<tr><td>${fRange(s.start,s.end)}</td><td><b>${esc(s.task)}</b></td><td>${s.volunteers.map(v=>esc(v.name)).join(', ')}</td><td>${s.pickups}</td>${co?`<td class="act"><button class="btn ghost sm" data-act="editShift" data-id="${s.id}">Edit</button><button class="btn danger sm" data-act="delShift" data-id="${s.id}">Delete</button></td>`:''}</tr>`).join('')}</tbody></table></div></div>`:`<div class="card"><p class="note">None.</p></div>`;
  $('#main').innerHTML=head(co?'Shifts':'My shifts',co?'Create distribution shifts and assign volunteers. The system checks each volunteer\'s availability first.':'Shifts you are assigned to. Update your weekly availability in My account.',co?`<button class="btn gold" data-act="newShift">New shift</button>`:`<a class="btn ghost" href="#/profile">Edit my availability</a>`)+`<h3 class="sec" style="margin-top:0">Upcoming</h3>${tbl(up)}<h3 class="sec">Past</h3>${tbl(past.slice(0,30))}`;
}
function shiftModal(s){
  const sel=new Set((s?.volunteers||[]).map(v=>v.id));
  modal(s?'Edit shift':'New shift',`<div class="grid2">${F('Starts','start',{type:'datetime-local',req:1,value:s?s.start.replace(' ','T'):''})}${F('Ends','end',{type:'datetime-local',req:1,value:s?s.end.replace(' ','T'):''})}</div>${F('Task','task',{req:1,value:s?.task,ph:'e.g. Saturday hamper pickup'})}
  <fieldset class="vols"><legend>Assign volunteers</legend>${VOLS.map(v=>`<label class="chk"><input type="checkbox" name="volunteer_ids" value="${v.id}" ${sel.has(v.id)?'checked':''}><span><b>${esc(v.name)}</b><small>${esc(v.availability||'Availability not set')}</small></span></label>`).join('')||'<p class="mut">No volunteers yet. Add them under Accounts.</p>'}</fieldset>`,
  async(v,f)=>{const body={start:v.start,end:v.end,task:v.task,volunteer_ids:$$('[name=volunteer_ids]:checked',f).map(x=>x.value)};
    const send=b=>s?PUT('/api/shifts/'+s.id,b):POST('/api/shifts',b);let r;
    try{r=await send(body)}catch(e){if(e.data?.conflicts&&ask(e.data.conflicts.join('\n')+'\n\nAssign anyway?'))r=await send({...body,force:true});else throw e}
    toast(r.msg);refresh()});
}

/* ---------- recipients (coordinator) + hampers (recipient) ---------- */
async function recipientsPage(){
  await listPage({title:'Recipients',sub:'Review new registrations before families can request hampers.',
    filters:`${F('Name','q')}${F('Status','status',{type:'select',options:opts(['Pending','Approved','Rejected'].map(s=>[s,s]),'Pending','All')})}`,
    fetch:q=>GET('/api/coordinator/recipients',q),
    render:r=>r.recipients.length?`<div class="card"><div class="tw"><table class="t"><thead><tr><th>Recipient</th><th>Household</th><th>Dietary needs</th><th>Emergency contact</th><th>Status</th><th></th></tr></thead><tbody>${r.recipients.map(x=>`<tr><td><b>${esc(x.name)}</b><br><span class="mut">${esc(x.email)}, ${esc(x.phone||'')}</span></td><td>${x.household}</td><td>${esc(x.dietary||'')}</td><td>${esc(x.emergency||'')}</td><td>${pill(x.status)}${x.approved_by?`<br><span class="mut">by ${esc(x.approved_by)}</span>`:''}</td>
      <td class="act">${x.status!=='Approved'?`<button class="btn sm" data-act="decide" data-id="${x.id}" data-d="Approved">Approve</button>`:''}${x.status!=='Rejected'?`<button class="btn danger sm" data-act="decide" data-id="${x.id}" data-d="Rejected">Reject</button>`:''}</td></tr>`).join('')}</tbody></table></div></div>`:'',empty:'No recipients found'});
}
async function hampersPage(){
  await listPage({title:'My hampers',sub:'Your pickups and what was in each hamper. Search by date.',filters:dateFilters,fetch:q=>GET('/api/recipient/hampers',q),
    render:r=>r.hampers.length?`<div class="card"><div class="tw"><table class="t"><thead><tr><th>Pickup</th><th>Status</th><th>Items</th><th>Given by</th></tr></thead><tbody>${r.hampers.map(h=>`<tr><td>${fDT(h.pickup)}</td><td>${pill(h.status)}</td><td>${itemsList(h.items)}</td><td>${esc(h.given_by||'')}</td></tr>`).join('')}</tbody></table></div></div>`:'',empty:'No hampers yet',});
}

/* ---------- profile + accounts ---------- */
const slotRow=(s={})=>`<div class="srow"><select name="day" aria-label="Day">${opts(['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d=>[d,d]),s.day)}</select><input type="time" name="start" value="${s.start||'09:00'}" aria-label="From"><span>to</span><input type="time" name="end" value="${s.end||'13:00'}" aria-label="Until"><button type="button" class="x" data-act="delrow" aria-label="Remove slot">×</button></div>`;
const slotsEditor=sl=>`<div class="f"><span>Weekly availability</span><div id="slots">${(sl||[]).map(slotRow).join('')}</div><button type="button" class="btn ghost sm" data-act="addSlot" style="align-self:flex-start">Add a time slot</button></div>`;
function profileFields(role,acct,p,sl,admin){
  let h=F('Email','email',{type:'email',req:1,value:acct.email})+`<div class="grid2">${F('Name','name',{req:1,value:p.Name})}${F('Phone','phone',{req:1,value:p.Phone})}</div>`;
  if(role==='Donor')h+=F('Donor type','donor_type',{type:'select',options:opts(['Individual','Business','Organization'].map(x=>[x,x]),p.Donor_Type)});
  if(role==='Recipient')h+=F('Household size','household_size',{type:'number',req:1,value:p.Household_Size,attrs:'min="1" max="30"'})+F('Dietary restrictions or allergies','dietary',{type:'textarea',req:1,value:p.Food_Preferences})+F('Emergency contact','emergency_contact',{req:1,value:p.Emergency_Contact});
  if(role==='Volunteer')h+=slotsEditor(sl);
  h+=`<div class="sec">${admin?'Reset password':'Change password'}</div><div class="grid2">${admin?'':F('Current password','current_password',{type:'password',attrs:'autocomplete="current-password"'})}${F('New password','new_password',{type:'password',attrs:'minlength="8" autocomplete="new-password"',hint:admin?'Leave blank to keep the current password.':'Leave blank to keep your current password.'})}</div>`;
  return h;
}
function profileBody(role,v,f){
  const b={email:v.email,name:v.name,phone:v.phone};
  if(role==='Donor')b.donor_type=v.donor_type;
  if(role==='Recipient'){b.household_size=v.household_size;b.dietary=v.dietary;b.emergency_contact=v.emergency_contact}
  if(role==='Volunteer')b.slots=$$('.srow',f).map(r=>({day:$('[name=day]',r).value,start:$('[name=start]',r).value,end:$('[name=end]',r).value}));
  if(v.new_password){b.new_password=v.new_password;if(v.current_password!==undefined)b.current_password=v.current_password}
  return b;
}
const picForm=(url,pic,name)=>`<div style="display:flex;gap:14px;align-items:center;margin-bottom:16px"><span id="pv">${avatar(name,pic)}</span><div><b>Profile picture</b><br><input type="file" id="picfile" accept="image/png,image/jpeg,image/webp" style="padding:6px"><small class="mut">JPG, PNG or WebP, up to 3 MB.</small></div></div>`;
function bindPic(url,after){const i=$('#picfile');if(i)i.onchange=()=>guard(async()=>{const fd=new FormData();fd.append('picture',i.files[0]);const r=await api('POST',url,fd);toast(r.msg);after&&after(r.picture)})}
async function profilePage(){
  const r=await GET('/api/profile'),role=ME.role;
  $('#main').innerHTML=head('My account','Keep your contact details current.')+`<div class="card pad" style="max-width:720px">${role==='Volunteer'?picForm('/api/profile/picture',r.profile.Picture,ME.name):''}<form id="pf">${profileFields(role,r.account,r.profile,r.slots,false)}<p class="merr" hidden></p><button class="btn">Save changes</button></form></div>`;
  bindPic('/api/profile/picture',()=>boot());
  $('#pf').onsubmit=e=>{e.preventDefault();const er=$('.merr',e.target);er.hidden=true;const v=Object.fromEntries(new FormData(e.target));
    (async()=>{try{const x=await PUT('/api/profile',profileBody(role,v,e.target));toast(x.msg);await boot()}catch(z){er.textContent=z.message;er.hidden=false}})()};
}
async function accountsPage(){
  await listPage({title:'Accounts',sub:'Create volunteer accounts and manage everyone else. Only coordinators can delete an account.',actions:`<button class="btn gold" data-act="newVol">Add volunteer</button>`,
    filters:`${F('Name or email','q')}${F('Role','role',{type:'select',options:opts(['Coordinator','Volunteer','Donor','Recipient'].map(s=>[s,s]),'','All roles')})}`,
    fetch:async q=>{const r=await GET('/api/accounts',q);CACHE.accts=r.accounts;return r},
    render:r=>r.accounts.length?`<div class="card"><div class="tw"><table class="t"><thead><tr><th>Name</th><th>Role</th><th>Contact</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>${r.accounts.map(a=>`<tr><td><span style="display:flex;gap:10px;align-items:center">${avatar(a.name,a.picture,1)}<b>${esc(a.name)}</b></span></td><td>${a.role}</td><td>${esc(a.email)}<br><span class="mut">${esc(a.phone||'')}</span></td><td>${pill(a.active?'Active':'Disabled')}${a.approval&&a.approval!=='Approved'?' '+pill(a.approval):''}</td><td class="mut">${a.last_login?fDT(a.last_login):'Never'}</td>
      <td class="act"><button class="btn ghost sm" data-act="editAcct" data-id="${a.id}">Edit</button>${a.id===ME.id?'':`<button class="btn ghost sm" data-act="toggleAcct" data-id="${a.id}">${a.active?'Disable':'Enable'}</button><button class="btn danger sm" data-act="delAcct" data-id="${a.id}">Delete</button>`}</td></tr>`).join('')}</tbody></table></div></div>`:'',empty:'No accounts found'});
}
function newVol(){
  modal('Add a volunteer',`${F('Name','name',{req:1})}<div class="grid2">${F('Email','email',{type:'email',req:1})}${F('Phone','phone',{req:1})}</div>${F('Temporary password','password',{type:'password',req:1,attrs:'minlength="8"',hint:'At least 8 characters. Tell the volunteer to change it after logging in.'})}${slotsEditor([])}`,
  async(v,f)=>{const r=await POST('/api/accounts/volunteer',{...v,slots:$$('.srow',f).map(x=>({day:$('[name=day]',x).value,start:$('[name=start]',x).value,end:$('[name=end]',x).value}))});toast(r.msg);refresh()},{wide:1,submit:'Create account'});
}
async function editAcct(id){
  const r=await GET('/api/accounts/'+id),role=r.account.role;
  modal(`Edit ${role.toLowerCase()} account`,`${role==='Volunteer'?picForm('',r.profile.Picture,r.profile.Name):''}${profileFields(role,r.account,r.profile,r.slots,true)}<label class="chk"><input type="checkbox" name="is_active" ${r.account.active?'checked':''} ${id===ME.id?'disabled':''}><span><b>Account is active</b><small>Disabled accounts cannot log in.</small></span></label>`,
  async(v,f)=>{const b=profileBody(role,v,f);b.is_active=$('[name=is_active]',f).checked;const x=await PUT('/api/accounts/'+id,b);toast(x.msg);refresh()},{wide:role==='Volunteer'});
  bindPic(`/api/accounts/${id}/picture`);
}

/* ---------- reports ---------- */
const tbl=rows=>rows.length?`<div class="card"><div class="tw"><table class="t"><thead><tr>${Object.keys(rows[0]).map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${Object.values(r).map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`:'<div class="card"><p class="note">No records for this period.</p></div>';
async function reportsPage(){
  const y=new Date().getFullYear(),mo=['January','February','March','April','May','June','July','August','September','October','November','December'];
  await listPage({title:'Reports',sub:'Choose a report, a year, and a month. Leave the month on "Whole year" for an annual report.',actions:`<button class="btn ghost" onclick="window.print()">Print</button>`,
    filters:`${F('Report','type',{type:'select',options:opts([['donation','Donation and Distribution Summary'],['waste','Inventory Waste Summary']])})}${F('Year','year',{type:'select',options:opts(Array.from({length:6},(_,i)=>[y-i,y-i]),y)})}${F('Month','month',{type:'select',options:opts(mo.map((m,i)=>[i+1,m]),new Date().getMonth()+1,'Whole year')})}`,
    fetch:q=>GET('/api/report',q),
    render:r=>`<h2 style="margin-bottom:14px">${esc(r.title)}</h2><div class="stats">${r.summary.map(([l,v])=>`<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join('')}</div>${r.tables.map(([t,rows])=>`<h3 class="sec">${esc(t)}</h3>${tbl(rows)}`).join('')}`});
}

/* ---------- AI + alerts ---------- */
async function aiPage(){
  $('#main').innerHTML=head('AI and alerts','The AI flags food that may expire before it is given out and emails coordinators about missed or delayed pickups.',`<a class="btn ghost" href="/viewer" target="_blank" rel="noopener">Open database viewer</a>`)+
  `<div class="two"><div class="card pad"><h3>Run the checks now</h3><p class="mut">Moves expired items to the waste table, flags items with 3 days or less left, marks late pickups, and sends alert emails. This also runs by itself every few hours.</p><button class="btn" id="run">Run AI check</button><div class="out" id="runout" hidden></div></div>
  <div class="card pad"><h3>Ask the AI</h3><p class="mut">Writes a short report from live inventory, or answers a question about it. The free AI tier allows about 5 requests a minute.</p><form id="ask" style="display:flex;gap:8px"><input name="question" placeholder="e.g. What should go in a hamper for a vegetarian family of 5?" aria-label="Question"><button class="btn">Ask</button></form><div class="chips"><button class="chip" data-q="">Write the inventory report</button><button class="chip" data-q="Which items should we give out first this week?">What to give out first</button><button class="chip" data-q="Which categories waste the most food, and why?">Biggest waste</button></div><div class="out" id="askout" hidden></div></div></div>
  <h3 class="sec">Alert emails sent</h3><div class="card" id="mails">Loading…</div>`;
  const show=(id,t)=>{const o=$(id);o.hidden=false;o.textContent=t};
  $('#run').onclick=async e=>{e.target.disabled=true;show('#runout','Running…');try{const r=await POST('/api/ai/run');show('#runout',r.log.join('\n'));loadMails()}catch(x){show('#runout',x.message)}e.target.disabled=false};
  const ask=async q=>{show('#askout','Thinking…');try{const r=await POST('/api/ai/insights',{question:q});show('#askout',r.text)}catch(x){show('#askout',x.message)}};
  $('#ask').onsubmit=e=>{e.preventDefault();ask(new FormData(e.target).get('question'))};
  $$('.chip[data-q]').forEach(c=>c.onclick=()=>ask(c.dataset.q));
  async function loadMails(){try{const {emails}=await GET('/api/emails');$('#mails').innerHTML=emails.length?emails.map(m=>`<details class="mail"><summary><b>${esc(m.subject)}</b>${pill(m.status)}<span class="mut">to ${esc(m.to_email)} (${m.role}), ${fDT(m.sent)}, written by ${esc(m.written_by)}</span></summary><pre>${esc(m.body)}</pre></details>`).join(''):'<p class="note">No alert emails yet. Run the check to create some.</p>'}catch(e){$('#mails').innerHTML=errBox(e)}}
  loadMails();
}

/* ---------- page registry ---------- */
const PAGES={
  Donor:{home:donorHome,donations:donationsPage,profile:profilePage},
  Recipient:{home:recipientHome,hampers:hampersPage,profile:profilePage},
  Volunteer:{home:volHome,distributions:distPage,inventory:invPage,donations:donationsPage,shifts:shiftsPage,profile:profilePage},
  Coordinator:{home:coHome,recipients:recipientsPage,accounts:accountsPage,shifts:shiftsPage,inventory:invPage,distributions:distPage,reports:reportsPage,ai:aiPage,profile:profilePage}};

/* ---------- click + change delegation ---------- */
const ACT={
  close:()=>$('#dlg').close(),
  menu:()=>document.body.classList.toggle('nav-open'),
  logout:()=>guard(async()=>{await POST('/api/logout');ME=null;showAuth()}),
  delrow:t=>t.closest('.irow,.srow').remove(),
  addDon:()=>$('#rows').insertAdjacentHTML('beforeend',donRow()),
  addDist:()=>$('#rows').insertAdjacentHTML('beforeend',dRow()),
  addSlot:()=>$('#slots').insertAdjacentHTML('beforeend',slotRow()),
  newDonation:()=>guard(newDonation),
  editDon:t=>guard(()=>editDonation(t.dataset.id)),
  editItem:t=>editItem(t.dataset.id),
  delItem:t=>ask('Delete this item?')&&guard(async()=>{toast((await DEL('/api/inventory/'+t.dataset.id)).msg);refresh()}),
  cats:()=>guard(cats),
  renCat:t=>{const n=prompt('New name for this category:',t.dataset.name);if(n)guard(async()=>{await PUT('/api/categories/'+t.dataset.id,{name:n});await CACHE.drawCats()})},
  delCat:t=>ask('Delete this category?')&&guard(async()=>{await DEL('/api/categories/'+t.dataset.id);await CACHE.drawCats()}),
  newDist:()=>guard(()=>distModal()),
  editDist:t=>guard(()=>distModal(t.dataset.id)),
  status:t=>{const s=t.dataset.s;if(s==='Missed'&&!ask('Mark this pickup as missed? The items go back to stock and coordinators are emailed.'))return;
    guard(async()=>{toast((await POST(`/api/distributions/${t.dataset.id}/status`,{status:s})).msg);refresh()})},
  delDist:t=>ask('Delete this distribution? Its items go back to stock.')&&guard(async()=>{toast((await DEL('/api/distributions/'+t.dataset.id)).msg);refresh()}),
  assignShift:t=>guard(()=>assignShift(t.dataset.id)),
  newShift:()=>shiftModal(null),
  editShift:t=>shiftModal(CACHE.shifts.find(s=>s.id==t.dataset.id)),
  delShift:t=>ask('Delete this shift? Pickups on it will need a new shift.')&&guard(async()=>{toast((await DEL('/api/shifts/'+t.dataset.id)).msg);refresh()}),
  decide:t=>guard(async()=>{toast((await POST(`/api/coordinator/recipients/${t.dataset.id}/decision`,{decision:t.dataset.d})).msg);refresh()}),
  newVol:()=>newVol(),
  editAcct:t=>guard(()=>editAcct(t.dataset.id)),
  toggleAcct:t=>{const a=CACHE.accts.find(x=>x.id==t.dataset.id);guard(async()=>{toast((await PUT('/api/accounts/'+a.id,{is_active:!a.active})).msg);refresh()})},
  delAcct:t=>{const a=CACHE.accts.find(x=>x.id==t.dataset.id);ask(`Permanently delete ${a.name}'s account? This cannot be undone.`)&&guard(async()=>{toast((await DEL('/api/accounts/'+a.id)).msg);refresh()})}};
document.addEventListener('click',e=>{const t=e.target.closest('[data-act]');if(t&&ACT[t.dataset.act])ACT[t.dataset.act](t,e)});
document.addEventListener('change',e=>{
  if(e.target.name==='recipient_id'){const o=e.target.selectedOptions[0],n=$('#diet');if(n){n.hidden=!o.value;n.textContent=o.value?`Household of ${o.dataset.hh}. Dietary needs: ${o.dataset.diet}`:''}}
  if(e.target.name==='item_id'){const o=e.target.selectedOptions[0],q=e.target.closest('.irow').querySelector('[name=quantity]');if(o&&o.dataset.max)q.max=o.dataset.max}});
boot();