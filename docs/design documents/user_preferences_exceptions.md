# user_preferences — Exception Taxonomy

**Companion to:** N/A (no standalone `user_preferences_design.md` exists yet)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

`user_preferences` has no custom exceptions, and no `raise`/`except`/`try` statements
of any kind, in any non-test, non-migration file (`models.py`, `views.py`,
`signals.py`, `admin.py`, `apps.py`). This is the shortest file in the taxonomy
series because there is nothing to document beyond that absence. Verified by grep
across every source file in the app.

---

## No exception handling

`toggle_show_duplicates` (`user_preferences/views.py:15–35`) is the app's one
consequential write path: it wraps a `UserPreferences.objects.get_or_create(...)` call
and a `preferences.save()` inside `transaction.atomic()`, with no exception handling
around either. An error at either step (a database failure, a constraint violation)
propagates uncaught out of the view and becomes Django's default 500 response —
`user_preferences` relies entirely on that default propagation rather than any
app-level handling of its own.

This is consistent with the read side: reading `UserPreferences.show_duplicates`
elsewhere in the codebase is handled at the *caller's* side, not here — see
[`frontend_exceptions.md`](frontend_exceptions.md)'s
`_get_show_duplicates_preference`, which catches `(DatabaseError, OperationalError,
AttributeError)` around its own lookup of this same model.
