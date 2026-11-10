/* ===== Player model: procedural skinned body, hair shells, painted kit and face textures =====
   Everything is generated in code (no downloaded models). One body mesh is shared by every player and
   officials; each character owns a 17-bone skeleton, a hair mesh and one painted texture. */
const ARM_X=.207,FOOT_TOE=.225,FOOT_HEEL=.092;
const BONE_DEF=[ // name, parent, rest position in metres for a 1.80 m figure
  ['hips',-1,0,.93,0],['spine',0,0,1.06,0],['chest',1,0,1.24,0],['neck',2,0,1.50,0],['head',3,0,1.575,.005],
  ['armL',2,ARM_X,1.447,0],['foreL',5,ARM_X,1.172,0],['handL',6,ARM_X,.918,0],
  ['armR',2,-ARM_X,1.447,0],['foreR',8,-ARM_X,1.172,0],['handR',9,-ARM_X,.918,0],
  ['thighL',0,.092,.895,0],['shinL',11,.088,.495,0],['footL',12,.084,.085,0],
  ['thighR',0,-.092,.895,0],['shinR',14,-.088,.495,0],['footR',15,-.084,.085,0]];
const BI={};BONE_DEF.forEach((b,i)=>BI[b[0]]=i);
const LEG1=.40,LEG2=.41,ANKLE=.085,HIP_Y=.895,HEAD_TOP=1.818,HEAD_CZ=.005;
// texture atlas regions on a 512-unit sheet: x, y, w, h
const ATLAS={shirt:[0,0,512,224],sleeve:[0,224,128,64],shorts:[128,224,256,96],sock:[384,224,128,96],arm:[0,288,64,32],skin:[64,288,64,32],
  head:[0,320,256,192],boot:[256,320,128,96],hand:[384,320,64,64]};
const HEAD_R=[[1.577,.040,.054,.042],[1.592,.053,.079,.052],[1.615,.066,.092,.063],[1.645,.072,.099,.075],[1.675,.076,.101,.086],
  [1.705,.0785,.101,.094],[1.735,.079,.100,.099],[1.762,.077,.096,.101],[1.787,.069,.083,.096],[1.805,.052,.062,.077],[1.815,.027,.033,.044]];
const PI=Math.PI,lerp=(a,b,t)=>a+(b-a)*t,smooth=(a,b,x)=>{const t=clamp((x-a)/(b-a),0,1);return t*t*(3-2*t)};
// point on an ellipse-like cross-section: a = angle (0 = front), k < 1 squares the shape off
function ell(a,rx,rf,rb,k){const sn=Math.sin(a),cs=Math.cos(a);
  if(k&&k!==1)return[rx*Math.sign(sn)*Math.pow(Math.abs(sn),k),(cs>=0?rf:rb)*Math.sign(cs)*Math.pow(Math.abs(cs),k)];
  return[rx*sn,(cs>=0?rf:rb)*cs]}
function headSurf(y,a){const R=HEAD_R;let i=0;while(i<R.length-2&&y>R[i+1][0])i++;
  const A=R[i],B=R[i+1],t=clamp((y-A[0])/(B[0]-A[0]),0,1),e=ell(a,lerp(A[1],B[1],t),lerp(A[2],B[2],t),lerp(A[3],B[3],t),.92);return[e[0],HEAD_CZ+e[1]]}
const hairline=(a,st)=>lerp(st.front??1.768,st.back??1.635,(1-Math.cos(a))/2)-(st.side||0)*Math.sin(a)**2;

function weldNormals(g,pos,grp){
  g.computeVertexNormals();const n=g.attributes.normal,acc=new Map();
  for(let i=0;i<pos.length/3;i++){const k=(grp?grp[i]:0)+'|'+Math.round(pos[i*3]*2e3)+','+Math.round(pos[i*3+1]*2e3)+','+Math.round(pos[i*3+2]*2e3);
    let a=acc.get(k);if(!a)acc.set(k,a=[0,0,0,[]]);a[0]+=n.getX(i);a[1]+=n.getY(i);a[2]+=n.getZ(i);a[3].push(i)}
  for(const a of acc.values()){const l=hyp(a[0],a[1],a[2])||1;for(const i of a[3])n.setXYZ(i,a[0]/l,a[1]/l,a[2]/l)}
}

// small face details pushed out of (or into) the head surface so the painted face sits on real shape
function faceRelief(y,a){a=Math.atan2(Math.sin(a),Math.cos(a));const g=(x,c,w)=>Math.exp(-(((x-c)/w)**2));
  const N=y<1.662?0:y<1.684?smooth(1.662,1.684,y):y<1.74?lerp(1,.22,(y-1.684)/.056):Math.max(0,.22*(1-(y-1.74)/.02));
  return .025*g(a,0,.2)*N+.004*g(y,1.748,.012)*g(a,0,.75)+.0035*g(y,1.643,.011)*g(a,0,.3)+.004*g(y,1.598,.013)*g(a,0,.32)
    -.0045*g(y,1.731,.011)*(g(a,.36,.17)+g(a,-.36,.17))}
