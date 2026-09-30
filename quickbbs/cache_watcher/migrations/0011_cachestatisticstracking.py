import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add CacheStatisticsTracking model for periodic cache hit/miss snapshots."""

    dependencies = [
        ("CacheWatcher", "0010_remove_redundant_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="CacheStatisticsTracking",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("cache_name", models.CharField(db_index=True, max_length=100, unique=True)),
                ("hits", models.BigIntegerField(default=0)),
                ("misses", models.BigIntegerField(default=0)),
                ("current_size", models.IntegerField(default=0)),
                ("max_size", models.IntegerField(default=0)),
                ("last_snapshot_at", models.DateTimeField(auto_now=True)),
                ("last_reset_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "cache_statistics_tracking",
            },
        ),
    ]
