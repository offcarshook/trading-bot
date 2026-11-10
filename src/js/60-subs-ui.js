/* ===== Substitutions screen ===== */
let subPick=null;
function fitBar(f){return`<i class="fit"><i style="transform:scaleX(${clamp(f,0,1).toFixed(2)});background:${f>.7?'var(--signal)':f>.5?'var(--flood)':'var(--flare)'}"></i></i>`}
function renderSubs(){
  const t=S.user;if(t<0)return;
  $('#subsLeft').textContent=`${S.subsLeft[t]} left`;
  const pend=new Map(S.subQueue.map(q=>[q.p,q]));
  $('#subOn').innerHTML=ROSTER[t].map((p,k)=>{const q=pend.get(p),b=q&&BENCH[t][q.bi];
    return`<button class="subrow${p.off?' gone':''}" data-on="${k}" aria-pressed="${subPick===p}" ${p.off?'disabled':''}><b class="pos">${p.role}</b><span class="nm">#${p.num} ${p.name}${p.yc?'<i class="yc"></i>':''}${p.off?' · sent off':''}</span>${q?`<em>→ #${b.num}</em>`:fitBar(p.fit)}</button>`}).join('');
  const queued=new Set(S.subQueue.map(q=>q.bi));
  $('#subBench').innerHTML=BENCH[t].map((b,k)=>`<button class="subrow${b.used?' gone':''}" data-bench="${k}" ${b.used||queued.has(k)?'disabled':''}><b class="pos">${b.role}</b><span class="nm">#${b.num} ${b.name}</span>${b.used?'<em>subbed off</em>':queued.has(k)?'<em>coming on</em>':fitBar(1)}</button>`).join('');
  $('#subTip').textContent=S.subsLeft[t]-S.subQueue.length<=0?'No substitutions left.':subPick?`Now pick who replaces #${subPick.num} ${subPick.name}.`:'Tap a player on the pitch, then someone from the bench. Changes happen at the next stoppage.';
}
function openSubs(){if(S.user<0)return;S.paused=true;$('#pause').hidden=true;$('#subs').hidden=false;subPick=null;renderSubs()}
function closeSubs(){$('#subs').hidden=true;S.paused=false;if(['dead','restart','half','cut'].includes(S.phase)&&S.phase!=='cut')applySubQueue()}
$('#subOn').addEventListener('click',e=>{const b=e.target.closest('[data-on]');if(!b)return;const p=ROSTER[S.user][+b.dataset.on];
  const qi=S.subQueue.findIndex(q=>q.p===p);if(qi>=0){S.subQueue.splice(qi,1);subPick=null}else subPick=subPick===p?null:p;renderSubs()});
$('#subBench').addEventListener('click',e=>{const b=e.target.closest('[data-bench]');if(!b||!subPick)return;
  if(S.subsLeft[S.user]-S.subQueue.length<=0)return;S.subQueue.push({t:S.user,p:subPick,bi:+b.dataset.bench});subPick=null;renderSubs()});
$('#subDone').addEventListener('click',closeSubs);
$('#subsBtn').addEventListener('click',openSubs);
$('#subsOpen').addEventListener('click',openSubs);
const PRESS_NAMES=['Low block','Balanced','High press'];
$('#pressBtn').addEventListener('click',()=>{S.press[S.user]=(S.press[S.user]+1)%3;$('#pressBtn').textContent='Pressing: '+PRESS_NAMES[S.press[S.user]]});
