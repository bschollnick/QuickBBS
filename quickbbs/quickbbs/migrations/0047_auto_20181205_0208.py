# Generated by Django 2.1.4 on 2018-12-05 02:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0046_index_data_file_ext'),
    ]

    operations = [
        migrations.AlterField(
            model_name='filetypes',
            name='filetype',
            field=models.IntegerField(blank=True, db_index=True, default=0, null=True),
        ),
    ]