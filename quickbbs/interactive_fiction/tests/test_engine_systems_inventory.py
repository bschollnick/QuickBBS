"""Tests for the generic `engine_plugins/inventory.py` framework.

Every id here is a fixture invention ("item_a", "holder_1", "room_x") —
no real story's items, characters or locations appear, so this suite
cannot pass or fail for reasons belonging to any particular game.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from interactive_fiction.engine_plugins.containers import (
    declare_container,
    is_container,
    is_container_open,
    put_in_container,
    set_container_open,
    take_from_container,
    visible_contents,
)
from interactive_fiction.engine_plugins.inventory import (
    DEFAULT_STACK_LIMIT,
    DEFAULT_WORN_SLOT_CAPACITY,
    MAX_STACK_LIMIT,
    MAX_WORN_SLOT_CAPACITY,
    UNLIMITED,
    ContainerClosedError,
    InvalidLimitError,
    InventoryFullError,
    InventoryState,
    ItemNotHeldError,
    SlotOccupiedError,
    StackFullError,
    capacity,
    give_item,
    has_item,
    held_items,
    is_worn,
    item_count,
    item_holder,
    item_location,
    items_at_location,
    place_item,
    remove_from_world,
    remove_worn_item,
    set_capacity,
    set_stack_limit,
    set_worn_slot_capacity,
    stack_limit,
    take_item,
    transfer_item,
    wear_item,
    worn_in_slot,
    worn_items,
    worn_slot_capacity,
)
from interactive_fiction.engine_plugins.item_text import describe


class WorldPlacementTests(SimpleTestCase):
    """Items lying in the world, and the world/holder exclusivity rule."""

    def test_a_placed_item_reports_its_location(self):
        state = place_item(InventoryState(), "item_a", "room_x")
        self.assertEqual(item_location(state, "item_a"), "room_x")

    def test_an_unplaced_item_has_no_location(self):
        self.assertIsNone(item_location(InventoryState(), "item_a"))

    def test_items_at_location_returns_only_that_locations_items(self):
        state = place_item(InventoryState(), "item_a", "room_x")
        state = place_item(state, "item_b", "room_x")
        state = place_item(state, "item_c", "room_y")
        self.assertEqual(items_at_location(state, "room_x"), frozenset({"item_a", "item_b"}))
        self.assertEqual(items_at_location(state, "room_y"), frozenset({"item_c"}))

    def test_placing_a_held_item_takes_it_from_its_holder(self):
        """Being held and lying on the ground are mutually exclusive."""
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = place_item(state, "item_a", "room_x")
        self.assertFalse(has_item(state, "holder_1", "item_a"))
        self.assertEqual(item_location(state, "item_a"), "room_x")

    def test_giving_a_placed_item_takes_it_out_of_the_world(self):
        state = place_item(InventoryState(), "item_a", "room_x")
        state = give_item(state, "holder_1", "item_a")
        self.assertIsNone(item_location(state, "item_a"))
        self.assertEqual(items_at_location(state, "room_x"), frozenset())

    def test_remove_from_world_clears_both_location_and_holder(self):
        state = place_item(InventoryState(), "item_a", "room_x")
        state = give_item(state, "holder_1", "item_b")
        state = remove_from_world(state, "item_a")
        state = remove_from_world(state, "item_b")
        self.assertIsNone(item_location(state, "item_a"))
        self.assertFalse(has_item(state, "holder_1", "item_b"))

    def test_removing_an_absent_item_is_not_an_error(self):
        """So a story can call it unconditionally without guarding."""
        state = remove_from_world(InventoryState(), "item_never_existed")
        self.assertIsNone(item_location(state, "item_never_existed"))


class PresenceAndQuantityTests(SimpleTestCase):
    """Both shapes the store must support: boolean presence and counts."""

    def test_has_item_is_false_before_and_true_after_giving(self):
        state = InventoryState()
        self.assertFalse(has_item(state, "holder_1", "item_a"))
        state = give_item(state, "holder_1", "item_a")
        self.assertTrue(has_item(state, "holder_1", "item_a"))

    def test_a_boolean_item_is_simply_a_count_of_one(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        self.assertEqual(item_count(state, "holder_1", "item_a"), 1)

    def test_counts_accumulate_and_decrement(self):
        state = give_item(InventoryState(), "holder_1", "item_a", count=3)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 3)
        state = take_item(state, "holder_1", "item_a")
        self.assertEqual(item_count(state, "holder_1", "item_a"), 2)

    def test_an_exhausted_item_is_dropped_not_left_at_zero(self):
        """has_item() and held_items() must never disagree."""
        state = give_item(InventoryState(), "holder_1", "item_a", count=2)
        state = take_item(state, "holder_1", "item_a", count=2)
        self.assertFalse(has_item(state, "holder_1", "item_a"))
        self.assertNotIn("item_a", held_items(state, "holder_1"))

    def test_taking_more_than_held_raises_and_leaves_state_untouched(self):
        state = give_item(InventoryState(), "holder_1", "item_a", count=2)
        with self.assertRaises(ItemNotHeldError):
            take_item(state, "holder_1", "item_a", count=3)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 2)

    def test_taking_an_unheld_item_raises(self):
        with self.assertRaises(ItemNotHeldError):
            take_item(InventoryState(), "holder_1", "item_a")

    def test_a_count_below_one_is_rejected(self):
        state = InventoryState()
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                give_item(state, "holder_1", "item_a", count=bad)


class HolderTests(SimpleTestCase):
    """A holder is any opaque id — character, NPC, or container alike."""

    def test_two_holders_carry_independently(self):
        state = give_item(InventoryState(), "holder_1", "item_a", count=3)
        state = give_item(state, "holder_2", "item_a", count=1)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 3)
        self.assertEqual(item_count(state, "holder_2", "item_a"), 1)

    def test_a_container_holds_items_exactly_like_a_character(self):
        """There is no separate container concept — same primitive."""
        state = give_item(InventoryState(), "container_1", "item_a")
        self.assertTrue(has_item(state, "container_1", "item_a"))
        self.assertEqual(item_holder(state, "item_a"), "container_1")

    def test_held_items_returns_a_copy(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        snapshot = held_items(state, "holder_1")
        snapshot["item_b"] = 99
        self.assertFalse(has_item(state, "holder_1", "item_b"))

    def test_item_holder_is_none_for_an_unheld_item(self):
        state = place_item(InventoryState(), "item_a", "room_x")
        self.assertIsNone(item_holder(state, "item_a"))


class CapacityTests(SimpleTestCase):
    """Capacity limits DISTINCT items, and refuses rather than dropping."""

    def test_a_holder_is_unlimited_by_default(self):
        self.assertIsNone(capacity(InventoryState(), "holder_1"))

    def test_giving_past_capacity_raises(self):
        state = set_capacity(InventoryState(), "holder_1", 2)
        state = give_item(state, "holder_1", "item_a")
        state = give_item(state, "holder_1", "item_b")
        with self.assertRaises(InventoryFullError):
            give_item(state, "holder_1", "item_c")

    def test_more_of_an_already_held_item_never_trips_capacity(self):
        """Capacity counts distinct entries, not total quantity."""
        state = set_capacity(InventoryState(), "holder_1", 1)
        state = give_item(state, "holder_1", "item_a")
        state = give_item(state, "holder_1", "item_a", count=10)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 11)

    def test_a_refused_item_stays_where_it_was(self):
        """The caller can catch the error and drop it on the floor
        instead — the failure must not consume the item."""
        state = set_capacity(InventoryState(), "holder_1", 1)
        state = give_item(state, "holder_1", "item_a")
        state = place_item(state, "item_b", "room_x")
        with self.assertRaises(InventoryFullError):
            give_item(state, "holder_1", "item_b")
        self.assertEqual(item_location(state, "item_b"), "room_x")

    def test_lowering_capacity_below_current_load_drops_nothing(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = give_item(state, "holder_1", "item_b")
        state = set_capacity(state, "holder_1", 1)
        self.assertTrue(has_item(state, "holder_1", "item_a"))
        self.assertTrue(has_item(state, "holder_1", "item_b"))
        with self.assertRaises(InventoryFullError):
            give_item(state, "holder_1", "item_c")


class TransferTests(SimpleTestCase):
    """Give-to and take-from a person are one primitive, both directions."""

    def test_transfer_moves_the_item(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = transfer_item(state, "holder_1", "holder_2", "item_a")
        self.assertFalse(has_item(state, "holder_1", "item_a"))
        self.assertTrue(has_item(state, "holder_2", "item_a"))

    def test_transfer_round_trips(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = transfer_item(state, "holder_1", "holder_2", "item_a")
        state = transfer_item(state, "holder_2", "holder_1", "item_a")
        self.assertTrue(has_item(state, "holder_1", "item_a"))
        self.assertFalse(has_item(state, "holder_2", "item_a"))

    def test_transfer_moves_only_the_count_asked_for(self):
        state = give_item(InventoryState(), "holder_1", "item_a", count=5)
        state = transfer_item(state, "holder_1", "holder_2", "item_a", count=2)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 3)
        self.assertEqual(item_count(state, "holder_2", "item_a"), 2)

    def test_transfer_from_a_holder_without_it_raises(self):
        with self.assertRaises(ItemNotHeldError):
            transfer_item(InventoryState(), "holder_1", "holder_2", "item_a")

    def test_a_full_receiver_raises_without_the_giver_losing_it(self):
        """The capacity check must happen BEFORE anything is removed, or
        a refused hand-over would destroy the item."""
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = set_capacity(state, "holder_2", 1)
        state = give_item(state, "holder_2", "item_b")
        with self.assertRaises(InventoryFullError):
            transfer_item(state, "holder_1", "holder_2", "item_a")
        self.assertTrue(has_item(state, "holder_1", "item_a"))


class ImmutabilityTests(SimpleTestCase):
    """Every function returns new state and never mutates its argument."""

    def test_give_does_not_mutate_the_original(self):
        original = InventoryState()
        give_item(original, "holder_1", "item_a")
        self.assertFalse(has_item(original, "holder_1", "item_a"))

    def test_place_does_not_mutate_the_original(self):
        original = InventoryState()
        place_item(original, "item_a", "room_x")
        self.assertIsNone(item_location(original, "item_a"))

    def test_transfer_does_not_mutate_the_original(self):
        original = give_item(InventoryState(), "holder_1", "item_a")
        transfer_item(original, "holder_1", "holder_2", "item_a")
        self.assertTrue(has_item(original, "holder_1", "item_a"))
        self.assertFalse(has_item(original, "holder_2", "item_a"))

    def test_nested_dicts_are_copied_not_shared(self):
        original = give_item(InventoryState(), "holder_1", "item_a")
        updated = give_item(original, "holder_1", "item_b")
        self.assertFalse(has_item(original, "holder_1", "item_b"))
        self.assertTrue(has_item(updated, "holder_1", "item_b"))


class SerializationTests(SimpleTestCase):
    """State must round-trip through a session's own serialized state."""

    def test_round_trip_preserves_everything(self):
        state = place_item(InventoryState(), "item_a", "room_x")
        state = give_item(state, "holder_1", "item_b", count=3)
        state = set_capacity(state, "holder_1", 4)

        rebuilt = InventoryState.from_dict(state.to_dict())

        self.assertEqual(item_location(rebuilt, "item_a"), "room_x")
        self.assertEqual(item_count(rebuilt, "holder_1", "item_b"), 3)
        self.assertEqual(capacity(rebuilt, "holder_1"), 4)

    def test_to_dict_is_json_safe(self):
        import json

        state = give_item(InventoryState(), "holder_1", "item_a", count=2)
        state = place_item(state, "item_b", "room_x")
        self.assertEqual(InventoryState.from_dict(json.loads(json.dumps(state.to_dict()))).to_dict(), state.to_dict())

    def test_from_dict_tolerates_missing_keys(self):
        """An older saved state that predates a field still loads."""
        rebuilt = InventoryState.from_dict({})
        self.assertEqual(rebuilt.to_dict(), InventoryState().to_dict())

    def test_to_dict_returns_copies_not_live_references(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        serialized = state.to_dict()
        serialized["holder_items"]["holder_1"]["item_b"] = 5
        self.assertFalse(has_item(state, "holder_1", "item_b"))


class StackLimitTests(SimpleTestCase):
    """How many units of ONE item fit in a holder's slot.

    Independent of the distinct-item capacity: a holder can hit a stack
    limit with slots still free, and hit a slot limit with stacks empty.
    """

    def test_a_holder_uses_the_default_limit_when_none_is_set(self):
        self.assertEqual(stack_limit(InventoryState(), "holder_1"), DEFAULT_STACK_LIMIT)

    def test_stacking_up_to_the_limit_is_allowed(self):
        state = set_stack_limit(InventoryState(), "holder_1", 5)
        for _ in range(5):
            state = give_item(state, "holder_1", "item_a")
        self.assertEqual(item_count(state, "holder_1", "item_a"), 5)

    def test_one_past_the_limit_is_refused(self):
        state = set_stack_limit(InventoryState(), "holder_1", 5)
        state = give_item(state, "holder_1", "item_a", count=5)
        with self.assertRaises(StackFullError):
            give_item(state, "holder_1", "item_a")

    def test_a_refused_stack_is_not_topped_up_to_the_limit(self):
        """The whole addition is refused, so the caller can leave the
        surplus where it was rather than silently losing part of it."""
        state = set_stack_limit(InventoryState(), "holder_1", 5)
        state = give_item(state, "holder_1", "item_a", count=3)
        with self.assertRaises(StackFullError):
            give_item(state, "holder_1", "item_a", count=4)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 3)

    def test_a_full_stack_does_not_block_a_different_item(self):
        state = set_stack_limit(InventoryState(), "holder_1", 2)
        state = give_item(state, "holder_1", "item_a", count=2)
        state = give_item(state, "holder_1", "item_b")
        self.assertTrue(has_item(state, "holder_1", "item_b"))

    def test_a_full_stack_can_happen_with_slots_still_free(self):
        """Stack and slot limits are independent refusals."""
        state = set_capacity(InventoryState(), "holder_1", 10)
        state = set_stack_limit(state, "holder_1", 1)
        state = give_item(state, "holder_1", "item_a")
        with self.assertRaises(StackFullError):
            give_item(state, "holder_1", "item_a")
        self.assertEqual(capacity(state, "holder_1"), 10)

    def test_limit_of_one_allows_exactly_one(self):
        state = set_stack_limit(InventoryState(), "holder_1", 1)
        state = give_item(state, "holder_1", "item_a")
        with self.assertRaises(StackFullError):
            give_item(state, "holder_1", "item_a")

    def test_unlimited_really_is_unlimited(self):
        state = set_stack_limit(InventoryState(), "holder_1", UNLIMITED)
        state = give_item(state, "holder_1", "item_a", count=MAX_STACK_LIMIT * 5)
        self.assertEqual(item_count(state, "holder_1", "item_a"), MAX_STACK_LIMIT * 5)

    def test_a_limit_above_the_maximum_is_rejected_not_clamped(self):
        """A typo like 2000 must surface as an error, not quietly become
        MAX_STACK_LIMIT."""
        with self.assertRaises(InvalidLimitError):
            set_stack_limit(InventoryState(), "holder_1", MAX_STACK_LIMIT + 1)

    def test_a_negative_limit_is_rejected(self):
        with self.assertRaises(InvalidLimitError):
            set_stack_limit(InventoryState(), "holder_1", -1)

    def test_the_maximum_itself_is_allowed(self):
        state = set_stack_limit(InventoryState(), "holder_1", MAX_STACK_LIMIT)
        self.assertEqual(stack_limit(state, "holder_1"), MAX_STACK_LIMIT)

    def test_lowering_a_limit_below_the_current_stack_drops_nothing(self):
        state = set_stack_limit(InventoryState(), "holder_1", 10)
        state = give_item(state, "holder_1", "item_a", count=8)
        state = set_stack_limit(state, "holder_1", 3)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 8)
        with self.assertRaises(StackFullError):
            give_item(state, "holder_1", "item_a")

    def test_transfer_respects_the_receivers_stack_limit(self):
        state = give_item(InventoryState(), "holder_1", "item_a", count=3)
        state = set_stack_limit(state, "holder_2", 2)
        with self.assertRaises(StackFullError):
            transfer_item(state, "holder_1", "holder_2", "item_a", count=3)
        self.assertEqual(item_count(state, "holder_1", "item_a"), 3)

    def test_stack_limits_survive_serialization(self):
        state = set_stack_limit(InventoryState(), "holder_1", 7)
        self.assertEqual(stack_limit(InventoryState.from_dict(state.to_dict()), "holder_1"), 7)

    def test_two_holders_have_independent_stack_limits(self):
        state = set_stack_limit(InventoryState(), "holder_1", 1)
        state = set_stack_limit(state, "holder_2", 9)
        self.assertEqual(stack_limit(state, "holder_1"), 1)
        self.assertEqual(stack_limit(state, "holder_2"), 9)


