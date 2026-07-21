"""Tests for the feedback loop system (feedback/loop.py)."""

import json

import pytest

from tardis.feedback.loop import FeedbackEntry, FeedbackLoop
from tardis.models import Step, StepType


class TestFeedbackEntry:
    def test_to_training_pair(self):
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="timeout",
            step_index=3,
            original_prompt="fix this",
            original_response="I don't know",
            suggested_fix="increase timeout",
            confidence=0.8,
            evidence=["e1"],
        )
        pair = entry.to_training_pair()
        assert pair["trace_id"] == "t1"
        assert pair["output"]["corrected_response"] == "increase timeout"

    def test_to_training_pair_with_correction(self):
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="timeout",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="suggested",
            corrected_response="corrected",
        )
        pair = entry.to_training_pair()
        assert pair["output"]["corrected_response"] == "corrected"

    def test_to_negative_pair(self):
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="timeout",
            step_index=0,
            original_prompt="fix this",
            original_response="bad response",
            suggested_fix="better response",
        )
        neg = entry.to_negative_pair()
        assert neg["prompt"] == "fix this"
        assert neg["chosen"] == "better response"
        assert neg["rejected"] == "bad response"

    def test_to_negative_pair_with_correction(self):
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="timeout",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="suggested",
            corrected_response="corrected",
        )
        neg = entry.to_negative_pair()
        assert neg["chosen"] == "corrected"


class TestFeedbackLoop:
    def test_init(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        assert len(loop._entries) == 0

    def test_add_entry(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="timeout",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        assert len(loop._entries) == 1
        assert "t1" in loop._index

    def test_add_entry_saves_to_disk(self, tmp_path):
        storage = tmp_path / "fb"
        loop = FeedbackLoop(storage_dir=str(storage))
        entry = FeedbackEntry(
            trace_id="t2",
            failure_type="error",
            step_index=1,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        files = list(storage.glob("*.json"))
        assert len(files) == 1

    def test_get_entries_for_trace(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        e1 = FeedbackEntry(
            trace_id="t1",
            failure_type="a",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        e2 = FeedbackEntry(
            trace_id="t2",
            failure_type="b",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(e1)
        loop.add_entry(e2)
        assert len(loop.get_entries_for_trace("t1")) == 1
        assert len(loop.get_entries_for_trace("t2")) == 1

    def test_add_from_autopsy(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        step = Step(
            trace_id="t1",
            index=0,
            type=StepType.llm_call,
            input={"kwargs": {"messages": "test prompt"}},
            output={"content": "test response"},
        )
        autopsy_result = {
            "failure_type": "timeout",
            "fix_suggestion": "increase timeout",
            "evidence": ["e1"],
            "confidence": 0.7,
            "summary": "timed out",
        }
        entry = loop.add_from_autopsy("t1", autopsy_result, [step])
        assert entry.failure_type == "timeout"
        assert len(loop._entries) == 1

    def test_export_jsonl(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="error",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        out = str(tmp_path / "export.jsonl")
        loop.export_training_data(out, format="jsonl")
        lines = open(out).read().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert "input" in data

    def test_export_json(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="error",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        out = str(tmp_path / "export.json")
        loop.export_training_data(out, format="json")
        data = json.loads(open(out).read())
        assert isinstance(data, list)

    def test_export_negative_pair(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="error",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        out = str(tmp_path / "neg.jsonl")
        loop.export_training_data(out, format="negative-pair")
        lines = open(out).read().strip().split("\n")
        assert len(lines) == 1

    def test_export_unknown_format(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        with pytest.raises(ValueError, match="Unknown format"):
            loop.export_training_data(str(tmp_path / "x"), format="xml")

    def test_export_fine_tuning_openai(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="error",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        out = str(tmp_path / "ft.jsonl")
        loop.export_fine_tuning_dataset(out, model_format="openai")
        lines = open(out).read().strip().split("\n")
        data = json.loads(lines[0])
        assert "messages" in data

    def test_export_fine_tuning_anthropic(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="error",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        out = str(tmp_path / "ft_anthropic.json")
        loop.export_fine_tuning_dataset(out, model_format="anthropic")
        data = json.loads(open(out).read())
        assert len(data) == 1

    def test_export_fine_tuning_raw(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        entry = FeedbackEntry(
            trace_id="t1",
            failure_type="error",
            step_index=0,
            original_prompt="p",
            original_response="r",
            suggested_fix="f",
        )
        loop.add_entry(entry)
        out = str(tmp_path / "ft_raw.json")
        loop.export_fine_tuning_dataset(out, model_format="raw")
        data = json.loads(open(out).read())
        assert data[0]["prompt"] == "p"

    def test_export_fine_tuning_unknown_format(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        with pytest.raises(ValueError, match="Unknown model format"):
            loop.export_fine_tuning_dataset(str(tmp_path / "x"), model_format="unknown")

    def test_get_statistics(self, tmp_path):
        loop = FeedbackLoop(storage_dir=str(tmp_path / "fb"))
        loop.add_entry(
            FeedbackEntry(
                trace_id="t1",
                failure_type="error",
                step_index=0,
                original_prompt="p",
                original_response="r",
                suggested_fix="f",
                confidence=0.8,
            )
        )
        stats = loop.get_statistics()
        assert stats["total_entries"] == 1
        assert stats["average_confidence"] == 0.8
        assert stats["traces_with_feedback"] == 1

    def test_clear(self, tmp_path):
        storage = tmp_path / "fb"
        loop = FeedbackLoop(storage_dir=str(storage))
        loop.add_entry(
            FeedbackEntry(
                trace_id="t1",
                failure_type="error",
                step_index=0,
                original_prompt="p",
                original_response="r",
                suggested_fix="f",
            )
        )
        loop.clear()
        assert len(loop._entries) == 0
        assert len(list(storage.glob("*.json"))) == 0
