"""Drop the fs_Cache_Tracking table after 0013 copied its state to DirectoryIndex.

Metadata-only DROP TABLE; also removes the table's pkey, the directory_data
unique and varchar_pattern_ops indexes, and the (directory, invalidated)
composite index. Reverse recreates the (empty) table, after which reversing
0013 refills it. See claude_docs/plans/Directory_index_overhaul.md Section 4.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("CacheWatcher", "0013_copy_tracking_to_directoryindex"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="fs_cache_tracking",
            name="CacheWatche_directo_4b46dc_idx",
        ),
        migrations.DeleteModel(
            name="fs_Cache_Tracking",
        ),
    ]
