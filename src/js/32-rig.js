/* ===== Animation rig =====
   No canned clips: each frame the pose is worked out from what the player is really doing
   (speed, stride phase, direction of travel, kick wind-up, dive, slide…) and blended smoothly. */
const CH={rootY:0,rootP:1,rootR:2,rootYw:3,spP:4,spYw:5,spR:6,hdP:7,hdYw:8,
  aLp:9,aLa:10,aLt:11,eL:12,aRp:13,aRa:14,aRt:15,eR:16,
  hLf:17,hLa:18,hLt:19,kL:20,nL:21,hRf:22,hRa:23,hRt:24,kR:25,nR:26,rootX:27,rootZ:28,gnd:29};
const NCH=30;
// arm channels: pitch (forward +), abduction (out +), twist (outward +), elbow.  leg channels: hip flex (forward +), abduction, twist, knee, foot pitch (toes down +, world)
const bump=(x,w)=>{x=Math.atan2(Math.sin(x),Math.cos(x));const u=x/w;return Math.abs(u)<1?.5*(1+Math.cos(u*PI)):0};
const _T=new Float32Array(NCH);
// stride rate: slower, shorter steps when walking; long fast strides at a sprint
const strideRate=v=>v*PI/(CFG.gait.stepLen[0]+CFG.gait.stepLen[1]*Math.min(v,8.5));

