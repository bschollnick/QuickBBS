"""The cost table: what an action costs, and whether it can be afforded.

Built 2026-08-31. The motivating case is the reference game's transform
spell, which source charges 10 mana for a character's first cast and 20
after (`spells-transform.js:56-58`). Before this the conversion had that
number in four unrelated shapes — a hardcoded Ink if-chain, a Python
function, an engine dict, and a literal `>= 20` repeated across ~20 story
files — and the transform case was missing from the if-chain entirely,
which is how a whole spell came to be priced only by literals.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from interactive_fiction.engine_config_schemas import SystemConfigValidationError, validate_cost_table
from interactive_fiction.engine_plugins.costs import (
    CostTableState,
    _bind_cost_table_state,
    can_afford,
    cost_of,
    initial_state,
    resource_of,
    set_cost,
)

CONFIG = {
    "costs": {
        "spell.charm": {"resource": "mana", "amount": 10, "variants": {"cheaper": 9}},
        "spell.transform": {"resource": "mana", "amount": 20, "variants": {"first": 10}},
        "turn.indoor": {"resource": "time", "amount": 1},
    }
}


class CostLookupTests(SimpleTestCase):
    """Reading a cost, with and without a variant."""

    def setUp(self):
        self.state = initial_state(CONFIG)

    def test_a_declared_cost_is_returned(self):
        """The ordinary case."""
        self.assertEqual(cost_of(self.state, "spell.transform"), 20)
        self.assertEqual(resource_of(self.state, "spell.transform"), "mana")

    def test_a_variant_overrides_the_base_amount(self):
        """A conditional price stays data: the caller names the variant
        when its condition holds, and the table holds only the number."""
        self.assertEqual(cost_of(self.state, "spell.transform", "first"), 10)
        self.assertEqual(cost_of(self.state, "spell.charm", "cheaper"), 9)

    def test_an_undeclared_variant_falls_back_to_the_base(self):
        """So a caller may always pass its variant without first checking
        whether this particular cost declares one."""
        self.assertEqual(cost_of(self.state, "turn.indoor", "first"), 1)

    def test_an_undeclared_key_costs_the_caller_s_default(self):
        """Asking about an unpriced action is a real question, not an
        error — a story may price an action only once it exists."""
        self.assertEqual(cost_of(self.state, "spell.nothing", default=-1), -1)
        self.assertEqual(cost_of(self.state, "spell.nothing"), 0)


class AffordabilityTests(SimpleTestCase):
    """The comparison, asked the same way by every caller."""

    def setUp(self):
        self.state = initial_state(CONFIG)

    def test_affordability_follows_the_variant(self):
        """The case this table was built for: 15 mana cannot pay for an
        ordinary transform but can pay for a character's first."""
        self.assertFalse(can_afford(self.state, "spell.transform", 15))
        self.assertTrue(can_afford(self.state, "spell.transform", 15, "first"))

    def test_exactly_enough_is_enough(self):
        """The boundary, pinned so it cannot drift to a strict >."""
        self.assertTrue(can_afford(self.state, "spell.transform", 20))

    def test_an_unpriced_action_is_always_affordable(self):
        """It costs nothing, so nothing can fail to cover it."""
        self.assertTrue(can_afford(self.state, "spell.nothing", 0))


class CostMutationTests(SimpleTestCase):
    """Prices that change during play."""

    def test_set_cost_returns_a_new_state(self):
        """Never mutates in place, like every other state function here."""
        state = initial_state(CONFIG)
        updated = set_cost(state, "spell.transform", "mana", 30)
        self.assertEqual(cost_of(updated, "spell.transform"), 30)
        self.assertEqual(cost_of(state, "spell.transform"), 20)

    def test_changing_the_base_keeps_the_variants(self):
        """A price rise should not silently discard the discount that
        already applied to it."""
        updated = set_cost(initial_state(CONFIG), "spell.transform", "mana", 30)
        self.assertEqual(cost_of(updated, "spell.transform", "first"), 10)

    def test_a_cost_may_be_declared_that_did_not_exist(self):
        """A story may price an action only once it becomes available."""
        updated = set_cost(CostTableState(), "spell.wealth", "mana", 1)
        self.assertEqual(cost_of(updated, "spell.wealth"), 1)

    def test_costs_survive_a_serialization_round_trip(self):
        """They live in session state, so they must round-trip."""
        state = CostTableState.from_dict(initial_state(CONFIG).to_dict())
        self.assertEqual(cost_of(state, "spell.transform", "first"), 10)
        self.assertEqual(resource_of(state, "spell.charm"), "mana")


class BindingTests(SimpleTestCase):
    """The bindings read and write the session's own dict directly."""

    def test_the_bindings_answer_from_the_state_dict(self):
        """No rebuild per call — the dict IS the session's live state."""
        state_dict = initial_state(CONFIG).to_dict()
        bindings = _bind_cost_table_state(state_dict)
        self.assertEqual(bindings["cost_of_now"]("spell.transform", "first"), 10)
        self.assertTrue(bindings["can_afford_now"]("spell.transform", 15, "first"))
        self.assertFalse(bindings["can_afford_now"]("spell.transform", 15))

    def test_a_write_lands_in_the_session_state(self):
        """So it is already persisted when the turn ends, with no
        write-back step for a caller to forget."""
        state_dict = initial_state(CONFIG).to_dict()
        bindings = _bind_cost_table_state(state_dict)
        bindings["set_cost_now"]("spell.wealth", "mana", 1)
        self.assertEqual(state_dict["costs"]["spell.wealth"], {"resource": "mana", "amount": 1})


class CostTableConfigValidationTests(SimpleTestCase):
    """The config is a closed schema, like every other system's."""

    def test_a_real_config_is_accepted(self):
        """Including an empty table: a story may opt in and price nothing yet."""
        validate_cost_table(CONFIG)
        validate_cost_table({})

    def test_a_cost_needs_a_resource_and_an_amount(self):
        """Without them a cost cannot be paid or compared."""
        for bad in ({"resource": "mana"}, {"amount": 10}):
            with self.subTest(cost=bad), self.assertRaises(SystemConfigValidationError):
                validate_cost_table({"costs": {"x": bad}})

    def test_an_amount_must_be_a_number(self):
        """`True` is rejected explicitly: it is an int subclass in Python,
        and a boolean where a price belongs is a mistake."""
        for bad in (True, "ten", None):
            with self.subTest(amount=bad), self.assertRaises(SystemConfigValidationError):
                validate_cost_table({"costs": {"x": {"resource": "mana", "amount": bad}}})

    def test_variants_must_be_names_mapped_to_numbers(self):
        """The variant is a name the caller passes; its value is a price."""
        with self.assertRaises(SystemConfigValidationError):
            validate_cost_table({"costs": {"x": {"resource": "mana", "amount": 1, "variants": {"a": "cheap"}}}})
        with self.assertRaises(SystemConfigValidationError):
            validate_cost_table({"costs": {"x": {"resource": "mana", "amount": 1, "variants": [1, 2]}}})
