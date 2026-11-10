/* ===== Game state ===== */
const S={phase:'restart',user:-1,teams:[TEAMS[0],TEAMS[1]],score:[0,0],half:1,clock:0,halfLen:99999,
  diff:DIFF.pro,camMode:0,ctrl:null,timeScale:1,rs:null,phaseT:0,lastTouch:0,lastKicker:null,shotId:0,
  stats:{shots:[0,0],poss:[0,0]},paused:false,goalTeam:0,goalEnd:1,autoT:0,sound:true,demo:true};
const sel={team:0,opp:1,len:4,diff:'pro',cam:0};
const ball={x:0,y:BR,z:0,vx:0,vy:0,vz:0,curl:0,dip:0,owner:null,shot:false,shotTeam:-1,passTo:null};
const players=[]; const TP=[[],[]];