function computePose(p,ch,time){
  const T=_T;T.fill(0);T[CH.gnd]=1;
  const Gt=CFG.gait,v=p.spd||0,mv=clamp(v/1.1,0,1),s=clamp((v-1.5)/6.3,0,1),L=a=>lerp(a[0],a[1],s);
  const f=v>.3?(p.vf??1):1,l=v>.3?(p.vl??0):0,af=Math.abs(f),ph=(p.phase||0)*(f<-.25?-1:1),sn=Math.sin(ph);
  const footLocal=(o,loc)=>{T[o+4]=T[CH.rootP]-T[o]+T[o+3]+loc};

  // --- legs: one stride = swing forward with the knee folding, plant, push off ---
  const A=L(Gt.hipSwing)*mv*af,off=L(Gt.hipLean)*mv*f,Ksw=L(Gt.kneeSwing)*mv*Math.max(af,.3),Kst=L(Gt.kneeStance)*mv,toe=L(Gt.toeOff)*mv*af;
  const leg=(phi,o)=>{T[o]=off+A*Math.sin(phi);T[o+3]=.08*mv+Ksw*bump(phi-1.92*PI,.78*PI)+Kst*bump(phi-.98*PI,.42*PI);
    T[o+4]=toe*bump(phi-1.42*PI,.34*PI)-.22*(1-s)*mv*af*bump(phi-.55*PI,.22*PI)};
  leg(ph,CH.hLf);leg(ph+PI,CH.hRf);
  // --- arms swing against the legs, elbows fold as the pace rises ---
  const Aa=L(Gt.armSwing)*mv*af,el=.16+L(Gt.elbow)*mv;
  T[CH.aLp]=-Aa*sn+.08*s;T[CH.aRp]=Aa*sn+.08*s;T[CH.eL]=el-.3*s*mv*sn;T[CH.eR]=el+.3*s*mv*sn;
  T[CH.aLa]=T[CH.aRa]=.07+.08*s;T[CH.aLt]=T[CH.aRt]=-.28*s*mv;
  // --- trunk: lean into the run, hips and shoulders counter-rotate ---
  T[CH.rootP]=L(Gt.bodyLean)*mv*f;T[CH.rootYw]=-.13*sn*mv*af*(.5+.5*s);T[CH.spYw]=.30*sn*mv*af*(.4+.6*s);T[CH.rootR]=.035*Math.cos(ph)*mv*af;
  // --- side-stepping (jockeying defenders, keepers, assistant referees) ---
  const sd=Math.abs(l)*mv;
  if(sd>.05){const sp=Math.sin(p.phase||0)*Math.sign(l);
    T[CH.hLa]+=sd*.30*(.5+.5*sp);T[CH.hRa]+=sd*.30*(.5-.5*sp);T[CH.kL]+=sd*(.30+.25*Math.max(0,-sp));T[CH.kR]+=sd*(.30+.25*Math.max(0,sp));
    T[CH.hLf]+=sd*.28;T[CH.hRf]+=sd*.28;T[CH.rootP]+=sd*.10;T[CH.aLa]+=sd*.2;T[CH.aRa]+=sd*.2;T[CH.eL]+=sd*.5;T[CH.eR]+=sd*.5}
  // --- standing: breathing, soft knees, weight shifting ---
  const idle=1-mv,br=Math.sin(time*1.7+ch.seed);
  T[CH.spP]+=idle*(.035+.012*br);T[CH.hdP]+=idle*.04;T[CH.eL]+=idle*.10;T[CH.eR]+=idle*.10;T[CH.kL]+=idle*.06;T[CH.kR]+=idle*.06;T[CH.hLf]+=idle*.03;T[CH.hRf]+=idle*.03;
  T[CH.rootR]+=idle*.02*Math.sin(time*.63+ch.seed*2);T[CH.hLa]+=idle*.035;T[CH.hRa]+=idle*.035;
  // --- ready stance (defender facing the ball, keeper set for a shot) ---
  const c=p.ready||0;
  if(c>0){const ab=(p.wide?1.0:.30)*c;T[CH.hLf]+=.40*c;T[CH.hRf]+=.40*c;T[CH.kL]+=.72*c;T[CH.kR]+=.72*c;T[CH.rootP]+=.15*c;T[CH.hLa]+=.13*c;T[CH.hRa]+=.13*c;
    T[CH.aLa]+=ab;T[CH.aRa]+=ab;T[CH.eL]+=.7*c;T[CH.eR]+=.7*c;T[CH.aLp]+=.25*c;T[CH.aRp]+=.25*c}
  // --- head follows the ball ---
  T[CH.hdYw]=clamp(-(p.lookAt||0),-1,1)*(1-.5*s)-(T[CH.rootYw]+T[CH.spYw]);if(p.hasBall)T[CH.hdP]+=.16;

  // --- striking the ball: backswing, contact exactly when the ball leaves, follow-through ---
  const wind=p.windA||0,kt=p.kickT||0;
  if(wind>0||kt>0){
    const Rk=(p.foot??-1)<0,K=Rk?CH.hRf:CH.hLf,Pl=Rk?CH.hLf:CH.hRf,sg=Rk?-1:1,kind=p.kickKind||0,amp=kind===1?1:kind===2?.85:.62,F=CFG.kick.follow;
    const contact=Math.asin(clamp(((p.ballD??.6)/ch.scale-.17)/.84,.12,.86));   // reach decided by where the ball actually is
    let hip,knee,tor;
    if(kt<=0){const b=smooth(0,.5,wind),fw=smooth(.5,1,wind);hip=lerp(-.85*amp*b,contact,fw);knee=lerp(1.75*amp*b,.28,fw);tor=-b*(1-fw)}
    else{const q=1-kt/F,sw=Math.sin(Math.min(1,q*1.7)*PI/2),rl=smooth(.55,1,q);hip=(contact+(1.3*amp-contact)*sw)*(1-.7*rl);knee=.28-.14*sw+.6*rl;tor=sw*(1-.6*rl)}
    const w=kt>0?1-smooth(.6,1,1-kt/F):1,set=(i,x)=>{T[i]=lerp(T[i],x,w)};
    set(K,hip);set(K+3,knee);set(K+1,-.09);set(K+2,kind===0?.8:.12);set(K+4,kind===0?.05:.5);
    set(Pl,.10+.12*amp);set(Pl+3,.30+.18*amp);set(Pl+1,.06);set(Pl+4,0);
    const bs=Math.max(0,-tor),ft=Math.max(0,tor),op=Rk?CH.aLp:CH.aRp,sm=Rk?CH.aRp:CH.aLp;
    set(CH.rootP,.05-.12*amp*bs+.20*amp*ft);set(CH.rootYw,-sg*.28*amp*tor);set(CH.spYw,sg*.38*amp*tor);
    set(op,.35*amp*bs-.25*amp*ft);set(op+1,.25+.95*amp*bs+.45*amp*ft);set(op+3,.35);
    set(sm,-.65*amp*(bs*.8+ft*.6));set(sm+1,.30+.3*amp);set(sm+3,.5);
  }
  // --- standing tackle: a lunge with the leading leg ---
  if((p.tackleT||0)>0&&!(p.slideT>0)){const k=Math.sin(PI*clamp(1-p.tackleT/.4,0,1));
    T[CH.hRf]=lerp(T[CH.hRf],.95,k);T[CH.kR]=lerp(T[CH.kR],.12,k);T[CH.hLf]=lerp(T[CH.hLf],-.45,k);T[CH.kL]=lerp(T[CH.kL],.4,k);T[CH.rootP]+=.25*k;T[CH.aLa]+=.6*k;T[CH.aRa]+=.6*k}
  // --- first touch: the receiving foot opens up ---
  if((p.trapT||0)>0){const h=Math.sin(PI*(1-p.trapT/.22)),o=(p.foot??-1)<0?CH.hRf:CH.hLf;T[o]+=.45*h;T[o+1]+=.22*h;T[o+2]+=.6*h;T[o+3]+=.3*h}
  // --- feint ---
  if((p.skillT||0)>0){const k=1-p.skillT/.4;T[CH.rootR]+=.26*Math.sin(2*PI*k);T[CH.hRa]+=.5*Math.sin(PI*k);T[CH.hRf]+=.45*Math.sin(2*PI*k);T[CH.aLa]+=.4;T[CH.aRa]+=.4}
  // --- knocked off balance ---
  const stn=clamp((p.stun||0)/.3,0,1);
  if(stn>0&&!(p.slideT>0)&&!(p.diveT>0)){T[CH.rootP]-=.22*stn;T[CH.aLa]+=.75*stn;T[CH.aRa]+=.75*stn;T[CH.aLp]-=.25*stn;T[CH.aRp]-=.25*stn;
    T[CH.kL]+=.4*stn;T[CH.kR]+=.4*stn;T[CH.hLf]+=.2*stn;T[CH.hRf]+=.2*stn;T[CH.hdP]-=.18*stn}
  // --- jump (headers, the wall) ---
  if((p.jumpT||0)>0){ch.jumpMax=Math.max(ch.jumpMax,p.jumpT);const k=1-p.jumpT/ch.jumpMax,h=Math.sin(PI*k),tuck=.55*(1-h)+.2*h;
    T[CH.rootY]+=.40*h;for(const o of [CH.hLf,CH.hRf]){T[o]=.25*tuck+.05;T[o+3]=tuck;T[o+4]=.55*h}
    if(!p.wall){T[CH.aLp]=T[CH.aRp]=.55*h;T[CH.aLa]=T[CH.aRa]=.2+.6*h;T[CH.eL]=T[CH.eR]=1.0;T[CH.spP]=lerp(-.18,.28,smooth(.4,.62,k))*h;T[CH.hdP]=lerp(-.2,.4,smooth(.42,.6,k))*h}
  }else ch.jumpMax=0;
  // --- keeper holding the ball, throw-ins, throws ---
  if(p.holdBall){T[CH.aLp]=T[CH.aRp]=.78;T[CH.eL]=T[CH.eR]=1.7;T[CH.aLa]=T[CH.aRa]=-.02;T[CH.aLt]=T[CH.aRt]=-.55}
  if(p.throwHold!=null&&p.throwHold>=0){const k=p.throwHold;T[CH.aLp]=T[CH.aRp]=2.7+.55*k;T[CH.eL]=T[CH.eR]=.85+.45*k;T[CH.aLa]=T[CH.aRa]=.10;T[CH.aLt]=T[CH.aRt]=-.2;T[CH.rootP]=-.06-.2*k;T[CH.spP]=-.1*k}
  if((p.throwT||0)>0){const r=1-p.throwT/.35,q=1-(1-r)*(1-r);
    if(p.gk){T[CH.aRp]=lerp(3.1,1.0,q);T[CH.eR]=lerp(.9,.1,q);T[CH.aRa]=.25;T[CH.aLp]=.6;T[CH.aLa]=.4;T[CH.spYw]=lerp(-.5,.4,q)}
    else{T[CH.aLp]=T[CH.aRp]=lerp(3.25,1.25,q);T[CH.eL]=T[CH.eR]=lerp(1.3,.12,q);T[CH.aLa]=T[CH.aRa]=.10;T[CH.rootP]=lerp(-.26,.28,q)}}
  // --- defensive wall: hands together in front ---
  if(p.wall){T[CH.aLp]=T[CH.aRp]=.40;T[CH.eL]=T[CH.eR]=.55;T[CH.aLa]=T[CH.aRa]=-.10;T[CH.aLt]=T[CH.aRt]=-.5}
  // --- celebrations: arms out, fist pump or both arms raised ---
  if((p.celebT||0)>0){const st=(ch.seed|0)%3,w=smooth(0,.3,p.celebT);
    if(st===0){T[CH.aLa]=lerp(T[CH.aLa],1.45,w);T[CH.aRa]=lerp(T[CH.aRa],1.45,w);T[CH.aLp]=T[CH.aRp]=0;T[CH.eL]=T[CH.eR]=.1;T[CH.rootR]+=.16*Math.sin(time*3.2)*w}
    else if(st===1){T[CH.aRp]=lerp(T[CH.aRp],2.5+.25*Math.sin(time*11),w);T[CH.eR]=lerp(T[CH.eR],.9,w);T[CH.aRa]=.2;T[CH.rootY]+=.10*Math.abs(Math.sin(time*6))*w}
    else{T[CH.aLp]=lerp(T[CH.aLp],2.65,w);T[CH.aRp]=lerp(T[CH.aRp],2.65,w);T[CH.aLa]=T[CH.aRa]=.32;T[CH.eL]=T[CH.eR]=.12;T[CH.hdP]=-.22*w}}
  // --- officials: card or flag up, advantage signal ---
  if((p.cardT||0)>0||(p.flagT||0)>0){T[CH.aRp]=2.95;T[CH.aRa]=.08;T[CH.eR]=.05}
  if((p.advT||0)>0){T[CH.aLp]=T[CH.aRp]=1.45;T[CH.eL]=T[CH.eR]=.05;T[CH.aLa]=T[CH.aRa]=.12}
  // --- slide tackle: sitting back, leading leg out along the turf ---
  if((p.slideT||0)>0){T[CH.gnd]=0;T[CH.rootY]=-.63;T[CH.rootP]=-1.1;T[CH.spP]=.5;T[CH.hdP]=.25;T[CH.rootYw]=T[CH.spYw]=T[CH.rootR]=0;
    T[CH.hRf]=.45;T[CH.kR]=.06;T[CH.hRa]=.05;T[CH.hRt]=0;T[CH.hLf]=-.2;T[CH.kL]=1.9;T[CH.hLa]=.45;T[CH.hLt]=0;footLocal(CH.hRf,-.1);footLocal(CH.hLf,.5);
    T[CH.aLp]=-.5;T[CH.aLa]=.55;T[CH.eL]=.75;T[CH.aRp]=-.5;T[CH.aRa]=.8;T[CH.eR]=.4}
  // --- keeper dive: crouch, launch sideways with both arms to the ball, land, get up ---
  if((p.diveT||0)>0){ch.diveMax=Math.max(ch.diveMax,p.diveT);
    const e=ch.diveMax-p.diveT,ext=smooth(.05,.26,e)*smooth(0,.28,p.diveT),sd2=Math.sign(Math.cos(p.face)*(p.diveDir||1))||1,cr=smooth(0,.07,e)*(1-ext);
    const fly=lerp(clamp((p.diveH??1)/ch.scale-.1,.3,1.25),.27,smooth(.42,.62,e));
    T[CH.gnd]=1-ext;T[CH.rootY]=(fly-HIP_Y)*ext;T[CH.rootR]=sd2*1.4*ext;T[CH.spR]=sd2*.22*ext;T[CH.rootP]=.1*cr;T[CH.rootYw]=T[CH.spYw]=0;T[CH.spP]=0;
    for(const o of [CH.hLf,CH.hRf]){T[o]=.5*cr+.12*ext;T[o+3]=.95*cr+.25*ext;T[o+1]=.12*ext;T[o+2]=0}
    const up=sd2>0?CH.hLf:CH.hRf;T[up+3]+=.6*ext;T[up]+=.3*ext;footLocal(CH.hLf,.4*ext);footLocal(CH.hRf,.4*ext);
    T[CH.aLp]=T[CH.aRp]=2.85*ext+.3*cr;T[CH.aLa]=T[CH.aRa]=.18*ext+.3*cr;T[CH.eL]=T[CH.eR]=.12+.5*cr;T[CH.aLt]=T[CH.aRt]=0;T[CH.hdP]=-.2*ext;
  }else ch.diveMax=0;
}

