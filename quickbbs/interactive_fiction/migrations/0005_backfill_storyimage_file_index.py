# Step 2 of 3 (see 0004/0006): backfill the new file_index FK from each
# StoryImage's existing blob_id -> StoryImageBlob.sha256_hash, matched
# against FileIndex.file_sha256 (content hash, not unique_sha256 — a blob's
# bytes can legitimately match any one of several FileIndex rows sharing
# that content; the first match is a stable, sufficient choice since the
# whole point is "this is the same picture", not a specific file identity).
#
# Confirmed against production data before writing this migration (2026-08-21):
# both live stories using StoryImageBlob-backed images (pk 3, 8 rows;
# pk 4, 90 rows) resolve 98/98 by this exact match, once their
# gallery images were scanned into Albums/. Any row that still fails to
# match (e.g. a future StoryImage created between this migration being
# written and applied, for an image not yet scanned into the gallery) is
# left with file_index=None rather than raising — matching this app's
# existing "an unresolved tag doesn't break the story" tolerance
# (interactive_fiction.views._current_image_urls silently skips tags with
# no resolvable StoryImage/file_index).

import logging

from django.db import migrations

logger = logging.getLogger(__name__)


def backfill_file_index(apps, schema_editor):
    """Match each StoryImage's blob content hash to a live FileIndex row."""
    StoryImage = apps.get_model("interactive_fiction", "StoryImage")
    StoryImageBlob = apps.get_model("interactive_fiction", "StoryImageBlob")
    FileIndex = apps.get_model("quickbbs", "FileIndex")

    matched = unmatched = 0
    for story_image in StoryImage.objects.all():
        try:
            blob = StoryImageBlob.objects.get(pk=story_image.blob_id)
        except StoryImageBlob.DoesNotExist:
            unmatched += 1
            continue

        file_index = FileIndex.objects.filter(file_sha256=blob.sha256_hash, delete_pending=False).first()
        if file_index is None:
            unmatched += 1
            logger.warning(
                "No FileIndex match for StoryImage story_id=%s tag_name=%r (blob sha256=%s) — "
                "left unlinked; see StoryImage.file_index's docstring.",
                story_image.story_id,
                story_image.tag_name,
                blob.sha256_hash,
            )
            continue

        story_image.file_index = file_index
        story_image.save(update_fields=["file_index"])
        matched += 1

    logger.info("StoryImage.file_index backfill: %d matched, %d unmatched.", matched, unmatched)


def noop_reverse(apps, schema_editor):
    """Reversal is a no-op: file_index is dropped again by a later
    migration reversal anyway, and there's no meaningful "undo" for a
    backfill match beyond clearing the field, which the schema reversal
    already implies."""


class Migration(migrations.Migration):

    dependencies = [
        ("interactive_fiction", "0004_storyimage_file_index"),
    ]

    operations = [
        migrations.RunPython(backfill_file_index, noop_reverse),
    ]
