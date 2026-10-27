"""Read the published full game from public GitHub/CDN and verify whole ZIP SHA.
Only three bounded fragments are kept in memory. No ZIP/artifact/cache is saved.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

def run(config):
    assert config['repository']=='triper3/forest-letters-downloads'
    expected=[a for a in config['assets'] if a['name'].startswith('ForestLetters-Windows-v'+config['version']+'.zip.part')]
    expected.sort(key=lambda a:a['name']);assert len(expected)==103
    whole=hashlib.sha256();total=0;started=time.monotonic()
    def get(asset):
        url='https://github.com/'+config['repository']+'/releases/download/v'+config['version']+'/'+asset['name']
        request=urllib.request.Request(url,headers={'User-Agent':'Noctis-Public-Release-Verification','Accept-Encoding':'identity'})
        with urllib.request.urlopen(request,timeout=120) as response:
            final=urllib.parse.urlparse(response.url)
            assert final.scheme=='https' and final.hostname in ('release-assets.githubusercontent.com','objects.githubusercontent.com','github.com')
            data=response.read(asset['bytes']+1)
        assert len(data)==asset['bytes'] and hashlib.sha256(data).hexdigest()==asset['sha256']
        return data
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for offset in range(0,len(expected),3):
            for asset,data in zip(expected[offset:offset+3],pool.map(get,expected[offset:offset+3])):
                whole.update(data);total+=len(data)
                print(json.dumps({'part':asset['name'],'verified':True,'bytes':len(data)}),flush=True)
    assert total==2146853242 and whole.hexdigest()==config['gameSHA256']
    print(json.dumps({'success':True,'publicHTTPParts':len(expected),'bytes':total,'wholeSHA256':whole.hexdigest(),'seconds':time.monotonic()-started,'duplicateWholeZIPWritten':False}),flush=True)

if __name__=='__main__':run(json.loads(Path('.github/release-transfer-v0.5.0.json').read_text()))