function applyPose(ch,P){
  const B=ch.B,lean=P[CH.rootP];let hipH=0;
  // feet on the ground: the lower foot decides how high the hips sit
  for(const o of [CH.hLf,CH.hRf]){const a=lean-P[o],b=a+P[o+3],g=P[o+4];
    const drop=(LEG1*Math.cos(a)+LEG2*Math.cos(b))*Math.cos(P[o+1])+Math.max(ANKLE*Math.cos(g)+FOOT_TOE*Math.sin(g),ANKLE*Math.cos(g)-FOOT_HEEL*Math.sin(g));
    if(drop>hipH)hipH=drop}
  B.hips.position.set(P[CH.rootX],lerp(HIP_Y,hipH,P[CH.gnd])+P[CH.rootY]+.035,P[CH.rootZ]);B.hips.rotation.set(lean,P[CH.rootYw],P[CH.rootR],'YXZ');
  B.spine.rotation.set(P[CH.spP]*.5,P[CH.spYw]*.5,P[CH.spR]*.5);B.chest.rotation.set(P[CH.spP]*.5,P[CH.spYw]*.5,P[CH.spR]*.5);
  B.neck.rotation.set(P[CH.hdP]*.4,P[CH.hdYw]*.4,0);B.head.rotation.set(P[CH.hdP]*.6,P[CH.hdYw]*.6,0);
  B.armL.rotation.set(-P[CH.aLp],P[CH.aLt],P[CH.aLa]);B.foreL.rotation.set(-P[CH.eL],0,0);
  B.armR.rotation.set(-P[CH.aRp],-P[CH.aRt],-P[CH.aRa]);B.foreR.rotation.set(-P[CH.eR],0,0);
  B.thighL.rotation.set(-P[CH.hLf],P[CH.hLt],P[CH.hLa]);B.shinL.rotation.set(P[CH.kL],0,0);
  B.footL.rotation.set(clamp(P[CH.nL]-(lean-P[CH.hLf]+P[CH.kL]),-.9,1.1),0,0);
  B.thighR.rotation.set(-P[CH.hRf],-P[CH.hRt],-P[CH.hRa]);B.shinR.rotation.set(P[CH.kR],0,0);
  B.footR.rotation.set(clamp(P[CH.nR]-(lean-P[CH.hRf]+P[CH.kR]),-.9,1.1),0,0);
}

