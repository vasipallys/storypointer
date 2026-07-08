"""Deterministic offline LLM for LLM_PROVIDER=mock.

Produces schema-valid, story-dependent outputs with no network or API key, so
demos, tests, and UI work run without a provider. The estimate is derived from
a stable hash of the story title, so the same story always gets the same points
and a 13 exercises the spike/split branch end to end.
"""

from __future__ import annotations

import asyncio
import json
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


_MOCK_DIAGRAMS = {
    "architecture_beta": "\n".join([
        "architecture-beta",
        "  group cloud(cloud)[Production cloud]",
        "  service web(internet)[Web] in cloud",
        "  service api(server)[API] in cloud",
        "  service db(database)[Database] in cloud",
        "  web:R --> L:api",
        "  api:R --> L:db",
    ]),
    "block": "\n".join([
        "block-beta",
        "  columns 3",
        "  web[\"Web\"] api[\"API\"] db[(\"DB\")]",
        "  web --> api",
        "  api --> db",
    ]),
    "packet": "\n".join([
        "packet",
        "  0-15: \"Source port\"",
        "  16-31: \"Destination port\"",
        "  32-63: \"Sequence number\"",
    ]),
    "class": "\n".join([
        "classDiagram",
        "  class Story",
        "  class Estimator",
        "  Story --> Estimator : analyzed by",
    ]),
    "state": "\n".join([
        "stateDiagram-v2",
        "  [*] --> Draft",
        "  Draft --> InReview",
        "  InReview --> Approved",
    ]),
    "er": "\n".join([
        "erDiagram",
        "  PROJECT ||--o{ STORY : contains",
        "  STORY ||--o{ TASK : proposes",
    ]),
    "requirement": "\n".join([
        "requirementDiagram",
        "  performanceRequirement availability {",
        "    id: NFR1",
        "    text: \"99.9 percent availability\"",
        "    risk: Medium",
        "    verifymethod: Test",
        "  }",
        "  element platform {",
        "    type: system",
        "    docref: platform.md",
        "  }",
        "  platform - satisfies -> availability",
    ]),
    "c4": "\n".join([
        "C4Context",
        "  Person(user, \"User\")",
        "  System(app, \"Story Pointer\")",
        "  Rel(user, app, \"Estimates stories\")",
    ]),
    "gantt": "\n".join([
        "gantt",
        "  title Mock plan",
        "  dateFormat YYYY-MM-DD",
        "  section Delivery",
        "  Build slice :2026-07-01, 5d",
    ]),
    "journey": "\n".join([
        "journey",
        "  title Mock journey",
        "  section Use",
        "    Submit story: 4: User",
        "    Review estimate: 5: User",
    ]),
    "timeline": "\n".join([
        "timeline",
        "  title Mock timeline",
        "  Discover : Scope",
        "  Deliver : Build : Validate",
    ]),
    "mindmap": "\n".join([
        "mindmap",
        "  root((Initiative))",
        "    Experience",
        "    Platform",
        "    Operations",
    ]),
    "quadrant": "\n".join([
        "quadrantChart",
        "  title Mock prioritization",
        "  x-axis Low effort --> High effort",
        "  y-axis Low value --> High value",
        "  \"Core\": [0.35, 0.80]",
    ]),
    "gitgraph": "\n".join([
        "gitGraph",
        "  commit id: \"init\"",
        "  branch feature",
        "  checkout feature",
        "  commit id: \"build\"",
    ]),
    "pie": "\n".join([
        "pie showData",
        "  title Mock effort",
        "  \"Frontend\" : 35",
        "  \"Backend\" : 45",
        "  \"Testing\" : 20",
    ]),
    "xychart": "\n".join([
        "xychart-beta",
        "  title \"Mock velocity\"",
        "  x-axis [Sprint 1, Sprint 2, Sprint 3]",
        "  y-axis \"Points\" 0 --> 50",
        "  line [20, 28, 34]",
    ]),
    "sankey": "\n".join([
        "sankey-beta",
        "  Discovery,Delivery,8",
        "  Delivery,Testing,5",
        "  Testing,Release,4",
    ]),
    "treemap": "\n".join([
        "treemap-beta",
        "  \"Initiative\"",
        "    \"Experience\": 34",
        "    \"Platform\": 21",
    ]),
    "venn": "\n".join([
        "venn-beta",
        "  set Frontend[\"Frontend\"]: 3",
        "  set Backend[\"Backend\"]: 3",
        "  union Frontend,Backend[\"API contracts\"]: 1",
    ]),
}


