# -*- coding: utf-8 -*-
# Generated by Django 1.11.9 on 2018-04-28 02:22
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0036_index_data_file_tnail'),
    ]

    operations = [
        migrations.AddField(
            model_name='index_data',
            name='archives',
            field=models.OneToOneField(default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='quickbbs.Thumbnails_Archives'),
        ),
    ]