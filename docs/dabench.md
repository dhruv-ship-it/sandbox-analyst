# dabench.md

The InfiAgent-DABench dataset: actual schema, answer format, and
licensing. Numbers and field names below were confirmed by reading the
real downloaded JSONL (`uv run python -m sandbox_analyst.bench.download`),
not assumed from the paper.

## Source and pinning

- Hugging Face dataset repo: `infiagent/DABench` (`repo_type="dataset"`).
- Pinned revision: `b455d578e30fee513abd79936cbdf7a6de026cb5` (resolved
  via `HfApi().dataset_info("infiagent/DABench").sha` on 2026-10-24).
- Downloaded into `data/dabench/` (gitignored, never committed), with
  the Hugging Face cache also kept under `data/.cache/huggingface/` so
  nothing lands on the system drive.
- A `data/dabench/manifest.json` records the pinned revision, a sha256
  per downloaded file, and the verified counts below.

## Verified shape (at the pinned revision)

| Check | Result |
|---|---|
| Questions (`da-dev-questions.jsonl`) | **257** |
| Labels (`da-dev-labels.jsonl`) | **257**, ids match the questions exactly |
| Every question's CSV exists under `da-dev-tables/` | yes |
| Distinct CSVs referenced by questions | **52** |
| CSV files present in `da-dev-tables/` on disk | 68 (16 are unreferenced by any question) |

The download script (`src/sandbox_analyst/bench/download.py`) hardcodes
these counts as its expected values and stops with the actual numbers
on any mismatch -- it never silently adjusts the expectation to match
what it finds.

## Schema

### `da-dev-questions.jsonl` -- one `Question` per line

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | matches a `da-dev-labels.jsonl` row's `id` |
| `question` | `str` | the natural-language question |
| `concepts` | `list[str]` | e.g. `["Summary Statistics"]` |
| `constraints` | `str` | free-text instructions (rounding, methodology) |
| `format` | `str` | the exact answer-tag format the answer must follow |
| `file_name` | `str` | the CSV under `da-dev-tables/` the question is about |
| `level` | `str` | `"easy"` / `"medium"` / `"hard"`; present on all 257 rows |

### `da-dev-labels.jsonl` -- one `Label` per line

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | matches a question's `id` |
| `common_answers` | `list[[str, str]]` | one `[name, value]` pair per sub-answer |

Most questions have a single sub-answer; multi-part questions (e.g.
"mean fare for elderly/adult/teenager/child passengers") have several
`[name, value]` pairs in the same `common_answers` list -- the
distribution across all 257 labels is 1 pair (140), 2 (68), 3 (33), 4
(7), 5 (1), 6 (5), 7 (1), 8 (2).

This project's own loader (`src/sandbox_analyst/bench/dabench.py`)
exposes `common_answers` as `Label.answers: list[tuple[str, str]]` --
a field rename for a clearer name in this codebase, not a schema
change.

## Answer format

Each question's `format` field specifies the exact tag syntax an
answer must use, e.g. `@mean_fare[mean_fare_value] where
"mean_fare_value" is a floating-point number rounded to two decimal
places.` A multi-part question has one `@tag[value]` per sub-answer.
The grader (a later task) parses answers against this tag format, not
free text.

## Dev/test split

Split **by CSV file**, not by question (D-012), with a fixed seed
(`SPLIT_SEED = 2026`, D-041): the 52 distinct files are sorted, then
shuffled with that seed, and files are added to dev until dev's
cumulative question count reaches at least 20% of all 257 questions.
Recorded in `eval/split.json` (committed -- file names and question
ids only, never question or label content):

| Split | Files | Questions | easy | medium | hard |
|---|---|---|---|---|---|
| dev | 11 | 74 | 21 | 25 | 28 |
| test | 41 | 183 | 61 | 62 | 60 |

`load_split("dev")` (`src/sandbox_analyst/bench/split.py`) works
freely. `load_split("test")` raises `SplitLockedError` unless the git
working tree is clean **and** `HEAD` is tagged `frozen-*` -- see
CLAUDE.md's test-set-discipline rule, added once this split existed.

## Licensing

Treated as **CC BY-NC 4.0** per the original InfiAgent-DABench paper
authors' GitHub README, even though the Hugging Face dataset card
itself is tagged Apache-2.0 (D-011) -- the stricter license is
followed. The dataset is never committed to this repo; it is
downloaded by script into a gitignored directory.

## Example question

Taken from the **dev** split only (`id=32`, file
`imp.score.ldlr.metabolome.csv`), per the test-set-discipline rule:

```json
{
  "id": 32,
  "question": "Calculate the mean and standard deviation of the \"importance.score\" column.",
  "concepts": ["Summary Statistics"],
  "constraints": "Calculate the mean and standard deviation to two decimal places for the \"importance.score\" column. Ignore any null or missing values in the calculations. The calculations are to be done using standard statistical methods without applying any transformations or filters to the data.",
  "format": "@importance_score_mean[mean] @importance_score_std[std_dev] where \"mean\" and \"std_dev\" are non-negative numbers rounded to two decimal places.",
  "file_name": "imp.score.ldlr.metabolome.csv",
  "level": "easy"
}
```

Its label (two sub-answers, matching the two `@tag[...]` slots in
`format`):

```json
{
  "id": 32,
  "common_answers": [
    ["importance_score_std", "0.01"],
    ["importance_score_mean", "0.0"]
  ]
}
```
