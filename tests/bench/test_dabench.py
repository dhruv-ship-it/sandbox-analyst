import json

from sandbox_analyst.bench.dabench import Label, Question, load_labels, load_questions


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_load_questions_from_tiny_synthetic_fixture(tmp_path):
    path = tmp_path / "questions.jsonl"
    _write_jsonl(
        path,
        [
            {
                "id": 1,
                "question": "What is the mean of x?",
                "concepts": ["Summary Statistics"],
                "constraints": "Round to 2 decimal places.",
                "format": "@mean[value]",
                "file_name": "toy.csv",
                "level": "easy",
            }
        ],
    )
    questions = load_questions(path)
    assert questions == [
        Question(
            id=1,
            question="What is the mean of x?",
            concepts=["Summary Statistics"],
            constraints="Round to 2 decimal places.",
            format="@mean[value]",
            file_name="toy.csv",
            level="easy",
        )
    ]


def test_load_questions_level_defaults_to_none_when_absent(tmp_path):
    path = tmp_path / "questions.jsonl"
    _write_jsonl(
        path,
        [
            {
                "id": 2,
                "question": "q",
                "concepts": [],
                "constraints": "c",
                "format": "f",
                "file_name": "toy.csv",
            }
        ],
    )
    assert load_questions(path)[0].level is None


def test_load_questions_skips_blank_lines(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text(
        '{"id": 1, "question": "q", "concepts": [], "constraints": "c", '
        '"format": "f", "file_name": "toy.csv"}\n\n   \n',
        encoding="utf-8",
    )
    assert len(load_questions(path)) == 1


def test_load_labels_single_answer(tmp_path):
    path = tmp_path / "labels.jsonl"
    _write_jsonl(path, [{"id": 1, "common_answers": [["mean", "34.65"]]}])
    assert load_labels(path) == [Label(id=1, answers=[("mean", "34.65")])]


def test_load_labels_multi_part_answer(tmp_path):
    path = tmp_path / "labels.jsonl"
    _write_jsonl(
        path,
        [
            {
                "id": 6,
                "common_answers": [
                    ["mean_fare_elderly", "43.47"],
                    ["mean_fare_adult", "35.17"],
                ],
            }
        ],
    )
    labels = load_labels(path)
    assert labels[0].answers == [("mean_fare_elderly", "43.47"), ("mean_fare_adult", "35.17")]
