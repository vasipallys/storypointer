"""The four agentic services. Each gathers context, prompts the LLM through the
factory's structured output, and returns a *proposal* — nothing is persisted here."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.ai.schemas import C4Scaffold, NarrativeOutput, StaffingProposal, StoryDecomposition
from backend.c4 import store as c4_store
from backend.graph.nodes import _parse_structured_result
from backend.llm.factory import get_structured_llm
from backend.planning import store as planning_store
from backend.resources import store as resources_store
from backend.storage.db import connect


async def _invoke(schema: type, system: str, human: str):
    model = get_structured_llm(schema)
    result = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=human)])
    return _parse_structured_result(schema, result)


# ---- Auto-staffing agent ------------------------------------------------

_STAFFING_SYSTEM = (
    "You are a delivery lead composing squads from an available talent pool.\n"
    "Rules:\n"
    "- Only assign people from the RESOURCE POOL list, by their exact staff_id.\n"
    "- Never exceed a person's remaining capacity; the sum of a person's new allocations must fit their remaining %.\n"
    "- Prefer matching skills/rank/HR role to the squad's mission and the open work.\n"
    "- Leave a person unassigned rather than overloading them.\n"
    "- Give each assignment a short, concrete reason."
)


def _staffing_context(project_id: str, l1_element_id: str) -> tuple[str, dict[str, Any]]:
    plan = planning_store.get_plan(project_id, l1_element_id)
    squads = [u for u in plan["units"] if u["unit_type"] == "squad"]
    staff = resources_store.list_staff({"staff_status": "Active"})

    with connect() as conn:
        alloc = {
            row["resource_staff_id"]: row["total"]
            for row in conn.execute(
                """SELECT resource_staff_id, COALESCE(SUM(allocation_percent), 0) AS total
                   FROM l1_team_members WHERE resource_staff_id IS NOT NULL GROUP BY resource_staff_id"""
            ).fetchall()
        }

    available = []
    for person in staff:
        remaining = 100 - alloc.get(person["id"], 0)
        if remaining <= 0:
            continue
        available.append({
            "staff_id": person["id"],
            "name": person["staff_name"],
            "rank": person["rank"],
            "hr_role": person["hr_role"],
            "tech_unit": person["tech_unit"],
            "remaining_percent": remaining,
        })

    open_work = [
        {"title": w["title"], "squad_id": w.get("squad_id"), "status": w["status"]}
        for w in plan.get("work_items", []) if w["status"] in ("planned", "in_progress", "at_risk")
    ]
    squad_view = [{"squad_id": s["id"], "name": s["name"], "mission": s.get("mission", ""),
                   "current_people": len(s.get("members", []))} for s in squads]

    human = (
        f"INITIATIVE: {plan['element']['name']}\n\n"
        f"SQUADS:\n{json.dumps(squad_view, indent=2)}\n\n"
        f"OPEN WORK ITEMS:\n{json.dumps(open_work, indent=2)}\n\n"
        f"RESOURCE POOL (with remaining capacity):\n{json.dumps(available, indent=2)}\n\n"
        "Propose assignments that staff the squads without exceeding anyone's remaining capacity."
    )
    return human, {"available": {p["staff_id"]: p for p in available}, "squads": {s["id"]: s for s in squads}}


async def propose_staffing(project_id: str, l1_element_id: str) -> StaffingProposal:
    human, index = _staffing_context(project_id, l1_element_id)
    if not index["available"] or not index["squads"]:
        return StaffingProposal(summary="No available resources or squads to staff.", assignments=[])
    proposal: StaffingProposal = await _invoke(StaffingProposal, _STAFFING_SYSTEM, human)

    # Defensively enforce the invariants regardless of what the model returned.
    remaining = {sid: person["remaining_percent"] for sid, person in index["available"].items()}
    clean = []
    for assignment in proposal.assignments:
        person = index["available"].get(assignment.staff_id)
        squad = index["squads"].get(assignment.squad_id)
        if not person or not squad:
            continue
        allocation = min(assignment.allocation_percent, remaining.get(assignment.staff_id, 0))
        if allocation <= 0:
            continue
        remaining[assignment.staff_id] -= allocation
        assignment.allocation_percent = allocation
        assignment.staff_name = person["name"]
        assignment.squad_name = squad["name"]
        clean.append(assignment)
    proposal.assignments = clean
    return proposal


def apply_staffing(project_id: str, assignments: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist accepted staffing assignments as team members (reuses the allocation cap)."""
    from backend.planning.models import TeamMemberCreate

    created = 0
    errors: list[str] = []
    for item in assignments:
        try:
            planning_store.create_member(project_id, item["squad_id"], TeamMemberCreate(
                name=item.get("staff_name", ""),
                resource_staff_id=item["staff_id"],
                role=item.get("role", ""),
                allocation_percent=float(item.get("allocation_percent", 0)),
            ))
            created += 1
        except Exception as exc:  # surfaced, not fatal — partial apply is fine
            errors.append(f"{item.get('staff_name', item.get('staff_id'))}: {exc}")
    return {"created": created, "errors": errors}


