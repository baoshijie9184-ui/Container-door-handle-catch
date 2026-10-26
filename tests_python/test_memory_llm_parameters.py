"""Exercise real native SDK request serialization without external model traffic."""
import json

import httpx
from openai import OpenAI
import pytest

from memory_service import main


@pytest.mark.parametrize('model', ['qwen3.8-flash', 'glm-5.3', 'kimi-k3', 'kimi-k2.7-code'])
@pytest.mark.parametrize('managed', [False, True])
def test_provider_models_retain_the_native_output_budget(monkeypatch, model, managed):
    from mem0.utils.factory import LlmFactory
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('MEM0_DATA_DIR', raising=False)
    for name in ('DASHSCOPE_API_KEY', 'EMBEDDING_API_KEY'):
        monkeypatch.setenv(name, 'fixture-not-real')
    monkeypatch.setenv('MEM0_LLM_MODEL', model)
    base='https://provider-fixture.example/v1'
    if managed:
        llm=main.create_configured_llm({'model': model, 'api_key': 'fixture-not-real', 'base_url': base})
    else:
        monkeypatch.setenv('DASHSCOPE_BASE_URL', base)
        llm=LlmFactory.create('openai', main.get_memory_config()['llm']['config'])
    original=llm.client
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'fixture-completion', 'object': 'chat.completion', 'created': 0, 'model': model,
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': '{"memory":[]}'}}]})
    transport=httpx.Client(transport=httpx.MockTransport(handler))
    llm.client=OpenAI(api_key='fixture-not-real', base_url=base, http_client=transport, max_retries=0)
    try:
        result=llm.generate_response(messages=[{'role':'user','content':'Return an empty JSON memory list.'}],
                                     response_format={'type':'json_object'})
        assert result=='{"memory":[]}' and len(captured)==1
        request=captured[0]
        assert request['model']==model and request['response_format']=={'type':'json_object'}
        assert request.get('max_tokens')==2000, 'Provider extraction lost its native output bound'
        assert request.get('temperature')==(1.0 if model.startswith('kimi-') else 0.1)
    finally:
        llm.client.close()
        original.close()