def _build_diagram_ai(messages: list[Any]) -> BaseModel:
    """Deterministic offline diagram authoring for LLM_PROVIDER=mock."""
    from backend.planning.models import DiagramAIOutput

    text = " ".join(str(getattr(message, "content", message)) for message in messages)
    type_match = re.search(r"DIAGRAM TYPE:\s*([A-Za-z0-9_]+)", text)
    diagram_type = type_match.group(1) if type_match else "architecture"
    instruction = ""
    match = re.search(r"INSTRUCTION:\s*(.+)", text)
    if match:
        instruction = match.group(1).splitlines()[0].strip()
    current = ""
    block = re.search(r"CURRENT DIAGRAM:\s*```mermaid\s*(.+?)```", text, re.DOTALL)
    if block and block.group(1).strip():
        current = block.group(1).strip()

    if current and not re.match(r"^(flowchart|graph)\b", current.strip(), re.IGNORECASE):
        mermaid = current
        message = "Mock mode: kept the current non-flowchart diagram for text editing."
    elif current:
        label = _keywords(instruction, 1)[0]
        node = f"{_node_id(label, 0)}x"
        lines = [current.rstrip(), f'  {node}["{label}"]']
        anchor = re.search(r"^\s*([A-Za-z0-9_]+)\s*[\[({]", current, re.MULTILINE) or re.search(r"\b([A-Za-z0-9_]+)\s*(?:--|==|-\.)", current)
        if anchor:
            lines.append(f"  {anchor.group(1)} --> {node}")
        mermaid = "\n".join(lines)
        message = f"Mock mode: added '{label}' to the diagram."
    elif diagram_type == "sequence":
        mermaid = "\n".join([
            "sequenceDiagram",
            "  actor User",
            "  participant Web",
            "  participant API",
            "  User->>Web: Request estimate",
            "  Web->>API: Stream story",
            "  API-->>Web: Points and reasoning",
        ])
        message = "Mock mode: drafted a sequence diagram from your prompt."
    elif diagram_type in _MOCK_DIAGRAMS:
        mermaid = _MOCK_DIAGRAMS[diagram_type]
        message = f"Mock mode: drafted a {diagram_type.replace('_', ' ')} diagram from your prompt."
    elif diagram_type == "kanban":
        mermaid = "\n".join([
            "kanban",
            "  backlog[Backlog]",
            "    task1[Clarify scope]@{ priority: 'High', assigned: 'Team' }",
            "  delivery[In delivery]",
            "    task2[Build slice]",
            "  done[Done]",
            "    task3[Seed sample data]",
        ])
        message = "Mock mode: drafted a kanban diagram from your prompt."
    elif diagram_type == "radar":
        mermaid = "\n".join([
            "radar-beta",
            "  title Mock readiness",
            "  axis Security, Scale, Delivery, Cost",
            "  curve Current{70, 60, 65, 55}",
            "  curve Target{90, 85, 80, 75}",
            "  max 100",
        ])
        message = "Mock mode: drafted a radar diagram from your prompt."
    else:
        labels = _keywords(instruction)
        ids = [_node_id(label, index) for index, label in enumerate(labels)]
        lines = ["flowchart LR"]
        lines += [f'  {node}["{label}"]' for node, label in zip(ids, labels)]
        lines += [f"  {source} --> {target}" for source, target in zip(ids, ids[1:])]
        mermaid = "\n".join(lines)
        message = f"Mock mode: drafted a {len(ids)}-node flowchart from your prompt."
    return DiagramAIOutput(mermaid=mermaid, message=message)


