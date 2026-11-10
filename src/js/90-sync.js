/* ===== Rendering sync ===== */
const _m=new THREE.Matrix4(),_q=new THREE.Quaternion(),_s=new THREE.Vector3(),_p=new THREE.Vector3(),_ax=new THREE.Vector3(),_rq=new THREE.Quaternion();
let lastBX=0,lastBZ=0;
function syncScene(t){
  for(let i=0;i<22;i++){
    const p=ALL[i],m=p.mesh;m.root.visible=!p.off;
    m.root.position.set(p.x,0,p.z);m.root.rotation.y=Math.PI/2-p.face;
    const amp=Math.min(p.spd/6.5,1),sw=Math.sin(p.phase)*.85*amp;
    m.hipL.rotation.x=sw;m.hipR.rotation.x=-sw;m.shL.rotation.set(-sw*.8,0,-.08);m.shR.rotation.set(sw*.8,0,.08);
    m.rig.rotation.set(amp*.13,0,0);m.rig.position.y=Math.abs(Math.sin(p.phase))*.06*amp;
    if(p.kickT>0){const k=1-p.kickT/.28;m.hipR.rotation.x=-Math.sin(k*Math.PI)*1.5+.25*(1-k);m.shL.rotation.x=-Math.sin(k*Math.PI)*.7}
    if(p.slideT>0){m.rig.rotation.x=-1.15;m.rig.position.y=.3;m.hipR.rotation.x=-1.3;m.hipL.rotation.x=-.5}
    if(p.diveT>0){const s=Math.sign(Math.cos(p.face)*p.diveDir)||1;const k=Math.min(1,(1.3-p.diveT)*3);m.rig.rotation.z=s*1.35*k;m.rig.position.y=.55*k;m.shL.rotation.x=m.shR.rotation.x=-3}
    if(p.hands&&ball.owner===p){m.shL.rotation.x=m.shR.rotation.x=-1.3}
    if(S.phase==='restart'&&S.rs&&S.rs.type==='throw'&&S.rs.taker===p){const k=S.rs.kick?Math.min(1,S.rs.kickT/.3):0;m.shL.rotation.set(-2.9-k*.6,0,-.12);m.shR.rotation.set(-2.9-k*.6,0,.12);m.rig.rotation.x=-.1-k*.25}
    if(p.throwT>0){const k=1-p.throwT/.35;m.shL.rotation.set(-3.4+k*2.2,0,-.12);m.shR.rotation.set(-3.4+k*2.2,0,.12);m.rig.rotation.x=.3*k}
    if(p.wall){m.shL.rotation.set(-.35,0,.45);m.shR.rotation.set(-.35,0,-.45)}
    if(p.celebT>0){m.shL.rotation.set(-2.9,0,-.4);m.shR.rotation.set(-2.9,0,.4);m.rig.position.y=Math.abs(Math.sin(t*9))*.35}
    if(p.skillT>0){m.rig.rotation.z=Math.sin(p.skillT*18)*.28}
    if(p.jumpT>0){m.rig.position.y+=Math.sin(p.jumpT/.35*Math.PI)*.45}
    if(p.stun>0&&p.slideT<=0&&p.diveT<=0){m.rig.rotation.x=-.25}
    _p.set(p.x,.02,p.z);_s.setScalar(p.off?0:1);_q.identity();_m.compose(_p,_q,_s);shadows.setMatrixAt(i,_m);
  }
  const sh=clamp(1-ball.y/6,.3,1)*.6;_p.set(ball.x,.021,ball.z);_s.set(sh,1,sh);_q.identity();_m.compose(_p,_q,_s);shadows.setMatrixAt(22,_m);syncOfficials();shadows.instanceMatrix.needsUpdate=true;
  ballMesh.position.set(ball.x,ball.y,ball.z);
  const dx=ball.x-lastBX,dz=ball.z-lastBZ,dist=hyp(dx,dz);
  if(dist>1e-4&&dist<3){_ax.set(dz,0,-dx).normalize();_rq.setFromAxisAngle(_ax,dist/BR);ballMesh.quaternion.premultiply(_rq)}
  lastBX=ball.x;lastBZ=ball.z;
  const c=S.ctrl;marker.visible=!!c&&S.phase!=='replay'&&S.phase!=='goal'&&!(S.phase==='restart'&&S.rs&&(S.rs.team===S.user||S.rs.type==='penalty'));
  if(c){marker.position.set(c.x,0,c.z);arrow.position.y=2.75*PSCALE+Math.sin(t*5)*.12}
  const rs=S.rs,showAim=S.phase==='restart'&&rs&&rs.ready&&!rs.kick&&rs.team===S.user;
  aimRing.visible=aimDots.visible=!!showAim;
  if(showAim){aimRing.position.set(rs.aimX,.05,rs.aimZ);aimRing.scale.setScalar(1+Math.sin(t*6)*.08);
    const near=Math.abs(rs.aimX-SIDE[rs.team]*HL)<4&&Math.abs(rs.aimZ)<6,btn=(rs.type==='penalty'||(rs.inRange&&near))?'shoot':IN.held.through!=null?'through':'pass';
    const hs=IN.held.shoot!=null?IN.held.shoot:IN.held.pass,pw=hs!=null?clamp((now()-hs)/.9,.2,1.18):.75;
    const k=userKickFor(rs,btn,pw);drawPath(solveKick(k,ball.x,k.mode==='throw'?2.5:BR,ball.z),k.mode)}
  const r=ball.passTo;recvRing.visible=!!r&&r!==c&&S.phase==='play';if(r)recvRing.position.set(r.x,0,r.z);
}
