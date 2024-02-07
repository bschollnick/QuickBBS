"""
Constants for QuickBBS, the python edition.
"""

import re

# used in Utilities
replacements = {"?": "", "/": "", ":": "", "#": "_"}
regex = re.compile("(%s)" % "|".join(map(re.escape, replacements.keys())))