class ContainerTests(SimpleTestCase):
    """Containers as a marked kind, not an inferred one."""

    def test_an_undeclared_holder_is_not_a_container(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        self.assertFalse(is_container(state, "holder_1"))

    def test_an_undeclared_holder_is_always_reachable(self):
        """Every holder that predates containers must behave unchanged."""
        self.assertTrue(is_container_open(InventoryState(), "holder_1"))

    def test_a_declared_container_defaults_to_permanently_open(self):
        """Inform's own default: not openable means always open, so an
        ordinary container costs nothing to declare."""
        state = declare_container(InventoryState(), "holder_1")
        self.assertTrue(is_container(state, "holder_1"))
        self.assertTrue(is_container_open(state, "holder_1"))

    def test_a_shut_container_cannot_be_reached_into(self):
        state = declare_container(InventoryState(), "holder_1", openable=True, is_open=False)
        self.assertFalse(is_container_open(state, "holder_1"))

    def test_contents_of_a_shut_opaque_container_are_invisible(self):
        state = give_item(InventoryState(), "holder_2", "item_a")
        state = declare_container(state, "holder_1", openable=True, is_open=False)
        state = transfer_item(state, "holder_2", "holder_1", "item_a")
        self.assertEqual(visible_contents(state, "holder_1"), {})

    def test_contents_of_a_shut_transparent_container_are_visible(self):
        state = give_item(InventoryState(), "holder_2", "item_a")
        state = declare_container(state, "holder_1", openable=True, is_open=False, transparent=True)
        state = transfer_item(state, "holder_2", "holder_1", "item_a")
        self.assertEqual(visible_contents(state, "holder_1"), {"item_a": 1})

    def test_seeing_into_a_transparent_container_is_not_reaching_into_it(self):
        state = give_item(InventoryState(), "holder_2", "item_a")
        state = declare_container(state, "holder_1", openable=True, is_open=False, transparent=True)
        state = transfer_item(state, "holder_2", "holder_1", "item_a")
        with self.assertRaises(ContainerClosedError):
            take_from_container(state, "holder_1", "holder_2", "item_a")

    def test_putting_into_a_shut_container_is_refused(self):
        state = give_item(InventoryState(), "holder_2", "item_a")
        state = declare_container(state, "holder_1", openable=True, is_open=False)
        with self.assertRaises(ContainerClosedError):
            put_in_container(state, "holder_2", "holder_1", "item_a")

    def test_opening_a_container_lets_its_contents_out(self):
        state = give_item(InventoryState(), "holder_2", "item_a")
        state = declare_container(state, "holder_1", openable=True, is_open=False)
        state = transfer_item(state, "holder_2", "holder_1", "item_a")
        state = set_container_open(state, "holder_1", True)
        state = take_from_container(state, "holder_1", "holder_2", "item_a")
        self.assertTrue(has_item(state, "holder_2", "item_a"))

    def test_a_round_trip_through_a_container_preserves_the_item(self):
        state = give_item(InventoryState(), "holder_2", "item_a")
        state = declare_container(state, "holder_1")
        state = put_in_container(state, "holder_2", "holder_1", "item_a")
        self.assertFalse(has_item(state, "holder_2", "item_a"))
        state = take_from_container(state, "holder_1", "holder_2", "item_a")
        self.assertTrue(has_item(state, "holder_2", "item_a"))

    def test_opening_a_non_openable_container_is_not_an_error(self):
        """The caller already has what it asked for."""
        state = declare_container(InventoryState(), "holder_1")
        self.assertTrue(is_container_open(set_container_open(state, "holder_1", False), "holder_1"))

    def test_containers_survive_serialization(self):
        state = declare_container(InventoryState(), "holder_1", openable=True, is_open=False, transparent=True)
        rebuilt = InventoryState.from_dict(state.to_dict())
        self.assertTrue(is_container(rebuilt, "holder_1"))
        self.assertFalse(is_container_open(rebuilt, "holder_1"))

    def test_a_state_predating_containers_still_loads(self):
        old = {"item_locations": {}, "holder_items": {"holder_1": {"item_a": 1}}, "capacities": {}, "stack_limits": {}}
        rebuilt = InventoryState.from_dict(old)
        self.assertEqual(rebuilt.containers, {})
        self.assertTrue(has_item(rebuilt, "holder_1", "item_a"))


class ExpiringContainerTests(SimpleTestCase):
    """`expires_when_empty` -- a container declaration that drops itself
    the moment it holds nothing, for a wrapper that is only ever emptied
    and never refilled or reopened once gone (a gift package, a burst
    pod). Ordinary containers (the default, `expires_when_empty=False`)
    must behave exactly as before -- covered above in `ContainerTests`,
    not repeated here.
    """

    def test_taking_the_last_item_out_drops_the_container_declaration(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = declare_container(state, "holder_1", expires_when_empty=True)
        state = take_from_container(state, "holder_1", "holder_2", "item_a")
        self.assertFalse(is_container(state, "holder_1"))

    def test_the_holder_and_item_survive_the_container_expiring(self):
        """Only the container's own wrapper disappears -- the item just
        taken, and the plain holder underneath, are untouched."""
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = declare_container(state, "holder_1", expires_when_empty=True)
        state = take_from_container(state, "holder_1", "holder_2", "item_a")
        self.assertTrue(has_item(state, "holder_2", "item_a"))
        self.assertTrue(is_container_open(state, "holder_1"))

    def test_taking_one_of_several_items_does_not_expire_it_yet(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = give_item(state, "holder_1", "item_b")
        state = declare_container(state, "holder_1", expires_when_empty=True)
        state = take_from_container(state, "holder_1", "holder_2", "item_a")
        self.assertTrue(is_container(state, "holder_1"))
        state = take_from_container(state, "holder_1", "holder_2", "item_b")
        self.assertFalse(is_container(state, "holder_1"))

    def test_taking_a_partial_stack_does_not_expire_it(self):
        state = give_item(InventoryState(), "holder_1", "item_a", count=3)
        state = declare_container(state, "holder_1", expires_when_empty=True)
        state = take_from_container(state, "holder_1", "holder_2", "item_a", count=2)
        self.assertTrue(is_container(state, "holder_1"))
        state = take_from_container(state, "holder_1", "holder_2", "item_a", count=1)
        self.assertFalse(is_container(state, "holder_1"))

    def test_an_ordinary_container_never_expires(self):
        """The default (`expires_when_empty=False`) must be unaffected --
        emptying a normal container leaves its declaration intact, so it
        can be refilled or reopened later."""
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = declare_container(state, "holder_1")
        state = take_from_container(state, "holder_1", "holder_2", "item_a")
        self.assertTrue(is_container(state, "holder_1"))

    def test_declaring_it_already_empty_does_not_expire_it_early(self):
        """Expiry is only checked on a real `take_from_container` call --
        declaring an empty expiring container (before its starting
        contents are added) must not vanish it on the spot."""
        state = declare_container(InventoryState(), "holder_1", expires_when_empty=True)
        self.assertTrue(is_container(state, "holder_1"))

    def test_a_shut_expiring_container_still_refuses_the_take(self):
        """expires_when_empty must not bypass the ordinary closed-container
        guard -- a shut container is still shut."""
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = declare_container(state, "holder_1", openable=True, is_open=False, expires_when_empty=True)
        with self.assertRaises(ContainerClosedError):
            take_from_container(state, "holder_1", "holder_2", "item_a")

    def test_expiry_survives_serialization(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = declare_container(state, "holder_1", expires_when_empty=True)
        rebuilt = InventoryState.from_dict(state.to_dict())
        self.assertTrue(is_container(rebuilt, "holder_1"))
        rebuilt = take_from_container(rebuilt, "holder_1", "holder_2", "item_a")
        self.assertFalse(is_container(rebuilt, "holder_1"))


class WornSlotTests(SimpleTestCase):
    """Worn slots, whose names belong to the game and not to this module."""

    def test_a_game_declaring_no_slots_wears_nothing(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        self.assertEqual(worn_items(state, "holder_1"), frozenset())
        self.assertFalse(is_worn(state, "holder_1", "item_a"))

    def test_wearing_requires_holding(self):
        with self.assertRaises(ItemNotHeldError):
            wear_item(InventoryState(), "holder_1", "item_a", "slot_x")

    def test_a_worn_item_is_still_held(self):
        """Wearing marks an item; it does not move it out of the
        inventory, so 'do you have it' keeps one home."""
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        self.assertTrue(is_worn(state, "holder_1", "item_a"))
        self.assertTrue(has_item(state, "holder_1", "item_a"))

    def test_a_slot_holds_one_item_by_default(self):
        self.assertEqual(worn_slot_capacity(InventoryState(), "slot_x"), DEFAULT_WORN_SLOT_CAPACITY)

    def test_a_full_slot_refuses_and_displaces_nothing(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = give_item(state, "holder_1", "item_b")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        with self.assertRaises(SlotOccupiedError):
            wear_item(state, "holder_1", "item_b", "slot_x")
        self.assertEqual(worn_in_slot(state, "holder_1", "slot_x"), ("item_a",))

    def test_a_slot_can_be_declared_to_hold_more_than_one(self):
        state = set_worn_slot_capacity(InventoryState(), "slot_x", 2)
        state = give_item(state, "holder_1", "item_a")
        state = give_item(state, "holder_1", "item_b")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        state = wear_item(state, "holder_1", "item_b", "slot_x")
        self.assertEqual(worn_in_slot(state, "holder_1", "slot_x"), ("item_a", "item_b"))

    def test_an_absurd_slot_capacity_is_rejected_not_clamped(self):
        with self.assertRaises(InvalidLimitError):
            set_worn_slot_capacity(InventoryState(), "slot_x", MAX_WORN_SLOT_CAPACITY + 1)

    def test_a_zero_slot_capacity_is_rejected(self):
        """UNLIMITED is meaningless for a slot: a slot that holds
        everything is not a constraint."""
        with self.assertRaises(InvalidLimitError):
            set_worn_slot_capacity(InventoryState(), "slot_x", 0)

    def test_wearing_the_same_item_twice_is_idempotent(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        self.assertEqual(worn_in_slot(state, "holder_1", "slot_x"), ("item_a",))

    def test_removing_a_worn_item_leaves_it_held(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        state = remove_worn_item(state, "holder_1", "item_a")
        self.assertFalse(is_worn(state, "holder_1", "item_a"))
        self.assertTrue(has_item(state, "holder_1", "item_a"))

    def test_removing_something_never_worn_is_not_an_error(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        self.assertFalse(is_worn(remove_worn_item(state, "holder_1", "item_a"), "holder_1", "item_a"))

    def test_two_holders_wear_independently(self):
        """Worn state is per-holder, so it composes with whatever the game
        does about possession."""
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = give_item(state, "holder_2", "item_b")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        state = wear_item(state, "holder_2", "item_b", "slot_x")
        self.assertEqual(worn_in_slot(state, "holder_1", "slot_x"), ("item_a",))
        self.assertEqual(worn_in_slot(state, "holder_2", "slot_x"), ("item_b",))

    def test_worn_state_survives_serialization(self):
        state = give_item(InventoryState(), "holder_1", "item_a")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        self.assertTrue(is_worn(InventoryState.from_dict(state.to_dict()), "holder_1", "item_a"))

    def test_a_state_predating_worn_slots_still_loads(self):
        old = {"item_locations": {}, "holder_items": {"holder_1": {"item_a": 1}}, "capacities": {}, "stack_limits": {}}
        self.assertEqual(InventoryState.from_dict(old).worn, {})


class WornCapacityExemptionTests(SimpleTestCase):
    """Worn items do not count against carrying capacity."""

    def test_wearing_an_item_frees_a_capacity_slot(self):
        state = set_capacity(InventoryState(), "holder_1", 2)
        state = give_item(state, "holder_1", "item_a")
        state = give_item(state, "holder_1", "item_b")
        with self.assertRaises(InventoryFullError):
            give_item(state, "holder_1", "item_c")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        state = give_item(state, "holder_1", "item_c")
        self.assertTrue(has_item(state, "holder_1", "item_c"))

    def test_taking_a_worn_item_off_reclaims_its_capacity_slot(self):
        state = set_capacity(InventoryState(), "holder_1", 2)
        state = give_item(state, "holder_1", "item_a")
        state = wear_item(state, "holder_1", "item_a", "slot_x")
        state = give_item(state, "holder_1", "item_b")
        state = give_item(state, "holder_1", "item_c")
        state = remove_worn_item(state, "holder_1", "item_a")
        with self.assertRaises(InventoryFullError):
            give_item(state, "holder_1", "item_d")

    def test_transfer_also_honours_the_exemption(self):
        state = set_capacity(InventoryState(), "holder_2", 1)
        state = give_item(state, "holder_2", "item_a")
        state = wear_item(state, "holder_2", "item_a", "slot_x")
        state = give_item(state, "holder_1", "item_b")
        state = transfer_item(state, "holder_1", "holder_2", "item_b")
        self.assertTrue(has_item(state, "holder_2", "item_b"))

    def test_a_holder_wearing_nothing_loads_exactly_what_it_holds(self):
        """The exemption must be a no-op for any game that never wears."""
        state = set_capacity(InventoryState(), "holder_1", 1)
        state = give_item(state, "holder_1", "item_a")
        with self.assertRaises(InventoryFullError):
            give_item(state, "holder_1", "item_b")


class DescriptionSlotTests(SimpleTestCase):
    """Lookup-with-fallback. All text belongs to the caller."""

    DEFAULTS = {"initial": "A {name} lies here.", "inventory": "A {name}."}

    def test_an_authored_string_wins(self):
        text = describe("initial", authored={"initial": "authored text"}, defaults=self.DEFAULTS, name="widget")
        self.assertEqual(text, "authored text")

    def test_a_default_template_is_formatted_with_the_name(self):
        self.assertEqual(describe("initial", authored=None, defaults=self.DEFAULTS, name="widget"), "A widget lies here.")

    def test_an_item_authoring_one_slot_still_falls_back_for_another(self):
        authored = {"inventory": "authored text"}
        self.assertEqual(describe("initial", authored=authored, defaults=self.DEFAULTS, name="widget"), "A widget lies here.")

    def test_an_unknown_slot_yields_empty_rather_than_raising(self):
        self.assertEqual(describe("slot_x", authored=None, defaults=self.DEFAULTS, name="widget"), "")

    def test_no_defaults_at_all_yields_empty(self):
        self.assertEqual(describe("initial", authored=None, defaults=None, name="widget"), "")

    def test_an_empty_authored_string_falls_through_to_the_default(self):
        authored = {"initial": ""}
        self.assertEqual(describe("initial", authored=authored, defaults=self.DEFAULTS, name="widget"), "A widget lies here.")

    def test_a_template_without_a_name_placeholder_is_returned_as_is(self):
        defaults = {"use_failure": "That doesn't work here."}
        self.assertEqual(describe("use_failure", authored=None, defaults=defaults, name="widget"), "That doesn't work here.")
