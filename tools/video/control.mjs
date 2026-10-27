import fs from 'node:fs';
import {connect} from './compositor/cdp.mjs';
const c=await connect(Number(process.env.VID_CDP||9341));
try{
 if(process.argv[2]==='--focus'){console.log('before',await c.evaluate('({hidden:document.hidden,focus:document.hasFocus()})'));await c.send('Emulation.setFocusEmulationEnabled',{enabled:true});await c.send('Page.bringToFront');console.log('after',await c.evaluate('({hidden:document.hidden,focus:document.hasFocus()})'));}
 else if(process.argv[2]==='--close')await c.send('Browser.close');
 else if(process.argv[2]==='shot'){let r=await c.send('Page.captureScreenshot',{format:'jpeg',quality:90});fs.writeFileSync(process.argv[3],Buffer.from(r.data,'base64'));}
 else console.log(JSON.stringify(await c.evaluate(process.argv[2]==='--file'?fs.readFileSync(process.argv[3],'utf8'):process.argv[2]),null,2));
}finally{c.close()}
