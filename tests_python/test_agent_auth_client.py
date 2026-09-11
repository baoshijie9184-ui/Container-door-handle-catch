from scripts.diagnostics import agent_live_smoke as agent


class FakeResponse:
    status_code = 200
    text = "ok"

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if url.endswith("/api/auth/login"):
            return FakeResponse({"code": 200, "data": {"username": "admin"}})
        return FakeResponse({"code": 200, "data": {"content": "ok"}})


def test_cookie_only_login_does_not_require_token(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(agent, "HTTP_SESSION", session)

    assert agent.login() is True


def test_subsequent_requests_reuse_session_without_authorization_header(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(agent, "HTTP_SESSION", session)

    agent.send_message(True, "你好")

    _, _, kwargs = session.calls[-1]
    assert "headers" not in kwargs
