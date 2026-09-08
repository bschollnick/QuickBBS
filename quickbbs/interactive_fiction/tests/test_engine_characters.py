"""`engine_plugins.characters` — per-character keyed storage, known-state,
and the delegating accessors (`asfa_engine_revamp.md` Step 9a).

The property worth guarding hardest is what this module does NOT store: a
character's location lives in the occupancy plugin, and
`current_location_of()` must read through to it rather than keeping a
copy. A regression there would reintroduce exactly the two-records-of-one-
fact bug the whole plan exists to remove, and would not otherwise show up
as a failure.

Generic fixtures only — no story names.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from interactive_fiction.engine_plugins.characters import (
    API,
    CharacterState,
    character_is_known,
    clear_all_attributes,
    current_location_of,
    does_attribute_exist,
    known_characters,
    read_attribute,
    set_attribute,
    set_known,
    set_unknown,
)


class AttributeTests(SimpleTestCase):
    """The storage this module actually owns."""

    def test_a_stored_attribute_reads_back(self):
        """The base case."""
        state = set_attribute(CharacterState(), "alice", "flag12", True)
        self.assertTrue(read_attribute(state, "alice", "flag12"))

    def test_attributes_are_per_character(self):
        """The point of keying by character: the same attribute name on two
        characters is two independent facts, which is what a flattened
        global-per-fact scheme cannot express without name mangling."""
        state = set_attribute(CharacterState(), "alice", "flag1", True)
        state = set_attribute(state, "bob", "flag1", False)
        self.assertTrue(read_attribute(state, "alice", "flag1"))
        self.assertFalse(read_attribute(state, "bob", "flag1"))

    def test_an_unset_attribute_reads_as_false_by_default(self):
        """Story content asks about facts that have not happened far more
        often than ones that have, so absence must not raise."""
        self.assertFalse(read_attribute(CharacterState(), "alice", "never_set"))

    def test_an_explicit_default_is_honoured(self):
        """A counter starting at 0, a name starting empty."""
        self.assertEqual(read_attribute(CharacterState(), "alice", "stage", 0), 0)
        self.assertEqual(read_attribute(CharacterState(), "alice", "title", ""), "")

    def test_existence_is_distinct_from_truthiness(self):
        """A flag explicitly set False is not the same as one never set —
        a story that must tell those apart has no other way to."""
        state = set_attribute(CharacterState(), "alice", "agreed", False)
        self.assertFalse(read_attribute(state, "alice", "agreed"))
        self.assertTrue(does_attribute_exist(state, "alice", "agreed"))
        self.assertFalse(does_attribute_exist(state, "alice", "never_set"))

    def test_values_may_be_any_json_safe_scalar(self):
        """Numbered flags are booleans, but stages are numbers and some
        facts are text; all must survive."""
        state = set_attribute(CharacterState(), "alice", "flag", True)
        state = set_attribute(state, "alice", "stage", 3)
        state = set_attribute(state, "alice", "fraction", 2.2)
        state = set_attribute(state, "alice", "note", "hello")
        self.assertEqual(read_attribute(state, "alice", "stage"), 3)
        self.assertEqual(read_attribute(state, "alice", "fraction"), 2.2)
        self.assertEqual(read_attribute(state, "alice", "note"), "hello")

    def test_setting_never_mutates_the_caller_s_state(self):
        """Same pure in/out contract as every other plugin."""
        original = CharacterState()
        set_attribute(original, "alice", "flag", True)
        self.assertEqual(original.records, {})

    def test_state_is_keyed_by_character_first(self):
        """The storage shape is load-bearing, not incidental: a path into
        it must read as the sentence the caller is saying —
        `(character, "attributes", name)` — rather than backwards through
        an attribute-major map. Schedule conditions address it by that
        path, so flipping the nesting would silently break them."""
        state = set_attribute(CharacterState(), "alice", "flag12", True)
        self.assertEqual(state.to_dict()["records"], {"alice": {"attributes": {"flag12": True}}})

    def test_clearing_removes_only_that_character(self):
        """One character's reset must not disturb another's."""
        state = set_attribute(CharacterState(), "alice", "flag", True)
        state = set_attribute(state, "bob", "flag", True)
        cleared = clear_all_attributes(state, "alice")
        self.assertFalse(read_attribute(cleared, "alice", "flag"))
        self.assertTrue(read_attribute(cleared, "bob", "flag"))

    def test_clearing_attributes_keeps_known_state(self):
        """Forgetting the details about someone is not the same as never
        having met them."""
        state = set_known(set_attribute(CharacterState(), "alice", "flag", True), "alice")
        cleared = clear_all_attributes(state, "alice")
        self.assertTrue(character_is_known(cleared, "alice"))


class KnownStateTests(SimpleTestCase):
    """ "Have I met this person" — the one uniform question worth its own
    vocabulary, mirroring `location_graph`'s own known-set."""

    def test_a_character_starts_unknown_and_becomes_known(self):
        """The base transition."""
        state = CharacterState()
        self.assertFalse(character_is_known(state, "alice"))
        self.assertTrue(character_is_known(set_known(state, "alice"), "alice"))

    def test_known_state_can_be_taken_back(self):
        """An erased memory, a mistaken identity — the same reason
        `location_graph.mark_unknown()` exists."""
        state = set_known(CharacterState(), "alice")
        self.assertFalse(character_is_known(set_unknown(state, "alice"), "alice"))

    def test_marking_known_twice_is_harmless(self):
        """Story content re-runs; a second introduction must not error."""
        state = set_known(set_known(CharacterState(), "alice"), "alice")
        self.assertEqual(known_characters(state), ["alice"])

    def test_forgetting_someone_never_met_is_harmless(self):
        """Same reasoning in reverse."""
        self.assertEqual(known_characters(set_unknown(CharacterState(), "alice")), [])

    def test_known_state_does_not_disturb_attributes(self):
        """The two halves of this module are independent."""
        state = set_attribute(CharacterState(), "alice", "flag", True)
        self.assertTrue(read_attribute(set_known(state, "alice"), "alice", "flag"))


