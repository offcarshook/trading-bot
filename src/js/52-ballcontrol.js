/* ===== Ball control: possession, kicks, passes, shots ===== */
function setCtrl(p){if(S.user<0||!p||p.team!==S.user||p.gk)return;S.ctrl=p;$('#whoNum').textContent=p.num;$('#whoName').textContent=p.name}
function gainPossession(p){
  if(p.offside&&S.phase==='play'){callOffside(p);return}
  clearOffside();
  ball.owner=p;ball.shot=false;ball.passTo=null;ball.curl=0;S.lastTouch=p.team;p.possT=0;
  players.forEach(q=>q.recv=false);
  p.hands=p.gk&&inOwnBox(p);if(p.hands)p.holdT=1.1;ball.dip=0;
  if(p.team===S.user)setCtrl(p);
  p.aiT=p.team===S.user?.3:S.diff.react*.7+.05;AU.touch();
}
function kick(p,vx,vy,vz,curl,soft){
  ball.owner=null;ball.vx=vx;ball.vy=vy;ball.vz=vz;ball.curl=curl||0;ball.dip=0;ball.y=Math.max(ball.y,BR+.01);
  ball.shot=false;ball.passTo=null;S.lastTouch=p.team;S.lastKicker=p;
  p.cool=.3;p.kickT=soft?0:.28;p.holdT=0;p.hands=false;p.mustPass=false;players.forEach(q=>q.recv=false);
  const rsT=S.phase==='restart'&&S.rs?S.rs.type:null;if(!rsT||rsT==='freekick')markOffside(p.team,p);else clearOffside();
  if(S.phase==='restart'){S.phase='play';S.rs=null}
  if(soft)AU.touch();else AU.kick(hyp(vx,vy,vz)/28);
}
function bestTarget(p,dir,through,maxD){
  const s=SIDE[p.team];let best=null,bs=-1e9;
  for(const t of TP[p.team]){
    if(t===p)continue;const dx=t.x-p.x,dz=t.z-p.z,d=hyp(dx,dz);if(d<3.5||d>maxD)continue;
    let sc=0;const fwd=dx*s/d;
    if(dir){const c=(dx*dir[0]+dz*dir[1])/d;if(c<.42)continue;sc+=c*3.2;if(t.gk)sc-=2}
    else{if(t.gk)continue;sc+=fwd*1.3+(t.x*s)/HL*.7;if(isOffsideNow(t))sc-=3}
    sc+=openness(p,t)*1.5-Math.abs(d-16)/28;
    if(through)sc+=fwd*.7+(FWD.has(t.role)?.4:0);
    if(sc>bs){bs=sc;best=t}
  }
  return best;
}
function passBall(p,dir,kind){
  const s=SIDE[p.team],through=kind==='through'||kind==='lobthrough',lob=kind==='lob'||kind==='lobthrough';
  const isThrow=S.rs&&S.rs.type==='throw';
  const maxD=isThrow?26:lob?62:44;
  const tgt=bestTarget(p,dir,through,maxD);
  let ax,az;
  if(tgt){
    let t=hyp(tgt.x-p.x,tgt.z-p.z)/16;
    for(let it=0;it<3;it++){
      ax=tgt.x+tgt.vx*t*.8+(through?s*6+tgt.vx*.4:0);az=tgt.z+tgt.vz*t*.8+(through&&dir?dir[1]*2:0);
      ax=clamp(ax,-HL+1,HL-1);az=clamp(az,-HW+1,HW-1);
      const d=hyp(ax-ball.x,az-ball.z);t=lob?d/clamp(11+d*.35,13,27):d/Math.max(10,Math.sqrt(100+2*ROLL*d)-d*.05);
    }
  }else{const dd=dir||[Math.cos(p.face),Math.sin(p.face)];ax=p.x+dd[0]*(lob?26:16);az=p.z+dd[1]*(lob?26:16)}
  const d=hyp(ax-ball.x,az-ball.z);
  const err=((1-p.stats.pass/100)*.11+pressureOn(p)*.05)*aiErr(p)*fat(p)*randn();
  const ang=Math.atan2(az-ball.z,ax-ball.x)+err;
  let vx,vy,vz;
  if(lob){const vh=clamp(11+d*.35,13,27),t=d/vh;vy=.5*G*t*rand(.96,1.04);vx=Math.cos(ang)*vh;vz=Math.sin(ang)*vh}
  else{const ve=through?7:10;let v0=clamp(Math.sqrt(ve*ve+2*ROLL*d),10,30)*(1+err*.6);vx=Math.cos(ang)*v0;vz=Math.sin(ang)*v0;vy=0}
  kick(p,vx,vy,vz,0);
  if(tgt){ball.passTo=tgt;tgt.recv=true;if(p.team===S.user)setCtrl(tgt)}
  else if(p.team===S.user&&p.gk){let b=null,bd=1e9;for(const q of TP[S.user]){if(q.gk)continue;const dd=hyp(q.x-ax,q.z-az);if(dd<bd){bd=dd;b=q}}setCtrl(b)}
}
function shoot(p,power,aimZ,finesse){
  const s=SIDE[p.team],gx=HL*s,gk=TP[1-p.team][0];
  const over=Math.max(0,power-1);power=Math.min(power,1);
  let tz=aimZ!=null?aimZ*3.1:(gk.z>ball.z*.15?-1:1)*rand(1.6,3.0);
  const dx=gx-ball.x,dz=tz-ball.z,d=hyp(dx,dz);
  const errA=((1-p.stats.shoot/100)*.07+d/40*.05+pressureOn(p)*.05+over*.55+(finesse?0:power*.025))*aiErr(p)*fat(p)*randn();
  const vh=finesse?17+power*5:15+power*17;const t=d/vh;
  const ty=finesse?.7+rand(0,.9):.35+power*1.3+over*10+rand(-.3,.4);
  let curl=0,aimX=gx,aimZ2=tz;
  if(finesse){const ux=dx/d,uz=dz/d;curl=-Math.sign(tz||1)*Math.sign(ux)*7;const off=.5*curl*t*t;aimX=gx+uz*off;aimZ2=tz-ux*off}
  const ang=Math.atan2(aimZ2-ball.z,aimX-ball.x)+errA;
  const vy=(ty-ball.y+.5*G*t*t)/t;
  kick(p,Math.cos(ang)*vh,vy,Math.sin(ang)*vh,curl);
  ball.shot=true;ball.shotTeam=p.team;S.shotId++;S.stats.shots[p.team]++;
  if(p.team===S.user)buzz(25);
}
function skillMove(p,dir){
  if(p.skillCD>0)return;p.skillCD=1.1;p.skillT=.4;
  const [o,d]=nearestOpp(p);if(o&&d<3.6&&Math.random()<.42+p.stats.drib/220){o.stun=.75;toast('NUTMEG? NO — JUST COOKED')}
  p.vx+=dir[0]*3.2;p.vz+=dir[1]*3.2;p.face=Math.atan2(dir[1],dir[0]);
}
function standTackle(p){
  if(p.tackleT>0||p.stun>0||p.slideT>0)return;
  p.tackleT=.4;p.kickT=.25;const fx=Math.cos(p.face),fz=Math.sin(p.face);
  const o=ball.owner,bd=hyp(ball.x-p.x,ball.z-p.z);
  if(o&&o.team!==p.team&&!o.hands){
    if(bd<1.9||hyp(o.x-p.x,o.z-p.z)<1.4){
      let ch=.47+(p.stats.def-o.stats.drib)/140;if(o===S.ctrl&&!userSprinting())ch-=.1;if(p===S.ctrl)ch+=.12;
      if(Math.random()<clamp(ch,.2,.9)){
        o.stun=.4;
        if(Math.random()<.55)gainPossession(p);
        else{ball.owner=null;ball.vx=fx*6+rand(-2,2);ball.vz=fz*6+rand(-2,2);ball.vy=0;S.lastTouch=p.team;o.cool=.4;p.cool=.15}
        AU.burst(.12,900,.3);if(p.team===S.user)buzz(20);
      }else{p.stun=.65;if(Math.random()<.1)foul(p,o,'stand')}
    }
  }else if(!o&&bd<1.6){ball.vx=fx*7;ball.vz=fz*7;S.lastTouch=p.team}
  p.vx+=fx*2.2;p.vz+=fz*2.2;
}
function slideTackle(p){if(p.slideT>0||p.stun>0)return;p.slideT=.62;p.slideHit=false;const sp=Math.max(8,p.spd+2.5);p.vx=Math.cos(p.face)*sp;p.vz=Math.sin(p.face)*sp;AU.burst(.35,400,.25)}
function slideContact(p){
  if(p.slideHit)return;
  const bd=hyp(ball.x-p.x,ball.z-p.z);
  if(bd<1.3&&ball.y<.8){const o=ball.owner;if(o&&o.team===p.team)return;if(o){o.stun=.7}
    ball.owner=null;const f=p.face;ball.vx=Math.cos(f)*8+rand(-2,2);ball.vz=Math.sin(f)*8+rand(-2,2);ball.vy=1;S.lastTouch=p.team;p.slideHit=true;p.cool=.25;AU.burst(.12,900,.3);return}
  for(const o of TP[1-p.team]){if(hyp(o.x-p.x,o.z-p.z)<.95){p.slideHit=true;o.stun=.9;if(Math.random()<.65)foul(p,o,'slide');return}}
}
