# Generated by Django 5.2.1 on 2025-05-14 20:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("CacheWatcher", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="fs_cache_tracking",
            name="directory_sha256",
            field=models.CharField(
                blank=True, db_index=True, default=None, null=True, unique=True
            ),
        ),
    ]
