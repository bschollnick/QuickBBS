# -*- coding: utf-8 -*-
# Generated by Django 1.11.5 on 2017-11-07 19:14
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0015_auto_20171107_1413'),
    ]

    operations = [
        migrations.AlterField(
            model_name='filedata',
            name='SortFileName',
            field=models.CharField(db_index=True, default='d', editable=False, max_length=512),
        ),
    ]