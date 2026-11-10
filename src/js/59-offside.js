/* ===== Offside ===== */
function markOffside(T,kicker){
  const s=SIDE[T],xs=TP[1-T].map(o=>o.x*s).sort((a,b)=>b-a),line=Math.max(xs[1]??0,ball.x*s,0);
  for(const q of players)q.offside=q.team===T&&!q.gk&&q!==kicker&&q.x*s>line+.3;
  S.offTeam=T;
}
function clearOffside(){for(const q of ALL)q.offside=false;S.offTeam=-1}
function isOffsideNow(q){const s=SIDE[q.team],xs=TP[1-q.team].map(o=>o.x*s).sort((a,b)=>b-a);return q.x*s>Math.max(xs[1]??0,ball.x*s,0)+.3}
function callOffside(p){
  S.stats.offsides[p.team]++;(p.x>0?AR1:AR2).flagT=2.6;
  const x=clamp(p.x,-HL+1,HL-1),z=clamp(p.z,-HW+1,HW-1);clearOffside();
  ballDead('freekick',1-p.team,x,z,'OFFSIDE');
}
