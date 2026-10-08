#!/usr/bin/env python3
"""The Factory's knowledge from the command line: `wgf knowledge`, without the workflow engine.

    python3 scripts/wgf-knowledge.py validate | show [ID] | resolve ... | contract RUN_ID | table ...

See scripts/wgf_knowledge/cli.py and docs/knowledge-enforcement.md. Exit status: 0 clean;
1 problems found; 2 the command could not run. Standard library only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgf_knowledge.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
