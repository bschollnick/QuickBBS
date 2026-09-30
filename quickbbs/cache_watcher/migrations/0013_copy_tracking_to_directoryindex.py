"""Data migration: copy fs_Cache_Tracking state onto DirectoryIndex.

Copies invalidated/lastscan from CacheWatcher_fs_cache_tracking into the new
cache_invalidated/cache_lastscan fields on quickbbs_directoryindex (added by
quickbbs 0041), joining on the dir_fqpn_sha256 varchar key. Run and verified
BEFORE 0014 drops the tracking table — both copies of the data exist between
the two migrations so the copy can be validated against the live rows.

Reverse: refills the tracking table from the DirectoryIndex fields. This
produces one row per DirectoryIndex — a superset of the original tracking
rows — which is semantically correct but not a byte-identical rollback.

See claude_docs/plans/Directory_index_overhaul.md Section 4.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("CacheWatcher", "0012_alter_fs_cache_tracking_invalidated"),
        ("quickbbs", "0041_directoryindex_cache_invalidated_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE quickbbs_directoryindex AS d
                SET cache_invalidated = c.invalidated,
                    cache_lastscan   = c.lastscan
                FROM "CacheWatcher_fs_cache_tracking" AS c
                WHERE c.directory_data = d.dir_fqpn_sha256;
            """,
            reverse_sql="""
                INSERT INTO "CacheWatcher_fs_cache_tracking" (lastscan, invalidated, directory_data)
                SELECT d.cache_lastscan, d.cache_invalidated, d.dir_fqpn_sha256
                FROM quickbbs_directoryindex AS d
                ON CONFLICT (directory_data) DO UPDATE
                    SET lastscan = EXCLUDED.lastscan, invalidated = EXCLUDED.invalidated;
            """,
        ),
    ]
