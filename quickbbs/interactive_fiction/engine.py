"""Ink runtime engine for interactive_fiction (Step 2, Sections 1-3).

Section 1: container/path addressing. Given a compiled Ink story's JSON,
build the Container tree and resolve dotted path strings (e.g.
"start.0.g-0.2") to the content they address.

Section 2: output stream assembly. Given a sequence of leaf tokens (text,
newlines, glue), assemble the visible turn text using Ink's real
newline/glue-suppression rules — not naive string concatenation.

Section 3: diverts and basic (bracket-only) choices. Advances a Pointer
through the container tree leaf-by-leaf, follows unconditional diverts,
collects `[choice-only]` ChoicePoint text, and prunes once-only choices by
visit count. Deliberately does NOT implement: conditional diverts/choices
(need the eval stack), start+choice-only text combos beyond the plain
bracket form (compiles to weave/tunnel machinery — real Section 5/6
territory), variables, or the call stack proper (Section 3 only needs a
"current ancestor to return to after this container ends" walk, not
PushPopType frames) — see the plan's Section 3 scope note.

Later sections (variables, call stack/tunnels, functions/threads, LISTs,
sequences/RNG, remaining ops/tags) are not yet implemented (see
claude_docs/plans/interactive_fiction_ink_engine.md, Step 2 "Build
sections").

JSON encoding reference (confirmed against real compiled output, and
matching inkle's reference runtime / the COUR4G3/inkpy port kept at
claude_docs/tools/inkpy-reference/ for structural reference only — not a
dependency):
- A container is a JSON list. All elements except the last are positional
  content (index-addressed). The last element, if a dict, is the
  "terminator": its keys are named content (e.g. sub-containers, knots)
  except for "#n" (this container's own name) and "#f" (count flags).
- A leaf string starting with "^" is literal text (the caret is stripped).
  A bare "\\n" is a newline. A leaf string "<>" is glue. Everything else at
  leaf level (diverts, control commands, etc.) is out of scope through
  Section 2 and stored as an opaque placeholder so path resolution still
  works.

Output-stream algorithm reference: ported from inkle's C# reference
runtime's StoryState.PushToOutputStream /
TrySplittingHeadTailWhitespace / PushToOutputStreamIndividual /
RemoveExistingGlue / TrimNewlinesFromOutputStream
(claude_docs/tools/ink-reference/ink-engine-runtime/StoryState.cs) — the
COUR4G3/inkpy port's equivalent (state.py's push_to_output_stream) was
checked and found to be a simplified stand-in that doesn't implement the
real glue-trim/newline-dedup algorithm, so this section is built from the
C# source directly, not from inkpy. The function-call-frame whitespace
trimming (functionTrimIndex in the C# source) is deliberately NOT
implemented yet — it needs the real call stack from Section 5/6 — so
OutputStream only implements the glue- and story-level newline-dedup
paths for now.
"""

# pylint: disable=too-many-lines
# Deliberately over the default module-line threshold and will stay that
# way: this module is the whole Ink interpreter, ported one build section
# at a time (see "Build sections" in the plan above), and will keep
# growing across Sections 4-10 regardless of any internal reorganization —
# mirroring the real Ink engine's own Story.cs/StoryState.cs, which are
# thousands of lines combined. Splitting into submodules now would just be
# undone by the next section's additions (same reasoning as
# InkRuntimeState's too-many-instance-attributes disable below).

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


class InkPathError(ValueError):
    """Raised when a path string cannot be resolved against a container tree."""


def _container_path(container: "Container") -> str:
    """Reconstruct a container's absolute dotted path string.

    Ports Object.path (ink-engine-runtime/Object.cs)'s container-side
    component exactly: walks up the parent chain, and at each level names
    the step as the child's own "#n" name if it has one (unconditionally
    trusted — `namedChild.hasValidName`, not a reverse lookup into the
    parent's named_content), otherwise its positional index in the
    parent's content list. This match depends on every named child
    actually carrying its own .name — including a child that's *only*
    reachable via a terminator-dict key with no positionally-placed slot
    at all, whose .name _load_container now sets from that key
    unconditionally (ports JsonSerialisation.JArrayToContainer's
    `namedSubContainer.name = keyVal.Key`, confirmed 2026-08-16 as a real
    gap: real compiled output never redundantly repeats a terminator-dict
    key as that same child's own "#n", so a container reachable only by
    name previously had no name recorded on it at all here, making it
    invisible to both branches below — a real bug caught while building
    Step 3's save-state serialization, which needs every reachable
    container to have a reliable, round-trippable path). Used by
    _shuffle_index()'s NextSequenceShuffleIndex port (real Ink's shuffle
    results depend on this exact string) and by state serialization
    (Step 3) to address self.pointer/current_choices/etc. as plain path
    strings rather than live object references.

    Args:
        container: The container to compute a path string for.

    Returns:
        The dotted path string from the story root to container.

    Raises:
        InkPathError: If container is not reachable from its own parent
            chain by name or by position — a malformed tree, which
            should not occur for any container actually produced by
            load_story_root() given the fix above.
    """
    components: list[str] = []
    current = container
    while current.parent is not None:
        parent = current.parent
        if current.name is not None:
            components.append(current.name)
        elif current in parent.content:
            components.append(str(parent.content.index(current)))
        else:
            raise InkPathError(f"Container {current!r} is not reachable from its own parent {parent!r} by name or position")
        current = parent
    return ".".join(reversed(components))


def _wrap_int32(value: int) -> int:
    """Wrap a Python int into C#'s 32-bit signed integer range.

    Args:
        value: Any integer, possibly outside int32 range after arithmetic.

    Returns:
        value reduced modulo 2**32 and reinterpreted as signed, matching
        C#'s implicit int32 overflow wraparound (Python ints never
        overflow on their own, so every arithmetic step in NetRandom that
        C# performs as int32 must be wrapped explicitly here).
    """
    value &= 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value


class NetRandom:  # pylint: disable=too-few-public-methods
    """A faithful Python port of the legacy .NET `System.Random(int seed)`
    algorithm (the Knuth subtractive/lagged-Fibonacci generator).

    Deliberately has one public method: real C# `System.Random` exposes
    several `Next(...)` overloads, but Ink itself only ever calls the bare
    parameterless `.Next()` (confirmed against every RNG call site in
    ink-engine-runtime/Story.cs — RANDOM/shuffle/LIST_RANDOM all do their
    own range-mapping on the raw int32 result), so implementing the other
    overloads here would be unused surface area, not a real gap.

    Real Ink's C# runtime seeds `new Random(...)` and calls bare `.Next()`
    for both `RANDOM()` and shuffle resolution
    (ink-engine-runtime/Story.cs) — never `Next(maxValue)`, so only the
    parameterless overload is implemented here. Confirmed 2026-08-16 that
    .NET Core 3.0+ (including net6.0, which `inklecate` targets)
    deliberately preserves this exact legacy algorithm for the
    explicit-seed constructor, even though the parameterless `Random()`
    constructor switched to a different (xoshiro128**-based) algorithm in
    modern .NET — confirmed by fetching the actual dotnet/runtime source
    (`Random.CompatImpl.cs`'s `Initialize(int seed)`), not inferred.
    Validated against real output from a small `dotnet run` program
    calling `new Random(seed).Next()` across 13 seeds (including 0, ±1,
    Int32.MaxValue, Int32.MinValue, and other values near the int32
    boundary) — every sequence matches exactly, including the
    Int32.MinValue edge case (special-cased to Int32.MaxValue in the
    seed-array initialization, confirmed against the real source rather
    than guessed: `Math.Abs(int.MinValue)` throws in C#, so the real
    algorithm substitutes `int.MaxValue` for that one seed value directly
    rather than computing an absolute value at all).

    Args:
        seed: The seed value (any int32; values outside int32 range are
            not expected here since Ink's own `storySeed` is always a
            small nonnegative int, but the algorithm is defined for the
            full int32 range and implemented that way).
    """

    _MBIG = 2147483647
    _MSEED = 161803398

    def __init__(self, seed: int) -> None:
        seed_array = [0] * 56
        subtraction = self._MBIG if seed == -2147483648 else abs(seed)
        mj = _wrap_int32(self._MSEED - subtraction)
        seed_array[55] = mj
        mk = 1
        ii = 0
        for i in range(1, 55):
            ii += 21
            if ii >= 55:
                ii -= 55
            seed_array[ii] = mk
            mk = _wrap_int32(mj - mk)
            if mk < 0:
                mk = _wrap_int32(mk + self._MBIG)
            mj = seed_array[ii]
        for _ in range(1, 5):
            for i in range(1, 56):
                seed_array[i] = _wrap_int32(seed_array[i] - seed_array[1 + (i + 30) % 55])
                if seed_array[i] < 0:
                    seed_array[i] = _wrap_int32(seed_array[i] + self._MBIG)
        self._seed_array = seed_array
        self._inext = 0
        self._inextp = 21

    def next(self) -> int:
        """Return the next pseudo-random int32 in this generator's sequence.

        Ports Random.InternalSample(): two rolling indices into the
        56-element seed array, each call advancing both and folding the
        difference back into the array.

        Returns:
            A value in [0, Int32.MaxValue), matching C#'s
            `Random.Next()` (the parameterless overload) exactly for the
            same seed.
        """
        inext = self._inext + 1
        if inext >= 56:
            inext = 1
        inextp = self._inextp + 1
        if inextp >= 56:
            inextp = 1
        ret_val = _wrap_int32(self._seed_array[inext] - self._seed_array[inextp])
        if ret_val == self._MBIG:
            ret_val -= 1
        if ret_val < 0:
            ret_val = _wrap_int32(ret_val + self._MBIG)
        self._seed_array[inext] = ret_val
        self._inext = inext
        self._inextp = inextp
        return ret_val


def _time_seed() -> int:
    """Return a nondeterministic int32 seed derived from the current time.

    Ports the construction-time default in Story.ResetState
    (ink-engine-runtime/StoryState.cs: `storySeed = new
    Random(timeSeed).Next() % 100`), where timeSeed comes from the system
    clock — a real story never has a fixed seed unless the author calls
    `SEED_RANDOM()` explicitly. Uses time.time_ns() truncated to int32
    range rather than any particular C# time-seed formula, since only
    "nondeterministic and different across constructions" matters here,
    not bit-for-bit matching a specific C# clock-based seed (which no
    fixture or real transcript comparison can pin down anyway, since it's
    never reproducible even between two real inklecate runs).

    Returns:
        A pseudo-random int32 value, different on (almost) every call.
    """
    return _wrap_int32(time.time_ns())


@dataclass
class PathComponent:
    """One dotted segment of an Ink path: either a list index or a name.

    Args:
        index: The positional index into a container's content list, or
            None if this component addresses named content instead.
        name: The named-content key, or None if this component is an
            index. The literal name "^" (PARENT_NAME) addresses the
            parent container instead of a real named child.
    """

    index: int | None = None
    name: str | None = None

    PARENT_NAME = "^"

    @property
    def is_index(self) -> bool:
        """
        Return whether this component addresses content by list index.

        Returns:
            True if this component is index-addressed, False if it's a
            named-content or parent-marker component.
        """
        return self.index is not None

    @property
    def is_parent(self) -> bool:
        """
        Return whether this component is the "^" parent-container marker.

        Returns:
            True if this component means "go up to the parent container".
        """
        return self.name == self.PARENT_NAME

    @staticmethod
    def parse(raw: str) -> "PathComponent":
        """Parse a single dotted-path segment into index or name form.

        Args:
            raw: One segment of a dotted path string, e.g. "0", "g-0", or "^".

        Returns:
            A PathComponent addressing that segment by index (if raw is a
            plain non-negative integer) or by name otherwise.
        """
        if raw.isdigit():
            return PathComponent(index=int(raw))
        return PathComponent(name=raw)

    def __str__(self) -> str:
        """
        Return this component's original dotted-path string form.

        Returns:
            The decimal index, or the component's name.
        """
        return str(self.index) if self.is_index else (self.name or "")


@dataclass
class Path:
    """A parsed Ink path: a sequence of components, absolute or relative.

    Args:
        components: The parsed path segments, in root-to-leaf order.
        is_relative: True if the original string began with ".", meaning
            resolution starts from a given container rather than the
            story root.
    """

    components: list[PathComponent] = field(default_factory=list)
    is_relative: bool = False

    @staticmethod
    def parse(raw: str) -> "Path":
        """Parse a dotted Ink path string into a Path.

        Args:
            raw: A path string as it appears in compiled JSON, e.g.
                "start.0.g-0.2" or ".^.b" (relative, one level up, then "b").

        Returns:
            The parsed Path.
        """
        is_relative = raw.startswith(".")
        stripped = raw[1:] if is_relative else raw
        components = [PathComponent.parse(part) for part in stripped.split(".") if part]
        return Path(components=components, is_relative=is_relative)

    def __str__(self) -> str:
        """
        Return this path's dotted string form.

        Returns:
            The reconstructed dotted path string, prefixed with "." if relative.
        """
        prefix = "." if self.is_relative else ""
        return prefix + ".".join(str(c) for c in self.components)


@dataclass
class Divert:
    """An unconditional or conditional `->` jump to another path.

    Args:
        target_path: Where to jump to. Ignored when is_variable_target is
            True — target_path is a placeholder Path in that case (the
            real destination is read from a variable at follow-time), kept
            only so every Divert has a well-typed target_path field
            without needing Optional.
        is_conditional: True if a truthy value must be popped off the eval
            stack first to decide whether to follow this divert.
        pushes_tunnel: True for a `->t->` tunnel-push divert (compiled
            from `-> knot ->`): pushes a return-address frame onto the
            call stack before jumping, so a later `->->` (PopTunnel) can
            resume right after this divert instead of ending the story.
        is_variable_target: True for a `{"->": "varName", "var": true}`
            variable-pointer divert (Section 10; compiled from Ink's
            empty-bracket choice syntax `* text[]` among other forms):
            `target_path`'s string form is actually a variable *name*,
            read at follow-time and expected to hold a DivertTargetValue
            whose own target_path is the real destination — ports
            Divert.hasVariableTarget/variableDivertName
            (ink-engine-runtime/Divert.cs).
    """

    target_path: Path
    is_conditional: bool = False
    pushes_tunnel: bool = False
    is_variable_target: bool = False


@dataclass
class ChoicePoint:
    """A `*`/`+` choice, addressed by the flags bitmask compiled into "flg".

    Bit values (matching the compiled JSON convention, confirmed against
    real inklecate output 2026-08-16): 1=has_condition, 2=has_start_content,
    4=has_choice_only_content, 8=is_invisible_default, 16=once_only.
    Section 3 only implements the plain `[choice-only]` bracket form
    (has_start_content unset) — start+choice-only combos compile to
    weave/tunnel machinery that needs the call stack (Section 5/6).

    Args:
        target_path: Where choosing this choice diverts to.
        flags: The raw compiled flags bitmask.
    """

    target_path: Path
    flags: int = 0

    @property
    def has_condition(self) -> bool:
        """Return whether a condition must be popped off the eval stack."""
        return bool(self.flags & 1)

    @property
    def has_start_content(self) -> bool:
        """Return whether this choice has text shown before the brackets."""
        return bool(self.flags & 2)

    @property
    def has_choice_only_content(self) -> bool:
        """Return whether this choice has bracketed choice-only text."""
        return bool(self.flags & 4)

    @property
    def is_invisible_default(self) -> bool:
        """Return whether this choice is auto-followed instead of shown."""
        return bool(self.flags & 8)

    @property
    def once_only(self) -> bool:
        """Return whether this choice is hidden once its target has been visited."""
        return bool(self.flags & 16)


@dataclass
class VariableReference:
    """A `{VAR?: name}` read of a global or temporary variable's current value.

    Args:
        name: The variable's name.
    """

    name: str


@dataclass
class VariableAssignment:
    """A `{VAR=: name}` (global) or `{temp=: name}` (local) variable write.

    Args:
        name: The variable's name.
        is_global: True for a `VAR=` global assignment, False for `temp=`.
        is_new_declaration: True if this is the variable's first
            declaration (no "re" key in the compiled JSON, or "re" false);
            False for a reassignment to an already-declared variable.
    """

    name: str
    is_global: bool
    is_new_declaration: bool


@dataclass
class DivertTargetValue:
    """A `{"^->": path}` literal divert-target value token, as it appears
    in a container's content list before being dispatched (e.g. `->
    knot_name` used as an expression, or `TURNS_SINCE(-> knot_name)`'s
    argument).

    Args:
        target_path: The path this value points at.
    """

    target_path: Path


@dataclass
class ResolvedDivertTarget:
    """The dispatched, eval-stack-resident form of a DivertTargetValue:
    the same first-class Ink value, but with its (possibly relative)
    target_path already resolved to the Container it addresses.

    Args:
        container: The resolved container, or None if the original
            target_path failed to resolve (an unreachable/malformed
            target — degrades to None rather than an exception, matching
            this module's standing philosophy).
    """

    container: Container | None


