"""The ASSETS module: turns a game design into an asset manifest and the files behind it.

    game-design ──► inspect ──► classify ──► existing? ──► library? ──► placeholder? ──► manifest
                    (requirements.py)        validate, licence, provenance     (placeholders.py,
                                             (pipeline.py, formats.py,          mcp.py)
                                              policy.py, library.py)
                                                         optimize (optimize.py)

Enable it in workspace/config/factory.yaml:

    factory:
      steps:
        modules: [wgf_assets]

What each asset kind may be and which licences may ship is core/reference/asset-policy.yaml.
The optional 2D asset MCP backend is in mcp.py; without it the procedural backend makes
every placeholder. A 3D requirement with a `model` spec is built headless by Blender
(blender.py, modelspec.py, blender_scripts/), and every GLB, whatever its source, is read and
checked by gltf.py. See docs/assets-module.md and docs/blender-pipeline.md.
"""

from .blender import BACKEND_ID as BLENDER_BACKEND_ID
from .blender import BlenderBackend
from .mcp import BACKEND_ID as MCP_BACKEND_ID
from .mcp import McpPlaceholderBackend
from .placeholders import register_backend
from .step import AssetsStep

__all__ = ["AssetsStep", "register"]

register_backend(MCP_BACKEND_ID, McpPlaceholderBackend)
register_backend(BLENDER_BACKEND_ID, BlenderBackend)


def register(registry):
    registry.register(AssetsStep.type, AssetsStep)
    return registry
