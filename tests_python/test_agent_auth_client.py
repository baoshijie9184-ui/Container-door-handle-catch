"""The smoke CLI must retain cookie authentication across its requests."""
import sys
from scripts.diagnostics import agent_live_smoke as agent


class FakeResponse:
    status_code = 200
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith('/agui/catalog'):
            return FakeResponse({'mode': 'READ_ONLY'})
        if url.endswith('/agent-health'):
            data = {'framework': 'AgentScope', 'mode': 'READ_ONLY'}
        elif url.endswith('/api/auth/login'):
            data = {'username': 'inspector.demo'}
        elif url.endswith('/sessions'):
            data = {'sessionId': 'session-fixture'}
        elif url.endswith('/trace'):
            data = {'framework': 'AgentScope', 'status': 'COMPLETED', 'runId': 'run-fixture',
                    'events': [{'type': 'RUN_STARTED'}, {'type': 'RUN_FINISHED'}]}
        elif method == 'GET':
            data = [{'role': 'user', 'content': 'question'}, {'role': 'assistant', 'content': 'answer'}]
        else:
            data = {'intent': 'AGENTSCOPE', 'content': 'answer'}
        return FakeResponse({'code': 200, 'data': data})


def run_cli(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(agent.requests, 'Session', lambda: session)
    monkeypatch.setenv('AGENT_SMOKE_PASSWORD', 'fixture-only')
    monkeypatch.setattr(sys, 'argv', ['agent_live_smoke', '--username', 'inspector.demo', '--question', 'question'])
    assert agent.main() == 0
    return session


def test_cookie_only_login_does_not_require_token(monkeypatch):
    session = run_cli(monkeypatch)
    assert session.calls[0][1].endswith('/api/auth/login')
    assert len(session.calls) == 7


def test_subsequent_requests_reuse_session_without_authorization_header(monkeypatch):
    session = run_cli(monkeypatch)
    assert all('headers' not in kwargs for _, _, kwargs in session.calls)
    assert session.trust_env is False
    assert session.calls[-1][1].endswith('/session-fixture/trace')
