"""Random-playthrough regression harness for a live, trusted story.

Drives a real Story through random choices, using the exact same
production path a real player's turn does (`load_list_defs` +
`bindings_for(story, engine_state)`, per `views.py`'s own play view) --
never a hand-assembled binding list, which previously produced a false
"hundreds of call sites answer nobody-is-anywhere" scare: that scare's
real cause was a test harness that omitted the generic
`character_occupancy` plugin from its own hand-built descriptor list,
not a corpus or engine defect.

A "dead end" here means: `continue_story()` returned with zero choices
and the story is not `done` (`DONE`/`END` reached) -- the pointer ran off
the end of content with nothing to do next, which for a real player is a
stuck game. Reaching `self.done` normally (an ending) ends that one run
cleanly and is not counted as a dead end.

Usage:
    python manage.py playthrough_harness <story_pk> [--runs N] [--steps N]
"""

from __future__ import annotations

import random
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from interactive_fiction.engine import InkRuntimeState, load_list_defs, load_story_root
from interactive_fiction.engine_services import bindings_for
from interactive_fiction.models import Story


class Command(BaseCommand):
    help = "Drive a trusted story through random playthroughs, reporting hangs and dead ends."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("story_pk", type=int, help="Primary key of the Story to drive.")
        parser.add_argument("--runs", type=int, default=40, help="Number of independent playthroughs (default 40).")
        parser.add_argument("--steps", type=int, default=600, help="Max steps per playthrough (default 600).")
        parser.add_argument("--seed", type=int, default=None, help="Random seed, for a reproducible run.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            story = Story.objects.get(pk=options["story_pk"])
        except Story.DoesNotExist as exc:
            raise CommandError(f"No Story with pk={options['story_pk']}") from exc

        runs = options["runs"]
        max_steps = options["steps"]
        if options["seed"] is not None:
            random.seed(options["seed"])

        root = load_story_root(story.compiled_json)
        list_defs = load_list_defs(story.compiled_json)

        total_steps = 0
        dead_ends = 0
        endings = 0
        capped = 0
        errors: list[str] = []

        # `max_steps` is a safety bound, not a pass/fail signal on its own:
        # a long story genuinely may not converge on DONE/END within 600
        # random steps (confirmed against this plan's own 2026-09-01
        # baseline run: 40 runs / 22,463 steps is ~562 steps/run on
        # average, so most of those "0 hangs" runs also used nearly the
        # full budget without reaching an ending). The one real failure
        # this loop watches for is a DEAD END -- continue_story() returning
        # with zero choices while the story is not done, i.e. the pointer
        # ran off the end of content with nothing to do next, which is a
        # stuck game for a real player. An uncaught exception mid-run is
        # also a real failure, surfaced via `errors` below either way.
        for run_index in range(runs):
            engine_state: dict[str, Any] = {}
            state = InkRuntimeState(root, list_defs, engine_bindings=bindings_for(story, engine_state))
            steps_this_run = 0
            try:
                for steps_this_run in range(1, max_steps + 1):
                    state.continue_story()
                    total_steps += 1
                    if state.done:
                        endings += 1
                        break
                    if not state.current_choices:
                        dead_ends += 1
                        errors.append(f"run {run_index}: dead end at step {steps_this_run}")
                        break
                    choice_index = random.randrange(len(state.current_choices))
                    state.choose(choice_index)
                else:
                    capped += 1
            except Exception as exc:  # noqa: BLE001 - a real crash mid-playthrough is exactly what this harness exists to surface
                errors.append(f"run {run_index}: exception at step {steps_this_run}: {exc!r}")

        exceptions = len(errors) - dead_ends
        self.stdout.write(f"{runs} runs x up to {max_steps} steps, {total_steps} total steps.")
        self.stdout.write(f"Endings reached: {endings}. Hit the step cap (not a failure on its own): {capped}. Dead ends: {dead_ends}. Exceptions: {exceptions}.")
        if errors:
            self.stdout.write("Details:")
            for line in errors:
                self.stdout.write(f"  {line}")
        if dead_ends or exceptions > 0:
            raise CommandError("Playthrough harness found real issues -- see output above.")
        self.stdout.write(self.style.SUCCESS("Clean: 0 dead ends, 0 exceptions."))
