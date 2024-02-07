from django.db import models
import re


class NaturalSortField(models.CharField):
    def __init__(self, for_field, **kwargs):
        self.for_field = for_field
        kwargs.setdefault("db_index", True)
        kwargs.setdefault("editable", False)
        kwargs.setdefault("max_length", 255)
        super(NaturalSortField, self).__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super(NaturalSortField, self).deconstruct()
        args.append(self.for_field)
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        return self.naturalize(getattr(model_instance, self.for_field))

    def naturalize(self, string):
        def naturalize_int_match(match):
            return "%08d" % (int(match.group(0)),)

        string = string.lower()
        string = string.strip()
        string = re.sub(r"^the\s+", "", string)
        string = re.sub(r"\d+", naturalize_int_match, string)

        return string
