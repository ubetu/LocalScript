#!/usr/bin/env python3
"""
LocalScript agent test runner.

Runs all 8 test cases from resources/LocaScript.md against the live API,
evaluates results with structural checks, and prints a report.

Usage:
    python scripts/test_agent.py [--base-url URL] [--timeout SECS] [--json FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum

import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 600  # seconds per HTTP request


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    id: str
    title: str
    prompt: str
    wf_context: dict | None = None
    existing_code: str | None = None
    expected_patterns: list[str] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)


class Verdict(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    FAIL = "FAIL"


@dataclass
class TestResult:
    case: TestCase
    verdict: Verdict
    raw_code: str = ""
    question: str = ""     # set when agent asks a clarification question
    issues: list[str] = field(default_factory=list)
    static_passed: bool | None = None
    dynamic_success: bool | None = None
    dynamic_output: str | None = None
    error: str = ""        # connection / unexpected error


# ── Test cases ────────────────────────────────────────────────────────────────

CASES: list[TestCase] = [
    TestCase(
        id="2.1",
        title="Last element of array",
        prompt="Из полученного списка email получи последний.",
        wf_context={
            "wf": {
                "vars": {
                    "emails": [
                        "user1@example.com",
                        "user2@example.com",
                        "user3@example.com",
                    ]
                }
            }
        },
        expected_patterns=["wf.vars.emails", "#wf.vars"],
    ),
    TestCase(
        id="2.2",
        title="Attempt counter",
        prompt="Увеличивай значение переменной `try_count_n` на каждой итерации",
        wf_context={"wf": {"vars": {"try_count_n": 3}}},
        expected_patterns=["wf.vars.try_count_n", "+ 1"],
    ),
    TestCase(
        id="2.3",
        title="Clear variable values",
        prompt=(
            "Для полученных данных из предыдущего REST запроса очисти значения "
            "переменных ID, ENTITY_ID, CALL"
        ),
        wf_context={
            "wf": {
                "vars": {
                    "RESTbody": {
                        "result": [
                            {
                                "ID": 123,
                                "ENTITY_ID": 456,
                                "CALL": "example_call_1",
                                "OTHER_KEY_1": "value1",
                                "OTHER_KEY_2": "value2",
                            },
                            {
                                "ID": 789,
                                "ENTITY_ID": 101,
                                "CALL": "example_call_2",
                                "EXTRA_KEY_1": "value3",
                                "EXTRA_KEY_2": "value4",
                            },
                        ]
                    }
                }
            }
        },
        expected_patterns=["wf.vars.RESTbody.result", "nil"],
    ),
    TestCase(
        id="2.4",
        title="ISO 8601 time format",
        prompt=(
            "Преобразуй время из формата `YYYYMMDD` и `HHMMSS` в строку в формате "
            "ISO 8601 с использованием Lua."
        ),
        wf_context={
            "wf": {
                "vars": {
                    "json": {
                        "IDOC": {
                            "ZCDF_HEAD": {
                                "DELIVERY": "123456789",
                                "SUBJECT": "Order Confirmation",
                                "DATUM": "20231015",
                                "TIME": "153000",
                                "STATUS": "Confirmed",
                                "ROUTE": "Route 66",
                                "ROUTE_TXT": "Main Distribution Route",
                                "ZCDF_PACKAGES": [],
                            }
                        }
                    }
                }
            }
        },
        expected_patterns=["wf.vars.json.IDOC.ZCDF_HEAD", "string.format"],
    ),
    TestCase(
        id="2.5",
        title="Ensure items are arrays",
        prompt=(
            "Как преобразовать структуру данных так, чтобы все элементы `items` "
            "в `ZCDF_PACKAGES` всегда были представлены в виде массивов, даже если "
            "они изначально не являются массивами"
        ),
        wf_context={
            "wf": {
                "vars": {
                    "json": {
                        "IDOC": {
                            "ZCDF_HEAD": {
                                "ZCDF_PACKAGES": [
                                    {"items": [{"sku": "A"}, {"sku": "B"}]},
                                    {"items": {"sku": "C"}},
                                ]
                            }
                        }
                    }
                }
            }
        },
        expected_patterns=[
            "wf.vars.json.IDOC.ZCDF_HEAD.ZCDF_PACKAGES",
            "_utils.array",
        ],
    ),
    TestCase(
        id="2.6",
        title="Filter array by field",
        prompt=(
            "Отфильтруй элементы из массива, чтобы включить только те, у которых "
            "есть значения в полях `Discount` или `Markdown`."
        ),
        wf_context={
            "wf": {
                "vars": {
                    "parsedCsv": [
                        {"SKU": "A001", "Discount": "10%", "Markdown": ""},
                        {"SKU": "A002", "Discount": "", "Markdown": "5%"},
                        {"SKU": "A003", "Discount": None, "Markdown": None},
                        {"SKU": "A004", "Discount": "", "Markdown": ""},
                    ]
                }
            }
        },
        expected_patterns=[
            "wf.vars.parsedCsv",
            "_utils.array.new",
            "Discount",
            "Markdown",
        ],
    ),
    TestCase(
        id="2.7",
        title="Add squared variable",
        prompt="Добавь переменную с квадратом числа",
        expected_patterns=["tonumber", "squared"],
        forbidden_patterns=["wf.vars"],
    ),
    TestCase(
        id="2.8",
        title="ISO to Unix timestamp",
        prompt="Конвертируй время в переменной `recallTime` в unix-формат.",
        wf_context={
            "wf": {
                "initVariables": {
                    "recallTime": "2023-10-15T15:30:00+00:00"
                }
            }
        },
        expected_patterns=["wf.initVariables.recallTime", "86400"],
        forbidden_patterns=["365.25", "30.44"],
    ),
]


# ── API helpers ───────────────────────────────────────────────────────────────

def generate(
    client: httpx.Client,
    content: str,
    wf_context: dict | None = None,
    existing_code: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Call POST /generate and return the parsed response."""
    payload: dict = {"content": content}
    if wf_context is not None:
        payload["wf_context"] = wf_context
    if existing_code is not None:
        payload["existing_code"] = existing_code
    if session_id is not None:
        payload["session_id"] = session_id
    resp = client.post("/generate", json=payload)
    resp.raise_for_status()
    return resp.json()


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(case: TestCase, response: dict) -> TestResult:
    question = response.get("question")
    result_obj = response.get("result")

    if question and result_obj is None:
        return TestResult(
            case=case,
            verdict=Verdict.NEEDS_CLARIFICATION,
            question=question,
        )

    if result_obj is None:
        return TestResult(
            case=case,
            verdict=Verdict.FAIL,
            error="Response has no result and no question",
        )

    raw_code = result_obj.get("raw_code", "")
    static = result_obj.get("static_result")
    dynamic = result_obj.get("dynamic_result")

    issues: list[str] = []
    static_passed: bool | None = None
    dynamic_success: bool | None = None
    dynamic_output: str | None = None

    if static is not None:
        static_passed = static.get("passed", False)
        if not static_passed:
            for err in static.get("errors", []):
                msg = err.get("message", {})
                issues.append(
                    f"static error [{err.get('type')}] "
                    f"L{msg.get('line')}: {msg.get('message')}"
                )

    if dynamic is not None:
        dynamic_success = dynamic.get("success", False)
        dynamic_output = dynamic.get("output")
        if not dynamic_success:
            issues.append(f"dynamic error: {dynamic.get('error')}")

    for pattern in case.expected_patterns:
        if pattern not in raw_code:
            issues.append(f"missing expected pattern: '{pattern}'")

    for pattern in case.forbidden_patterns:
        if pattern in raw_code:
            issues.append(f"forbidden pattern found: '{pattern}'")

    if not issues:
        verdict = Verdict.PASS
    elif static_passed is not False and dynamic_success is not False:
        verdict = Verdict.PARTIAL
    else:
        verdict = Verdict.FAIL

    return TestResult(
        case=case,
        verdict=verdict,
        raw_code=raw_code,
        issues=issues,
        static_passed=static_passed,
        dynamic_success=dynamic_success,
        dynamic_output=dynamic_output,
    )


