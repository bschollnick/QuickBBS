"""Step 5 tests: interactive_fiction.images (decode/verify, content-addressed
storage, zip-bundle extraction).

TestCase (never TransactionTestCase, per standing project rule) — these
tests write real StoryImageBlob/StoryImage rows through the actual model
layer, not just pure functions.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from interactive_fiction.images import (
    MAX_ZIP_MEMBERS,
    decode_and_verify_image,
    delete_orphaned_blobs,
    extract_image_zip,
    get_or_create_blob,
    set_story_image,
)
from interactive_fiction.models import Story, StoryImage, StoryImageBlob
from interactive_fiction.tests.image_test_utils import make_image_bytes, make_image_zip


def _make_story() -> Story:
    user = get_user_model().objects.create_user(username="imgowner", password="pw")
    return Story.objects.create(owner=user, title="Image Story", slug="image-story", compiled_json={"inkVersion": 21, "root": [], "listDefs": {}})


class DecodeAndVerifyImageTests(TestCase):
    """decode_and_verify_image(): whitelist + real-decode + dimensions."""

    def test_valid_jpeg_decodes_with_correct_dimensions_and_type(self):
        """A real JPEG decodes to image/jpeg with its actual pixel dimensions."""
        decoded = decode_and_verify_image(make_image_bytes("JPEG", size=(10, 6)))
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.content_type, "image/jpeg")
        self.assertEqual((decoded.width, decoded.height), (10, 6))

    def test_valid_png_decodes(self):
        """A real PNG decodes to image/png."""
        decoded = decode_and_verify_image(make_image_bytes("PNG"))
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.content_type, "image/png")

    def test_garbage_bytes_are_rejected(self):
        """Bytes that aren't a real image at all decode to None, not raise."""
        self.assertIsNone(decode_and_verify_image(b"not an image"))

    def test_svg_masquerading_as_declared_image_is_rejected(self):
        """An SVG (scriptable, excluded from the whitelist per the plan's
        stored-XSS mitigation) is rejected even though it's well-formed
        XML — Pillow can't decode it as a raster image at all, so it fails
        the same real-decode path as garbage bytes."""
        svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        self.assertIsNone(decode_and_verify_image(svg_bytes))

    def test_content_type_comes_from_decoded_bytes_not_a_claimed_extension(self):
        """The returned content_type reflects what Pillow actually decoded
        (JPEG bytes -> image/jpeg) regardless of what a caller might later
        name the file — there is no client-supplied MIME type parameter to
        this function at all, which is the point: it can't be spoofed."""
        decoded = decode_and_verify_image(make_image_bytes("PNG"))
        self.assertEqual(decoded.content_type, "image/png")


class GetOrCreateBlobTests(TestCase):
    """get_or_create_blob(): content-addressed dedup (ThumbnailFiles pattern)."""

    def test_identical_bytes_reuse_the_same_blob_row(self):
        """Two calls with identical bytes return the same StoryImageBlob
        pk instead of violating a unique constraint or creating a
        duplicate row — the whole point of content-addressing by hash."""
        raw = make_image_bytes("JPEG")
        decoded = decode_and_verify_image(raw)
        first = get_or_create_blob(raw, decoded)
        second = get_or_create_blob(raw, decoded)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(StoryImageBlob.objects.count(), 1)

    def test_is_cover_generates_a_thumbnail(self):
        """A blob created with is_cover=True gets cover_thumb filled via
        the real thumbnail engine, not left null."""
        raw = make_image_bytes("JPEG", size=(50, 50))
        decoded = decode_and_verify_image(raw)
        blob = get_or_create_blob(raw, decoded, is_cover=True)
        self.assertIsNotNone(blob.cover_thumb)

    def test_non_cover_leaves_thumbnail_null(self):
        """A blob created without is_cover=True has no cover_thumb —
        thumbnail generation only runs for images actually used as covers."""
        raw = make_image_bytes("JPEG")
        decoded = decode_and_verify_image(raw)
        blob = get_or_create_blob(raw, decoded)
        self.assertIsNone(blob.cover_thumb)


class SetStoryImageTests(TestCase):
    """set_story_image(): per-tag attach/replace, is_cover exclusivity."""

    def setUp(self):
        self.story = _make_story()

    def test_valid_image_creates_a_story_image_row(self):
        """A successful call returns None and creates a StoryImage row
        resolvable back to the right blob via the blob property."""
        error = set_story_image(self.story, "forest.jpg", make_image_bytes("JPEG"))
        self.assertIsNone(error)
        image = StoryImage.objects.get(story=self.story, tag_name="forest.jpg")
        self.assertEqual(image.blob.content_type, "image/jpeg")

    def test_invalid_image_returns_an_error_and_creates_nothing(self):
        """Bad bytes report an error naming the tag and leave no row behind."""
        error = set_story_image(self.story, "broken.jpg", b"not an image")
        self.assertIsNotNone(error)
        self.assertIn("broken.jpg", error)
        self.assertFalse(StoryImage.objects.filter(story=self.story, tag_name="broken.jpg").exists())

    def test_uploading_the_same_tag_again_replaces_it(self):
        """A second upload to the same tag_name updates the existing row
        rather than violating the (story, tag_name) uniqueness constraint."""
        set_story_image(self.story, "forest.jpg", make_image_bytes("JPEG", color=(255, 0, 0)))
        set_story_image(self.story, "forest.jpg", make_image_bytes("PNG", color=(0, 255, 0)))
        self.assertEqual(StoryImage.objects.filter(story=self.story, tag_name="forest.jpg").count(), 1)
        image = StoryImage.objects.get(story=self.story, tag_name="forest.jpg")
        self.assertEqual(image.blob.content_type, "image/png")

    def test_setting_a_new_cover_clears_the_previous_one(self):
        """is_cover is exclusive per story (StoryImage's partial unique
        constraint) — setting a new cover unmarks the old one instead of
        violating the constraint."""
        set_story_image(self.story, "first.jpg", make_image_bytes("JPEG"), is_cover=True)
        set_story_image(self.story, "second.jpg", make_image_bytes("PNG"), is_cover=True)
        self.assertEqual(StoryImage.objects.filter(story=self.story, is_cover=True).count(), 1)
        cover = self.story.cover_image
        self.assertEqual(cover.tag_name, "second.jpg")


