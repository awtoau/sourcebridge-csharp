"""The Sourcebridge generic C# rule-runtime entrypoint.

This is deliberately a narrow adapter, not a converter. It accepts the
merged resolved-profile JSON produced by Sourcebridge, verifies that the
profile is the generic C# -> Rust profile, and exposes only the two imported
language slices recorded in ``docs/rule-runtime-boundary.json``:

* explicit-interface method-name lowering;
* C# composite-format lowering, including visible gaps for unsupported shapes.

The implementation delegates to the already-imported methods in ``scripts/``
instead of copying the legacy converter. Renode rules, project plugins, corpus
profiles, replacement directives, and unknown rules are returned as structured
``blocked`` results.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
BOUNDARY_PATH = REPO / "docs" / "rule-runtime-boundary.json"
PROVENANCE_PATH = REPO / "docs" / "legacy-rule-import.json"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from core.csharp_emitter import Emitter
from emitter.lang.expressions import Expressions

CONTRACT_SCHEMA_VERSION = 1
PACK_ID = "sourcebridge-csharp"
TARGET_BACKEND = "sourcebridge-rust"
CONTRACT_ID = "sourcebridge.rule-runtime"
SUPPORTED_PROFILE_DIRECTIVES = {"enable", "configure"}
KNOWN_PROFILE_DIRECTIVES = {"enable", "disable", "replace", "configure"}


class RuleRuntimeError(ValueError):
    """The profile or request does not satisfy the rule-runtime contract."""


class _FormatEmitter(Expressions):
    """Minimal receiver for the imported generic format rule."""

    def __init__(self, configuration: Mapping[str, Any] | None = None) -> None:
        format_configuration: dict[str, Any] = {
            "specs": {"x": "x", "X": "X"},
            "padded_hex": "0{width}{spec}",
        }
        if configuration:
            format_configuration.update(configuration)
        self.language = {"format_strings": format_configuration}
        self.unhandled: dict[str, int] = {}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = (
            json.load(sys.stdin)
            if str(path) == "-"
            else json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuleRuntimeError(f"{label} is not readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuleRuntimeError(f"{label} must contain a JSON object")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuleRuntimeError(f"{label} must be a JSON object")
    return dict(value)


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuleRuntimeError(f"{label} must be a non-empty string")
    return value


def _boundary() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Load and cross-check the allowlist against the imported legacy record."""

    boundary = _read_json(BOUNDARY_PATH, "rule-runtime boundary")
    provenance = _read_json(PROVENANCE_PATH, "rule import provenance")
    if boundary.get("contract_id") != CONTRACT_ID:
        raise RuleRuntimeError("rule-runtime boundary has the wrong contract id")
    if boundary.get("contract_version") != CONTRACT_SCHEMA_VERSION:
        raise RuleRuntimeError("unsupported rule-runtime contract version")
    if boundary.get("pack_id") != PACK_ID:
        raise RuleRuntimeError("rule-runtime boundary names the wrong pack")
    if boundary.get("provenance_record") != str(PROVENANCE_PATH.relative_to(REPO)):
        raise RuleRuntimeError("rule-runtime provenance record path does not match")

    candidates = provenance.get("candidates")
    if not isinstance(candidates, list):
        raise RuleRuntimeError("rule import provenance has no candidate list")
    by_id = {
        candidate.get("id"): candidate
        for candidate in candidates
        if isinstance(candidate, dict) and isinstance(candidate.get("id"), str)
    }
    rules = boundary.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RuleRuntimeError("rule-runtime boundary has no rules")

    imported_ids = {
        candidate_id
        for candidate_id, candidate in by_id.items()
        if candidate.get("classification") == "imported"
    }
    boundary_ids = {
        rule.get("id")
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str)
    }
    if imported_ids != boundary_ids:
        raise RuleRuntimeError(
            "rule-runtime allowlist differs from the imported generic rule set"
        )

    catalogue: dict[str, dict[str, Any]] = {}
    for rule_value in rules:
        rule = _object(rule_value, "rule-runtime rule")
        rule_id = _string(rule.get("id"), "rule id")
        candidate_id = _string(
            rule.get("provenance_candidate"), f"{rule_id} provenance candidate"
        )
        candidate = by_id.get(candidate_id)
        if candidate is None or candidate.get("classification") != "imported":
            raise RuleRuntimeError(f"{rule_id} is not an imported generic rule")
        source = candidate.get("source")
        pinned_source = rule.get("provenance")
        if not isinstance(source, dict) or source != pinned_source:
            raise RuleRuntimeError(f"{rule_id} provenance pin does not match its record")
        source_path = source.get("path", "")
        if "plugins/" in source_path or source_path.startswith("src/renode"):
            raise RuleRuntimeError(f"{rule_id} crosses the generic/Renode boundary")
        catalogue[rule_id] = {
            "id": rule_id,
            "operation": _string(rule.get("operation"), f"{rule_id} operation"),
            "provenance": dict(source),
        }
    return boundary, catalogue


