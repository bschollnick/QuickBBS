"""
Constants for QuickBBS, the python edition.
"""

import re

# used in Utilities
replacements = {"?": "", "/": "", ":": "", "#": "_"}
regex = re.compile("({})".format("|".join(map(re.escape, replacements))))
