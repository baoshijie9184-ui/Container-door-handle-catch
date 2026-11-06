"""Exercise real native SDK request serialization without external model traffic."""
import json

import httpx
from openai import OpenAI
import pytest

from memory_service import main


def test_memory_gateway_changes_transport_and_preserves_frozen_model_credentials_and_embedding(monkeypatch):
    monkeypatch.setenv('MEM0_MODEL_GATEWAY_BASE_URL', 'http://owned-gateway:8099')
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'fixture-not-real')
    monkeypatch.setenv('EMBEDDING_API_KEY', 'fixture-embedding')
    monkeypatch.setenv('DASHSCOPE_BASE_URL', 'https://frozen-provider.example/compatible-mode/v1')
    monkeypatch.setenv('EMBEDDING_BASE_URL', 'https://embedding-fixture.example/v1')
    frozen = {'provider': 'deepseek', 'base_url': 'https://frozen-deepseek.example/v1',
              'model': 'deepseek-flash', 'api_key': 'frozen-fixture-key'}
    before = dict(frozen)
    llm = main.create_configured_llm(frozen)
    try:
        assert str(llm.client.base_url).rstrip('/') == 'http://owned-gateway:8099/llm/deepseek/v1'
        assert llm.client.api_key == 'frozen-fixture-key'
        assert frozen == before
        config = main.get_memory_config()
        assert config['llm']['config']['openai_base_url'] == 'http://owned-gateway:8099/llm/dashscope/compatible-mode/v1'
        assert config['embedder']['config']['openai_base_url'] == 'https://embedding-fixture.example/v1'
    finally:
        llm.client.close()
    monkeypatch.setenv('MEM0_MODEL_GATEWAY_BASE_URL', '')
    assert main.llm_transport_url('deepseek', frozen['base_url']) == frozen['base_url']


@pytest.mark.parametrize('gateway', ['http://user:secret@gateway', 'https://gateway/path', 'file:///tmp/gateway'])
def test_memory_gateway_rejects_credentials_or_unsupported_deployment_routes(monkeypatch, gateway):
    monkeypatch.setenv('MEM0_MODEL_GATEWAY_BASE_URL', gateway)
    with pytest.raises(ValueError, match='deployment LLM gateway'):
        main.llm_transport_url('deepseek', 'https://provider.example/v1')


@pytest.mark.parametrize('model', ['qwen3.8-flash', 'qwen3.8-max-0902', 'glm-5.3', 'kimi-k3', 'kimi-k2.7-code'])
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
        main.configure_llm_provider(llm)
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
        if model.startswith('qwen3.8-'):
            assert request.get('enable_thinking') is False
        else:
            assert 'enable_thinking' not in request
    finally:
        llm.client.close()
        original.close()
