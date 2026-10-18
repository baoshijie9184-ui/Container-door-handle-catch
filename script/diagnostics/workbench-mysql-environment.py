"""Create an isolated ECS MySQL verification database and a private SSH tunnel.

Credentials stay in ignored work/ files. Never touches the application database.
"""
import argparse,json,re,socket,subprocess,time,uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'work/workbench-mysql'
CONFIG=OUT/'connection.json'
SSH=['ssh','-F',str(ROOT/'work/cloud/ssh-config'),'-o','BatchMode=yes','-o','ConnectTimeout=8']
HOST='doorhandle-bj'
CONTAINER='doorhandlecatch-monolith-mysql-1'
MYSQL=f'''sudo -n docker exec -i {CONTAINER} sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names' '''
def remote(command,stdin=None):
 result=subprocess.run(SSH+[HOST,command],input=stdin,capture_output=True,text=True,encoding='utf8',timeout=30)
 if result.returncode:raise RuntimeError('SSH/MySQL verification command failed; no credential output is displayed')
 return result.stdout.strip()
def database(value):
 if not re.fullmatch(r'doorhandle_wb_verify_[a-f0-9]{10}',value):raise RuntimeError('Refusing operation outside the dedicated verification database prefix')
 return value
def prepare():
 OUT.mkdir(parents=True,exist_ok=True)
 if CONFIG.exists():raise RuntimeError('An isolated environment already exists; inspect or clean it before creating another')
 name=database('doorhandle_wb_verify_'+uuid.uuid4().hex[:10]);port=13308
 with socket.socket() as probe:
  if probe.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Verification port 13308 is already in use; refusing to replace its owner')
 address=remote(f"sudo -n docker inspect --format '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {CONTAINER}")
 if not re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}',address):raise RuntimeError('Unexpected container address')
 username='wb_verify_'+name.rsplit('_',1)[-1];password=uuid.uuid4().hex+uuid.uuid4().hex
 config={'database':name,'url':f'jdbc:mysql://127.0.0.1:{port}/{name}?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai','username':username,'password':password,'containerAddress':address,'port':port}
 # Persist the cleanup identity before remote mutations; never copy a production password.
 CONFIG.write_text(json.dumps(config,ensure_ascii=False),encoding='utf8')
 remote(MYSQL,f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4;\nCREATE USER '{username}'@'%' IDENTIFIED BY '{password}';\nGRANT ALL ON `{name}`.* TO '{username}'@'%';\n")
 with (OUT/'tunnel.log').open('wb') as log:
  process=subprocess.Popen(SSH+['-N','-L',f'127.0.0.1:{port}:{address}:3306','-o','ExitOnForwardFailure=yes',HOST],stdout=subprocess.DEVNULL,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 config['tunnelPid']=process.pid
 CONFIG.write_text(json.dumps(config,ensure_ascii=False),encoding='utf8')
 for _ in range(40):
  with socket.socket() as probe:
   if probe.connect_ex(('127.0.0.1',port))==0:
    print(json.dumps({'database':name,'port':port,'ready':True}));return
  if process.poll() is not None:break
  time.sleep(.2)
 raise RuntimeError('Verification tunnel did not become ready; cleanup information is retained')
def cleanup():
 config=json.loads(CONFIG.read_text(encoding='utf8'));name=database(config['database'])
 username=config['username']
 if username not in ('root','wb_verify_'+name.rsplit('_',1)[-1]):raise RuntimeError('Invalid verification account identity')
 port=int(config['port']);address=config['containerAddress']
 if port!=13308:raise RuntimeError('Invalid verification port')
 if not re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}',address):raise RuntimeError('Invalid verification tunnel identity')
 remote(MYSQL,'DROP DATABASE IF EXISTS `'+name+'`;\n'+(f"DROP USER IF EXISTS '{username}'@'%';\n" if username!='root' else ''))
 # Native PowerShell validates the precise command line before stopping this owned process.
 if 'tunnelPid' in config:
  pid=int(config['tunnelPid'])
  script=f'''$taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId={pid}"; if($taskProcess -and $taskProcess.Name -eq 'ssh.exe' -and $taskProcess.CommandLine -like '*127.0.0.1:{port}:{address}:3306*' -and $taskProcess.CommandLine -like '*doorhandle-bj*'){{Stop-Process -Id {pid}}}'''
  subprocess.run(['pwsh','-NoProfile','-Command',script],check=True,capture_output=True)
 receipt={'database':name,'cleaned':True};(OUT/'cleanup.json').write_text(json.dumps(receipt),encoding='utf8')
 CONFIG.unlink();print(json.dumps(receipt))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','cleanup']);args=parser.parse_args()
 prepare() if args.action=='prepare' else cleanup()
