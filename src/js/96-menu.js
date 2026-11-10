/* ===== Menu, pause, full time ===== */
function crest(T){const c=document.createElement('span');c.className='crest';c.style.background='#'+new THREE.Color(T.kit).getHexString();c.style.color=colorDist(T.kit,0xffffff)<.5?'#111':'#fff';c.textContent=T.code[0];return c}
function buildChips(el,key){el.innerHTML='';TEAMS.forEach((T,i)=>{const b=document.createElement('button');b.className='chip';b.append(crest(T),T.name);
  b.addEventListener('click',()=>{sel[key]=i;if(sel.team===sel.opp){const o=key==='team'?'opp':'team';sel[o]=(i+1)%TEAMS.length}refreshMenu()});el.append(b)})}
function bindSeg(el,key,num){el.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{sel[key]=num?+b.dataset.v:b.dataset.v;refreshMenu()}))}
function refreshMenu(){
  [...$('#teamPick').children].forEach((b,i)=>b.setAttribute('aria-pressed',i===sel.team));
  [...$('#oppPick').children].forEach((b,i)=>b.setAttribute('aria-pressed',i===sel.opp));
  $('#lenPick').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',+b.dataset.v===sel.len));
  $('#diffPick').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.v===sel.diff));
  $('#camPick').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',+b.dataset.v===sel.cam));
  try{localStorage.setItem('strike27',JSON.stringify(sel))}catch(e){}
}
try{const v=JSON.parse(localStorage.getItem('strike27')||'null');if(v)Object.assign(sel,v)}catch(e){}
buildChips($('#teamPick'),'team');buildChips($('#oppPick'),'opp');
bindSeg($('#lenPick'),'len',true);bindSeg($('#diffPick'),'diff',false);bindSeg($('#camPick'),'cam',true);refreshMenu();

function resetMatch(){
  S.score=[0,0];S.half=1;S.clock=0;REC.count=0;S.timeScale=1;S.paused=false;RP=null;
  players.length=0;players.push(...ALL);for(const t of [0,1]){TP[t].length=0;TP[t].push(...ROSTER[t])}
  players.forEach(p=>{p.stam=1;p.celebT=0});
  S.stats={shots:[0,0],poss:[0,0],fouls:[0,0],cards:[[0,0],[0,0]],offsides:[0,0],subs:[0,0]};
  S.subsLeft=[5,5];S.subQueue=[];S.aiSubAt=[0,0];S.adv=null;S.offTeam=-1;S.fatK=.24/S.halfLen;S.press=[1,1];setupTeams();paintCrowd();updateBoard();
}
function startDemo(){
  S.demo=true;S.user=-1;S.ctrl=null;S.halfLen=99999;S.camMode=0;S.diff=DIFF.pro;
  const a=(Math.random()*TEAMS.length)|0;let b=(Math.random()*TEAMS.length)|0;if(b===a)b=(a+1)%TEAMS.length;S.teams=[TEAMS[a],TEAMS[b]];
  resetMatch();restart('kickoff',0);
}
function startMatch(){
  AU.init();if(AU.ctx&&AU.ctx.state==='suspended')AU.ctx.resume();
  S.demo=false;S.user=0;S.teams=[TEAMS[sel.team],TEAMS[sel.opp]];S.halfLen=sel.len*60;S.diff=DIFF[sel.diff];S.camMode=sel.cam;
  resetMatch();S.press=[1,{amateur:0,pro:1,legend:2}[sel.diff]];$('#pressBtn').textContent='Pressing: '+PRESS_NAMES[1];$('#subs').hidden=true;$('#menu').hidden=true;$('#ft').hidden=true;$('#hud').hidden=false;$('#joyHint').classList.remove('gone');lastMode=null;
  restart('kickoff',0);banner(S.teams[0].code+'  v  '+S.teams[1].code,'Kick off');
  $('#camBtn').textContent='Camera: '+CAMS[S.camMode].name;
  try{const d=document.documentElement;if(matchMedia('(pointer:coarse)').matches&&d.requestFullscreen)d.requestFullscreen().then(()=>screen.orientation&&screen.orientation.lock&&screen.orientation.lock('landscape').catch(()=>{})).catch(()=>{})}catch(e){}
}
function togglePause(force){S.paused=force!==undefined?force:!S.paused;$('#pause').hidden=!S.paused}
function toMenu(){S.paused=false;$('#pause').hidden=true;$('#subs').hidden=true;$('#ft').hidden=true;$('#hud').hidden=true;$('#menu').hidden=false;banner('');startDemo()}
function showFullTime(){
  $('#hud').hidden=true;$('#ft').hidden=false;$('#ftA').textContent=S.teams[0].code;$('#ftB').textContent=S.teams[1].code;$('#ftS').textContent=S.score[0]+' – '+S.score[1];
  const tp=S.stats.poss[0]+S.stats.poss[1]||1,pa=Math.round(S.stats.poss[0]/tp*100);
  const cd=t=>`${S.stats.cards[t][0]}Y · ${S.stats.cards[t][1]}R`;
  const rows=[['Possession',pa+'%',(100-pa)+'%'],['Shots',S.stats.shots[0],S.stats.shots[1]],['Fouls',S.stats.fouls[0],S.stats.fouls[1]],['Cards',cd(0),cd(1)],['Offsides',S.stats.offsides[0],S.stats.offsides[1]],['Subs',S.stats.subs[0],S.stats.subs[1]],['Result',S.score[0]>S.score[1]?'Win':S.score[0]<S.score[1]?'Loss':'Draw','']];
  $('#ftStats').innerHTML=rows.map((r,i)=>`<dd class="l" style="--r:${i+1}">${r[1]}</dd><dt style="grid-row:${i+1}">${r[0]}</dt><dd class="r" style="--r:${i+1}">${r[2]}</dd>`).join('');
}
$('#kickoff').addEventListener('click',startMatch);
$('#pauseBtn').addEventListener('click',()=>togglePause(true));
$('#resume').addEventListener('click',()=>togglePause(false));
$('#quit').addEventListener('click',toMenu);
$('#again').addEventListener('click',startMatch);
$('#toMenu').addEventListener('click',toMenu);
$('#camBtn').addEventListener('click',()=>{S.camMode=(S.camMode+1)%CAMS.length;sel.cam=S.camMode;refreshMenu();$('#camBtn').textContent='Camera: '+CAMS[S.camMode].name});
$('#sndBtn').addEventListener('click',()=>{S.sound=!S.sound;AU.mute(S.sound);$('#sndBtn').textContent='Sound: '+(S.sound?'On':'Off')});
touch.addEventListener('pointerdown',()=>{if(S.phase==='replay'&&RP&&RP.t>.6)afterGoal()});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&S.user>=0&&(S.phase==='play'||S.phase==='restart'))togglePause(true)});
addEventListener('resize',()=>{renderer.setSize(innerWidth,innerHeight);camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix()});
