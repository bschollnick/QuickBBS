"""Reusable engine-service frameworks (claude_docs/plans/
external_expansion_IF_engine.md Steps 5-7).

Each system here (LocationSystem, SchedulingSystem, SkillSystem) is a
generic framework a story's own EXTERNAL-bound Ink content calls into —
never an ASFA-specific implementation. A system's Python class holds no
per-story data of its own; every method takes a story's own
StorySystemConfig.config (Step 4) and the current session's own state
explicitly, and returns a plain value or an updated state dict. This is
the same stateless discipline the plan's "per-session isolation" section
requires of every EXTERNAL binding: two different stories (or two
different sessions of the same story) must be able to share the exact
same system instance with zero bleed-through, because nothing about
either one is ever held on `self`.
"""

from __future__ import annotations