class Void:  # pylint: disable=too-few-public-methods
    """A pure marker type — instance identity/isinstance checks are its
    whole interface (mirrors this module's other sentinel-like dataclasses,
    e.g. ChoicePoint's own flag-only fields), so it has no methods at all.

    The implicit return value of a function that falls off the end of
    its own body without an explicit "~ret" (real Ink: functions may
    evaluate to Void, ink-engine-runtime/Story.cs). Distinct from the
    integer 0 — confirmed 2026-08-16 while fixing a bug found via Step 4's
    upload validation: `_advance_pointer` was pushing a bare Python `0` for
    this case, which EVAL_OUTPUT then printed as the literal text "0" for
    any void function called as a print expression (e.g. `{UPPERCASE(...)}`
    where UPPERCASE's fallback body has no `~ret`) — real inklecate prints
    nothing at all in that case. A `~ bump()` void-call statement is
    unaffected either way, since its result is always discarded by a
    trailing VOID_POP rather than ever reaching EVAL_OUTPUT.
    """


VOID = Void()


@dataclass
class ReadCountTarget:
    """A `{"CNT?": path}` bare read-count reference (e.g. `{knot_name}`
    used as a value — how many times knot_name has been visited).

    Args:
        target_path: The path whose visit count is being read.
    """

    target_path: Path


@dataclass
class FunctionCall:
    """A `{"f()": path}` call to an `== function ==` knot, or a
    `{"x()": name, "exArgs": n}` call to an EXTERNAL-declared function.

    Args:
        target_path: The function's target path — an absolute top-level
            name for an ordinary call (e.g. "add_points"), or a relative
            path for a function calling itself or a sibling
            (confirmed 2026-08-16, real compiled output: a recursive self
            -call from inside a function's own body compiles to a
            *relative* target like ".^.^.^", climbing back up to the
            function's own container — resolved the same way as a Divert/
            ChoicePoint's target_path, via _resolve_target, not always a
            bare self.root.named_content lookup). An "x()" call's target
            is always a bare top-level name (confirmed 2026-08-16), never
            relative — QuickBBS's own EXTERNAL always binds to its
            same-named ink fallback, never a self/sibling-relative call.
        is_external: True for "x()" (an EXTERNAL call — dispatched via the
            exact same _call_function machinery as an ordinary "f()" call,
            since the compiler already erases the distinction at runtime;
            this flag exists only so Step 4's upload validation can walk
            the tree and check that every EXTERNAL's declared fallback
            actually resolves, without also flagging an ordinary internal
            "f()" call to a genuinely broken/typo'd path as an "unbound
            EXTERNAL" error).
    """

    target_path: Path
    is_external: bool = False


@dataclass(frozen=True)
class ListValue:
    """An Ink LIST value: an ordered set of (origin, item) flags with
    integer values, e.g. `(Coins, Notes)` from `LIST Wallet = Coins, Notes,
    Cards`.

    Ports the observable behavior of ink-engine-runtime/InkList.cs as far
    as Section 7's real compiled-output scope needs (confirmed 2026-08-16):
    a plain Dictionary<InkListItem, int> keyed by (originName, itemName),
    plus the origin list names for LIST_ALL/LIST_INVERT/empty-value display
    (InkList.origins) — Section 7 stores entries as a plain dict keyed by
    (origin, item) tuples rather than a custom InkListItem type, since
    Python tuples are already hashable and comparable for free.

    Args:
        entries: This value's items, as {(origin_name, item_name): int_value}.
        origin_names: The list definition name(s) this value is known to
            come from — needed even for an empty value (e.g. a bare `VAR w
            = ()` typed to a specific list) so LIST_ALL/LIST_INVERT and
            item-addition (`+= someItem`) know which listDefs to consult.
    """

    entries: tuple[tuple[tuple[str, str], int], ...] = ()
    origin_names: tuple[str, ...] = ()

    @staticmethod
    def single(origin: str, item: str, value: int, origin_names: tuple[str, ...] | None = None) -> "ListValue":
        """Build a single-item ListValue, e.g. for a bare `Coins` reference.

        Args:
            origin: The item's origin list name.
            item: The item's own name.
            value: The item's integer value (from listDefs).
            origin_names: The value's known origins; defaults to (origin,)
                when not given (the common case — a literal item reference
                is only ever known to come from its own origin).

        Returns:
            A ListValue with exactly one entry.
        """
        return ListValue(entries=(((origin, item), value),), origin_names=origin_names or (origin,))

    def as_dict(self) -> dict[tuple[str, str], int]:
        """
        Return this value's entries as a plain dict for lookup/comparison.

        Returns:
            {(origin_name, item_name): int_value}.
        """
        return dict(self.entries)

    @property
    def ordered_entries(self) -> list[tuple[tuple[str, str], int]]:
        """
        Return entries sorted the way real Ink orders them for display/min/max.

        Ports InkList.orderedItems: sorted by value, then by origin name
        to break ties consistently for mixed-list values.

        Returns:
            entries sorted ascending by (value, origin_name).
        """
        return sorted(self.entries, key=lambda pair: (pair[1], pair[0][0]))

    def to_display_string(self) -> str:
        """
        Return this value's display form, e.g. "Coins, Notes".

        Ports InkList.ToString(): item names only (no origin qualifier),
        comma-joined, in orderedItems order.

        Returns:
            The comma-joined item names, or "" for an empty value.
        """
        return ", ".join(item_name for (_, item_name), _ in self.ordered_entries)


@dataclass
class Choice:
    """One choice offered to the player at a decision point.

    Args:
        text: The choice's display text (already whitespace-cleaned).
        target: The container choosing this choice diverts to, already
            resolved (Section 3's ChoicePoint target paths may be relative
            to the choice point's own container, e.g. ".^.c-0", so
            resolution happens once at choice-creation time rather than
            being redone later against the wrong start container).
    """

    text: str
    target: Container


class Container:
    """A node in the compiled story's content tree.

    Args:
        name: This container's own name (from a "#n" terminator entry),
            or None for unnamed containers (most positional containers).
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name
        self.parent: "Container | None" = None
        self.content: list[Any] = []
        self.named_content: dict[str, Any] = {}
        self.count_flags: int = 0

    @property
    def visits_should_be_counted(self) -> bool:
        """
        Return whether visiting this container should bump its visit count.

        Ports Container.visitsShouldBeCounted, bit 1 of the compiled "#f"
        flags (Container.CountFlags.Visits — ink-engine-runtime/Container.cs).

        Returns:
            True if bit 1 of count_flags is set.
        """
        return bool(self.count_flags & 1)

    @property
    def turn_index_should_be_counted(self) -> bool:
        """
        Return whether visiting this container should record the current turn index.

        Ports Container.turnIndexShouldBeCounted, bit 2 of "#f"
        (Container.CountFlags.Turns).

        Returns:
            True if bit 2 of count_flags is set.
        """
        return bool(self.count_flags & 2)

    @property
    def counting_at_start_only(self) -> bool:
        """
        Return whether this container only counts a visit when entered at its own start.

        Ports Container.countingAtStartOnly, bit 4 of "#f"
        (Container.CountFlags.CountStartOnly) — set for once-only choice
        gathers/knots so re-entering partway through (e.g. resuming after
        a tunnel return) doesn't count as a fresh visit.

        Returns:
            True if bit 4 of count_flags is set.
        """
        return bool(self.count_flags & 4)

    def add_content(self, item: Any) -> None:
        """Append a positionally-addressed child to this container.

        Args:
            item: The child object (Container, str, or other leaf value).
                If it is itself a Container, its parent is set to self.
        """
        if isinstance(item, Container):
            item.parent = self
        self.content.append(item)

    def add_named_content(self, name: str, item: Any) -> None:
        """Register a named child, addressable by name in a path component.

        Args:
            name: The key this child is addressed by (a knot/stitch/label name).
            item: The child object. If it is itself a Container, its
                parent is set to self.
        """
        if isinstance(item, Container):
            item.parent = self
        self.named_content[name] = item

    def content_with_component(self, component: PathComponent) -> Any:
        """Resolve a single path component against this container's children.

        Args:
            component: The path segment to resolve (index, name, or parent marker).

        Returns:
            The matching child (index-addressed, named, or the parent
            container), or None if no such child exists.
        """
        if component.is_parent:
            return self.parent
        if component.is_index:
            assert component.index is not None
            if 0 <= component.index < len(self.content):
                return self.content[component.index]
            return None
        assert component.name is not None
        return self.named_content.get(component.name)


def load_story_root(story_json: dict[str, Any]) -> Container:
    """Build the story's Container tree from its compiled JSON.

    Args:
        story_json: The parsed top-level compiled-Ink JSON object (must
            contain a "root" key holding the container list).

    Returns:
        The root Container of the story's content tree.

    Raises:
        InkPathError: If the JSON has no "root" key.
    """
    if "root" not in story_json:
        raise InkPathError("Compiled story JSON has no 'root' key")
    return _load_container(story_json["root"])


def load_list_defs(story_json: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Extract the story's LIST definitions from its compiled JSON.

    Args:
        story_json: The parsed top-level compiled-Ink JSON object.

    Returns:
        {list_name: {item_name: int_value}}, or {} if the story declares
        no LISTs (the "listDefs" key is always present but may be empty,
        confirmed 2026-08-16 against every bundled example story).
    """
    return story_json.get("listDefs", {})


def find_unbound_externals(root: Container) -> list[str]:
    """Find every EXTERNAL-declared function with no resolvable ink fallback.

    Compiled Ink JSON erases the EXTERNAL/ordinary-function distinction
    entirely except at the call site itself (confirmed 2026-08-16,
    Section 10/Step 4): `EXTERNAL name(...)` leaves no trace of its own,
    but a `{"x()": name, ...}` call to it still requires a same-named
    `=== function name(...) ===` to exist somewhere in the tree — the ink
    fallback QuickBBS always executes, since it never binds a real host
    function (Step 4's upload validation: "every EXTERNAL function the
    compiled story declares must have a same-named ink fallback function
    defined in the story"). Walks every Container reached from root
    (recursing into both positional content and named-only/terminator-dict
    children, matching _container_by_id_index()'s own traversal) collecting
    every FunctionCall.is_external target name, then checks each one
    resolves to a real Container via resolve_path.

    Args:
        root: The story's root Container (from load_story_root()).

    Returns:
        The sorted, de-duplicated list of EXTERNAL function names with no
        resolvable fallback — empty if every EXTERNAL call site resolves.
    """
    external_names: set[str] = set()

    def walk(container: Container) -> None:
        for item in container.content:
            if isinstance(item, Container):
                walk(item)
            elif isinstance(item, FunctionCall) and item.is_external:
                external_names.add(str(item.target_path))
        for item in container.named_content.values():
            if isinstance(item, Container):
                walk(item)

    walk(root)
    unbound = [name for name in external_names if not isinstance(resolve_path(root, Path.parse(name)), Container)]
    return sorted(unbound)


def _load_container(obj: list[Any]) -> Container:
    """Recursively build a Container from its compiled-JSON list form.

    Args:
        obj: The container's JSON list: positional content followed by an
            optional terminator dict of named content / "#n" / "#f".

    Returns:
        The constructed Container, with parent pointers set on every
        Container-typed child.
    """
    container = Container()

    positional = obj
    terminator = None
    if obj and isinstance(obj[-1], dict):
        positional = obj[:-1]
        terminator = obj[-1]

    for item in positional:
        loaded = _load_object(item)
        container.add_content(loaded)
        if isinstance(loaded, Container) and loaded.name:
            # Ports Container.TryAddNamedOnlyContent (ink-engine-runtime/
            # Container.cs): every positionally-added child that is
            # itself a named container (e.g. a `- (label)` gather or a
            # `=== knot ===` inside a weave) becomes addressable by that
            # name from its parent too, independent of whether the JSON
            # terminator dict separately lists it — confirmed 2026-08-16
            # as a real gap via testing TURNS_SINCE(-> label): the
            # target's own container carries a "#n" name but was never
            # added to the parent's named_content, so resolution silently
            # failed. No Section 1-8 fixture needed to address a
            # positionally-nested-but-named container by name from its
            # parent until Section 9's TURNS_SINCE/ReadCount usage.
            container.add_named_content(loaded.name, loaded)

    if terminator:
        for key, value in terminator.items():
            if key == "#n":
                container.name = value
            elif key == "#f":
                container.count_flags = value
            else:
                loaded_named = _load_object(value)
                if isinstance(loaded_named, Container):
                    # Ports JsonSerialisation.JArrayToContainer
                    # (ink-engine-runtime/JsonSerialisation.cs):
                    # `namedSubContainer.name = keyVal.Key` — every
                    # terminator-dict-only named child's own .name comes
                    # from the dict key itself, unconditionally, even
                    # though real compiled output never redundantly
                    # repeats that same name as the child's own "#n"
                    # (confirmed 2026-08-16 by grepping every
                    # terminator-dict entry across theintercept.ink's
                    # compiled output — none carry a matching "#n").
                    # Without this, a terminator-dict-only container has
                    # no name at all and is absent from its parent's
                    # positional content too, making it unreachable by
                    # _container_path()'s real-Ink-matching algorithm
                    # (Object.path in Object.cs: named-if-hasValidName,
                    # else positional index — never a named_content
                    # dict lookup) — caught as a real bug 2026-08-16
                    # while building Step 3's save-state serialization,
                    # which needs every reachable container to have a
                    # reliable, round-trippable path.
                    loaded_named.name = key  # pylint: disable=attribute-defined-outside-init
                container.add_named_content(key, loaded_named)

    return container


def _load_object(obj: Any) -> Any:
    """Convert one compiled-JSON token into its runtime representation.

    Containers become nested Container objects; text/newline leaves are
    unwrapped strings; divert and choice-point dicts (Section 3) become
    typed Divert/ChoicePoint objects. Every other leaf token (control
    commands, values, variable refs/assigns, etc.) is left as its raw JSON
    form as an opaque placeholder — later sections replace this with real
    typed objects as each op family is built.

    Args:
        obj: A single element from a container's content list.

    Returns:
        A nested Container for list tokens; the stripped string for
        text/newline tokens; a Divert or ChoicePoint for those dict forms;
        the raw JSON token unchanged otherwise.
    """
    if isinstance(obj, list):
        return _load_container(obj)
    if isinstance(obj, str) and obj.startswith("^"):
        return obj[1:]
    if isinstance(obj, dict):
        return _load_dict_object(obj)
    return obj


def _load_dict_object(obj: dict[str, Any]) -> Any:
    """Convert one compiled-JSON dict-form leaf into its typed runtime object.

    Args:
        obj: A dict-form leaf token (divert, choice point, variable
            reference/assignment — every other dict shape used by later
            sections passes through unchanged as an opaque placeholder).

    Returns:
        The matching typed object, or obj unchanged if no known key is present.
    """
    for key, builder in _DICT_OBJECT_BUILDERS:
        if key in obj:
            return builder(obj)
    return obj


def _load_list_value(obj: dict[str, Any]) -> ListValue:
    """Build a ListValue from a `{"list": {"Origin.Item": value, ...}}` leaf.

    Args:
        obj: The dict-form leaf token. "origins" holds the value's known
            origin list name(s) even when "list" itself is empty (a typed
            empty value, e.g. from `VAR w = ()` — confirmed 2026-08-16
            against real compiled output: {"list": {}, "origins": [...]}).

    Returns:
        The ListValue, with each "Origin.Item" key split on its first "."
        (confirmed 2026-08-16 that origin/item names themselves never
        contain "." in real compiled output).
    """
    entries = []
    for qualified_name, value in obj["list"].items():
        origin, _, item = qualified_name.partition(".")
        entries.append(((origin, item), int(value)))
    origin_names = tuple(obj.get("origins", []))
    if not origin_names:
        origin_names = tuple(dict.fromkeys(origin for (origin, _), _ in entries))
    return ListValue(entries=tuple(entries), origin_names=origin_names)


def _load_divert(obj: dict[str, Any]) -> Divert:
    """Build a Divert from a `{"->": target, "c": bool, "var": bool}` leaf.

    Args:
        obj: The dict-form leaf token. A "var": true entry means target is
            a variable *name* to read at follow-time (Section 10; ports
            Divert.hasVariableTarget — ink-engine-runtime/Divert.cs), not
            a path string — confirmed 2026-08-16 against real compiled
            output for Ink's empty-bracket choice syntax (`* text[]`).

    Returns:
        The Divert. For a variable-target divert, target_path holds a
        single-name-component placeholder Path (never resolved as a
        path — is_variable_target routes _follow_divert to read the
        real target from a variable instead), so the field stays
        well-typed without needing Optional.
    """
    target = str(obj["->"])
    if obj.get("var", False):
        return Divert(target_path=Path(components=[PathComponent(name=target)]), is_variable_target=True)
    return Divert(target_path=Path.parse(target), is_conditional=bool(obj.get("c", False)))


