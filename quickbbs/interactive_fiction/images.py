"""Story image handling for the interactive_fiction app (Step 5).

Decode-and-verify, content-addressed storage, and zip-bundle extraction for
the images an Ink author tags with `# image: <tag_name>`. See the plan's
Step 5 section for the model shape (StoryImageBlob/StoryImage) and the
security rationale for the whitelist/verify/nosniff steps below — the
serving path is a stored-XSS surface unless constrained, since the blob and
its content type are author-supplied and served back to other users under
the site origin.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from io import BytesIO

from django.conf import settings
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from interactive_fiction.models import Story, StoryImage, StoryImageBlob
from thumbnails.engine.engine import create_thumbnails_from_bytes

# Zip-bundle upload hygiene (Step 5's zip-bomb guard): cap member count so a
# crafted archive can't force thousands of decode attempts.
MAX_ZIP_MEMBERS = 200


@dataclass
class DecodedImage:
    """The result of a successful decode-and-verify pass on raw image bytes."""

    content_type: str
    width: int
    height: int
    sha256_hash: str


def decode_and_verify_image(raw_bytes: bytes) -> DecodedImage | None:
    """Decode, verify, and fingerprint an uploaded image.

    The stored content_type always comes from what Pillow identified, never
    from the client's declared MIME type (per the plan's Step 5 security
    rules) — a mismatched or absent declared type can't smuggle a
    non-whitelisted format through.

    Args:
        raw_bytes: The raw uploaded image content.

    Returns:
        A DecodedImage, or None if the bytes don't decode as a whitelisted
        image format (settings.STORY_IMAGE_CONTENT_TYPES).
    """
    try:
        with Image.open(BytesIO(raw_bytes)) as image:
            image.verify()
        with Image.open(BytesIO(raw_bytes)) as image:
            width, height = image.size
            pillow_format = image.format
    except (UnidentifiedImageError, OSError, ValueError):
        return None

    content_type = Image.MIME.get(pillow_format or "", "")
    if content_type not in settings.STORY_IMAGE_CONTENT_TYPES:
        return None

    return DecodedImage(
        content_type=content_type,
        width=width,
        height=height,
        sha256_hash=hashlib.sha256(raw_bytes).hexdigest(),
    )


def get_or_create_blob(raw_bytes: bytes, decoded: DecodedImage, *, is_cover: bool = False) -> StoryImageBlob:
    """Get or create the content-addressed StoryImageBlob for the given bytes.

    Matches the ThumbnailFiles dedup pattern: identical bytes uploaded again
    (by any story, any tag) reuse the same row instead of violating a
    per-story unique constraint. `cover_thumb` is filled the first time the
    blob is used as a cover image; an already-existing blob later used as a
    cover gets its thumbnail backfilled rather than left null.

    Args:
        raw_bytes: The raw image content (already verified by the caller).
        decoded: The result of decode_and_verify_image(raw_bytes).
        is_cover: Whether this upload is being used as a story's cover_image
            — triggers cover_thumb generation.

    Returns:
        The StoryImageBlob row (existing or newly created).
    """
    blob, created = StoryImageBlob.objects.get_or_create(
        sha256_hash=decoded.sha256_hash,
        defaults={
            "content_type": decoded.content_type,
            "image_blob": raw_bytes,
            "width": decoded.width,
            "height": decoded.height,
        },
    )
    if is_cover and blob.cover_thumb is None:
        thumbs = create_thumbnails_from_bytes(raw_bytes, settings.STORY_COVER_THUMB_SIZE, output="JPEG")
        blob.cover_thumb = thumbs["cover"]
        blob.save(update_fields=["cover_thumb"])
    del created
    return blob


def set_story_image(story: Story, tag_name: str, raw_bytes: bytes, *, is_cover: bool = False) -> str | None:
    """Validate and attach an image to a story's `tag_name`, replacing any prior mapping.

    Args:
        story: The story the image belongs to.
        tag_name: The Ink `# image: <tag_name>` value this upload maps to.
        raw_bytes: The raw uploaded image content.
        is_cover: Whether to mark the resulting StoryImage as this story's
            cover (see StoryImage.is_cover) and generate its library-grid
            thumbnail.

    Returns:
        None on success, or an error message if raw_bytes did not decode as
        a whitelisted image format.
    """
    decoded = decode_and_verify_image(raw_bytes)
    if decoded is None:
        return f"Image for '{tag_name}' is not a valid JPEG/PNG/GIF/WEBP file."

    with transaction.atomic():
        blob = get_or_create_blob(raw_bytes, decoded, is_cover=is_cover)
        if is_cover:
            StoryImage.objects.filter(story=story, is_cover=True).exclude(tag_name=tag_name).update(is_cover=False)
        defaults: dict[str, object] = {"blob_id": blob.pk}
        if is_cover:
            defaults["is_cover"] = True
        StoryImage.objects.update_or_create(story=story, tag_name=tag_name, defaults=defaults)
    return None


def delete_orphaned_blobs() -> int:
    """Delete every StoryImageBlob with no remaining StoryImage reference.

    The application-level equivalent of PROTECT's enforcement (see
    StoryImage's docstring for why blob_id can't be a real FK with a
    DB-level PROTECT constraint) — call this after a story or a per-tag
    image is deleted/replaced, never implicitly mid-delete.

    Returns:
        The number of orphaned blob rows deleted.
    """
    referenced_ids = set(StoryImage.objects.values_list("blob_id", flat=True))
    orphaned = StoryImageBlob.objects.exclude(pk__in=referenced_ids)
    count = orphaned.count()
    orphaned.delete()
    return count


def extract_image_zip(story: Story, zip_bytes: bytes) -> list[str]:
    """Extract a zip of story images, mapping each basename (minus extension) to a tag_name.

    Member paths are never interpreted as directories (basenames only, per
    the plan's Step 5 path-traversal guard) — a member named `../../evil` is
    stored under the tag name `evil`, never written to any filesystem path.

    Args:
        story: The story the images belong to.
        zip_bytes: The raw uploaded zip file content.

    Returns:
        A list of error messages (empty on full success). Errors from
        individual bad members don't stop the rest of the archive.
    """
    errors: list[str] = []
    try:
        with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if len(members) > MAX_ZIP_MEMBERS:
                return [f"Zip archive has too many files (max {MAX_ZIP_MEMBERS})."]

            for info in members:
                basename = info.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                if not basename:
                    continue
                if info.file_size > settings.MAX_STORY_IMAGE_UPLOAD_BYTES:
                    errors.append(f"'{basename}' is too large (max {settings.MAX_STORY_IMAGE_UPLOAD_BYTES:,} bytes).")
                    continue
                error = set_story_image(story, basename, archive.read(info))
                if error:
                    errors.append(error)
    except zipfile.BadZipFile:
        return ["File is not a valid zip archive."]
    return errors
