# Step 3 of 3 (see 0004/0005): now that every StoryImage.file_index has
# been backfilled, drop the superseded StoryImageBlob model and
# StoryImage.blob_id field for good.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("interactive_fiction", "0005_backfill_storyimage_file_index"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="storyimage",
            name="blob_id",
        ),
        migrations.DeleteModel(
            name="StoryImageBlob",
        ),
    ]