def _profile_identity(profile: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Accept both a base profile and Sourcebridge's resolved-profile shape."""

    source_values: list[str] = []
    target_values: list[str] = []
    for container in (profile, _object(profile.get("base_profile", {}), "base_profile")):
        for key in ("source_frontend", "source_frontend_pack_id"):
            value = container.get(key)
            if isinstance(value, str):
                source_values.append(value)
        for key in ("target_backend", "target_backend_pack_id"):
            value = container.get(key)
            if isinstance(value, str):
                target_values.append(value)
    if len(set(source_values)) > 1 or len(set(target_values)) > 1:
        raise RuleRuntimeError("resolved profile has conflicting source or target identities")
    return (
        source_values[0] if source_values else None,
        target_values[0] if target_values else None,
    )


def _profile_block_reason(profile: Mapping[str, Any]) -> str | None:
    source, target = _profile_identity(profile)
    if source != PACK_ID:
        return f"profile source frontend must be {PACK_ID}"
    if target != TARGET_BACKEND:
        return f"profile target backend must be {TARGET_BACKEND}"

    base_profile = _object(profile.get("base_profile", {}), "base_profile")
    corpus_pack = (
        profile.get("corpus_pack")
        or profile.get("corpus_pack_id")
        or base_profile.get("corpus_pack")
        or base_profile.get("corpus_pack_id")
    )
    if corpus_pack:
        return "corpus/project profiles are outside the generic rule-runtime boundary"
    project_id = str(profile.get("project_id", "")).lower()
    workspace = str(profile.get("workspace_name", "")).lower()
    if "renode" in project_id or "renode" in workspace:
        return "Renode project profiles are outside the generic rule-runtime boundary"
    return None


def _profile_overrides(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    overrides = profile.get("rule_overrides", [])
    if not isinstance(overrides, list):
        raise RuleRuntimeError("resolved profile rule_overrides must be a JSON array")
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(overrides):
        override = _object(value, f"rule_overrides[{index}]")
        normalized.append(
            {
                "rule_key": _string(
                    override.get("rule_key"), f"rule_overrides[{index}].rule_key"
                ),
                "directive": _string(
                    override.get("directive"), f"rule_overrides[{index}].directive"
                ),
                "configuration": (
                    override.get("configuration")
                    if override.get("configuration") is not None
                    else {}
                ),
            }
        )
    return normalized


def _provenance(rule: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "record": str(PROVENANCE_PATH.relative_to(REPO)),
        "candidate": rule["id"],
        "classification": "imported",
        "source": dict(rule["provenance"]),
    }


def _blocked(
    reason: str,
    *,
    rule_id: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract": CONTRACT_ID,
        "status": "blocked",
        "reason": reason,
    }
    if rule_id is not None:
        result["rule_id"] = rule_id
    if detail:
        result["detail"] = detail
    return result


def _rule_gate(
    profile: Mapping[str, Any],
    rule_id: str,
    *,
    requested_directive: str | None,
    requested_configuration: Any,
    catalogue: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    try:
        profile_reason = _profile_block_reason(profile)
    except RuleRuntimeError as exc:
        return None, _blocked("invalid-profile", rule_id=rule_id, detail=str(exc))
    if profile_reason:
        return None, _blocked(profile_reason, rule_id=rule_id)

    try:
        overrides = _profile_overrides(profile)
    except RuleRuntimeError as exc:
        return None, _blocked("invalid-profile", rule_id=rule_id, detail=str(exc))

    matching = [item for item in overrides if item["rule_key"] == rule_id]
    for override in overrides:
        directive = override["directive"]
        if directive not in KNOWN_PROFILE_DIRECTIVES:
            return None, _blocked(
                "unsupported-directive",
                rule_id=rule_id,
                detail=f"profile directive `{directive}` is not supported",
            )
    for override in matching:
        if override["directive"] in {"disable", "replace"}:
            return None, _blocked(
                "unsupported-directive",
                rule_id=rule_id,
                detail=(
                    f"profile directive `{override['directive']}` cannot execute "
                    "this generic slice"
                ),
            )

    directive = requested_directive
    configuration = requested_configuration
    if directive is not None and not isinstance(directive, str):
        return None, _blocked(
            "unsupported-directive",
            rule_id=rule_id,
            detail="request directive must be a string",
        )
    if directive is None:
        for override in matching:
            if override["directive"] == "configure":
                directive = "configure"
                configuration = override["configuration"]
                break
            if override["directive"] == "enable":
                directive = "enable"
    if directive is not None and directive not in SUPPORTED_PROFILE_DIRECTIVES:
        return None, _blocked(
            "unsupported-directive",
            rule_id=rule_id,
            detail=f"request directive `{directive}` is not executable",
        )
    if directive == "configure" and configuration is not None and not isinstance(
        configuration, dict
    ):
        return None, _blocked(
            "invalid-configuration",
            rule_id=rule_id,
            detail="configure requires a JSON object",
        )
    return directive, None


def identify(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Identify the imported rules available to a resolved generic profile."""

    try:
        profile = _object(profile, "resolved_profile")
        boundary, catalogue = _boundary()
    except RuleRuntimeError as exc:
        return _blocked("invalid-runtime-boundary", detail=str(exc))
    try:
        profile_reason = _profile_block_reason(profile)
    except RuleRuntimeError as exc:
        return _blocked("invalid-profile", detail=str(exc))
    if profile_reason:
        return _blocked(profile_reason)

    try:
        overrides = _profile_overrides(profile)
    except RuleRuntimeError as exc:
        return _blocked("invalid-profile", detail=str(exc))

    provenance = _read_json(PROVENANCE_PATH, "rule import provenance")
    blocked_overrides: list[dict[str, Any]] = [
        {
            "rule_id": candidate.get("id"),
            "status": "blocked",
            "reason": "not-imported-generic-rule",
            "classification": candidate.get("classification"),
        }
        for candidate in provenance.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("id") not in catalogue
    ]
    blocked_overrides.extend(
        {
            "rule_id": item["rule_key"],
            "status": "blocked",
            "reason": (
                "unsupported-rule"
                if item["rule_key"] not in catalogue
                else (
                    "unsupported-directive"
                    if item["directive"] not in KNOWN_PROFILE_DIRECTIVES
                    or item["directive"] in {"disable", "replace"}
                    else None
                )
            ),
            "directive": item["directive"],
        }
        for item in overrides
        if item["rule_key"] not in catalogue
        or item["directive"] not in KNOWN_PROFILE_DIRECTIVES
        or item["directive"] in {"disable", "replace"}
    )
    blocked_rule_ids = {
        item["rule_id"]
        for item in blocked_overrides
        if item["rule_id"] in catalogue
    }
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract": CONTRACT_ID,
        "status": "identified",
        "pack_id": PACK_ID,
        "capability": boundary["capability"],
        "profile": {
            "resolved_digest": profile.get("resolved_digest"),
            "source_frontend": PACK_ID,
            "target_backend": TARGET_BACKEND,
        },
        "rules": [
            {
                "id": rule["id"],
                "operation": rule["operation"],
                "status": (
                    "blocked" if rule["id"] in blocked_rule_ids else "available"
                ),
                "provenance": _provenance(rule),
            }
            for rule in catalogue.values()
        ],
        "blocked": blocked_overrides,
    }


def execute(
    profile: Mapping[str, Any],
    rule_id: str,
    input_value: Mapping[str, Any],
    *,
    directive: str | None = None,
    configuration: Any = None,
) -> dict[str, Any]:
    """Execute one allowlisted slice, or return a visible blocked result."""

    try:
        profile = _object(profile, "resolved_profile")
        rule_id = _string(rule_id, "rule_id")
        input_value = _object(input_value, "input")
        _boundary_value, catalogue = _boundary()
    except RuleRuntimeError as exc:
        return _blocked("invalid-request", rule_id=rule_id or None, detail=str(exc))
    rule = catalogue.get(rule_id)
    if rule is None:
        return _blocked("unsupported-rule", rule_id=rule_id)
    _effective_directive, blocked = _rule_gate(
        profile,
        rule_id,
        requested_directive=directive,
        requested_configuration=configuration,
        catalogue=catalogue,
    )
    if blocked:
        return blocked
    if _effective_directive == "configure":
        configuration = configuration if configuration is not None else {}
    if configuration is not None and not isinstance(configuration, dict):
        return _blocked(
            "invalid-configuration",
            rule_id=rule_id,
            detail="configuration must be a JSON object",
        )

    try:
        if rule["operation"] == "lower_explicit_interface_name":
            method_name = _string(input_value.get("method_name"), "input.method_name")
            prefixes = (configuration or {}).get("strip_prefixes", ["get_", "set_"])
            if not isinstance(prefixes, list) or not all(
                isinstance(prefix, str) for prefix in prefixes
            ):
                return _blocked(
                    "invalid-configuration",
                    rule_id=rule_id,
                    detail="strip_prefixes must be a list of strings",
                )
            emitter = Emitter.__new__(Emitter)
            emitter.project = {
                "peripheral_methods": {"accessor_names": {"strip_prefixes": prefixes}}
            }
            value = emitter.fn_name(method_name)
        elif rule["operation"] == "lower_composite_format":
            text = _string(input_value.get("text"), "input.text")
            format_emitter = _FormatEmitter(configuration)
            value = format_emitter.csharp_format(text)
            if format_emitter.unhandled:
                return {
                    **_blocked(
                        "unsupported-composite-format",
                        rule_id=rule_id,
                        detail="the imported slice counted an unsupported C# shape",
                    ),
                    "gap": value,
                    "unhandled": dict(format_emitter.unhandled),
                    "provenance": _provenance(rule),
                }
        else:
            return _blocked(
                "unsupported-operation", rule_id=rule_id, detail=rule["operation"]
            )
    except (KeyError, TypeError, ValueError) as exc:
        return _blocked("invalid-input", rule_id=rule_id, detail=str(exc))

    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract": CONTRACT_ID,
        "status": "executed",
        "rule_id": rule_id,
        "operation": rule["operation"],
        "value": value,
        "provenance": _provenance(rule),
    }


def run_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Run the JSON request/response contract used by the pack entrypoint."""

    try:
        request = _object(request, "request")
        if request.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            raise RuleRuntimeError("request schema_version must be 1")
        profile = request.get("resolved_profile", request.get("profile"))
        profile = _object(profile, "resolved_profile")
        action = request.get("action", request.get("operation", "identify"))
        if action == "identify":
            return identify(profile)
        if action != "execute":
            return _blocked(
                "unsupported-action", detail=f"request action `{action}` is not supported"
            )
        input_value = request.get("input", {})
        return execute(
            profile,
            _string(request.get("rule_id"), "rule_id"),
            _object(input_value, "input"),
            directive=request.get("directive"),
            configuration=request.get("configuration"),
        )
    except RuleRuntimeError as exc:
        return _blocked("invalid-request", detail=str(exc))


def _request_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.request:
        return _read_json(args.request, "request")
    if not args.profile:
        raise RuleRuntimeError("--profile or --request is required")
    profile = _read_json(args.profile, "resolved profile")
    if args.action == "identify":
        return {"schema_version": 1, "action": "identify", "profile": profile}
    input_value = json.loads(args.input) if args.input else {}
    return {
        "schema_version": 1,
        "action": "execute",
        "profile": profile,
        "rule_id": args.rule_id,
        "input": input_value,
        "directive": args.directive,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sourcebridge C# rule runtime")
    parser.add_argument("--request", type=Path, help="JSON request file")
    parser.add_argument("--profile", type=Path, help="merged resolved-profile JSON")
    parser.add_argument(
        "--action", choices=("identify", "execute"), default="identify"
    )
    parser.add_argument("--rule-id", help="allowlisted rule id for execute")
    parser.add_argument("--input", help="JSON input object for execute")
    parser.add_argument("--directive", help="Sourcebridge profile directive")
    args = parser.parse_args(argv)
    try:
        response = run_request(_request_from_args(args))
    except (OSError, json.JSONDecodeError, RuleRuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
