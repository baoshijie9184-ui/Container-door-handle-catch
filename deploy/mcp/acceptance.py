"""Server-side gateway acceptance. Credentials flow over stdin, never command arguments/logs."""
import json
from pathlib import Path
import re
import subprocess
import sys

CHECK = r'''
import asyncio, base64, hashlib, hmac, json, sys, time, uuid
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
config=json.load(sys.stdin)
def token(owner,scope):
    now=int(time.time())
    body=base64.urlsafe_b64encode(json.dumps(dict(aud='doorhandle-mcp-runner',owner=owner,scope=scope,
        installation=str(uuid.uuid4()),nonce=str(uuid.uuid4()),iat=now,exp=now+60)).encode()).decode().rstrip('=')
    signature=base64.urlsafe_b64encode(hmac.new(config['secret'].encode(),body.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    return body+'.'+signature
base='http://higress:8080/mcp/fetch'
async def main():
    report={}
    async with httpx.AsyncClient(trust_env=False,timeout=20) as http:
        credential=token(1,'install')
        headers={'Authorization':'Bearer '+credential,'X-MCP-Gateway-Key':config['key']}
        response=await http.get(base+'/artifact',headers=headers)
        assert response.status_code==200,('artifact',response.status_code,response.text[:160])
        assert response.json()['image']==config['image']
        report['artifactVerified']=True
        response=await http.get(base+'/artifact',headers={'Authorization':'Bearer '+credential})
        assert response.status_code==401,('gatewayKey',response.status_code)
        response=await http.get(base+'/artifact',headers={'Authorization':'Bearer '+credential+'x','X-MCP-Gateway-Key':config['key']})
        assert response.status_code==401,('signature',response.status_code)
        report['authenticationDenied']=True
    async def fetch(owner):
        credential=token(owner,'execute')
        headers={'Authorization':'Bearer '+credential,'X-MCP-Gateway-Key':config['key']}
        async with streamablehttp_client(base+'/mcp',headers=headers,timeout=35) as (read,write,_):
            async with ClientSession(read,write) as client:
                await client.initialize()
                tools=await client.list_tools()
                assert [tool.name for tool in tools.tools]==['fetch']
                denied=await client.call_tool('fetch',{'url':'http://169.254.169.254/'})
                assert denied.isError, 'private address allowed'
                result=await client.call_tool('fetch',{'url':'https://example.com/','max_length':1200})
                assert not result.isError,('fetch',result)
                assert 'Example Domain' in '\n'.join(item.text for item in result.content if hasattr(item,'text'))
        async with httpx.AsyncClient(trust_env=False,timeout=10) as http:
            response=await http.post(base+'/cancel',headers=headers)
            assert response.status_code==200
            response=await http.post(base+'/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/list'})
            assert response.status_code==401
        return owner
    report['owners']=await asyncio.gather(fetch(100001),fetch(100002))
    report['fetchSucceeded']=True
    report['privateAddressDenied']=True
    report['cancelRevoked']=True
    # Observe and cancel an actual running Stdio container, before its call completes.
    credential=token(100003,'execute')
    headers={'Authorization':'Bearer '+credential,'X-MCP-Gateway-Key':config['key']}
    async with streamablehttp_client(base+'/mcp',headers=headers,timeout=35) as (read,write,_):
        async with ClientSession(read,write) as client:
            await client.initialize()
            task=asyncio.create_task(client.call_tool('fetch',{'url':'https://httpbingo.org/delay/10','max_length':200}))
            observed=None
            for _ in range(80):
                process=await asyncio.create_subprocess_exec('docker','ps','-q','--filter','label=doorhandle.mcp.owner=100003',stdout=asyncio.subprocess.PIPE)
                output,_=await process.communicate()
                if output.strip():
                    detail=await asyncio.create_subprocess_exec('docker','inspect',output.decode().strip(),stdout=asyncio.subprocess.PIPE)
                    raw,_=await detail.communicate()
                    observed=json.loads(raw)[0]
                    break
                if task.done(): break
                await asyncio.sleep(.1)
            assert observed is not None, 'No active test container was observed'
            host=observed['HostConfig']
            assert observed['Config']['User']=='10001:10001' and host['ReadonlyRootfs'] and not host['Privileged']
            assert not host['Binds'] and host['NetworkMode']=='doorhandlecatch-mcp-exec'
            assert 'ALL' in host['CapDrop'] and host['Memory']==256*1024*1024 and host['PidsLimit']==64
            names={value.split('=',1)[0] for value in observed['Config']['Env']}
            assert not {'MCP_RUNNER_SECRET','OPENAI_API_KEY','DASHSCOPE_API_KEY','DB_PASSWORD','ALIYUN_OSS_ACCESS_KEY_SECRET'} & names
            async with httpx.AsyncClient(trust_env=False,timeout=10) as http:
                response=await http.post(base+'/cancel',headers=headers)
                assert response.status_code==200
            try:
                result=await asyncio.wait_for(task,10)
                assert result.isError, 'Cancelled process unexpectedly returned a successful result'
            except Exception as error:
                if isinstance(error, AssertionError): raise
            report['activeCancellationVerified']=True
            report['containerRestrictionsVerified']=True
    print(json.dumps(report))
asyncio.run(main())
'''


def main(envfile):
    values = dict(line.split('=', 1) for line in Path(envfile).read_text().splitlines() if re.match(r'^[A-Z_][A-Z_0-9]*=', line))
    cid = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=doorhandlecatch-monolith',
        '--filter', 'label=com.docker.compose.service=mcp-runner'], text=True).strip()
    if not re.fullmatch(r'[a-f0-9]{12,64}', cid):
        raise SystemExit('One running MCP runner is required')
    config = {'key': values['AGENT_MCP_GATEWAY_KEY'], 'secret': values['AGENT_MCP_GATEWAY_SECRET'], 'image': values['MCP_FETCH_IMAGE']}
    subprocess.run(['docker', 'exec', '-i', cid, '/opt/fetch/.venv/bin/python', '-c', CHECK],
        input=json.dumps(config).encode(), check=True, timeout=120)
    remaining = subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'label=doorhandle.mcp.managed=true'], text=True).strip()
    if remaining:
        raise SystemExit('Temporary MCP containers remain after the test')
    print('All temporary Fetch containers were removed')


if __name__ == '__main__':
    main(sys.argv[1])
