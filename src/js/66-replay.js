/* ===== Replay recorder ===== */
const REC={N:210,F:3+22*8,head:0,count:0,acc:0};REC.buf=new Float32Array(REC.N*REC.F);
function record(dt){REC.acc+=dt;if(REC.acc<1/30)return;REC.acc-=1/30;const b=REC.buf,o=REC.head*REC.F;b[o]=ball.x;b[o+1]=ball.y;b[o+2]=ball.z;
  ALL.forEach((p,i)=>{const k=o+3+i*8;b[k]=p.x;b[k+1]=p.z;b[k+2]=p.face;b[k+3]=p.phase;b[k+4]=p.kickT;b[k+5]=p.slideT;b[k+6]=p.diveT*(p.diveDir||1);b[k+7]=p.spd});
  REC.head=(REC.head+1)%REC.N;REC.count=Math.min(REC.count+1,REC.N)}
function applyFrame(f){const b=REC.buf,o=f*REC.F;ball.x=b[o];ball.y=b[o+1];ball.z=b[o+2];
  ALL.forEach((p,i)=>{const k=o+3+i*8;p.x=b[k];p.z=b[k+1];p.face=b[k+2];p.phase=b[k+3];p.kickT=b[k+4];p.slideT=b[k+5];p.diveT=Math.abs(b[k+6]);p.diveDir=Math.sign(b[k+6]);p.spd=b[k+7];p.celebT=0;p.holdT=0})}
let RP=null;
function startReplay(){const n=Math.min(REC.count,165);if(n<40){afterGoal();return}
  RP={start:(REC.head-n+REC.N)%REC.N,n,t:0};S.phase='replay';$('#replayTag').hidden=false;banner('',null)}
function afterGoal(){if(cutting)return;RP=null;$('#replayTag').hidden=true;REC.count=0;const k=1-S.goalTeam;cutTo(()=>restart('kickoff',k))}
