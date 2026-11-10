/* ===== Restarts, goals, halves ===== */
/* ---------- Set pieces: dead ball → cut → real shape → aim → run-up → strike ---------- */
const SP_NAME={throw:'THROW-IN',corner:'CORNER',goalkick:'GOAL KICK',freekick:'FREE KICK',penalty:'PENALTY'};
const RUNUP={kickoff:.9,goalkick:3.2,corner:2.2,freekick:2.6,penalty:2.8};
const AIDELAY={kickoff:1,throw:.8,goalkick:1.4,corner:1.7,freekick:1.9,penalty:2.2};
let cutting=false;
function ballDead(type,team,x,z,label){
  if(S.phase!=='play')return;
  S.phase='dead';S.phaseT=0;S.pending={type,team,x,z};
  ball.shot=false;ball.passTo=null;players.forEach(p=>{p.recv=false;p.save=null});
  AU.whistle(type==='penalty'?2:1,.22);
  if(type==='penalty'){banner('PENALTY!',S.teams[team].name);AU.ooh()}else toast(label||SP_NAME[type]);
}
function cutTo(fn){
  if(cutting)return;
  if(S.instantCut){fn();cam.init=false;return}
  cutting=true;S.phase='cut';const f=$('#fade');f.classList.add('on');
  setTimeout(()=>{fn();cam.init=false;cutting=false;requestAnimationFrame(()=>f.classList.remove('on'))},190);
}
function setW(p,x,z){p.x=clamp(x,-HL-1.5,HL+1.5);p.z=clamp(z,-HW-1.2,HW+1.2);p.vx=p.vz=0;p.sx=p.x;p.sz=p.z}
const ownW=(p,ox,oz)=>setW(p,ox*SIDE[p.team],oz);
const jit=()=>rand(-1.2,1.2);
function markGoalSide(m,a){const gx=-HL*SIDE[m.team],dx=gx-a.x,dz=-a.z,d=hyp(dx,dz)||1;setW(m,a.x+dx/d*.9,a.z+dz/d*.9+rand(-.3,.3))}
// attackers crowd the box, defenders mark goal-side, a near-post man for corners
function boxSetup(T,c,taker,cornerish){
  const e=SIDE[T],O=1-T,spots=[[5,3.2],[7,-.5],[6.5,-4.2],[11,1.5],[13,-6],[18,4]];
  const atk=[9,2,3,8,10,7,5].map(i=>R(T,i)).filter(p=>p&&p!==taker).slice(0,6);
  atk.forEach((p,k)=>setW(p,e*(HL-spots[k][0]-rand(0,.8)),c*spots[k][1]+rand(-.6,.6)));
  const used=new Set();
  setW(TP[O][0],e*(HL-.7),c*.6);
  const order=[2,3,6,1,4,5,7,8,10].map(i=>R(O,i)).filter(p=>p&&!p.wall);
  atk.forEach((a,k)=>{const m=order[k];if(m){markGoalSide(m,a);used.add(m)}});
  if(cornerish){const np=order.find(p=>!used.has(p));if(np){setW(np,e*(HL-.4),c*3.4);used.add(np)}}
  TP[O].filter(p=>!p.gk&&!p.wall&&!used.has(p)).forEach((p,k)=>{if(p.i===9)setW(p,-e*3,rand(-8,8));else setW(p,e*(HL-21-k*2),(k%2?1:-1)*rand(3,12))});
  TP[T].filter(p=>!p.gk&&p!==taker&&!atk.includes(p)).forEach((p,k)=>{if(p.i===6)setW(p,e*(HL-25),c*5);else setW(p,e*rand(-4,4),(k%2?1:-1)*rand(6,16))});
}
function buildWall(rs,T){
  const e=SIDE[T],O=1-T,gx=e*HL,sz=Math.sign(ball.z||1);
  const dx=gx-ball.x,dz=sz*1.4-ball.z,d=hyp(dx,dz),ux=dx/d,uz=dz/d;
  const n=d<20?5:d<26?4:3,cx=ball.x+ux*9.15,cz=ball.z+uz*9.15;
  const wall=TP[O].filter(p=>!p.gk).sort((a,b)=>hyp(a.x-cx,a.z-cz)-hyp(b.x-cx,b.z-cz)).slice(0,n);
  wall.forEach((p,k)=>{const o=(k-(n-1)/2)*.62;setW(p,cx-uz*o,cz+ux*o);p.wall=true});
  rs.wall=wall;
}
const SETUP={
  kickoff(rs,T){
    for(const p of players){let ox=p.gk?-HL+1.2:Math.min(p.hx*.85-2,-1.5),oz=p.hz*.9;if(p.team!==T&&!p.gk&&hyp(ox,oz)<10)ox=-10.2;ownW(p,ox,oz)}
    ball.x=0;ball.z=0;rs.taker=RA(T,9);rs.mate=RA(T,6);if(rs.mate===rs.taker)rs.mate=TP[T].find(q=>!q.gk&&q!==rs.taker);ownW(rs.mate,-7,2);
  },
  goalkick(rs,T){
    // modern build-up shape: centre-backs split wide, full-backs high; opponents outside the box
    const A=[0,[-28,-30],[-41,-17],[-41,17],[-28,30],[-15,-14],[-29,0],[-15,14],[-2,-26],[3,0],[-2,26]];
    const D=[0,[-8,-26],[-12,-9],[-12,9],[-8,26],[12,-14],[3,0],[12,14],[26,-22],[31,0],[26,22]];
    for(let i=1;i<11;i++){const a=R(T,i),d=R(1-T,i);if(a)ownW(a,A[i][0]+jit(),A[i][1]+jit());if(d)ownW(d,D[i][0]+jit(),D[i][1]+jit())}
    rs.taker=TP[T][0];
  },
  throw(rs,T,x,z){
    const e=SIDE[T],c=Math.sign(z||1);ball.x=x;ball.z=c*(HW+.15);
    const pool=TP[T].filter(p=>!p.gk).sort((a,b)=>hyp(a.x-x,a.z-z)-hyp(b.x-x,b.z-z));
    const tk=rs.taker=pool[0];setW(tk,x,c*(HW+.12));tk.face=Math.atan2(-c,0);
    rs.opts=pool.slice(1,3);
    rs.opts.forEach((p,k)=>setW(p,clamp(x+(k?-rand(4,7):rand(6,10))*e,-HL+2,HL-2),c*(HW-rand(4,8))));
    const taken=new Set();
    rs.opts.forEach(o=>{let m=null,md=1e9;for(const q of TP[1-T]){if(q.gk||taken.has(q))continue;const d=hyp(q.x-o.x,q.z-o.z);if(d<md){md=d;m=q}}if(m){taken.add(m);markGoalSide(m,o)}});
  },
  corner(rs,T,x,z){
    const e=SIDE[T],c=Math.sign(z||1);ball.x=e*(HL-.35);ball.z=c*(HW-.35);
    rs.taker=RA(T,c>0?10:8);
    boxSetup(T,c,rs.taker,true);
  },
  freekick(rs,T,x,z){
    const e=SIDE[T],xo=x*e,dG=hyp(HL-xo,z);ball.x=x;ball.z=z;
    rs.inRange=dG<32&&xo>8&&Math.abs(z)<26;rs.cross=!rs.inRange&&xo>14;
    const near=TP[T].filter(p=>!p.gk).sort((a,b)=>hyp(a.x-x,a.z-z)-hyp(b.x-x,b.z-z));
    rs.taker=rs.inRange?near.slice(0,5).sort((a,b)=>b.stats.shoot-a.stats.shoot)[0]:near[0];
    if(rs.inRange)buildWall(rs,T);
    if(rs.inRange||rs.cross)boxSetup(T,Math.sign(z||1),rs.taker,false);
    if(rs.inRange)setW(TP[1-T][0],e*(HL-.6),-Math.sign(z||1)*.7);
  },
  penalty(rs,T){
    const e=SIDE[T];ball.x=e*(HL-11);ball.z=0;
    rs.taker=TP[T].filter(p=>!p.gk).sort((a,b)=>b.stats.shoot-a.stats.shoot)[0];
    const others=players.filter(p=>!p.gk&&p!==rs.taker);
    others.forEach((p,k)=>setW(p,e*(HL-21.5-(k%2)*1.6-rand(0,.5)),-17+k*(34/(others.length-1))+rand(-.3,.3)));
    setW(TP[1-T][0],e*(HL-.15),0);setW(TP[T][0],-e*(HL-2),0);
  },
};
function defaultAim(rs){
  const T=rs.team,e=SIDE[T];let ax,az;
  switch(rs.type){
    case 'kickoff':ax=rs.mate.x;az=rs.mate.z;break;
    case 'throw':ax=rs.opts[0].x;az=rs.opts[0].z;break;
    case 'goalkick':{const f=RA(T,9);ax=f.x;az=f.z;break}
    case 'corner':ax=e*(HL-8);az=Math.sign(ball.z)*.5;break;
    case 'penalty':ax=e*HL;az=0;break;
    default:if(rs.inRange){ax=e*HL;az=-Math.sign(ball.z||1)*1.8}else if(rs.cross){ax=e*(HL-9);az=0}
      else{const t=bestTarget(rs.taker,null,false,45);ax=t?t.x:ball.x+e*15;az=t?t.z:ball.z}
  }
  rs.aimX=ax;rs.aimZ=az;
}
function restart(type,team,x,z){
  S.phase='restart';S.timeScale=1;S.autoT=0;IN.queue.length=0;
  for(const p of ALL)if(p.pendingOff)sendOff(p);
  applySubQueue();for(const t of [0,1])if(t!==S.user)aiSubs(t);clearOffside();S.adv=null;
  const rs=S.rs={type,team,x,z,t:0,ready:false,kick:null,kickT:0,fire:false,taker:null,mate:null,aimX:0,aimZ:0,wall:[],opts:[],inRange:false,cross:false};
  ball.owner=null;ball.vx=ball.vy=ball.vz=0;ball.curl=0;ball.dip=0;ball.shot=false;ball.passTo=null;ball.x=x;ball.z=z;ball.y=BR;
  players.forEach(p=>{p.recv=false;p.mustPass=false;p.holdT=0;p.hands=false;p.slideT=0;p.diveT=0;p.save=null;p.stun=0;p.celebT=0;p.kickT=0;p.throwT=0;p.wall=false;p.cool=0;p.jumpT=0;p.act=null;p.windA=0});
  for(const p of players){const[hx,hz]=homePos(p,p.team===team);setW(p,hx,hz)}
  for(const t of [0,1])ownW(TP[t][0],-HL+1,0);
  SETUP[type](rs,team,x,z);
  const tk=rs.taker;
  if(type!=='throw'&&type!=='penalty'){for(const p of TP[1-team]){if(p.gk||p.wall)continue;const dx=p.x-ball.x,dz=p.z-ball.z,d=hyp(dx,dz);
    if(d<9.15){const ux=d>.01?dx/d:-SIDE[team],uz=d>.01?dz/d:0;setW(p,ball.x+ux*9.15,ball.z+uz*9.15)}}}
  defaultAim(rs);
  if(type!=='throw'){const dx=rs.aimX-ball.x,dz=rs.aimZ-ball.z,d=hyp(dx,dz)||1,rd=RUNUP[type]||2.4,lat=type==='penalty'||type==='freekick'?.9:0;
    setW(tk,ball.x-dx/d*rd+dz/d*lat,ball.z-dz/d*rd-dx/d*lat);tk.face=Math.atan2(dz,dx)}
  for(const p of players){if(p!==tk)p.face=Math.atan2(ball.z-p.z,ball.x-p.x);p.tx=p.sx;p.tz=p.sz}
  if(team===S.user)setCtrl(tk);
  if(S.user>=0&&(!S.ctrl||S.ctrl.off))setCtrl(TP[S.user].filter(q=>!q.gk).sort((a,b)=>hyp(a.x-ball.x,a.z-ball.z)-hyp(b.x-ball.x,b.z-ball.z))[0]);
  if(type==='kickoff')AU.whistle(1,.5);
  setHint();lastMode=null;for(const p of ALL)p.mesh.snap=true;
}
function setHint(){
  const rs=S.rs;let t='';
  if(S.user>=0&&rs){
    if(rs.team===S.user)t={throw:'Stick: aim the throw · any button: throw it',corner:'Stick: move the target · PASS: curl it in · THRU: driven',
      goalkick:'Stick: aim · PASS: long ball · THRU: play it short',penalty:'Stick: pick your corner · hold SHOOT for power',kickoff:'PASS to kick off',
      freekick:rs.inRange?'Stick: aim · hold SHOOT to bend it over the wall · PASS: play it short':'Stick: aim · PASS: lofted · THRU: driven'}[rs.type];
    else if(rs.type==='penalty')t='Your keeper: hold the stick left or right to pick a dive';
  }
  S.hintText=t;$('#hint').textContent=t;
}
function takerMove(p,dt){
  const rs=S.rs;
  if(rs.type==='throw'){p.vx=p.vz=0;p.faceT=Math.atan2(rs.aimZ-p.z,rs.aimX-p.x);return}
  const ax=rs.kick?rs.kick.ax:rs.aimX,az=rs.kick?rs.kick.az:rs.aimZ,dx=ax-ball.x,dz=az-ball.z,d=hyp(dx,dz)||1,ux=dx/d,uz=dz/d;
  p.faceT=Math.atan2(uz,ux);
  if(rs.kick){const px=ball.x-ux*.42,pz=ball.z-uz*.42,ddx=px-p.x,ddz=pz-p.z,dd=hyp(ddx,ddz);
    if(dd<.3||rs.kickT>1.6){rs.fire=true;p.vx*=.5;p.vz*=.5}else{const v=Math.min(5.6,dd/dt);p.vx=ddx/dd*v;p.vz=ddz/dd*v}}
  else{const rd=RUNUP[rs.type]||2.4,lat=rs.type==='penalty'||rs.type==='freekick'?.9:0;moveToward(p,dt,ball.x-ux*rd+uz*lat,ball.z-uz*rd-ux*lat,3.2,12)}
}
function userAim(rs,dt){
  const[ix,iz,m]=worldInput(),e=SIDE[rs.team];
  if(m>0){const sp=rs.type==='penalty'?5:rs.type==='throw'?14:20;rs.aimX+=ix*m*sp*dt;rs.aimZ+=iz*m*sp*dt}
  if(rs.type==='penalty'){rs.aimX=e*HL;rs.aimZ=clamp(rs.aimZ,-3.4,3.4);return}
  rs.aimX=clamp(rs.aimX,-HL+.5,HL-.5);rs.aimZ=clamp(rs.aimZ,-HW+.5,HW-.5);
  if(rs.type==='throw'){const dx=rs.aimX-ball.x,dz=rs.aimZ-ball.z,d=hyp(dx,dz);if(d>24){rs.aimX=ball.x+dx/d*24;rs.aimZ=ball.z+dz/d*24}}
}
function shotKick(rs,tz,power){const e=SIDE[rs.team];return{mode:'shot',ax:e*HL,az:tz,power,opts:{pen:rs.type==='penalty',fk:rs.type==='freekick',curlSign:(Math.sign(tz-ball.z)||1)*e}}}
function userKickFor(rs,btn,pw){
  const e=SIDE[rs.team],ax=rs.aimX,az=rs.aimZ,d=hyp(ax-ball.x,az-ball.z);
  const shotOK=rs.type==='penalty'||rs.inRange,nearGoal=Math.abs(ax-e*HL)<4&&Math.abs(az)<6;
  if(rs.type==='throw')return{mode:'throw',ax,az};
  if(rs.type==='kickoff')return{mode:'ground',ax,az};
  if(shotOK&&(btn==='shoot'||nearGoal))return shotKick(rs,clamp(az,-3.3,3.3),pw);
  if(btn==='through')return{mode:rs.type==='corner'||d>24?'driven':'ground',ax,az,opts:{ty:rs.type==='corner'?1.5:.25}};
  return{mode:d<14&&rs.type!=='corner'?'ground':'lob',ax,az,opts:rs.type==='corner'||rs.cross?{curl:Math.sign(ball.z||1)*e*5,ty:1.7}:{}};
}
function userSetPiece(a){
  const rs=S.rs;if(!rs||rs.kick||!rs.ready||a.b==='skill')return;
  rs.kick=userKickFor(rs,a.b,a.held<.18?.62:clamp(a.held/.9,.2,1.18));$('#hint').hidden=true;
}
function aiSetPiece(rs){
  const T=rs.team,e=SIDE[T],tk=rs.taker;let k;
  switch(rs.type){
    case 'kickoff':k={mode:'ground',ax:rs.mate.x,az:rs.mate.z};break;
    case 'throw':{const t=bestTarget(tk,null,false,22)||rs.opts[0];k={mode:'throw',ax:t.x+t.vx*.3,az:t.z+t.vz*.3};break}
    case 'goalkick':{if(Math.random()<.55){const f=RA(T,[8,9,10][(Math.random()*3)|0]);k={mode:'lob',ax:f.x+e*3,az:f.z}}
      else{const cb=RA(T,Math.random()<.5?2:3);k={mode:'ground',ax:cb.x,az:cb.z}}break}
    case 'penalty':{const r=Math.random(),tz=(r<.14?rand(-.6,.6):(r<.57?-1:1)*rand(1.7,3.1))+randn()*.35*aiErr(tk);k=shotKick(rs,tz,rand(.45,.88));break}
    default:{
      if(rs.inRange&&Math.random()<.6){k=shotKick(rs,-Math.sign(ball.z||1)*rand(1.2,3.0)+randn()*.9*aiErr(tk),rand(.5,.95));break}
      if(rs.type==='corner'||rs.cross){const box=TP[T].filter(p=>p!==tk&&Math.abs(p.x-e*HL)<15&&Math.abs(p.z)<13),t=box[(Math.random()*box.length)|0],c=Math.sign(ball.z||1);
        k=t?{mode:Math.random()<.75?'lob':'driven',ax:t.x+rand(-.8,.8),az:t.z+rand(-.8,.8),opts:{curl:c*e*(Math.random()<.7?5:-4),ty:1.6}}:{mode:'lob',ax:e*(HL-8),az:0,opts:{ty:1.6}};break}
      const t=bestTarget(tk,null,false,45);k=t?{mode:hyp(t.x-ball.x,t.z-ball.z)>24?'lob':'ground',ax:t.x,az:t.z}:{mode:'ground',ax:ball.x+e*14,az:ball.z};
    }
  }
  if(!k.opts)k.opts={};rs.aimX=k.ax;rs.aimZ=k.az;rs.kick=k;
}
// one solver for every dead-ball strike, also used to draw the aim path
function solveKick(k,x0,y0,z0){
  const o=k.opts||{},dx=k.ax-x0,dz=k.az-z0,d=Math.max(.5,hyp(dx,dz)),ux=dx/d,uz=dz/d;
  const aimAt=off=>{const ax2=k.ax+uz*off,az2=k.az-ux*off,d2=hyp(ax2-x0,az2-z0);return[(ax2-x0)/d2,(az2-z0)/d2,d2]};
  let vh,t,vy,curl=0,dip=0,u=[ux,uz,d];
  if(k.mode==='ground'){const v0=clamp(Math.sqrt(30+2*ROLL*d),7,28);return{vx:ux*v0,vy:0,vz:uz*v0,curl:0,dip:0,y0}}
  if(k.mode==='throw'){vh=clamp(8+d*.3,9,16);t=d/vh;vy=(.5-y0+.5*G*t*t)/t;return{vx:ux*vh,vy,vz:uz*vh,curl:0,dip:0,y0}}
  if(k.mode==='shot'){const pw=Math.min(k.power,1),over=Math.max(0,k.power-1);vh=o.pen?19+pw*9:19+pw*7;
    const ty=(o.pen?.35+pw*1.6:1.25+pw*.95)+over*6;
    if(o.fk){dip=6;curl=o.curlSign*7.5;u=aimAt(.5*curl*(d/vh)**2)}
    t=u[2]/vh;vy=(ty-y0+.5*(G+dip)*t*t)/t;return{vx:u[0]*vh,vy,vz:u[1]*vh,curl,dip,y0}}
  vh=k.mode==='driven'?clamp(15+d*.33,17,29):clamp(9+d*.3,10,25);curl=o.curl||0;
  if(curl)u=aimAt(.5*curl*(d/vh)**2);t=u[2]/vh;
  vy=((o.ty!=null?o.ty:.8)-y0+.5*G*t*t)/t;return{vx:u[0]*vh,vy,vz:u[1]*vh,curl,dip:0,y0};
}
function execSetPiece(){
  const rs=S.rs,k=rs.kick,tk=rs.taker,T=rs.team,y0=k.mode==='throw'?2.5:BR;
  const v=solveKick(k,ball.x,y0,ball.z),sk=k.mode==='shot'?tk.stats.shoot:tk.stats.pass;
  const err=(1-sk/100)*(k.mode==='shot'?.07:.05)*aiErr(tk)*randn(),c=Math.cos(err),s=Math.sin(err);
  ball.y=y0;tk.kickKind=k.mode==='shot'?1:k.mode==='ground'?0:2;
  kick(tk,v.vx*c-v.vz*s,v.vy*(1+randn()*.03),v.vx*s+v.vz*c,v.curl,k.mode==='throw');
  ball.dip=v.dip;
  if(k.mode==='throw')tk.throwT=.35;
  rs.wall.forEach(p=>{p.jumpT=.42;p.wall=false});
  if(k.mode==='shot'){ball.shot=true;ball.shotTeam=T;S.shotId++;S.stats.shots[T]++;if(rs.type==='penalty')penaltyKeeper(T,k.az,v)}
  else{let r=null,rd=8;for(const p of TP[T]){if(p===tk)continue;const d=hyp(p.x-k.ax,p.z-k.az);if(d<rd){rd=d;r=p}}
    if(r){ball.passTo=r;r.recv=true;if(T===S.user)setCtrl(r)}}
  $('#hint').hidden=true;
}
function penaltyKeeper(T,tz,v){
  const k=TP[1-T][0];k.shotSeen=S.shotId;
  let g;if(1-T===S.user){const[ix,iz,m]=worldInput();g=m>.35?Math.sign(iz):0}else{const r=Math.random();g=r<.44?-1:r<.88?1:0}
  const side=Math.abs(tz)<1.1?0:Math.sign(tz),spd=hyp(v.vx,v.vy,v.vz),skill=1-T===S.user||S.demo?.76:S.diff.gk;
  const p=g===side?clamp(.6-(spd-24)/14+skill*.1-(Math.abs(tz)>2.7?.25:0),.1,.8):0;
  const ok=Math.random()<p;
  k.save={ok,tz:ok?tz:g===side&&g?g*Math.max(.3,Math.abs(tz)-rand(1.1,1.6)):g*2.3,zk:tz,yk:1.2,dir:g||Math.sign(tz)||1,spd};
  if(g){k.diveT=1.1;k.diveDir=g}
  if(!ok)k.cool=1.2;
}
function keeperDistribute(k){
  const t=bestTarget(k,null,false,60);
  if(!t){passBall(k,null,'lob');return}
  const ax=t.x+t.vx*.6,az=t.z+t.vz*.6,d=hyp(ax-k.x,az-k.z);
  if(!k.hands){passBall(k,null,d>28?'lob':'ground');return}
  const thr=d<30,kk=thr?{mode:'throw',ax,az}:{mode:'lob',ax,az,opts:{}},y0=thr?1.9:.7,v=solveKick(kk,ball.x,y0,ball.z);
  ball.y=y0;kick(k,v.vx,v.vy,v.vz,0,thr);if(thr)k.throwT=.35;
  ball.passTo=t;t.recv=true;if(k.team===S.user)setCtrl(t);
}
// aim reticle + dotted flight path for the human's set pieces
const DOTS=40,dotPos=new Float32Array(DOTS*3);
const dotTex=canvasTex(32,32,g=>{g.fillStyle='#fff';g.beginPath();g.arc(16,16,13,0,7);g.fill()});
const aimDots=new THREE.Points(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(dotPos,3)),
  new THREE.PointsMaterial({map:dotTex,color:0xffffff,size:.34,transparent:true,opacity:.9,depthWrite:false,alphaTest:.3}));