def _json_after(text: str, label: str) -> Any:
    """Extract the bracket-balanced JSON array/object that follows a label."""
    start = text.find(label)
    if start == -1:
        return None
    segment = text[start + len(label):]
    open_index = next((i for i, ch in enumerate(segment) if ch in "[{"), -1)
    if open_index == -1:
        return None
    opener = segment[open_index]
    closer = "]" if opener == "[" else "}"
    depth = 0
    for i in range(open_index, len(segment)):
        if segment[i] == opener:
            depth += 1
        elif segment[i] == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(segment[open_index:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _build_agentic(schema: type[BaseModel], messages: list[Any]) -> BaseModel:
    """Deterministic offline proposals for the agentic services (LLM_PROVIDER=mock)."""
    from backend.ai.schemas import (
        C4Scaffold, NarrativeOutput, ProposedStory, ScaffoldElement, ScaffoldRelation,
        StaffingAssignment, StaffingProposal, StoryDecomposition,
    )

    # Parse the human message only — labels like "RESOURCE POOL" also appear in
    # the system instructions, so joining both would match the wrong occurrence.
    human_messages = [m for m in messages if getattr(m, "type", "") == "human"]
    source = human_messages or messages
    text = " ".join(str(getattr(message, "content", message)) for message in source)

    if schema is StaffingProposal:
        available = _json_after(text, "RESOURCE POOL") or []
        squads = _json_after(text, "SQUADS:") or []
        assignments = []
        for index, person in enumerate(available):
            if not squads:
                break
            squad = squads[index % len(squads)]
            allocation = min(person.get("remaining_percent", 0), 50)
            if allocation <= 0:
                continue
            assignments.append(StaffingAssignment(
                staff_id=person["staff_id"], staff_name=person.get("name", ""),
                squad_id=squad["squad_id"], squad_name=squad.get("name", ""),
                role=person.get("hr_role", "") or "Contributor",
                allocation_percent=allocation,
                reason=f"Mock mode: {person.get('name', 'this person')} has {person.get('remaining_percent', 0)}% free and fits {squad.get('name', 'the squad')}.",
            ))
        return StaffingProposal(summary=f"Mock staffing: proposed {len(assignments)} assignment(s) across {len(squads)} squad(s).", assignments=assignments)

    if schema is NarrativeOutput:
        metrics = _json_after(text, "METRICS:") or {}
        portfolio = metrics.get("portfolio", {})
        resources = metrics.get("resources", {})
        return NarrativeOutput(
            headline=f"{portfolio.get('projects', 0)} platforms · {portfolio.get('estimated_pct', 0)}% estimated",
            summary=(
                f"Mock briefing: the portfolio spans {portfolio.get('projects', 0)} platforms with "
                f"{portfolio.get('estimated', 0)}/{portfolio.get('stories', 0)} stories estimated. "
                f"{resources.get('active', 0)} of {resources.get('total', 0)} resources are active, "
                f"{resources.get('on_bench', 0)} on the bench, at {resources.get('avg_utilisation', 0)}% average utilisation."
            ),
            highlights=[
                f"{portfolio.get('squads', 0)} squads with {portfolio.get('members', 0)} people assigned.",
                f"{resources.get('fully_allocated', 0)} people fully allocated.",
            ],
            risks=(["Work items are flagged at risk."] if portfolio.get("at_risk_work_items") else ["No work items are currently at risk."]),
            recommendations=[
                "Move bench resources onto open squads." if resources.get("on_bench") else "Utilisation looks healthy; keep monitoring.",
            ],
        )

    if schema is StoryDecomposition:
        match = re.search(r"ELEMENT \([^)]*\):\s*(.+)", text)
        name = match.group(1).splitlines()[0].strip() if match else "the scope"
        seeds = [("Happy path", "core flow"), ("Validation & errors", "edge cases"), ("Persistence & audit", "data and traceability"), ("Tests & observability", "quality gates")]
        stories = [ProposedStory(
            name=f"{name}: {title}",
            description=f"As a user, I can complete the {focus} for {name}.\nAcceptance:\n- {focus} works end to end\n- covered by tests",
            rationale=f"Mock decomposition slice covering {focus}.",
        ) for title, focus in seeds]
        return StoryDecomposition(summary=f"Mock mode: decomposed '{name}' into {len(stories)} stories.", stories=stories)

    if schema is C4Scaffold:
        desc_match = re.search(r"DESCRIPTION:\s*(.+)", text, re.DOTALL)
        keywords = _keywords(desc_match.group(1) if desc_match else text, 3)
        elements = [
            ScaffoldElement(ref="sys", level="L1", name=f"{keywords[0]} platform", kind="system", description="Mock-scaffolded system."),
            ScaffoldElement(ref="web", level="L2", name=f"{keywords[0].lower()}-web", kind="container", tech="React", parent_ref="sys", description="User-facing web app."),
            ScaffoldElement(ref="svc", level="L2", name=f"{keywords[0].lower()}-service", kind="container", tech="Spring Boot", parent_ref="sys", description="Core service."),
            ScaffoldElement(ref="db", level="L2", name=f"{keywords[0].lower()}-db", kind="container", tech="PostgreSQL", parent_ref="sys", description="System of record."),
            ScaffoldElement(ref="cmp1", level="L3", name=f"{keywords[1]} module", kind="component", parent_ref="svc", description="Mock component."),
            ScaffoldElement(ref="cmp2", level="L3", name=f"{keywords[2]} module", kind="component", parent_ref="svc", description="Mock component."),
        ]
        relations = [
            ScaffoldRelation(source_ref="web", target_ref="svc", label="calls", kind="sync"),
            ScaffoldRelation(source_ref="svc", target_ref="db", label="reads/writes", kind="data"),
        ]
        return C4Scaffold(summary=f"Mock mode: scaffolded a C4 model around '{keywords[0]}'.", elements=elements, relations=relations)

    raise RuntimeError(f"Mock LLM has no agentic builder for schema '{schema.__name__}'")


_AGENTIC_SCHEMAS = {"StaffingProposal", "NarrativeOutput", "StoryDecomposition", "C4Scaffold"}


class MockStructuredLLM:
    """Stands in for a structured chat model; returns a valid schema instance."""

    def __init__(self, schema: type[BaseModel]) -> None:
        self.schema = schema

    async def ainvoke(self, messages: list[Any]) -> BaseModel:
        await asyncio.sleep(0.15)  # let the streaming pipeline view animate
        if self.schema.__name__ == "DiagramAIOutput":
            return _build_diagram_ai(messages)
        if self.schema.__name__ in _AGENTIC_SCHEMAS:
            return _build_agentic(self.schema, messages)
        return _build(self.schema, _title(messages))
