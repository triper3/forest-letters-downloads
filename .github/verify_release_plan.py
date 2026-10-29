"""Read current public game fragments and verify their ordered whole ZIP SHA.

The config contains only public asset metadata. No ZIP, cache or Actions
artifact is saved. Three bounded fragments may be held in memory at a time.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY='triper3/forest-letters-downloads'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def public_fragment(version,asset):
    initial='https://github.com/'+REPOSITORY+'/releases/download/v'+version+'/'+asset['name']
    opener=urllib.request.build_opener(NoRedirect());url=initial
    for hop in range(4):
        request=urllib.request.Request(url,headers={'User-Agent':'Noctis-Public-Release-Verification','Accept-Encoding':'identity'})
        try:
            with opener.open(request,timeout=120) as response:
                assert response.status==200 and response.headers.get('Content-Encoding') in (None,'identity')
                assert response.headers.get('Content-Length')==str(asset['bytes'])
                return response.read(asset['bytes']+1)
        except urllib.error.HTTPError as error:
            if error.code not in (301,302,303,307,308) or hop==3:raise
            target=urllib.parse.urlparse(urllib.parse.urljoin(url,error.headers.get('Location','')))
            assert target.scheme=='https' and target.hostname in ('release-assets.githubusercontent.com','objects.githubusercontent.com') and target.port in (None,443) and not target.username and not target.password and not target.fragment and target.path.startswith('/github-production-release-asset')
            url=target.geturl()
    raise ValueError('Release redirect limit exceeded')

def full_assets(config):
    assert config['repository']==REPOSITORY and re.fullmatch(r'\d+\.\d+\.\d+',config['version'])
    prefix='ForestLetters-Windows-v'+config['version']+'.zip.part'
    assets=sorted((a for a in config['assets'] if a['name'].startswith(prefix)),key=lambda a:a['name'])
    assert 1<=len(assets)<=512 and len(assets)==config['fullPartCount']
    for index,asset in enumerate(assets,1):
        assert asset['name']==prefix+f'{index:03d}' and type(asset['bytes']) is int and 0<asset['bytes']<=20*1024*1024 and re.fullmatch('[a-f0-9]{64}',asset['sha256'])
    assert type(config['gameBytes']) is int and 0<config['gameBytes']<=4*1024**3 and sum(a['bytes'] for a in assets)==config['gameBytes'] and re.fullmatch('[a-f0-9]{64}',config['gameSHA256'])
    return assets

def run(config,fetch=public_fragment,progress=True):
    assets=full_assets(config);whole=hashlib.sha256();total=0;started=time.monotonic()
    def get(asset):
        body=fetch(config['version'],asset)
        assert len(body)==asset['bytes'] and hashlib.sha256(body).hexdigest()==asset['sha256'],'Public fragment SHA/size differs'
        return body
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for offset in range(0,len(assets),3):
            for asset,body in zip(assets[offset:offset+3],pool.map(get,assets[offset:offset+3])):
                whole.update(body);total+=len(body)
                if progress:print(json.dumps(dict(part=asset['name'],verified=True,bytes=len(body))),flush=True)
    assert total==config['gameBytes'] and whole.hexdigest()==config['gameSHA256'],'Public whole ZIP SHA differs'
    result=dict(success=True,version=config['version'],publicHTTPParts=len(assets),bytes=total,wholeSHA256=whole.hexdigest(),seconds=time.monotonic()-started,duplicateWholeZIPWritten=False)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--receipt');args=parser.parse_args()
    result=run(json.loads(Path(args.config).read_text('utf-8-sig')))
    if args.receipt:
        with Path(args.receipt).open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result),flush=True)
