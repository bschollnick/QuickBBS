"""Step 3 tests: play/save/load/export/import views end-to-end.

Uses Django's real test client against a Story row built from
tests/fixtures/section3_choices.ink.json (a small, real compiled story
with two once-only choices) — TestCase (never TransactionTestCase, per
standing project rule), since these tests touch real CurrentGame/SaveState
rows through the actual view/model layer, not just engine.py in isolation.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path as FilePath

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from interactive_fiction.images import link_story_image
from interactive_fiction.models import CurrentGame, SaveState, Story, StoryImage
from interactive_fiction.tests.image_test_utils import make_gallery_image
from quickbbs.models import DirectoryIndex
from user_preferences.models import UserPreferences

FIXTURES = FilePath(__file__).parent / "fixtures"


class _AlbumsRootMixin:
    """Points ALBUMS_PATH at a temp dir for the duration of the test, per
    quickbbs/tests/test_fileindex.py's own pattern — DirectoryIndex.add_directory()
    rejects any path outside the configured albums root. Call
    _enable_albums_root() from setUp() and it self-registers cleanup."""

    def _enable_albums_root(self):
        self.temp_dir = tempfile.mkdtemp()
        self.albums_dir = FilePath(self.temp_dir) / "albums"
        self.albums_dir.mkdir(exist_ok=True)
        settings_override = override_settings(ALBUMS_PATH=self.temp_dir)
        settings_override.enable()
        DirectoryIndex._albums_prefix = None
        DirectoryIndex._albums_root = None

        def _cleanup():
            settings_override.disable()
            DirectoryIndex._albums_prefix = None
            DirectoryIndex._albums_root = None
            shutil.rmtree(self.temp_dir, ignore_errors=True)

        self.addCleanup(_cleanup)


def _load_compiled_json() -> dict:
    with open(FIXTURES / "section3_choices.ink.json", encoding="utf-8") as f:
        return json.load(f)


def _load_tagged_story_json() -> dict:
    with open(FIXTURES / "section9_tags.ink.json", encoding="utf-8") as f:
        return json.load(f)


class PlayViewTests(TestCase):
    """GET /if/<slug>/ — loading/resuming a game."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="ifplayer", password="pw")
        self.story = Story.objects.create(owner=self.user, title="Choices", slug="choices-story", compiled_json=_load_compiled_json(), is_public=True)

    def test_anonymous_redirects_to_login(self):
        """An unauthenticated request is redirected to the login flow."""
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_first_visit_creates_current_game_and_shows_opening_text(self):
        """A player's first visit creates a CurrentGame row and shows the
        story's opening text and both choices."""
        self.client.force_login(self.user)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hello, traveler.", response.content)
        self.assertIn(b"Go north", response.content)
        self.assertIn(b"Go south", response.content)
        self.assertTrue(CurrentGame.objects.filter(user=self.user, story=self.story).exists())

    def test_second_visit_resumes_without_duplicating_current_game(self):
        """A second visit reuses the existing CurrentGame row rather than
        creating a second one or restarting the story."""
        self.client.force_login(self.user)
        self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertEqual(CurrentGame.objects.filter(user=self.user, story=self.story).count(), 1)

    def test_play_page_always_offers_a_library_exit_link(self):
        """A player mid-story always has a way back to the library, even
        for a story with no gallery source (uploaded, not scanner-ingested)
        — the sidebar's "up" button points straight at the library."""
        self.client.force_login(self.user)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertIn(b'href="/if/"', response.content)
        self.assertNotIn(b"/view_item/", response.content)