# ── Runner ────────────────────────────────────────────────────────────────────

def run_all(base_url: str, timeout: int) -> list[TestResult]:
    results: list[TestResult] = []

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        for case in CASES:
            print(f"  Running {case.id}: {case.title} ...", end=" ", flush=True)
            try:
                response = generate(
                    client,
                    content=case.prompt,
                    wf_context=case.wf_context,
                    existing_code=case.existing_code,
                )
                result = evaluate(case, response)
            except Exception as exc:
                result = TestResult(
                    case=case,
                    verdict=Verdict.FAIL,
                    error=str(exc),
                )
            results.append(result)
            print(result.verdict)

    return results


# ── Report ────────────────────────────────────────────────────────────────────

_VERDICT_SYMBOL = {
    Verdict.PASS: "✓",
    Verdict.PARTIAL: "~",
    Verdict.NEEDS_CLARIFICATION: "?",
    Verdict.FAIL: "✗",
}

_COL_ID = 5
_COL_TITLE = 32
_COL_VERDICT = 22


def print_report(results: list[TestResult], base_url: str) -> None:
    sep = "─" * (_COL_ID + _COL_TITLE + _COL_VERDICT + 30)
    header = (
        f"{'ID':<{_COL_ID}}"
        f"{'Title':<{_COL_TITLE}}"
        f"{'Verdict':<{_COL_VERDICT}}"
        f"Issues"
    )

    print()
    print("=" * len(sep))
    print("  LocalScript Agent — Test Report")
    print(f"  {base_url}")
    print("=" * len(sep))
    print()
    print(header)
    print(sep)

    for r in results:
        sym = _VERDICT_SYMBOL[r.verdict]
        first_issue = r.issues[0] if r.issues else (r.question if r.question else r.error)
        print(
            f"{r.case.id:<{_COL_ID}}"
            f"{r.case.title:<{_COL_TITLE}}"
            f"{sym} {r.verdict:<{_COL_VERDICT - 2}}"
            f"{first_issue}"
        )

    print(sep)

    counts = {v: sum(1 for r in results if r.verdict == v) for v in Verdict}
    summary_parts = [f"{counts[v]} {v}" for v in Verdict if counts[v]]
    print(f"\nSummary: {', '.join(summary_parts)}\n")

    # Detailed section for non-PASS cases
    non_pass = [r for r in results if r.verdict != Verdict.PASS]
    if non_pass:
        print("─" * len(sep))
        print("  Details for non-PASS cases")
        print("─" * len(sep))
        for r in non_pass:
            print(f"\n[{r.case.id}] {r.case.title}  →  {_VERDICT_SYMBOL[r.verdict]} {r.verdict}")
            if r.question:
                print(f"  Clarification question: {r.question}")
            if r.error:
                print(f"  Error: {r.error}")
            for issue in r.issues:
                print(f"  Issue: {issue}")
            if r.static_passed is not None:
                print(f"  Static check passed: {r.static_passed}")
            if r.dynamic_success is not None:
                print(f"  Dynamic check success: {r.dynamic_success}")
                if r.dynamic_output:
                    print(f"  Dynamic output: {r.dynamic_output}")
            if r.raw_code:
                lines = r.raw_code.splitlines()
                preview = "\n    ".join(lines[:10])
                tail = f"\n    ... ({len(lines) - 10} more lines)" if len(lines) > 10 else ""
                print(f"  raw_code:\n    {preview}{tail}")
        print()


# ── JSON export ───────────────────────────────────────────────────────────────

def results_to_dict(results: list[TestResult]) -> list[dict]:
    out = []
    for r in results:
        out.append({
            "id": r.case.id,
            "title": r.case.title,
            "verdict": str(r.verdict),
            "raw_code": r.raw_code,
            "question": r.question,
            "issues": r.issues,
            "static_passed": r.static_passed,
            "dynamic_success": r.dynamic_success,
            "dynamic_output": r.dynamic_output,
            "error": r.error,
        })
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--json",
        metavar="FILE",
        dest="json_file",
        help="Write full results as JSON to FILE",
    )
    args = parser.parse_args()

    print(f"\nRunning {len(CASES)} test cases against {args.base_url} ...\n")
    results = run_all(args.base_url, args.timeout)
    print_report(results, args.base_url)

    if args.json_file:
        with open(args.json_file, "w") as f:
            json.dump(results_to_dict(results), f, indent=2, ensure_ascii=False)
        print(f"JSON results written to: {args.json_file}")

    any_fail = any(r.verdict in (Verdict.FAIL, Verdict.NEEDS_CLARIFICATION) for r in results)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
