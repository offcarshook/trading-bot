/* ===== Discipline: fouls, advantage, cards ===== */
function showCard(p,red){
  REF.cardT=2.4;REF.cardMesh.material.color.setHex(red?0xe0202a:0xffd400);REF.faceT=Math.atan2(p.z-REF.z,p.x-REF.x);
  notice(`<i class="cardi" style="background:${red?'#e0202a':'#ffd400'}"></i><span><b>${red?'RED CARD':'YELLOW CARD'}</b>#${p.num} ${p.name} · ${S.teams[p.team].code}</span>`);S.stats.cards[p.team][red?1:0]++;
}
function book(p,card){
  if(card==='yellow'){p.yc=(p.yc||0)+1;if(p.yc<2){showCard(p,false);return}}
  showCard(p,true);p.pendingOff=true;
}
function foul(f,v,kind){
  if(S.phase!=='play'||S.adv)return;
  S.stats.fouls[f.team]++;
  const x=clamp(v.x,-HL+1,HL-1),z=clamp(v.z,-HW+1,HW-1),e=SIDE[v.team];
  const behind=Math.cos(f.face)*Math.cos(v.face)+Math.sin(f.face)*Math.sin(v.face)>.45;
  const dG=hyp(e*HL-v.x,v.z);let cover=0;
  for(const d of TP[f.team]){if(d===f||d.gk)continue;if((d.x-v.x)*e>0&&Math.abs(d.z-v.z)<14)cover++}
  const lastMan=dG<32&&cover===0&&v.x*e>0;
  let card=null;
  if(lastMan&&Math.random()<.75)card='red';
  else if(Math.random()<(kind==='slide'?(behind?.7:.3):(behind?.25:.08)))card='yellow';
  const inBox=x*e>BOXX&&Math.abs(z)<BOXZ;
  // advantage: the fouled side kept the ball and is going forward
  const own=ball.owner;let keep=own&&own.team===v.team&&own!==v;
  if(!own){let n=null,nd=1e9;for(const q of players){const d=hyp(q.x-ball.x,q.z-ball.z);if(d<nd){nd=d;n=q}}keep=n&&n.team===v.team&&n!==v&&nd<3}
  if(card)book(f,card);
  if(!inBox&&card!=='red'&&keep&&x*e>-15){S.adv={team:v.team,x,z,t:0};REF.advT=1.4;toast('ADVANTAGE');return}
  if(inBox){ballDead('penalty',v.team,e*(HL-11),0);return}
  ballDead('freekick',v.team,x,z,'FOUL');
}
function stepAdvantage(dt){
  const a=S.adv;if(!a)return;a.t+=dt;
  if(S.phase!=='play'){S.adv=null;return}
  const own=ball.owner;
  if(own&&own.team!==a.team&&a.t<2.2){S.adv=null;ballDead('freekick',a.team,a.x,a.z,'BACK FOR THE FREE KICK');return}
  if(a.t>3)S.adv=null;
}
