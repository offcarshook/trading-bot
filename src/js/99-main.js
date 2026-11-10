/* ===== Main loop ===== */
let last=performance.now(),resScale=1,frAcc=0,frN=0;
function frame(nowMs){
  const real=Math.min(.05,(nowMs-last)/1000);last=nowMs;const t=nowMs/1000;
  // adaptive resolution: if frames run slow, render fewer pixels; creep back up when there is headroom
  if(!S.paused&&!document.hidden){frAcc+=Math.min(.25,(nowMs-(frame.prev||nowMs))/1000);frN++;
    if(frAcc>CFG.adaptive.window){const ms=frAcc/frN*1000,A=CFG.adaptive,o=resScale;frAcc=frN=0;
      if(ms>A.slowMs)resScale=Math.max(A.minScale,resScale-A.step);else if(ms<A.fastMs)resScale=Math.min(1,resScale+A.step/2);
      if(resScale!==o)renderer.setPixelRatio(Math.min(devicePixelRatio||1,GFX.dpr)*resScale)}}
  frame.prev=nowMs;
  pollGamepad();
  if(!S.paused){
    if(S.phase==='replay'&&RP){RP.t+=real*.65;const f=Math.floor(RP.t*30);if(f>=RP.n-1)afterGoal();else applyFrame((RP.start+f)%REC.N)}
    else if(S.phase!=='full'){
      const sim=real*S.timeScale,n=Math.max(1,Math.ceil(sim/(1/90))),h=sim/n;for(let i=0;i<n;i++)step(h);
      if(S.phase==='goal'){S.phaseT+=real;if(S.phaseT>1.3)S.timeScale=1;if(S.phaseT>3)startReplay()}
      if(S.phase==='half'){S.phaseT+=real;if(S.phaseT>3)cutTo(()=>{S.half=2;S.clock=0;banner('');restart('kickoff',1)})}
    }
    bannerT-=real;if(bannerT<0&&S.phase!=='half')$('#banner').classList.remove('on');
    toastT-=real;if(toastT<0)$('#toast').classList.remove('on');
    noticeT-=real;if(noticeT<0)$('#notice').classList.remove('on');
    const dGoal=Math.min(hyp(ball.x-HL,ball.z),hyp(ball.x+HL,ball.z));AU.excite(clamp(1-dGoal/35,0,1));
  }
  animateCrowd(real);syncScene(t,S.paused?0:real);updateCamera(real);updateSun();
  if(S.user>=0){drawMini();updateHud()}
  renderer.render(scene,camera);
  requestAnimationFrame(frame);
}
window.strike27={renderer,book,sendOff,callOffside,markOffside,S,ball,players,ALL,ROSTER,BENCH,REF,AR1,AR2,startMatch,startDemo,step,restart,doSub,foul,applySubQueue,openSubs};
startDemo();
// repaint names and numbers once the display font has arrived
if(document.fonts&&document.fonts.load)document.fonts.load('900 40px "Big Shoulders Display"').then(()=>{ALL.forEach(applyLook);refKit()}).catch(()=>{});
requestAnimationFrame(frame);
