/* ===== HUD ===== */
const mini=$('#mini'),mg=mini.getContext('2d');
function drawMini(){
  const W=mini.width,H=mini.height,sx=W/(PL+6),X=x=>(x+HL+3)*sx,Z=z=>(z+HW+3)*sx;
  mg.clearRect(0,0,W,H);mg.strokeStyle='rgba(238,243,255,.35)';mg.lineWidth=2;mg.strokeRect(X(-HL),Z(-HW),PL*sx,PW*sx);
  mg.beginPath();mg.moveTo(X(0),Z(-HW));mg.lineTo(X(0),Z(HW));mg.stroke();mg.beginPath();mg.arc(X(0),Z(0),9.15*sx,0,7);mg.stroke();
  mg.strokeRect(X(-HL),Z(-BOXZ),16.5*sx,BOXZ*2*sx);mg.strokeRect(X(BOXX),Z(-BOXZ),16.5*sx,BOXZ*2*sx);
  const col=[ '#'+new THREE.Color(S.kitColor?S.kitColor[0]:0x1f5fd1).getHexString(),'#'+new THREE.Color(S.kitColor?S.kitColor[1]:0xd2612a).getHexString()];
  for(const p of players){mg.fillStyle=col[p.team];mg.beginPath();mg.arc(X(p.x),Z(p.z),p===S.ctrl?6:4.2,0,7);mg.fill();
    mg.strokeStyle=p===S.ctrl?'#2ee6c5':'rgba(0,0,0,.6)';mg.lineWidth=p===S.ctrl?2.5:1;mg.stroke()}
  mg.fillStyle='#ffd23f';mg.beginPath();mg.arc(X(ball.x),Z(ball.z),3.6,0,7);mg.fill();
}
let lastMode=null;
function updateHud(){
  const mins=Math.min(90,Math.floor(((S.half-1)*S.halfLen+Math.min(S.clock,S.halfLen))/S.halfLen*45));
  $('#clk').textContent=mins+"'";
  const atk=attackMode(),rs=S.rs,sp=S.phase==='restart'&&rs&&rs.team===S.user,mode=sp?'sp'+rs.type+rs.inRange:atk?'a':'d';
  $('#hint').hidden=!(S.hintText&&S.phase==='restart'&&rs&&rs.ready&&!rs.kick);
  if(mode!==lastMode){lastMode=mode;const shot=sp&&(rs.type==='penalty'||rs.inRange);const L=sp?(rs.type==='throw'?{pass:['THROW',''],through:['THROW',''],shoot:['THROW',''],skill:['—',''],lob:['THROW','']}
      :rs.type==='penalty'?{pass:['SHOOT','placed'],through:['SHOOT','placed'],shoot:['SHOOT','hold: power'],skill:['—',''],lob:['—','']}
      :rs.type==='kickoff'?{pass:['PASS','kick off'],through:['PASS',''],shoot:['PASS',''],skill:['—',''],lob:['PASS','']}
      :{pass:['PASS',rs.type==='corner'||rs.cross?'cross':'lofted'],through:['THRU','driven'],shoot:shot?['SHOOT','hold: power']:rs.type==='corner'||rs.cross?['CROSS','whipped']:['LONG','lofted'],skill:['—',''],lob:['LOB','lofted']})
      :atk?{pass:['PASS','tap'],through:['THRU','ball'],shoot:['SHOOT','hold: power'],skill:['SKILL','feint'],lob:['LOB','long ball']}
      :{pass:['SWITCH','player'],through:['PRESS','hold'],shoot:['TACKLE','tap'],skill:['CONTAIN','hold'],lob:['SLIDE','tackle']};
    for(const b in L){const el=document.querySelector(`[data-b="${b}"]`);el.querySelector('.lbl').textContent=L[b][0];el.querySelector('.sub').textContent=L[b][1]}}
  const h=IN.held.shoot;
  const pw=$('#power');if(h!=null&&atk){const v=(now()-h)/.9;pw.classList.add('on');pw.firstElementChild.style.transform=`scaleX(${clamp(v/1.15,0,1)})`}else pw.classList.remove('on');
  if(S.ctrl)$('#stam i').style.transform=`scaleX(${S.ctrl.stam})`;
  const co=ball.owner||ball.passTo,cb=$('#carrier');
  if(co&&S.phase!=='replay'){cb.hidden=false;const key=co.team+'|'+co.num+co.name;
    if(cb.dataset.k!==key){cb.dataset.k=key;cb.innerHTML=`<i style="background:#${new THREE.Color(S.kitColor[co.team]).getHexString()}"></i><b>${co.num}</b><span>${co.name}</span>`}}
  else cb.hidden=true;
}
function updateBoard(){$('#t0').textContent=S.teams[0].code;$('#t1').textContent=S.teams[1].code;$('#sc').textContent=S.score[0]+' – '+S.score[1];
  $('#c0').style.background='#'+new THREE.Color(S.kitColor[0]).getHexString();$('#c1').style.background='#'+new THREE.Color(S.kitColor[1]).getHexString()}
let bannerT=0,toastT=0;
function banner(txt,sub){const b=$('#banner');if(!txt){b.classList.remove('on');return}b.innerHTML='';b.append(txt);if(sub){const s=document.createElement('small');s.textContent=sub;b.append(s)}b.classList.add('on');bannerT=2.4}
let noticeT=0;
function notice(html){if(S.user<0)return;const n=$('#notice');n.innerHTML=html;n.classList.add('on');noticeT=3}
function toast(t){if(!t)return;const e=$('#toast');e.textContent=t;e.classList.add('on');toastT=1.3}
