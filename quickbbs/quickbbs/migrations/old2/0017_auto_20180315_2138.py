# -*- coding: utf-8 -*-
# Generated by Django 1.11.9 on 2018-03-15 21:38
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0016_thumbnails_files'),
    ]

    operations = [
        migrations.AlterField(
            model_name='thumbnails_files',
            name='LargeThumb',
            field=models.BinaryField(default=b''),
        ),
        migrations.AlterField(
            model_name='thumbnails_files',
            name='MediumThumb',
            field=models.BinaryField(default=b''),
        ),
        migrations.AlterField(
            model_name='thumbnails_files',
            name='SmallThumb',
            field=models.BinaryField(default=b''),
        ),
    ]