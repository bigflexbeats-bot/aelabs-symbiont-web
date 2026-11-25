/* Run: node tests_alarm_controller.js — no browser or network needed. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const elements = Object.fromEntries(['soundToggle','alarmTest','alarmAck','alarmAudioStatus','alarmVolume'].map(id => [id,{
  id, listeners:{},classList:{values:new Set(),toggle(name,yes){if(yes)this.values.add(name);else this.values.delete(name)}},
  addEventListener(name,callback){this.listeners[name]=callback},click(){this.listeners.click?.()},
  textContent:'',value:'',disabled:false,setAttribute(name,value){this[name]=value}
}]));
const audio = {};
class MockAudio {
  constructor(src){this.src=src;this.paused=true;this.playCount=0;this.volume=0;this.listeners={};audio[src]=this}
  addEventListener(event,cb){this.listeners[event]=cb}
  pause(){this.paused=true}
  play(){this.paused=false;this.playCount++;return Promise.resolve()}
  set currentTime(value){this._time=value}
}
const storage = new Map();
const ctx={window:{}, Audio:MockAudio,document:{hidden:false,getElementById:id=>elements[id],addEventListener(){}},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,val)=>storage.set(key,val)},console};
vm.runInNewContext(fs.readFileSync('static/alarm-controller.js','utf8'),ctx);
const alarm=ctx.window.AELABSAlarm;
const crit=audio['/alarm-critical.wav'],warn=audio['/alarm-warning.wav'];
const red1={level:'error',key:'scale1red',text:'Весы 1 — красный уровень 0.800 кг'};
const yellow1={level:'warning',key:'scale1',text:'Весы 1 — жёлтый уровень'};
const redFromYellow={level:'error',key:'scale1',text:'Весы 1 — критический уровень'};
// Browser cannot play before explicit gesture.
alarm.update([red1]);assert.strictEqual(crit.playCount,0);
elements.soundToggle.click();assert.strictEqual(crit.playCount,1);assert.strictEqual(crit.paused,false);
assert.strictEqual(alarm.getState().pending,1);
// Same alarm in 5-second polls must not restart the siren.
alarm.update([{...red1,text:'Весы 1 — красный уровень 0.700 кг'}]);assert.strictEqual(crit.playCount,1);
// Acknowledge silences but does not erase critical condition.
elements.alarmAck.click();assert.strictEqual(crit.paused,true);assert.strictEqual(alarm.getState().critical,false);
alarm.update([red1]);assert.strictEqual(crit.paused,true);
// New critical while other error is acknowledged re-arms.
alarm.update([red1,{level:'error',key:'network',text:'Ошибка связи 502'}]);assert.strictEqual(crit.playCount,2);
// All resolved clears acknowledgement, so reappearing danger rings again.
alarm.update([]);assert.strictEqual(crit.paused,true);
alarm.update([red1]);assert.strictEqual(crit.playCount,3);
// Mute / enable works in both directions.
elements.soundToggle.click();assert.strictEqual(crit.paused,true);
elements.soundToggle.click();assert.strictEqual(crit.playCount,4);
// Yellow warning plays once, not in a loop.
alarm.update([]);const w0=warn.playCount;
alarm.update([yellow1]);assert.strictEqual(warn.playCount,w0+1);
alarm.update([yellow1]);assert.strictEqual(warn.playCount,w0+1);
// Even an acknowledged warning must trigger audible critical alarm upon escalation.
elements.alarmAck.click();alarm.update([redFromYellow]);assert.strictEqual(crit.playCount,5);
// A newer communication failure must also ring.
alarm.update([{level:'error',key:'network-fetch-failure',text:'HTTP 502'}]);assert.strictEqual(crit.paused,false);
elements.alarmAck.click();assert.strictEqual(crit.paused,true);
console.log('alarm controller tests passed');
