/* ===== Officials: referee + two assistants ===== */
const OFFKIT={kit:new THREE.MeshLambertMaterial({color:0x111111}),shorts:new THREE.MeshLambertMaterial({color:0x111111}),socks:new THREE.MeshLambertMaterial({color:0x111111})};
function mkOfficial(role){
  const o={role,x:role==='ref'?-6:0,z:role==='ref'?10:0,vx:0,vz:0,spd:0,face:0,faceT:0,phase:rand(0,6),cardT:0,flagT:0,advT:0};
  o.mesh=buildModel(0,false,SKIN[(Math.random()*4)|0],HAIR[(Math.random()*5)|0],OFFKIT);
  o.cardMesh=new THREE.Mesh(new THREE.PlaneGeometry(.12,.17),new THREE.MeshBasicMaterial({color:0xffd400,side:THREE.DoubleSide}));
  o.cardMesh.position.set(0,-.66,.03);o.cardMesh.visible=false;o.mesh.shR.add(o.cardMesh);
  if(role!=='ref'){const f=new THREE.Mesh(new THREE.PlaneGeometry(.34,.26),new THREE.MeshBasicMaterial({color:0xffd23f,side:THREE.DoubleSide}));f.position.set(0,-.6,.18);o.mesh.shR.add(f)}
  return o;
}
const REF=mkOfficial('ref'),AR1=mkOfficial('ar'),AR2=mkOfficial('ar'),OFFICIALS=[REF,AR1,AR2];
function refKit(){
  const pal=[0x111111,0xd8f23a,0xe0458a,0x29b6f6];let best=pal[0],bs=-1;
  for(const c of pal){const d=Math.min(colorDist(c,S.kitColor[0]),colorDist(c,S.kitColor[1]));if(d>bs){bs=d;best=c}}
  OFFKIT.kit.color.setHex(best);OFFKIT.socks.color.setHex(best);
}
function offLineWorld(a){const s=SIDE[a],xs=TP[1-a].map(o=>o.x*s).sort((p,q)=>q-p);return s*Math.max(xs[1]??0,ball.x*s,0)}
function offMove(o,dt,tx,tz,mx){const dx=tx-o.x,dz=tz-o.z,d=hyp(dx,dz),sp=d>.4?Math.min(mx,d*1.6):0;
  const ax=(d?dx/d*sp:0)-o.vx,az=(d?dz/d*sp:0)-o.vz,l=hyp(ax,az),a=14*dt;if(l>a){o.vx+=ax/l*a;o.vz+=az/l*a}else{o.vx+=ax;o.vz+=az}}
function stepOfficials(dt){
  const own=ball.owner,dir=own?SIDE[own.team]:Math.sign(ball.vx)||1;
  let tx=clamp(ball.x-dir*9,-HL+6,HL-6),tz=clamp(ball.z+(ball.z>0?-9:9),-HW+4,HW-4);
  if(S.phase==='restart'&&S.rs){tx=clamp(ball.x-SIDE[S.rs.team]*12,-HL+8,HL-8);tz=clamp(ball.z*.4+(ball.z>0?-14:14),-HW+5,HW-5)}
  if(REF.cardT>0){tx=REF.x;tz=REF.z}
  offMove(REF,dt,tx,tz,7.2);
  if(REF.cardT<=0)REF.faceT=Math.atan2(ball.z-REF.z,ball.x-REF.x);
  const aR=SIDE[0]>0?0:1;
  offMove(AR1,dt,clamp(Math.max(offLineWorld(aR),ball.x),0,HL),-(HW+1.5),7.5);
  offMove(AR2,dt,clamp(Math.min(offLineWorld(1-aR),ball.x),-HL,0),HW+1.5,7.5);
  AR1.faceT=Math.PI/2;AR2.faceT=-Math.PI/2;
  for(const o of OFFICIALS){o.x+=o.vx*dt;o.z+=o.vz*dt;o.spd=hyp(o.vx,o.vz);o.phase+=o.spd*dt*1.75;
    const ft=o===REF&&o.spd>2&&o.cardT<=0?Math.atan2(o.vz,o.vx):o.faceT;let d=ft-o.face;d=Math.atan2(Math.sin(d),Math.cos(d));o.face+=clamp(d,-8*dt,8*dt);
    o.cardT=Math.max(0,o.cardT-dt);o.flagT=Math.max(0,o.flagT-dt);o.advT=Math.max(0,o.advT-dt)}
}
function syncOfficials(){
  OFFICIALS.forEach((o,k)=>{const m=o.mesh;m.root.position.set(o.x,0,o.z);m.root.rotation.y=Math.PI/2-o.face;
    const amp=Math.min(o.spd/6.5,1),sw=Math.sin(o.phase)*.85*amp;
    m.hipL.rotation.x=sw;m.hipR.rotation.x=-sw;m.shL.rotation.set(-sw*.8,0,-.08);m.shR.rotation.set(sw*.8,0,.08);m.rig.position.y=Math.abs(Math.sin(o.phase))*.06*amp;m.rig.rotation.set(amp*.1,0,0);
    if(o.advT>0){m.shL.rotation.set(-1.6,0,-.2);m.shR.rotation.set(-1.6,0,.2)}
    if(o.cardT>0||o.flagT>0)m.shR.rotation.set(-3.05,0,.12);
    o.cardMesh.visible=o.cardT>0;
    _p.set(o.x,.02,o.z);_s.set(1,1,1);_q.identity();_m.compose(_p,_q,_s);shadows.setMatrixAt(23+k,_m)});
}
