/* ===== Renderer & scene ===== */
const renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.75));
renderer.setSize(innerWidth,innerHeight);
renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.toneMapping=THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure=1.15;
$('#stage').appendChild(renderer.domElement);
const scene=new THREE.Scene();
scene.background=new THREE.Color(0x060a13);
scene.fog=new THREE.Fog(0x060a13,110,230);
const camera=new THREE.PerspectiveCamera(38,innerWidth/innerHeight,0.5,500);
camera.position.set(0,24,40);
scene.add(new THREE.HemisphereLight(0xe8efff,0x22331a,1.5));
const sun=new THREE.DirectionalLight(0xfff6e6,2.2); sun.position.set(-20,60,30); scene.add(sun);
const fill=new THREE.DirectionalLight(0xbcd2ff,.7); fill.position.set(30,40,-40); scene.add(fill);

function canvasTex(w,h,draw){const c=document.createElement('canvas');c.width=w;c.height=h;draw(c.getContext('2d'),w,h);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t}

/* ---------- Pitch ---------- */
(function buildPitch(){
  const M=7, W=2048, H=Math.round(W*(PW+2*M)/(PL+2*M)), sx=W/(PL+2*M);
  const X=x=>(x+HL+M)*sx, Z=z=>(z+HW+M)*sx;
  const tex=canvasTex(W,H,(g)=>{
    g.fillStyle='#2b6f2f';g.fillRect(0,0,W,H);
    const n=18;for(let i=0;i<n;i++){g.fillStyle=i%2?'#327d35':'#2a6c2e';g.fillRect(X(-HL+i*PL/n),0,PL/n*sx+1,H)}
    for(let i=0;i<9000;i++){g.fillStyle=`rgba(${Math.random()<.5?0:255},${Math.random()<.5?40:255},0,.035)`;g.fillRect(Math.random()*W,Math.random()*H,2,2)}
    g.strokeStyle='rgba(255,255,255,.9)';g.fillStyle='rgba(255,255,255,.9)';g.lineWidth=.13*sx;
    const rect=(x0,z0,x1,z1)=>g.strokeRect(X(Math.min(x0,x1)),Z(Math.min(z0,z1)),Math.abs(x1-x0)*sx,Math.abs(z1-z0)*sx);
    const arc=(x,z,r,a0,a1)=>{g.beginPath();g.arc(X(x),Z(z),r*sx,a0,a1);g.stroke()};
    const spot=(x,z)=>{g.beginPath();g.arc(X(x),Z(z),.2*sx,0,7);g.fill()};
    rect(-HL,-HW,HL,HW);g.beginPath();g.moveTo(X(0),Z(-HW));g.lineTo(X(0),Z(HW));g.stroke();
    arc(0,0,9.15,0,7);spot(0,0);
    for(const s of [-1,1]){
      rect(s*HL,-BOXZ,s*BOXX,BOXZ);rect(s*HL,-9.16,s*(HL-5.5),9.16);spot(s*(HL-11),0);
      const a=Math.acos(5.5/9.15); if(s>0)arc(s*(HL-11),0,9.15,Math.PI-a,Math.PI+a); else arc(s*(HL-11),0,9.15,-a,a);
      for(const t of [-1,1]){const cx=s*HL,cz=t*HW;const a0=s>0?(t>0?Math.PI:Math.PI/2):(t>0?-Math.PI/2:0);arc(cx,cz,1,a0,a0+Math.PI/2)}
    }
  });
  tex.anisotropy=renderer.capabilities.getMaxAnisotropy();
  const pitch=new THREE.Mesh(new THREE.PlaneGeometry(PL+2*M,PW+2*M),new THREE.MeshLambertMaterial({map:tex}));
  pitch.rotation.x=-Math.PI/2;scene.add(pitch);
  const apron=new THREE.Mesh(new THREE.PlaneGeometry(260,200),new THREE.MeshLambertMaterial({color:0x15301a}));
  apron.rotation.x=-Math.PI/2;apron.position.y=-.02;scene.add(apron);
})();

