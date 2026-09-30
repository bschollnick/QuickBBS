# Generated manually for IndexDirs to DirectoryIndex rename

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('quickbbs', '0034_indexdata_indexdata_sha256_unlinked_idx_and_more'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='IndexDirs',
            new_name='DirectoryIndex',
        ),
        migrations.AlterModelTable(
            name='DirectoryIndex',
            table='quickbbs_directoryindex',
        ),
    ]
