"""Serving a bundled game\'s media over HTTP, from the real bundle."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from interactive_fiction.bundle_media import (
    close_all_bundles,
    open_member,
    resolve_tag_in_bundle,
)
from interactive_fiction.models import Story
from interactive_fiction.tests.bundle_fixtures import (
    NEW_GAME_IMAGE,
    VIDEO_TAG,
    write_bundle,
)

#: Tags the synthetic bundle really ships.
AN_IMAGE_TAG = "hero/portrait.jpg"
A_VIDEO_TAG = VIDEO_TAG


class BundleServingTestCase(TestCase):
    def setUp(self):
        self.addCleanup(close_all_bundles)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bundle = write_bundle(self.tmp, name="servinggame")
        self.user = get_user_model().objects.create_user(username="reader", password="pw")
        self.story = Story.objects.create(
            owner=self.user,
            title="A Test Game",
            slug="servinggame",
            compiled_json={"inkVersion": 21, "root": [["done", None], "done", None]},
            is_public=True,
            is_available=True,
            source_fqfn=str(self.bundle),
        )
        self.client = Client()
        self.client.force_login(self.user)


class ImageFromBundleTests(BundleServingTestCase):
    def test_a_tagged_image_is_served_from_the_bundle(self):
        response = self.client.get(f"/if/{self.story.slug}/image/{AN_IMAGE_TAG}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        body = b"".join(response.streaming_content)
        self.assertTrue(body.startswith(b"\xff\xd8"), "not JPEG bytes")

    def test_the_served_bytes_are_the_bundles_own(self):
        member = resolve_tag_in_bundle(self.bundle, "image", AN_IMAGE_TAG)
        handle, size = open_member(self.bundle, member)
        expected = handle.read()
        handle.close()

        response = self.client.get(f"/if/{self.story.slug}/image/{AN_IMAGE_TAG}/", secure=True)
        self.assertEqual(b"".join(response.streaming_content), expected)
        self.assertEqual(int(response["Content-Length"]), size)

    def test_an_unknown_tag_is_404(self):
        response = self.client.get(f"/if/{self.story.slug}/image/no/such/art.jpg/", secure=True)
        self.assertEqual(response.status_code, 404)

    def test_a_slash_bearing_tag_routes_at_all(self):
        """`path:` (not `str:`) in urls.py -- every tag here is
        path-qualified, and `str:` matches no slash."""
        self.assertIn("/", AN_IMAGE_TAG)
        self.assertEqual(self.client.get(f"/if/{self.story.slug}/image/{AN_IMAGE_TAG}/", secure=True).status_code, 200)

    def test_the_response_carries_nosniff(self):
        response = self.client.get(f"/if/{self.story.slug}/image/{AN_IMAGE_TAG}/", secure=True)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")


class StoryVideoFromBundleTests(BundleServingTestCase):
    def test_a_video_is_served_whole_without_a_range_header(self):
        response = self.client.get(f"/if/{self.story.slug}/video/{A_VIDEO_TAG}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "video/mp4")
        self.assertEqual(response["Accept-Ranges"], "bytes")

    def test_a_range_request_answers_206_with_just_that_slice(self):
        """A browser cannot seek a video without this."""
        response = self.client.get(f"/if/{self.story.slug}/video/{A_VIDEO_TAG}/", secure=True, HTTP_RANGE="bytes=100-199")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(int(response["Content-Length"]), 100)
        self.assertIn("bytes 100-199/", response["Content-Range"])
        self.assertEqual(len(b"".join(response.streaming_content)), 100)

    def test_a_range_slice_holds_the_right_bytes(self):
        member = resolve_tag_in_bundle(self.bundle, "video", A_VIDEO_TAG)
        handle, _ = open_member(self.bundle, member)
        expected = handle.read(200)[100:200]
        handle.close()

        response = self.client.get(f"/if/{self.story.slug}/video/{A_VIDEO_TAG}/", secure=True, HTTP_RANGE="bytes=100-199")
        self.assertEqual(b"".join(response.streaming_content), expected)

    def test_an_open_ended_range_runs_to_the_end(self):
        response = self.client.get(f"/if/{self.story.slug}/video/{A_VIDEO_TAG}/", secure=True, HTTP_RANGE="bytes=0-")
        self.assertEqual(response.status_code, 206)

    def test_a_range_past_the_end_is_416(self):
        response = self.client.get(f"/if/{self.story.slug}/video/{A_VIDEO_TAG}/", secure=True, HTTP_RANGE="bytes=999999999-")
        self.assertEqual(response.status_code, 416)


class AccessControlTests(BundleServingTestCase):
    def test_a_private_storys_art_is_not_served_to_a_stranger(self):
        """A guessable media URL must not leak private art -- the same
        user_can_access() gate the story itself has."""
        self.story.is_public = False
        self.story.save(update_fields=["is_public"])
        stranger = Client()
        stranger.force_login(get_user_model().objects.create_user(username="stranger", password="pw"))

        response = stranger.get(f"/if/{self.story.slug}/image/{AN_IMAGE_TAG}/", secure=True)
        self.assertIn(response.status_code, (403, 404))


class NewGameImageServingTests(BundleServingTestCase):
    """The character-creation picker's own images, over HTTP."""

    def test_a_character_creation_image_is_served(self):
        """character_creation.jinja builds these URLs as
        `newgame:<filename>`; before that namespace was handled every one
        of them 404'd on a bundled game."""
        response = self.client.get(f"/if/{self.story.slug}/image/newgame:{NEW_GAME_IMAGE}/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))

    def test_an_unknown_option_image_is_404(self):
        response = self.client.get(f"/if/{self.story.slug}/image/newgame:nope.png/", secure=True)
        self.assertEqual(response.status_code, 404)


class CoverServingTests(BundleServingTestCase):
    def test_a_game_shipping_no_cover_is_404_not_a_crash(self):
        response = self.client.get(f"/if/{self.story.slug}/cover/", secure=True)
        self.assertEqual(response.status_code, 404)
