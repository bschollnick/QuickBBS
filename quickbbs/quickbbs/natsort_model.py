"""Self-maintaining natural-sort CharField for Django models."""

from __future__ import annotations

import re

from django.db import models

# Pre-compiled regex patterns for natural sorting
_STRIP_THE_RE = re.compile(r"^the\s+", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+")


def _naturalize_int_match(match: re.Match) -> str:
    """Zero-pad integers to 8 digits for natural sorting."""
    return f"{int(match.group(0)):08d}"


class NaturalSortField(models.CharField):
    """CharField that stores a natural-sort key derived from another field.

    On every save, pre_save() recomputes the key from `for_field`:
    lowercased, leading "the " stripped, and digit runs zero-padded to 8
    digits — so "file2" sorts before "file10" in plain ORDER BY.

    Example:
        >>> name_sort = NaturalSortField(for_field="name", max_length=384)
        >>> # "Episode 2" is stored as "episode 00000002"
    """

    def __init__(self, for_field, **kwargs):
        """Initialize the field.

        Args:
            for_field: Name of the model field the sort key is derived from.
            **kwargs: CharField options; db_index defaults to True,
                editable to False, max_length to 255.
        """
        self.for_field = for_field
        kwargs.setdefault("db_index", True)
        kwargs.setdefault("editable", False)
        kwargs.setdefault("max_length", 255)
        super().__init__(**kwargs)

    def deconstruct(self) -> tuple[str, str, list, dict]:
        """Return the field's deconstructed form for migration serialization.

        ``db_index`` is emitted explicitly: ``__init__`` defaults it to True via
        setdefault, so omitting it (CharField only serializes non-default values,
        and the Field default is False) would make a ``db_index=False`` declaration
        reconstruct as ``db_index=True``, causing endless AlterField churn.

        Returns:
            Tuple of (name, path, args, kwargs) for reconstructing the field.
        """
        name, path, args, kwargs = super().deconstruct()  # pylint: disable=no-member
        args.append(self.for_field)
        kwargs["db_index"] = self.db_index
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        """Return the naturalized sort key computed from for_field's current value."""
        return self.naturalize(getattr(model_instance, self.for_field))

    def naturalize(self, string: str) -> str:
        """Convert string to natural sort key with zero-padded numbers."""
        string = string.lower().strip()
        string = _STRIP_THE_RE.sub("", string)
        string = _DIGITS_RE.sub(_naturalize_int_match, string)
        return string
