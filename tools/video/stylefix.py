from pathlib import Path
p=Path(__file__).parent/'compositor/index.html'
s=p.read_text(encoding='utf-8')
s=s.replace('</style>','.block{white-space:pre-line}.foot{background:rgba(0,0,0,.66);padding:5px 9px;border-radius:5px}</style>')
p.write_text(s,encoding='utf-8')
