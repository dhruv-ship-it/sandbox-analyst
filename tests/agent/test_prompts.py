import re

from sandbox_analyst.agent import prompts
from sandbox_analyst.agent.evidence import EvidenceResult
from sandbox_analyst.guard.checker import Violation
from sandbox_analyst.sandbox.base import ExecError

FORBIDDEN_SUBSTRINGS = ["attempt", "remaining", "last chance", "retries", "tries"]


def _assert_no_attempt_language(text: str) -> None:
    lowered = text.lower()
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in lowered, f"found forbidden phrase {forbidden!r} in: {text!r}"


# ---- code_system_prompt ----


def test_code_system_prompt_names_the_data_path():
    prompt = prompts.code_system_prompt("titanic.csv")
    assert "/work/data/titanic.csv" in prompt


def test_code_system_prompt_lists_allowed_imports():
    prompt = prompts.code_system_prompt("x.csv")
    assert "pandas" in prompt
    assert "numpy" in prompt


def test_code_system_prompt_mentions_untrusted_preview():
    prompt = prompts.code_system_prompt("x.csv")
    assert "untrusted" in prompt.lower()


# ---- build_user_message ----


def test_build_user_message_includes_preview_and_question():
    msg = prompts.build_user_message("PREVIEW BLOCK", "what is the mean?")
    assert "PREVIEW BLOCK" in msg
    assert "what is the mean?" in msg


def test_build_user_message_omits_constraints_and_format_when_not_given():
    msg = prompts.build_user_message("PREVIEW", "q?")
    assert "Constraints" not in msg
    assert "Required output format" not in msg


def test_build_user_message_includes_constraints_and_format_when_given():
    msg = prompts.build_user_message(
        "PREVIEW", "q?", constraints="round to 2 dp", answer_format="@x[value]"
    )
    assert "round to 2 dp" in msg
    assert "@x[value]" in msg


# ---- build_repair_message ----


def test_build_repair_message_includes_previous_code_and_observation():
    msg = prompts.build_repair_message("print(1)", "KeyError: 'x'")
    assert "print(1)" in msg
    assert "KeyError: 'x'" in msg
    assert "```python" in msg


def test_build_repair_message_omits_code_section_when_none():
    msg = prompts.build_repair_message(None, prompts.observation_no_code_block())
    assert "Your previous script" not in msg
    assert "no python code block found" in msg


# ---- observation builders ----


def test_observation_no_code_block_text():
    assert prompts.observation_no_code_block() == "no python code block found"


def test_observation_for_checker_violations_lists_each_one():
    violations = [
        Violation("IMPORT_NOT_ALLOWED", 3, 0, "import of `os` is blocked"),
        Violation("FORBIDDEN_CALL", 5, 2, "`eval` is blocked"),
    ]
    text = prompts.observation_for_checker_violations(violations)
    assert "IMPORT_NOT_ALLOWED" in text
    assert "import of `os` is blocked" in text
    assert "FORBIDDEN_CALL" in text
    assert "line 3" in text
    assert "line 5" in text


def test_observation_for_exec_error_includes_name_value_traceback_and_stdout_tail():
    error = ExecError(name="KeyError", value="'col'", traceback="line1\nline2\nKeyError: 'col'")
    text = prompts.observation_for_exec_error(error, "some stdout output\n")
    assert "KeyError" in text
    assert "'col'" in text
    assert "line1" in text
    assert "some stdout output" in text


def test_observation_for_exec_error_caps_the_traceback_to_last_15_lines():
    traceback_text = "\n".join(f"line{i}" for i in range(30))
    error = ExecError(name="ValueError", value="bad", traceback=traceback_text)
    text = prompts.observation_for_exec_error(error, "")
    assert "line0" not in text
    assert "line29" in text


def test_observation_for_exec_error_caps_stdout_to_last_2000_chars():
    long_stdout = "x" * 5000
    error = ExecError(name="ValueError", value="bad", traceback="tb")
    text = prompts.observation_for_exec_error(error, long_stdout)
    assert len(text) < 5000 + 200
    assert "x" * 100 in text  # the tail is still present


def test_observation_for_timeout_mentions_timeout():
    assert "timeout" in prompts.observation_for_timeout().lower()


def test_observation_for_crash_matches_the_exact_required_wording():
    text = prompts.observation_for_crash()
    assert text == (
        "your script was killed, most likely for exceeding the 2 GiB memory limit; use less memory"
    )


def test_observation_for_evidence_failure_lists_only_failed_answers():
    results = [
        EvidenceResult(name="a", value="1", passed=True, reason="matched"),
        EvidenceResult(name="b", value="2", passed=False, reason="no number in stdout matches"),
    ]
    text = prompts.observation_for_evidence_failure(results)
    assert "b" in text
    assert "no number in stdout matches" in text
    assert "a=" not in text


# ---- answer prompts ----


def test_build_answer_message_includes_question_code_and_stdout():
    msg = prompts.build_answer_message("what is x?", "print('x')", "x = 1\n")
    assert "what is x?" in msg
    assert "print('x')" in msg
    assert "x = 1" in msg


def test_build_answer_message_includes_constraints_and_format_when_given():
    msg = prompts.build_answer_message(
        "q?", "code", "out", constraints="round to 2dp", answer_format="@x[value]"
    )
    assert "round to 2dp" in msg
    assert "@x[value]" in msg


def test_build_answer_message_caps_stdout_to_4000_chars():
    long_stdout = "@" * 10000
    msg = prompts.build_answer_message("q?", "code", long_stdout)
    assert msg.count("@") == prompts.ANSWER_STDOUT_CAP


def test_build_answer_retry_message_includes_previous_reply_and_error():
    msg = prompts.build_answer_retry_message("not json", "no JSON object found")
    assert "not json" in msg
    assert "no JSON object found" in msg


# ---- the no-attempt-count rule, across every message this module can build ----


def test_no_message_ever_reveals_attempt_count():
    violation = Violation("IMPORT_NOT_ALLOWED", 1, 0, "import of `os` is blocked")
    error = ExecError(name="KeyError", value="'col'", traceback="tb line")
    evidence_results = [
        EvidenceResult(name="a", value="1", passed=False, reason="no number in stdout matches")
    ]

    messages = [
        prompts.code_system_prompt("data.csv"),
        prompts.ANSWER_SYSTEM_PROMPT,
        prompts.build_user_message("PREVIEW", "q?", constraints="c", answer_format="@x[value]"),
        prompts.build_user_message("PREVIEW", "q?"),
        prompts.build_repair_message("print(1)", prompts.observation_no_code_block()),
        prompts.build_repair_message(None, prompts.observation_no_code_block()),
        prompts.build_repair_message(
            "print(1)", prompts.observation_for_checker_violations([violation])
        ),
        prompts.build_repair_message("print(1)", prompts.observation_for_exec_error(error, "x")),
        prompts.build_repair_message("print(1)", prompts.observation_for_timeout()),
        prompts.build_repair_message("print(1)", prompts.observation_for_crash()),
        prompts.build_repair_message(
            "print(1)", prompts.observation_for_evidence_failure(evidence_results)
        ),
        prompts.build_answer_message(
            "q?", "print(1)", "out", constraints="c", answer_format="@x[value]"
        ),
        prompts.build_answer_retry_message("bad reply", "no JSON object found"),
    ]

    for msg in messages:
        _assert_no_attempt_language(msg)


def test_prompt_version_is_a_plain_version_string():
    assert re.fullmatch(r"v\d+", prompts.PROMPT_VERSION)
