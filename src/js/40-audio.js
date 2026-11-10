/* ===== Audio (procedural Web Audio) ===== */
const AU={ctx:null,master:null,crowd:null,noise:null,
  init(){if(this.ctx)return;try{const C=window.AudioContext||window.webkitAudioContext;this.ctx=new C();this.master=this.ctx.createGain();this.master.gain.value=S.sound?.8:0;this.master.connect(this.ctx.destination);
    const len=this.ctx.sampleRate*2,buf=this.ctx.createBuffer(1,len,this.ctx.sampleRate),d=buf.getChannelData(0);let last=0;for(let i=0;i<len;i++){const w=Math.random()*2-1;last=(last+.02*w)/1.02;d[i]=w*.4+last*3}
    this.noise=buf;const src=this.ctx.createBufferSource();src.buffer=buf;src.loop=true;const bp=this.ctx.createBiquadFilter();bp.type='bandpass';bp.frequency.value=650;bp.Q.value=.5;
    this.crowd=this.ctx.createGain();this.crowd.gain.value=.05;src.connect(bp).connect(this.crowd).connect(this.master);src.start()}catch(e){this.ctx=null}},
  mute(on){if(this.master)this.master.gain.value=on?.8:0},
  excite(v){if(this.crowd)this.crowd.gain.setTargetAtTime(.04+v*.1,this.ctx.currentTime,.6)},
  burst(dur,freq,gain,type='lowpass'){if(!this.ctx)return;const t=this.ctx.currentTime,s=this.ctx.createBufferSource();s.buffer=this.noise;const f=this.ctx.createBiquadFilter();f.type=type;f.frequency.value=freq;
    const g=this.ctx.createGain();g.gain.setValueAtTime(gain,t);g.gain.exponentialRampToValueAtTime(.001,t+dur);s.connect(f).connect(g).connect(this.master);s.start(t,Math.random());s.stop(t+dur+.05)},
  tone(freq,dur,gain,type='sine',slide=0){if(!this.ctx)return;const t=this.ctx.currentTime,o=this.ctx.createOscillator(),g=this.ctx.createGain();o.type=type;o.frequency.setValueAtTime(freq,t);if(slide)o.frequency.exponentialRampToValueAtTime(slide,t+dur);
    g.gain.setValueAtTime(gain,t);g.gain.exponentialRampToValueAtTime(.001,t+dur);o.connect(g).connect(this.master);o.start(t);o.stop(t+dur+.02)},
  kick(p){this.tone(140,.12,.5*Math.min(1,.4+p),'sine',50);this.burst(.06,2200,.25*Math.min(1,.4+p))},
  touch(){this.tone(180,.06,.15,'sine',90)},
  post(){this.tone(880,.4,.22,'triangle',860);this.tone(1320,.3,.1,'sine')},
  whistle(n=1,len=.3){if(!this.ctx)return;for(let i=0;i<n;i++){const t=this.ctx.currentTime+i*(len+.12),o=this.ctx.createOscillator(),l=this.ctx.createOscillator(),lg=this.ctx.createGain(),g=this.ctx.createGain();
    o.type='square';o.frequency.value=2900;l.frequency.value=38;lg.gain.value=180;l.connect(lg).connect(o.frequency);g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.09,t+.02);g.gain.setValueAtTime(.09,t+len);g.gain.linearRampToValueAtTime(0,t+len+.04);
    const f=this.ctx.createBiquadFilter();f.type='bandpass';f.frequency.value=2900;o.connect(f).connect(g).connect(this.master);o.start(t);l.start(t);o.stop(t+len+.06);l.stop(t+len+.06)}},
  roar(){if(!this.ctx)return;const t=this.ctx.currentTime,s=this.ctx.createBufferSource();s.buffer=this.noise;s.loop=true;const f=this.ctx.createBiquadFilter();f.type='bandpass';f.frequency.value=800;f.Q.value=.4;
    const g=this.ctx.createGain();g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.55,t+.4);g.gain.exponentialRampToValueAtTime(.01,t+4.5);s.connect(f).connect(g).connect(this.master);s.start(t);s.stop(t+4.6)},
  ooh(){this.burst(1.2,500,.25,'bandpass')},
};
const buzz=p=>{try{navigator.vibrate&&navigator.vibrate(p)}catch(e){}};
