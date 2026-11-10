/* ===== Input: floating joystick, buttons, keyboard, gamepad ===== */
const IN={jx:0,jy:0,joyId:null,ox:0,oy:0,sprintBtn:false,keys:new Set(),queue:[],held:{},contain:false,press:false,lastTackle:0,gpPrev:[]};
const joyEl=$('#joy'),knob=$('#knob');
const touch=$('#touch');
touch.addEventListener('pointerdown',e=>{
  if(S.user<0||IN.joyId!==null||e.clientX>innerWidth*.55)return;
  IN.joyId=e.pointerId;IN.ox=e.clientX;IN.oy=e.clientY;joyEl.style.left=IN.ox+'px';joyEl.style.top=IN.oy+'px';joyEl.classList.add('on');$('#joyHint').classList.add('gone');
  try{touch.setPointerCapture(e.pointerId)}catch(_){}
});
touch.addEventListener('pointermove',e=>{if(e.pointerId!==IN.joyId)return;let dx=e.clientX-IN.ox,dy=e.clientY-IN.oy;const R=58,l=hyp(dx,dy);if(l>R){dx*=R/l;dy*=R/l}
  IN.jx=dx/R;IN.jy=dy/R;knob.style.transform=`translate(${dx}px,${dy}px)`});
const joyEnd=e=>{if(e.pointerId!==IN.joyId)return;IN.joyId=null;IN.jx=IN.jy=0;knob.style.transform='';joyEl.classList.remove('on')};
touch.addEventListener('pointerup',joyEnd);touch.addEventListener('pointercancel',joyEnd);
document.addEventListener('contextmenu',e=>e.preventDefault());

