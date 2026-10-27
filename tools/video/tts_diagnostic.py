import asyncio,edge_tts,aiohttp,sys
import edge_tts.communicate as c
async def main():
    for version in ['143.0.3650.75','156.0.4314.42']:
        c.SEC_MS_GEC_VERSION='1-'+version
        try:
            async for x in edge_tts.Communicate('May 2024. Rio Grande do Sul.','en-US-AndrewMultilingualNeural').stream():
                if x['type']=='audio': print('AUDIO',len(x['data']));return
        except aiohttp.ClientResponseError as e: print(version,e.status,dict(e.headers),flush=True)
asyncio.run(main())