_DICT_OBJECT_BUILDERS: list[tuple[str, Any]] = [
    ("->", _load_divert),
    ("->t->", lambda obj: Divert(target_path=Path.parse(str(obj["->t->"])), pushes_tunnel=True)),
    ("*", lambda obj: ChoicePoint(target_path=Path.parse(str(obj["*"])), flags=int(obj.get("flg", 0)))),
    ("VAR?", lambda obj: VariableReference(name=str(obj["VAR?"]))),
    (
        "VAR=",
        lambda obj: VariableAssignment(name=str(obj["VAR="]), is_global=True, is_new_declaration=not obj.get("re", False)),
    ),
    (
        "temp=",
        lambda obj: VariableAssignment(name=str(obj["temp="]), is_global=False, is_new_declaration=not obj.get("re", False)),
    ),
    ("f()", lambda obj: FunctionCall(target_path=Path.parse(str(obj["f()"])))),
    # {"x()": name, "exArgs": n} — a call to an EXTERNAL-declared function.
    # Bug found 2026-08-16 while building Step 4's upload validation: this
    # key was never in this table, so every external call silently no-op'd
    # (fell through _dispatch_literal_content's opaque-token branch)
    # instead of dispatching to the function's ink fallback — Section 10's
    # own ExternalFallbackTests passed anyway by coincidence (uppercase.ink's
    # fallback is an identity passthrough, and string_to_list.ink's skipped
    # call left the original string on the eval stack, which happened to
    # render identically to the correctly-resolved LIST item for a
    # single-word match). Dispatches through the exact same FunctionCall/
    # _call_function machinery as an ordinary "f()" call — real Ink's own
    # compiler already erases the EXTERNAL/ordinary-function distinction
    # down to "call this top-level function by name" (confirmed 2026-08-16:
    # x()'s target is always a bare declared name, never a relative path,
    # so _resolve_target's existing absolute-path handling is sufficient).
    # "exArgs" (the declared external's arity) is intentionally unused, same
    # reasoning as "f()": arity is self-describing via what's already on
    # eval_stack when the call is reached.
    ("x()", lambda obj: FunctionCall(target_path=Path.parse(str(obj["x()"])), is_external=True)),
    ("list", _load_list_value),
    ("^->", lambda obj: DivertTargetValue(target_path=Path.parse(str(obj["^->"])))),
    ("CNT?", lambda obj: ReadCountTarget(target_path=Path.parse(str(obj["CNT?"])))),
]


def resolve_path(start: Container, path: Path) -> Container | Any | None:
    """Resolve a parsed Path to the content it addresses, starting from start.

    Args:
        start: The container resolution begins from — the story root for
            an absolute path, or the "current" container for a relative one.
        path: The parsed path to resolve.

    Returns:
        The resolved content (a Container or a leaf value), or None if any
        component along the path fails to resolve.
    """
    current: Any = start
    for component in path.components:
        if not isinstance(current, Container):
            return None
        current = current.content_with_component(component)
        if current is None:
            return None
    return current


GLUE = "<>"
NEWLINE = "\n"


def _is_whitespace_only(text: str) -> bool:
    """
    Return whether text contains only spaces/tabs (no other characters).

    Args:
        text: A leaf text token (already had any "^" marker stripped).

    Returns:
        True if text is non-empty and made up entirely of " "/"\\t".
    """
    return bool(text) and all(c in (" ", "\t") for c in text)


def _scan_newline_run(indices: range, text: str) -> tuple[int, int]:
    """Scan a run of spaces/tabs/newlines from one end of text, in the given order.

    Shared by the head (forward) and tail (backward) scans in
    _split_head_tail_whitespace: walks indices in the order given, treating
    inline whitespace as transparent, and stops at the first character
    that is neither whitespace nor a newline.

    Args:
        indices: The index sequence to scan, e.g. range(len(text)) for a
            forward (head) scan or range(len(text) - 1, -1, -1) for a
            backward (tail) scan.
        text: The text being scanned.

    Returns:
        A (first_newline, last_newline) pair of indices in scan order
        (i.e. for a backward scan, first_newline is the newline closest to
        the end of the string), or (-1, -1) if no newline was found before
        real content.
    """
    first_newline = -1
    last_newline = -1
    for i in indices:
        c = text[i]
        if c == NEWLINE:
            if first_newline == -1:
                first_newline = i
            last_newline = i
        elif c in (" ", "\t"):
            continue
        else:
            break
    return first_newline, last_newline


def _split_head_tail_whitespace(text: str) -> list[str] | None:
    """Split leading/trailing run-of-newlines-and-spaces off a text token.

    Ports StoryState.TrySplittingHeadTailWhitespace from the C# reference
    runtime (ink-engine-runtime/StoryState.cs): excess newlines at the head
    or tail of a string are collapsed to a single "\\n" each (with any
    surrounding spaces/tabs kept as their own separate token), so each
    piece can be pushed through the same glue/newline-dedup logic as if it
    had arrived as a separate token. Interior newlines are left untouched.

    Args:
        text: A leaf text token (already had any "^" marker stripped).

    Returns:
        None if no head/tail newline run was found (nothing to split); a
        list of the substrings, in order, resulting from the split.
    """
    length = len(text)

    head_first_newline, head_last_newline = _scan_newline_run(range(length), text)
    tail_last_newline, tail_first_newline = _scan_newline_run(range(length - 1, -1, -1), text)

    if head_first_newline == -1 and tail_last_newline == -1:
        return None

    pieces: list[str] = []
    inner_start = 0
    inner_end = length

    if head_first_newline != -1:
        if head_first_newline > 0:
            pieces.append(text[:head_first_newline])
        pieces.append(NEWLINE)
        inner_start = head_last_newline + 1

    if tail_last_newline != -1:
        inner_end = tail_first_newline

    if inner_end > inner_start:
        pieces.append(text[inner_start:inner_end])

    if tail_last_newline != -1 and tail_first_newline > head_last_newline:
        pieces.append(NEWLINE)
        if tail_last_newline < length - 1:
            pieces.append(text[tail_last_newline + 1 :])

    return pieces


class OutputStream:
    """Assembles visible turn text from leaf tokens using Ink's real
    glue/newline-suppression rules (Section 2 scope only).

    Not yet implemented (deferred to the section that first needs it):
    function-call-frame whitespace trimming, which needs a real call
    stack (Section 5/6). Only glue-triggered trimming and story-level
    newline dedup/no-leading-newline are implemented here.
    """

    def __init__(self) -> None:
        self.tokens: list[str] = []

    @property
    def ends_in_newline(self) -> bool:
        """
        Return whether the stream currently ends in a newline.

        Mirrors StoryState.outputStreamEndsInNewline: scans backward
        past glue, stopping at the first non-whitespace text.

        Returns:
            True if the most recent non-glue text token is exactly a
            newline; False otherwise (including when the stream is empty).
        """
        for token in reversed(self.tokens):
            if token == GLUE:
                continue
            if token == NEWLINE:
                return True
            if not _is_whitespace_only(token):
                break
        return False

    @property
    def contains_content(self) -> bool:
        """
        Return whether the stream has any non-whitespace, non-glue text.

        Returns:
            True if at least one token is real (non-whitespace) text.
        """
        return any(token != GLUE and not _is_whitespace_only(token) and token != NEWLINE for token in self.tokens)

    def _remove_existing_glue(self) -> None:
        """Drop trailing glue tokens, per RemoveExistingGlue in the C# source.

        Called only when non-whitespace text is about to be appended while
        a glue-trim is active — that text has "consumed" the glue's join,
        so the glue marker itself is no longer needed in the stream.
        """
        while self.tokens and self.tokens[-1] == GLUE:
            self.tokens.pop()

    def _trim_newlines_from_end(self) -> None:
        """Remove a trailing run of newline/whitespace text, per
        TrimNewlinesFromOutputStream in the C# source. Called when new
        glue arrives, so glue always "eats" whitespace immediately before it.
        """
        remove_from = -1
        for i in range(len(self.tokens) - 1, -1, -1):
            token = self.tokens[i]
            if token == GLUE:
                break
            if _is_whitespace_only(token):
                continue
            if token == NEWLINE:
                remove_from = i
            else:
                break
        if remove_from >= 0:
            del self.tokens[remove_from:]

    def _latest_glue_index(self) -> int:
        """Find the index of the most recent still-active glue token.

        Ports the backward scan in PushToOutputStreamIndividual: walks
        back from the end of the stream and returns the index of the
        first glue token encountered. Section 2 has no ControlCommand
        tokens in the stream (those are opaque/out of scope), so unlike
        the C# source this never has a BeginString boundary to stop at.

        Returns:
            The index of the most recent glue token, or -1 if the stream
            has no trailing glue (i.e. it was already closed off by real
            text, or none was ever pushed).
        """
        for i in range(len(self.tokens) - 1, -1, -1):
            if self.tokens[i] == GLUE:
                return i
        return -1

    def push(self, token: str) -> None:
        """Push one leaf token (text, newline, or glue) onto the stream.

        Ports StoryState.PushToOutputStreamIndividual: glue triggers a
        backward trim of trailing whitespace/newlines; while a glue token
        is still "open" (nothing real has been pushed since it arrived),
        every subsequent newline is suppressed outright, and the first
        non-whitespace text closes the glue by removing its marker.
        Outside of an open glue, ordinary newline dedup/no-leading-newline
        rules apply.

        Args:
            token: A text/newline leaf value (already "^"-stripped) or the
                literal glue marker "<>".
        """
        if token == GLUE:
            self._trim_newlines_from_end()
            self.tokens.append(GLUE)
            return

        glue_index = self._latest_glue_index()
        if glue_index != -1:
            if token == NEWLINE:
                return
            if not _is_whitespace_only(token):
                self._remove_existing_glue()
            self.tokens.append(token)
            return

        if token == NEWLINE:
            if self.ends_in_newline or not self.contains_content:
                return
            self.tokens.append(NEWLINE)
            return

        self.tokens.append(token)

    def push_text(self, text: str) -> None:
        """Push a raw leaf text token, splitting head/tail newline runs first.

        Args:
            text: The leaf text value (already "^"-stripped if it came
                from a "^"-marked JSON string). Plain "\\n" tokens should
                be passed straight to push(), not through here.
        """
        pieces = _split_head_tail_whitespace(text)
        if pieces is None:
            self.push(text)
            return
        for piece in pieces:
            self.push(piece)

    def get_text(self) -> str:
        """
        Return the assembled visible text for everything pushed so far.

        Ports Runtime.State.CleanOutputWhitespace from the C# reference: a
        second, display-time pass over the joined text that collapses any
        run of inline spaces/tabs down to a single space, unless it sits
        at the very start of a line (immediately after a newline). This is
        distinct from — and runs after — the push-time glue/newline logic
        above: two text pieces glued together each carrying their own
        adjacent space (e.g. "One " <> " Two ") would otherwise leave a
        double space at the join point, which real Ink output never shows.

        Returns:
            The fully assembled and whitespace-cleaned visible text, with
            glue markers omitted (a glue token that survived to this point
            had nothing to suppress and contributes no text of its own).
        """
        joined = "".join(token for token in self.tokens if token != GLUE)

        output: list[str] = []
        whitespace_start = -1
        line_start = 0
        for i, char in enumerate(joined):
            is_inline_whitespace = char in (" ", "\t")

            if is_inline_whitespace and whitespace_start == -1:
                whitespace_start = i

            if not is_inline_whitespace:
                if char != NEWLINE and whitespace_start > 0 and whitespace_start != line_start:
                    output.append(" ")
                whitespace_start = -1

            if char == NEWLINE:
                line_start = i + 1

            if not is_inline_whitespace:
                output.append(char)

        return "".join(output)


DONE_COMMANDS = frozenset({"done", "end"})
EVAL_START = "ev"
EVAL_END = "/ev"
STRING_START = "str"
STRING_END = "/str"
EVAL_OUTPUT = "out"
POP_TUNNEL = "->->"
FUNCTION_RETURN = "~ret"
VOID_POP = "pop"
START_THREAD = "thread"
DUPLICATE_TOP = "du"
CHOICE_COUNT = "choiceCnt"
TURNS = "turn"
TURNS_SINCE = "turns"
READ_COUNT = "readc"
VISIT_INDEX = "visit"
BEGIN_TAG = "#"
END_TAG = "/#"

# The full set of bare-string ControlCommand markers the compiled JSON
# format can emit (confirmed against serialisation.py's own ENCODING
# SCHEME docstring and control_command.py's CommandType enum,
# inkpy-reference/runtime/). Everything in this set is a real Ink
# control-command marker, never literal display text — confirmed a real
# bug 2026-08-16 by smoke-testing against `murder_scene.ink` (a bundled
# real-world story), where bare "nop"/"thread" tokens (NoOp,
# StartThread — both out of Section 3's scope, but still present in real
# compiled output well before any variable/function content) were being
# pushed to the output stream as if they were literal text, since only
# EVAL_START/EVAL_END/STRING_START/STRING_END/DONE_COMMANDS were
# recognized. Every other command in this set is unimplemented until its
# owning section (variables, call stack, LISTs, RNG, tags) — recognizing
# them here only prevents this specific literal-text leak; it does not
# implement their actual behavior.
CONTROL_COMMAND_MARKERS = frozenset(
    {
        "ev",
        "out",
        "/ev",
        "du",
        "pop",
        "~ret",
        "str",
        "/str",
        "nop",
        "choiceCnt",
        "turn",
        "turns",
        "readc",
        "rnd",
        "srnd",
        "visit",
        "seq",
        "thread",
        "done",
        "end",
        "listInt",
        "range",
        "lrnd",
        "#",
        "/#",
    }
)

# Section 4 native-function operator set: arithmetic/comparison/logic on
# Int/Float/String/Bool. Excludes list ops (?, !?, ^, LIST_*) and the two
# DivertTargetValue-only ops (Equal/NotEquals on divert targets) — no
# LIST/DivertTargetValue operands reach the eval stack yet (Sections 6/7).
# Ported from ink-engine-runtime/NativeFunctionCall.cs's op tables (Int/
# Float/String sections only), not inkpy (which has no NativeFunctionCall
# implementation at all — confirmed absent 2026-08-16).
NATIVE_FUNCTION_ARITY = {
    "+": 2,
    "-": 2,
    "/": 2,
    "*": 2,
    "%": 2,
    "_": 1,  # Negate
    "==": 2,
    ">": 2,
    "<": 2,
    ">=": 2,
    "<=": 2,
    "!=": 2,
    "!": 1,
    "&&": 2,
    "||": 2,
    "MIN": 2,
    "MAX": 2,
    "POW": 2,
    "FLOOR": 1,
    "CEILING": 1,
    "INT": 1,
    "FLOAT": 1,
}

# Section 7 LIST operator set: ported from NativeFunctionCall.cs's
# AddListBinaryOp/AddListUnaryOp call sites — LIST_RANGE/LIST_RANDOM are
# NOT here because they're not NativeFunctionCall operators at all in the
# real engine (confirmed 2026-08-16: they're ControlCommand.ListRange/
# ListRandom, already recognized-but-unimplemented via
# CONTROL_COMMAND_MARKERS's "range"/"lrnd" entries) — LIST_RANDOM also
# needs Section 8's seeded RNG regardless.
LIST_NATIVE_FUNCTION_ARITY = {
    "+": 2,
    "-": 2,
    "?": 2,
    "!?": 2,
    "^": 2,
    "==": 2,
    "!=": 2,
    ">": 2,
    "<": 2,
    ">=": 2,
    "<=": 2,
    "&&": 2,
    "||": 2,
    "LIST_MIN": 1,
    "LIST_MAX": 1,
    "LIST_ALL": 1,
    "LIST_COUNT": 1,
    "LIST_VALUE": 1,
    "LIST_INVERT": 1,
}
NATIVE_FUNCTION_ARITY.update(LIST_NATIVE_FUNCTION_ARITY)


def _coerce_native_function_operands(args: list[Any]) -> tuple[type, list[Any]]:
    """Coerce operands to the operation's shared type, per NativeFunctionCall.cs.

    "Higher level" types infect both sides so a binary op always runs on
    matching types: bool coerces to int first (no operation is ever done
    directly on a bool in the C# source either — see the comment there),
    then int < float < str, and any float or str operand promotes both
    sides to that type.

    Args:
        args: One or two operand values (bool/int/float/str).

    Returns:
        (coerced_type, coerced_args) — coerced_type is bool, int, float,
        or str; coerced_args holds args cast to that type.
    """
    types = [bool if isinstance(a, bool) else type(a) for a in args]
    if str in types:
        target: type = str
    elif float in types:
        target = float
    else:
        target = int
    coerced = [target(a) for a in args]
    return target, coerced


def _is_truthy(value: Any) -> bool:
    """Return whether a popped eval-stack value counts as true.

    Ports Story.IsTruthy (ink-engine-runtime/Story.cs) for the value
    types Section 4 supports: bool/int/float are truthy iff nonzero
    (bool included, since Python bools are ints); str is truthy iff
    non-empty. DivertTargetValue truthiness is a compile-time error in
    real Ink ("did you intend a function call?") and doesn't arise here
    since Section 4 never pushes one onto the eval stack.

    Args:
        value: A value popped off the eval stack.

    Returns:
        The value's truthiness.
    """
    if isinstance(value, str):
        return len(value) > 0
    if isinstance(value, ListValue):
        return len(value.entries) > 0
    return bool(value)


