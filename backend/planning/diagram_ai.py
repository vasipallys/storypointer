"""LLM-backed diagram authoring: generate a diagram from a requirement and
apply conversational change requests.

Provider selection stays inside the LLM factory; this module only builds
prompts and normalises the returned Mermaid. `LLM_PROVIDER=mock` produces a
deterministic flowchart offline (see backend/llm/mock.py).
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend.graph.nodes import _parse_structured_result
from backend.llm.factory import get_structured_llm
from backend.planning.models import DiagramAIOutput

SYSTEM = (
    "You are a senior software architect who expresses systems as Mermaid FLOWCHART diagrams.\n"
    "Rules:\n"
    "- Output a single Mermaid flowchart. Start with `flowchart LR` for architecture views or "
    "`flowchart TB` for infrastructure views.\n"
    "- Give every node a short alphanumeric id and a quoted label, e.g. Api[\"Experience API\"].\n"
    "- Shapes you may use: [\"rectangle\"], ([\"stadium\"]), ((\"circle\")), [(\"database\")], "
    "{\"decision\"}, {{\"hexagon\"}}, [/\"data\"/].\n"
    "- Edges: `A --> B` (dependency), `A -. label .-> B` (event/async), `A ==> B` (primary flow), "
    "`A --- B` (association). Label edges with `A -- text --> B`.\n"
    "- Group related nodes with `subgraph id[\"Title\"] ... end` when it aids clarity.\n"
    "- Keep it readable: prefer 4-15 nodes unless asked for more.\n"
    "- When modifying an existing diagram, keep existing node ids and labels unless the change "
    "requires otherwise, and return the FULL updated diagram, never a diff.\n"
    "Put the diagram in `mermaid` and a one or two sentence summary of what you did in `message`."
)

_MERMAID_HEADERS = re.compile(
    r"^(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|mindmap|timeline|gitGraph|quadrantChart|C4Context)\b",
    re.IGNORECASE,
)


def _sanitize_mermaid(text: str, diagram_type: str) -> str:
    """Strip code fences and guarantee a diagram header the renderer accepts."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[A-Za-z]*\n?", "", body)
        body = re.sub(r"\n?```\s*$", "", body).strip()
    first_line = body.splitlines()[0].strip() if body.splitlines() else ""
    if not _MERMAID_HEADERS.match(first_line):
        direction = "LR" if diagram_type == "architecture" else "TB"
        body = f"flowchart {direction}\n{body}".strip()
    return body[:50000]


def _build_human(prompt: str, diagram_type: str, current_source: str, history: list[dict]) -> str:
    parts: list[str] = []
    if history:
        convo = "\n".join(f"{turn['role'].upper()}: {turn['content']}" for turn in history[-8:])
        parts.append(f"CONVERSATION SO FAR:\n{convo}")
    if current_source.strip():
        parts.append(f"CURRENT DIAGRAM:\n```mermaid\n{current_source.strip()}\n```")
        task = "Modify the current diagram according to the instruction. Return the full updated diagram."
    else:
        task = "Create a new diagram that satisfies the instruction."
    parts.append(f"DIAGRAM TYPE: {diagram_type}")
    parts.append(f"INSTRUCTION: {prompt.strip()}")
    parts.append(task)
    return "\n\n".join(parts)


async def assist_diagram(
    *,
    prompt: str,
    diagram_type: str = "architecture",
    current_source: str = "",
    history: list[dict] | None = None,
) -> dict[str, str]:
    """Return `{mermaid, message}` for a generation or edit request."""
    model = get_structured_llm(DiagramAIOutput)
    messages = [SystemMessage(content=SYSTEM), HumanMessage(content=_build_human(prompt, diagram_type, current_source, history or []))]
    result = await model.ainvoke(messages)
    output = _parse_structured_result(DiagramAIOutput, result)
    mermaid = _sanitize_mermaid(output.mermaid, diagram_type)
    message = output.message.strip() or ("Updated the diagram." if current_source.strip() else "Here is a first draft.")
    return {"mermaid": mermaid, "message": message}


def title_from_prompt(prompt: str) -> str:
    """A concise diagram title derived from the first line of the prompt."""
    first = (prompt or "").strip().splitlines()[0] if prompt.strip() else "Generated diagram"
    words = first.split()
    title = " ".join(words[:8]).strip(" .,:;-")
    return (title[:80] or "Generated diagram")