const BODY_GEO=(()=>{
  const pos=[],uv=[],si=[],sw=[],idx=[],grp=[];let part=0;
  const vert=(x,y,z,u,v,w)=>{const e=Object.entries(w).filter(q=>q[1]>0).sort((a,b)=>b[1]-a[1]).slice(0,4);let s=0;e.forEach(q=>s+=q[1]);
    const I=[0,0,0,0],Wt=[0,0,0,0];e.forEach((q,k)=>{I[k]=BI[q[0]];Wt[k]=q[1]/s});
    pos.push(x,y,z);uv.push(u,v);si.push(...I);sw.push(...Wt);grp.push(part);return pos.length/3-1};
  // stitch a stack of rings into a tube; winding is detected so parts can be listed in any direction
  const skin=(rings,reg,o={})=>{part++;
    const[ax,ay,aw,ah]=ATLAS[reg],u0=o.u0??0,u1=o.u1??1,n=rings[0].pts.length;
    const U=t=>(ax+aw*(o.flat?.5:u0+(u1-u0)*t))/512,V=v=>1-(ay+ah*(o.flat?.5:v))/512;
    const ids=rings.map(r=>r.pts.map((p,i)=>vert(p[0],p[1],p[2],U(r.us[i]),V(r.v),r.w)));
    const a=rings[0].pts[0],b=rings[0].pts[1],c=rings[1].pts[0],cen=rings[0].c;
    const nx=(b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]),ny=(b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),nz=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
    const out=nx*(a[0]-cen[0])+ny*(a[1]-cen[1])+nz*(a[2]-cen[2])>0;
    for(let j=0;j<rings.length-1;j++)for(let i=0;i<n-1;i++){const A=ids[j][i],B=ids[j][i+1],C=ids[j+1][i],D=ids[j+1][i+1];
      if(out)idx.push(A,B,C,B,D,C);else idx.push(A,C,B,B,C,D)}
    const cap=(k,first)=>{const r=rings[k],cv=vert(r.c[0],r.c[1],r.c[2],U(.5),V(r.v),r.w);
      for(let i=0;i<n-1;i++){const A=ids[k][i],B=ids[k][i+1];if(out===first)idx.push(A,cv,B);else idx.push(A,B,cv)}};
    if(o.cap0)cap(0,true);if(o.cap1)cap(rings.length-1,false)};
  // horizontal ring (a slice of a standing body part)
  const vr=(cx,y,cz,rx,rf,rb,n,w,v,o={})=>{const pts=[],us=[],s0=o.seam??-PI/2,m=o.mir?-1:1;
    for(let i=0;i<=n;i++){const t=i/n,e=ell(s0+t*PI*2*m,rx,rf,rb,o.sq);pts.push([cx+e[0],y,cz+e[1]]);us.push(t)}
    return{pts,us,c:[cx,y,cz],v,w}};
  // vertical ring (a slice of a boot), flat-ish underneath
  const hr=(cx,z,rx,ry,n,w,v)=>{const pts=[],us=[];
    for(let i=0;i<=n;i++){const t=i/n,a=PI+t*PI*2,cs=Math.cos(a);pts.push([cx+rx*Math.sin(a),ry+ry*(cs<0?-Math.pow(-cs,.7):cs),z]);us.push(t)}
    return{pts,us,c:[cx,ry,z],v,w}};
  // rounded lump (ears)
  const orb=(cx,cy,cz,rx,ry,rz,w)=>{const R=[];for(let j=0;j<=5;j++){const f=j/5*PI,r=Math.max(.06,Math.sin(f));R.push(vr(cx,cy-ry*Math.cos(f),cz,rx*r,rz*r,rz*r,8,w,.5))}skin(R,'skin',{flat:true,cap0:true,cap1:true})};

  // shirt (torso): loose hem, broad shoulder line
  const wTor=y=>y<.97?{hips:1}:y<1.03?{hips:(1.03-y)/.06,spine:(y-.97)/.06}:y<1.16?{spine:1}:y<1.26?{spine:(1.26-y)/.1,chest:(y-1.16)/.1}:y<1.5?{chest:1}:{chest:.6,neck:.4};
  skin([[.885,.186,.126,.132],[.95,.178,.118,.126],[1.03,.164,.108,.116],[1.11,.160,.108,.114],[1.19,.174,.118,.122],[1.28,.192,.132,.130],
        [1.36,.202,.138,.134],[1.425,.204,.130,.132],[1.47,.192,.110,.122],[1.505,.130,.084,.100],[1.535,.070,.064,.072]]
    .map(r=>vr(0,r[0],.004,r[1],r[2],r[3],24,wTor(r[0]),1-(r[0]-.885)/.65,{sq:.82})),'shirt',{cap0:true,cap1:true});
  // shorts: pelvis block tucked inside one tube per leg
  skin([[.775,.10,.07,.08],[.82,.152,.098,.112],[.86,.172,.114,.128],[.935,.172,.114,.124]]
    .map(r=>vr(0,r[0],0,r[1],r[2],r[3],20,{hips:1},(.935-r[0])/.16*.5,{sq:.85})),'shorts',{cap0:true});
  for(const s of [1,-1]){
    const th=s>0?'thighL':'thighR',sh=s>0?'shinL':'shinR',ft=s>0?'footL':'footR',ar=s>0?'armL':'armR',fo=s>0?'foreL':'foreR',hd=s>0?'handL':'handR';
    const lg={seam:-s*PI/2,mir:s<0},ax=s*ARM_X;
    skin([[.885,.090,.110,.120,{hips:.5,[th]:.5}],[.80,.102,.112,.122,{[th]:1}],[.70,.108,.114,.116,{[th]:1}],[.62,.112,.118,.118,{[th]:1}]]
      .map(r=>vr(s*.096,r[0],0,r[1],r[2],r[3],16,r[4],.5+(.885-r[0])/.265*.5,lg)),'shorts',{cap1:true,u0:s>0?0:.5,u1:s>0?.5:1});
    // thigh and knee (skin)
    skin([[.80,.096,.094,.102,.106,{[th]:1}],[.70,.094,.088,.098,.098,{[th]:1}],[.62,.092,.080,.090,.088,{[th]:1}],[.56,.090,.069,.077,.075,{[th]:1}],
          [.52,.089,.062,.070,.066,{[th]:.75,[sh]:.25}],[.495,.089,.060,.070,.062,{[th]:.5,[sh]:.5}],[.465,.088,.058,.064,.062,{[th]:.25,[sh]:.75}],[.44,.088,.059,.062,.066,{[sh]:1}]]
      .map(r=>vr(s*r[1],r[0],0,r[2],r[3],r[4],14,r[5],.5,lg)),'skin',{flat:true,cap0:true});
    // sock over the shin and calf
    skin([[.445,.088,.062,.065,.070],[.40,.087,.064,.064,.080],[.33,.086,.064,.062,.086],[.25,.085,.055,.055,.070],[.17,.084,.046,.048,.055],[.10,.084,.043,.046,.048],[.055,.084,.044,.048,.048]]
      .map(r=>vr(s*r[1],r[0],0,r[2],r[3],r[4],14,{[sh]:1},(.445-r[0])/.39,lg)),'sock');
    // boot
    skin([[-FOOT_HEEL,.022,.024],[-.076,.037,.044],[-.038,.044,.060],[0,.046,.064],[.045,.048,.054],[.10,.051,.041],[.155,.050,.033],[.198,.041,.026],[FOOT_TOE,.022,.015]]
      .map(r=>hr(s*.084,r[0],r[1],r[2],12,{[ft]:1},(r[0]+FOOT_HEEL)/(FOOT_TOE+FOOT_HEEL))),'boot',{cap0:true,cap1:true});
    // sleeve with a rounded shoulder, then arm, then hand
    skin([[1.508,.022],[1.492,.046],[1.464,.062],[1.42,.064],[1.37,.061],[1.322,.062]]
      .map(r=>vr(ax,r[0],0,r[1],r[1]*1.05,r[1],12,{[ar]:1},(1.508-r[0])/.186,lg)),'sleeve',{cap0:true,cap1:true});
    skin([[1.345,.052,{[ar]:1}],[1.28,.052,{[ar]:1}],[1.22,.047,{[ar]:1}],[1.19,.044,{[ar]:.7,[fo]:.3}],[1.172,.043,{[ar]:.5,[fo]:.5}],[1.15,.044,{[ar]:.3,[fo]:.7}],
          [1.10,.047,{[fo]:1}],[1.02,.040,{[fo]:1}],[.95,.033,{[fo]:1}],[.925,.031,{[fo]:1}]]
      .map(r=>vr(ax,r[0],0,r[1]*.96,r[1]*1.05,r[1]*1.02,12,r[2],.5)),'arm',{flat:true});
    skin([[.932,.026,.030,0,{[fo]:.5,[hd]:.5}],[.90,.020,.040,.004,{[hd]:1}],[.86,.019,.046,.008,{[hd]:1}],[.81,.017,.042,.013,{[hd]:1}],[.765,.013,.030,.018,{[hd]:1}],[.74,.007,.016,.02,{[hd]:1}]]
      .map(r=>vr(ax,r[0],r[3],r[1],r[2],r[2],10,r[4],.5)),'hand',{flat:true,cap1:true});
    orb(s*.079,1.702,-.006,.011,.028,.018,{head:1});   // ear
  }
  // neck and head (the head carries a nose, brow, lips and chin)
  skin([[1.50,.068,{chest:.6,neck:.4}],[1.55,.061,{neck:1}],[1.605,.058,{neck:.5,head:.5}]]
    .map(r=>vr(0,r[0],-.004,r[1],r[1]*1.04,r[1]*1.02,14,r[2],.5)),'skin',{flat:true});
  const HN=32,headRing=y=>{const pts=[],us=[];for(let i=0;i<=HN;i++){const t=i/HN,a=PI+t*PI*2,q=headSurf(y,a);pts.push([q[0],y,q[1]+faceRelief(y,a)]);us.push(t)}
    return{pts,us,c:[0,y,HEAD_CZ],v:(HEAD_TOP-y)/(HEAD_TOP-1.577),w:{head:1}}};
  skin([1.577,1.588,1.60,1.615,1.63,1.645,1.658,1.67,1.682,1.694,1.706,1.72,1.735,1.75,1.765,1.78,1.793,1.805,1.8125].map(headRing),'head',{cap0:true,cap1:true});

  const g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
  g.setAttribute('skinIndex',new THREE.Uint16BufferAttribute(si,4));g.setAttribute('skinWeight',new THREE.Float32BufferAttribute(sw,4));
  g.setIndex(idx);weldNormals(g,pos,grp);
  g.boundingSphere=new THREE.Sphere(new THREE.Vector3(0,.95,0),1.8);
  return g;
})();