const _f=new THREE.Vector3();
function rawStick(){
  let jx=IN.jx,jy=IN.jy;const k=IN.keys;
  const kx=(k.has('KeyD')||k.has('ArrowRight')?1:0)-(k.has('KeyA')||k.has('ArrowLeft')?1:0),ky=(k.has('KeyS')||k.has('ArrowDown')?1:0)-(k.has('KeyW')||k.has('ArrowUp')?1:0);
  if(kx||ky){const l=hyp(kx,ky);jx=kx/l;jy=ky/l}
  if(IN.gp&&hyp(IN.gp[0],IN.gp[1])>.18){jx=IN.gp[0];jy=IN.gp[1]}
  return[jx,jy];
}
function worldInput(){
  const[jx,jy]=rawStick();const m=Math.min(1,hyp(jx,jy));if(m<.14)return[0,0,0];
  camera.getWorldDirection(_f);_f.y=0;_f.normalize();const rx=-_f.z,rz=_f.x;
  const wx=rx*jx+_f.x*-jy,wz=rz*jx+_f.z*-jy,l=hyp(wx,wz)||1;return[wx/l,wz/l,m];
}
const userSprinting=()=>IN.sprintBtn||IN.keys.has('ShiftLeft')||IN.keys.has('ShiftRight')||(IN.gp&&IN.gp[2])||(hyp(...rawStick())>.93&&IN.joyId!==null);
const attackMode=()=>S.phase==='restart'&&S.rs?S.rs.team===S.user:ball.owner?ball.owner.team===S.user:!!(ball.passTo&&ball.passTo.team===S.user);
const canAct=()=>S.user>=0&&S.ctrl&&(S.phase==='play'||S.phase==='restart')&&!S.paused;
function btnDown(b){
  if(b==='sprint'){IN.sprintBtn=true;return}
  if(S.phase==='dead'&&S.user>=0&&S.phaseT>.35){S.phaseT=99;return}
  if(!canAct())return;
  IN.held[b]=now();
  if(!attackMode()){
    IN.held[b]=null;
    if(b==='pass')switchPlayer();
    else if(b==='shoot'){const t=now();if(t-IN.lastTackle<.32)slideTackle(S.ctrl);else standTackle(S.ctrl);IN.lastTackle=t}
    else if(b==='through')IN.press=true;
    else if(b==='skill')IN.contain=true;
    else if(b==='lob')slideTackle(S.ctrl);
  }else if(b!=='shoot'){IN.held[b]=null;IN.queue.push({b,held:0,at:now()})}
  buzz(6);
}
function btnUp(b){
  if(b==='sprint'){IN.sprintBtn=false;return}
  if(b==='through')IN.press=false;if(b==='skill')IN.contain=false;
  const t0=IN.held[b];IN.held[b]=null;if(t0==null)return;
  IN.queue.push({b,held:now()-t0,at:now()});
}
document.querySelectorAll('#pad [data-b]').forEach(el=>{
  const b=el.dataset.b;
  el.addEventListener('pointerdown',e=>{e.preventDefault();e.stopPropagation();try{el.setPointerCapture(e.pointerId)}catch(_){}el.classList.add('on');btnDown(b)});
  const up=e=>{if(!el.classList.contains('on'))return;el.classList.remove('on');btnUp(b)};
  el.addEventListener('pointerup',up);el.addEventListener('pointercancel',up);
});
const KEYMAP={KeyJ:'pass',KeyK:'shoot',KeyL:'through',KeyI:'skill',KeyU:'lob',Space:'pass'};
addEventListener('keydown',e=>{
  if(e.repeat)return;IN.keys.add(e.code);
  if(KEYMAP[e.code]){e.preventDefault();btnDown(KEYMAP[e.code])}
  if(e.code==='ShiftLeft'||e.code==='ShiftRight')IN.sprintBtn=true;
  if((e.code==='KeyP'||e.code==='Escape')&&S.user>=0&&S.phase!=='full')togglePause();
  if(S.phase==='replay'&&(e.code==='Space'||e.code==='KeyJ'))afterGoal();
});
addEventListener('keyup',e=>{IN.keys.delete(e.code);if(KEYMAP[e.code])btnUp(KEYMAP[e.code]);if(e.code==='ShiftLeft'||e.code==='ShiftRight')IN.sprintBtn=false});
function pollGamepad(){
  const gp=navigator.getGamepads?[...navigator.getGamepads()].find(Boolean):null;if(!gp){IN.gp=null;return}
  IN.gp=[gp.axes[0]||0,gp.axes[1]||0,gp.buttons[7]&&gp.buttons[7].pressed];
  const map=[[0,'pass'],[1,'shoot'],[2,'through'],[3,'skill'],[4,'lob']];
  for(const[i,b]of map){const p=!!(gp.buttons[i]&&gp.buttons[i].pressed);if(p&&!IN.gpPrev[i])btnDown(b);if(!p&&IN.gpPrev[i])btnUp(b);IN.gpPrev[i]=p}
}
function switchPlayer(){
  const[ix,iz,m]=worldInput();let best=null,bs=1e9;
  for(const t of TP[S.user]){if(t===S.ctrl||t.gk)continue;let sc=hyp(t.x-ball.x,t.z-ball.z);
    if(m>.3){const dx=t.x-S.ctrl.x,dz=t.z-S.ctrl.z,d=hyp(dx,dz)||1;sc-=((dx*ix+dz*iz)/d)*14}
    if(sc<bs){bs=sc;best=t}}
  if(best){setCtrl(best);buzz(10)}
}
function processQueue(){
  const p=S.ctrl;
  if(S.phase==='restart'&&S.rs){if(S.rs.team===S.user&&S.rs.ready&&!S.rs.kick&&IN.queue.length){const a=IN.queue.shift();IN.queue.length=0;userSetPiece(a)}else if(!S.rs.ready||S.rs.team!==S.user)IN.queue.length=0;return}
  if(!p){IN.queue.length=0;return}
  if(ball.owner===p&&IN.queue.length){const a=IN.queue.shift();IN.queue.length=0;doUserAction(p,a);return}
  const t=now();IN.queue=IN.queue.filter(a=>(ball.passTo===p&&t-a.at<1.6)||t-a.at<.15);
}
function doUserAction(p,a){
  const[ix,iz,m]=worldInput();const dir=m>.15?[ix,iz]:null;
  const rs=S.rs?S.rs.type:null;
  if(a.b==='pass'){const cross=p.x*SIDE[p.team]>HL-32&&Math.abs(p.z)>15;passBall(p,dir,cross?'lob':'ground')}
  else if(a.b==='through'){passBall(p,dir,'through')}
  else if(a.b==='lob'){passBall(p,dir,'lob')}
  else if(a.b==='shoot'){
    if(p.mustPass&&rs!=='freekick'){passBall(p,dir,'lob');return}
    const fin=a.held<.18;shoot(p,fin?.55:clamp(a.held/.9,.2,1.18),m>.2?clamp(iz*1.3,-1,1):null,fin);
  }
  else if(a.b==='skill'){if(!p.mustPass)skillMove(p,dir||[Math.cos(p.face),Math.sin(p.face)])}
}
