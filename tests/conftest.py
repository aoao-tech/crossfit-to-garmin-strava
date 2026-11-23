import json
import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail any test that tries to open a real network connection."""

    def guard(*_args, **_kwargs):
        raise RuntimeError("network access is not allowed in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture
def garmin_raw_activities():
    return json.loads((FIXTURES / "garmin_activities.json").read_text(encoding="utf-8"))
