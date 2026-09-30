# Step 1 of 3 (see 0005/0006): add the new file_index FK, nullable, so
# 0005's data migration can backfill it from the still-present blob_id
# before 0006 removes StoryImageBlob/blob_id for good.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("interactive_fiction", "0003_storyimageblob_remove_story_cover_image_and_more"),
        ("quickbbs", "0043_favorite_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="storyimage",
            name="file_index",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.DB_SET_NULL,
                related_name="story_images",
                to="quickbbs.fileindex",
            ),
        ),
    ]
