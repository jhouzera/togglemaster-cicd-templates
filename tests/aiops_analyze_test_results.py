#!/usr/bin/env python3
"""Generate AIOps test analysis artifacts (JSON report + JSON schema + Markdown summary).

This script is intentionally deterministic: it does not call external AI services.
It prepares structured evidence so a later Gemini-enabled step can consume it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple


SCHEMA: Dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://togglemaster.dev/schemas/aiops-test-analysis.json",
    "title": "AIOps Test Analysis Report",
    "type": "object",
    "required": [
        "report_version",
        "generated_at",
        "service",
        "workflow",
        "result",
        "signals",
        "recommendations",
    ],
    "properties": {
        "report_version": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "service": {
            "type": "object",
            "required": ["name", "language", "path"],
            "properties": {
                "name": {"type": "string"},
                "language": {"type": "string"},
                "path": {"type": "string"},
            },
        },
        "workflow": {
            "type": "object",
            "required": ["repository", "run_id", "run_attempt", "sha", "ref"],
            "properties": {
                "repository": {"type": "string"},
                "run_id": {"type": "string"},
                "run_attempt": {"type": "string"},
                "sha": {"type": "string"},
                "ref": {"type": "string"},
            },
        },
        "result": {
            "type": "object",
            "required": ["status", "severity", "confidence"],
            "properties": {
                "status": {"type": "string", "enum": ["pass", "fail"]},
                "severity": {"type": "string", "enum": ["none", "low", "medium", "high", "critical"]},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        },
        "signals": {
            "type": "object",
            "required": ["test_outcome", "lint_outcome", "matched_patterns", "missing_inputs"],
            "properties": {
                "test_outcome": {"type": "string"},
                "lint_outcome": {"type": "string"},
                "matched_patterns": {"type": "array", "items": {"type": "string"}},
                "missing_inputs": {"type": "array", "items": {"type": "string"}},
                "files": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "required": ["path", "exists", "size_bytes"],
                        "properties": {
                            "path": {"type": "string"},
                            "exists": {"type": "boolean"},
                            "size_bytes": {"type": "integer", "minimum": 0},
                        },
                    },
                },
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["priority", "action"],
                "properties": {
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                    "action": {"type": "string"},
                },
            },
        },
        "evidence_excerpt": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


PATTERNS: List[Tuple[str, str, str]] = [
    ("timeout", r"timeout|timed out|deadline exceeded", "P1"),
    ("network", r"connection refused|no such host|temporary failure|503|502|504", "P1"),
    ("assertion", r"assert|expected .* got|FAIL", "P1"),
    ("dependency", r"module not found|no required module|cannot find package|import error", "P1"),
    ("auth", r"unauthorized|forbidden|permission denied|access denied", "P1"),
    ("flake", r"flaky|intermittent|race", "P2"),
]


def read_text(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def file_meta(path: str) -> Dict[str, object]:
    p = Path(path)
    if not p.is_file():
        return {"path": path, "exists": False, "size_bytes": 0}
    return {"path": path, "exists": True, "size_bytes": p.stat().st_size}


def match_patterns(text: str) -> List[str]:
    hits: List[str] = []
    lowered = text.lower()
    for name, pattern, _prio in PATTERNS:
        if re.search(pattern, lowered):
            hits.append(name)
    return hits


def recommendations(status: str, pattern_hits: List[str], missing_inputs: List[str]) -> List[Dict[str, str]]:
    recs: List[Dict[str, str]] = []

    if missing_inputs:
        recs.append({
            "priority": "P1",
            "action": "Publicar logs de teste/lint completos para ampliar contexto de diagnostico AIOps.",
        })

    if status == "pass":
        recs.append({
            "priority": "P3",
            "action": "Armazenar este artefato como baseline para comparação de regressões futuras.",
        })
        return recs

    if "dependency" in pattern_hits:
        recs.append({
            "priority": "P1",
            "action": "Revisar lockfile e instalação de dependências na etapa de validação.",
        })
    if "network" in pattern_hits or "timeout" in pattern_hits:
        recs.append({
            "priority": "P1",
            "action": "Validar dependências externas (serviços, endpoints, DNS) e aumentar observabilidade de latência.",
        })
    if "auth" in pattern_hits:
        recs.append({
            "priority": "P1",
            "action": "Verificar variáveis/secrets de autenticação e permissões OIDC/IRSA no ambiente de execução.",
        })
    if "assertion" in pattern_hits:
        recs.append({
            "priority": "P1",
            "action": "Inspecionar mudanças recentes no código do serviço e nos contratos de API testados.",
        })

    if not recs:
        recs.append({
            "priority": "P2",
            "action": "Coletar stack traces completos e executar rerun controlado para diferenciar regressão de instabilidade.",
        })

    return recs


def severity(status: str, hits: List[str]) -> str:
    if status == "pass":
        return "none"
    if "auth" in hits or "dependency" in hits:
        return "high"
    if "timeout" in hits or "network" in hits or "assertion" in hits:
        return "medium"
    return "low"


def confidence(status: str, hits: List[str], missing: List[str]) -> float:
    base = 0.85 if status == "fail" else 0.95
    if missing:
        base -= 0.25
    if not hits and status == "fail":
        base -= 0.20
    return max(0.10, min(0.99, round(base, 2)))


def write_markdown(report: Dict[str, object], output_md: Path) -> None:
    result = report["result"]
    signals = report["signals"]
    recs = report["recommendations"]
    evidence = report.get("evidence_excerpt", [])

    lines = [
        "# AIOps Test Analysis",
        "",
        f"- Service: {report['service']['name']} ({report['service']['language']})",
        f"- Path: {report['service']['path']}",
        f"- Status: **{result['status'].upper()}**",
        f"- Severity: **{result['severity']}**",
        f"- Confidence: **{result['confidence']}**",
        "",
        "## Signals",
        f"- Test outcome: {signals['test_outcome']}",
        f"- Lint outcome: {signals['lint_outcome']}",
        f"- Matched patterns: {', '.join(signals['matched_patterns']) if signals['matched_patterns'] else 'none'}",
        f"- Missing inputs: {', '.join(signals['missing_inputs']) if signals['missing_inputs'] else 'none'}",
        "",
        "## Recommended Actions",
    ]

    for item in recs:
        lines.append(f"- {item['priority']}: {item['action']}")

    if evidence:
        lines.extend(["", "## Evidence Excerpt", "```text"])
        lines.extend(evidence)
        lines.append("```")

    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-name", required=True)
    parser.add_argument("--service-language", required=True)
    parser.add_argument("--service-path", required=True)
    parser.add_argument("--test-outcome", default="unknown")
    parser.add_argument("--lint-outcome", default="unknown")
    parser.add_argument("--test-log", default="")
    parser.add_argument("--lint-log", default="")
    parser.add_argument("--output-dir", default=".aiops")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    test_text = read_text(args.test_log) if args.test_log else ""
    lint_text = read_text(args.lint_log) if args.lint_log else ""
    combined = "\n".join([test_text, lint_text]).strip()

    missing_inputs: List[str] = []
    if args.test_log and not Path(args.test_log).is_file():
        missing_inputs.append("test_log")
    if args.lint_log and not Path(args.lint_log).is_file():
        missing_inputs.append("lint_log")

    status = "pass"
    if args.test_outcome != "success" or args.lint_outcome not in ("success", "skipped"):
        status = "fail"

    hits = match_patterns(combined)
    report = {
        "report_version": "1.0.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "service": {
            "name": args.service_name,
            "language": args.service_language,
            "path": args.service_path,
        },
        "workflow": {
            "repository": os.getenv("GITHUB_REPOSITORY", "unknown"),
            "run_id": os.getenv("GITHUB_RUN_ID", "unknown"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "unknown"),
            "sha": os.getenv("GITHUB_SHA", "unknown"),
            "ref": os.getenv("GITHUB_REF", "unknown"),
        },
        "result": {
            "status": status,
            "severity": severity(status, hits),
            "confidence": confidence(status, hits, missing_inputs),
        },
        "signals": {
            "test_outcome": args.test_outcome,
            "lint_outcome": args.lint_outcome,
            "matched_patterns": hits,
            "missing_inputs": missing_inputs,
            "files": {
                "test_log": file_meta(args.test_log) if args.test_log else {"path": "", "exists": False, "size_bytes": 0},
                "lint_log": file_meta(args.lint_log) if args.lint_log else {"path": "", "exists": False, "size_bytes": 0},
            },
        },
        "recommendations": recommendations(status, hits, missing_inputs),
        "evidence_excerpt": [line[:300] for line in combined.splitlines()[:30]],
    }

    schema_path = out_dir / "aiops_test_report.schema.json"
    report_path = out_dir / "aiops_test_report.json"
    summary_path = out_dir / "aiops_test_summary.md"

    schema_path.write_text(json.dumps(SCHEMA, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    write_markdown(report, summary_path)

    print(f"AIOps artifacts generated at: {out_dir}")
    print(f"- {schema_path}")
    print(f"- {report_path}")
    print(f"- {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