/* ---------- hair: a shell that follows the head shape ---------- */
const hnoise=(a,t,f)=>Math.sin(a*f*1.3+t*7.1)*Math.sin(a*f*.7-t*11.3+1.7);
const HAIR_STYLES=[
  {id:'short',k:(a,t)=>.085+.035*t},
  {id:'crop',front:1.772,k:(a,t)=>.03+.16*Math.pow(t,1.5)+.05*Math.max(0,Math.cos(a))*t},
  {id:'curly',k:(a,t)=>.15+.045*hnoise(a,t,9)},
  {id:'afro',front:1.76,back:1.62,k:(a,t)=>.34+.05*hnoise(a,t,7)},
  {id:'long',back:1.50,k:(a,t)=>.10+.03*t+.05*((1-Math.cos(a))/2)},
  {id:'buzz',k:()=>.03},
  {id:'bald',none:true},
  {id:'bun',k:(a,t)=>.07+.02*t,bun:true},
];
const HAIR_COLS=[0x15100c,0x2b1a10,0x4a2f1b,0x7a5230,0xc9a45c,0xa8552a,0x8a8a8a];
const HAIR_MATS=HAIR_COLS.map(c=>new THREE.MeshStandardMaterial({color:c,roughness:.92,metalness:0}));
const HAIR_GEO=HAIR_STYLES.map(st=>{
  if(st.none)return null;
  const N=22,M=7,pos=[],idx=[],C=[0,1.70,HEAD_CZ];
  for(let j=0;j<=M;j++){const t=j/M;for(let i=0;i<=N;i++){const a=i/N*PI*2,h0=hairline(a,st),y=h0+(HEAD_TOP+.001-h0)*Math.sin(t*PI/2);
    let x=0,z=HEAD_CZ;if(j<M){const p=headSurf(Math.min(y,1.8149),a);x=p[0];z=p[1]}
    const k=.012+st.k(a,t)*smooth(0,.2,t);pos.push(C[0]+(x-C[0])*(1+k),C[1]+(y-C[1])*(1+k),C[2]+(z-C[2])*(1+k))}}
  for(let j=0;j<M;j++)for(let i=0;i<N;i++){const A=j*(N+1)+i,B=A+1,Cc=A+N+1,D=Cc+1;idx.push(A,B,Cc,B,D,Cc)}
  if(st.bun){const b=pos.length/3,c=[0,1.80,-.085],r=.04;const q=[[r,0,0],[-r,0,0],[0,r,0],[0,-r,0],[0,0,r],[0,0,-r]];
    q.forEach(v=>pos.push(c[0]+v[0],c[1]+v[1],c[2]+v[2]));[[0,2,4],[2,1,4],[1,3,4],[3,0,4],[2,0,5],[1,2,5],[3,1,5],[0,3,5]].forEach(f=>idx.push(b+f[0],b+f[1],b+f[2]))}
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));g.setIndex(idx);weldNormals(g,pos,null);return g;
});