class ExtractImageZipTests(TestCase):
    """extract_image_zip(): zip-bundle upload, basename-only, hygiene guards."""

    def setUp(self):
        self.story = _make_story()

    def test_each_member_becomes_a_tag_by_its_basename(self):
        """Zip members map to StoryImage rows keyed by basename (extension
        included, per the plan's upload-flow convention)."""
        zip_bytes = make_image_zip({"forest_clearing.jpg": make_image_bytes("JPEG")})
        errors = extract_image_zip(self.story, zip_bytes)
        self.assertEqual(errors, [])
        self.assertTrue(StoryImage.objects.filter(story=self.story, tag_name="forest_clearing.jpg").exists())

    def test_path_traversal_member_names_are_reduced_to_a_basename(self):
        """A member named with directory components or traversal segments
        never gets those segments interpreted as a filesystem path — only
        the basename is used as the tag_name."""
        zip_bytes = make_image_zip({"../../evil/forest.jpg": make_image_bytes("JPEG")})
        errors = extract_image_zip(self.story, zip_bytes)
        self.assertEqual(errors, [])
        self.assertTrue(StoryImage.objects.filter(story=self.story, tag_name="forest.jpg").exists())
        self.assertFalse(StoryImage.objects.filter(tag_name__contains="..").exists())

    def test_not_a_zip_file_is_rejected(self):
        """Non-zip bytes report a clear error instead of raising."""
        errors = extract_image_zip(self.story, b"not a zip")
        self.assertEqual(errors, ["File is not a valid zip archive."])

    def test_one_bad_member_does_not_block_the_rest_of_the_archive(self):
        """A zip with one corrupt image alongside a valid one reports the
        bad member's error but still extracts the good one."""
        zip_bytes = make_image_zip({"good.jpg": make_image_bytes("JPEG"), "bad.jpg": b"not an image"})
        errors = extract_image_zip(self.story, zip_bytes)
        self.assertEqual(len(errors), 1)
        self.assertIn("bad.jpg", errors[0])
        self.assertTrue(StoryImage.objects.filter(story=self.story, tag_name="good.jpg").exists())

    def test_too_many_members_is_rejected_before_extracting_any(self):
        """A zip exceeding MAX_ZIP_MEMBERS is rejected wholesale (zip-bomb
        member-count guard) rather than partially processed."""
        members = {f"img{i}.jpg": make_image_bytes("JPEG") for i in range(MAX_ZIP_MEMBERS + 1)}
        zip_bytes = make_image_zip(members)
        errors = extract_image_zip(self.story, zip_bytes)
        self.assertEqual(len(errors), 1)
        self.assertIn("too many files", errors[0])
        self.assertEqual(StoryImage.objects.filter(story=self.story).count(), 0)

    def test_oversized_member_is_rejected_without_decoding(self):
        """A member declaring a file_size over MAX_STORY_IMAGE_UPLOAD_BYTES
        is rejected by size before any decode attempt."""
        with override_settings(MAX_STORY_IMAGE_UPLOAD_BYTES=10):
            zip_bytes = make_image_zip({"huge.jpg": make_image_bytes("JPEG")})
            errors = extract_image_zip(self.story, zip_bytes)
        self.assertEqual(len(errors), 1)
        self.assertIn("too large", errors[0])
        self.assertFalse(StoryImage.objects.filter(story=self.story, tag_name="huge.jpg").exists())


class DeleteOrphanedBlobsTests(TestCase):
    """delete_orphaned_blobs(): the application-level PROTECT-equivalent cleanup pass."""

    def test_blob_with_no_remaining_story_image_is_deleted(self):
        """A blob whose only StoryImage reference was deleted is removed
        by the cleanup pass."""
        story = _make_story()
        set_story_image(story, "forest.jpg", make_image_bytes("JPEG"))
        StoryImage.objects.filter(story=story, tag_name="forest.jpg").delete()
        deleted_count = delete_orphaned_blobs()
        self.assertEqual(deleted_count, 1)
        self.assertEqual(StoryImageBlob.objects.count(), 0)

    def test_blob_still_referenced_by_another_story_survives(self):
        """A shared blob (two stories, or two tags, using identical bytes)
        is not deleted while at least one StoryImage still references it —
        this is the whole reason blob deletion isn't a DB-level cascade."""
        story_a = _make_story()
        story_b = Story.objects.create(
            owner=story_a.owner, title="Second Story", slug="second-story", compiled_json={"inkVersion": 21, "root": [], "listDefs": {}}
        )
        raw = make_image_bytes("JPEG")
        set_story_image(story_a, "forest.jpg", raw)
        set_story_image(story_b, "forest.jpg", raw)
        StoryImage.objects.filter(story=story_a, tag_name="forest.jpg").delete()

        deleted_count = delete_orphaned_blobs()

        self.assertEqual(deleted_count, 0)
        self.assertEqual(StoryImageBlob.objects.count(), 1)
