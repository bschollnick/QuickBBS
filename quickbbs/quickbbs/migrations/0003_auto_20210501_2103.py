# Generated by Django 3.2 on 2021-05-02 02:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0002_auto_20210501_2100'),
    ]

    operations = [
        migrations.AddField(
            model_name='thumbnails_large',
            name='FileSize',
            field=models.BigIntegerField(default=-1),
        ),
        migrations.AddField(
            model_name='thumbnails_medium',
            name='FileSize',
            field=models.BigIntegerField(default=-1),
        ),
        migrations.AddField(
            model_name='thumbnails_small',
            name='FileSize',
            field=models.BigIntegerField(default=-1),
        ),
    ]