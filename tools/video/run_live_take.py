"""Same hero API calls; attach the native UI to real /run SSE while it executes."""
import sys,time,json
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
import demo_hero
import demo_lib as lib
demo_hero.HERO=Path(__file__).parent/'assets/hero-brief-snapshot.jsonl'
import os
feed=Path(os.environ.get('RTD_VIDEO_FEED') or Path(__file__).resolve().parents[2]/'out/video/vid_current_run.json')
feed.parent.mkdir(parents=True,exist_ok=True)
BaseDesk=lib.Desk
class StreamDesk(BaseDesk):
    def post(self,path,body):
        if path!='/run':return super().post(path,body)
        status,start=super().post(path,{**body,'async':True})
        if status!=202 or not start.get('run_id'):return status,start
        feed.write_text(json.dumps({'run_id':start['run_id'],'wall':time.time()}),encoding='utf-8')
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            status,state=self.get('/api/runs/'+start['run_id'])
            if status!=200:return status,state
            if state.get('status')=='complete':return 200,state['result']
            if state.get('status')=='failed':return 500,state.get('result',{'error':'run failed'})
            time.sleep(.35)
        return 504,{'error':'video run exceeded 300 seconds'}
lib.Desk=StreamDesk
demo_hero.main()