/* ---------- one character = bones + shared body mesh + hair + texture ---------- */
function buildCharacter(){
  const root=new THREE.Group(),bones=BONE_DEF.map(b=>{const o=new THREE.Bone();o.name=b[0];return o}),B={};
  BONE_DEF.forEach((b,i)=>{const p=b[1];B[b[0]]=bones[i];
    if(p>=0){bones[p].add(bones[i]);bones[i].position.set(b[2]-BONE_DEF[p][2],b[3]-BONE_DEF[p][3],b[4]-BONE_DEF[p][4])}else bones[i].position.set(b[2],b[3],b[4])});
  const cv=document.createElement('canvas');cv.width=cv.height=GFX.tex;
  const tex=new THREE.CanvasTexture(cv);tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=4;
  const mesh=new THREE.SkinnedMesh(BODY_GEO,new THREE.MeshStandardMaterial({map:tex,roughness:.84,metalness:0}));
  mesh.add(bones[0]);root.add(mesh);root.updateMatrixWorld(true);mesh.bind(new THREE.Skeleton(bones));
  mesh.frustumCulled=false;mesh.castShadow=true;
  const hair=new THREE.Mesh(HAIR_GEO[0],HAIR_MATS[0]);hair.position.set(0,-1.575,-HEAD_CZ);hair.castShadow=true;hair.frustumCulled=false;B.head.add(hair);
  scene.add(root);
  return{root,mesh,B,cv,tex,hair,P:new Float32Array(NCH),seed:Math.random()*100,scale:PSCALE,snap:true,diveMax:0,jumpMax:0};
}