/* ---------- Goals ---------- */
(function buildGoals(){
  const white=new THREE.MeshLambertMaterial({color:0xffffff});
  const post=new THREE.CylinderGeometry(.07,.07,GH,10), bar=new THREE.CylinderGeometry(.07,.07,GHW*2+.14,10);
  const netMat=new THREE.LineBasicMaterial({color:0xdfe7f5,transparent:true,opacity:.32});
  for(const s of [-1,1]){
    for(const z of [-GHW,GHW]){const m=new THREE.Mesh(post,white);m.position.set(s*HL,GH/2,z);scene.add(m)}
    const b=new THREE.Mesh(bar,white);b.rotation.x=Math.PI/2;b.position.set(s*HL,GH,0);scene.add(b);
    const pts=[], D=2, bx=s*(HL+D);
    for(let z=-GHW;z<=GHW+.01;z+=.5){pts.push(bx,0,z,bx,GH*.85,z, s*HL,GH,z,bx,GH*.85,z)}
    for(let y=0;y<=GH*.85+.01;y+=.45){pts.push(bx,y,-GHW,bx,y,GHW)}
    for(const z of [-GHW,GHW]){for(let x=0;x<=D+.01;x+=.5){const yy=GH-(GH*.15)*(x/D);pts.push(s*(HL+x),0,z,s*(HL+x),yy,z)}
      for(let y=0;y<=GH;y+=.45){pts.push(s*HL,y,z,bx,Math.min(y,GH*.85),z)}}
    for(let x=0;x<=D+.01;x+=.5){pts.push(s*(HL+x),GH-(GH*.15)*(x/D),-GHW,s*(HL+x),GH-(GH*.15)*(x/D),GHW)}
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pts,3));
    scene.add(new THREE.LineSegments(g,netMat));
    const flagGeo=new THREE.CylinderGeometry(.03,.03,1.5,6);
    for(const t of [-1,1]){const f=new THREE.Mesh(flagGeo,white);f.position.set(s*HL,.75,t*HW);scene.add(f);
      const fl=new THREE.Mesh(new THREE.PlaneGeometry(.4,.28),new THREE.MeshBasicMaterial({color:0xffd23f,side:THREE.DoubleSide}));fl.position.set(s*HL+.2*-s,1.36,t*HW);scene.add(fl)}
  }
})();

/* ---------- Stadium, boards, crowd ---------- */
let crowd, crowdBase=[];
(function buildStadium(){
  const standMat=new THREE.MeshLambertMaterial({color:0x121a2c});
  const roofMat=new THREE.MeshLambertMaterial({color:0x0b1120});
  const boards=canvasTex(1024,64,(g,w,h)=>{g.fillStyle='#0d1530';g.fillRect(0,0,w,h);const words=['STRIKE 27','KICKWAVE','NOVA FUEL','HARBOR BANK','STRIKE 27','PITCHLINE'];
    g.font='800 38px "Arial Narrow",Impact,sans-serif';g.textBaseline='middle';let x=10;words.forEach((t,i)=>{g.fillStyle=i%2?'#ffd23f':'#2ee6c5';g.fillText(t,x,h/2+2);x+=g.measureText(t).width+44})});
  boards.wrapS=THREE.RepeatWrapping;
  const bMat=new THREE.MeshBasicMaterial({map:boards});
  const addBoard=(len,x,z,ry)=>{const t=boards.clone();t.needsUpdate=true;t.repeat.set(len/40,1);const m=new THREE.Mesh(new THREE.BoxGeometry(len,.9,.15),new THREE.MeshBasicMaterial({map:t}));m.position.set(x,.45,z);m.rotation.y=ry;scene.add(m)};
  addBoard(PL+10,0,-(HW+4),0);addBoard(PL+10,0,HW+4.5,Math.PI);
  for(const s of [-1,1]){addBoard(26,s*(HL+4.5),-20,s*Math.PI/2);addBoard(26,s*(HL+4.5),20,s*Math.PI/2)}
  // tiers
  const tier=(len,depth,x,z,ry,hasRoof=true)=>{const g=new THREE.Group();for(let i=0;i<4;i++){const m=new THREE.Mesh(new THREE.BoxGeometry(len,1.6,depth/4),standMat);m.position.set(0,.8+i*1.9,i*depth/4);g.add(m)}
    const roof=new THREE.Mesh(new THREE.BoxGeometry(len,.5,depth*.8),roofMat);roof.position.set(0,15,depth*.5);if(hasRoof)g.add(roof);g.position.set(x,0,z);g.rotation.y=ry;scene.add(g)};
  tier(PL+30,16,0,-(HW+8),Math.PI);tier(PL+30,16,0,HW+8,0,false);tier(PW+20,14,-(HL+8),0,-Math.PI/2);tier(PW+20,14,HL+8,0,Math.PI/2);
  // floodlights
  const towerMat=new THREE.MeshLambertMaterial({color:0x2a3248}), lampMat=new THREE.MeshBasicMaterial({color:0xfff4cc});
  for(const sx of [-1,1])for(const sz of [-1,1]){const t=new THREE.Mesh(new THREE.CylinderGeometry(.5,.8,34,8),towerMat);t.position.set(sx*(HL+20),17,sz*(HW+20));scene.add(t);
    const l=new THREE.Mesh(new THREE.BoxGeometry(6,3,.6),lampMat);l.position.set(sx*(HL+20),34,sz*(HW+20));l.lookAt(0,0,0);scene.add(l)}
  // crowd (one instanced draw call)
  const spots=[];
  const row=(len,step,fn)=>{for(let r=0;r<11;r++)for(let a=-len/2;a<=len/2;a+=step)if(Math.random()<.9)spots.push(fn(a+rand(-.15,.15),r))};
  row(PL+26,.95,(a,r)=>[a,1.9+r*.7,-(HW+8.6+r*1.0)]);row(PL+26,.95,(a,r)=>[a,1.9+r*.7,HW+8.6+r*1.0]);
  row(PW+16,.95,(a,r)=>[-(HL+8.6+r*.9),1.9+r*.7,a]);row(PW+16,.95,(a,r)=>[HL+8.6+r*.9,1.9+r*.7,a]);
  crowd=new THREE.InstancedMesh(new THREE.BoxGeometry(.5,.8,.4),new THREE.MeshLambertMaterial(),spots.length);
  const m=new THREE.Matrix4();spots.forEach((p,i)=>{m.makeTranslation(p[0],p[1],p[2]);crowd.setMatrixAt(i,m);crowdBase.push(p)});
  scene.add(crowd);
})();
function paintCrowd(){const c=new THREE.Color();const pal=[S.teams[0].kit,S.teams[0].kit,S.teams[1].kit,S.teams[1].kit,0xffffff,0x2a2f3a,0x404a60,0xd8d0c0];
  for(let i=0;i<crowd.count;i++){c.setHex(pal[(Math.random()*pal.length)|0]);c.multiplyScalar(rand(.55,1));crowd.setColorAt(i,c)}crowd.instanceColor.needsUpdate=true}
