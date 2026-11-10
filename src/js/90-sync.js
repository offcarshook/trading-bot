/* ===== Rendering sync ===== */
const _m=new THREE.Matrix4(),_q=new THREE.Quaternion(),_s=new THREE.Vector3(),_p=new THREE.Vector3(),_ax=new THREE.Vector3(),_rq=new THREE.Quaternion();
let lastBX=0,lastBZ=0;
function syncScene(t,dt){
  const replay=S.phase==='replay';
  for(let i=0;i<22;i++){
    const p=ALL[i],ch=p.mesh;ch.root.visible=!p.off;
    if(!p.off){ch.root.position.set(p.x,0,p.z);ch.root.rotation.y=PI/2-p.face;if(!replay)poseContext(p);poseCharacter(p,ch,dt,t)}
    _p.set(p.x,.02,p.z);_s.setScalar(p.off?0:1);_q.identity();_m.compose(_p,_q,_s);shadows.setMatrixAt(i,_m);
  }
  const sh=clamp(1-ball.y/6,.3,1)*.6;_p.set(ball.x,.021,ball.z);_s.set(sh,1,sh);_q.identity();_m.compose(_p,_q,_s);shadows.setMatrixAt(22,_m);syncOfficials(dt,t);shadows.instanceMatrix.needsUpdate=true;
  ballMesh.position.set(ball.x,ball.y,ball.z);
  const dx=ball.x-lastBX,dz=ball.z-lastBZ,dist=hyp(dx,dz);
  if(dist>1e-4&&dist<3){_ax.set(dz,0,-dx).normalize();_rq.setFromAxisAngle(_ax,dist/BR);ballMesh.quaternion.premultiply(_rq)}
  lastBX=ball.x;lastBZ=ball.z;
  const c=S.ctrl;marker.visible=!!c&&S.phase!=='replay'&&S.phase!=='goal'&&!(S.phase==='restart'&&S.rs&&(S.rs.team===S.user||S.rs.type==='penalty'));
  if(c){marker.position.set(c.x,0,c.z);arrow.position.y=c.mesh.scale*1.84+.42+Math.sin(t*5)*.12}
  const rs=S.rs,showAim=S.phase==='restart'&&rs&&rs.ready&&!rs.kick&&rs.team===S.user;
  aimRing.visible=aimDots.visible=!!showAim;
  if(showAim){aimRing.position.set(rs.aimX,.05,rs.aimZ);aimRing.scale.setScalar(1+Math.sin(t*6)*.08);
    const near=Math.abs(rs.aimX-SIDE[rs.team]*HL)<4&&Math.abs(rs.aimZ)<6,btn=(rs.type==='penalty'||(rs.inRange&&near))?'shoot':IN.held.through!=null?'through':'pass';
    const hs=IN.held.shoot!=null?IN.held.shoot:IN.held.pass,pw=hs!=null?clamp((now()-hs)/.9,.2,1.18):.75;
    const k=userKickFor(rs,btn,pw);drawPath(solveKick(k,ball.x,k.mode==='throw'?2.5:BR,ball.z),k.mode)}
  const r=ball.passTo;recvRing.visible=!!r&&r!==c&&S.phase==='play';if(r)recvRing.position.set(r.x,0,r.z);
}
