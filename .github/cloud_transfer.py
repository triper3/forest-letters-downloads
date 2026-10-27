"""Public release transfer utility: public binary URLs only, no game source.

Runs on the download repository's standard hosted runner. No Actions artifacts,
cache, production signing secret, private source access or external credentials.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY='triper3/forest-letters-downloads'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def run(config):
    assert os.environ['GITHUB_REPOSITORY']==REPOSITORY and config['repository']==REPOSITORY
    token=os.environ['GH_TOKEN'];opener=urllib.request.build_opener(NoRedirect())
    def api(method,path,payload=None,data=None,name=None):
        assert path=='/repos/'+REPOSITORY or path.startswith('/repos/'+REPOSITORY+'/')
        url=('https://uploads.github.com' if name else 'https://api.github.com')+path
        if name:url+='?name='+urllib.parse.quote(name,safe='')
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'Noctis-Public-Release-Transfer'}
        if payload is not None:data=json.dumps(payload).encode()
        if data is not None:headers.update({'Content-Type':'application/octet-stream' if name else 'application/json','Content-Length':str(len(data))})
        with opener.open(urllib.request.Request(url,data=data,headers=headers,method=method),timeout=180) as response:
            body=response.read();return json.loads(body) if body else None
    def pages(path):
        rows=[]
        for page in range(1,11):
            part=api('GET',path+'?per_page=100&page='+str(page));assert isinstance(part,list);rows+=part
            if len(part)<100:return rows
        raise ValueError('Pagination boundary')
    prefix='/repos/'+REPOSITORY
    repo=api('GET',prefix);assert repo['private'] is False
    release=api('GET',prefix+'/releases/'+str(config['releaseId']))
    assert release['body']==config['releaseBody'] and release['draft'] is True
    path=prefix+'/releases/'+str(release['id'])
    existing={a['name']:a for a in pages(path+'/assets')}
    assert set(existing)<=set(a['name'] for a in config['assets'])
    completed=0;lock=threading.Lock();started=time.monotonic()
    def match(a,b):return a.get('state')=='uploaded' and a['size']==b['bytes'] and a.get('digest')=='sha256:'+b['sha256']
    def transfer(asset):
        nonlocal completed
        old=existing.get(asset['name'])
        if old and not match(old,asset):
            # A stopped local request may leave an empty starter in this owned
            # draft. Never replace a completed upload with a different digest.
            assert old['state']=='starter' and old['size']==0
            api('DELETE',prefix+'/releases/assets/'+str(old['id']));old=None
        if old:state='reused'
        else:
            if 'inline' in asset:data=asset['inline'].encode()
            else:
                assert asset.get('sourceUrl'),'Small launcher must be verified-uploaded before cloud handoff'
                url=urllib.parse.urlparse(asset['sourceUrl']);assert url.scheme=='https' and url.netloc in config['sourceHosts'] and not url.username and not url.query and not url.fragment
                request=urllib.request.Request(asset['sourceUrl'],headers={'User-Agent':'Noctis-Public-Release-Transfer','Accept-Encoding':'identity'})
                with urllib.request.urlopen(request,timeout=120) as response:data=response.read(asset['bytes']+1)
            assert len(data)==asset['bytes'] and hashlib.sha256(data).hexdigest()==asset['sha256']
            result=api('POST',path+'/assets',data=data,name=asset['name']);assert match(result,asset);state='uploaded'
        with lock:
            completed+=1;print(json.dumps({'completed':completed,'total':len(config['assets']),'state':state,'name':asset['name'],'bytes':asset['bytes']}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(transfer,config['assets']))
    final=pages(path+'/assets');expected={a['name']:a for a in config['assets']}
    assert set(expected)==set(a['name'] for a in final)
    assert all(match(a,expected[a['name']]) for a in final)
    result=api('PATCH',path,{'draft':False,'make_latest':'true'});assert result['draft'] is False
    proof={'success':True,'assets':len(final),'bytes':sum(a['size'] for a in final),'seconds':time.monotonic()-started,'release':result['html_url'],'gameSHA256':config['gameSHA256'],'sourceRepositoriesAccessed':False,'actionsArtifactsCreated':False}
    print(json.dumps(proof),flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as out:out.write('```json\n'+json.dumps(proof,indent=2)+'\n```\n')

if __name__=='__main__':run(json.loads(Path('.github/release-transfer-v0.5.0.json').read_text()))
