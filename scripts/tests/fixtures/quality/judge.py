"""The quality-consistency suite's visual-qa judge: a command that reads the frames.

    python judge.py <frames_dir> <verdict>

It stands in for an agent able to read images, and judges only what pixels show - it is told
nothing about the build. Every frame staged under <frames_dir>/<viewport>/<frame>.png is
decoded; a frame in which a magenta missing-texture band and a black region the renderer
never drew into cover more than a tenth of the picture is a cropped, broken frame: a blocker
(`cropped-play`, category composition, route develop). Otherwise every rubric dimension
scores 4 and every state question is answered as a finished game answers it. The verdict
has the shape core/reference/visual-qa-rubric.yaml asks for, answered for every (state,
viewport) that has frames, exactly as wgf_visualqa.rubric parses it.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, SCRIPTS)

from wgf_assets.raster import decode_png  # noqa: E402
from wgf_visualqa.brief import frame_state  # noqa: E402
from wgf_visualqa.rubric import load_rubric, questions_for, state_ids  # noqa: E402


def broken(path):
    with open(path, "rb") as handle:
        image = decode_png(handle.read())
    px = image.pixels
    total = image.width * image.height
    magenta = black = 0
    for i in range(0, len(px), 4):
        r, g, b = px[i], px[i + 1], px[i + 2]
        if r > 240 and g < 20 and b > 240:
            magenta += 1
        elif r < 8 and g < 8 and b < 8:
            black += 1
    return magenta / float(total) > 0.02 and (magenta + black) / float(total) > 0.1


def main(frames_dir, verdict_path):
    rubric = load_rubric()
    frames, findings = [], []
    for viewport in sorted(os.listdir(frames_dir)):
        folder = os.path.join(frames_dir, viewport)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".png"):
                continue
            frame_id = name[:-4]
            state, _ = frame_state(frame_id)
            frames.append((viewport, frame_id, state))
            if broken(os.path.join(folder, name)):
                findings.append({"id": f"cropped-{viewport}-{frame_id}", "severity": "blocker",
                                 "category": "composition", "frame": f"{viewport}/{frame_id}",
                                 "summary": "the lower part of the play area is not drawn: a "
                                            "black band with a magenta missing-texture stripe",
                                 "route": "develop"})
    pairs = []
    for state in state_ids(rubric):
        for viewport in sorted({f[0] for f in frames}):
            if any(f[0] == viewport and f[2] == state for f in frames):
                pairs.append((state, viewport))
    states = []
    for state, viewport in pairs:
        answers = {}
        for question in questions_for(rubric, state):
            answers[question["id"]] = not question["fail_when"]
        states.append({"state": state, "viewport": viewport, "answers": answers,
                       "comment": "fixture judge"})
    scores = {name: 4 for name in rubric["dimensions"]}
    scores["no_debug"] = 5  # nothing a developer left on screen
    if findings:
        scores["composition"] = 1
    verdict = {"scores": scores, "findings": findings[:6], "states": states,
               "look": "finished-game",
               "look_reason": "fixture judge", "notes": "fixture judge"}
    with open(verdict_path, "w", encoding="utf-8") as handle:
        json.dump(verdict, handle)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
