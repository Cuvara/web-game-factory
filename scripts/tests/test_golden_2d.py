"""2D GOLDEN: the real new-game pipeline, end to end, for Tower Merge Rush (PixiJS).

Runs only with WGF_GOLDEN=1 - the real pipeline with pnpm, Vite, Playwright and Chromium,
several minutes - and is SKIPPED otherwise, so `wgf test-core` reports 2D GOLDEN as SKIP
until someone actually runs it. A skip is never a pass. The always-on checks of the harness
(config, fixtures, steering, replay mapping, reviewer) are in test_golden_fast.py.
See docs/golden-runs.md.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from golden.testing import end_to_end_case  # noqa: E402

Golden2DEndToEnd = end_to_end_case("2d")

if __name__ == "__main__":
    unittest.main()
