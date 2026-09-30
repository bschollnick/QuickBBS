"""Make room for the quicksave, and denormalize turn_count.

`slot` becomes signed so it can hold the shared quicksave number (-1),
which is negative precisely so it falls outside every numbered range.
The check constraint gains a matching floor.

Existing rows keep working: `state` is untouched and every stored slot
number is already within the new range. Only the format of an *exported
save file* changes, and that is a clean break with no in-place data.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("interactive_fiction", "0016_remove_storysystemconfig_unique_story_system_config_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="savestate",
            name="savestate_slot_ceiling",
        ),
        migrations.AddField(
            model_name="savestate",
            name="turn_count",
            field=models.IntegerField(default=-1),
        ),
        migrations.AlterField(
            model_name="savestate",
            name="slot",
            field=models.SmallIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="savestate",
            constraint=models.CheckConstraint(condition=models.Q(("slot__gte", -1), ("slot__lt", 32)), name="savestate_slot_ceiling"),
        ),
    ]
