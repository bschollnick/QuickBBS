# -*- coding: utf-8 -*-
# Generated by Django 1.11.9 on 2018-04-17 02:23
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0028_auto_20180417_0220'),
    ]

    operations = [
        migrations.AlterField(
            model_name='favorites',
            name='uuid',
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='index_data',
            name='uuid',
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='thumbnails_archives',
            name='uuid',
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='thumbnails_dirs',
            name='uuid',
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='thumbnails_files',
            name='uuid',
            field=models.UUIDField(default=None, editable=False, null=True),
        ),
    ]