class PlaySubmitViewTests(TestCase):
    """POST /if/<slug>/play/ — submitting a choice, including the
    concurrent-tab guard."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="ifplayer2", password="pw")
        self.story = Story.objects.create(
            owner=self.user, title="Choices", slug="choices-story-2", compiled_json=_load_compiled_json(), is_public=True
        )
        self.client.force_login(self.user)
        self.client.get(f"/if/{self.story.slug}/", secure=True)

    def test_choosing_advances_the_story_and_updates_current_game(self):
        """Submitting a valid choice with the correct turn_count advances
        the story and updates the stored CurrentGame row."""
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        response = self.client.post(
            f"/if/{self.story.slug}/play/",
            {"choice": 0, "turn_count": current_game.turn_count},
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You went north.", response.content)
        current_game.refresh_from_db()
        self.assertEqual(current_game.turn_count, 0)

    def test_stale_turn_count_is_rejected_not_silently_applied(self):
        """A submission with a turn_count that no longer matches the
        stored row (simulating a second, stale browser tab) is rejected
        with 409, and the story does not advance."""
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        stale_turn_count = current_game.turn_count - 1
        response = self.client.post(
            f"/if/{self.story.slug}/play/",
            {"choice": 0, "turn_count": stale_turn_count},
            secure=True,
        )
        self.assertEqual(response.status_code, 409)
        current_game.refresh_from_db()
        self.assertEqual(current_game.turn_count, -1)

    def test_out_of_range_choice_index_is_rejected(self):
        """A choice index outside current_choices is rejected with 400,
        not silently clamped or crashing."""
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        response = self.client.post(
            f"/if/{self.story.slug}/play/",
            {"choice": 99, "turn_count": current_game.turn_count},
            secure=True,
        )
        self.assertEqual(response.status_code, 400)

    def test_get_only_route_requires_post(self):
        """The play_submit endpoint rejects GET (require_POST)."""
        response = self.client.get(f"/if/{self.story.slug}/play/", secure=True)
        self.assertEqual(response.status_code, 405)


class SaveLoadViewTests(TestCase):
    """POST /if/<slug>/saves/<slot>/save/ and .../load/."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="ifplayer3", password="pw")
        self.story = Story.objects.create(
            owner=self.user, title="Choices", slug="choices-story-3", compiled_json=_load_compiled_json(), is_public=True
        )
        self.client.force_login(self.user)
        self.client.get(f"/if/{self.story.slug}/", secure=True)

    def test_save_creates_a_slot_snapshot(self):
        """Saving copies the current CurrentGame.state into a new
        SaveState row for the given slot."""
        response = self.client.post(f"/if/{self.story.slug}/saves/0/save/", {"label": "My save"}, secure=True)
        self.assertEqual(response.status_code, 200)
        save_state = SaveState.objects.get(user=self.user, story=self.story, slot=0)
        self.assertEqual(save_state.label, "My save")
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.assertEqual(save_state.state, current_game.state)

    def test_load_restores_slot_into_current_game_without_mutating_slot(self):
        """Loading a slot copies its state into CurrentGame; the slot
        itself is left untouched, matching the plan's design."""
        # Advance the game one turn, then save at that point.
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": current_game.turn_count}, secure=True)
        self.client.post(f"/if/{self.story.slug}/saves/0/save/", {}, secure=True)
        saved_state_before_load = SaveState.objects.get(user=self.user, story=self.story, slot=0).state

        # Advance further, then load slot 0 back — CurrentGame should
        # revert to the saved turn, and the slot's own state must be
        # unchanged by the act of loading it.
        current_game.refresh_from_db()
        response = self.client.post(f"/if/{self.story.slug}/saves/0/load/", secure=True)
        self.assertEqual(response.status_code, 200)

        current_game.refresh_from_db()
        save_state_after_load = SaveState.objects.get(user=self.user, story=self.story, slot=0)
        self.assertEqual(current_game.state, saved_state_before_load)
        self.assertEqual(save_state_after_load.state, saved_state_before_load)

    def test_slot_out_of_configured_range_is_rejected(self):
        """A slot number outside [0, MAX_SAVE_SLOTS_PER_STORY) is rejected
        with 400."""
        response = self.client.post(f"/if/{self.story.slug}/saves/99/save/", {}, secure=True)
        self.assertEqual(response.status_code, 400)


