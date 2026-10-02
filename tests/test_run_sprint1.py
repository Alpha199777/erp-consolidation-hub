from hub import run_sprint1


class FakeConnector:
    def __init__(self, source, ping_result=True, raises=False):
        self.source = source
        self._ping_result = ping_result
        self._raises = raises

    def ping(self):
        if self._raises:
            raise RuntimeError("connexion refusée")
        return self._ping_result


def test_check_only_all_ok(capsys):
    code = run_sprint1.check_only([FakeConnector("a"), FakeConnector("b")])
    assert code == 0
    assert "OK" in capsys.readouterr().out


def test_check_only_one_false_returns_1():
    code = run_sprint1.check_only([FakeConnector("a"), FakeConnector("b", ping_result=False)])
    assert code == 1


def test_check_only_exception_does_not_stop_others(capsys):
    code = run_sprint1.check_only([FakeConnector("a", raises=True), FakeConnector("b")])
    out = capsys.readouterr().out
    assert code == 1
    assert "a" in out and "b" in out  # le second ERP a bien été testé


def test_build_connectors_skips_missing_env(monkeypatch):
    class WithEnv:
        source = "with_env"

        @classmethod
        def from_env(cls):
            return FakeConnector("with_env")

    class WithoutEnv:
        source = "without_env"

        @classmethod
        def from_env(cls):
            return None

    monkeypatch.setattr(run_sprint1, "CONNECTOR_CLASSES", [WithEnv, WithoutEnv])
    active, skipped = run_sprint1.build_connectors()
    assert [c.source for c in active] == ["with_env"]
    assert skipped == ["without_env"]