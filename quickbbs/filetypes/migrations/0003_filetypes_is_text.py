# Generated by Django 4.1.3 on 2022-12-01 19:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("filetypes", "0002_filetypes_is_audio"),
    ]

    operations = [
        migrations.AddField(
            model_name="filetypes",
            name="is_text",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]