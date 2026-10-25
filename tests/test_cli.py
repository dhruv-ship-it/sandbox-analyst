import logging
import logging.config

import pytest

from sandbox_analyst.bench.dabench import Question
from sandbox_analyst.cli import build_parser, configure_app_logging, select_smoke_questions


def _questions(level_counts: dict[str, int]) -> list[Question]:
    questions = []
    next_id = 0
    for level, count in level_counts.items():
        for _ in range(count):
            questions.append(
                Question(
                    id=next_id,
                    question="q",
                    concepts=[],
                    constraints="c",
                    format="f",
                    file_name=f"{level}-{next_id}.csv",
                    level=level,
                )
            )
            next_id += 1
    return questions


# ---- argument parsing ----


def test_ask_parses_csv_path_and_question():
    args = build_parser().parse_args(["ask", "data.csv", "what is the mean?"])
    assert args.command == "ask"
    assert args.csv_path == "data.csv"
    assert args.question == "what is the mean?"


def test_dabench_smoke_defaults():
    args = build_parser().parse_args(["dabench-smoke"])
    assert args.command == "dabench-smoke"
    assert args.n == 5
    assert args.seed == 2026


def test_dabench_smoke_accepts_explicit_n_and_seed():
    args = build_parser().parse_args(["dabench-smoke", "--n", "10", "--seed", "7"])
    assert args.n == 10
    assert args.seed == 7


def test_no_command_is_an_error():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_dabench_smoke_rejects_an_unrecognized_split_option():
    # There must be no way to ask this CLI to touch the held-out test split.
    with pytest.raises(SystemExit):
        build_parser().parse_args(["dabench-smoke", "--split", "test"])


def test_eval_parses_defaults():
    args = build_parser().parse_args(["eval", "--run-name", "r1"])
    assert args.command == "eval"
    assert args.split == "dev"
    assert args.run_name == "r1"
    assert args.concurrency == 6
    assert args.limit is None
    assert args.final_held_out_run is False


def test_eval_requires_run_name():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["eval"])


def test_eval_accepts_test_split_and_final_held_out_run_flag():
    args = build_parser().parse_args(
        ["eval", "--split", "test", "--run-name", "r1", "--final-held-out-run"]
    )
    assert args.split == "test"
    assert args.final_held_out_run is True


def test_report_parses_one_or_more_run_names():
    args = build_parser().parse_args(["report", "r1", "r2", "r3"])
    assert args.command == "report"
    assert args.run_names == ["r1", "r2", "r3"]


def test_report_requires_at_least_one_run_name():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["report"])


# ---- select_smoke_questions ----


def test_select_smoke_questions_spreads_2_2_1_for_n_5():
    questions = _questions({"easy": 10, "medium": 10, "hard": 10})
    selected = select_smoke_questions(questions, n=5, seed=2026)
    by_level = {"easy": 0, "medium": 0, "hard": 0}
    for q in selected:
        by_level[q.level] += 1
    assert by_level == {"easy": 2, "medium": 2, "hard": 1}
    assert len(selected) == 5


def test_select_smoke_questions_is_deterministic_for_a_fixed_seed():
    questions = _questions({"easy": 10, "medium": 10, "hard": 10})
    first = select_smoke_questions(questions, n=5, seed=2026)
    second = select_smoke_questions(questions, n=5, seed=2026)
    assert [q.id for q in first] == [q.id for q in second]


def test_select_smoke_questions_different_seeds_can_select_differently():
    questions = _questions({"easy": 10, "medium": 10, "hard": 10})
    a = select_smoke_questions(questions, n=5, seed=1)
    b = select_smoke_questions(questions, n=5, seed=2)
    assert [q.id for q in a] != [q.id for q in b]


def test_select_smoke_questions_even_split_for_n_divisible_by_3():
    questions = _questions({"easy": 10, "medium": 10, "hard": 10})
    selected = select_smoke_questions(questions, n=6, seed=2026)
    by_level = {"easy": 0, "medium": 0, "hard": 0}
    for q in selected:
        by_level[q.level] += 1
    assert by_level == {"easy": 2, "medium": 2, "hard": 2}


def test_select_smoke_questions_raises_when_a_level_is_short():
    questions = _questions({"easy": 1, "medium": 10, "hard": 10})
    with pytest.raises(ValueError, match="easy"):
        select_smoke_questions(questions, n=5, seed=2026)


def test_select_smoke_questions_ignores_questions_outside_the_given_pool():
    # Simulates "dev-only": questions not passed in at all can never be selected.
    dev_questions = _questions({"easy": 2, "medium": 2, "hard": 1})
    selected = select_smoke_questions(dev_questions, n=5, seed=2026)
    dev_ids = {q.id for q in dev_questions}
    assert all(q.id in dev_ids for q in selected)
    assert len(selected) == 5


# ---- app logging (CLAUDE.md "make unexpected failures loud") ----


@pytest.fixture
def clean_app_logger():
    """Save/restore the `sandbox_analyst` logger's state around a test that reconfigures it."""
    app_logger = logging.getLogger("sandbox_analyst")
    saved_handlers = list(app_logger.handlers)
    saved_level = app_logger.level
    saved_propagate = app_logger.propagate
    app_logger.handlers.clear()
    try:
        yield app_logger
    finally:
        app_logger.handlers = saved_handlers
        app_logger.setLevel(saved_level)
        app_logger.propagate = saved_propagate


def test_configure_app_logging_sends_app_logs_to_stdout(clean_app_logger, capsys):
    configure_app_logging()
    logging.getLogger("sandbox_analyst.api.runs").error("boom")

    assert "boom" in capsys.readouterr().out


def test_uvicorns_own_log_config_does_not_remove_the_app_logging_handler(clean_app_logger):
    import uvicorn.config

    configure_app_logging()
    handler_before = clean_app_logger.handlers[0]

    # disable_existing_loggers: False (uvicorn's own default) must leave a
    # logger it never names -- "sandbox_analyst" -- completely untouched.
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)

    assert clean_app_logger.handlers == [handler_before]
    assert clean_app_logger.disabled is False
