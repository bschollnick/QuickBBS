# Generated by Django 2.1.4 on 2018-12-14 21:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0050_auto_20181214_2033'),
    ]

    operations = [
        migrations.AddField(
            model_name='filetypes',
            name='is_image',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]