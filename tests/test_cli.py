"""Tests for the CLI entry point."""

from click.testing import CliRunner

from tardis.cli import main
from tardis.models import Step, StepType, Trace


def _make_cli_trace(trace_id, success=False):
    from tardis.store.sqlite_store import Store
    store = Store()
    store.conn.execute("DELETE FROM steps WHERE trace_id=?", (trace_id,))
    store.conn.execute("DELETE FROM traces WHERE id=?", (trace_id,))
    store.conn.commit()
    trace = Trace(id=trace_id, success=success)
    trace.add_step(Step(trace_id=trace_id, index=0, type=StepType.llm_call,
                        input={}, output={}, hash="cli_h0"))
    if not success:
        trace.add_step(Step(trace_id=trace_id, index=1, type=StepType.error,
                            input={}, output={"error": "fail"},
                            hash="cli_h1", success=False))
    store.save_trace(trace)
    return trace


class TestCLI:
    def test_health(self):
        runner = CliRunner()
        result = runner.invoke(main, ["health"])
        assert result.exit_code == 0
        assert "TARDIS OK" in result.output

    def test_init(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["init"])
        assert result.exit_code == 0
        assert "Initialized" in result.output
        assert (tmp_path / ".tardis").exists()

    def test_list_empty(self):
        runner = CliRunner()
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0

    def test_show_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(main, ["show", "nonexistent_id"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_replay_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(main, ["replay", "nonexistent_id"])
        assert result.exit_code != 0 or "not found" in result.output

    def test_autopsy_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(main, ["autopsy", "nonexistent_id"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_orch_status(self):
        runner = CliRunner()
        result = runner.invoke(main, ["orch", "status"])
        assert result.exit_code == 0

    def test_vector_stats(self):
        runner = CliRunner()
        result = runner.invoke(main, ["vector-stats"])
        assert result.exit_code == 0
        assert "LanceDB" in result.output

    def test_hook_non_windows(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        runner = CliRunner()
        result = runner.invoke(main, ["hook", "--duration", "1"])
        assert result.exit_code == 0
        assert "only available on Windows" in result.output

    def test_analyze_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(main, ["analyze", "nonexistent_id"])
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_gen_test_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(main, ["gen-test", "no_such_trace"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_gen_test_existing_trace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_cli_trace("cli_gen_ok", success=True)
        runner = CliRunner()
        result = runner.invoke(main, ["gen-test", "cli_gen_ok"])
        assert result.exit_code == 0
        assert "Generated" in result.output

    def test_gen_all_tests_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["gen-all-tests"])
        assert result.exit_code == 0
        assert "0 regression tests" in result.output

    def test_gen_all_tests_with_failures(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for i in range(3):
            _make_cli_trace(f"cli_fail_{i}", success=False)
        _make_cli_trace("cli_ok_1", success=True)
        runner = CliRunner()
        result = runner.invoke(main, ["gen-all-tests"])
        assert result.exit_code == 0
        assert "regression tests" in result.output

    def test_search_empty(self):
        runner = CliRunner()
        result = runner.invoke(main, ["search", "zzz_nonexistent_xyz"])
        assert result.exit_code == 0

    def test_search_with_results(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_cli_trace("search_cli", success=False)
        runner = CliRunner()
        result = runner.invoke(main, ["search", "error fail"])
        assert result.exit_code == 0

    def test_trace_diff_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(main, ["trace-diff", "no_a", "--target", "no_b"])
        assert "not found" in result.output or result.exit_code != 0

    def test_stream_start_stop(self):
        runner = CliRunner()
        _make_cli_trace("stream_cli", success=False)
        result = runner.invoke(main, ["stream", "stream_cli", "--duration", "1"])
        assert result.exit_code == 0
        assert "Streaming" in result.output or "ended" in result.output

    def test_show_existing_trace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_cli_trace("show_ok", success=True)
        runner = CliRunner()
        result = runner.invoke(main, ["show", "show_ok"])
        assert result.exit_code == 0

    def test_autopsy_existing_trace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_cli_trace("autopsy_cli", success=False)
        runner = CliRunner()
        result = runner.invoke(main, ["autopsy", "autopsy_cli"])
        assert result.exit_code == 0
