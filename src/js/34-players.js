/* ===== Players: the 22 on the pitch ===== */
for(let t=0;t<2;t++)for(let i=0;i<11;i++){
  const f=FORM[i];
  const p={team:t,i,role:f[2],num:f[3],gk:i===0,hx:f[0],hz:f[1],x:0,z:0,vx:0,vz:0,spd:0,vf:1,vl:0,face:t?Math.PI:0,phase:rand(0,6),
    stam:1,cool:0,stun:0,kickT:0,kickKind:0,windA:0,act:null,slideT:0,slideHit:false,tackleT:0,skillCD:0,skillT:0,trapT:0,diveT:0,diveDir:0,diveH:1,celebT:0,holdT:0,jumpT:0,
    aiT:0,possT:0,tx:0,tz:0,sx:0,sz:0,run:false,recv:false,mustPass:false,throwT:0,hands:false,wall:false,save:null,shotSeen:-1,supT:0,stats:null,name:'',jog:5.4,sprint:8,
    fit:1,yc:0,off:false,offside:false,foot:-1,look:null};
  p.mesh=buildCharacter();
  players.push(p);TP[t].push(p);
}
function colorDist(a,b){const A=new THREE.Color(a),B=new THREE.Color(b);return hyp(A.r-B.r,A.g-B.g,A.b-B.b)}
// repaint a player's texture, hair and build from who they are now (used at kick-off and for substitutes)
function applyLook(p){const T=S.teams[p.team];paintLook(p.mesh,p.look,kitFor(T,S.away[p.team],p.gk),{num:p.num,name:p.name,crest:T.code[0]});p.foot=p.look.foot;p.mesh.snap=true}
function setupTeams(){
  S.away=[false,colorDist(S.teams[1].kit,S.teams[0].kit)<.45];S.kitColor=[];
  for(let t=0;t<2;t++){
    const T=S.teams[t];S.kitColor[t]=S.away[t]?T.away:T.kit;
    const rnd=mulberry(TEAMS.indexOf(T)*977+13);
    ROSTER[t].forEach(p=>{
      const r=T.rating+(rnd()*10-5), b=k=>clamp(Math.round(r+k+(rnd()*8-4)),45,96);
      p.stats=genStats(p.role,b);p.num=FORM[p.i][3];
      p.jog=4.7+p.stats.pace/100*1.1;p.sprint=6.7+p.stats.pace/100*2.1;
      p.name=INIT[(rnd()*INIT.length)|0]+'. '+SUR[(rnd()*SUR.length)|0];
      p.look=randomLook(rnd,p.role);
      p.fit=1;p.stam=1;p.yc=0;p.off=false;p.pendingOff=false;p.offside=false;p.mesh.root.visible=true;
      applyLook(p);
    });
    makeBench(t,T,rnd);
  }
  refKit();
}
