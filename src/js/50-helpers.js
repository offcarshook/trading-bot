/* ===== Geometry helpers for the match logic ===== */
const inOwnBox=p=>Math.abs(p.z)<BOXZ&&p.x*SIDE[p.team]<-BOXX;
function nearestOpp(p){let b=null,bd=1e9;for(const o of TP[1-p.team]){const d=hyp(o.x-p.x,o.z-p.z);if(d<bd){bd=d;b=o}}return[b,bd]}
const pressureOn=p=>clamp(1-(nearestOpp(p)[1]-1)/4,0,1);
const aiErr=p=>p.team===S.user?1:S.diff.err;
function segDist(ax,az,bx,bz,px,pz){const dx=bx-ax,dz=bz-az,l2=dx*dx+dz*dz||1;const t=clamp(((px-ax)*dx+(pz-az)*dz)/l2,0,1);return hyp(ax+dx*t-px,az+dz*t-pz)}
function openness(p,t){let seg=1e9,mark=1e9;for(const o of TP[1-p.team]){seg=Math.min(seg,segDist(p.x,p.z,t.x,t.z,o.x,o.z));mark=Math.min(mark,hyp(o.x-t.x,o.z-t.z))}
  return clamp((seg-.8)/4,0,1)*.6+clamp((mark-1)/5,0,1)*.4}
function predictBall(t){
  const vh=hyp(ball.vx,ball.vz);if(vh<.01)return[ball.x,ball.z];
  const ux=ball.vx/vh,uz=ball.vz/vh;let tl=0;
  if(ball.y>BR+.02||ball.vy>.1)tl=(ball.vy+Math.sqrt(ball.vy*ball.vy+2*G*Math.max(0,ball.y-BR)))/G;
  let d;if(t<=tl)d=vh*t;else{const v2=tl>0?vh*.82:vh,tr=t-tl,ts=Math.min(tr,v2/ROLL);d=vh*tl+v2*ts-.5*ROLL*ts*ts}
  return[ball.x+ux*d,ball.z+uz*d];
}
function intercept(p){
  const mx=p.sprint*(.85+.15*p.stam);
  for(let k=0;k<=28;k++){const t=k*.1,[bx,bz]=predictBall(t);const d=Math.max(0,hyp(bx-p.x,bz-p.z)-.6);if(d/mx+.12<=t)return[bx,bz,t]}
  const [bx,bz]=predictBall(2.8);return[bx,bz,2.8+hyp(bx-p.x,bz-p.z)/mx];
}