class DelegationTests(SimpleTestCase):
    """What this module deliberately does NOT own."""

    def test_location_is_read_from_the_occupancy_store(self):
        """The load-bearing property: a character's location is answered
        from the plugin that owns it, so there is exactly one record of
        it. If this ever starts reading a local field, the duplication
        this plan removed has come back."""
        occupancy = {"locations": {"alice": "the_square"}}
        self.assertEqual(current_location_of(occupancy, "alice"), "the_square")

    def test_an_unplaced_character_reads_as_empty(self):
        """Matches the empty-string convention story bindings use, since
        Ink has no None."""
        self.assertEqual(current_location_of({"locations": {}}, "alice"), "")
        self.assertEqual(current_location_of({}, "alice"), "")

    def test_this_module_stores_no_location_of_its_own(self):
        """Stated as a test so it cannot be quietly changed: the state
        this module serializes has no location in it at all."""
        state = set_known(set_attribute(CharacterState(), "alice", "flag", True), "alice")
        self.assertEqual(sorted(state.to_dict()), ["known", "records"])


class SerializationTests(SimpleTestCase):
    """State must survive a session save/load like every other plugin's."""

    def test_round_trips_through_real_json(self):
        """A real dumps/loads round-trip, not just to_dict/from_dict."""
        state = set_attribute(CharacterState(), "alice", "flag12", True)
        state = set_attribute(state, "bob", "stage", 3)
        state = set_known(state, "alice")
        restored = CharacterState.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertTrue(read_attribute(restored, "alice", "flag12"))
        self.assertEqual(read_attribute(restored, "bob", "stage"), 3)
        self.assertEqual(known_characters(restored), ["alice"])

    def test_the_serialized_form_is_stable(self):
        """`known` is a set; serializing it unordered would produce a
        different payload on every save for identical state, which makes
        saves diff noisily and hides real changes."""
        first = set_known(set_known(CharacterState(), "bob"), "alice")
        second = set_known(set_known(CharacterState(), "alice"), "bob")
        self.assertEqual(first.to_dict(), second.to_dict())


class BindingTests(SimpleTestCase):
    """The EXTERNAL surface a story actually calls."""

    def setUp(self):
        self.state = API.init_state()
        self.occupancy = {"locations": {"alice": "the_square"}}
        self.bindings = API.bind_stateful(self.state, {"character_occupancy": self.occupancy})

    def test_writes_persist_into_the_session_state_dict(self):
        """A binding that did not write through would lose everything at
        the end of the request."""
        self.bindings["set_attribute_now"]("alice", "flag12", True)
        self.assertTrue(CharacterState.from_dict(self.state).attributes["alice"]["flag12"])

    def test_the_full_attribute_surface_round_trips(self):
        """set/read/exists/clear through the bindings, as Ink uses them."""
        self.bindings["set_attribute_now"]("alice", "flag12", True)
        self.assertTrue(self.bindings["read_attribute_now"]("alice", "flag12"))
        self.assertTrue(self.bindings["does_attribute_exist_now"]("alice", "flag12"))
        self.bindings["clear_all_attributes_now"]("alice")
        self.assertFalse(self.bindings["does_attribute_exist_now"]("alice", "flag12"))

    def test_known_state_round_trips_through_the_bindings(self):
        """The 37-flag migration's target surface. Named and shaped to
        mirror location_graph's location_known_now/set_location_known_now
        pair exactly: a getter plus one boolean-taking setter."""
        self.assertFalse(self.bindings["character_known_now"]("alice"))
        self.bindings["set_character_known_now"]("alice", True)
        self.assertTrue(self.bindings["character_known_now"]("alice"))
        self.bindings["set_character_known_now"]("alice", False)
        self.assertFalse(self.bindings["character_known_now"]("alice"))

    def test_the_location_binding_tracks_the_occupancy_slot_live(self):
        """Not a snapshot taken at bind time: moving a character in the
        occupancy store must change what this answers, or the delegation
        is only cosmetic."""
        self.assertEqual(self.bindings["current_location_now"]("alice"), "the_square")
        self.occupancy["locations"]["alice"] = "the_shop"
        self.assertEqual(self.bindings["current_location_now"]("alice"), "the_shop")

    def test_the_descriptor_declares_the_slot_it_reads(self):
        """`also_reads` is what makes the delegation possible; losing it
        would silently turn `current_location_now` into a dead answer."""
        self.assertEqual(API.state_key, "characters")
        self.assertIn("character_occupancy", API.also_reads)
