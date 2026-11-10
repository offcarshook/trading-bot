/* ===== Constants & helpers ===== */
const PL=105, PW=68, HL=52.5, HW=34, GHW=3.66, GH=2.44, BOXX=HL-16.5, BOXZ=20.16;
const BR=0.15, G=9.81, ROLL=3.0, PSCALE=1.22;
const $=s=>document.querySelector(s);
const rand=(a=0,b=1)=>a+Math.random()*(b-a);
const clamp=(v,a,b)=>v<a?a:v>b?b:v;
const randn=()=>(Math.random()+Math.random()+Math.random()-1.5)/1.5;
const now=()=>performance.now()/1000;
const hyp=Math.hypot;
function mulberry(a){return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}

const TEAMS=[
  {name:'Harbor Wolves',code:'HBW',kit:0x1f5fd1,shorts:0xffffff,socks:0x1f5fd1,away:0xf2f2f2,awayShorts:0x1f5fd1,gk:0xf2c230,rating:80},
  {name:'Copper Vale',code:'CPV',kit:0xd2612a,shorts:0x1c1c1c,socks:0xd2612a,away:0x1c1c1c,awayShorts:0xd2612a,gk:0x26c06a,rating:78},
  {name:'Northline FC',code:'NTL',kit:0xeef1f6,shorts:0x15203a,socks:0xeef1f6,away:0x15203a,awayShorts:0xeef1f6,gk:0xe8433f,rating:83},
  {name:'Kestrel United',code:'KES',kit:0x179a4b,shorts:0xf6d33c,socks:0x179a4b,away:0xf6d33c,awayShorts:0x179a4b,gk:0x7b45e0,rating:76},
  {name:'Ironbridge',code:'IRB',kit:0x8e1f2a,shorts:0xf0b72f,socks:0x8e1f2a,away:0xf0b72f,awayShorts:0x8e1f2a,gk:0x1fa6e0,rating:81},
  {name:'Solano City',code:'SOL',kit:0x101a33,shorts:0x3dc2f0,socks:0x3dc2f0,away:0x3dc2f0,awayShorts:0x101a33,gk:0xf27b2a,rating:79},
];
const SUR=['Okafor','Lindqvist','Moreau','Tanaka','Duarte','Haddad','Kowal','Brennan','Novak','Mensah','Castillo','Rahimi','Varga','Holm','Quinn','Azevedo','Sato','Ferrand','Ilunga','Petrov','Marsh','Ekwueme','Dahl','Ruiz','Osei','Laine','Bakker','Cruz','Hale','Nakamura','Sorensen','Adeyemi','Vidal','Kerr','Abara','Lund'];
const INIT='ABCDEFGHJKLMNOPRST';
// 4-3-3 in the frame of a team attacking +x (own goal at x=-52.5)
const FORM=[[-50,0,'GK',1],[-35,-22,'LB',3],[-38,-8,'CB',4],[-38,8,'CB',5],[-35,22,'RB',2],
  [-23,-13,'CM',8],[-27,0,'DM',6],[-23,13,'CM',10],[-11,-22,'LW',11],[-8,0,'ST',9],[-11,22,'RW',7]];
const FWD=new Set(['LW','ST','RW']);
const DIFF={
  amateur:{react:.5,err:1.7,tackle:.55,gk:.55,press:.85},
  pro:{react:.3,err:1,tackle:1,gk:.72,press:1},
  legend:{react:.16,err:.6,tackle:1.45,gk:.88,press:1.15},
};
const SIDE=[1,-1];
