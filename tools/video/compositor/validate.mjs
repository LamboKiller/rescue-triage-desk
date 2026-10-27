import fs from 'node:fs';
export function validate(T){
 const wordCount=s=>String(s).trim().split(/\s+/).filter(w=>/[\p{L}\p{N}]/u.test(w)).length;
 const errors=[],entries=[];let end=0;
 if(T.fps!==60||T.width!==1920||T.height!==1080)errors.push('Master must be 1920x1080 / 60');
 if(T.duration<210||T.duration>238)errors.push('Duration must be 210–238 seconds');
 for(let [i,s] of T.shots.entries()){
  if(Math.abs(s.start-end)>.001)errors.push(`Shot ${i}: gap or overlap`);end=s.end;
  if(s.end-s.start>6.001)errors.push(`Shot ${i}: no visual change for over 6 seconds`);
  if(s.kind==='ui'&&s.speed>8.001)errors.push(`Shot ${i}: speed exceeds 8x`);
  for(let b of s.blocks||[]){let words=wordCount(b.text||b.readingText||b.html?.replace(/<[^>]*>/g,' ')||'');let need=Math.max(b.stat?2.5:1.5,.32*words+.6);let hold=b.until-b.at-(b.counter?.seconds??b.reveal??.55)-.30;
   if(hold+1e-4<need)errors.push(`Shot ${i}: "${(b.text||b.readingText||b.html).slice(0,65)}" holds ${hold.toFixed(2)}s; needs ${need.toFixed(2)}s`);
   if(!b.credit)entries.push(s.start+b.at);
   if(/0 unsafe/i.test(b.text||b.readingText||b.html||'')&&!/dev|development|red.team/i.test(b.text||b.readingText||b.html))errors.push('Unsafe claim lacks scope');
  }
 }
 for(let b of T.blocks||[]){let words=wordCount(b.text||b.readingText||b.html?.replace(/<[^>]*>/g,' ')||'');let need=Math.max(b.stat?2.5:1.5,.32*words+.6),hold=b.until-b.at-(b.counter?.seconds??b.reveal??.55)-.30;if(hold+1e-4<need)errors.push(`Global: "${(b.text||b.readingText||b.html).slice(0,65)}" holds ${hold.toFixed(2)}s; needs ${need.toFixed(2)}s`);if(!b.credit)entries.push(b.at);if(/0 unsafe/i.test(b.text||b.readingText||b.html||'')&&!/dev|development|red.team/i.test(b.text||b.readingText||b.html))errors.push('Unsafe claim lacks scope');}
 entries.sort((a,b)=>a-b);for(let i=1;i<entries.length;i++)if(entries[i]-entries[i-1]<1.199)errors.push(`Text entrances ${entries[i-1]} and ${entries[i]} are too close`);
 for(let [i,c] of T.captions.entries()){
  if(c.end-c.start<.9-1e-4)errors.push(`Caption ${i} flashes <.9s`);
  if(c.text.trim().split(/\s+/).length>7)errors.push(`Caption ${i} exceeds 7 words`);
  if(c.text.split('\n').length>2||c.text.split('\n').some(x=>x.length>42))errors.push(`Caption ${i} exceeds 2 x 42 chars`);
  if(i&&c.start<T.captions[i-1].end-.001)errors.push(`Caption ${i} overlaps`);
 }
 if(Math.abs(end-T.duration)>.001)errors.push('Shots do not cover master duration');
 if(errors.length)throw Error('Timeline validation FAILED:\n'+errors.join('\n'));
 return {shots:T.shots.length,captions:T.captions.length,textBlocks:entries.length,duration:T.duration};
}
if(process.argv[1]?.endsWith('validate.mjs'))console.log(validate(JSON.parse(fs.readFileSync(process.argv[2]||'out/video/final/timeline.json','utf8'))));
