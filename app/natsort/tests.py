# Tests for natural order sorting module.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 11, 2014
# URL: https://github.com/xolox/python-naturalsort

# Standard library modules.
import unittest

# The module we're testing.
from natsort import natsort

class NaturalSortTestCase(unittest.TestCase):

    def runTest(self):

      # This is plain old sorting (what we don't want).
      assert sorted(['1', '5', '10', '50']) == ['1', '10', '5', '50']

      # This is version sorting (what we're after).
      assert natsort(['1', '5', '10', '50']) == ['1', '5', '10', '50']

      # This is version sorting reversed.
      assert natsort(['1', '5', '10', '50'], reverse=True) == ['50', '10', '5', '1']

      # This covers a previously fixed bug. I've purposefully shuffled the
      # order on the left side to avoid false positives caused by stable
      # sorting.
      assert natsort(['1.5', '1.0']) == ['1.0', '1.5']
