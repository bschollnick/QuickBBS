from __future__ import annotations

import re

from django.db import models

# Pre-compiled regex patterns for natural sorting
_STRIP_THE_RE = re.compile(r"^the\s+", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+")


def _naturalize_int_match(match: re.Match) -> str:
    """Zero-pad integers to 8 digits for natural sorting."""
    return "%08d" % (int(match.group(0)),)


class NaturalSortField(models.CharField):
    def __init__(self, for_field, **kwargs):
        self.for_field = for_field
        kwargs.setdefault("db_index", True)
        kwargs.setdefault("editable", False)
        kwargs.setdefault("max_length", 255)
        super().__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        args.append(self.for_field)
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        return self.naturalize(getattr(model_instance, self.for_field))

    def naturalize(self, string: str) -> str:
        """Convert string to natural sort key with zero-padded numbers."""
        string = string.lower().strip()
        string = _STRIP_THE_RE.sub("", string)
        string = _DIGITS_RE.sub(_naturalize_int_match, string)
        return string
