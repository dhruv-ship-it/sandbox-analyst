import pytest

from sandbox_analyst.llm.base import Message
from sandbox_analyst.llm.fake import FakeLLM
from sandbox_analyst.llm.record import CassetteMiss, RecordingLLM, ReplayLLM


def _msg(content: str) -> list[Message]:
    return [Message(role="user", content=content)]


def test_record_then_replay_round_trip(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    real = FakeLLM(["4"], provider="nim", model="gpt-oss-20b")
    recorder = RecordingLLM(real, cassette_path=cassette)

    recorded = recorder.complete(_msg("2 + 2?"), temperature=1.0, top_p=1.0)

    replay = ReplayLLM(cassette, provider="nim", model="gpt-oss-20b")
    replayed = replay.complete(_msg("2 + 2?"), temperature=1.0, top_p=1.0)

    assert replayed == recorded
    assert replayed.text == "4"


def test_replay_miss_on_an_unseen_request(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    real = FakeLLM(["4"], provider="nim", model="gpt-oss-20b")
    RecordingLLM(real, cassette_path=cassette).complete(_msg("2 + 2?"))

    replay = ReplayLLM(cassette, provider="nim", model="gpt-oss-20b")
    with pytest.raises(CassetteMiss):
        replay.complete(_msg("a completely different question"))


def test_replay_miss_against_an_empty_cassette_file(tmp_path):
    cassette = tmp_path / "does_not_exist.jsonl"
    replay = ReplayLLM(cassette, provider="nim", model="gpt-oss-20b")
    with pytest.raises(CassetteMiss):
        replay.complete(_msg("anything"))


def test_different_sampling_params_are_different_cassette_keys(tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    real = FakeLLM(["low", "high"], provider="nim", model="gpt-oss-20b")
    recorder = RecordingLLM(real, cassette_path=cassette)
    recorder.complete(_msg("q"), reasoning_effort="low")
    recorder.complete(_msg("q"), reasoning_effort="high")

    replay = ReplayLLM(cassette, provider="nim", model="gpt-oss-20b")
    assert replay.complete(_msg("q"), reasoning_effort="low").text == "low"
    assert replay.complete(_msg("q"), reasoning_effort="high").text == "high"
