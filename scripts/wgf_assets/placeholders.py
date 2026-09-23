"""Placeholder backends: stand-in assets so code is never blocked on art.

A backend turns a classified requirement into files. The pipeline tries backends in the
configured order and takes the first that is available, supports the kind and succeeds; a
backend that is missing, misconfigured or failing is recorded on the manifest and skipped,
never fatal. The procedural backend is always last and always works, which is what keeps the
pipeline independent of any optional generator.

    class MyBackend(PlaceholderBackend):
        id = "my-backend"
        kinds = {"sprite", "icon"}
        def probe(self): return True, None
        def generate(self, req): return Generated([GeneratedFile("png", data)], ...)

    register_backend("my-backend", lambda settings: MyBackend())

Register from a step module, then name it in `factory.assets.placeholders.backends`.
"""

import zlib
from collections import namedtuple

from . import encoders
from .policy import GENERATED_LICENSE

__all__ = [
    "PlaceholderBackend", "ProceduralBackend", "Generated", "GeneratedFile", "BackendError",
    "register_backend", "backend_factories", "build_backends", "FONT_STACK",
]

# `suffix` is appended to the asset id to form the file name: "" for the primary file,
# ".atlas" for a spritesheet's descriptor.
GeneratedFile = namedtuple("GeneratedFile", "format data suffix")
GeneratedFile.__new__.__defaults__ = ("",)


class Generated:
    def __init__(self, files, *, generator, license=None, reference=None, notes=None):
        self.files = list(files)
        self.generator = generator
        self.license = license
        self.reference = reference
        self.notes = notes


class BackendError(RuntimeError):
    """A backend could not produce an asset. The pipeline falls through to the next one."""


class PlaceholderBackend:
    id = None
    kinds = None  # None: every kind

    def supports(self, req):
        return self.kinds is None or req.kind in self.kinds

    def probe(self):
        """(available, note). Called once per execution, before any generate()."""
        return True, None

    def generate(self, req):  # pragma: no cover - interface
        raise NotImplementedError

    def close(self):
        pass


FONT_STACK = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans', sans-serif"


class ProceduralBackend(PlaceholderBackend):
    """Pure-Python placeholders for every kind: coloured PNGs, sine-tone WAVs, box GLBs,
    glTF materials, and a system font stack as a font's named fallback."""

    id = "procedural"

    def generate(self, req):
        kind = req.kind
        colour = encoders.colour_for(req.id)
        make = Generated
        if kind == "font":
            return make([], generator=self.id, license=GENERATED_LICENSE,
                        reference=FONT_STACK, notes="System font stack until a font is chosen.")
        if kind == "spritesheet":
            frames = int(req.frames or 4)
            frame_w, frame_h = req.size()
            image = encoders.png(frame_w * frames, frame_h, colour, frames=frames)
            atlas = encoders.atlas_json(f"{req.id}.placeholder.png", frame_w, frame_h,
                                        frames, req.id)
            return make([GeneratedFile("png", image), GeneratedFile("json", atlas, ".atlas")],
                        generator=self.id, license=GENERATED_LICENSE)
        if kind in ("sfx", "music"):
            seconds = 2.0 if kind == "music" else 0.2
            frequency = 220 + zlib.crc32(req.id.encode()) % 660
            return make([GeneratedFile("wav", encoders.wav(seconds, frequency))],
                        generator=self.id, license=GENERATED_LICENSE)
        if kind == "material":
            return make([GeneratedFile("json", encoders.material_json(req.id, colour))],
                        generator=self.id, license=GENERATED_LICENSE)
        if kind in ("model", "environment", "animation") and (
                kind != "animation" or req.dimension == "3d"):
            shape = "environment" if kind == "environment" else "box"
            data = encoders.glb(req.id, colour, shape=shape, animated=kind == "animation")
            return make([GeneratedFile("glb", data)], generator=self.id,
                        license=GENERATED_LICENSE)
        if kind == "animation":
            # A 2D animation is a spritesheet in all but name.
            frames = int(req.frames or 4)
            frame_w, frame_h = req.size()
            image = encoders.png(frame_w * frames, frame_h, colour, frames=frames)
            atlas = encoders.atlas_json(f"{req.id}.placeholder.png", frame_w, frame_h,
                                        frames, req.id)
            return make([GeneratedFile("png", image), GeneratedFile("json", atlas, ".atlas")],
                        generator=self.id, license=GENERATED_LICENSE)
        width, height = req.size()
        checker = 16 if kind == "texture" else 0
        return make([GeneratedFile("png", encoders.png(width, height, colour, checker=checker))],
                    generator=self.id, license=GENERATED_LICENSE)


_FACTORIES = {"procedural": lambda settings: ProceduralBackend()}


def register_backend(backend_id, factory):
    """`factory(settings)` returns a PlaceholderBackend. Settings are the backend's block
    under `factory.assets.placeholders.<id>`, or {}."""
    _FACTORIES[backend_id] = factory


def backend_factories():
    return dict(_FACTORIES)


def build_backends(order, settings):
    """[(id, backend or None, note)] in `order`, procedural appended if absent. An id with no
    registered factory is kept with a note, so the manifest shows it was asked for."""
    order = list(order or [])
    if "procedural" not in order:
        order.append("procedural")
    built = []
    for backend_id in order:
        factory = _FACTORIES.get(backend_id)
        if factory is None:
            built.append((backend_id, None, "no backend registered under this id"))
            continue
        try:
            built.append((backend_id, factory(dict(settings.get(backend_id) or {})), None))
        except Exception as exc:  # a broken optional backend must not break the pipeline
            built.append((backend_id, None, f"could not be constructed: {exc}"))
    return built
