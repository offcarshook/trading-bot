/* ===== AI ===== */
function homePos(p,attacking){
  const s=SIDE[p.team],bOwn=ball.x*s,t=clamp((bOwn+HL)/PL,0,1);
  let x=p.hx+t*42-6+(attacking?7:-1)+((S.press?S.press[p.team]:1)-1)*(attacking?3:6);
  if(!attacking&&!FWD.has(p.role))x=Math.min(x,bOwn+6);
  x=clamp(x,-HL+3,HL-4);
  const z=clamp(p.hz*(attacking?1:.78)+ball.z*.28,-HW+2,HW-2);
  return[x*s,z];
}
function aiTick(){
  if(S.phase==='goal'){
    for(const p of players){const sc=p.celebT>0;if(sc){p.tx=S.goalEnd*(HL-2);p.tz=Math.sign(p.z||1)*(HW-3);p.run=true}
      else if(p.team===S.goalTeam&&S.lastKicker&&S.lastKicker.celebT>0){p.tx=S.lastKicker.x;p.tz=S.lastKicker.z;p.run=false}
      else{p.tx=p.x;p.tz=p.z;p.run=false}}
    return;
  }
  if(S.phase==='dead'){const P=S.pending;let tk=null,bd=1e9;
    for(const p of TP[P.team]){if(p.gk!==(P.type==='goalkick'))continue;const d=hyp(p.x-P.x,p.z-P.z);if(d<bd){bd=d;tk=p}}
    for(const p of players){if(p===S.ctrl)continue;p.run=false;if(p===tk){p.tx=P.x;p.tz=P.z}else{p.tx=p.x+p.vx*.25;p.tz=p.z+p.vz*.25}}
    return}
  if(S.phase==='restart'){for(const p of players){if(p===S.rs.taker)continue;p.tx=p.sx;p.tz=p.sz;p.run=false}return}
  if(S.phase==='cut')return;
  if(S.user>=0&&matchMin()>60){const ai=1-S.user;if(S.score[ai]<S.score[S.user])S.press[ai]=2}
  const own=ball.owner;
  for(let t=0;t<2;t++){
    const s=SIDE[t],mates=TP[t];
    const hasBall=own&&own.team===t,oppBall=own&&own.team!==t;
    const opX=TP[1-t].map(o=>o.x*s).sort((a,b)=>b-a);const offLine=Math.max(opX[1],ball.x*s,0)-.6;
    for(const p of mates){if(p.gk||p===S.ctrl&&!p.recv||p===own)continue;const[hx,hz]=homePos(p,hasBall||(!own&&S.lastTouch===t));p.tx=hx;p.tz=hz;p.run=hyp(hx-p.x,hz-p.z)>9}
    if(hasBall){
      if(own!==S.ctrl&&!own.gk)ownerAI(own);
      const sup=mates.filter(q=>q!==own&&!q.gk&&q!==S.ctrl).sort((a,b)=>hyp(a.x-own.x,a.z-own.z)-hyp(b.x-own.x,b.z-own.z)).slice(0,2);
      sup.forEach((q,k)=>{q.supT-=.1;if(q.supT<=0||q.supSide===undefined){q.supT=1.5;q.supSide=q.z>own.z?1:-1}
        q.tx=clamp(own.x+s*rand(3,9),-HL+2,HL-2);q.tz=clamp(own.z+q.supSide*rand(8,11),-HW+2,HW-2);q.run=true});
      if(own.x*s>-10)for(const q of mates){if(q===S.ctrl||!FWD.has(q.role)||q===own)continue;q.tx=Math.min(q.tx*s+7,offLine)*s;q.run=true}
    }else if(!own){
      let ch=null,ct=1e9,cp=null;
      for(const p of mates){if(p.gk&&!(inOwnBox({x:ball.x,z:ball.z,team:t})&&hyp(ball.vx,ball.vz)<14))continue;
        const r=intercept(p);if(p.recv){ch=p;cp=r;ct=-1;break}if(r[2]<ct){ct=r[2];ch=p;cp=r}}
      if(ch&&ch!==S.ctrl){
        let skip=false;if(S.ctrl&&S.ctrl.team===t&&!ch.recv){const rc=intercept(S.ctrl);if(rc[2]<=ct+.35)skip=true}
        if(!skip){ch.tx=cp[0];ch.tz=cp[1];ch.run=true}
      }
      if(ch&&ch===S.ctrl&&ch.recv){ch.tx=cp[0];ch.tz=cp[1]}
    }else if(oppBall){
      const cands=mates.filter(q=>!q.gk).sort((a,b)=>hyp(a.x-own.x,a.z-own.z)-hyp(b.x-own.x,b.z-own.z));
      let k=0;const ctrlClose=S.ctrl&&S.ctrl.team===t&&hyp(S.ctrl.x-own.x,S.ctrl.z-own.z)<hyp(cands[0].x-own.x,cands[0].z-own.z)+2;
      const press=cands.filter(q=>q!==S.ctrl);
      const gx=-HL*s;
      const pr=press[0],cv=press[1];
      const P=S.press[t],sit=P===0&&own.x*s>0;
      const presser=(p)=>{const dx=gx-own.x,dz=-own.z,d=hyp(dx,dz)||1;
        if(sit){p.tx=own.x+dx/d*8;p.tz=own.z+dz/d*8;p.run=false;return}
        p.tx=own.x+dx/d*1.5;p.tz=own.z+dz/d*1.5;p.run=true;const dd=hyp(p.x-own.x,p.z-own.z);
        if(dd<1.8&&p.tackleT<=0&&p.stun<=0){const lam=.6*(t===S.user?1:S.diff.tackle)*(own===S.ctrl&&userSprinting()?1.3:1)*(P===2?1.2:1);if(Math.random()<lam*.1)standTackle(p)}
        else if(dd>1.3&&dd<3.2&&p.slideT<=0&&p.stun<=0&&p.tackleT<=0&&Math.random()<.006*(t===S.user?.6:S.diff.tackle)*(P===2?1.4:1)){p.face=Math.atan2(own.z-p.z,own.x-p.x);slideTackle(p)}};
      if(pr&&!ctrlClose)presser(pr);
      else if(pr){const dx=gx-own.x,dz=-own.z,d=hyp(dx,dz)||1;pr.tx=own.x+dx/d*6;pr.tz=own.z+dz/d*6;pr.run=true}
      if(cv){const dx=gx-own.x,dz=-own.z,d=hyp(dx,dz)||1;cv.tx=own.x+dx/d*6;cv.tz=own.z+dz/d*6;cv.run=true;
        if((IN.press&&t===S.user)||(P===2&&own.x*s>-12))presser(cv)}
    }
  }
  // auto-switch for the human on defence
  if(S.ctrl&&!attackMode()&&S.phase==='play'){
    S.autoT-=.1;if(S.autoT<=0){const cd=hyp(S.ctrl.x-ball.x,S.ctrl.z-ball.z);let b=null,bd=1e9;
      for(const q of TP[S.user]){if(q.gk)continue;const d=hyp(q.x-ball.x,q.z-ball.z);if(d<bd){bd=d;b=q}}
      if(b&&b!==S.ctrl&&cd>13&&bd<cd-7){setCtrl(b);S.autoT=1.2}}
  }
}
function ownerAI(o){
  const s=SIDE[o.team],gx=HL*s,dG=hyp(gx-o.x,o.z),[opp,press]=nearestOpp(o);
  let dz=-o.z*.03;
  if(opp&&press<7&&(opp.x-o.x)*s>0)dz+=Math.sign(o.z-opp.z||1)*1.0;
  o.tx=o.x+s*8;o.tz=clamp(o.z+dz*8,-HW+2,HW-2);o.run=press>3&&o.stam>.25;
  o.aiT-=.1;
  if(o.aiT>0)return;
  o.aiT=S.diff.react*(o.team===S.user?.5:.8)+rand(.05,.18);
  if(dG<29&&Math.abs(o.z)<20){const pr=dG<14?.85:dG<21?.5:.16;if(Math.random()<pr){shoot(o,rand(.55,.95),null,dG<19&&Math.random()<.4);return}}
  const tgt=bestTarget(o,null,false,40);
  let want=press<2.4?.5:press<4.5?.14:.03;if(o.possT>3.5)want+=.35;if(tgt&&openness(o,tgt)<.35)want*=.3;
  if(tgt&&Math.random()<want){passBall(o,null,FWD.has(tgt.role)&&Math.random()<.4?'through':'ground');return}
}
function keeperThink(k){
  const s=SIDE[k.team],gx=-HL*s;
  if(S.phase==='restart'){k.tx=k.sx;k.tz=k.sz;k.run=false;return}
  if(ball.owner===k){
    k.tx=k.x;k.tz=k.z;
    if(k.holdT<=0){k.aiT-=1/60;if(k.aiT<=0)keeperDistribute(k)}
    return;
  }
  if(ball.shot&&ball.shotTeam!==k.team&&!ball.owner&&ball.vx*s<0){
    if(k.shotSeen!==S.shotId)decideSave(k);
    if(k.save){k.tx=gx+s*1.2;k.tz=k.save.tz;return}
  }
  k.run=false;const dB=hyp(ball.x-gx,ball.z)||1;
  let off=clamp(dB*.1,.8,4.2);
  const own=ball.owner;
  if(own&&own.team!==k.team&&inOwnBox({x:own.x,z:own.z,team:k.team})&&hyp(own.x-k.x,own.z-k.z)<10)off=clamp(dB*.45,1,7);
  k.tx=gx+(ball.x-gx)/dB*off;k.tz=clamp(ball.z/dB*off*1.6,-GHW+.4,GHW-.4);
  if(!own&&!ball.shot&&ball.y>1.2&&ball.vx*s<0&&S.phase==='play'){const r=intercept(k);if(Math.abs(r[0]-gx)<6.5&&Math.abs(r[1])<9.5&&r[2]<2.2){k.tx=r[0];k.tz=r[1];k.run=true;return}}
  if(!own&&inOwnBox({x:ball.x,z:ball.z,team:k.team})&&hyp(ball.vx,ball.vz)<13&&!ball.shot){
    let closest=true;const dk=hyp(ball.x-k.x,ball.z-k.z);for(const q of TP[1-k.team])if(hyp(ball.x-q.x,ball.z-q.z)<dk-1)closest=false;
    if(closest||dk<6){const r=intercept(k);k.tx=r[0];k.tz=r[1]}
  }
}
function decideSave(k){
  k.shotSeen=S.shotId;k.save=null;const s=SIDE[k.team],gx=-HL*s;
  const vx=ball.vx;if(Math.abs(vx)<.5)return;
  const tk=(k.x-ball.x)/vx,tl=(gx-ball.x)/vx;if(tk<=0)return;
  const vh=hyp(ball.vx,ball.vz)||1;
  const lat=t=>ball.z+ball.vz*t+(vx/vh)*.5*ball.curl*t*t;
  const g2=G+ball.dip,zk=lat(tk),yk=ball.y+ball.vy*tk-.5*g2*tk*tk,zl=lat(tl),yl=ball.y+ball.vy*tl-.5*g2*tl*tl;
  if(!(Math.abs(zl)<GHW+.2&&yl<GH+.15))return;
  const skill=k.team===S.user||S.demo?.76:S.diff.gk;
  const react=.24-skill*.12,reach=.9+1.7*skill,move=Math.max(0,tk-react)*5.2,need=Math.abs(zk-k.z);
  const spd=hyp(ball.vx,ball.vy,ball.vz);
  let p=need<=move+reach?.5+skill*.45-Math.max(0,spd-20)/45-Math.max(0,need-move-.6)/reach*.35-Math.max(0,yk-1.9)*.3:0;
  if(spd<16)p+=.15;
  const ok=Math.random()<clamp(p,0,.96);
  const dir=Math.sign(zk-k.z)||1;
  k.save={ok,tz:ok?zk:k.z+dir*Math.max(0,Math.min(need,move+reach)-rand(.9,1.6)),zk,yk,dir,spd};
  if(need>1.1){k.diveT=Math.min(tk,.6)+.7;k.diveDir=dir}
  if(!ok)k.cool=tk+.45;
}
function resolveSaves(){
  if(!ball.shot||ball.owner)return;
  for(const t of [0,1]){const k=TP[t][0];if(!k.save||!k.save.ok||ball.shotTeam===t)continue;
    if(Math.abs(ball.x-k.x)<.75&&Math.abs(ball.z-k.z)<2.6&&ball.y<2.8){
      const sv=k.save;k.save=null;
      if(sv.spd<22&&sv.yk<2.1&&Math.random()<.62){gainPossession(k);k.holdT=1.3;toast('SAVED')}
      else{ball.vx=-ball.vx*.3;ball.vz=sv.dir*rand(4,9)+ball.vz*.2;ball.vy=rand(2,5);ball.shot=false;S.lastTouch=t;k.cool=.5;toast('PARRIED')}
      AU.ooh();
    }}
}