// blend towards the target pose; the kicking leg follows almost instantly so contact lands on time
function poseCharacter(p,ch,dt,time){
  computePose(p,ch,time);const P=ch.P,T=_T;
  if(ch.snap){P.set(T);ch.snap=false}
  else{const k=1-Math.exp(-dt*26),kf=1-Math.exp(-dt*80),fast=(p.windA>0||p.kickT>0)?((p.foot??-1)<0?CH.hRf:CH.hLf):-1;
    for(let i=0;i<NCH;i++)P[i]+=(T[i]-P[i])*(fast>=0&&i>=fast&&i<fast+5?kf:k)}
  applyPose(ch,P);
}

// what the animation needs to know about the match situation (kept on the player so replays can restore it)
const POSE_FIELDS=['x','z','face','phase','spd','vf','vl','windA','kickT','kickKind','slideT','tackleT','diveT','diveDir','diveH','jumpT','throwT','celebT','stun','skillT','trapT',
  'ready','lookAt','throwHold','holdBall','wall','wide','hasBall','ballD'];
function poseContext(p){
  const own=ball.owner,dx=ball.x-p.x,dz=ball.z-p.z,d=hyp(dx,dz),a=Math.atan2(dz,dx)-p.face,rs=S.phase==='restart'?S.rs:null;
  p.ballD=d;p.hasBall=own===p;p.holdBall=!!(p.hands&&own===p);p.lookAt=p.hasBall?0:Math.atan2(Math.sin(a),Math.cos(a));
  p.throwHold=rs&&rs.type==='throw'&&rs.taker===p?(rs.kick?Math.min(1,rs.kickT/.3):0):-1;
  let c=0;p.wide=false;
  if(p.gk){if(own!==p)c=clamp(1.25-hyp(ball.x+HL*SIDE[p.team],ball.z)/40,0,.9);if(rs&&rs.type==='penalty'&&rs.team!==p.team){c=1;p.wide=true}}
  else if(own&&own.team!==p.team&&!p.wall)c=clamp(1-d/8,0,.75)*clamp(1.2-p.spd/5,0,1);
  p.ready=c;
}
