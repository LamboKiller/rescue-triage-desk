"""Isolated video desk. All mutable stores are placed in the supplied workdir."""
import sys,time,argparse
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
import demo_run
import app.provenance
app.provenance._head=lambda: None
p=argparse.ArgumentParser()
p.add_argument('--workdir',required=True)
p.add_argument('--port',type=int,default=8096)
p.add_argument('--live',action='store_true')
a=p.parse_args()
work=Path(a.workdir).resolve()
import os
# Optional guard: set RTD_VIDEO_SCRATCH to force every workdir under one scratch root.
scratch=os.environ.get('RTD_VIDEO_SCRATCH')
assert work.name.startswith('vid') and (not scratch or work.is_relative_to(Path(scratch).resolve())),work
class VideoRoot:
    def __truediv__(self,part):
        return (work if str(part).split('/')[0] in ('runtime','logs') else Path(__file__).resolve().parents[2])/part
import app.pipeline as pipeline
pipeline.ROOT=VideoRoot()
if a.live:
    import app.config as config
    config.load_env()
    import app.web.server as web
    import threading
    web.ROOT=VideoRoot()
    (work/'runtime').mkdir(parents=True,exist_ok=True)
    (work/'logs').mkdir(parents=True,exist_ok=True)
    server=web.create_server('127.0.0.1',a.port,sample=False,registry_path=work/'runtime/events.jsonl')
    threading.Thread(target=server.serve_forever,daemon=True).start()
else:server=demo_run.serve_embedded(work,a.port)
print(f'VIDEO DESK http://127.0.0.1:{server.server_port}/v2',flush=True)
try:
    while True: time.sleep(1)
finally:
    server.shutdown();server.server_close()
