/* ===== Simulation step ===== */
function moveToward(p,dt,tx,tz,maxSp,acc){
  const dx=tx-p.x,dz=tz-p.z,d=hyp(dx,dz);
  const sp=d>.25?Math.min(maxSp,d*2.2):0;
  const dvx=(d>0?dx/d*sp:0)-p.vx,dvz=(d>0?dz/d*sp:0)-p.vz,dl=hyp(dvx,dvz),a=acc*dt;
  if(dl>a){p.vx+=dvx/dl*a;p.vz+=dvz/dl*a}else{p.vx+=dvx;p.vz+=dvz}
}
function userMove(p,dt){
  const[ix,iz,m]=worldInput();
  const own=ball.owner;
  if(IN.contain&&own&&own.team!==p.team){const gx=-HL*SIDE[p.team],dx=gx-own.x,dz=-own.z,d=hyp(dx,dz)||1;
    moveToward(p,dt,own.x+dx/d*1.6+ix*1.5,own.z+dz/d*1.6+iz*1.5,p.jog,22);p.faceT=Math.atan2(own.z-p.z,own.x-p.x);return}
  if(IN.press&&own&&own.team!==p.team){const gx=-HL*SIDE[p.team],dx=gx-own.x,dz=-own.z,d=hyp(dx,dz)||1;
    moveToward(p,dt,own.x+dx/d*.9+ix*1.2,own.z+dz/d*.9+iz*1.2,p.stam>.05?p.sprint:p.jog,26);p.faceT=Math.atan2(own.z-p.z,own.x-p.x);p.sprinting=p.stam>.05;return}
  if(m<.05&&p.recv){moveToward(p,dt,p.tx,p.tz,p.jog,22);return}
  const sprint=userSprinting()&&p.stam>.05;
  const max=(sprint?p.sprint:p.jog)*(own===p?.93:1)*(.86+.14*p.stam);
  const tvx=ix*m*max,tvz=iz*m*max,dvx=tvx-p.vx,dvz=tvz-p.vz,dl=hyp(dvx,dvz),a=(m>.05?26:18)*dt;
  if(dl>a){p.vx+=dvx/dl*a;p.vz+=dvz/dl*a}else{p.vx=tvx;p.vz=tvz}
  if(m>.1)p.faceT=Math.atan2(iz,ix);
  p.sprinting=sprint&&m>.3;
}
function stepPlayers(dt){
  for(const p of players){
    p.cool-=dt;p.stun-=dt;p.kickT=Math.max(0,p.kickT-dt);p.tackleT-=dt;p.skillCD-=dt;p.skillT=Math.max(0,p.skillT-dt);p.celebT=Math.max(0,p.celebT-dt);p.throwT=Math.max(0,p.throwT-dt);p.diveT=Math.max(0,p.diveT-dt);p.jumpT=Math.max(0,p.jumpT-dt);
    if(ball.owner===p){p.possT+=dt;if(p.gk)p.holdT-=dt}
    p.faceT=null;p.sprinting=false;
    const lockedTaker=S.phase==='restart'&&S.rs&&p===S.rs.taker;
    if(p.slideT>0){p.slideT-=dt;p.vx*=1-2.3*dt;p.vz*=1-2.3*dt;if(S.phase==='play')slideContact(p);if(p.slideT<=0)p.stun=.45}
    else if(lockedTaker)takerMove(p,dt);
    else if(p.stun>0){p.vx*=1-8*dt;p.vz*=1-8*dt}
    else if(p===S.ctrl&&S.phase!=='goal'&&S.phase!=='cut'&&!(S.phase==='restart'&&(S.rs.type==='penalty'||S.rs.team===S.user)))userMove(p,dt);
    else if(p.gk){keeperThink(p);const diving=p.save&&p.diveT>0;
      if(diving){const dx=p.tx-p.x,dz=p.tz-p.z;p.vx=clamp(dx*6,-4,4);p.vz=Math.abs(dz)>.05?Math.sign(dz)*Math.min(7.2,Math.abs(dz)/dt):0}
      else moveToward(p,dt,p.tx,p.tz,p.run?p.sprint:5.2,20)}
    else{const fast=p.run&&p.stam>.15;let mx=(fast?p.sprint*.97:p.jog*.9)*(.86+.14*p.stam);
      if(p.team!==S.user&&ball.owner&&ball.owner.team!==p.team)mx*=S.diff.press;
      if(ball.owner===p)mx*=.93;moveToward(p,dt,p.tx,p.tz,mx,17);p.sprinting=fast&&p.spd>p.jog}
    p.x+=p.vx*dt;p.z+=p.vz*dt;
    p.x=clamp(p.x,-HL-2.5,HL+2.5);p.z=clamp(p.z,-HW-2.5,HW+2.5);
    p.spd=hyp(p.vx,p.vz);p.phase+=p.spd*dt*1.75;
    p.stam=clamp(p.stam+(p.sprinting?-.055:.03)*dt,0,1);
    p.fit=Math.max(.35,p.fit-(p.spd/7)*(p.sprinting?1.6:1)*(S.fatK||0)*dt);if(p.stam>p.fit)p.stam=p.fit;
    let ft=p.faceT;
    if(ft==null){if(p.spd>.6)ft=Math.atan2(p.vz,p.vx);else if(ball.owner!==p)ft=Math.atan2(ball.z-p.z,ball.x-p.x)}
    if(ft!=null&&p.slideT<=0&&p.diveT<=0){let d=ft-p.face;d=Math.atan2(Math.sin(d),Math.cos(d));const r=(ball.owner===p?9:11)*dt;p.face+=clamp(d,-r,r)}
  }
  // separation
  const NP=players.length;for(let i=0;i<NP;i++)for(let j=i+1;j<NP;j++){const a=players[i],b=players[j];const dx=b.x-a.x,dz=b.z-a.z,d2=dx*dx+dz*dz;
    if(d2<.64&&d2>1e-6){const d=Math.sqrt(d2),push=(.8-d)*.5;a.x-=dx/d*push;a.z-=dz/d*push;b.x+=dx/d*push;b.z+=dz/d*push}}
  // keep opponents back at set pieces
  if(S.phase==='restart'&&S.rs&&S.rs.type!=='throw'&&S.rs.type!=='penalty'){for(const p of TP[1-S.rs.team]){if(p.wall||p.gk)continue;const dx=p.x-ball.x,dz=p.z-ball.z,d=hyp(dx,dz);if(d<9.15&&d>0){p.x=ball.x+dx/d*9.15;p.z=ball.z+dz/d*9.15}}}
}
function stepBall(dt){
  const o=ball.owner;
  if(o){
    if(o.hands){ball.x=o.x+Math.cos(o.face)*.35;ball.z=o.z+Math.sin(o.face)*.35;ball.y=1.15;ball.vx=o.vx;ball.vz=o.vz;ball.vy=0;return}
    const lead=.55+o.spd*.07,tx=o.x+Math.cos(o.face)*lead,tz=o.z+Math.sin(o.face)*lead,k=1-Math.exp(-dt*18);
    const nx=ball.x+(tx-ball.x)*k,nz=ball.z+(tz-ball.z)*k;ball.vx=(nx-ball.x)/dt;ball.vz=(nz-ball.z)/dt;ball.x=nx;ball.z=nz;ball.y=BR;ball.vy=0;return;
  }
  if(S.phase==='restart'){ball.vx=ball.vy=ball.vz=0;const rs=S.rs;
    if(rs&&rs.type==='throw'){const tk=rs.taker,k=rs.kick?Math.min(1,rs.kickT/.3):0,o2=.12-k*.32;ball.x=tk.x+Math.cos(tk.face)*o2;ball.z=tk.z+Math.sin(tk.face)*o2;ball.z=Math.sign(ball.z)*Math.min(Math.abs(ball.z),HW-.05);ball.y=2.55}
    return}
  const vh=hyp(ball.vx,ball.vz);
  if(ball.y>BR+.001||ball.vy>0){
    ball.vy-=(G+ball.dip)*dt;const v=hyp(ball.vx,ball.vy,ball.vz),dr=1-.0022*v*dt;ball.vx*=dr;ball.vy*=dr;ball.vz*=dr;
    if(vh>1&&ball.curl){const cx=-ball.vz/vh*ball.curl*dt,cz=ball.vx/vh*ball.curl*dt;ball.vx+=cx;ball.vz+=cz}
  }else if(vh>0){const nv=Math.max(0,vh-ROLL*dt);ball.vx*=nv/vh;ball.vz*=nv/vh;ball.curl*=.9}
  ball.x+=ball.vx*dt;ball.y+=ball.vy*dt;ball.z+=ball.vz*dt;
  if(ball.y<BR){ball.y=BR;ball.dip=0;if(ball.vy<-1.2){ball.vy=-ball.vy*.48;ball.vx*=.76;ball.vz*=.76;ball.curl*=.4}else ball.vy=0}
  // advertising boards
  if(Math.abs(ball.z)>HW+4.2){ball.z=Math.sign(ball.z)*(HW+4.2);ball.vz*=-.3}
  if(Math.abs(ball.x)>HL+4.3&&Math.abs(ball.z)>GHW+.6){ball.x=Math.sign(ball.x)*(HL+4.3);ball.vx*=-.3}
  // posts & bar
  for(const s of [-1,1]){const gx=s*HL;if(Math.abs(ball.x-gx)>1)continue;
    for(const pz of [-GHW,GHW]){if(ball.y>GH+.1)continue;const dx=ball.x-gx,dz=ball.z-pz,d=hyp(dx,dz),r=BR+.07;
      if(d<r&&d>0){const nx=dx/d,nz=dz/d,vn=ball.vx*nx+ball.vz*nz;if(vn<0){ball.vx-=1.7*vn*nx;ball.vz-=1.7*vn*nz;AU.post();ball.shot=false}ball.x=gx+nx*r;ball.z=pz+nz*r}}
    if(Math.abs(ball.z)<GHW){const dx=ball.x-gx,dy=ball.y-GH,d=hyp(dx,dy),r=BR+.07;
      if(d<r&&d>0){const nx=dx/d,ny=dy/d,vn=ball.vx*nx+ball.vy*ny;if(vn<0){ball.vx-=1.7*vn*nx;ball.vy-=1.7*vn*ny;AU.post();ball.shot=false}ball.x=gx+nx*r;ball.y=GH+ny*r}}
  }
  // inside the net
  if(Math.abs(ball.x)>HL&&Math.abs(ball.z)<GHW+.3&&ball.y<GH+.3&&(S.phase==='goal'||S.phase==='replay'||Math.abs(ball.z)<GHW)){
    const s=Math.sign(ball.x);
    if(Math.abs(ball.x)>HL+1.9){ball.x=s*(HL+1.9);ball.vx*=-.15}
    if(Math.abs(ball.z)>GHW-.1){ball.z=Math.sign(ball.z)*(GHW-.1);ball.vz*=-.15}
    if(ball.y>GH-.1){ball.y=GH-.1;ball.vy*=-.2}
  }
}
function checkPickup(){
  if(ball.owner||S.phase!=='play')return;
  let best=null,bd=1e9;
  for(const p of players){
    if(p.cool>0||p.stun>0||p.slideT>0)continue;
    if(p.gk&&ball.shot&&ball.shotTeam!==p.team)continue;
    const hands=p.gk&&inOwnBox(p),r=hands?1.25:.8,ym=hands?2.5:p.recv?1.2:.95;
    const dx=ball.x-p.x,dz=ball.z-p.z,d2=dx*dx+dz*dz;
    if(d2<r*r&&ball.y<ym&&d2<bd){bd=d2;best=p}
  }
  if(best){
    const spd=hyp(ball.vx,ball.vy,ball.vz),lim=best.recv?32:best.gk?30:15+best.stats.drib*.06;
    if(spd>lim){if(best.team!==S.offTeam)clearOffside();ball.vx=ball.vx*-.25+rand(-3,3);ball.vz=ball.vz*-.25+rand(-3,3);ball.vy=Math.abs(ball.vy)*.3+1;S.lastTouch=best.team;best.cool=.35;ball.shot=false;AU.touch();if(S.lastKicker&&S.lastKicker.team!==best.team)toast('BLOCKED')}
    else gainPossession(best);
    return;
  }
  // headers
  if(ball.y>.95&&ball.y<2.4){
    for(const p of players){if(p.cool>0||p.stun>0||p.gk)continue;if(hyp(ball.x-p.x,ball.z-p.z)>.95)continue;
      if(p.offside){callOffside(p);return}if(p.team!==S.offTeam)clearOffside();
      const s=SIDE[p.team],gx=HL*s;p.cool=.4;p.jumpT=.35;S.lastTouch=p.team;S.lastKicker=p;
      if(hyp(gx-p.x,p.z)<20&&(p.x*s)>20){const tz=rand(-3,3),dx=gx-ball.x,dz=tz-ball.z,d=hyp(dx,dz),sp=13+p.stats.shoot*.04,e=randn()*.12;const a=Math.atan2(dz,dx)+e;
        ball.vx=Math.cos(a)*sp;ball.vz=Math.sin(a)*sp;ball.vy=(rand(.3,2)-ball.y+.5*G*(d/sp)**2)/(d/sp);ball.curl=0;ball.shot=true;ball.shotTeam=p.team;S.shotId++;S.stats.shots[p.team]++;toast('HEADER')}
      else{const dx=s,dz=-ball.z*.02+rand(-.6,.6),l=hyp(dx,dz);ball.vx=dx/l*13;ball.vz=dz/l*13;ball.vy=5;ball.shot=false}
      ball.passTo=null;players.forEach(q=>q.recv=false);AU.touch();break}
  }
}
function checkRules(){
  if(S.phase!=='play')return;
  if(Math.abs(ball.x)>HL+BR){
    const end=Math.sign(ball.x);
    if(Math.abs(ball.z)<GHW&&ball.y<GH){goalScored(SIDE[0]===end?0:1);return}
    const def=SIDE[0]===-end?0:1;
    if(S.lastTouch===def)ballDead('corner',1-def,end*(HL-.4),Math.sign(ball.z||1)*(HW-.4));
    else ballDead('goalkick',def,end*(HL-5.5),Math.sign(ball.z||1)*4.5);
    return;
  }
  if(Math.abs(ball.z)>HW+BR)ballDead('throw',1-S.lastTouch,clamp(ball.x,-HL+1,HL-1),Math.sign(ball.z)*(HW-.1));
}
let aiAcc=0;
function step(dt){
  if(S.phase==='cut')return;
  if(S.phase==='play'||S.phase==='restart'){
    S.clock+=dt;if(S.clock>=S.halfLen){endHalf();return}
    if(ball.owner)S.stats.poss[ball.owner.team]+=dt;
  }
  if(S.phase==='dead'){S.phaseT+=dt;if(S.phaseT>(S.pending.type==='throw'?.75:1.1)){const P=S.pending;cutTo(()=>restart(P.type,P.team,P.x,P.z));if(S.phase==='cut')return}}
  if(S.phase==='restart'){const rs=S.rs;rs.t+=dt;
    if(!rs.ready&&rs.t>.35)rs.ready=true;
    if(rs.ready&&!rs.kick){
      if(rs.team===S.user){userAim(rs,dt);if(rs.t>10)aiSetPiece(rs)}
      else if(rs.t>(AIDELAY[rs.type]||1.6)+S.diff.react*.5)aiSetPiece(rs);
    }
    if(rs.kick)rs.kickT+=dt;
  }
  aiAcc+=dt;if(aiAcc>=.1){aiAcc-=.1;aiTick()}
  if(S.ctrl&&S.phase!=='goal')processQueue();
  stepPlayers(dt);
  stepOfficials(dt);stepAdvantage(dt);
  if(S.phase==='restart'&&(S.rs.fire||(S.rs.kick&&S.rs.type==='throw'&&S.rs.kickT>.3)))execSetPiece();
  stepBall(dt);
  resolveSaves();
  checkPickup();
  checkRules();
  if(S.phase==='play'||S.phase==='restart'||(S.phase==='goal'&&S.phaseT<1.3))record(dt);
}