# ---- Reporting narrative agent ------------------------------------------

_NARRATIVE_SYSTEM = (
    "You are a delivery-portfolio analyst. Given a set of metrics, write a crisp executive briefing.\n"
    "Be specific and quantitative, reference the numbers, and keep each list item to one sentence.\n"
    "Do not invent data beyond what is provided."
)


async def generate_narrative(overview: dict[str, Any]) -> NarrativeOutput:
    human = (
        "Write an executive summary of this delivery portfolio snapshot.\n\n"
        f"METRICS:\n{json.dumps(overview, indent=2)}"
    )
    return await _invoke(NarrativeOutput, _NARRATIVE_SYSTEM, human)


# ---- Requirements → stories decomposition -------------------------------

_DECOMPOSE_SYSTEM = (
    "You are a senior BA/tech-lead decomposing a piece of scope into small, independently "
    "deliverable user stories.\n"
    "Rules:\n"
    "- Each story is vertically sliced, testable, and sized to fit a single sprint.\n"
    "- Write the description as a user story with a couple of acceptance criteria.\n"
    "- Aim for 3-8 stories; avoid overlap; cover the happy path plus key edges."
)


async def decompose_element(project_id: str, element_id: str, guidance: str = "") -> StoryDecomposition:
    element = c4_store.get_element(project_id, element_id)
    parent_name = ""
    if element.get("parent_id"):
        try:
            parent_name = c4_store.get_element(project_id, element["parent_id"])["name"]
        except Exception:
            parent_name = ""
    human = (
        f"PARENT: {parent_name or '(top level)'}\n"
        f"ELEMENT ({element['level']}): {element['name']}\n"
        f"DESCRIPTION: {element.get('description') or '(none provided)'}\n"
        f"TECH: {element.get('tech') or '(unspecified)'}\n"
        + (f"EXTRA GUIDANCE: {guidance}\n" if guidance.strip() else "")
        + "\nPropose the child stories that fully deliver this scope."
    )
    return await _invoke(StoryDecomposition, _DECOMPOSE_SYSTEM, human)


def apply_decomposition(project_id: str, element_id: str, stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Create accepted stories as proposed child elements one level below the parent."""
    from backend.c4.models import C4ElementCreate

    parent = c4_store.get_element(project_id, element_id)
    child_level = {"L1": "L2", "L2": "L3", "L3": "L4"}.get(parent["level"], "L3")
    created = 0
    for story in stories:
        c4_store.create_element(project_id, C4ElementCreate(
            level=child_level,
            name=story["name"][:200],
            description=story.get("description", ""),
            parent_id=element_id,
            kind="component" if child_level == "L3" else "task",
            status="proposed",
        ))
        created += 1
    return {"created": created, "level": child_level}


# ---- C4-from-description scaffold ----------------------------------------

_SCAFFOLD_SYSTEM = (
    "You are a software architect turning a description into a C4 model.\n"
    "Rules:\n"
    "- Produce exactly one L1 system, a handful of L2 containers, and L3 components under them.\n"
    "- Use `ref` as a temporary handle; set each element's parent_ref (L1 has null).\n"
    "- Add relations between containers/components that exchange data or calls.\n"
    "- Keep it to 8-20 elements; use realistic tech for containers."
)


async def scaffold_c4(project_id: str, description: str) -> C4Scaffold:
    human = (
        "Turn this description into a C4 model (one L1 system, L2 containers, L3 components + relations).\n\n"
        f"DESCRIPTION:\n{description.strip()}"
    )
    return await _invoke(C4Scaffold, _SCAFFOLD_SYSTEM, human)


def apply_scaffold(project_id: str, scaffold: dict[str, Any]) -> dict[str, Any]:
    """Create the proposed elements + relations, resolving temporary refs to real ids."""
    from backend.c4.models import C4ElementCreate, C4RelationCreate

    ref_to_id: dict[str, str] = {}
    order = {"L1": 0, "L2": 1, "L3": 2}
    elements = sorted(scaffold.get("elements", []), key=lambda e: order.get(e["level"], 3))
    created_elements = 0
    for element in elements:
        parent_ref = element.get("parent_ref")
        parent_id = ref_to_id.get(parent_ref) if parent_ref else None
        record = c4_store.create_element(project_id, C4ElementCreate(
            level=element["level"],
            name=element["name"][:200],
            kind=element.get("kind", ""),
            description=element.get("description", ""),
            tech=element.get("tech", ""),
            parent_id=parent_id,
            status="proposed",
        ))
        ref_to_id[element["ref"]] = record["id"]
        created_elements += 1

    created_relations = 0
    for relation in scaffold.get("relations", []):
        source = ref_to_id.get(relation["source_ref"])
        target = ref_to_id.get(relation["target_ref"])
        if not source or not target:
            continue
        kind = relation.get("kind", "sync")
        if kind not in ("sync", "async", "data"):
            kind = "sync"
        c4_store.create_relation(project_id, C4RelationCreate(
            source_id=source, target_id=target, label=relation.get("label", ""), kind=kind,
        ))
        created_relations += 1
    return {"created_elements": created_elements, "created_relations": created_relations}
