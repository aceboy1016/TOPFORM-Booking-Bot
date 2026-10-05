/* Single-recipient GAS delivery. No booking sessions, calendars or AI calls. */
const REMINDER_TZ = 'Asia/Tokyo';
const STATE_KEY = 'EXERCISE_STATE';
const HANDLER = 'exerciseReminderTick';

function localClock_(now) {
  const day = Utilities.formatDate(now, REMINDER_TZ, 'yyyy-MM-dd');
  const weekday = new Date(day + 'T12:00:00Z').getUTCDay();
  return {day:day, month:day.slice(0,7), weekday:weekday,
    minute:Number(Utilities.formatDate(now, REMINDER_TZ, 'HH'))*60+
      Number(Utilities.formatDate(now, REMINDER_TZ, 'mm'))};
}
function config_() {
  const p = PropertiesService.getScriptProperties();
  const c = {token:p.getProperty('LINE_CHANNEL_ACCESS_TOKEN'), to:p.getProperty('RECIPIENT_USER_ID'),
    name:p.getProperty('EXPECTED_RECIPIENT_NAME'), bot:p.getProperty('EXPECTED_BOT_NAME'),
    imageBase:p.getProperty('IMAGE_BASE_URL'), reserve:Number(p.getProperty('RESERVE_MESSAGES') || '50')};
  if (!c.token || !/^U[0-9a-f]{32}$/.test(c.to || '') || !c.name || !c.bot ||
      !/^https:\/\//.test(c.imageBase || '') || !Number.isInteger(c.reserve) || c.reserve<0)
    throw new Error('通知設定が不足しています。スクリプトプロパティを確認してください。');
  return c;
}
function line_(c, path, body, retry) {
  const headers = {Authorization:'Bearer '+c.token};
  if (retry) headers['X-Line-Retry-Key']=retry;
  const options = {method:body===undefined?'get':'post',headers:headers,muteHttpExceptions:true};
  if (body!==undefined) {options.contentType='application/json';options.payload=JSON.stringify(body);}
  const r=UrlFetchApp.fetch('https://api.line.me/v2/bot/'+path, options);
  const code=r.getResponseCode();
  let data={}; try {data=JSON.parse(r.getContentText() || '{}');} catch (_) {}
  const h=r.getAllHeaders();
  const accepted=Object.keys(h).some(k=>k.toLowerCase()==='x-line-accepted-request-id' && h[k]);
  return {code:code,data:data,accepted:accepted};
}
function getLine_(c,path) {
  const r=line_(c,path);
  if (r.code!==200) throw new Error('LINE確認に失敗しました（HTTP '+r.code+'）。');
  return r.data;
}
function verifyIdentity_(c) {
  if (getLine_(c,'info').displayName!==c.bot || getLine_(c,'profile/'+c.to).displayName!==c.name)
    throw new Error('送信元または送信先の表示名が設定と一致しません。配信を開始しません。');
}
function card_(c,item) {
  return {type:'flex',altText:'🌿 '+item.title,contents:{type:'bubble',size:'mega',
    hero:{type:'image',url:c.imageBase.replace(/\/$/,'')+'/'+item.id+'.png',size:'full',aspectRatio:'3:2',aspectMode:'fit'},
    body:{type:'box',layout:'vertical',spacing:'md',paddingAll:'20px',contents:[
      {type:'text',text:'TOPFORM｜ちょこっと運動',size:'xs',color:'#167D8D',weight:'bold'},
      {type:'text',text:item.text,size:'md',wrap:true}]},
    footer:{type:'box',layout:'vertical',contents:[
      {type:'text',text:'配信の停止はスタッフにお知らせください。',size:'xs',color:'#888888',wrap:true}]}}};
}
function readState_(p) {return JSON.parse(p.getProperty(STATE_KEY)||'{}');}
function saveState_(p,s) {p.setProperty(STATE_KEY,JSON.stringify(s));}
function choose_(last) {
  const candidates=EXERCISE_CONTENT.filter(x=>x.id!==last);
  return candidates[Math.floor(Math.random()*candidates.length)];
}
function plan_(c,s,clock) {
  // Five-minute poll plus slack: never deliberately schedule at the 17:00 boundary.
  const earliest=Math.max(540,clock.minute+5);
  if (earliest>1015) return null;
  const item=choose_(s.lastContent);
  return {day:clock.day,minute:earliest+Math.floor(Math.random()*(1016-earliest)),
    to:c.to, content:item.id, message:card_(c,item),retryKey:Utilities.getUuid(),status:'planned'};
}
function exerciseReminderTick() {
  const lock=LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const p=PropertiesService.getScriptProperties();
    if (p.getProperty('ENABLED')!=='true') return;
    const clock=localClock_(new Date());
    if (clock.weekday===0 || clock.weekday===6 || clock.minute>=1020) return;
    const c=config_(), s=readState_(p);
    if (s.month!==clock.month) {s.month=clock.month;s.sentCount=0;}
    if (!s.job || s.job.day!==clock.day) {s.job=plan_(c,s,clock);saveState_(p,s);}
    const j=s.job;
    if (!j || j.status==='sent' || j.status==='failed' || clock.minute<540 || clock.minute<j.minute) return;
    if (j.to!==c.to) throw new Error('送信先が変更されています。一度停止して設定を確認してください。');
    if ((s.sentCount||0)>=25) return;
    const quota=getLine_(c,'message/quota'), used=getLine_(c,'message/quota/consumption');
    // Stop rather than spend beyond the free account's limit. Shared quota can race
    // with booking pushes; reserve is a buffer, not an allocation guarantee.
    if (quota.type!=='limited' || !Number.isFinite(quota.value) || !Number.isFinite(used.totalUsage))
      throw new Error('LINE送信枠を確認できないため配信を見送りました。');
    if (quota.value-used.totalUsage<=c.reserve) return;
    j.status='sending';saveState_(p,s); // persist exact payload/key before network call
    const r=line_(c,'message/push',{to:j.to,messages:[j.message]},j.retryKey);
    if (r.code===200 || (r.code===409 && r.accepted)) {
      j.status='sent';j.acceptedAt=new Date().toISOString();s.lastContent=j.content;
      s.sentCount=(s.sentCount||0)+1;saveState_(p,s);
    } else if (r.code===429 || r.code>=500) {
      j.status='retry';saveState_(p,s); // same day only; LINE retry key valid for 24h
      throw new Error('LINE一時エラー（HTTP '+r.code+'）。時間内に同じキーで再試行します。');
    } else {
      j.status='failed';j.errorCode=r.code;saveState_(p,s);
      throw new Error('LINE送信を停止しました（HTTP '+r.code+'）。設定を確認してください。');
    }
  } finally {lock.releaseLock();}
}
// Validates all five cards and remote images, but never sends a LINE message.
function validateExerciseReminder() {
  const c=config_();verifyIdentity_(c);
  EXERCISE_CONTENT.forEach(item=>{
    const url=c.imageBase.replace(/\/$/,'')+'/'+item.id+'.png';
    const img=UrlFetchApp.fetch(url,{muteHttpExceptions:true});
    if (img.getResponseCode()!==200 || !/^image\//.test(img.getBlob().getContentType()))
      throw new Error('画像を取得できません: '+item.id);
    if (line_(c,'message/validate/push',{messages:[card_(c,item)]}).code!==200)
      throw new Error('カード検証に失敗しました: '+item.id);
  });
  return '5種類の画像・カードと送信先を確認しました。メッセージは送信していません。';
}
function startExerciseReminder() {
  const lock=LockService.getScriptLock();lock.waitLock(10000);
  try {
    validateExerciseReminder();
    ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()===HANDLER).forEach(ScriptApp.deleteTrigger);
    ScriptApp.newTrigger(HANDLER).timeBased().everyMinutes(5).create();
    PropertiesService.getScriptProperties().setProperty('ENABLED','true');
    return '配信を開始しました。月〜金の9〜17時に1日1回送信します。';
  } finally {lock.releaseLock();}
}
function stopExerciseReminder() {
  const lock=LockService.getScriptLock();lock.waitLock(10000);
  try {
    PropertiesService.getScriptProperties().setProperty('ENABLED','false');
    ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()===HANDLER).forEach(ScriptApp.deleteTrigger);
    // Retain history: resuming on the same date must not send again.
    return '配信を停止しました。送信済み記録は保持しています。';
  } finally {lock.releaseLock();}
}
function exerciseReminderStatus() {
  const p=PropertiesService.getScriptProperties(),s=readState_(p);
  return {enabled:p.getProperty('ENABLED')==='true',month:s.month||null,sentCount:s.sentCount||0,
    day:s.job?s.job.day:null,plannedMinute:s.job?s.job.minute:null,status:s.job?s.job.status:null};
}
