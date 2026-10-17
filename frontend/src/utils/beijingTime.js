// Legacy DATETIME strings have no offset. New business writes use UTC+8 explicitly.
export function businessDate(value){
 if(value instanceof Date)return Number.isFinite(value.getTime())?value:null;
 if(typeof value!=='string')return null;
 let text=value.trim().replace(' ','T');
 if(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?$/.test(text))text+='+08:00';
 else if(!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/i.test(text))return null;
 const date=new Date(text);return Number.isFinite(date.getTime())?date:null;
}
export function beijingClock(value){const date=businessDate(value);return date?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date):''}
export function relativeBeijingTime(value,now=Date.now()){
 const date=businessDate(value);if(!date)return '';
 const diff=now-date.getTime();if(diff>=-60000&&diff<60000)return '刚刚';
 if(diff>=0&&diff<3600000)return Math.floor(diff/60000)+' 分钟前';
 if(diff>=0&&diff<86400000)return Math.floor(diff/3600000)+' 小时前';
 return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',...(diff<0?{hour:'2-digit',minute:'2-digit',hourCycle:'h23'}:{})}).format(date);
}
export function businessTimestamp(value){return businessDate(value)?.getTime()??0}
export function beijingDateTime(value=new Date()){
 const date=businessDate(value);if(!date)return '';
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(date).map(part=>[part.type,part.value]));
 return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}
export function beijingExportStamp(value=new Date()){const text=beijingDateTime(value);return text?text.replace(/[-:]/g,'').replace(' ','-'):''}
