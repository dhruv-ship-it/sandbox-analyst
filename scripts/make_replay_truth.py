"""Host-side pandas ground truth for the replay regression fixtures (tests/replay/).

This is our own trusted analysis code, run once over our own synthetic
example datasets (the same CSVs served by `sandbox_analyst.api.examples`)
to compute the expected answers `tests/replay/test_replay.py` checks
every recorded agent run against -- never model-written code, and never
executed by the agent itself (CLAUDE.md rule 1).

Run with `uv run python scripts/make_replay_truth.py` to (re)write the
"expected" field of every task in tests/replay/tasks.json. Re-run it
whenever tests/replay/tasks.json's questions change, or whenever the
example CSVs themselves change.
"""

import json
from pathlib import Path

import pandas as pd

EXAMPLES_DIR = Path("src/sandbox_analyst/api/examples")
TASKS_PATH = Path("tests/replay/tasks.json")


def _load(file_name: str) -> pd.DataFrame:
    return pd.read_csv(EXAMPLES_DIR / file_name)


def truth_sales_total_revenue() -> dict[str, str]:
    df = _load("sales.csv").dropna(subset=["units"])
    total = float((df["units"] * df["unit_price"]).sum())
    return {"total_revenue": f"{total:.2f}"}


def truth_sales_highest_avg_price_product() -> dict[str, str]:
    df = _load("sales.csv")
    means = df.groupby("product")["unit_price"].mean()
    top = means.idxmax()
    return {"product": top, "avg_price": f"{means[top]:.2f}"}


def truth_sales_west_total_units() -> dict[str, str]:
    df = _load("sales.csv").dropna(subset=["units"])
    total = int(df.loc[df["region"] == "West", "units"].sum())
    return {"west_units": str(total)}


def truth_sales_region_bar_chart() -> dict[str, str]:
    df = _load("sales.csv").dropna(subset=["units"])
    totals = df.groupby("region")["units"].sum()
    return {"top_region": totals.idxmax()}


def truth_students_avg_math_score() -> dict[str, str]:
    df = _load("students.csv")
    mean = float(df.loc[df["subject"] == "Math", "score"].mean())
    return {"avg_math_score": f"{mean:.2f}"}


def truth_students_highest_attendance_class() -> dict[str, str]:
    df = _load("students.csv")
    means = df.groupby("class")["attendance"].mean()
    top = means.idxmax()
    return {"class_name": top, "avg_attendance": f"{means[top]:.2f}"}


def truth_students_score_histogram() -> dict[str, str]:
    df = _load("students.csv")
    return {"n_scores": str(len(df))}


def truth_students_score_attendance_corr() -> dict[str, str]:
    df = _load("students.csv")
    corr = float(df["score"].corr(df["attendance"]))
    return {"correlation": f"{corr:.3f}"}


def truth_weather_avg_temp_mumbai() -> dict[str, str]:
    df = _load("weather.csv")
    mean = float(df.loc[df["city"] == "Mumbai", "temp_c"].mean())
    return {"avg_temp_mumbai": f"{mean:.2f}"}


def truth_weather_most_rainfall_city() -> dict[str, str]:
    df = _load("weather.csv")
    totals = df.groupby("city")["rainfall_mm"].sum()
    top = totals.idxmax()
    std = float(df.loc[df["city"] == top, "temp_c"].std(ddof=1))
    return {"top_city": top, "temp_std": f"{std:.2f}"}


TASK_TRUTH_FUNCS = {
    "sales_total_revenue": truth_sales_total_revenue,
    "sales_highest_avg_price_product": truth_sales_highest_avg_price_product,
    "sales_west_total_units": truth_sales_west_total_units,
    "sales_region_bar_chart": truth_sales_region_bar_chart,
    "students_avg_math_score": truth_students_avg_math_score,
    "students_highest_attendance_class": truth_students_highest_attendance_class,
    "students_score_histogram": truth_students_score_histogram,
    "students_score_attendance_corr": truth_students_score_attendance_corr,
    "weather_avg_temp_mumbai": truth_weather_avg_temp_mumbai,
    "weather_most_rainfall_city": truth_weather_most_rainfall_city,
}


def compute_all() -> dict[str, dict[str, str]]:
    return {task_id: fn() for task_id, fn in TASK_TRUTH_FUNCS.items()}


def main() -> int:
    truth = compute_all()
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    missing = [task["id"] for task in tasks if task["id"] not in truth]
    if missing:
        raise SystemExit(f"no truth function for task id(s): {missing}")
    for task in tasks:
        task["expected"] = truth[task["id"]]
    TASKS_PATH.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {TASKS_PATH} with {len(tasks)} tasks' expected truth")  # noqa: T201
    for task in tasks:
        print(f"  {task['id']}: {task['expected']}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