def _display_string(value: Any) -> str:
    """Render a popped eval-stack value as it appears in visible story text.

    Args:
        value: Any value that can reach the output stream via EVAL_OUTPUT.

    Returns:
        value.to_display_string() for a ListValue (item names only, no
        Python repr/dataclass noise); "true"/"false" for a bool (matches
        real inklecate output, confirmed 2026-08-16 — Python's str(bool)
        capitalizes, which real Ink never does); str(value) for everything
        else.
    """
    if isinstance(value, ListValue):
        return value.to_display_string()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def apply_native_function(name: str, args: list[Any], list_defs: dict[str, dict[str, int]] | None = None) -> Any:
    """Apply one native-function operator to its popped operands.

    Args:
        name: The operator's compiled-JSON symbol (e.g. "+", "==", "MOD").
        args: The operands, already popped off the eval stack in push
            order (args[0] pushed first).
        list_defs: The story's LIST definitions ({list_name: {item_name:
            int_value}}), needed only when args contains a ListValue and
            name is LIST_ALL/LIST_INVERT (see _list_unary_op). Defaults to
            {} — every other operator/type combination ignores this
            argument entirely.

    Returns:
        The operation's result (bool/int/float/str/ListValue).

    Raises:
        InkPathError: If name is a binary/unary-only string op not valid
            for the coerced operand type (e.g. "-" on strings), or an
            unsupported string-comparison-family op reaches string
            operands without a defined behavior here.
    """
    if any(isinstance(a, ListValue) for a in args):
        return _apply_list_native_function(name, args, list_defs or {})

    target, coerced = _coerce_native_function_operands(args)

    if target is str:
        return _apply_string_native_function(name, coerced)
    return _apply_numeric_native_function(name, coerced, is_float=target is float)


def _apply_string_native_function(name: str, args: list[Any]) -> Any:
    """Apply a string-typed native function (Add=concat, Equal, NotEquals only).

    Args:
        name: The operator symbol.
        args: One or two string operands.

    Returns:
        The result (str for "+", bool for "=="/"!=").

    Raises:
        InkPathError: If name has no defined string operation (matches
            the C# source's AddStringBinaryOp calls: only +, ==, != — Has/
            Hasnt (?, !?) are excluded for strings; the LIST-typed ?/!?
            family is handled separately by _apply_list_native_function).
    """
    if name == "+":
        return args[0] + args[1]
    if name == "==":
        return args[0] == args[1]
    if name == "!=":
        return args[0] != args[1]
    raise InkPathError(f"Native function {name!r} is not defined for string operands")


def _list_ordered_entries(value: ListValue) -> list[tuple[tuple[str, str], int]]:
    """
    Return value.ordered_entries, exposed as a module function for reuse.

    Args:
        value: The ListValue to order.

    Returns:
        value.ordered_entries (see ListValue.ordered_entries).
    """
    return value.ordered_entries


def _list_binary_op(name: str, first: ListValue, second: ListValue) -> Any:
    """Apply a two-LIST-operand native function.

    Ports the relevant InkList methods (Union/Without/Contains/Intersect/
    GreaterThan/LessThan/(Not)Equals/And/Or — ink-engine-runtime/InkList.cs)
    confirmed 2026-08-16 against real compiled output for +, -, ?, !?, ^,
    ==, !=, and one comparison (>). The remaining comparisons (<, >=, <=)
    follow directly from the same min/max-item logic, not independently
    re-verified against a real transcript for each operator but ported
    line-for-line from the same InkList methods.

    Args:
        name: The operator symbol.
        first: The left operand.
        second: The right operand.

    Returns:
        A ListValue for +/-/^ (set operations); bool for every comparison
        and Has/Hasnt/And/Or.

    Raises:
        InkPathError: If name has no defined two-LIST operation.
    """
    first_map, second_map = first.as_dict(), second.as_dict()
    ops: dict[str, Any] = {
        "+": lambda: ListValue(
            entries=tuple({**first_map, **second_map}.items()),
            origin_names=tuple(dict.fromkeys(first.origin_names + second.origin_names)),
        ),
        "-": lambda: ListValue(entries=tuple((k, v) for k, v in first_map.items() if k not in second_map), origin_names=first.origin_names),
        "^": lambda: ListValue(entries=tuple((k, v) for k, v in first_map.items() if k in second_map), origin_names=first.origin_names),
        "?": lambda: bool(second_map) and set(second_map) <= set(first_map),
        "!?": lambda: not (bool(second_map) and set(second_map) <= set(first_map)),
        "==": lambda: first_map == second_map,
        "!=": lambda: first_map != second_map,
        "&&": lambda: bool(first_map) and bool(second_map),
        "||": lambda: bool(first_map) or bool(second_map),
    }
    op = ops.get(name)
    if op is not None:
        return op()
    return _list_comparison_op(name, first, second)


def _list_comparison_op(name: str, first: ListValue, second: ListValue) -> bool:
    """Apply a LIST magnitude comparison (>, <, >=, <=).

    Ports InkList.GreaterThan/LessThan/GreaterThanOrEquals/LessThanOrEquals:
    an empty operand makes every one of these comparisons trivially decided
    by count alone (see each branch below) before any item value is looked
    at — confirmed 2026-08-16 against real compiled output for ">".

    Args:
        name: The comparison operator symbol.
        first: The left operand.
        second: The right operand.

    Returns:
        The comparison result.
    """
    first_entries, second_entries = _list_ordered_entries(first), _list_ordered_entries(second)

    def greater_than() -> bool:
        if not first_entries:
            return False
        if not second_entries:
            return True
        return first_entries[0][1] > second_entries[-1][1]

    def less_than() -> bool:
        if not second_entries:
            return False
        if not first_entries:
            return True
        return first_entries[-1][1] < second_entries[0][1]

    def greater_or_equal() -> bool:
        if not first_entries:
            return False
        if not second_entries:
            return True
        return first_entries[0][1] >= second_entries[0][1] and first_entries[-1][1] >= second_entries[-1][1]

    def less_or_equal() -> bool:
        if not second_entries:
            return False
        if not first_entries:
            return True
        return first_entries[-1][1] <= second_entries[-1][1] and first_entries[0][1] <= second_entries[0][1]

    comparisons = {">": greater_than, "<": less_than, ">=": greater_or_equal, "<=": less_or_equal}
    comparison = comparisons.get(name)
    if comparison is None:
        raise InkPathError(f"Native function {name!r} is not defined for LIST operands")
    return comparison()


def _list_unary_op(name: str, value: ListValue, list_defs: dict[str, dict[str, int]]) -> Any:
    """Apply a one-LIST-operand native function.

    Ports InkList.minItem/maxItem/all/inverse (ink-engine-runtime/InkList.cs)
    confirmed 2026-08-16 against real compiled output for LIST_MIN, LIST_MAX,
    LIST_ALL, LIST_COUNT, LIST_VALUE, and LIST_INVERT.

    Args:
        name: The operator symbol.
        value: The single LIST operand.
        list_defs: The story's LIST definitions ({list_name: {item_name:
            int_value}}), needed by LIST_ALL/LIST_INVERT to enumerate every
            item of value's origin list(s), not just the ones value
            currently holds.

    Returns:
        A ListValue for LIST_MIN/LIST_MAX/LIST_ALL/LIST_INVERT; int for
        LIST_COUNT/LIST_VALUE.

    Raises:
        InkPathError: If name has no defined one-LIST operation.
    """
    entries = _list_ordered_entries(value)
    if name == "LIST_MIN":
        return ListValue(entries=(entries[0],), origin_names=value.origin_names) if entries else ListValue()
    if name == "LIST_MAX":
        return ListValue(entries=(entries[-1],), origin_names=value.origin_names) if entries else ListValue()
    if name == "LIST_COUNT":
        return len(entries)
    if name == "LIST_VALUE":
        return entries[0][1] if entries else 0
    if name in ("LIST_ALL", "LIST_INVERT"):
        held = value.as_dict()
        result: dict[tuple[str, str], int] = {}
        for origin in value.origin_names:
            for item_name, item_value in list_defs.get(origin, {}).items():
                key = (origin, item_name)
                if name == "LIST_ALL" or key not in held:
                    result[key] = item_value
        return ListValue(entries=tuple(result.items()), origin_names=value.origin_names)
    raise InkPathError(f"Native function {name!r} is not defined for LIST operands")


def _apply_list_native_function(name: str, args: list[Any], list_defs: dict[str, dict[str, int]]) -> Any:
    """Apply one Section 7 LIST-typed native function.

    A LIST operand always takes priority in dispatch (called before
    _coerce_native_function_operands' bool/int/float/str coercion, since a
    ListValue is none of those) — matches the C# source's own type-directed
    dispatch, where NativeFunctionCall checks for List operands before
    falling through to Int/Float/String (ink-engine-runtime/
    NativeFunctionCall.cs's CallType resolution).

    Args:
        name: The operator symbol.
        args: One or two operands — at least one is a ListValue (checked
            by the caller); a lone non-list operand in a binary op (e.g.
            comparing a LIST against a bare int) has no defined operation
            here, matching Section 7's real-world scope (every fixture and
            bundled example story compares LIST against LIST or applies a
            unary LIST_* op, never a mixed LIST/int comparison).
        list_defs: The story's LIST definitions, needed by the unary
            LIST_ALL/LIST_INVERT ops (see _list_unary_op).

    Returns:
        See _list_unary_op/_list_binary_op.

    Raises:
        InkPathError: If any operand isn't a ListValue, or name has no
            defined LIST operation.
    """
    if not all(isinstance(a, ListValue) for a in args):
        raise InkPathError(f"Native function {name!r} requires all LIST operands, got {args!r}")
    if len(args) == 1:
        return _list_unary_op(name, args[0], list_defs)
    return _list_binary_op(name, args[0], args[1])


def _numeric_native_functions(is_float: bool) -> dict[str, Any]:
    """Build the operator-name -> callable table for numeric operands.

    Split from a single shared table (rather than two near-duplicates)
    only where int/float behavior genuinely diverges — FLOOR/CEILING/INT
    are identity on ints (an int is already its own floor/ceiling/int)
    but do real work on floats, and "/" truncates for ints but not
    floats — matching the C# source's separate
    AddIntUnaryOp/AddFloatUnaryOp and AddIntBinaryOp/AddFloatBinaryOp
    call sites for each op, not a single generic implementation.

    Args:
        is_float: True to build the float-operand table, False for int.

    Returns:
        A dict mapping operator symbol to a callable taking (first,
        second) — second is unused (may be None) for unary operators.
    """
    identity = (lambda x, _y: x) if not is_float else None
    return {
        "+": lambda x, y: x + y,
        "-": lambda x, y: x - y,
        "*": lambda x, y: x * y,
        "/": (lambda x, y: x / y) if is_float else (lambda x, y: int(x / y)),
        "%": lambda x, y: x % y,
        "_": lambda x, _y: -x,
        "==": lambda x, y: x == y,
        ">": lambda x, y: x > y,
        "<": lambda x, y: x < y,
        ">=": lambda x, y: x >= y,
        "<=": lambda x, y: x <= y,
        "!=": lambda x, y: x != y,
        "!": lambda x, _y: x == 0,
        "&&": lambda x, y: x != 0 and y != 0,
        "||": lambda x, y: x != 0 or y != 0,
        "MIN": min,
        "MAX": max,
        "POW": lambda x, y: float(x**y),
        "FLOOR": identity or (lambda x, _y: float(math.floor(x))),
        "CEILING": identity or (lambda x, _y: float(math.ceil(x))),
        "INT": identity or (lambda x, _y: int(x)),
        "FLOAT": lambda x, _y: float(x),
    }


def _apply_numeric_native_function(name: str, args: list[Any], is_float: bool) -> Any:
    """Apply an int- or float-typed native function.

    Args:
        name: The operator symbol.
        args: One or two int/float operands (already coerced to a
            matching type by the caller).
        is_float: True if args are float (changes Floor/Ceiling/Int/Float
            unary op behavior and division semantics to match the C#
            source's separate int/float operator tables).

    Returns:
        The operation's result.

    Raises:
        InkPathError: If name has no defined numeric operation.
    """
    first = args[0]
    second = args[1] if len(args) == 2 else None
    op = _numeric_native_functions(is_float).get(name)
    if op is None:
        raise InkPathError(f"Native function {name!r} is not defined for numeric operands")
    return op(first, second)


@dataclass
class Pointer:
    """A container plus an index into its content: "the next thing to run."

    Args:
        container: The container being stepped through, or None if this
            pointer has run off the end of the story.
        index: The position within container.content this pointer
            addresses.
    """

    container: Container | None
    index: int = 0

    def resolve(self) -> Any:
        """
        Return the content this pointer currently addresses.

        Returns:
            container.content[index], or the container itself if index is
            negative (used to mean "the container as a whole"), or None if
            this pointer has no container or index is out of range.
        """
        if self.container is None:
            return None
        if self.index < 0:
            return self.container
        if self.index >= len(self.container.content):
            return None
        return self.container.content[self.index]

    def copy(self) -> "Pointer":
        """
        Return a shallow copy of this pointer.

        Returns:
            A new Pointer with the same container and index.
        """
        return Pointer(self.container, self.index)

    @staticmethod
    def start_of(container: Container) -> "Pointer":
        """Build a pointer to the first content item of container.

        Args:
            container: The container to point into.

        Returns:
            A Pointer at index 0 of container.
        """
        return Pointer(container, 0)


@dataclass
class CallFrame:
    """One `== function ==` call-stack frame (Section 6 scope only —
    tunnels use the separate, simpler `tunnel_stack` from Section 5, since
    they need no per-frame temp scoping: a tunnel has no parameters or
    return value, just a return address).

    Args:
        return_pointer: Where to resume the caller once this frame pops
            (via FUNCTION_RETURN or falling off the end of the function's
            container).
        temps: This call's own local `temp=` scope, confirmed against real
            compiled output 2026-08-16 (nested functions each get their
            own independent `n` parameter without clobbering the caller's
            — see section6_nested_func.ink) — separate from Section 4/5's
            flat `InkRuntimeState.temps`, which now only backs the
            outermost (no active function call) scope.
    """

    return_pointer: Pointer
    temps: dict[str, Any] = field(default_factory=dict)


