/* ===== Camera ===== */
const CAMS=[{name:'Broadcast',h:20,d:29,fov:38},{name:'Tele',h:14,d:22,fov:38},{name:'Wide',h:34,d:50,fov:40},{name:'Pro',pro:true}];
const cam={x:0,z:0,lx:0,ly:0,lz:0,init:false};
function updateCamera(dt){
  const a=camera.aspect,pf=a<1?1.75:a<1.45?1.2:1;
  let px,py,pz,lx,ly,lz,k=1-Math.exp(-dt*3.4);
  if(S.phase==='replay'){
    const e=S.goalEnd;px=e*(HL+9);py=5.5;pz=ball.z*.4+(e>0?8:-8)*.0+9;lx=ball.x;ly=1;lz=ball.z;k=1-Math.exp(-dt*5);
  }else{
    const own=ball.owner,lead=own?SIDE[own.team]*7:clamp(ball.vx*.3,-8,8);
    const fx=clamp(ball.x+lead,-HL+10,HL-10),fz=clamp(ball.z*.85,-HW*.5,HW*.72);
    cam.x+=(fx-cam.x)*k;cam.z+=(fz-cam.z)*k;
    const C=CAMS[S.camMode];
    if(C.pro&&S.ctrl){const p=S.ctrl,s=SIDE[S.user];px=p.x-s*13*pf;py=7.5*pf;pz=p.z*.85;lx=p.x+s*12;ly=0;lz=p.z*.85;k=1-Math.exp(-dt*4)}
    else{const C2=C.pro?CAMS[0]:C,zo=1+Math.min(1,hyp(ball.vx,ball.vz)/30)*.1+(ball.y>3?.08:0);
      px=cam.x;py=C2.h*pf*zo;pz=cam.z+C2.d*pf*zo;lx=cam.x;ly=0;lz=cam.z-1.5;camera.fov=C2.fov}
    if(S.phase==='restart'&&S.rs){const rs=S.rs,e=SIDE[rs.team];
      if(rs.type==='corner'){const c=Math.sign(ball.z);px=ball.x-e*1.2;py=8.5*pf;pz=ball.z+c*7.5;lx=e*(HL-10);ly=0;lz=c*2;camera.fov=42}
      else if(rs.type==='penalty'||rs.inRange){const gx=e*HL,dx=ball.x-gx,dz=ball.z,d=hyp(dx,dz)||1,wx=dx/d,wz=dz/d,bk=rs.type==='penalty'?9:10.5;
        px=ball.x+wx*bk+wz*1.6;py=(rs.type==='penalty'?3.6:4.4)*pf;pz=ball.z+wz*bk-wx*1.6;lx=gx;ly=1;lz=ball.z*.25;camera.fov=40}}
  }
  if(!cam.init){camera.position.set(px,py,pz);cam.lx=lx;cam.ly=ly;cam.lz=lz;cam.init=true}
  camera.position.x+=(px-camera.position.x)*k;camera.position.y+=(py-camera.position.y)*k;camera.position.z+=(pz-camera.position.z)*k;
  cam.lx+=(lx-cam.lx)*k;cam.ly+=(ly-cam.ly)*k;cam.lz+=(lz-cam.lz)*k;
  camera.lookAt(cam.lx,cam.ly,cam.lz);camera.updateProjectionMatrix();
}
