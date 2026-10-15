"""Verify the Fetch network directly, including destinations below application URL checks."""
import json
from pathlib import Path
import re
import subprocess
import sys

CHECK = r'''
import json,sys,httpx
addresses=json.load(sys.stdin)
denied=[]
with httpx.Client(proxy='http://mcp-egress:3128',trust_env=False,timeout=10) as proxy:
    assert proxy.get('https://example.com/').status_code==200
    for address in ['169.254.169.254','127.0.0.1','10.0.0.1','100.100.100.200','127.0.0.1.nip.io',*addresses]:
        response=proxy.get('http://'+address+'/')
        assert response.status_code==403,(address,response.status_code)
        denied.append(address)
try:
    with httpx.Client(trust_env=False,timeout=2) as direct:
        direct.get('https://1.1.1.1/')
except httpx.RequestError:
    pass
else:
    raise AssertionError('Execution container unexpectedly has direct public internet access')
print(json.dumps({'publicProxyAllowed':True,'privateAndServerDestinationsDenied':denied,'directInternetDenied':True}))
'''


if __name__ == '__main__':
    values = dict(line.split('=',1) for line in Path(sys.argv[1]).read_text().splitlines() if re.match(r'^[A-Z_][A-Z_0-9]*=',line))
    image=values['MCP_FETCH_IMAGE']
    assert re.fullmatch('sha256:[a-f0-9]{64}',image)
    args=['docker','run','--rm','-i','--network','doorhandlecatch-mcp-exec','--user','10001:10001',
          '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--memory=128m','--pids-limit=64',
          '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=8m,uid=10001,gid=10001',image,'/opt/fetch/.venv/bin/python','-c',CHECK]
    subprocess.run(args,input=json.dumps(values['MCP_SERVER_PUBLIC_IPS'].split(',')).encode(),check=True,timeout=90)