/* ---------- looks: who a player is, visually ---------- */
const SKIN_TONES=[0xf3d2b8,0xe6b996,0xcf9d78,0xa8724c,0x7d5235,0x573624];
const BOOT_COLS=[0x111111,0xf2f2f2,0xd7ff3a,0xff6a1f,0x1f8fff,0xff3d86,0x17c3a2,0xe6c229];
const EYE_COLS=['#3b2a1c','#2a1c12','#4a6a8c','#4c6b46','#5a4630'];
const FONT='"Big Shoulders Display","Arial Narrow",Impact,sans-serif';
const css=c=>'#'+(c>>>0).toString(16).padStart(6,'0');
const shade=(c,f)=>{const k=new THREE.Color(c);if(f<0)k.multiplyScalar(1+f);else k.lerp(new THREE.Color(0xffffff),f);return'#'+k.getHexString()};
const lumOf=c=>{const k=new THREE.Color(c);return .299*k.r+.587*k.g+.114*k.b};
function randomLook(rnd,role){
  const skin=(rnd()*SKIN_TONES.length)|0,dark=skin>=3;
  const hairCol=dark?(rnd()<.85?0:1):(rnd()*HAIR_COLS.length*.86)|0;
  const r=rnd(),hairStyle=dark?(r<.3?5:r<.5?2:r<.62?3:r<.8?1:r<.9?6:0):(r<.34?0:r<.62?1:r<.72?4:r<.8?5:r<.87?2:r<.93?7:6);
  const tall=role==='GK'?.05:role==='CB'?.035:role==='ST'?.01:/W$/.test(role)?-.03:0;
  return{skin,hairCol,hairStyle,beard:rnd()<.42?0:rnd()<.6?1:rnd()<.8?2:3,eye:(rnd()*EYE_COLS.length)|0,boot:(rnd()*BOOT_COLS.length)|0,
    h:1+tall+(rnd()-.5)*.07,w:1+(role==='CB'||role==='GK'?.04:/W$/.test(role)?-.03:0)+(rnd()-.5)*.08,foot:rnd()<.22?1:-1};
}
// kit designs: what each club wears (original designs)
const KIT_STYLE={HBW:{pattern:'panel',alt:0xffffff,trim:0xffffff},CPV:{pattern:'pin',alt:0x1c1c1c,trim:0x1c1c1c},NTL:{pattern:'band',alt:0x15203a,trim:0x15203a},
  KES:{pattern:'stripes',alt:0xf6d33c,trim:0xf6d33c},IRB:{pattern:'halves',alt:0xf0b72f,trim:0xf0b72f},SOL:{pattern:'sash',alt:0x3dc2f0,trim:0x3dc2f0}};
function kitFor(T,away,gk){
  const st=KIT_STYLE[T.code]||{pattern:'solid',alt:T.shorts,trim:T.shorts};
  if(gk){const b=T.gk;return{base:b,alt:b,trim:0x111111,pattern:'gk',shorts:0x151515,socks:b,num:lumOf(b)>.55?0x111111:0xffffff,gk:true,glove:0xf4f4f4}}
  const base=away?T.away:T.kit,alt=away?T.awayShorts:st.alt,num=lumOf(base)>.55?(lumOf(alt)<.4?alt:0x111111):(lumOf(alt)>.7?alt:0xffffff);
  return{base,alt,trim:away?T.awayShorts:st.trim,pattern:away?'panel':st.pattern,shorts:away?T.awayShorts:T.shorts,socks:away?T.away:T.socks,num};
}

