const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm');
function harness() {
  let now='2026-10-06T08:00:00+09:00',responses=[],calls=[],locked=false;
  const p={ENABLED:'true',LINE_CHANNEL_ACCESS_TOKEN:'test',RECIPIENT_USER_ID:'U'+'a'.repeat(32),EXPECTED_RECIPIENT_NAME:'test',EXPECTED_BOT_NAME:'bot',IMAGE_BASE_URL:'https://example.com/images'};
  const properties={getProperty:k=>p[k]??null,setProperty:(k,v)=>p[k]=v};
  class FakeDate extends Date {constructor(...args){super(...(args.length?args:[now]));}}
  const c=vm.createContext({Date:FakeDate,Math:Object.assign(Object.create(Math),{random:()=>0}),
    PropertiesService:{getScriptProperties:()=>properties},
    LockService:{getScriptLock:()=>({tryLock:()=>{if(locked)return false;locked=true;return true;},releaseLock:()=>locked=false,waitLock:()=>locked=true})},
    Utilities:{getUuid:()=> 'stable-retry-key',formatDate:(d,tz,f)=>{
      const s=new Date(d.getTime()+9*3600000).toISOString();
      return f==='yyyy-MM-dd'?s.slice(0,10):f==='HH'?s.slice(11,13):s.slice(14,16);
    }},
    UrlFetchApp:{fetch:(url,o)=>{
      calls.push({url,options:o});
      let data={},code=200,headers={};
      if(url.endsWith('/quota'))data={type:'limited',value:200};
      else if(url.endsWith('/consumption'))data={totalUsage:Number(p.used||0)};
      else if(url.endsWith('/info'))data={displayName:'bot'};
      else if(url.includes('/profile/'))data={displayName:'test'};
      else if(url.endsWith('/push')&&!url.includes('/validate/')) {
        const r=responses.shift();if(r==='timeout')throw new Error('timeout');
        if(r){code=r.code;headers=r.headers||{};}
      }
      return {getResponseCode:()=>code,getContentText:()=>JSON.stringify(data),getAllHeaders:()=>headers,getBlob:()=>({getContentType:()=> 'image/png'})};
    }},ScriptApp:{getProjectTriggers:()=>[],deleteTrigger:()=>{},newTrigger:()=>({timeBased:()=>({everyMinutes:()=>({create:()=>{}})})})}
  });
  ['Content.js','Code.js'].forEach(f=>vm.runInContext(fs.readFileSync(__dirname+'/gas/'+f,'utf8'),c));
  return {c,p,calls,responses,time:t=>now=t,run:s=>vm.runInContext(s,c),state:()=>JSON.parse(p.EXERCISE_STATE||'{}'),pushes:()=>calls.filter(x=>x.url.endsWith('/message/push'))};
}
test('weekday schedule delivers once, correct hero/text, repeats and restart are safe',()=>{
 const h=harness();h.run('exerciseReminderTick()');assert.equal(h.state().job.minute,540);assert.equal(h.pushes().length,0);
 h.time('2026-10-06T09:00:00+09:00');h.run('exerciseReminderTick()');assert.equal(h.pushes().length,1);assert.equal(h.state().job.status,'sent');
 const payload=JSON.parse(h.pushes()[0].options.payload);assert.equal(payload.to,h.p.RECIPIENT_USER_ID);assert.equal(payload.messages.length,1);assert.match(payload.messages[0].contents.hero.url,/01-serious.png$/);
 h.run('exerciseReminderTick(); stopExerciseReminder(); startExerciseReminder(); exerciseReminderTick()');assert.equal(h.pushes().length,1);
 h.time('2026-10-07T08:00:00+09:00');h.run('exerciseReminderTick()');assert.equal(h.state().job.content,'02-break');
 h.time('2026-10-07T09:00:00+09:00');h.run('exerciseReminderTick()');assert.equal(h.pushes().length,2);assert.equal(h.state().sentCount,2);
});
test('disabled/weekends/outside time window never send, including JST vs UTC',()=>{
 const h=harness();for(const t of ['2026-10-10T12:00:00+09:00','2026-10-11T12:00:00+09:00','2026-10-06T17:00:00+09:00']){h.time(t);h.run('exerciseReminderTick()');}assert.equal(h.calls.length,0);
 h.p.ENABLED='false';h.time('2026-10-06T10:00:00+09:00');h.run('exerciseReminderTick()');assert.equal(h.calls.length,0);
 h.p.ENABLED='true';h.time('2026-10-12T00:00:00+09:00');h.run('exerciseReminderTick()');assert.equal(h.state().job.day,'2026-10-12');
});
test('ambiguous timeout retries identical payload/key; LINE accepted 409 completes',()=>{
 const h=harness();h.run('exerciseReminderTick()');h.time('2026-10-06T09:00:00+09:00');h.responses.push('timeout');assert.throws(()=>h.run('exerciseReminderTick()'),/timeout/);
 h.responses.push({code:409,headers:{'x-line-accepted-request-id':'accepted'}});h.run('exerciseReminderTick()');assert.equal(h.pushes().length,2);assert.deepEqual(h.pushes()[0].options,h.pushes()[1].options);assert.equal(h.state().sentCount,1);
 h.run('exerciseReminderTick()');assert.equal(h.pushes().length,2);
});
test('quota reserve prevents optional pushes',()=>{
 const h=harness();h.run('exerciseReminderTick()');h.time('2026-10-06T09:00:00+09:00');h.p.used='150';h.run('exerciseReminderTick()');assert.equal(h.pushes().length,0);
 h.p.used='149';h.run('exerciseReminderTick()');assert.equal(h.pushes().length,1);
});
test('old failed job is never caught up tomorrow or after 17:00',()=>{
 const h=harness();h.run('exerciseReminderTick()');h.time('2026-10-06T16:59:00+09:00');h.responses.push({code:500});assert.throws(()=>h.run('exerciseReminderTick()'));
 h.time('2026-10-06T17:00:00+09:00');h.run('exerciseReminderTick()');assert.equal(h.pushes().length,1);
 h.time('2026-10-07T08:00:00+09:00');h.run('exerciseReminderTick()');assert.equal(h.state().job.day,'2026-10-07');assert.equal(h.pushes().length,1);
});
test('recipient mutation cannot reroute persisted daily message',()=>{
 const h=harness();h.run('exerciseReminderTick()');h.p.RECIPIENT_USER_ID='U'+'b'.repeat(32);h.time('2026-10-06T09:00:00+09:00');assert.throws(()=>h.run('exerciseReminderTick()'),/送信先/);assert.equal(h.pushes().length,0);
});
test('validation has no pushes; monthly reset; random schedule remains in window',()=>{
 const h=harness();h.run('validateExerciseReminder()');assert.equal(h.pushes().length,0);
 h.p.EXERCISE_STATE=JSON.stringify({month:'2026-09',sentCount:25});h.run('exerciseReminderTick()');assert.equal(h.state().sentCount,0);
 for(const random of [0,0.5,0.999999]){h.c.Math.random=()=>random;const job=h.run('plan_(config_(), {}, localClock_(new Date()))');assert.ok(job.minute>=540&&job.minute<=1015);}
});
