/* ===== Squads, fitness, substitutions ===== */
const ALL=players.slice(),ROSTER=[TP[0].slice(),TP[1].slice()],BENCH=[[],[]];
const R=(t,i)=>ROSTER[t][i].off?null:ROSTER[t][i];
const RA=(t,i)=>R(t,i)||TP[t].filter(q=>!q.gk).sort((a,b)=>Math.abs(a.i-i)-Math.abs(b.i-i))[0];
const POSG=r=>r==='GK'?'GK':/B$/.test(r)?'DEF':/M$/.test(r)?'MID':'FWD';
function genStats(role,b){return{pace:b(FWD.has(role)?6:role==='CB'?-6:0),shoot:b(FWD.has(role)?8:role==='CB'||role==='GK'?-20:-4),pass:b(role.includes('M')?7:0),
  drib:b(FWD.has(role)?7:role==='CB'?-8:0),def:b(role==='CB'||role==='DM'?10:FWD.has(role)?-18:role.endsWith('B')?5:0),gk:b(role==='GK'?8:-40)}}
const fat=p=>1+(1-p.stam)*.7;
const matchMin=()=>((S.half-1)*S.halfLen+Math.min(S.clock,S.halfLen))/S.halfLen*45;
function makeBench(t,T,rnd){
  const roles=['GK','CB','RB','CM','DM','RW','ST'],nums=[12,15,14,16,18,17,19];
  BENCH[t]=roles.map((role,k)=>{const r=T.rating-3+(rnd()*8-4),b=x=>clamp(Math.round(r+x+(rnd()*8-4)),45,94);
    return{role,num:nums[k],name:INIT[(rnd()*INIT.length)|0]+'. '+SUR[(rnd()*SUR.length)|0],stats:genStats(role,b),skin:(rnd()*4)|0,hair:(rnd()*5)|0,used:false}});
}
function doSub(t,p,bi){
  const b=BENCH[t][bi];if(!b||b.used||p.off||S.subsLeft[t]<=0)return false;
  const out={role:p.role,num:p.num,name:p.name,stats:p.stats,skin:p.skin,hair:p.hair,used:true,fit:p.fit};
  p.num=b.num;p.name=b.name;p.stats=b.stats;p.jog=4.7+b.stats.pace/100*1.1;p.sprint=6.7+b.stats.pace/100*2.1;p.stam=1;p.fit=1;p.yc=0;
  p.skin=b.skin;p.hair=b.hair;p.mesh.head.material=SKIN[b.skin];p.mesh.hairM.material=HAIR[b.hair];
  BENCH[t][bi]=out;S.subsLeft[t]--;S.stats.subs[t]++;
  notice(`<span><b>SUBSTITUTION · ${S.teams[t].code}</b><span class="in">▲ #${b.num} ${b.name}</span>&nbsp;&nbsp;<span class="out">▼ #${out.num} ${out.name}</span></span>`);
  if(S.ctrl===p)setCtrl(p);
  return true;
}
function applySubQueue(){for(const q of S.subQueue)doSub(q.t,q.p,q.bi);S.subQueue=[]}
function aiSubs(t){
  const m=matchMin();if(m<56||S.subsLeft[t]<=0||m-S.aiSubAt[t]<8)return;
  const tired=TP[t].filter(p=>!p.gk&&p.fit<.8).sort((a,b)=>a.fit-b.fit)[0];if(!tired)return;
  let bi=BENCH[t].findIndex(b=>!b.used&&POSG(b.role)===POSG(tired.role));
  if(bi<0)bi=BENCH[t].findIndex(b=>!b.used&&b.role!=='GK');
  if(bi>=0&&doSub(t,tired,bi)){S.aiSubAt[t]=m;if(!S.aiSubTwice){S.aiSubTwice=true;S.aiSubAt[t]=-99;aiSubs(t);S.aiSubAt[t]=m;S.aiSubTwice=false}}
}
function sendOff(p){
  p.off=true;p.pendingOff=false;p.recv=false;p.offside=false;
  const i=players.indexOf(p);if(i>=0)players.splice(i,1);const j=TP[p.team].indexOf(p);if(j>=0)TP[p.team].splice(j,1);
  p.mesh.root.visible=false;if(ball.owner===p)ball.owner=null;
  if(S.ctrl===p){S.ctrl=null;setCtrl(TP[p.team].find(q=>!q.gk))}
}
