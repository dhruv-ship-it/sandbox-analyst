"""`run_redteam`: the one entry point that ties every category and the layer-isolation
measurements together, and writes `runs/redteam/<run-name>/report.{md,json}`.
"""

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sandbox_analyst.llm import LLMClient, make_llm
from sandbox_analyst.sandbox import Sandbox, make_sandbox

from . import category_a, category_b, category_c, category_d, layer_isolation, report
from .canary import generate_canary, install_canary, uninstall_canary

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings

DEFAULT_OUT_DIR = Path("runs/redteam")


@dataclass(frozen=True)
class RedteamOutcome:
    run_name: str
    run_dir: Path
    report: dict
    md_path: Path
    json_path: Path


def run_redteam(
    *,
    run_name: str,
    settings: "Settings",
    llm: LLMClient | None = None,
    sandbox_factory: Callable[[], Sandbox] | None = None,
    concurrency: int = 1,
    out_dir: Path = DEFAULT_OUT_DIR,
    category_a_cases_path: Path = category_a.DEFAULT_CASES_PATH,
    category_a_data_path: Path = category_a.DEFAULT_DATA_PATH,
    category_b_cases_path: Path = category_b.DEFAULT_CASES_PATH,
    category_b_base_dir: Path = category_b.DEFAULT_BASE_DIR,
    known_bad_path: Path = layer_isolation.DEFAULT_KNOWN_BAD_PATH,
) -> RedteamOutcome:
    shared_llm = llm if llm is not None else make_llm(settings)
    build_sandbox = (
        sandbox_factory if sandbox_factory is not None else (lambda: make_sandbox(settings))
    )

    canary = generate_canary()
    canary_path = install_canary(canary)
    try:
        a_pairs = category_a.run_category_a_with_agent_results(
            category_a.load_category_a_cases(category_a_cases_path),
            llm=shared_llm,
            sandbox_factory=build_sandbox,
            settings=settings,
            canary=canary,
            data_path=category_a_data_path,
            concurrency=concurrency,
        )
        a_results = [case_result for case_result, _ in a_pairs]
        a_agent_results = [agent_result for _, agent_result in a_pairs]

        b_results = category_b.run_category_b(
            category_b.load_category_b_cases(category_b_cases_path),
            llm=shared_llm,
            sandbox_factory=build_sandbox,
            settings=settings,
            canary=canary,
            base_dir=category_b_base_dir,
            concurrency=concurrency,
        )

        c_results = category_c.run_category_c(settings=settings, canary=canary)

        with tempfile.TemporaryDirectory(prefix="sa_redteam_d_") as tmp_dir:
            d_results = category_d.run_category_d(Path(tmp_dir), settings=settings)

        sandbox_only_results = layer_isolation.run_sandbox_only_layer(
            a_agent_results, build_sandbox, canary
        )

        known_bad = layer_isolation.load_known_bad_snippets(known_bad_path)
        known_bad_blocked = layer_isolation.run_checker_only(
            [(c["id"], c["code"]) for c in known_bad]
        )
        category_a_scripts = layer_isolation.every_generated_code(a_agent_results)
        category_a_blocked = layer_isolation.run_checker_only(category_a_scripts)

        checker_only_category_a_rate = (
            sum(category_a_blocked.values()) / len(category_a_blocked)
            if category_a_blocked
            else 0.0
        )
        checker_only_known_bad_rate = (
            sum(known_bad_blocked.values()) / len(known_bad_blocked) if known_bad_blocked else 0.0
        )

        report_dict = report.build_report(
            category_a=a_results,
            category_b=b_results,
            category_c=c_results,
            category_d=d_results,
            sandbox_only_results=sandbox_only_results,
            checker_only_category_a_block_rate=checker_only_category_a_rate,
            checker_only_known_bad_block_rate=checker_only_known_bad_rate,
        )
        run_dir = out_dir / run_name
        md_path, json_path = report.write_report(report_dict, run_name, run_dir)
    finally:
        uninstall_canary(canary_path)

    return RedteamOutcome(
        run_name=run_name, run_dir=run_dir, report=report_dict, md_path=md_path, json_path=json_path
    )
