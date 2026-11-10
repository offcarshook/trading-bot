/* ===== Players (procedural rigged models) ===== */
const GEO={torso:new THREE.BoxGeometry(.48,.62,.28),shorts:new THREE.BoxGeometry(.46,.26,.3),
  leg:new THREE.BoxGeometry(.16,.72,.17).translate(0,-.36,0),arm:new THREE.BoxGeometry(.13,.58,.13).translate(0,-.29,0),
  head:new THREE.SphereGeometry(.15,12,10),hair:new THREE.SphereGeometry(.158,12,8,0,Math.PI*2,0,Math.PI*.5)};
const SKIN=[0xf1c9a5,0xd9a47a,0xa8714a,0x6e4428].map(c=>new THREE.MeshLambertMaterial({color:c}));
const HAIR=[0x1b120c,0x3b2414,0x8a5a2b,0xd8c18a,0x0b0b0b].map(c=>new THREE.MeshLambertMaterial({color:c}));
const KIT=[0,1].map(()=>({kit:new THREE.MeshLambertMaterial(),shorts:new THREE.MeshLambertMaterial(),socks:new THREE.MeshLambertMaterial(),gk:new THREE.MeshLambertMaterial(),gks:new THREE.MeshLambertMaterial({color:0x1a1a1a})}));

function buildModel(team,gk,skin,hair,mats){
  const K=mats||KIT[team];const root=new THREE.Group(), rig=new THREE.Group();root.add(rig);
  const torso=new THREE.Mesh(GEO.torso,gk?K.gk:K.kit);torso.position.y=1.13;
  const shorts=new THREE.Mesh(GEO.shorts,gk?K.gks:K.shorts);shorts.position.y=.78;
  const head=new THREE.Mesh(GEO.head,skin);head.position.y=1.6;
  const hr=new THREE.Mesh(GEO.hair,hair);hr.position.y=1.62;
  const hip=(x)=>{const g=new THREE.Group();g.position.set(x,.72,0);g.add(new THREE.Mesh(GEO.leg,gk?K.gk:K.socks));rig.add(g);return g};
  const sh=(x)=>{const g=new THREE.Group();g.position.set(x,1.4,0);g.add(new THREE.Mesh(GEO.arm,gk?K.gk:K.kit));rig.add(g);return g};
  rig.add(torso,shorts,head,hr);
  const m={root,rig,head,hairM:hr,hipL:hip(-.12),hipR:hip(.12),shL:sh(-.31),shR:sh(.31)};
  root.scale.setScalar(PSCALE);scene.add(root);return m;
}
for(let t=0;t<2;t++)for(let i=0;i<11;i++){
  const f=FORM[i];
  const p={team:t,i,role:f[2],num:f[3],gk:i===0,hx:f[0],hz:f[1],x:0,z:0,vx:0,vz:0,spd:0,face:t?Math.PI:0,phase:rand(0,6),
    stam:1,cool:0,stun:0,kickT:0,slideT:0,slideHit:false,tackleT:0,skillCD:0,skillT:0,diveT:0,diveDir:0,celebT:0,holdT:0,jumpT:0,
    aiT:0,possT:0,tx:0,tz:0,sx:0,sz:0,run:false,recv:false,mustPass:false,throwT:0,hands:false,wall:false,save:null,shotSeen:-1,supT:0,stats:null,name:'',jog:5.4,sprint:8};
  p.skin0=p.skin=(Math.random()*4)|0;p.hair0=p.hair=(Math.random()*5)|0;p.fit=1;p.yc=0;p.off=false;p.offside=false;
  p.mesh=buildModel(t,p.gk,SKIN[p.skin],HAIR[p.hair]);
  players.push(p);TP[t].push(p);
}
function colorDist(a,b){const A=new THREE.Color(a),B=new THREE.Color(b);return hyp(A.r-B.r,A.g-B.g,A.b-B.b)}
function setupTeams(){
  for(let t=0;t<2;t++){
    const T=S.teams[t];let kit=T.kit,shorts=T.shorts,socks=T.socks;
    if(t===1&&colorDist(T.kit,S.teams[0].kit)<.45){kit=T.away;shorts=T.awayShorts;socks=T.away}
    KIT[t].kit.color.setHex(kit);KIT[t].shorts.color.setHex(shorts);KIT[t].socks.color.setHex(socks);KIT[t].gk.color.setHex(T.gk);
    S.kitColor=S.kitColor||[];S.kitColor[t]=kit;
    const rnd=mulberry(TEAMS.indexOf(T)*977+13);
    ROSTER[t].forEach(p=>{
      const r=T.rating+(rnd()*10-5), b=k=>clamp(Math.round(r+k+(rnd()*8-4)),45,96);
      p.stats=genStats(p.role,b);p.num=FORM[p.i][3];p.skin=p.skin0;p.hair=p.hair0;p.mesh.head.material=SKIN[p.skin];p.mesh.hairM.material=HAIR[p.hair];
      p.jog=4.7+p.stats.pace/100*1.1;p.sprint=6.7+p.stats.pace/100*2.1;
      p.name=INIT[(rnd()*INIT.length)|0]+'. '+SUR[(rnd()*SUR.length)|0];
      p.fit=1;p.stam=1;p.yc=0;p.off=false;p.pendingOff=false;p.offside=false;p.mesh.root.visible=true;
    });
    makeBench(t,T,rnd);
  }
  refKit();
}
