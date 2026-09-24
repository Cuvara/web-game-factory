"""The golden harness's always-on checks, for both golden games. No node, no browser.

The harness configuration, the frozen fixtures, the research -> G3 slice of the real
workflow steering to the right engine, the replay developer's mapping onto the template's
examples, the port's static conformance, and the golden reviewer on a throwaway repository.

Kept out of test_golden_2d/3d on purpose: those are the 2D/3D GOLDEN categories of
`wgf test-core`, and a category that passed only these fast checks would read as PASS
without the pipeline having run. The real runs are the WGF_GOLDEN=1 cases there.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from golden.testing import fast_case  # noqa: E402

Golden2DFast = fast_case("2d")
Golden3DFast = fast_case("3d")

if __name__ == "__main__":
    unittest.main()