/* ---------- painting the texture ---------- */
function paintLook(ch,look,kit,info){
  const cv=ch.cv;if(cv.width!==GFX.tex){cv.width=cv.height=GFX.tex}
  const S=cv.width/512,g=cv.getContext('2d');g.setTransform(S,0,0,S,0,0);g.clearRect(0,0,512,512);
  const skinC=SKIN_TONES[look.skin],skin=css(skinC),hairC=HAIR_COLS[look.hairCol],hair=css(hairC),st=HAIR_STYLES[look.hairStyle];
  const base=css(kit.base),alt=css(kit.alt),trim=css(kit.trim),numC=css(kit.num),patterned=['stripes','hoops','halves','pin','sash'].includes(kit.pattern);
  const R=(name,fn)=>{const a=ATLAS[name];g.save();g.beginPath();g.rect(a[0],a[1],a[2],a[3]);g.clip();g.translate(a[0],a[1]);fn(a[2],a[3]);g.restore()};
  const text=(t,x,y,size,col,sx=1,stroke)=>{g.save();g.translate(x,y);g.scale(sx,1);g.font=`900 ${size}px ${FONT}`;g.textAlign='center';g.textBaseline='middle';
    if(stroke){g.lineWidth=size*.09;g.strokeStyle=stroke;g.lineJoin='round';g.strokeText(t,0,0)}g.fillStyle=col;g.fillText(t,0,0);g.restore()};
  const vgrad=(h,a,b)=>{const q=g.createLinearGradient(0,0,0,h);q.addColorStop(0,a);q.addColorStop(1,b);return q};

  R('shirt',(w,h)=>{
    g.fillStyle=base;g.fillRect(0,0,w,h);g.fillStyle=alt;const P=kit.pattern;
    if(P==='stripes')for(let k=-3;k<8;k++)g.fillRect(128+k*51.2-12.8,0,25.6,h);
    else if(P==='hoops')for(let y=26;y<h;y+=40)g.fillRect(0,y,w,20);
    else if(P==='pin')for(let k=-12;k<32;k++)g.fillRect(128+k*12.8-1,0,2,h);
    else if(P==='band'){g.fillRect(0,62,w,40);g.fillStyle=shade(kit.alt,.35);g.fillRect(0,58,w,4);g.fillRect(0,102,w,4)}
    else if(P==='halves')g.fillRect(128,0,256,h);
    else if(P==='sash'){g.beginPath();g.moveTo(40,12);g.lineTo(92,12);g.lineTo(222,h);g.lineTo(170,h);g.closePath();g.fill()}
    else if(P==='panel'){g.fillRect(238,0,36,h);g.fillRect(0,0,18,h);g.fillRect(494,0,18,h)}
    else if(P==='gk'){g.fillStyle=shade(kit.base,-.22);for(let k=0;k<9;k++){g.beginPath();g.moveTo(k*64-20,0);g.lineTo(k*64+12,0);g.lineTo(k*64+52,h);g.lineTo(k*64+20,h);g.closePath();g.fill()}}
    g.fillStyle=vgrad(h,'rgba(255,255,255,.08)','rgba(0,0,0,.18)');g.fillRect(0,0,w,h);
    for(const cx of [0,256,512]){const q=g.createLinearGradient(cx-36,0,cx+36,0);q.addColorStop(0,'rgba(0,0,0,0)');q.addColorStop(.5,'rgba(0,0,0,.16)');q.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=q;g.fillRect(cx-36,0,72,h)}
    g.strokeStyle='rgba(0,0,0,.07)';g.lineWidth=3;g.lineCap='round';
    for(let i=0;i<8;i++){const x=30+i*64+(i*37%23);g.beginPath();g.moveTo(x,118+(i*13%20));g.quadraticCurveTo(x+16,165,x-8,h);g.stroke()}
    g.fillStyle=trim;g.fillRect(0,0,w,10);g.beginPath();g.moveTo(106,0);g.lineTo(128,30);g.lineTo(150,0);g.closePath();g.fill();
    g.fillStyle=skin;g.beginPath();g.moveTo(114,0);g.lineTo(128,19);g.lineTo(142,0);g.closePath();g.fill();
    g.fillStyle=trim;g.fillRect(0,h-5,w,5);
    if(info.ref){g.fillStyle='rgba(255,255,255,.9)';g.fillRect(150,58,26,20);g.fillStyle='#111';g.fillRect(154,62,18,3);return}
    // crest on the left chest, small number on the right
    g.save();g.translate(168,70);g.scale(1.38,1);g.beginPath();g.moveTo(-9,-12);g.lineTo(9,-12);g.lineTo(9,3);g.quadraticCurveTo(9,11,0,15);g.quadraticCurveTo(-9,11,-9,3);g.closePath();
    g.fillStyle=lumOf(kit.base)>.5?alt:'#ffffff';g.fill();g.lineWidth=1.6;g.strokeStyle=numC;g.stroke();g.restore();
    text(info.crest||'S',168,71,15,lumOf(kit.base)>.5?'#ffffff':base,1.38);
    text(String(info.num),90,72,30,numC,1.38,patterned?base:null);
    // back: name and number (a plain panel behind them on patterned shirts)
    if(patterned){g.fillStyle=base;g.globalAlpha=.94;g.beginPath();g.roundRect(384-84,34,168,150,10);g.fill();g.globalAlpha=1}
    const nm=String(info.name||'').split(' ').pop().toUpperCase();
    text(nm,384,56,nm.length>8?20:24,numC,1.38);
    text(String(info.num),384,126,104,numC,1.38,lumOf(kit.num)>.5?'rgba(0,0,0,.35)':'rgba(255,255,255,.35)');
  });
  R('sleeve',(w,h)=>{g.fillStyle=kit.pattern==='halves'?base:base;g.fillRect(0,0,w,h);if(kit.pattern==='panel'){g.fillStyle=alt;g.fillRect(56,0,16,h)}
    g.fillStyle=vgrad(h,'rgba(255,255,255,.1)','rgba(0,0,0,.14)');g.fillRect(0,0,w,h);g.fillStyle=trim;g.fillRect(0,h-10,w,10)});
  R('shorts',(w,h)=>{const sc=kit.shorts,stc=lumOf(sc)>.5?css(kit.base):(lumOf(kit.trim)>.35?trim:'#ffffff');
    g.fillStyle=css(sc);g.fillRect(0,0,w,h);g.fillStyle=stc;
    g.fillRect(0,0,6,48);g.fillRect(250,0,6,48);g.fillRect(122,0,12,48);g.fillRect(58,48,12,48);g.fillRect(186,48,12,48);
    g.fillStyle=vgrad(h,'rgba(255,255,255,.06)','rgba(0,0,0,.2)');g.fillRect(0,0,w,h);
    g.fillStyle='rgba(0,0,0,.25)';g.fillRect(0,0,w,5);
    if(!info.ref)text(String(info.num),32,74,22,lumOf(sc)>.5?'#111111':'#ffffff',1.15)});
  R('sock',(w,h)=>{g.fillStyle=css(kit.socks);g.fillRect(0,0,w,h);g.fillStyle=lumOf(kit.socks)>.5&&lumOf(kit.trim)>.5?css(kit.base):trim;g.fillRect(0,5,w,11);g.fillRect(0,21,w,5);
    const q=g.createLinearGradient(0,0,w,0);q.addColorStop(0,'rgba(0,0,0,.2)');q.addColorStop(.3,'rgba(255,255,255,.07)');q.addColorStop(.75,'rgba(0,0,0,.16)');q.addColorStop(1,'rgba(0,0,0,.2)');g.fillStyle=q;g.fillRect(0,0,w,h)});
  R('arm',(w,h)=>{g.fillStyle=kit.gk?base:skin;g.fillRect(0,0,w,h)});
  R('skin',(w,h)=>{g.fillStyle=skin;g.fillRect(0,0,w,h)});
  R('hand',(w,h)=>{g.fillStyle=kit.gk?css(kit.glove):skin;g.fillRect(0,0,w,h)});
  R('boot',(w,h)=>{const bc=info.ref?0x111111:BOOT_COLS[look.boot];g.fillStyle=css(bc);g.fillRect(0,0,w,h);
    g.fillStyle=shade(bc,lumOf(bc)>.5?-.35:.35);g.beginPath();g.moveTo(20,h*.3);g.lineTo(44,h*.25);g.lineTo(34,h*.8);g.lineTo(18,h*.8);g.closePath();g.fill();
    g.beginPath();g.moveTo(108,h*.3);g.lineTo(84,h*.25);g.lineTo(94,h*.8);g.lineTo(110,h*.8);g.closePath();g.fill();
    g.fillStyle='rgba(255,255,255,.75)';for(let y=30;y<64;y+=7)g.fillRect(54,y,20,2.4);
    g.fillStyle='#0c0c0c';g.fillRect(0,0,13,h);g.fillRect(115,0,13,h);g.fillStyle=css(kit.socks);g.fillRect(40,0,48,26)});

  R('head',(w,h)=>{
    const PY=y=>(HEAD_TOP-y)*h/(HEAD_TOP-1.577),cx=w/2;
    g.fillStyle=skin;g.fillRect(0,0,w,h);
    // gentle modelling: lighter brow and cheeks, darker sides and under the jaw
    let q=g.createRadialGradient(cx,PY(1.70),6,cx,PY(1.70),74);q.addColorStop(0,'rgba(255,255,255,.10)');q.addColorStop(1,'rgba(0,0,0,.10)');g.fillStyle=q;g.fillRect(0,0,w,h);
    q=g.createLinearGradient(0,PY(1.62),0,h);q.addColorStop(0,'rgba(0,0,0,0)');q.addColorStop(1,'rgba(0,0,0,.30)');g.fillStyle=q;g.fillRect(0,PY(1.62),w,h);
    // hair growing on the scalp (also what a buzz cut looks like)
    if(!st.none){g.save();g.shadowColor=hair;g.shadowBlur=5;g.fillStyle=hair;g.beginPath();g.moveTo(-8,-8);
      for(let x=-8;x<=w+8;x+=4){const a=(x/w-.5)*PI*2;g.lineTo(x,PY(hairline(a,st))+2*Math.sin(x*.9))}g.lineTo(w+8,-8);g.closePath();g.fill();
      g.restore()}
    // beard: 1 stubble, 2 full, 3 goatee/moustache
    if(look.beard){g.save();g.fillStyle=hair;g.globalAlpha=look.beard===1?.26:.86;g.beginPath();
      if(look.beard===3){g.ellipse(cx,PY(1.618),15,12,0,0,7);g.rect(cx-15,PY(1.655)-2,30,5)}
      else{g.moveTo(cx-60,PY(1.69));g.quadraticCurveTo(cx-50,PY(1.63),cx-19,PY(1.648));g.lineTo(cx-15,PY(1.66));g.lineTo(cx+15,PY(1.66));g.lineTo(cx+19,PY(1.648));
        g.quadraticCurveTo(cx+50,PY(1.63),cx+60,PY(1.69));g.lineTo(cx+62,h);g.lineTo(cx-62,h);g.closePath()}
      g.fill();g.restore()}
    // eyes
    const ey=PY(1.731),dk=shade(skinC,-.45);
    for(const s of [-1,1]){const ex=cx+s*17.5;
      q=g.createRadialGradient(ex,ey,2,ex,ey,15);q.addColorStop(0,'rgba(0,0,0,.22)');q.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=q;g.fillRect(ex-16,ey-14,32,28);
      g.save();g.beginPath();g.ellipse(ex,ey,7.4,4.3,0,0,7);g.clip();g.fillStyle='#f4f1ec';g.fillRect(ex-9,ey-6,18,12);
      g.fillStyle=EYE_COLS[look.eye];g.beginPath();g.ellipse(ex,ey,3.1,5,0,0,7);g.fill();g.fillStyle='#0b0b0b';g.beginPath();g.ellipse(ex,ey,1.4,2.3,0,0,7);g.fill();g.restore();
      g.strokeStyle=dk;g.lineWidth=1.5;g.beginPath();g.ellipse(ex,ey,7.4,4.3,0,PI,PI*2);g.stroke();
      // brow
      g.fillStyle=shade(hairC,-.2);g.beginPath();g.moveTo(ex-s*9.5,ey-11);g.quadraticCurveTo(ex,ey-17,ex+s*10.5,ey-12);g.lineTo(ex+s*10.5,ey-9);g.quadraticCurveTo(ex,ey-12,ex-s*9.5,ey-7);g.closePath();g.fill()}
    // nose shadow and mouth
    g.fillStyle='rgba(0,0,0,.26)';g.beginPath();g.ellipse(cx,PY(1.664),9,3.2,0,0,7);g.fill();
    g.strokeStyle='rgba(0,0,0,.10)';g.lineWidth=2;for(const s of [-1,1]){g.beginPath();g.moveTo(cx+s*6,ey+6);g.lineTo(cx+s*8.5,PY(1.672));g.stroke()}
    const my=PY(1.643);g.fillStyle=shade(skinC,-.28);g.beginPath();g.moveTo(cx-14,my);g.quadraticCurveTo(cx,my-5,cx+14,my);g.quadraticCurveTo(cx,my+1.5,cx-14,my);g.fill();
    g.fillStyle=new THREE.Color(skinC).lerp(new THREE.Color(0xb04a4a),.35).getStyle();g.beginPath();g.moveTo(cx-12,my+.8);g.quadraticCurveTo(cx,my+8,cx+12,my+.8);g.quadraticCurveTo(cx,my+2.4,cx-12,my+.8);g.fill();
    g.strokeStyle='rgba(30,12,10,.75)';g.lineWidth=1.3;g.beginPath();g.moveTo(cx-14,my);g.quadraticCurveTo(cx,my+2,cx+14,my);g.stroke();
  });
  ch.tex.needsUpdate=true;
  // hair mesh, build, glove size
  const hg=HAIR_GEO[look.hairStyle];ch.hair.visible=!!hg;if(hg){ch.hair.geometry=hg;ch.hair.material=HAIR_MATS[look.hairCol]}
  ch.scale=PSCALE*look.h;ch.root.scale.set(ch.scale*look.w,ch.scale,ch.scale*look.w);
  const gs=kit.gk?1.4:1;ch.B.handL.scale.setScalar(gs);ch.B.handR.scale.setScalar(gs);
  ch.foot=look.foot;
}
