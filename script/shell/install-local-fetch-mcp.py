"""Install one pinned Fetch release into a prevalidated user/job directory. No shell."""
import argparse
import email
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
import zipfile

VERSION='2026.10.10'
FETCH_SHA='d722c48bdc1de3e2a81727853bc490cf55c6c935e2038cdcad3c111b1d85db77'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory',required=True)
parser.add_argument('--gateway-runtime',action='store_true',help='Include the reviewed HTTP bridge dependencies in the hashed installation')
parser.add_argument('--package-index',choices=['https://pypi.org/simple','https://mirrors.aliyun.com/pypi/simple'],default='https://pypi.org/simple')
args=parser.parse_args()
folder=Path(args.directory).resolve()
if not folder.is_dir() or (folder/'manifest.json').exists(): raise SystemExit('Expected fresh installation directory')
packages=folder/'packages';packages.mkdir()
cache=folder/'cache';cache.mkdir()

def run(command):
    subprocess.run(command,check=True,timeout=1200 if args.gateway_runtime else 420,cwd=folder)

requirements=[f'mcp-server-fetch=={VERSION}']
if args.gateway_runtime: requirements += ['mcp==1.29.0','uvicorn==0.40.0','PyYAML==6.0.3']
run([sys.executable,'-I','-m','pip','--isolated','download',*requirements,
     '--only-binary=:all:','--index-url',args.package_index,'--dest',str(packages),
     '--cache-dir',str(cache),'--disable-pip-version-check'])
wheels=list(packages.glob('*.whl'))
if not wheels or len(wheels)>80 or sum(p.stat().st_size for p in wheels)>150*1024*1024:
    raise SystemExit('Unexpected artifact count or total size')
locked=[];artifacts=[];licenses=[];found=False
legal=folder/'licenses';legal.mkdir()
for index,wheel in enumerate(sorted(wheels)):
    if wheel.stat().st_size>40*1024*1024: raise SystemExit('Artifact too large')
    digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
    with zipfile.ZipFile(wheel) as archive:
        metas=[n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        if len(metas)!=1: raise SystemExit('Invalid wheel metadata')
        meta=email.message_from_bytes(archive.read(metas[0]))
        name=meta['Name'];version=meta['Version']
        if not name or not version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in name+version):
            raise SystemExit('Invalid package identity')
        if name.lower().replace('_','-')=='mcp-server-fetch':
            if version!=VERSION or digest!=FETCH_SHA: raise SystemExit('Fetch wheel digest does not match reviewed release')
            found=True
        for entry in archive.infolist():
            leaf=entry.filename.rsplit('/',1)[-1].lower()
            if entry.file_size<=256*1024 and ('license' in leaf or leaf.startswith('copying') or leaf.startswith('notice')) and not entry.is_dir():
                filename=f'{index}-{len(licenses)}.txt';target=legal/filename
                target.write_bytes(archive.read(entry))
                licenses.append({'package':name,'version':version,'originalPath':entry.filename,'path':'licenses/'+filename,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    locked.append(f'{name}=={version} --hash=sha256:{digest}')
    artifacts.append({'name':name,'version':version,'path':'packages/'+wheel.name,'sha256':digest,'bytes':wheel.stat().st_size})
if not found or not any(x['package'].lower().replace('_','-')=='mcp-server-fetch' for x in licenses):
    raise SystemExit('Fetch artifact or license missing')
lock=folder/'requirements.lock';lock.write_text('\n'.join(locked)+'\n',encoding='utf-8')
venv.EnvBuilder(with_pip=True,symlinks=False).create(folder/'.venv')
python=folder/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
run([str(python),'-I','-m','pip','--isolated','install','--no-index','--find-links',str(packages),
     '--require-hashes','-r',str(lock),'--cache-dir',str(cache),'--disable-pip-version-check'])
run([str(python),'-I','-m','pip','check'])
result=subprocess.run([str(python),'-I','-c',"import importlib.metadata as m;print(m.version('mcp-server-fetch'))"],check=True,timeout=20,capture_output=True,text=True)
if result.stdout.strip()!=VERSION: raise SystemExit('Installed version mismatch')
site=folder/'.venv'/('Lib/site-packages' if os.name=='nt' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
config=folder/'stdio.json'
config.write_text(json.dumps({'mcpServers':{'fetch':{'command':str(python),'args':['-I','-m','mcp_server_fetch'],'env':{'PYTHONIOENCODING':'utf-8','PYTHONNOUSERSITE':'1'}}}},ensure_ascii=False,indent=2),encoding='utf-8')
critical=[python,site/'mcp_server_fetch/server.py',lock,config]+list(legal.glob('*.txt'))
protected=[{'path':p.relative_to(folder).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in critical]
manifest={'serverKey':'fetch','package':'mcp-server-fetch','version':VERSION,'transport':'STDIO',
          'packageSha256':FETCH_SHA,'sourceUrl':'https://pypi.org/project/mcp-server-fetch/'+VERSION+'/',
          'python':python.relative_to(folder).as_posix(),'args':['-I','-m','mcp_server_fetch'],
          'artifacts':artifacts,'licenses':licenses,'protectedFiles':protected}
(folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')
print(json.dumps({'installed':True,'version':VERSION,'artifacts':len(artifacts),'licenses':len(licenses)}))