class InkRuntimeState:  # pylint: disable=too-many-instance-attributes
    """Tracks one story's playthrough position, output, and choices.

    Deliberately over the default instance-attribute threshold and will
    stay that way: this mirrors the real Ink engine's own StoryState,
    which carries dozens of fields (eval stack, call stack, variables,
    visit/turn counts, RNG state, etc.) — see the plan's "Interpreter
    state shape" section for the full target shape landing across
    Sections 4-10. Splitting this now would just be undone by the next
    section's additions.

    Section 3 scope: pointer advancement, unconditional-divert following,
    and `[choice-only]` ChoicePoint collection with once-only/sticky
    pruning by visit count. Section 4 adds: global/temp variables, the
    eval stack, the core arithmetic/comparison/logic/string operator set
    (see apply_native_function()), conditional diverts/choices (now
    actually followed/shown, not just parsed and skipped), and running
    the compiled "global decl" container once at construction time to
    initialize VAR declarations (ports Story.ResetGlobals —
    ink-engine-runtime/Story.cs — since inkpy has no equivalent).

    Args:
        root: The story's root Container (from load_story_root()).
        list_defs: The story's LIST definitions (from load_list_defs()),
            {list_name: {item_name: int_value}}. Defaults to {} for
            stories with no LIST declarations.
    """

    def __init__(self, root: Container, list_defs: dict[str, dict[str, int]] | None = None) -> None:
        self.root = root
        self.list_defs = list_defs or {}
        self.pointer: Pointer | None = Pointer.start_of(root)
        self.previous_pointer: Pointer | None = None
        self.output = OutputStream()
        self.current_choices: list[Choice] = []
        self.visit_counts: dict[int, int] = {}
        self.visit_turns: dict[int, int] = {}
        self.current_tags: list[str] = []
        self._in_tag = False
        self._tag_buffer = OutputStream()
        self.done = False
        self._eval_run_depth = 0
        self.globals: dict[str, Any] = {}
        self.temps: dict[str, Any] = {}
        self.eval_stack: list[Any] = []
        self._string_capture_stack: list[OutputStream] = []
        self.tunnel_stack: list[Pointer] = []
        self.call_stack: list[CallFrame] = []
        self._pending_thread = False
        self.turn_count = -1
        self.story_seed = NetRandom(_time_seed()).next() % 100
        self.previous_random = 0
        self.last_turn_text = ""
        self._register_list_item_globals()
        self._run_global_decl()

    def _register_list_item_globals(self) -> None:
        """Pre-register every LIST item name as a single-item-value global.

        Ports the observable effect of ListDefinitionsOrigin's item lookup
        (ink-engine-runtime/ListDefinition.cs): confirmed 2026-08-16 against
        real compiled output that a bare item name (e.g. `Notes` in `w +=
        Notes`) compiles to an ordinary `{"VAR?": "Notes"}` VariableReference,
        not a special list-item-lookup token — so the item must already be
        a resolvable global by the time any story content runs, before
        _run_global_decl() even executes the compiled "global decl"
        container. Two different LISTs sharing an item name is a real Ink
        ambiguity error at compile time (confirmed via ListDefinition.cs's
        AddItem, which throws when an unqualified name matches more than
        one origin) — out of scope here, so a later origin's item silently
        wins if that ever happens, rather than raising.
        """
        for list_name, items in self.list_defs.items():
            for item_name, value in items.items():
                self.globals[item_name] = ListValue.single(list_name, item_name, int(value))

    def _visit_count(self, container: Container) -> int:
        """
        Return how many times container has been stepped into.

        Args:
            container: The container to look up.

        Returns:
            The number of times _record_visit() has been called for this
            container, or 0 if never visited.
        """
        return self.visit_counts.get(id(container), 0)

    def _record_visit(self, container: Container, at_start: bool = True) -> None:
        """Increment container's visit count and/or record this turn's
        index against it, gated by its compiled count-flags.

        Ports Story.VisitContainer's gating (ink-engine-runtime/Story.cs):
        `if (!container.countingAtStartOnly || atStart) { ... }` — a
        container flagged counting-at-start-only (matches every once-only
        choice gather/knot fixture tested so far, confirmed 2026-08-16 via
        real compiled "#f" values) only counts a visit when actually
        entered at its own first content item, not when merely resumed or
        stepped past partway through (e.g. after a tunnel return). Visit
        count and turn index are gated independently by their own
        visits_should_be_counted/turn_index_should_be_counted bits — a
        container can be flagged for one without the other.

        Args:
            container: The container being entered.
            at_start: True if this visit is entering container at its own
                index 0 (the ordinary case for every call site in this
                module so far — descending into a container always lands
                on its first item, and a divert/choice target is always
                Pointer.start_of(target)); False only matters for a
                container flagged counting_at_start_only.
        """
        if container.counting_at_start_only and not at_start:
            return
        if container.visits_should_be_counted:
            self.visit_counts[id(container)] = self._visit_count(container) + 1
        if container.turn_index_should_be_counted:
            self.visit_turns[id(container)] = self.turn_count

    def _run_global_decl(self) -> None:
        """Run the compiled "global decl" container once, if present.

        Ports Story.ResetGlobals (ink-engine-runtime/Story.cs): VAR
        declarations compile into a container named "global decl" holding
        an eval-run per declaration ("ev <value> {"VAR=": name} /ev ...
        end"), which must be executed once before real play starts so
        `self.globals` holds each VAR's initial value. Temporarily points
        self.pointer at that container, steps it to completion (it always
        ends in a bare "end" ControlCommand — see DONE_COMMANDS), then
        restores self.pointer and self.done to their pre-bootstrap state
        so this doesn't look like "the story already ended" to the caller.
        """
        global_decl = self.root.named_content.get("global decl")
        if not isinstance(global_decl, Container):
            return

        original_pointer = self.pointer
        self.pointer = Pointer.start_of(global_decl)
        while not self.done and self.pointer is not None:
            if self._step():
                break
        self.pointer = original_pointer
        self.done = False

    def _pop_eval_stack(self, default: Any = 0) -> Any:
        """Pop one value off eval_stack, tolerating an empty stack.

        A well-formed compiled story always leaves exactly the values on
        eval_stack that later tokens expect to pop — but an out-of-scope
        construct (a LIST literal, a `VisitIndex`/`TURNS` result, etc.,
        Sections 7-9) can silently fail to push what a later pop expects,
        since Section 5 recognizes but doesn't implement those tokens'
        real behavior. Popping from an empty list would otherwise crash
        the whole interpreter on real-world content that happens to mix
        an in-scope construct with an out-of-scope one nearby — confirmed
        2026-08-16 via smoke-testing pontoon_example.ink, which hit this
        for a conditional divert's condition value.

        Args:
            default: The value to return instead of crashing when
                eval_stack is empty.

        Returns:
            The popped value, or default if eval_stack was empty.
        """
        return self.eval_stack.pop() if self.eval_stack else default

    def _duplicate_top_of_eval_stack(self) -> None:
        """Push a copy of eval_stack's top value, tolerating an empty stack.

        Ports ControlCommand.CommandType.Duplicate, shared by both
        _handle_string_content's main-stream DUPLICATE_TOP branch and
        _handle_eval_run_command's — confirmed 2026-08-16 that a switch-
        on-value construct's "du" token can be reached at either eval-run
        depth, depending on whether the switch itself sits inside an
        outer, still-open eval bracket in real compiled output.
        """
        if self.eval_stack:
            self.eval_stack.append(self.eval_stack[-1])

    @property
    def _current_temps(self) -> dict[str, Any]:
        """
        Return the temp-variable scope for the innermost active call frame.

        Section 6 gives each function call its own local `temp=` scope
        (CallFrame.temps), matching real compiled output where nested
        function calls each get an independent copy of a same-named
        parameter (confirmed 2026-08-16, section6_nested_func.ink) —
        Section 5's tunnels push no CallFrame (they have no parameters or
        return value), so a tunnel body still shares the outermost flat
        scope, matching real Ink where tunnels don't introduce a new
        VariablesState scope either.

        Returns:
            self.call_stack[-1].temps if a function call is active,
            otherwise self.temps (the outermost scope).
        """
        if self.call_stack:
            return self.call_stack[-1].temps
        return self.temps

    def _read_variable(self, name: str) -> Any:
        """Look up a variable's current value by name.

        Checks the current call frame's temps before globals, matching
        the reference's declared-shadowing order (a temp can shadow a
        global of the same name).

        Args:
            name: The variable's name.

        Returns:
            Its current value, or 0 if never declared (matches
            VariablesState's own "Variable not found... default value of
            0" warning-and-continue behavior rather than raising).
        """
        temps = self._current_temps
        if name in temps:
            return temps[name]
        if name in self.globals:
            return self.globals[name]
        return 0

    def _write_variable(self, assignment: VariableAssignment, value: Any) -> None:
        """Store a value under a VariableAssignment's target name.

        Args:
            assignment: The assignment being performed (says whether it's
                a global VAR= or a local temp=).
            value: The value popped off eval_stack to store.
        """
        if assignment.is_global:
            self.globals[assignment.name] = value
        else:
            self._current_temps[assignment.name] = value

    @staticmethod
    def _resolve_target(holder: Container, root: Container, path: Path) -> Any | None:
        """Resolve a Divert/ChoicePoint target path to the content it addresses.

        Ports Object.ResolvePath (ink-engine-runtime/Object.cs): for an
        absolute path, resolution starts at the story root. For a relative
        path, resolution starts at holder (the container directly holding
        the Divert/ChoicePoint) — critically, a leading "^" component on a
        relative path is *not* itself walked as a further step up to
        holder.parent; it is only an assertion/marker that the path is
        relative to holder and is discarded before resolving the
        remaining components. This is the detail the COUR4G3/inkpy port's
        equivalent silently gets wrong (confirmed 2026-08-16 against both
        the C# source's `path = path.tail` and real inklecate-compiled
        output: `.^.c-0` on a choice point addresses named content
        *within* the choice point's own holder container, not within
        holder's parent).

        Args:
            holder: The container that directly holds the Divert/
                ChoicePoint whose target_path is being resolved.
            root: The story's root container, used for absolute paths.
            path: The target path (relative or absolute).

        Returns:
            The resolved content (usually a Container), or None if any
            component fails to resolve.
        """
        if not path.is_relative:
            return resolve_path(root, path)
        components = path.components
        if components and components[0].is_parent:
            components = components[1:]
        return resolve_path(holder, Path(components=components, is_relative=True))

    def _visit_changed_containers_due_to_divert(self) -> None:
        """Record visits for ancestor containers newly entered by a jump.

        Ports VisitChangedContainersDueToDivert (Story.cs): after a divert
        or choice sets self.pointer to some new position, the normal
        step-by-step _descend_into_containers walk only records visits for
        containers *nested below* that new position — it never sees the
        containers *above* it that were also freshly entered (e.g. the
        named knot container itself, when diverting straight to a leaf
        several levels inside it). This walks up from the new pointer's
        immediate parent chain, recording a visit for each ancestor that
        was not already an ancestor of the previous pointer (so
        containers we're still "inside" from before the jump aren't
        double-counted).

        **at_start tracking (added Section 9, confirmed 2026-08-16 via
        TURNS_SINCE testing)**: an ancestor only counts as "entered at
        start" if the child pointing into it is literally that ancestor's
        own content[0], AND every ancestor closer to the leaf was also
        entered at start (ports the C# source's allChildrenEnteredAtStart
        latch — diverting to some index N>0 inside knot K means K itself
        was NOT entered at its start, even though K is still newly
        entered and still gets its plain visit count bumped). This only
        changes behavior for a container flagged counting_at_start_only
        (Container.counting_at_start_only) — Section 3-8's fixtures never
        exercised that combination (a countingAtStartOnly container
        entered away from its own index 0), so this was previously
        unobservable, not merely "not needed yet."
        """
        pointer = self.pointer
        if pointer is None or pointer.container is None:
            return

        previous_ancestors: set[int] = set()
        if self.previous_pointer is not None and self.previous_pointer.container is not None:
            resolved = self.previous_pointer.resolve()
            ancestor: Container | None = resolved if isinstance(resolved, Container) else self.previous_pointer.container
            while ancestor is not None:
                previous_ancestors.add(id(ancestor))
                ancestor = ancestor.parent

        child: Any = pointer.resolve()
        current_ancestor: Container | None = pointer.container
        all_at_start = True
        while current_ancestor is not None and (id(current_ancestor) not in previous_ancestors or current_ancestor.counting_at_start_only):
            # Ports the C# source's loop condition exactly (Story.cs,
            # VisitChangedContainersDueToDivert): an already-"open"
            # ancestor still gets re-evaluated if it's flagged
            # counting_at_start_only — confirmed 2026-08-16 via testing
            # TURNS_SINCE across a loop-back divert (`-> start` from
            # inside a container nested under `start` itself): stopping
            # at the first already-seen ancestor unconditionally (the
            # initial, incorrect version of this loop) meant `start`
            # never got a fresh at-start visit recorded when re-entered
            # via its own descendant's divert, since `start` was still
            # technically "open" from the previous pointer's ancestry.
            entering_at_start = bool(current_ancestor.content) and child is current_ancestor.content[0] and all_at_start
            all_at_start = entering_at_start
            self._record_visit(current_ancestor, at_start=entering_at_start)
            child = current_ancestor
            current_ancestor = current_ancestor.parent

    def _divert_start(self, divert: Divert, holder: Container) -> Pointer:
        """Resolve a Divert's target path to a starting Pointer.

        Ports Divert.target_pointer's is_index special case
        (inkpy-reference/runtime/divert.py, confirmed correct against
        real compiled output 2026-08-16 — the initial Section 3
        implementation dropped this case entirely and only handled a
        Container target, silently producing a null pointer whenever a
        divert's target path's last component was an index rather than a
        name; caught because such targets are common, e.g. the compiled
        "resume after this conditional-text block" address that follows
        every `{cond: a|b}` construct).

        Args:
            divert: The divert being followed.
            holder: The container that directly holds this divert object
                (used as the resolution start for a relative target path).

        Returns:
            A Pointer at the start of the target container; or, if the
            target path's last component is an index (meaning "resume
            inside this container at this position", not "enter this
            leaf as a container"), a Pointer at that index within the
            leaf's own parent container; or a null Pointer if resolution
            failed entirely.
        """
        if divert.is_variable_target:
            # Ports the variable-target branch of Story's Divert handling
            # (Story.cs): the "path" is actually a variable name — read
            # its current value, which must be a ResolvedDivertTarget (the
            # dispatched form of a DivertTargetValue literal — see its own
            # docstring for why resolution already happened at push time,
            # not here) — confirmed 2026-08-16 against real compiled
            # output for Ink's empty-bracket choice syntax `* text[]`,
            # which is what actually exercises this in the bundled
            # example stories.
            assert divert.target_path.components[0].name is not None
            var_name = divert.target_path.components[0].name
            value = self._read_variable(var_name)
            if not isinstance(value, ResolvedDivertTarget) or value.container is None:
                return Pointer(None)
            return Pointer.start_of(value.container)

        target = self._resolve_target(holder, self.root, divert.target_path)
        if isinstance(target, Container):
            return Pointer.start_of(target)

        components = divert.target_path.components
        if target is not None and components and components[-1].is_index:
            parent_path = Path(components=components[:-1], is_relative=divert.target_path.is_relative)
            if parent_path.components:
                parent = self._resolve_target(holder, self.root, parent_path)
            else:
                parent = holder if divert.target_path.is_relative else self.root
            if isinstance(parent, Container):
                assert components[-1].index is not None
                return Pointer(parent, components[-1].index)

        return Pointer(None)

    def _follow_divert(self, divert: Divert, holder: Container) -> None:
        """Update self.pointer for one Divert encountered while stepping.

        Args:
            divert: The divert being processed.
            holder: The container directly holding this divert (used to
                resolve its target path if relative).
        """
        if self._pending_thread:
            self._pending_thread = False
            assert self.pointer is not None
            self.pointer = self._advance_past(self.pointer)
            self._run_thread(divert, holder)
            return

        if divert.is_conditional and not _is_truthy(self._pop_eval_stack()):
            assert self.pointer is not None
            self.pointer = self._advance_past(self.pointer)
            return

        if divert.pushes_tunnel:
            # Ports CallStack.push(PushPopType.Tunnel) — a `-> knot ->`
            # divert pushes a return address (the position right after
            # this divert) before jumping, so a later `->->` (PopTunnel)
            # resumes here instead of ending the story. Section 5 only
            # implements the Tunnel push type — Function/
            # FunctionEvaluationFromGame frames are Section 6 scope.
            assert self.pointer is not None
            return_address = self._advance_past(self.pointer)
            assert return_address is not None
            self.tunnel_stack.append(return_address)

        self.previous_pointer = self.pointer
        self.pointer = self._divert_start(divert, holder)
        self._visit_changed_containers_due_to_divert()

    def _run_thread(self, divert: Divert, holder: Container) -> None:
        """Run a `<- knot` thread as an isolated sub-walk to its own stop point.

        Ports StartThread (Story.cs) as far as Section 6's observed real
        compiled-output scope needs (confirmed 2026-08-16, section6_thread*
        fixtures): a thread runs immediately and synchronously — not
        deferred — stepping its own independent Pointer from the divert's
        target until it either falls off the end (silently discarded, no
        effect on the main flow) or reaches its own choice point(s), which
        are appended to self.current_choices exactly like the main flow's
        own choices. Confirmed against real transcripts: threads
        contribute their choices *before* the main flow's own choices
        (thread runs immediately when "thread" is encountered, before
        stepping continues past it), and choosing a threaded choice
        resumes purely within that thread — the main flow's own pending
        choices and position are simply abandoned, which the existing
        choose()/Choice(target=Container) shape already does unconditionally
        (Choice carries no memory of "which flow produced it" because none
        is needed: every real transcript tested resumes solely from the
        chosen target, matching Section 3-5's existing choose()).
        A bare DONE_COMMANDS reached inside the thread ends only the
        thread's own sub-walk (self.done is never touched here), matching
        real Ink's per-thread completion rather than ending the whole story
        — confirmed 2026-08-16 against section6_thread.ink, where the
        thread's own "done" leaves the main flow's "-> DONE" still to run.

        Args:
            divert: The thread's own target divert (the one immediately
                following the "thread" marker).
            holder: The container directly holding this divert (used to
                resolve its target path if relative).
        """
        target = self._resolve_target(holder, self.root, divert.target_path)
        if not isinstance(target, Container):
            return

        thread_pointer: Pointer | None = Pointer.start_of(target)
        thread_done = False
        while not thread_done and thread_pointer is not None:
            thread_pointer = self._descend_into_containers(thread_pointer)
            thread_container = thread_pointer.container
            assert thread_container is not None
            if thread_pointer.index >= len(thread_container.content):
                break
            content = thread_pointer.resolve()
            if content is None:
                thread_pointer = self._advance_pointer(thread_pointer)
                continue
            if isinstance(content, ChoicePoint):
                self._process_choice_point(content, thread_container)
                thread_pointer = self._advance_pointer(thread_pointer)
                continue
            if isinstance(content, str) and content in DONE_COMMANDS:
                break
            saved_pointer = self.pointer
            self.pointer = thread_pointer
            thread_done = self._dispatch_content(content, thread_pointer, thread_container)
            thread_pointer = self.pointer
            self.pointer = saved_pointer

    def _pop_tunnel(self) -> None:
        """Handle a bare "->->" (PopTunnel) control command.

        Ports the PopTunnel branch of Story._perform_logic_and_flow_control
        (ink-engine-runtime/Story.cs): pops one value off eval_stack (the
        compiler always emits "ev void /ev" immediately before a plain
        `->->`, to leave room for the `->-> someExpr` override-target
        form — Section 5 doesn't implement that override, since no
        fixture or real-world example exercises it, but the plain-form
        void still has to be popped so it doesn't corrupt whatever
        expression evaluates next), then resumes at the most recently
        pushed tunnel return address. If tunnel_stack is empty (a `->->`
        outside any tunnel), this is a story error in real Ink; Section 5
        treats it as ending the story rather than raising, matching
        DONE_COMMANDS' own not-a-crash handling of unexpected story ends.
        """
        self._pop_eval_stack()
        if not self.tunnel_stack:
            self.done = True
            return
        self.pointer = self.tunnel_stack.pop()

    def _call_function(self, call: FunctionCall, holder: Container) -> None:
        """Push a CallFrame and jump into a `{"f()": path}` function call.

        Ports the Function branch of CallStack.Push
        (ink-engine-runtime/CallStack.cs) as far as Section 6/7 needs:
        arguments are already on eval_stack (pushed by the caller before
        this token, confirmed 2026-08-16), and the function body's own
        leading `temp=` assignments pop them into its fresh CallFrame
        scope — the interpreter itself never needs to know the function's
        arity.

        **Correction (2026-08-16, found via real-world smoke-testing
        listToNumber.ink)**: an ordinary top-level call target is an
        absolute path (e.g. "add_points"), but a function calling itself
        or a sibling function compiles to a *relative* target (e.g.
        ".^.^.^" for direct recursion, confirmed against
        section7_recurse.ink's real compiled output) — resolved via
        _resolve_target exactly like Divert/ChoicePoint targets, not
        always a bare self.root.named_content lookup as Section 6
        originally (incorrectly) assumed; that version silently failed
        every recursive/sibling function call, since no Section 6 fixture
        happened to exercise recursion.

        Args:
            call: The function call being processed.
            holder: The container directly holding this call (used to
                resolve its target path if relative).
        """
        target = self._resolve_target(holder, self.root, call.target_path)
        if not isinstance(target, Container):
            # An unresolvable function name is a story error in real Ink;
            # degrade gracefully rather than crash, matching this
            # section's standing "recognized but not runnable" philosophy.
            self.eval_stack.append(0)
            assert self.pointer is not None
            self.pointer = self._advance_past(self.pointer)
            return

        assert self.pointer is not None
        return_pointer = self._advance_past(self.pointer)
        assert return_pointer is not None
        self.call_stack.append(CallFrame(return_pointer=return_pointer))
        self.pointer = Pointer.start_of(target)
        self._visit_changed_containers_due_to_divert()

    def _return_from_function(self) -> None:
        """Handle a bare "~ret" (function return) control command.

        Ports the Function branch of Story._perform_logic_and_flow_control
        popping a CallFrame: the return value is already on eval_stack
        (pushed by the preceding "ev...{VAR?: name}.../ev" run, confirmed
        2026-08-16), so this only needs to restore self.pointer to the
        call frame's return address. If call_stack is empty (a "~ret"
        outside any function call — shouldn't happen in well-formed
        compiled output), degrades to ending the story rather than
        raising, matching _pop_tunnel's equivalent guard.
        """
        if not self.call_stack:
            self.done = True
            return
        frame = self.call_stack.pop()
        self.pointer = frame.return_pointer

    def _advance_past(self, pointer: Pointer) -> Pointer | None:
        """Move one content item past pointer, walking up ended containers.

        Ports the non-call-stack portion of Story._next_content: increments
        pointer.index; if that runs past the end of container.content,
        walks up to the parent container and continues from just after the
        child that ended, repeating until a valid position is found or the
        story root has no parent left to walk up to.

        Args:
            pointer: The current position (must have a container).

        Returns:
            The next Pointer, or None if the story has no more content
            anywhere above pointer.
        """
        current = pointer.copy()
        current.index += 1
        while current.container is not None and current.index >= len(current.container.content):
            ancestor = current.container.parent
            if ancestor is None or current.container not in ancestor.content:
                # No positional sibling to advance to: either the story
                # root (no parent) or a container reached via named/knot
                # addressing rather than positional nesting (e.g. falling
                # off the end of a knot with no divert) — both mean the
                # story has genuinely run out of content here, matching
                # real Ink's "falling off the end" behavior rather than an
                # error, confirmed against inklecate 2026-08-16.
                return None
            child_index = ancestor.content.index(current.container)
            current = Pointer(ancestor, child_index + 1)
        return current

    def _advance_pointer(self, pointer: Pointer) -> Pointer | None:
        """Advance the live self.pointer, popping a function frame if needed.

        A function body that falls off the end of its own container
        without an explicit "~ret" (confirmed real, valid compiled output
        2026-08-16: a void function like `bump()` above has no "~ret" at
        all) reaches the same "no positional sibling, no parent to walk
        up to" case _advance_past() already treats as "story genuinely
        ran out of content" — but when a CallFrame is active, that case
        instead means "this function call is over," matching real Ink's
        implicit Void return (ink-engine-runtime/Story.cs: "Functions may
        evaluate to Void"). This wrapper is the one place that
        distinguishes the two: true end-of-story only when call_stack is
        also empty.

        Args:
            pointer: The current pointer to advance from.

        Returns:
            The next Pointer; or, if a function frame popped, that frame's
            return_pointer; or None if the story has genuinely ended.
        """
        result = self._advance_past(pointer)
        while result is None and self.call_stack:
            self.eval_stack.append(VOID)
            frame = self.call_stack.pop()
            result = frame.return_pointer
        return result

    def _descend_into_containers(self, pointer: Pointer) -> Pointer:
        """Step into nested empty-index containers until content is reached.

        A pointer whose resolved content is itself a Container (Ink nests
        containers for grouping, e.g. a choice's own sub-container) doesn't
        point at real leaf content yet — descend to that container's first
        item, recording a visit for each container entered along the way.

        Args:
            pointer: The position to descend from.

        Returns:
            A Pointer at real leaf content (or an empty container with no
            content of its own, left as-is).
        """
        current = pointer
        content = current.resolve()
        while isinstance(content, Container):
            self._record_visit(content)
            if not content.content:
                break
            current = Pointer.start_of(content)
            content = current.resolve()
        return current

    def _process_choice_point(self, choice_point: ChoicePoint, holder: Container) -> None:
        """Evaluate a ChoicePoint and append a Choice if it should be shown.

        Ports Story.ProcessChoice (ink-engine-runtime/Story.cs): pops
        eval_stack in the same fixed order the compiler always emits
        pushes in — condition value first (it's pushed last, so it's on
        top), then choice-only text, then start text (Section 10:
        confirmed against real compiled output for Ink's empty-bracket
        choice syntax `* text[]`, which produces a ChoicePoint with
        has_start_content set and has_choice_only_content unset — the two
        flags are independent, not mutually exclusive as Section 3/4's
        original "out of scope" note assumed; a choice can have start
        text only, choice-only text only, both, or neither, and the C#
        source's own field order — hasChoiceOnlyContent popped before
        hasStartContent — is what this pop order ports) — regardless of
        whether the choice ends up shown, since the compiled token stream
        already ran and pushed these values onto the stack before the
        ChoicePoint object itself was reached; leaving them unpopped
        would corrupt whatever expression evaluates next.

        Args:
            choice_point: The choice point being processed.
            holder: The container that directly holds this choice point
                (used to resolve its target path if relative).
        """
        show_choice = True
        if choice_point.has_condition and not _is_truthy(self._pop_eval_stack()):
            show_choice = False

        choice_only_text = self._pop_eval_stack(default="") if choice_point.has_choice_only_content else ""
        start_text = self._pop_eval_stack(default="") if choice_point.has_start_content else ""

        if not show_choice:
            return

        target = self._resolve_target(holder, self.root, choice_point.target_path)
        if not isinstance(target, Container):
            return

        if choice_point.once_only and self._visit_count(target) > 0:
            return

        text = (str(start_text) + str(choice_only_text)).strip()
        self.current_choices.append(Choice(text=text, target=target))

    def _handle_string_in_capture(self, content: str) -> None:
        """Push one leaf token into the innermost active string-capture stream.

        Args:
            content: The leaf value to capture (text, glue, or newline).
        """
        capture = self._string_capture_stack[-1]
        if content in (GLUE, NEWLINE):
            capture.push(content)
        else:
            capture.push_text(content)

    def _handle_string_capture_command(self, content: str) -> bool:
        """Handle one string leaf token belonging to the str/.../str family.

        Args:
            content: The leaf value.

        Returns:
            True if content was a string-capture marker or was consumed by
            an active capture; False if the caller should try other
            eval-run command types instead.
        """
        if content == STRING_START:
            # Ports BeginString/EndString (Story.cs): text between str and
            # /str is captured into its own OutputStream (so it still gets
            # real glue/newline handling) rather than the main output
            # stream, then closed into a single string value pushed onto
            # eval_stack when /str arrives.
            self._string_capture_stack.append(OutputStream())
            return True
        if content == STRING_END:
            captured = self._string_capture_stack.pop()
            self.eval_stack.append(captured.get_text())
            return True
        if self._string_capture_stack:
            if content in CONTROL_COMMAND_MARKERS:
                # A bare "nop" (and any other still-unimplemented control
                # command) can appear *inside* an active str/../str capture,
                # not just at the main-stream level — confirmed a real bug
                # 2026-08-16 via smoke-testing an inline conditional-choice-
                # text construct (`* [Follow {cond:A|B}]`): the compiler
                # emits "nop" as a branch separator inside the choice-only
                # text's own string-capture run, and this method was
                # unconditionally capturing every token as literal text
                # once a capture was active, leaking "nop" onto the end of
                # the choice label (e.g. "Angelanop"). Must be silently
                # consumed here exactly like the main-stream branch in
                # _handle_string_content already does, not captured as text.
                return True
            self._handle_string_in_capture(content)
            return True
        return False

    def _handle_eval_run_command(self, content: str) -> bool:
        """Handle one string leaf token while inside an "ev".."/ev" run.

        Args:
            content: The leaf value (an operator symbol, EVAL_OUTPUT, a
                string-capture marker, or an eval-run-local literal).

        Returns:
            True if content was recognized and handled here; False if the
            caller should fall through to ordinary main-stream handling
            (only possible for EVAL_START/EVAL_END themselves, handled by
            the caller, not this method).
        """
        if self._handle_string_capture_command(content):
            return True
        if content == EVAL_OUTPUT:
            if self.eval_stack:
                value = self._pop_eval_stack()
                if not isinstance(value, Void):
                    self.output.push_text(_display_string(value))
            return True
        if content == VOID_POP:
            # A void function call (e.g. `~ bump()`, no `~return`) always
            # leaves a value on eval_stack for symmetry with non-void
            # calls (real Ink's implicit Void return, confirmed
            # 2026-08-16 — see _advance_pointer's docstring) — the
            # compiler always emits a bare "pop" right after such a call
            # to discard it. _pop_eval_stack() tolerates an empty stack
            # defensively, matching this section's standing philosophy,
            # though a well-formed call always leaves something to pop.
            self._pop_eval_stack()
            return True
        if content == DUPLICATE_TOP:
            # A switch-on-value construct's per-branch "du" can itself
            # execute at eval-run depth > 0, not just depth 0 — confirmed
            # 2026-08-16 via smoke-testing listToNumber.ink's recursive
            # bit-storage logic: the whole switch weave container is
            # itself nested inside an outer, still-open "ev" bracket in
            # real compiled output (the enclosing conditional's own
            # condition-eval run), so this must be handled here too, not
            # only in the main-stream branch _handle_string_content
            # already has.
            self._duplicate_top_of_eval_stack()
            return True
        return self._handle_eval_run_command_tail(content)

    def _handle_eval_run_command_tail(self, content: str) -> bool:
        """Handle the story-metadata/RNG/native-function tail of an eval
        run command, once the always-present markers (string-capture,
        EVAL_OUTPUT, VOID_POP, DUPLICATE_TOP) are ruled out.

        Split from _handle_eval_run_command purely to keep that method's
        branch/return count within pylint's threshold as Section 8/9 grew
        it — same reasoning as _handle_story_metadata_command's own split.

        Args:
            content: The leaf value, already confirmed not one of the
                markers _handle_eval_run_command itself handles.

        Returns:
            True (every case here is either handled or the intentional
            unreachable-literal fallthrough, both treated as consumed).
        """
        if content in (CHOICE_COUNT, TURNS, TURNS_SINCE, READ_COUNT, VISIT_INDEX):
            self._handle_story_metadata_command(content)
            return True
        if content in ("rnd", "srnd", "seq", "lrnd"):
            self._handle_rng_command(content)
            return True
        if content in NATIVE_FUNCTION_ARITY:
            self._apply_operator_defensively(content)
            return True
        # Numeric/text literals inside an eval run that aren't one of the
        # cases above are unreachable here — plain literal values
        # (int/float/str) are dispatched in _dispatch_content by Python
        # type, not as strings, except for string literals inside
        # str/.../str (handled above). Nothing legitimate falls through
        # to here; treated as consumed either way.
        return True

    def _handle_story_metadata_command(self, name: str) -> None:
        """Handle CHOICE_COUNT/TURNS/TURNS_SINCE/ReadCount/VisitIndex.

        Each of these bare ControlCommand markers pushes a single int onto
        eval_stack, computed from story-level bookkeeping this module
        already tracks (current_choices, turn_count, visit_counts,
        visit_turns) — grouped into one dispatch here (rather than five
        separate `if` branches inline in _handle_eval_run_command) purely
        to keep that method's branch/return count within pylint's
        threshold; each still ports its own distinct C# Story.cs case
        (documented individually below).

        Args:
            name: One of CHOICE_COUNT, TURNS, TURNS_SINCE, READ_COUNT, VISIT_INDEX.
        """
        if name == CHOICE_COUNT:
            # Ports ControlCommand.CommandType.ChoiceCount: the number of
            # choices generated so far *this turn* (Story.cs reads
            # state.generatedChoices.Count directly) — confirmed
            # 2026-08-16 against real compiled output that this is always
            # read before any later-in-the-turn ChoicePoint runs, so
            # len(self.current_choices) at this exact moment is the
            # correct count, not a running total across turns.
            self.eval_stack.append(len(self.current_choices))
        elif name == TURNS:
            # Ports ControlCommand.CommandType.Turns: state.currentTurnIndex+1.
            self.eval_stack.append(self.turn_count + 1)
        elif name == TURNS_SINCE:
            self._push_turns_since()
        elif name == READ_COUNT:
            self._push_read_count()
        else:
            # VISIT_INDEX. Ports ControlCommand.CommandType.VisitIndex:
            # pushes VisitCountForContainer(self.pointer.container) - 1 —
            # the *current* container's own visit count, minus 1 to
            # convert count to a zero-based index (Story.cs: "index not
            # count"). This is the visit-count read behind sequences
            # (`{a|b|c}`, capped via MIN) and cycles (`{&a|b|c}`, wrapped
            # via %) — confirmed 2026-08-16 as a real gap: "visit" had
            # been left as a silent CONTROL_COMMAND_MARKERS no-op since
            # Section 3, so every sequence/cycle read 0 (an absent push
            # defaulting via _pop_eval_stack) until this section wired it up.
            assert self.pointer is not None and self.pointer.container is not None
            self.eval_stack.append(self._visit_count(self.pointer.container) - 1)

    def _pop_resolved_divert_target(self) -> Container | None:
        """Pop a ResolvedDivertTarget off eval_stack and unwrap it.

        Shared by _push_turns_since()/_push_read_count(), both of which
        consume a DivertTargetValue's dispatched (container-resolved)
        form the same way — see ResolvedDivertTarget's own docstring for
        why the wrapper exists.

        Returns:
            The wrapped container, or None if the popped value wasn't a
            ResolvedDivertTarget at all (an out-of-scope construct never
            pushed one) or wrapped a failed resolution.
        """
        target = self._pop_eval_stack(default=None)
        if isinstance(target, ResolvedDivertTarget):
            return target.container
        return None

    def _push_turns_since(self) -> None:
        """Handle a bare "turns" (TURNS_SINCE) command.

        Ports StoryState.TurnsSinceForContainer: pops a ResolvedDivertTarget
        (pushed by _dispatch_literal_content's DivertTargetValue branch)
        and pushes how many turns have elapsed since that container was
        last visited, or -1 if it has never been visited. An unresolvable
        target degrades to -1 as well, matching the "never visited" case
        rather than crashing — the real engine's own fallback for a lookup
        failure (Story.cs: "Failed to find container... assume
        -1/unknown") reaches the same shape.
        """
        target = self._pop_resolved_divert_target()
        if target is None or id(target) not in self.visit_turns:
            self.eval_stack.append(-1)
            return
        self.eval_stack.append(self.turn_count - self.visit_turns[id(target)])

    def _push_read_count(self) -> None:
        """Handle a bare "readc" (ReadCount) command.

        Ports StoryState.VisitCountForContainer via the explicit
        READ_COUNT(-> knot) function syntax: pops a ResolvedDivertTarget
        and pushes its visit count (0 if never visited or unresolvable —
        matches the real engine's own "assume 0, default to allowing
        entry" fallback for a lookup failure).
        """
        target = self._pop_resolved_divert_target()
        self.eval_stack.append(self._visit_count(target) if target is not None else 0)

    def _handle_rng_command(self, name: str) -> None:
        """Handle "rnd" (RANDOM), "srnd" (SEED_RANDOM), "seq"
        (SequenceShuffleIndex, the `{~a|b|c}` shuffle operator), or
        "lrnd" (LIST_RANDOM).

        Ports the Random/SeedRandom/SequenceShuffleIndex/ListRandom
        branches of Story._perform_logic_and_flow_control
        (ink-engine-runtime/Story.cs), using NetRandom (the ported .NET
        System.Random algorithm — see its own docstring) so results match
        real inklecate output for the same story_seed, confirmed
        2026-08-16 against real compiled output for all four operators.

        Args:
            name: "rnd", "srnd", "seq", or "lrnd".
        """
        if name == "lrnd":
            self._push_list_random()
            return
        if name == "srnd":
            # SEED_RANDOM(seed): pops the new seed, resets previous_random
            # to 0 (a fresh reseed discards the running RNG state), and
            # pushes a Void placeholder for the compiler's trailing bare
            # "pop" to discard (SEED_RANDOM returns nothing in real Ink).
            self.story_seed = int(self._pop_eval_stack(default=0))
            self.previous_random = 0
            self.eval_stack.append(0)
            return

        if name == "rnd":
            # RANDOM(min, max): operands pushed min-then-max, so max is on
            # top and popped first.
            max_value = int(self._pop_eval_stack(default=0))
            min_value = int(self._pop_eval_stack(default=0))
            random_range = max_value - min_value + 1
            if random_range <= 0:
                self.eval_stack.append(min_value)
                return
            result_seed = self.story_seed + self.previous_random
            next_random = NetRandom(result_seed).next()
            self.eval_stack.append((next_random % random_range) + min_value)
            self.previous_random = next_random
            return

        # "seq": SequenceShuffleIndex for `{~a|b|c}`. Operands pushed
        # visit-count-then-num-elements (the compiled "visit", N, "seq"
        # order confirmed 2026-08-16), so num_elements is popped first.
        num_elements = int(self._pop_eval_stack(default=1))
        seq_count = int(self._pop_eval_stack(default=0))
        if num_elements <= 0:
            self.eval_stack.append(0)
            return
        loop_index = seq_count // num_elements
        iteration_index = seq_count % num_elements
        self.eval_stack.append(self._shuffle_index(num_elements, loop_index, iteration_index))

    def _shuffle_index(self, num_elements: int, loop_index: int, iteration_index: int) -> int:
        """Compute which element `{~a|b|c}` should resolve to this visit.

        Ports Story.NextSequenceShuffleIndex: derives a seed from the
        current container's path (a simple character-sum hash, matching
        the C# source exactly rather than a stronger hash — real Ink's own
        algorithm is this simple), the loop count (how many full passes
        through the shuffle have completed), and story_seed; then draws
        without replacement from the element indices until iteration_index
        is reached.

        Args:
            num_elements: How many alternatives the shuffle has.
            loop_index: How many full shuffle cycles have completed.
            iteration_index: Which draw within the current cycle this is.

        Returns:
            The chosen element's index.
        """
        assert self.pointer is not None and self.pointer.container is not None
        try:
            path_str = _container_path(self.pointer.container)
        except InkPathError:
            # A malformed/unreachable container tree shape shouldn't
            # occur for any container load_story_root() produces (see
            # _container_path()'s own docstring for the real fix), but
            # degrades to an empty path string rather than crashing the
            # whole turn if it somehow does — only affects which element
            # this one shuffle picks, matching this module's standing
            # out-of-scope-construct-degrades-not-crashes philosophy.
            path_str = ""
        sequence_hash = sum(ord(c) for c in path_str)
        random_seed = sequence_hash + loop_index + self.story_seed
        rng = NetRandom(random_seed)
        unpicked = list(range(num_elements))
        chosen_index = unpicked[0]
        for i in range(iteration_index + 1):
            chosen = rng.next() % len(unpicked)
            chosen_index = unpicked.pop(chosen)
            if i == iteration_index:
                break
        return chosen_index

    def _push_list_random(self) -> None:
        """Handle "lrnd" (LIST_RANDOM(list)).

        Ports the ListRandom branch of
        Story._perform_logic_and_flow_control: pops a ListValue, and (if
        non-empty) picks one entry at random — by index into entries in
        their original insertion order, matching real .NET Dictionary
        enumeration order for a freshly-built InkList, confirmed
        2026-08-16 against real compiled output — and pushes a new
        single-item ListValue holding just that entry. An empty list, or
        a popped value that isn't a ListValue at all (an out-of-scope
        upstream construct never pushed one), degrades to pushing an
        empty ListValue rather than crashing.
        """
        value = self._pop_eval_stack(default=None)
        if not isinstance(value, ListValue) or not value.entries:
            self.eval_stack.append(ListValue())
            return
        result_seed = self.story_seed + self.previous_random
        next_random = NetRandom(result_seed).next()
        chosen_key, chosen_value = value.entries[next_random % len(value.entries)]
        self.eval_stack.append(ListValue(entries=((chosen_key, chosen_value),), origin_names=(chosen_key[0],)))
        self.previous_random = next_random

    def _apply_operator_defensively(self, name: str) -> None:
        """Pop operands for one native-function operator and push its result.

        Degrades to a no-op rather than crashing when the operands aren't
        there or don't coerce cleanly — both are consequences of an
        out-of-scope construct (LIST/DivertTargetValue operands, Sections
        7/8) never pushing what a later operator expects, not a defect in
        this section's own operators. Confirmed as real crashes 2026-08-16
        via smoke-testing pontoon_example.ink: an empty-stack "MIN"
        (IndexError) and a None operand from an unassigned variable
        (TypeError) both reached this code path on real, unmodified
        bundled example content.

        Args:
            name: The operator symbol (already confirmed present in
                NATIVE_FUNCTION_ARITY by the caller).
        """
        arity = NATIVE_FUNCTION_ARITY[name]
        if len(self.eval_stack) < arity:
            return
        args = [self.eval_stack.pop() for _ in range(arity)]
        args.reverse()
        try:
            result = apply_native_function(name, args, self.list_defs)
        except (InkPathError, TypeError, ValueError):
            return
        self.eval_stack.append(result)

    def _handle_tag_command(self, content: str) -> bool:
        """Handle one main-stream token belonging to the "#"/.../"/#"
        tag-capture family.

        Ports the BeginTag/EndTag branches of Story.cs: text between "#"
        and "/#" is excluded from visible output entirely (StoryState.
        currentText's "inTag" skip) and collected separately into
        current_tags instead — confirmed 2026-08-16 against real compiled
        output/transcripts. Split out of _handle_string_content purely to
        keep that method's branch count within pylint's threshold, same
        reasoning as _handle_string_capture_command's own split.

        Args:
            content: The leaf value.

        Returns:
            True if content was a tag marker or was consumed by an active
            tag capture; False if the caller should try other main-stream
            handling instead.
        """
        if content == BEGIN_TAG:
            self._in_tag = True
            self._tag_buffer = OutputStream()
            return True
        if content == END_TAG:
            self.current_tags.append(self._tag_buffer.get_text())
            self._in_tag = False
            return True
        if self._in_tag:
            if content in CONTROL_COMMAND_MARKERS:
                # A bare "nop" (and any other still-unimplemented control
                # command) can appear inside an active tag capture too, not
                # just the main output stream or a str/../str choice-text
                # capture (see _handle_string_capture_command's identical
                # fix, same bug class) — confirmed a real bug 2026-08-16 via
                # smoke-testing an inline conditional inside a tag
                # (`# image: {cond:a.jpg|b.jpg}`): unlike choice-only text,
                # the compiler does not wrap this construct in ev/../ev at
                # all, so it runs at main-stream depth while _in_tag is
                # still True, and the branch's trailing "nop" was being
                # captured as literal tag text (e.g. "image: a.jpgnop")
                # instead of being silently consumed like the main-stream
                # CONTROL_COMMAND_MARKERS branch already does.
                return True
            if content in (GLUE, NEWLINE):
                self._tag_buffer.push(content)
            else:
                self._tag_buffer.push_text(content)
            return True
        return False

    def _handle_string_content(self, content: str) -> bool:
        """Process one string leaf token: a control-command marker, operator,
        text, or a stop signal.

        Args:
            content: The string leaf value at the current pointer.

        Returns:
            True if this token ends the story (a DONE_COMMANDS marker);
            False otherwise.
        """
        if content in DONE_COMMANDS:
            self.done = True
            return True
        if content == EVAL_START:
            self._eval_run_depth += 1
        elif content == EVAL_END:
            self._eval_run_depth -= 1
        elif self._eval_run_depth > 0 or self._string_capture_stack:
            # A string-capture run (str/.../str) can itself be reached
            # from outside "ev".."/ev" in principle, but in practice only
            # ever appears nested inside one (see the ENCODING SCHEME
            # docstring) — self._string_capture_stack is checked here too
            # defensively so a capture in progress is never abandoned.
            self._handle_eval_run_command(content)
        elif content == START_THREAD:
            # Confirmed against real compiled output 2026-08-16: a bare
            # "thread" marker is always immediately followed by the
            # Divert it applies to (`<- knot` compiles to "thread" then
            # {"->": knot}) — sets a flag _follow_divert checks so that
            # one Divert runs as an isolated sub-walk (see _run_thread)
            # instead of jumping the main self.pointer.
            self._pending_thread = True
        elif content == DUPLICATE_TOP:
            # Ports ControlCommand.CommandType.Duplicate: a switch-on-value
            # construct (`{x: - 1: ... - 2: ...}`) pushes the switch value
            # once and re-tests it against each branch's own condition, so
            # every branch but the last "du"-plicates it first rather than
            # consuming the original — confirmed a real bug 2026-08-16 via
            # smoke-testing listToNumber.ink: leaving "du" as a silent no-op
            # (its CONTROL_COMMAND_MARKERS-only treatment before this fix)
            # let the first branch's own "==" comparison consume the shared
            # switch value, leaving nothing for every later branch to test
            # against, corrupting downstream arithmetic built on the result.
            self._duplicate_top_of_eval_stack()
        elif content == VOID_POP:
            # A switch-on-value construct's trailing bare "pop" (outside
            # any "ev".."/ev" bracket, confirmed 2026-08-16 against real
            # compiled output — section7_binstore.ink) discards the
            # DUPLICATE_TOP-ed switch value when no branch matched it.
            # Previously only handled inside _handle_eval_run_command
            # (the void-function-call "pop"), so this main-stream form
            # fell through to CONTROL_COMMAND_MARKERS' silent no-op,
            # leaving a stale value on eval_stack that corrupted the next
            # eval run to use the stack — confirmed a real bug via
            # smoke-testing listToNumber.ink's recursive bit-storage logic.
            self._pop_eval_stack()
        elif self._handle_tag_command(content):
            pass
        elif content in CONTROL_COMMAND_MARKERS:
            # A real ControlCommand marker whose behavior isn't
            # implemented yet (call stack, LISTs, RNG, tags — each lands
            # in its own later section). Must still be recognized and
            # silently consumed here rather than falling through to
            # push_text() below: confirmed as a real bug 2026-08-16 by
            # smoke-testing real-world stories, where bare "nop"/"thread"
            # markers were leaking into visible output as if they were
            # literal text.
            pass
        elif content in (GLUE, NEWLINE):
            self.output.push(content)
        else:
            self.output.push_text(content)
        return False

    def _dispatch_content(self, content: Any, pointer: Pointer, holder: Container) -> bool:
        """Handle one resolved content item, advancing self.pointer as needed.

        Args:
            content: The resolved content at pointer (never None — the
                caller handles that case, since it needs no dispatch at
                all beyond advancing).
            pointer: The current pointer (guaranteed non-None by the
                caller, unlike self.pointer's declared type).
            holder: The container pointer is currently in (== pointer.container).

        Returns:
            True if this content item ends the story (a DONE_COMMANDS
            marker); False otherwise. self.pointer is left at the next
            position to process (which may itself be None, meaning the
            story ran out of content here).
        """
        if content in (POP_TUNNEL, FUNCTION_RETURN):
            # Handled here, not in _handle_string_content: both set
            # self.pointer themselves (a jump, like Divert/ChoicePoint
            # below), so neither must also go through the unconditional
            # auto-advance the plain string branch applies below — that
            # combination was a real Section 5 bug (see POP_TUNNEL's own
            # note), and the same reasoning applies to FUNCTION_RETURN.
            if content == POP_TUNNEL:
                self._pop_tunnel()
            else:
                self._return_from_function()
            return False

        if isinstance(content, str):
            if self._handle_string_content(content):
                return True
            self.pointer = self._advance_pointer(pointer)
            return False

        if isinstance(content, Divert):
            self._follow_divert(content, holder)
            return False

        if isinstance(content, FunctionCall):
            self._call_function(content, holder)
            return False

        if isinstance(content, ChoicePoint):
            self._process_choice_point(content, holder)
        else:
            self._dispatch_literal_content(content, holder)

        self.pointer = self._advance_pointer(pointer)
        return False

    def _dispatch_literal_content(self, content: Any, holder: Container) -> None:
        """Push (or apply) one eval-stack-bound literal/reference token.

        Split out of _dispatch_content purely to keep that method's
        branch count within pylint's threshold as Section 9 added
        ReadCountTarget/DivertTargetValue handling — the individual
        branches below are unchanged from _dispatch_content's own,
        documented at their original level of detail.

        Args:
            content: The resolved content item (never a ChoicePoint,
                Divert, FunctionCall, POP_TUNNEL/FUNCTION_RETURN marker,
                or plain str — all handled by the caller before this is
                reached).
            holder: The container content is directly nested in, needed
                to resolve ReadCountTarget/DivertTargetValue's (possibly
                relative) target paths.
        """
        if isinstance(content, (int, float, bool, ListValue)):
            # A numeric/bool/LIST literal, always pushed as-is regardless
            # of _eval_run_depth: it can only legally appear inside an
            # eval run in the first place (ports the numeric-literal
            # branch of NativeFunctionCall's operand handling — the
            # compiled format never emits a bare number/list outside
            # "ev".."/ev").
            self.eval_stack.append(content)
        elif isinstance(content, VariableReference):
            self.eval_stack.append(self._read_variable(content.name))
        elif isinstance(content, VariableAssignment):
            self._write_variable(content, self._pop_eval_stack())
        elif isinstance(content, ReadCountTarget):
            # A bare `{knot_name}` read-count reference resolves directly
            # to its visit-count int at push time — confirmed 2026-08-16
            # against real compiled output that {"CNT?": path} is the
            # *entire* operation (immediately followed by "out"), not a
            # marker consumed later by a separate "readc" ControlCommand
            # the way TURNS_SINCE/RANDOM's bare-marker operators are.
            # Resolved eagerly using holder for the same reason as
            # DivertTargetValue below — the path can be relative
            # (confirmed: {"CNT?": ".^"}).
            resolved = self._resolve_target(holder, self.root, content.target_path)
            self.eval_stack.append(self._visit_count(resolved) if isinstance(resolved, Container) else 0)
        elif isinstance(content, DivertTargetValue):
            # A `-> knot_name` literal used as an expression: e.g.
            # TURNS_SINCE(-> knot_name)'s argument, or (Section 10,
            # confirmed 2026-08-16 against real compiled output for Ink's
            # empty-bracket choice syntax `* text[]`) the value assigned
            # to a temp variable behind a `{"->": "$r", "var": true}`
            # variable-target divert. Resolved eagerly here (using
            # holder, the container this literal is directly nested in)
            # to a ResolvedDivertTarget wrapping the Container itself —
            # not the raw Path — since real Ink's own DivertTargetValue
            # is opaque data to everything except the two places that
            # consume it (TURNS_SINCE/ReadCount want the container
            # identity directly; a variable-target divert wants a
            # Pointer, itself just Pointer.start_of(container) for the
            # non-index-terminal case every real fixture here exercises).
            # Confirmed a relative target path can appear here
            # (`{"CNT?": ".^"}`), so resolution needs the same
            # holder-container context every other relative-path
            # resolution in this module already requires.
            resolved = self._resolve_target(holder, self.root, content.target_path)
            self.eval_stack.append(ResolvedDivertTarget(container=resolved if isinstance(resolved, Container) else None))
        # else: an opaque/unrecognised leaf token (control commands,
        # values, etc. outside a choice-text run) is skipped — out of
        # scope until its owning section is built.

    def _step(self) -> bool:
        """Process one content item at the current pointer.

        Returns:
            True if the story has reached a stopping point this step
            (a choice point was reached with choices pending after this
            container, the story ended, or the pointer ran out); False to
            keep stepping.
        """
        if self.pointer is None or self.pointer.container is None:
            self.done = True
            return True

        self.pointer = self._descend_into_containers(self.pointer)
        pointer = self.pointer
        assert pointer.container is not None
        if pointer.index >= len(pointer.container.content):
            # Ports the "ran off the end, walk up to the parent" branch of
            # Story._next_content — reached whenever a jump (a variable-
            # target divert, in the one real case found so far, Section
            # 10) lands directly on an *empty* container: a compiler-
            # emitted anonymous return-address marker (`[{"#n": "$r1"}]`,
            # confirmed 2026-08-16 against real compiled output for Ink's
            # empty-bracket choice syntax `* text[]`) that has no content
            # of its own — the real destination is whatever comes right
            # after it positionally in its parent. The initial version of
            # this check unconditionally treated an out-of-range index as
            # "story over," which was only ever correct for the outermost
            # container with no parent left to walk up to — _advance_pointer
            # already handles exactly that distinction (None only when
            # there truly is nowhere left to go, including popping a
            # function call frame if one is active).
            self.pointer = self._advance_pointer(pointer)
            return self.pointer is None

        content = pointer.resolve()

        if content is None:
            # A real "null" JSON leaf (confirmed compiled output, see the
            # Section 1 divergence note on trailing terminator nulls) is a
            # legitimate no-op token, not "story ended" — only an
            # out-of-range index (checked above) means that.
            self.pointer = self._advance_pointer(self.pointer)
            return self.pointer is None

        story_ended = self._dispatch_content(content, pointer, pointer.container)
        return story_ended or self.pointer is None or self.pointer.container is None

    def continue_story(self) -> str:
        """Advance the story until the next stopping point.

        A stopping point is DONE/END being reached (self.done) or the
        pointer running off the end of all content — ChoicePoints
        encountered along the way are recorded in current_choices but do
        not themselves halt continuation, since a container can (and
        typically does) hold several sibling choices in a row. Mirrors
        Story.continue_() in scope but without the newline-lookahead/
        glue-rewind snapshotting the real engine uses — Section 3's
        fixtures don't need it since each turn's leaf run ends cleanly at
        DONE/END.

        Returns:
            The newly produced visible text for this turn (since the last
            continue_story()/choose() call).
        """
        self.current_choices = []
        # current_tags is per-turn, like current_choices above, not
        # cumulative across the whole playthrough — confirmed a real bug
        # 2026-08-16 (found while wiring image tags into a real converted
        # story, claude_docs/plans/asfa_ink_conversions/julie.ink) via
        # inklecate -p's own transcript: a second tagged turn's "# tags:"
        # line shows only that turn's tags, not every tag seen so far.
        # Without this reset, _handle_tag_command's append-only current_tags
        # (this class's own docstring at its declaration) meant every
        # image: tag ever encountered stayed "active" for the rest of the
        # story once callers like interactive_fiction.views._current_image_urls()
        # iterate the accumulated list each turn.
        self.current_tags = []
        start_length = len(self.output.tokens)
        while not self.done:
            if self._step():
                break
        new_tokens = self.output.tokens[start_length:]
        turn_stream = OutputStream()
        for token in new_tokens:
            turn_stream.tokens.append(token)
        self.last_turn_text = turn_stream.get_text()
        return self.last_turn_text

    def choose(self, index: int) -> None:
        """Select one of the currently offered choices and follow its target.

        Args:
            index: The index into current_choices to select.

        Raises:
            IndexError: If index is out of range for current_choices.
        """
        choice = self.current_choices[index]
        self.previous_pointer = self.pointer
        self.pointer = Pointer.start_of(choice.target)
        self.done = False
        self.turn_count += 1
        self._visit_changed_containers_due_to_divert()
        self.current_choices = []

    def _serialize_pointer(self, pointer: Pointer | None) -> dict[str, Any] | None:
        """Convert a Pointer to a plain, JSON-safe dict.

        Args:
            pointer: The pointer to serialize, or None.

        Returns:
            {"path": <container's absolute path string>, "index": int},
            or None if pointer is None or its container is None (a
            pointer that's run off the end of the story — nothing to
            resume from).
        """
        if pointer is None or pointer.container is None:
            return None
        return {"path": _container_path(pointer.container), "index": pointer.index}

    def _deserialize_pointer(self, data: dict[str, Any] | None) -> Pointer | None:
        """Convert a _serialize_pointer() dict back to a live Pointer.

        Args:
            data: The serialized form, or None.

        Returns:
            A Pointer with container resolved against self.root, or None
            if data is None or its path fails to resolve (a story
            re-upload removed the container — degrades to None rather
            than raising; the save-compatibility repair path (Step 4)
            is what's meant to recover from this, not this method).
        """
        if data is None:
            return None
        target = resolve_path(self.root, Path.parse(str(data["path"])))
        if not isinstance(target, Container):
            return None
        return Pointer(container=target, index=int(data["index"]))

    def _serialize_value(self, value: Any) -> Any:
        """Convert one globals/temps/eval_stack entry to a JSON-safe form.

        Args:
            value: A bool/int/float/str/ListValue/ResolvedDivertTarget/Void
                — every type Section 1-10's own dispatch code can leave on
                eval_stack or store in a variable (confirmed by inventory
                of every eval_stack.append()/globals[...]=/temps[...]=
                call site in this module — no other type reaches this).

        Returns:
            The value unchanged for bool/int/float/str (already JSON-safe
            as-is — order matters: bool is checked before int, since
            Python's bool is an int subclass and must round-trip as a
            bool, not silently become 0/1); a tagged dict for
            ListValue/ResolvedDivertTarget/Void, whose entries reference
            Container objects/tuples that need converting to plain data
            (Void has none, but still needs its own tag — found 2026-08-16
            while fixing the implicit-void-return bug: a snapshot taken
            between a void function call returning and its EVAL_OUTPUT/
            VOID_POP consuming that value must not silently degrade Void to
            None, which _deserialize_value would otherwise reconstruct as a
            genuinely different, printable value).
        """
        if isinstance(value, bool):
            return {"$type": "bool", "value": value}
        if isinstance(value, (int, float, str)):
            return value
        if isinstance(value, Void):
            return {"$type": "void"}
        if isinstance(value, ListValue):
            return {
                "$type": "list",
                "entries": [[list(key), val] for key, val in value.entries],
                "origin_names": list(value.origin_names),
            }
        if isinstance(value, ResolvedDivertTarget):
            return {
                "$type": "divert_target",
                "path": _container_path(value.container) if value.container is not None else None,
            }
        # else: an opaque/unexpected value type — degrades to None rather
        # than raising, matching this module's standing philosophy; no
        # known code path produces anything else, but a future
        # out-of-scope construct's value should never break a save.
        return None

    def _deserialize_value(self, data: Any) -> Any:
        """Convert one _serialize_value() result back to a live value.

        Args:
            data: The serialized form.

        Returns:
            The reconstructed value, matching _serialize_value()'s own
            tagging scheme.
        """
        if not isinstance(data, dict) or "$type" not in data:
            return data
        if data["$type"] == "bool":
            return bool(data["value"])
        if data["$type"] == "void":
            return VOID
        if data["$type"] == "list":
            entries = tuple((tuple(key), val) for key, val in data["entries"])
            return ListValue(entries=entries, origin_names=tuple(data["origin_names"]))
        if data["$type"] == "divert_target":
            return self._deserialize_divert_target(data)
        return None

    def _deserialize_divert_target(self, data: dict[str, Any]) -> ResolvedDivertTarget:
        """Convert one {"$type": "divert_target", "path": ...} dict back to
        a ResolvedDivertTarget. Split out of _deserialize_value purely to
        keep that method's return-statement count within pylint's
        threshold, same reasoning as this module's other such splits.

        Args:
            data: The serialized divert-target dict.

        Returns:
            The reconstructed ResolvedDivertTarget, with container=None if
            the path is missing or no longer resolves against self.root
            (matches _deserialize_value()'s own degrade-rather-than-raise
            philosophy for a save taken against a since-edited story).
        """
        path = data["path"]
        if path is None:
            return ResolvedDivertTarget(container=None)
        target = resolve_path(self.root, Path.parse(str(path)))
        return ResolvedDivertTarget(container=target if isinstance(target, Container) else None)

    def _container_by_id_index(self) -> dict[int, Container]:
        """Build an id(Container) -> Container index for the whole tree.

        visit_counts/visit_turns are keyed by id(container) (an
        in-process identity, meaningless across a save/load boundary),
        not by container reference — this walk is what lets
        _id_keyed_dict_to_path_keyed() look up the actual Container for
        each key to compute its path string. Rebuilt fresh each call
        rather than cached, since it's only used by to_dict() (once per
        turn at most, not a hot path worth memoizing against the risk of
        a stale cache if this were ever called before the tree finished
        loading).

        Returns:
            {id(container): container} for every Container reachable
            from self.root, including named-only (terminator-dict-only)
            children.
        """
        index: dict[int, Container] = {}

        def walk(container: Container) -> None:
            index[id(container)] = container
            for item in container.content:
                if isinstance(item, Container):
                    walk(item)
            for item in container.named_content.values():
                if isinstance(item, Container) and id(item) not in index:
                    walk(item)

        walk(self.root)
        return index

    def _id_keyed_dict_to_path_keyed(self, id_keyed: dict[int, int]) -> dict[str, int]:
        """Convert an id(Container)-keyed dict (visit_counts/visit_turns'
        own storage shape) to a path-keyed dict, for serialization.

        Args:
            id_keyed: {id(container): int_value}.

        Returns:
            {path_string: int_value}, one entry per id_keyed key whose
            container is still reachable from self.root (an id whose
            container no longer exists — should not happen within one
            InkRuntimeState's lifetime, since containers are never
            removed from the tree after loading — is silently dropped
            rather than raised, matching this module's degrade-not-crash
            philosophy).
        """
        by_id = self._container_by_id_index()
        result: dict[str, int] = {}
        for container_id, value in id_keyed.items():
            container = by_id.get(container_id)
            if container is not None:
                result[_container_path(container)] = value
        return result

    def _path_keyed_dict_to_id_keyed(self, path_keyed: dict[str, int]) -> dict[int, int]:
        """Convert a path-keyed dict (to_dict()'s serialized form) back to
        the id(Container)-keyed shape visit_counts/visit_turns actually
        use at runtime.

        Args:
            path_keyed: {path_string: int_value}.

        Returns:
            {id(container): int_value}, one entry per path that still
            resolves against self.root (a path a story re-upload removed
            is silently dropped — the save-compatibility repair path,
            Step 4, is what's meant to handle that case holistically, not
            this method).
        """
        result: dict[int, int] = {}
        for path_str, value in path_keyed.items():
            target = resolve_path(self.root, Path.parse(path_str))
            if isinstance(target, Container):
                result[id(target)] = value
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize this state to a plain, JSON-safe dict.

        Every Container/Pointer reference is converted to a path string
        (via _container_path()/resolve_path(), Section 8's shuffle-seed
        helper repurposed here as the general container-addressing
        mechanism), so the result contains only
        dicts/lists/str/int/float/bool/None — safe to round-trip through
        `json.dumps`/`json.loads` or a Django JSONField with no custom
        encoder, matching the plan's "Interpreter state shape" design.

        **Transient mid-dispatch flags are included too, not just the
        "obvious" story-progress fields.** A real bug found while
        building this method: the first version omitted
        _eval_run_depth/_pending_thread/_in_tag/_tag_buffer/
        _string_capture_stack entirely, since they look like internal
        bookkeeping rather than "state." But a stopping point can
        legitimately be captured mid-eval-run (e.g. right after a nested
        function call's own "~ret" pops its frame, while the *outer*
        eval run that called it is still open) — confirmed via a direct
        round-trip test against section6_nested_func.ink's own fixture,
        where a snapshot taken with call_stack non-empty resumed into a
        bare "out" marker that silently produced no output at all,
        because the reconstructed state's _eval_run_depth had reset to 0
        (fresh construction's default) instead of the 1 it actually was
        at snapshot time, routing "out" through the no-op
        CONTROL_COMMAND_MARKERS branch instead of _handle_eval_run_command's
        real EVAL_OUTPUT handling.

        Returns:
            The serialized state.
        """
        return {
            "pointer": self._serialize_pointer(self.pointer),
            "previous_pointer": self._serialize_pointer(self.previous_pointer),
            "output_tokens": list(self.output.tokens),
            "current_choices": [{"text": choice.text, "target_path": _container_path(choice.target)} for choice in self.current_choices],
            "visit_counts": self._id_keyed_dict_to_path_keyed(self.visit_counts),
            "visit_turns": self._id_keyed_dict_to_path_keyed(self.visit_turns),
            "current_tags": list(self.current_tags),
            "done": self.done,
            "globals": {name: self._serialize_value(value) for name, value in self.globals.items()},
            "temps": {name: self._serialize_value(value) for name, value in self.temps.items()},
            "eval_stack": [self._serialize_value(value) for value in self.eval_stack],
            "tunnel_stack": [self._serialize_pointer(pointer) for pointer in self.tunnel_stack],
            "call_stack": [
                {
                    "return_pointer": self._serialize_pointer(frame.return_pointer),
                    "temps": {name: self._serialize_value(value) for name, value in frame.temps.items()},
                }
                for frame in self.call_stack
            ],
            "turn_count": self.turn_count,
            "story_seed": self.story_seed,
            "previous_random": self.previous_random,
            "eval_run_depth": self._eval_run_depth,
            "pending_thread": self._pending_thread,
            "in_tag": self._in_tag,
            "tag_buffer_tokens": list(self._tag_buffer.tokens),
            "string_capture_stack": [list(capture.tokens) for capture in self._string_capture_stack],
            "last_turn_text": self.last_turn_text,
        }

    @classmethod
    def from_dict(cls, root: Container, data: dict[str, Any], list_defs: dict[str, dict[str, int]] | None = None) -> "InkRuntimeState":
        """Rebuild an InkRuntimeState from a to_dict() result.

        Args:
            root: The story's root Container (from load_story_root()) —
                must be the same compiled story data as when the state
                was serialized (Step 4's save-compatibility repair path
                handles a story that has since changed; this method does
                not attempt any of that itself, matching to_dict()'s own
                "path that no longer resolves is silently dropped"
                degradation rather than raising).
            data: A to_dict() result.
            list_defs: The story's LIST definitions, same as the
                InkRuntimeState(root, list_defs) constructor's own
                parameter — passed through so __init__'s normal
                bootstrap (_register_list_item_globals(),
                _run_global_decl()) runs identically to a fresh
                construction, before this method overwrites the fields
                that actually hold save data.

        Returns:
            A new InkRuntimeState with every field from data restored.
        """
        state = cls(root, list_defs)
        state.pointer = state._deserialize_pointer(data.get("pointer"))
        state.previous_pointer = state._deserialize_pointer(data.get("previous_pointer"))
        state.output = OutputStream()
        state.output.tokens = list(data.get("output_tokens", []))
        state.current_choices = []
        for choice_data in data.get("current_choices", []):
            target = resolve_path(state.root, Path.parse(str(choice_data["target_path"])))
            if isinstance(target, Container):
                state.current_choices.append(Choice(text=str(choice_data["text"]), target=target))
        state.visit_counts = state._path_keyed_dict_to_id_keyed(data.get("visit_counts", {}))
        state.visit_turns = state._path_keyed_dict_to_id_keyed(data.get("visit_turns", {}))
        state.current_tags = list(data.get("current_tags", []))
        state.done = bool(data.get("done", False))
        state.globals = {name: state._deserialize_value(value) for name, value in data.get("globals", {}).items()}
        state.temps = {name: state._deserialize_value(value) for name, value in data.get("temps", {}).items()}
        state.eval_stack = [state._deserialize_value(value) for value in data.get("eval_stack", [])]
        state.tunnel_stack = [pointer for pointer in (state._deserialize_pointer(p) for p in data.get("tunnel_stack", [])) if pointer is not None]
        state.call_stack = []
        for frame_data in data.get("call_stack", []):
            return_pointer = state._deserialize_pointer(frame_data.get("return_pointer"))
            if return_pointer is None:
                # A call frame with no valid return address is unusable —
                # dropping it degrades to "this call never returns
                # properly," matching the plan's save-compatibility repair
                # framing (Step 4) that call_stack is exactly the kind of
                # state a story edit can invalidate; not attempting a
                # partial repair here, since that's Step 4's own job.
                continue
            frame_temps = {name: state._deserialize_value(value) for name, value in frame_data.get("temps", {}).items()}
            state.call_stack.append(CallFrame(return_pointer=return_pointer, temps=frame_temps))
        state.turn_count = int(data.get("turn_count", -1))
        state.story_seed = int(data.get("story_seed", state.story_seed))
        state.previous_random = int(data.get("previous_random", 0))
        state._eval_run_depth = int(data.get("eval_run_depth", 0))
        state._pending_thread = bool(data.get("pending_thread", False))
        state._in_tag = bool(data.get("in_tag", False))
        state._tag_buffer = OutputStream()
        state._tag_buffer.tokens = list(data.get("tag_buffer_tokens", []))
        state._string_capture_stack = []
        for tokens in data.get("string_capture_stack", []):
            capture = OutputStream()
            capture.tokens = list(tokens)
            state._string_capture_stack.append(capture)
        state.last_turn_text = str(data.get("last_turn_text", ""))
        return state
