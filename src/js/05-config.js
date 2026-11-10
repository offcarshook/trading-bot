/* ===== Tunable settings (data-driven: change numbers here, not in the systems) ===== */
const CFG={
  // graphics presets — picked automatically on first launch, changeable in the pause menu
  gfx:{
    low:   {label:'Low',   dpr:1,   shadow:0,    tex:256,  aa:false},   // soft blob shadows only
    medium:{label:'Medium',dpr:1.5, shadow:1024, tex:512,  aa:true},
    high:  {label:'High',  dpr:2,   shadow:2048, tex:1024, aa:true},
  },
  // adaptive resolution: drop render scale when frames get slow, raise it back when there is headroom
  adaptive:{slowMs:21, fastMs:13, step:.12, minScale:.6, window:1.5},
  // delay between pressing a button and the boot meeting the ball (seconds): the leg swings back, then through
  kick:{userPass:.07, userLob:.09, userShot:.06, userFinesse:.09, firstTime:.05, aiPass:.12, aiShot:.21, follow:.28},
  // running cycle: [walk, sprint] values blended by speed
  gait:{hipSwing:[.40,.78], hipLean:[.03,.24], kneeSwing:[.85,2.0], kneeStance:[.10,.34], toeOff:[.45,.90],
        armSwing:[.22,.95], elbow:[.37,1.55], bodyLean:[.02,.20], stepLen:[.70,.13]},
};
// current graphics level: saved choice, otherwise a guess from the device
let GFX=(()=>{let k=null;try{k=localStorage.getItem('strike27gfx')}catch(e){}
  if(!CFG.gfx[k]){const mem=navigator.deviceMemory||4,cores=navigator.hardwareConcurrency||4,touch=typeof matchMedia==='function'&&matchMedia('(pointer:coarse)').matches;
    k=mem<=2||cores<=2?'low':touch?(cores<=4?'low':'medium'):'high'}
  return Object.assign({key:k},CFG.gfx[k])})();