aimDots.frustumCulled=false;aimDots.visible=false;scene.add(aimDots);
const aimRing=new THREE.Mesh(new THREE.RingGeometry(.55,.78,32).rotateX(-Math.PI/2),new THREE.MeshBasicMaterial({color:0xffd23f,transparent:true,opacity:.95,depthWrite:false}));
aimRing.visible=false;scene.add(aimRing);
function drawPath(v,mode){
  let x=ball.x,y=v.y0,z=ball.z,vx=v.vx,vy=v.vy,vz=v.vz,n=0;const dt=1/60;
  for(let i=0;i<300&&n<DOTS;i++){
    const vh=hyp(vx,vz);
    if(y>BR+.001||vy>0){vy-=(G+v.dip)*dt;const sp=hyp(vx,vy,vz),dr=1-.0022*sp*dt;vx*=dr;vy*=dr;vz*=dr;if(vh>1&&v.curl){const cx=-vz/vh*v.curl*dt,cz=vx/vh*v.curl*dt;vx+=cx;vz+=cz}}
    else if(vh>0){const nv=Math.max(0,vh-ROLL*dt);vx*=nv/vh;vz*=nv/vh;if(nv<.6)break}
    x+=vx*dt;y+=vy*dt;z+=vz*dt;
    if(y<BR){y=BR;if(mode!=='ground'){dotPos[n*3]=x;dotPos[n*3+1]=.08;dotPos[n*3+2]=z;n++;break}vy=0}
    if(i%(mode==='ground'?4:3)===0){dotPos[n*3]=x;dotPos[n*3+1]=Math.max(y,.08);dotPos[n*3+2]=z;n++}
    if(Math.abs(x)>HL+1)break;
  }
  aimDots.geometry.setDrawRange(0,n);aimDots.geometry.attributes.position.needsUpdate=true;
}
function goalScored(team){
  S.score[team]++;S.phase='goal';S.phaseT=0;S.timeScale=.4;S.goalTeam=team;S.goalEnd=Math.sign(ball.x);
  const k=S.lastKicker;const own=!k||k.team!==team;
  if(k&&!own)k.celebT=4;
  banner('GOAL!',own?'Own goal':k.name+'  ·  '+S.teams[team].code);
  AU.roar();crowdJump=3;if(team===S.user)buzz([40,40,90]);
  ball.shot=false;players.forEach(p=>{p.save=null});
  updateBoard();
}
function endHalf(){
  if(S.half===1){S.phase='half';S.phaseT=0;AU.whistle(2,.35);banner('HALF TIME',S.teams[0].code+' '+S.score[0]+' – '+S.score[1]+' '+S.teams[1].code)}
  else{S.phase='full';AU.whistle(3,.4);if(S.demo){setTimeout(startDemo,600);return}showFullTime()}
}