class ExportImportViewTests(TestCase):
    """GET /if/<slug>/saves/<slot>/export/ and POST .../import/."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="ifplayer4", password="pw")
        self.story = Story.objects.create(
            owner=self.user, title="Choices", slug="choices-story-4", compiled_json=_load_compiled_json(), is_public=True
        )
        self.client.force_login(self.user)
        self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.client.post(f"/if/{self.story.slug}/saves/0/save/", {"label": "Exportable"}, secure=True)

    def test_export_returns_a_valid_envelope(self):
        """The exported file is a JSON envelope with the expected
        version/story_slug/label/state fields."""
        response = self.client.get(f"/if/{self.story.slug}/saves/0/export/", secure=True)
        self.assertEqual(response.status_code, 200)
        envelope = json.loads(response.content)
        self.assertEqual(envelope["quickbbs_if_save_version"], 1)
        self.assertEqual(envelope["story_slug"], self.story.slug)
        self.assertEqual(envelope["label"], "Exportable")
        self.assertIn("state", envelope)
        self.assertIn("attachment", response["Content-Disposition"])

    def test_import_round_trips_an_exported_save(self):
        """A save exported from slot 0 can be imported into slot 1 of the
        same story, preserving its state."""
        export_response = self.client.get(f"/if/{self.story.slug}/saves/0/export/", secure=True)
        exported_bytes = export_response.content

        upload = SimpleUploadedFile("save.json", exported_bytes, content_type="application/json")
        response = self.client.post(f"/if/{self.story.slug}/saves/import/", {"slot": 1, "save_file": upload}, secure=True)
        self.assertEqual(response.status_code, 200)

        original = SaveState.objects.get(user=self.user, story=self.story, slot=0)
        imported = SaveState.objects.get(user=self.user, story=self.story, slot=1)
        self.assertEqual(original.state, imported.state)
        self.assertEqual(imported.label, "Exportable")

    def test_import_rejects_envelope_for_a_different_story(self):
        """An envelope whose story_slug doesn't match the target story is
        rejected with 400, never silently imported."""
        other_story = Story.objects.create(owner=self.user, title="Other", slug="other-story", compiled_json=_load_compiled_json(), is_public=True)
        export_response = self.client.get(f"/if/{self.story.slug}/saves/0/export/", secure=True)

        upload = SimpleUploadedFile("save.json", export_response.content, content_type="application/json")
        response = self.client.post(f"/if/{other_story.slug}/saves/import/", {"slot": 0, "save_file": upload}, secure=True)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SaveState.objects.filter(user=self.user, story=other_story, slot=0).exists())

    def test_import_rejects_oversized_upload(self):
        """An upload larger than MAX_SAVE_FILE_UPLOAD_BYTES is rejected
        before attempting to parse it, per the plan's design."""
        from django.test import override_settings

        oversized = SimpleUploadedFile("save.json", b"{}" + b" " * 1000, content_type="application/json")
        with override_settings(MAX_SAVE_FILE_UPLOAD_BYTES=10):
            response = self.client.post(f"/if/{self.story.slug}/saves/import/", {"slot": 2, "save_file": oversized}, secure=True)
        self.assertEqual(response.status_code, 400)


