"""Phase 2-B (v0.15.0): persona starter packs for the PoI wizard.

Each template is a curated list of :class:`TopicSpec` rows that get
copied into the user's ``[skills.topic].topics`` config when chosen
from the wizard's Manual page dropdown. Users can combine multiple
templates (e.g. "Engineer + Customer Success") and the resulting
``TopicSpec``s are merged by name (case-insensitive).

Templates are intentionally minimal: 2-5 PoIs each, mostly keyword-
based, no LLM judge. The point is to bootstrap the wizard with a
*recognisable* first set of PoIs, not to ship a complete tracking
ontology.
"""
from __future__ import annotations

from dataclasses import dataclass

from .skill import TopicSpec


@dataclass(slots=True, frozen=True)
class PersonaTemplate:
    """A persona starter pack."""

    key: str
    display_name: str
    description: str
    topics: tuple[TopicSpec, ...]


def _spec(
    name: str,
    description: str,
    *,
    keywords: list[str] | None = None,
    regex: list[str] | None = None,
) -> TopicSpec:
    return TopicSpec(
        name=name,
        description=description,
        keywords=keywords or [name],
        regex=regex or [],
    )


PERSONA_TEMPLATES: tuple[PersonaTemplate, ...] = (
    PersonaTemplate(
        key="engineer",
        display_name="Software Engineer",
        description=(
            "Track PRs, tickets, and design docs you spend time on."
        ),
        topics=(
            _spec(
                "Pull Requests",
                "Pull requests on GitHub / Azure DevOps you open or review.",
                keywords=["pull request", "merge request", "PR #"],
                regex=[r"PR #\d+", r"!\d+"],
            ),
            _spec(
                "Tickets",
                "GitHub issues, JIRA cards, or in-tree issue trackers.",
                keywords=["issue", "ticket"],
                regex=[r"\b[A-Z]{2,}-\d+\b", r"#\d{3,6}\b"],
            ),
            _spec(
                "Design Docs",
                "RFC / design / spec markdown you read or write.",
                keywords=["design doc", "RFC", "spec", "proposal"],
            ),
            _spec(
                "Incident",
                "Live-site / production incident postmortems.",
                keywords=["incident", "postmortem", "rootcause", "ICM"],
            ),
        ),
    ),
    PersonaTemplate(
        key="customer_success",
        display_name="Customer Success",
        description=(
            "Track support tickets, customer accounts, and renewal cycles."
        ),
        topics=(
            _spec(
                "Support Tickets",
                "Ticket IDs you investigate or close.",
                keywords=["case", "ticket"],
                regex=[r"\bINC\d{7}\b", r"\bCASE\d{6,8}\b", r"\bSR\d{7,10}\b"],
            ),
            _spec(
                "Customer Calls",
                "Meeting / call notes with named customers.",
                keywords=["customer call", "QBR", "kick-off", "renewal"],
            ),
            _spec(
                "Escalations",
                "Tickets that escalated to engineering or leadership.",
                keywords=["escalation", "exec sponsor", "P0", "P1"],
            ),
        ),
    ),
    PersonaTemplate(
        key="researcher",
        display_name="Researcher / Student",
        description=(
            "Track papers, datasets, experiments, and writing sessions."
        ),
        topics=(
            _spec(
                "Papers",
                "Papers you read, annotate, or cite.",
                keywords=["paper", "arXiv", "doi"],
                regex=[r"arXiv:\d{4}\.\d{4,5}", r"doi:10\.\d+/\S+"],
            ),
            _spec(
                "Experiments",
                "Experiment runs / notebook sessions.",
                keywords=["experiment", "run", "ablation", "notebook"],
            ),
            _spec(
                "Writing",
                "Time spent in your draft / thesis / proposal.",
                keywords=["draft", "thesis", "manuscript", "proposal"],
            ),
            _spec(
                "Lit Review",
                "Searches and reading lists for the literature review.",
                keywords=["literature", "related work", "survey"],
            ),
        ),
    ),
    PersonaTemplate(
        key="manager",
        display_name="Engineering Manager / Lead",
        description=(
            "Track 1:1s, planning rituals, and key initiatives."
        ),
        topics=(
            _spec(
                "1:1s",
                "Per-direct 1:1 notes (rename to the person's name).",
                keywords=["1:1", "one-on-one"],
            ),
            _spec(
                "Roadmap",
                "Quarterly / annual planning artefacts.",
                keywords=["roadmap", "OKR", "planning", "milestone"],
            ),
            _spec(
                "Hiring",
                "Interview loops, panel debriefs, candidate screens.",
                keywords=["interview", "panel", "candidate", "loop"],
            ),
            _spec(
                "Status Updates",
                "Weekly / monthly status reports you write or skim.",
                keywords=["status update", "weekly report", "monthly review"],
            ),
        ),
    ),
)


def list_templates() -> tuple[PersonaTemplate, ...]:
    """Return all bundled persona templates in display order."""

    return PERSONA_TEMPLATES


def template_by_key(key: str) -> PersonaTemplate | None:
    """Lookup a template by its short key. Returns ``None`` if not found."""

    for template in PERSONA_TEMPLATES:
        if template.key == key:
            return template
    return None


def merge_template_topics(
    templates: list[PersonaTemplate],
) -> list[TopicSpec]:
    """Merge multiple persona packs, deduping by name (case-insensitive)."""

    merged: list[TopicSpec] = []
    seen: set[str] = set()
    for template in templates:
        for topic in template.topics:
            key = topic.name.strip().casefold()
            if not key or key in seen:
                continue
            merged.append(topic.model_copy(deep=True))
            seen.add(key)
    return merged


__all__ = [
    "PERSONA_TEMPLATES",
    "PersonaTemplate",
    "list_templates",
    "template_by_key",
    "merge_template_topics",
]
