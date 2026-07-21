import pathlib
import time

import pytest

from tardis.models import FailureType, Step, StepType, Trace
from tardis.regression.generator import (
    RegressionTestGenerator,
    RegressionTestSuite,
    TestCase,
    _extract_step_hashes,
    _generate_test_code,
    _generate_test_digest,
    _trace_to_test_filename,
)


def _make_failed_trace(tmp_path, trace_id="reg_test_fail_01"):
    from tardis.store.sqlite_store import Store

    store = Store()
    store.conn.execute("DELETE FROM steps WHERE trace_id=?", (trace_id,))
    store.conn.execute("DELETE FROM traces WHERE id=?", (trace_id,))
    store.conn.commit()

    trace = Trace(id=trace_id, success=False)
    trace.failure_type = FailureType.tool_failure
    trace.add_step(
        Step(trace_id=trace.id, index=0, type=StepType.llm_call,
             input={"kwargs": {"messages": [{"role": "user", "content": "do it"}]}},
             output={"content": "ok"}, duration_ms=100, hash="hash_a",
             token_count={"total_tokens": 50}, cost_usd=0.001, model_name="gpt-4o")
    )
    trace.add_step(
        Step(trace_id=trace.id, index=1, type=StepType.tool_call,
             input={"name": "read_file", "path": "/data"},
             output={"error": "permission denied"}, duration_ms=50, hash="hash_b",
             success=False, error_type="permission")
    )
    trace.add_step(
        Step(trace_id=trace.id, index=2, type=StepType.error,
             input={}, output={"error": "permission denied"},
             hash="hash_c", success=False, error_type="permission")
    )
    store.save_trace(trace)
    return trace


def _make_successful_trace(tmp_path, trace_id="reg_test_ok_01"):
    from tardis.store.sqlite_store import Store

    store = Store()
    store.conn.execute("DELETE FROM steps WHERE trace_id=?", (trace_id,))
    store.conn.execute("DELETE FROM traces WHERE id=?", (trace_id,))
    store.conn.commit()

    trace = Trace(id=trace_id, success=True)
    trace.add_step(
        Step(trace_id=trace.id, index=0, type=StepType.llm_call,
             input={}, output={}, hash="hash_a")
    )
    store.save_trace(trace)
    return trace


class TestUtilities:
    def test_trace_to_test_filename(self):
        name = _trace_to_test_filename("abc-123_def")
        assert name == "regression_test_abc-123_def.py"
        assert name.endswith(".py")

    def test_extract_step_hashes(self):
        trace = Trace()
        trace.add_step(Step(trace_id="t", index=0, type=StepType.llm_call,
                            input={}, output={}, hash="h1"))
        trace.add_step(Step(trace_id="t", index=1, type=StepType.tool_call,
                            input={}, output={}, hash="h2"))
        hashes = _extract_step_hashes(trace)
        assert hashes == ["h1", "h2"]

    def test_extract_step_hashes_skips_none(self):
        trace = Trace()
        trace.add_step(Step(trace_id="t", index=0, type=StepType.llm_call,
                            input={}, output={}, hash=None))
        hashes = _extract_step_hashes(trace)
        assert hashes == []

    def test_generate_test_digest_consistent(self):
        trace = Trace(id="stable_id")
        trace.add_step(Step(trace_id="t", index=0, type=StepType.llm_call,
                            input={}, output={}, hash="a"))
        d1 = _generate_test_digest(trace)
        d2 = _generate_test_digest(trace)
        assert d1 == d2
        assert len(d1) == 16

    def test_generate_test_digest_changes_on_modification(self):
        trace_a = Trace(id="id")
        trace_a.add_step(Step(trace_id="t", index=0, type=StepType.llm_call,
                              input={}, output={}, hash="a"))
        trace_b = Trace(id="id")
        trace_b.add_step(Step(trace_id="t", index=0, type=StepType.llm_call,
                              input={}, output={}, hash="b"))
        assert _generate_test_digest(trace_a) != _generate_test_digest(trace_b)


class TestGenerateTestCode:
    def test_generates_valid_python(self):
        trace = _make_failed_trace(None, "code_gen_01")
        code = _generate_test_code(trace, ".tardis/regression_tests")
        compile(code, "<test>", "exec")
        assert "class TestRegression_code_gen_01" in code
        assert "def test_replay_completes" in code
        assert "def test_autopsy_classifies" in code

    def test_includes_trace_id_in_class(self):
        trace = _make_failed_trace(None, "my_trace_42")
        code = _generate_test_code(trace, ".tardis/regression_tests")
        assert "TestRegression_my_trace_42" in code

    def test_includes_step_count_check(self):
        trace = _make_failed_trace(None, "step_count_01")
        code = _generate_test_code(trace, ".tardis/regression_tests")
        assert "assert len(trace.steps) == 3" in code

    def test_includes_failure_type_assertion(self):
        trace = _make_failed_trace(None, "ftype_01")
        trace.failure_type = FailureType.tool_failure
        code = _generate_test_code(trace, ".tardis/regression_tests")
        assert 'assert ftype.value == "tool_failure"' in code

    def test_handles_unknown_failure_type(self):
        trace = _make_failed_trace(None, "unknown_ftype")
        trace.failure_type = None
        code = _generate_test_code(trace, ".tardis/regression_tests")
        compile(code, "<test>", "exec")

    def test_handles_empty_trace(self):
        trace = Trace(id="empty_trace")
        code = _generate_test_code(trace, ".tardis/regression_tests")
        compile(code, "<test>", "exec")


