# Generated by Django 4.1.3 on 2022-11-25 17:36

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="filetypes",
            fields=[
                (
                    "fileext",
                    models.CharField(
                        db_index=True,
                        max_length=10,
                        primary_key=True,
                        serialize=False,
                        unique=True,
                    ),
                ),
                ("generic", models.BooleanField(db_index=True, default=False)),
                (
                    "icon_filename",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=384
                    ),
                ),
                ("color", models.CharField(default="000000", max_length=7)),
                (
                    "filetype",
                    models.IntegerField(
                        blank=True, db_index=True, default=0, null=True
                    ),
                ),
                ("is_image", models.BooleanField(db_index=True, default=False)),
                ("is_archive", models.BooleanField(db_index=True, default=False)),
                ("is_pdf", models.BooleanField(db_index=True, default=False)),
                ("is_movie", models.BooleanField(db_index=True, default=False)),
                ("is_dir", models.BooleanField(db_index=True, default=False)),
            ],
            options={
                "verbose_name": "File Type",
                "verbose_name_plural": "File Types",
            },
        ),
    ]
