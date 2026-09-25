"""The golden harness's always-on checks, for both golden games. No node, no browser.

The harness configuration, the frozen fixtures, the research -> G3 slice of the real
workflow steering to the right engine, the replay developer's mapping onto the template's
examples, the port overlays' static conformance, and the golden reviewer on a throwaway
repository. The overlays (examples/*/wgf-golden, examples/wgf-golden-shared) are read from
the pinned template checkout: the Factory holds no game source, and a pin that does not ship
them fails here.

Kept out of test_golden_2d/3d on purpose: those are the 2D/3D GOLDEN categories of
`wgf test-core`, and a category that passed only these fast checks would read as PASS
without the pipeline having run. The real runs are the WGF_GOLDEN=1 cases there.
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from golden.testing import fast_case  # noqa: E402

Golden2DFast = fast_case("2d")
Golden3DFast = fast_case("3d")


class GoldenTestingImports(unittest.TestCase):
    def test_it_imports_without_the_tests_directory_on_sys_path(self):
        """`python -m unittest scripts.tests.test_golden_2d` puts only the repository root
        on sys.path, not scripts/tests where testenv lives; golden.testing must find it."""
        scripts = os.path.dirname(HERE)
        code = (f"import sys; sys.path.insert(0, {scripts!r}); "
                f"assert not any(p.rstrip('/').endswith('tests') for p in sys.path), sys.path; "
                f"import golden.testing")
        done = subprocess.run([sys.executable, "-I", "-c", code], cwd=os.path.dirname(scripts),
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)

if __name__ == "__main__":
    unittest.main()