class TestTestCase:
    def test_testcase_creation(self):
        tc = TestCase(name="TestFoo", source="print('hi')", trace_id="abc", digest="d1")
        assert tc.name == "TestFoo"
        assert tc.digest == "d1"
        assert tc.test_file == ""

    def test_testcase_defaults(self):
        tc = TestCase(name="T", source="", trace_id="t", digest="d")
        assert tc.created_at > 0


class TestRegressionTestSuite:
    def test_creation_creates_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        suite = RegressionTestSuite(output_dir=str(tmp_path / "reg"))
        assert (tmp_path / "reg").exists()
        assert suite.get_test_count() == 0

    def test_list_tests_returns_empty_when_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        suite = RegressionTestSuite(output_dir=str(tmp_path / "reg"))
        assert suite.list_tests() == []

    def test_get_test_count(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        suite = RegressionTestSuite(output_dir=str(tmp_path / "reg"))
        (tmp_path / "reg" / "regression_test_a.py").write_text("# trace:t1")
        (tmp_path / "reg" / "regression_test_b.py").write_text("# trace:t2")
        assert suite.get_test_count() == 2

    def test_remove_test_by_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        suite = RegressionTestSuite(output_dir=str(tmp_path / "reg"))
        f = tmp_path / "reg" / "regression_test_abc.py"
        f.write_text("# trace:abc")
        assert suite.remove_test("abc") is True
        assert not f.exists()

    def test_remove_test_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        suite = RegressionTestSuite(output_dir=str(tmp_path / "reg"))
        assert suite.remove_test("nonexistent") is False


class TestRegressionTestGenerator:
    def test_generate_from_trace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_failed_trace(tmp_path, "gen_from_trace")
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=True)
        case = gen.generate_from_trace("gen_from_trace")
        assert case.trace_id == "gen_from_trace"
        assert pathlib.Path(case.test_file).exists()
        assert case.digest is not None

    def test_generate_from_missing_trace_raises(self, tmp_path):
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "non_existent"))
        with pytest.raises(ValueError, match="not found"):
            gen.generate_from_trace("no_such_trace")

    def test_generate_from_trace_object(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        trace = _make_failed_trace(tmp_path, "obj_test")
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=True)
        case = gen.generate_from_trace_object(trace)
        assert case.trace_id == "obj_test"
        assert pathlib.Path(case.test_file).exists()

    def test_overwrite_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_failed_trace(tmp_path, "overwrite_test")
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=False)
        case1 = gen.generate_from_trace("overwrite_test")
        size1 = pathlib.Path(case1.test_file).stat().st_size
        gen2 = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=False)
        case2 = gen2.generate_from_trace("overwrite_test")
        size2 = pathlib.Path(case2.test_file).stat().st_size
        assert size1 == size2

    def test_generate_from_all_failed_traces(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_failed_trace(tmp_path, "failed_01")
        _make_successful_trace(tmp_path, "ok_01")
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=True)
        cases = gen.generate_from_all_failed_traces(limit=10)
        ids = [c.trace_id for c in cases]
        assert "failed_01" in ids
        assert "ok_01" not in ids

    def test_generated_test_compiles_and_imports(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_failed_trace(tmp_path, "compile_check")
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=True)
        case = gen.generate_from_trace("compile_check")
        source = pathlib.Path(case.test_file).read_text()
        compile(source, "test.py", "exec")

    def test_digest_matches_on_regeneration(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _make_failed_trace(tmp_path, "digest_check")
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=False)
        case1 = gen.generate_from_trace("digest_check")
        time.sleep(0.01)
        gen2 = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=False)
        case2 = gen2.generate_from_trace("digest_check")
        assert case1.digest == case2.digest

    def test_generates_for_multiple_traces(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for i in range(5):
            _make_failed_trace(tmp_path, f"multi_{i}")
        gen = RegressionTestGenerator(output_dir=str(tmp_path / "reg"), overwrite=True)
        cases = gen.generate_from_all_failed_traces(limit=10)
        assert len(cases) == 5