let crowdJump=0;
function animateCrowd(dt){if(crowdJump<=0)return;crowdJump-=dt;const m=new THREE.Matrix4();const t=performance.now()/1000;
  for(let i=0;i<crowd.count;i++){const p=crowdBase[i];const j=crowdJump>0?Math.max(0,Math.sin(t*12+i))*0.35:0;m.makeTranslation(p[0],p[1]+j,p[2]);crowd.setMatrixAt(i,m)}crowd.instanceMatrix.needsUpdate=true}

/* ---------- Ball ---------- */
const ballMesh=new THREE.Mesh(new THREE.SphereGeometry(BR,20,14),new THREE.MeshLambertMaterial({map:canvasTex(256,128,(g,w,h)=>{
  g.fillStyle='#f7f8fb';g.fillRect(0,0,w,h);g.fillStyle='#14203e';for(let i=0;i<10;i++){const x=(i%5)*w/5+(i>4?w/10:0),y=i>4?h*.7:h*.3;g.beginPath();for(let k=0;k<5;k++){const a=k/5*Math.PI*2;g.lineTo(x+Math.cos(a)*13,y+Math.sin(a)*13)}g.fill()}
  g.fillStyle='#ffd23f';g.fillRect(0,h*.48,w,h*.04);})}));
scene.add(ballMesh);

/* ---------- Shadows (instanced blobs) ---------- */
const shadowTex=canvasTex(64,64,(g)=>{const r=g.createRadialGradient(32,32,2,32,32,32);r.addColorStop(0,'rgba(0,0,0,.55)');r.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=r;g.fillRect(0,0,64,64)});
const shadows=new THREE.InstancedMesh(new THREE.PlaneGeometry(1.3,1.3).rotateX(-Math.PI/2),new THREE.MeshBasicMaterial({map:shadowTex,transparent:true,depthWrite:false}),26);
scene.add(shadows);

/* ---------- Control marker ---------- */
const marker=new THREE.Group();
const ring=new THREE.Mesh(new THREE.RingGeometry(.62,.82,36).rotateX(-Math.PI/2),new THREE.MeshBasicMaterial({color:0x2ee6c5,transparent:true,opacity:.95,depthWrite:false}));
ring.position.y=.03;marker.add(ring);
const arrow=new THREE.Mesh(new THREE.ConeGeometry(.22,.4,3),new THREE.MeshBasicMaterial({color:0x2ee6c5}));arrow.rotation.x=Math.PI;marker.add(arrow);
scene.add(marker);marker.visible=false;
const recvRing=new THREE.Mesh(new THREE.RingGeometry(.5,.62,28).rotateX(-Math.PI/2),new THREE.MeshBasicMaterial({color:0xffd23f,transparent:true,opacity:.8,depthWrite:false}));
recvRing.position.y=.03;scene.add(recvRing);recvRing.visible=false;
