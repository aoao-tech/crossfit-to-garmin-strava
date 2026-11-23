import json

from arbox_sync.garmin_client import interactive_login


class FakeInner:
    def __init__(self):
        self.dumped_to = None

    def dump(self, path):
        self.dumped_to = path
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"di_token": "x", "di_refresh_token": "y", "di_client_id": "z"}, fh)


class FakeLoginApi:
    def __init__(self, needs_mfa, **kwargs):
        self.kwargs = kwargs
        self.needs_mfa = needs_mfa
        self.resumed_with = None
        self.client = FakeInner()

    def login(self, tokenstore=None):
        return ("needs_mfa", {"state": 1}) if self.needs_mfa else (None, None)

    def resume_login(self, state, code):
        self.resumed_with = (state, code)


def _factory(needs_mfa, holder):
    def make(**kwargs):
        api = FakeLoginApi(needs_mfa, **kwargs)
        holder.append(api)
        return api

    return make


def test_login_without_mfa_saves_tokens(tmp_path):
    made = []
    path = tmp_path / "sub" / "garmin_tokens.json"
    needed = interactive_login("a@b.c", "pw", path, ask_code=lambda: "000000", api_factory=_factory(False, made))
    assert needed is False
    assert path.is_file()
    assert made[0].resumed_with is None
    assert made[0].kwargs["return_on_mfa"] is True


def test_login_with_mfa_asks_code_and_resumes(tmp_path):
    made = []
    path = tmp_path / "garmin_tokens.json"
    needed = interactive_login("a@b.c", "pw", path, ask_code=lambda: " 123456\n", api_factory=_factory(True, made))
    assert needed is True
    assert made[0].resumed_with == ({"state": 1}, "123456")
    assert path.is_file()


def test_saved_file_contains_no_password(tmp_path):
    path = tmp_path / "garmin_tokens.json"
    interactive_login("a@b.c", "s3cret-pw", path, ask_code=lambda: "1", api_factory=_factory(False, []))
    assert "s3cret-pw" not in path.read_text(encoding="utf-8")
