"""Deterministic offline LLM for LLM_PROVIDER=mock.

Produces schema-valid, story-dependent outputs with no network or API key, so
demos, tests, and UI work run without a provider. The estimate is derived from
a stable hash of the story title, so the same story always gets the same points
and a 13 exercises the spike/split branch end to end.
"""

from __future__ import annotations

import asyncio
import re
import zlib
from typing import Any

from pydantic import BaseModel

from backend.anchors import ANCHORS
from backend.graph.state import (
    PARAMETERS,
    AnchorComparisonOutput,
    DriversOutput,
    EffortRange,
    HiddenTasksOutput,
    HiddenTask,
    LayerEffort,
    ParameterScore,
    PlainLanguageOutput,
    PointsOutput,
    Risk,
    RisksOutput,
    ScorecardOutput,
    SplitOutput,
)

FIBONACCI = [2, 3, 5, 8, 13]
LEVELS = ["Low", "Medium", "High"]


def _seed(text: str) -> int:
    return zlib.crc32(text.encode("utf-8"))


def _title(messages: list[Any]) -> str:
    text = " ".join(str(getattr(message, "content", message)) for message in messages)
    match = re.search(r'"title":\s*"([^"]+)"', text)
    return match.group(1) if match else "the story"


def _points(title: str) -> int:
    return FIBONACCI[_seed(title) % len(FIBONACCI)]


def _score(title: str, parameter: str) -> str:
    return LEVELS[_seed(f"{title}:{parameter}") % len(LEVELS)]


def _build(schema: type[BaseModel], title: str) -> BaseModel:
    points = _points(title)
    anchor_titles = [anchor["title"] for anchor in ANCHORS[:2]]
    if schema is ScorecardOutput:
        return ScorecardOutput(scores=[
            ParameterScore(parameter=parameter, score=_score(title, parameter),
                           reason=f"Mock assessment of {parameter.replace('_', ' ')} from the supplied evidence.")
            for parameter in PARAMETERS
        ])
    if schema is DriversOutput:
        drivers = sorted(PARAMETERS, key=lambda parameter: _seed(f"{title}:{parameter}"))[:2]
        return DriversOutput(drivers=drivers, explanation=f"Mock mode: {drivers[0]} and {drivers[1]} dominate the effort for '{title}'.")
    if schema is AnchorComparisonOutput:
        return AnchorComparisonOutput(
            comparison=f"Mock mode: '{title}' sits near {anchor_titles[0]} and is judged {'bigger' if points >= 8 else 'similar or smaller'} against {anchor_titles[1]}.",
            anchor_titles=anchor_titles,
        )
    if schema is PointsOutput:
        return PointsOutput(points=points, derivation=f"Mock derivation: hashed scope of '{title}' maps to {points} on the modified Fibonacci scale.")
    if schema is PlainLanguageOutput:
        return PlainLanguageOutput(
            plain_language_why=(
                f"This is a {points} because the mocked scorecard puts the deciding weight on scope and dependencies for '{title}'. "
                f"It compares closest to the anchor '{anchor_titles[0]}'. No real model was consulted (mock mode)."
            ),
            tldr=f"{points} - Mock estimate: scope and dependencies decide it.",
            effort=LayerEffort(
                react="Mocked UI adjustments", spring="Mocked service work", existing_code="Mocked integration touchpoints",
                person_days=EffortRange(optimistic=points * 0.5, likely=float(points), pessimistic=points * 1.6),
            ),
        )
    if schema is HiddenTasksOutput:
        return HiddenTasksOutput(hidden_tasks=[
            HiddenTask(task=f"Mock hidden task: audit logging for {title}", weight="medium"),
            HiddenTask(task=f"Mock hidden task: regression tests around {title}", weight="small"),
        ])
    if schema is RisksOutput:
        spike = points >= 8
        return RisksOutput(
            risks=[
                Risk(risk=f"Mock risk: unclear integration contract for {title}", mitigation_or_assumption="Assume the contract is confirmed in refinement."),
                Risk(risk="Mock risk: environment availability", mitigation_or_assumption="Assume test environments exist."),
            ],
            assumptions=["Mock mode is active; no real analysis was performed."],
            spike_recommended=spike,
            spike_reason="Mock mode flags a spike for larger estimates." if spike else None,
        )
    if schema is SplitOutput:
        split = points == 13
        return SplitOutput(
            split_recommended=split,
            rationale="Mock mode: a 13 must be split." if split else "Mock mode: the story is deliverable as one slice.",
            proposed_stories=[f"{title} — happy path (5)", f"{title} — edge cases and audit (5)"] if split else [],
        )
    raise RuntimeError(f"Mock LLM has no builder for schema '{schema.__name__}'")


_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "with", "that", "this", "add", "create",
    "new", "diagram", "show", "make", "into", "from", "using", "please", "our", "then", "when",
    "flow", "between", "should", "which", "node", "connect", "change", "update", "modify",
}


def _keywords(text: str, limit: int = 5) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", text)
    picks: list[str] = []
    for word in words:
        if word.lower() in _STOPWORDS or len(word) < 3:
            continue
        capital = word[:1].upper() + word[1:]
        if capital not in picks:
            picks.append(capital)
        if len(picks) >= limit:
            break
    return picks or ["System", "Service", "Data"]


def _node_id(label: str, index: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", label)[:14]
    return f"{cleaned or 'node'}{index}"


def _build_diagram_ai(messages: list[Any]) -> BaseModel:
    """Deterministic offline diagram authoring for LLM_PROVIDER=mock."""
    from backend.planning.models import DiagramAIOutput

    text = " ".join(str(getattr(message, "content", message)) for message in messages)
    instruction = ""
    match = re.search(r"INSTRUCTION:\s*(.+)", text)
    if match:
        instruction = match.group(1).splitlines()[0].strip()
    current = ""
    block = re.search(r"CURRENT DIAGRAM:\s*```mermaid\s*(.+?)```", text, re.DOTALL)
    if block and block.group(1).strip():
        current = block.group(1).strip()

    if current:
        label = _keywords(instruction, 1)[0]
        node = f"{_node_id(label, 0)}x"
        lines = [current.rstrip(), f'  {node}["{label}"]']
        anchor = re.search(r"^\s*([A-Za-z0-9_]+)\s*[\[({]", current, re.MULTILINE) or re.search(r"\b([A-Za-z0-9_]+)\s*(?:--|==|-\.)", current)
        if anchor:
            lines.append(f"  {anchor.group(1)} --> {node}")
        mermaid = "\n".join(lines)
        message = f"Mock mode: added '{label}' to the diagram."
    else:
        labels = _keywords(instruction)
        ids = [_node_id(label, index) for index, label in enumerate(labels)]
        lines = ["flowchart LR"]
        lines += [f'  {node}["{label}"]' for node, label in zip(ids, labels)]
        lines += [f"  {source} --> {target}" for source, target in zip(ids, ids[1:])]
        mermaid = "\n".join(lines)
        message = f"Mock mode: drafted a {len(ids)}-node flowchart from your prompt."
    return DiagramAIOutput(mermaid=mermaid, message=message)


class MockStructuredLLM:
    """Stands in for a structured chat model; returns a valid schema instance."""

    def __init__(self, schema: type[BaseModel]) -> None:
        self.schema = schema

    async def ainvoke(self, messages: list[Any]) -> BaseModel:
        await asyncio.sleep(0.15)  # let the streaming pipeline view animate
        if self.schema.__name__ == "DiagramAIOutput":
            return _build_diagram_ai(messages)
        return _build(self.schema, _title(messages))
