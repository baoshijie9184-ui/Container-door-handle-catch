"""Real ECS Prometheus scrape of the shared Python runtime, not a mock exporter."""
import json
import os
from pathlib import Path
import socket
import time
from urllib.error import HTTPError
from urllib.parse import urlencode,urlsplit
from urllib.request import ProxyHandler,Request,build_opener
import pytest
from runtime_telemetry import RuntimeTelemetry

pytestmark=pytest.mark.skipif(os.getenv('DOORHANDLE_REQUIRE_OBSERVABILITY_TESTS')!='true',reason='Owned ECS observability fixture is not configured')

def query(opener,prometheus,expression):
    with opener.open(prometheus+'/api/v1/query?'+urlencode({'query':expression}),timeout=5) as response:
        assert response.status==200;value=json.loads(response.read(2*1024**2))
    assert value['status']=='success';return value

def await_sample(opener,prometheus,expression,minimum):
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        result=query(opener,prometheus,expression);samples=result['data']['result']
        if len(samples)==1 and float(samples[0]['value'][1])>=minimum:return result
        time.sleep(.2)
    pytest.fail('Owned Prometheus did not observe the Python metric within the acceptance window')

def test_real_prometheus_scrapes_authenticated_python_counter_and_histogram(monkeypatch):
    prometheus=os.environ['DOORHANDLE_TEST_PROMETHEUS_URL'];parsed=urlsplit(prometheus)
    assert parsed.scheme=='http' and parsed.hostname=='127.0.0.1' and parsed.port>=1024 and not parsed.username and not parsed.query and not parsed.fragment
    targets=Path(os.environ['DOORHANDLE_TEST_OBSERVABILITY_TARGETS']).resolve(strict=True)
    token_file=Path(os.environ['DOORHANDLE_TEST_OBSERVABILITY_TOKEN_FILE']).resolve(strict=True)
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    for name,value in {'OTEL_ENABLED':'false','TELEMETRY_EVENTS_ENABLED':'false','TELEMETRY_METRICS_ENABLED':'true',
            'TELEMETRY_METRICS_HOST':'127.0.0.1','TELEMETRY_METRICS_PORT':str(port),'TELEMETRY_METRICS_TOKEN_FILE':str(token_file)}.items():monkeypatch.setenv(name,value)
    telemetry=RuntimeTelemetry.from_env('doorhandle-source-python',default_metrics_port=port)
    opener=build_opener(ProxyHandler({}));url='http://127.0.0.1:'+str(port)+'/metrics';target=targets/'python.json'
    try:
        assert telemetry.bootstrap_failure is None
        for supplied in (None,'wrong-machine-token'):
            headers={} if supplied is None else {'Authorization':'Bearer '+supplied}
            with pytest.raises(HTTPError) as denied:opener.open(Request(url,headers=headers),timeout=5)
            assert denied.value.code==401
        with opener.open(Request(url,headers={'Authorization':'Bearer '+token_file.read_text().strip()}),timeout=5) as response:
            assert response.status==200
        telemetry.set_ready(True)
        for _ in range(3):
            with telemetry.span('mem0.search'):pass
        temporary=targets/'python.tmp';temporary.write_text(json.dumps([{'targets':['127.0.0.1:'+str(port)],'labels':{'fixture':'python'}}]))
        temporary.replace(target)
        observations={
            'up':await_sample(opener,prometheus,'up{fixture="python"}',1),
            'counter':await_sample(opener,prometheus,'doorhandle_runtime_operations_total{fixture="python",operation="mem0.search",outcome="success"}',3),
            'histogramCount':await_sample(opener,prometheus,'doorhandle_runtime_operation_seconds_count{fixture="python",operation="mem0.search"}',3),
            'histogramBucket':await_sample(opener,prometheus,'doorhandle_runtime_operation_seconds_bucket{fixture="python",operation="mem0.search",le="+Inf"}',3),
            'histogramSum':await_sample(opener,prometheus,'doorhandle_runtime_operation_seconds_sum{fixture="python",operation="mem0.search"}',0)}
        receipt={'schemaVersion':1,'runtime':'python','status':'PASS','missingTokenStatus':401,'wrongTokenStatus':401,
            'authenticatedStatus':200,'providerCalls':0,'observations':observations}
        (targets.parent/'evidence/python-scrape.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    finally:
        target.unlink(missing_ok=True);telemetry.close()
