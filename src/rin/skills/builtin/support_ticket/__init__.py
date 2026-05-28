"""``support_ticket`` skill — group captures by ticket ID; archive when closed.

Designed for tech-support engineers who juggle many tickets across many
customers. ``detect`` extracts ticket IDs via regex (default covers
ServiceNow, Salesforce, and GitHub-style numbers); ``should_close``
fires when (a) any capture in the bucket mentions a "ticket closed"
phrase, or (b) no new capture has joined the bucket for
``auto_archive_after_days`` days.

The archive is a chronological LLM-driven roll-up of the entire ticket
journey ("Customer reported X, you investigated Y, root cause was Z,
resolution was W"). Falls back to a Jinja template when no provider is
configured.
"""
from .skill import SKILL, SupportTicketSkill

__all__ = ["SKILL", "SupportTicketSkill"]