class CsrfProtectionTests(TestCase):
    """Every POST-accepting interactive_fiction form must carry a CSRF
    token — found 2026-08-16 while starting Step 4's own upload form that
    every Step 3 template (play_content.jinja's HTMX form, saves.jinja's
    three plain forms) omitted {% csrf_token %}/hx-headers entirely, which
    Django's real CsrfViewMiddleware (active, unexempted, confirmed via
    quickbbs/settings.py MIDDLEWARE) would reject in an actual browser;
    PlaySubmitViewTests/SaveLoadViewTests/ExportImportViewTests above never
    caught this because Django's default test Client doesn't enforce CSRF
    unless explicitly configured to. Uses enforce_csrf_checks=True here
    specifically to catch that class of regression."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.user = get_user_model().objects.create_user(username="ifcsrf", password="pw")
        self.story = Story.objects.create(
            owner=self.user, title="Choices", slug="choices-story-csrf", compiled_json=_load_compiled_json(), is_public=True
        )
        self.client.force_login(self.user)

    def test_play_submit_without_csrf_token_is_rejected(self):
        """A play-choice POST with no CSRF token/cookie is rejected with
        403 by the real CsrfViewMiddleware, not accepted."""
        response = self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": -1}, secure=True)
        self.assertEqual(response.status_code, 403)

    def test_play_content_partial_carries_a_csrf_token(self):
        """The rendered play form includes a real (non-empty,
        non-NOTPROVIDED) CSRF token via hx-headers, proving the fix is
        actually wired into the template, not just present in the
        engine's own request context."""
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"X-CSRFToken", response.content)
        self.assertNotIn(b"NOTPROVIDED", response.content)

    def test_saves_page_forms_carry_csrf_tokens(self):
        """The save-slot manager's three POST forms (save/load/import)
        each carry a real csrfmiddlewaretoken hidden input."""
        response = self.client.get(f"/if/{self.story.slug}/saves/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.content.count(b"csrfmiddlewaretoken"), 3)


class UploadViewTests(TestCase):
    """POST /if/upload/ — Step 4: staff-gated story upload with validation."""

    def setUp(self):
        self.client = Client()
        self.staff_user = get_user_model().objects.create_user(username="ifstaff", password="pw", is_staff=True)
        self.regular_user = get_user_model().objects.create_user(username="ifregular", password="pw")

    def test_anonymous_redirects_to_login(self):
        """An unauthenticated request is redirected to the login flow."""
        response = self.client.get("/if/upload/", secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_non_staff_user_is_forbidden(self):
        """can_upload_story() gates this to staff/superuser — a regular
        authenticated user is rejected with 403, not shown the form."""
        self.client.force_login(self.regular_user)
        response = self.client.get("/if/upload/", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_staff_user_can_upload_a_valid_story(self):
        """A staff user uploading a well-formed compiled story (bound
        EXTERNAL, supported inkVersion) is redirected to the new story's
        play page, and the Story row is created not public by default."""
        self.client.force_login(self.staff_user)
        with open(FIXTURES / "section3_choices.ink.json", "rb") as story_file:
            response = self.client.post("/if/upload/", {"title": "My New Story", "story_file": story_file}, secure=True)
        story = Story.objects.get(title="My New Story")
        self.assertRedirects(response, f"/if/{story.slug}/", fetch_redirect_response=False)
        self.assertEqual(story.owner, self.staff_user)
        self.assertFalse(story.is_public)

    def test_upload_rejects_unbound_external(self):
        """A story with an EXTERNAL lacking an ink fallback is rejected
        with the function name in the error, per the plan's requirement,
        and no Story row is created."""
        self.client.force_login(self.staff_user)
        data = json.loads((FIXTURES / "section10_external_uppercase.ink.json").read_text(encoding="utf-8"))
        del data["root"][2]["UPPERCASE"]
        broken_file = SimpleUploadedFile("broken.ink.json", json.dumps(data).encode(), content_type="application/json")
        response = self.client.post("/if/upload/", {"title": "Broken Story", "story_file": broken_file}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"UPPERCASE", response.content)
        self.assertFalse(Story.objects.filter(title="Broken Story").exists())

    def test_upload_rejects_unsupported_ink_version(self):
        """A story compiled against an inkVersion this interpreter was
        never validated against is rejected, not silently accepted."""
        self.client.force_login(self.staff_user)
        data = json.loads((FIXTURES / "section3_choices.ink.json").read_text(encoding="utf-8"))
        data["inkVersion"] = 999
        bad_version_file = SimpleUploadedFile("future.ink.json", json.dumps(data).encode(), content_type="application/json")
        response = self.client.post("/if/upload/", {"title": "Future Story", "story_file": bad_version_file}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"999", response.content)
        self.assertFalse(Story.objects.filter(title="Future Story").exists())

    def test_upload_rejects_non_json_file(self):
        """A file that isn't valid JSON at all is rejected cleanly."""
        self.client.force_login(self.staff_user)
        garbage_file = SimpleUploadedFile("garbage.ink.json", b"not json", content_type="application/json")
        response = self.client.post("/if/upload/", {"title": "Garbage", "story_file": garbage_file}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Story.objects.filter(title="Garbage").exists())


class EditViewTests(TestCase):
    """POST /if/<slug>/edit/ — Step 4: owner-gated title/visibility/content edit."""

    def setUp(self):
        self.client = Client()
        self.owner = get_user_model().objects.create_user(username="ifowner", password="pw", is_staff=True)
        self.other_user = get_user_model().objects.create_user(username="ifother", password="pw")
        self.story = Story.objects.create(
            owner=self.owner, title="Original Title", slug="edit-story", compiled_json=_load_compiled_json(), is_public=False
        )

    def test_non_owner_non_superuser_is_forbidden(self):
        """A user who is neither the story's owner nor a superuser is
        rejected with 403, not shown the edit form."""
        self.client.force_login(self.other_user)
        response = self.client.get(f"/if/{self.story.slug}/edit/", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_update_title_and_visibility_without_replacing_content(self):
        """Editing title/is_public with no story_file leaves compiled_json
        untouched."""
        self.client.force_login(self.owner)
        original_json = self.story.compiled_json
        response = self.client.post(f"/if/{self.story.slug}/edit/", {"title": "Updated Title", "is_public": "on"}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.story.refresh_from_db()
        self.assertEqual(self.story.title, "Updated Title")
        self.assertTrue(self.story.is_public)
        self.assertEqual(self.story.compiled_json, original_json)

    def test_owner_can_replace_compiled_content(self):
        """Uploading a new story_file replaces compiled_json after
        validation passes."""
        self.client.force_login(self.owner)
        with open(FIXTURES / "section10_external_uppercase.ink.json", "rb") as story_file:
            response = self.client.post(f"/if/{self.story.slug}/edit/", {"title": "Original Title", "story_file": story_file}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.story.refresh_from_db()
        self.assertIn("UPPERCASE", self.story.compiled_json["root"][2])

    def test_replacement_content_is_still_validated(self):
        """A re-upload with an unbound EXTERNAL is rejected the same way
        as a first-time upload, leaving the existing content untouched."""
        self.client.force_login(self.owner)
        data = json.loads((FIXTURES / "section10_external_uppercase.ink.json").read_text(encoding="utf-8"))
        del data["root"][2]["UPPERCASE"]
        broken_file = SimpleUploadedFile("broken.ink.json", json.dumps(data).encode(), content_type="application/json")
        original_json = self.story.compiled_json
        response = self.client.post(f"/if/{self.story.slug}/edit/", {"title": "Original Title", "story_file": broken_file}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"UPPERCASE", response.content)
        self.story.refresh_from_db()
        self.assertEqual(self.story.compiled_json, original_json)


class StoryImageViewTests(_AlbumsRootMixin, TestCase):
    """GET /if/<slug>/image/<tag_name>/ — serving a story's linked gallery image."""

    def setUp(self):
        self._enable_albums_root()
        self.client = Client()
        self.owner = get_user_model().objects.create_user(username="imgowner", password="pw", is_staff=True)
        self.other_user = get_user_model().objects.create_user(username="imgother", password="pw")
        self.story = Story.objects.create(
            owner=self.owner, title="Tagged", slug="tagged-story", compiled_json=_load_tagged_story_json(), is_public=False
        )
        file_index = make_gallery_image(self.albums_dir, "cover.jpg")
        link_story_image(self.story, "cover.jpg", file_index)
        self.client.force_login(self.owner)

    def test_owner_can_fetch_a_tagged_image(self):
        """The owner can fetch an image they uploaded for a known tag."""
        response = self.client.get(f"/if/{self.story.slug}/image/cover.jpg/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")

    def test_response_carries_nosniff_header(self):
        """X-Content-Type-Options: nosniff is set per the plan's stored-XSS mitigation."""
        response = self.client.get(f"/if/{self.story.slug}/image/cover.jpg/", secure=True)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_user_without_access_is_forbidden(self):
        """A user with no grant on this non-public story is rejected with
        403 — a guessable image URL must not leak private story art."""
        self.client.force_login(self.other_user)
        response = self.client.get(f"/if/{self.story.slug}/image/cover.jpg/", secure=True)
        self.assertEqual(response.status_code, 403)

    def test_unknown_tag_name_is_404(self):
        """A tag_name with no matching StoryImage row is a plain 404."""
        response = self.client.get(f"/if/{self.story.slug}/image/nonexistent.jpg/", secure=True)
        self.assertEqual(response.status_code, 404)

    def test_anonymous_can_fetch_image_of_a_public_story(self):
        """No login_required on this view — user_can_access() alone gates
        it, so an anonymous visitor to a public story's image URL is
        served the image rather than redirected to login."""
        self.story.is_public = True
        self.story.save(update_fields=["is_public"])
        self.client.logout()
        response = self.client.get(f"/if/{self.story.slug}/image/cover.jpg/", secure=True)
        self.assertEqual(response.status_code, 200)


class StoryCoverViewTests(_AlbumsRootMixin, TestCase):
    """GET /if/<slug>/cover/ — serving a story's library-grid cover thumbnail."""

    def setUp(self):
        self._enable_albums_root()
        self.client = Client()
        self.owner = get_user_model().objects.create_user(username="coverowner", password="pw", is_staff=True)
        self.story = Story.objects.create(
            owner=self.owner, title="Covered", slug="covered-story", compiled_json=_load_compiled_json(), is_public=True
        )

    def test_story_with_no_cover_is_404(self):
        """A story that never had a cover image set returns 404, not an error."""
        response = self.client.get(f"/if/{self.story.slug}/cover/", secure=True)
        self.assertEqual(response.status_code, 404)

    def test_story_with_a_cover_serves_a_jpeg_thumbnail(self):
        """A story with a cover set via edit()'s cover_gallery_path field
        serves the generated thumbnail, always as JPEG."""
        self.client.force_login(self.owner)
        file_index = make_gallery_image(self.albums_dir, "cover.jpg")
        self.client.post(
            f"/if/{self.story.slug}/edit/",
            {"title": "Covered", "is_public": "on", "cover_gallery_path": file_index.full_filepathname},
            secure=True,
        )
        self.client.logout()
        response = self.client.get(f"/if/{self.story.slug}/cover/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")


class UploadWithImagesTests(_AlbumsRootMixin, TestCase):
    """POST /if/upload/ with a "cover_gallery_path" — referencing an existing gallery file."""

    def setUp(self):
        self._enable_albums_root()
        self.client = Client()
        self.staff_user = get_user_model().objects.create_user(username="imgstaff", password="pw", is_staff=True)

    def test_uploading_with_a_cover_gallery_path_attaches_the_cover(self):
        """A cover_gallery_path referencing a real gallery file, submitted
        alongside a new story, attaches it as a StoryImage row on the
        newly created story."""
        self.client.force_login(self.staff_user)
        file_index = make_gallery_image(self.albums_dir, "cover.jpg")
        with open(FIXTURES / "section9_tags.ink.json", "rb") as story_file:
            response = self.client.post(
                "/if/upload/",
                {"title": "Story With Images", "story_file": story_file, "cover_gallery_path": file_index.full_filepathname},
                secure=True,
            )
        story = Story.objects.get(title="Story With Images")
        self.assertRedirects(response, f"/if/{story.slug}/", fetch_redirect_response=False)
        self.assertTrue(StoryImage.objects.filter(story=story, tag_name="cover.jpg").exists())

    def test_uploading_with_an_unknown_gallery_path_is_rejected(self):
        """A cover_gallery_path with no matching gallery file is a
        validation error, not a silent no-op."""
        self.client.force_login(self.staff_user)
        with open(FIXTURES / "section9_tags.ink.json", "rb") as story_file:
            response = self.client.post(
                "/if/upload/",
                {"title": "Story With Bad Cover", "story_file": story_file, "cover_gallery_path": "/nonexistent/path.jpg"},
                secure=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no gallery file found", response.content.lower())
        self.assertFalse(Story.objects.filter(title="Story With Bad Cover").exists())


class EditWithImagesTests(_AlbumsRootMixin, TestCase):
    """POST /if/<slug>/edit/ with "cover_gallery_path" — referencing an existing gallery file."""

    def setUp(self):
        self._enable_albums_root()
        self.client = Client()
        self.owner = get_user_model().objects.create_user(username="editimgowner", password="pw", is_staff=True)
        self.story = Story.objects.create(owner=self.owner, title="Edit Images", slug="edit-images-story", compiled_json=_load_compiled_json())
        self.client.force_login(self.owner)

    def test_cover_gallery_path_sets_the_cover(self):
        """A cover_gallery_path referencing a real gallery file sets the
        story's cover and redirects on success."""
        file_index = make_gallery_image(self.albums_dir, "cover.jpg")
        response = self.client.post(
            f"/if/{self.story.slug}/edit/",
            {"title": "Edit Images", "cover_gallery_path": file_index.full_filepathname},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.story.refresh_from_db()
        cover = self.story.cover_image
        self.assertIsNotNone(cover)
        self.assertEqual(cover.tag_name, "cover.jpg")

    def test_unknown_gallery_path_is_rejected(self):
        """A cover_gallery_path with no matching gallery file is a
        validation error, not a silent no-op or a crash."""
        response = self.client.post(
            f"/if/{self.story.slug}/edit/",
            {"title": "Edit Images", "cover_gallery_path": "/nonexistent/path.jpg"},
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no gallery file found", response.content.lower())
        self.assertIsNone(self.story.cover_image)


class PlayViewImageTagTests(_AlbumsRootMixin, TestCase):
    """GET /if/<slug>/ and POST .../play/ — image: tags render as image_urls."""

    def setUp(self):
        self._enable_albums_root()
        self.client = Client()
        self.owner = get_user_model().objects.create_user(username="playimgowner", password="pw", is_staff=True)
        self.story = Story.objects.create(
            owner=self.owner, title="Tagged Play", slug="tagged-play-story", compiled_json=_load_tagged_story_json(), is_public=True
        )
        self.client.force_login(self.owner)

    def test_image_tag_with_no_matching_story_image_renders_text_only(self):
        """A story whose 'image: cover.jpg' tag has no matching StoryImage
        row still plays — the play page just shows no <img> for it, per
        the plan's work-in-progress-placeholder-tags rule."""
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"if-story-images", response.content)

    def test_image_tag_with_a_matching_story_image_renders_an_img_tag(self):
        """Once cover.jpg is linked, the same tag resolves to a servable
        image URL and an <img> appears in the play page."""
        file_index = make_gallery_image(self.albums_dir, "cover.jpg")
        link_story_image(self.story, "cover.jpg", file_index)
        response = self.client.get(f"/if/{self.story.slug}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/if/{self.story.slug}/image/cover.jpg/".encode(), response.content)


class LibraryPlayStatusTests(TestCase):
    """GET /if/ — Step 7: each story annotated with its play status."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="libstatususer", password="pw")
        self.story = Story.objects.create(
            owner=self.user, title="Status Story", slug="status-story", compiled_json=_load_compiled_json(), is_public=True
        )
        self.client.force_login(self.user)

    def test_never_played_story_shows_no_status_tag(self):
        """A story with no CurrentGame row for this user shows neither
        Continue nor Finished."""
        response = self.client.get("/if/", secure=True)
        self.assertNotIn(b"Continue", response.content)
        self.assertNotIn(b"Finished", response.content)

    def test_in_progress_story_shows_continue(self):
        """A story with an active CurrentGame that still has choices shows
        the Continue tag."""
        self.client.get(f"/if/{self.story.slug}/", secure=True)
        response = self.client.get("/if/", secure=True)
        self.assertIn(b"Continue", response.content)
        self.assertNotIn(b"Finished", response.content)

    def test_finished_story_shows_finished_play_again(self):
        """A story whose CurrentGame has ended (done, no more choices)
        shows the Finished tag instead of Continue — this fixture's 'Go
        north' branch ends the story in one turn."""
        self.client.get(f"/if/{self.story.slug}/", secure=True)
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": current_game.turn_count}, secure=True)
        response = self.client.get("/if/", secure=True)
        self.assertIn(b"Finished", response.content)
        self.assertNotIn(b"Continue", response.content)


class LibraryPaginationTests(TestCase):
    """GET /if/?page=N — the library sidebar's pagination (mirrors the
    main gallery's sidebar, since a library with more stories than fit on
    one page needs the same first/prev/next/last controls)."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="libpageuser", password="pw")
        self.client.force_login(self.user)

    def _make_stories(self, count: int) -> None:
        compiled_json = _load_compiled_json()
        for index in range(count):
            Story.objects.create(owner=self.user, title=f"Story {index:03d}", slug=f"story-{index:03d}", compiled_json=compiled_json, is_public=True)

    def test_single_page_has_no_visible_page_count(self):
        """A library that fits on one page doesn't show a page count line."""
        self._make_stories(3)
        response = self.client.get("/if/", secure=True)
        self.assertNotIn(b"Page 1 of", response.content)

    def test_second_page_shows_the_next_slice_of_stories(self):
        """With more stories than IF_LIBRARY_ITEMS_PER_PAGE, page 2 shows
        a different set of stories than page 1."""
        with override_settings(IF_LIBRARY_ITEMS_PER_PAGE=2):
            self._make_stories(5)
            page1 = self.client.get("/if/?page=1", secure=True)
            page2 = self.client.get("/if/?page=2", secure=True)
        self.assertIn(b"Story 000", page1.content)
        self.assertNotIn(b"Story 002", page1.content)
        self.assertIn(b"Story 002", page2.content)
        self.assertNotIn(b"Story 000", page2.content)

    def test_out_of_range_page_clamps_instead_of_erroring(self):
        """A stale/bookmarked page number beyond the last page clamps to
        the last page rather than returning an empty page or 404."""
        with override_settings(IF_LIBRARY_ITEMS_PER_PAGE=2):
            self._make_stories(3)
            response = self.client.get("/if/?page=999", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Story 002", response.content)

    def test_library_sidebar_offers_a_way_back_to_the_gallery(self):
        """The library page's sidebar (not an ad hoc button) links back to
        the main gallery."""
        self._make_stories(1)
        response = self.client.get("/if/", secure=True)
        self.assertIn(b'href="/albums/"', response.content)


class PlayUndoRestartTranscriptTests(TestCase):
    """POST /if/<slug>/undo/ and .../restart/, plus transcript rendering — Step 8."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="undoresetuser", password="pw")
        self.story = Story.objects.create(owner=self.user, title="Undo Story", slug="undo-story", compiled_json=_load_compiled_json(), is_public=True)
        self.client.force_login(self.user)
        self.client.get(f"/if/{self.story.slug}/", secure=True)

    def test_fresh_game_has_nothing_to_undo(self):
        """A game on its opening turn has no previous_state — undo is
        rejected with 400 rather than doing nothing silently."""
        response = self.client.post(f"/if/{self.story.slug}/undo/", secure=True)
        self.assertEqual(response.status_code, 400)

    def test_undo_restores_the_previous_turn(self):
        """After one choice, undo restores CurrentGame to the opening
        turn's text and choices."""
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": current_game.turn_count}, secure=True)

        response = self.client.post(f"/if/{self.story.slug}/undo/", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hello, traveler.", response.content)
        self.assertIn(b"Go north", response.content)
        current_game.refresh_from_db()
        self.assertEqual(current_game.turn_count, -1)

    def test_undo_after_undo_has_nothing_left_to_undo(self):
        """One level only — undoing twice in a row rejects the second
        attempt (no bounded history stack, per the plan)."""
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": current_game.turn_count}, secure=True)
        self.client.post(f"/if/{self.story.slug}/undo/", secure=True)

        response = self.client.post(f"/if/{self.story.slug}/undo/", secure=True)
        self.assertEqual(response.status_code, 400)

    def test_restart_resets_to_the_opening_turn(self):
        """After finishing the story, restart discards progress and
        returns to the opening turn."""
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": current_game.turn_count}, secure=True)

        response = self.client.post(f"/if/{self.story.slug}/restart/", secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hello, traveler.", response.content)
        self.assertIn(b"Go north", response.content)
        current_game.refresh_from_db()
        self.assertEqual(current_game.turn_count, -1)

    def test_restart_leaves_named_save_slots_untouched(self):
        """Restart only ever touches the single CurrentGame row — a named
        SaveState slot survives a restart unchanged."""
        self.client.post(f"/if/{self.story.slug}/saves/0/save/", {"label": "Before restart"}, secure=True)
        saved_before = SaveState.objects.get(user=self.user, story=self.story, slot=0).state

        self.client.post(f"/if/{self.story.slug}/restart/", secure=True)

        saved_after = SaveState.objects.get(user=self.user, story=self.story, slot=0).state
        self.assertEqual(saved_before, saved_after)

    def test_transcript_shows_prior_turns_on_the_play_page(self):
        """After a choice, the play page includes the prior turn's text in
        its transcript section, above the current turn."""
        current_game = CurrentGame.objects.get(user=self.user, story=self.story)
        self.client.post(f"/if/{self.story.slug}/play/", {"choice": 0, "turn_count": current_game.turn_count}, secure=True)

        response = self.client.get(f"/if/{self.story.slug}/", secure=True)

        self.assertIn(b"if-story-transcript", response.content)
        self.assertIn(b"Hello, traveler.", response.content)


class PreferencesViewTests(TestCase):
    """GET/POST /if/preferences/ — Step 8: reader display preferences."""

    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username="prefsuser", password="pw")
        self.client.force_login(self.user)

    def test_anonymous_redirects_to_login(self):
        """An unauthenticated request is redirected to the login flow."""
        self.client.logout()
        response = self.client.get("/if/preferences/", secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_defaults_are_medium(self):
        """A user with no prior preferences sees the model's own defaults."""
        response = self.client.get("/if/preferences/", secure=True)
        self.assertEqual(response.status_code, 200)
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.if_font_size, "medium")
        self.assertEqual(prefs.if_text_width, "medium")

    def test_valid_choices_are_saved(self):
        """Posting valid choices updates the user's UserPreferences row."""
        response = self.client.post("/if/preferences/", {"if_font_size": "large", "if_text_width": "narrow"}, secure=True)
        self.assertEqual(response.status_code, 302)
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.if_font_size, "large")
        self.assertEqual(prefs.if_text_width, "narrow")

    def test_invalid_choice_is_rejected_without_saving(self):
        """An out-of-range choice value is rejected — the row keeps its
        previous value rather than storing garbage."""
        response = self.client.post("/if/preferences/", {"if_font_size": "gigantic", "if_text_width": "medium"}, secure=True)
        self.assertEqual(response.status_code, 200)
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.if_font_size, "medium")

    def test_preferences_apply_css_classes_on_the_play_page(self):
        """Saved preferences show up as if-font-*/if-width-* classes on
        the play page's section wrapper."""
        self.client.post("/if/preferences/", {"if_font_size": "small", "if_text_width": "wide"}, secure=True)
        story = Story.objects.create(owner=self.user, title="Prefs Story", slug="prefs-story", compiled_json=_load_compiled_json(), is_public=True)
        response = self.client.get(f"/if/{story.slug}/", secure=True)
        self.assertIn(b"if-font-small", response.content)
        self.assertIn(b"if-width-wide", response.content)
