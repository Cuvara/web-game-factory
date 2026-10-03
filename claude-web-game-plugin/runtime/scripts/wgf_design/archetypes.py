"""Genre archetypes: the offline design knowledge the default author starts from.

An archetype is a proven shape of web game at this scale - its loop, mechanics, controls,
starting tuning, content unit and asset list. It is a starting point the author fits to the
strategy (session length, platforms, exclusions), not a design in itself: the archetype
never decides monetization, locales or scope cuts - the strategy and the platform profiles
do.

Everything here is data. Selection reads the strategy's own words: first the archetype
`signature` - the terms that name its core mechanic (drop into a column, swap to match, steer
between walls) - against the strategy's concept (one-liner, core mechanic, core loop), then its
broader `keywords` against the whole strategy. A workflow can pin one with
`with: {archetype: <id>}`. Genre words alone ("merge", "puzzle", "3d") never decide it: two
archetypes of one genre can be different games, and the design must describe the game the
strategy approved (design-consistency rule `concept_mechanics_carried` checks it).

Tiers use the game-design vocabulary: mvp, post-mvp, optional.
"""

__all__ = ["ARCHETYPES", "CONTENT", "DEPTH", "EXPERIENCE", "FALLBACK", "dimension_of",
           "select", "drop_merge_top_level"]

import re

ARCHETYPES = {
    "lane-runner": {
        "label": "Lane runner",
        "keywords": ["runner", "run", "lane", "dodge", "endless", "rhythm", "beat", "dash", "surf"],
        "signature": ["lane", "lanes", "runner", "endless runner", "switch lane"],
        "dimension": "2d",
        "structure": "run",
        "camera": "Fixed, player anchored in the lower third, world scrolls toward the player.",
        "orientation": "portrait",
        "identity_affinity": ["neon-night", "riso-arcade", "signal-brutal"],
        "fantasy": "Moving faster than you think you can, and making it through anyway.",
        "core_loop": "Read the next obstacle -> switch lane in time -> survive and bank distance -> speed rises -> a miss ends the run -> retry at once.",
        "pillars": [
            "Readable at a glance on a phone held in one hand",
            "Every failure is the player's mistake, never the game's",
            "Back in a run within one second of failing",
        ],
        "run_seconds": 60,
        "first_reward_s": 20,
        "content_units": 3,
        "content_unit_kind": "run-segment",
        "genre": {"family": "arcade", "node": "lane-runner", "ending": "endless"},
        "difficulty_axes": ["speed", "density", "variety", "precision"],
        "mastery": {
            "model": "execution",
            "statement": "A better runner reads the row after the one in front and takes the "
                         "near-miss lane instead of the safe one, so the multiplier never "
                         "resets.",
            "signals": ["distance", "multiplier", "best"],
        },
        "retention_hooks": ["progression", "streak"],
        "return_reason": "I was so close to my best, and I know exactly what I did wrong.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "lane-switch", "name": "Lane switching", "tier": "mvp", "progression_role": "core",
             "description": "The player occupies one of three lanes and moves one lane per input.",
             "rules": ["Three lanes; the player starts in the middle one.",
                       "One input moves exactly one lane; inputs during a move are queued, at most one.",
                       "A lane move completes in 120 ms; the player is collidable in the destination lane from its midpoint."],
             "parameters": {"lanes": 3, "move_ms": 120, "input_queue": 1}},
            {"id": "obstacles", "name": "Obstacles", "tier": "mvp", "progression_role": "core",
             "description": "Obstacles spawn ahead in patterns drawn from obstacle sets and approach at the run speed.",
             "rules": ["At least one lane is always passable in every spawned row.",
                       "Contact with an obstacle ends the run.",
                       "Patterns come from the active obstacle set; sets unlock by elapsed run time."],
             "parameters": {"start_speed": 6.0, "row_gap_s": 1.1, "min_row_gap_s": 0.45}},
            {"id": "distance-score", "name": "Distance score", "tier": "mvp", "progression_role": "mastery",
             "description": "Score is distance travelled, with a multiplier for consecutive near-misses.",
             "rules": ["Score increases continuously with distance.",
                       "Passing an obstacle in an adjacent lane within 150 ms is a near-miss and adds 1 to the multiplier, max 5.",
                       "A lane change that is not a near-miss leaves the multiplier as it is; a run end resets it."],
             "parameters": {"max_multiplier": 5, "near_miss_ms": 150}},
            {"id": "pickups", "name": "Pickups", "tier": "post-mvp", "progression_role": "variation",
             "description": "Collectibles in lanes that add score and fill a short shield.",
             "rules": ["A pickup adds 50 points times the current multiplier.",
                       "Ten pickups grant a shield that absorbs one hit."],
             "parameters": {"pickup_points": 50, "shield_cost": 10}},
        ],
        "actions": [
            {"id": "move-left", "action": "Move one lane left", "tier": "mvp", "mechanic": "lane-switch",
             "touch": "Tap the left half of the screen, or swipe left", "mouse": "Click the left half",
             "keyboard": "Left arrow or A", "gamepad": "D-pad left"},
            {"id": "move-right", "action": "Move one lane right", "tier": "mvp", "mechanic": "lane-switch",
             "touch": "Tap the right half of the screen, or swipe right", "mouse": "Click the right half",
             "keyboard": "Right arrow or D", "gamepad": "D-pad right"},
        ],
        "goals": {
            "moment": "Get through the next row without touching anything.",
            "session": "Beat the personal best at least once.",
            "long_term": "Push the best distance into the next obstacle set.",
        },
        "progression_steps": [
            {"id": "set-2", "tier": "mvp", "unlock_condition": "Reach 30 seconds in one run",
             "grants": "Obstacle set 2 joins the pattern pool for the rest of that run"},
            {"id": "set-3", "tier": "mvp", "unlock_condition": "Reach 60 seconds in one run",
             "grants": "Obstacle set 3 joins the pattern pool"},
        ],
        "curve": [
            {"at": "0-20s", "description": "Forgiving opening: single-obstacle rows, slow speed, so a first-time player reaches a reward before failing.",
             "parameters": {"speed": 6.0, "row_gap_s": 1.1}},
            {"at": "20-60s", "description": "Two-obstacle rows appear; speed rises 3% every 5 seconds.",
             "parameters": {"speed_step": 0.03, "row_gap_s": 0.8}},
            {"at": "60s+", "description": "All sets active; speed caps so a skilled player can sustain the run.",
             "parameters": {"speed_cap": 12.0, "row_gap_s": 0.45}},
        ],
        "assist": "After three runs under 15 seconds, the first 20 seconds of the next run use the opening density again.",
        "failure_condition": "The player touches an obstacle.",
        "failure_feedback": "Hit-stop for 150 ms, screen shake, the obstacle flashes, then the result card slides up with distance and best.",
        "rewards": [
            {"id": "new-best", "tier": "mvp", "trigger": "Run ends above the personal best",
             "grants": "New personal best, saved", "feedback": "Best counter bursts and re-colours; a short fanfare."},
            {"id": "multiplier-up", "tier": "mvp", "trigger": "Near-miss",
             "grants": "Multiplier +1", "feedback": "Multiplier badge pulses; pitch of the pass sound rises with the multiplier."},
            {"id": "set-unlocked", "tier": "mvp", "trigger": "A new obstacle set joins mid-run",
             "grants": "Recognition of progress", "feedback": "A thin banner names the set; the background shifts hue."},
        ],
        "hud": [
            {"id": "score", "tier": "mvp", "shows": "Current distance score", "anchor": "top-center",
             "updates_on": "Every frame", "feedback": "Digits roll rather than jump"},
            {"id": "multiplier", "tier": "mvp", "shows": "Near-miss multiplier (hidden at x1)", "anchor": "top-right",
             "updates_on": "Near-miss and run end", "feedback": "Pulses on increase"},
            {"id": "best-marker", "tier": "mvp", "shows": "Personal best line crossing the track when reached", "anchor": "center",
             "updates_on": "When distance passes the best"},
        ],
        "tutorial": {
            "approach": "diegetic",
            "rationale": "The idiom is familiar; the first rows teach it without a single sentence.",
            "steps": [
                {"id": "first-row", "tier": "mvp", "trigger": "First run, first obstacle row",
                 "prompt": "Two pulsing hand icons on each half of the screen; the row blocks the player's lane",
                 "completes_on": "The player changes lane"},
                {"id": "both-ways", "tier": "mvp", "trigger": "First run, second row",
                 "prompt": "The row forces a move in the other direction",
                 "completes_on": "The player has moved both left and right"},
            ],
        },
        "assets": [
            {"id": "player", "type": "spritesheet", "tier": "mvp", "description": "Player character, run and hit frames",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Vector-drawn; 8 run frames, 2 hit frames, 128px",
             "role": "player", "dimension": "2d",
             "readability": "The runner as one solid silhouette in the identity's lead accent, facing up the track with a clear stride, readable at 64 px tall in the lower third against the moving track"},
            {"id": "obstacles", "type": "sprite", "tier": "mvp", "description": "Obstacle shapes, one per set",
             "count": 3, "source_preference": "procedural", "est_cost": 0, "spec": "Vector-drawn, lane-width, readable at 64px",
             "role": "threat", "dimension": "2d",
             "readability": "Each obstacle a hard-edged block filling its lane, outlined and darker than the track, never in the runner's colour: 'do not touch' at 64 px, a row ahead"},
            {"id": "track", "type": "texture", "tier": "mvp", "description": "Scrolling lane surface and parallax background",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Tileable 512px, 2 parallax layers",
             "role": "environment", "dimension": "2d",
             "readability": "Three lanes told apart at a glance by their edge lines; the surface stays low-contrast so the runner and the obstacles are the brightest things on screen"},
            {"id": "pickup", "type": "sprite", "tier": "post-mvp", "description": "Pickup collectible",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "64px, idle spin",
             "role": "collectible", "dimension": "2d",
             "readability": "A small bright token, round where obstacles are square, readable at 32 px and never mistaken for an obstacle"},
            {"id": "hit-vfx", "type": "vfx", "tier": "mvp", "description": "Hit burst and near-miss streak",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets",
             "role": "vfx", "dimension": "2d",
             "readability": "A burst at the point of contact for 150 ms that shows what was hit, then clears before the result card"},
        ],
        "audio": [
            {"id": "music-run", "type": "music", "tier": "mvp", "description": "One driving loop for the run",
             "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "sfx-move", "type": "sfx", "tier": "mvp", "description": "Lane move whoosh",
             "trigger": "Lane change", "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-near-miss", "type": "sfx", "tier": "mvp", "description": "Near-miss tick, pitch follows the multiplier",
             "trigger": "Near-miss", "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-hit", "type": "sfx", "tier": "mvp", "description": "Impact",
             "trigger": "Run ends", "loop": False, "source_preference": "library", "est_cost": 5},
        ],
        "post_mvp": [
            {"id": "second-biome", "name": "Second visual theme", "description": "A second palette and obstacle skin, unlocked by distance."},
        ],
        "optional": [
            {"id": "weekly-seed", "name": "Weekly seeded run", "description": "A fixed obstacle sequence everyone plays for a week."},
            {"id": "skins", "name": "Character skins", "description": "Cosmetic character variants."},
        ],
    },

    "drop-merge": {
        "label": "Drop-merge puzzle",
        "keywords": ["drop", "merge", "column", "columns", "track", "tower", "stack", "2048", "cascade", "puzzle"],
        "signature": ["drop", "column", "columns", "track"],
        "dimension": "2d",
        "structure": "run",
        "camera": "Fixed, the seven-column track centred, no scrolling.",
        "orientation": "portrait",
        "identity_affinity": ["paper-diorama", "riso-arcade", "lacquer-brass"],
        "fantasy": "Turning a crowded track into one tall tower with a chain of merges you saw coming.",
        "core_loop": "Pick a column -> drop the next piece there -> equal neighbours merge and cascade for points -> the next piece's level ramps up -> the track fills -> a full track ends the run -> retry for a higher score.",
        "pillars": [
            "One tap, one column: the player can always predict where a piece lands",
            "Cascades are the reward, and they are loud",
            "Back in a run within one second of the track filling",
        ],
        "run_seconds": 90,
        "first_reward_s": 10,
        "content_units": 4,
        "content_unit_kind": "run-segment",
        "genre": {"family": "arcade", "node": "arcade", "ending": "endless"},
        "difficulty_axes": ["speed", "density", "variety", "precision"],
        "mastery": {
            "model": "execution",
            "statement": "A better player keeps one column free for the piece level that is "
                         "coming rather than the one in hand, so a cascade is always available.",
            "signals": ["score", "best"],
        },
        "retention_hooks": ["progression", "streak"],
        "return_reason": "I saw the cascade that would have saved that track, and I want to set it up again.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "track", "name": "Seven-column track", "tier": "mvp", "progression_role": "core",
             "description": "A single row of seven column cells; each cell is empty or holds one numbered tower piece.",
             "rules": ["The track has seven columns and one row; a column holds at most one piece.",
                       "A tower piece shows its level as a numeral and as a size or shape, never by colour alone.",
                       "A new run starts with an empty track."],
             "parameters": {"columns": 7}},
            {"id": "drop", "name": "Drop a piece", "tier": "mvp", "progression_role": "core",
             "description": "The player drops the next numbered piece into the column they choose with one tap.",
             "rules": ["The next piece's level is shown before it is dropped.",
                       "A drop lands in the chosen column only if that column is empty; a drop onto a full column is refused and costs nothing.",
                       "Every drop is resolved (merges and cascades) before the next drop is accepted."]},
            {"id": "merge-cascade", "name": "Merge and cascade", "tier": "mvp", "progression_role": "core",
             "description": "Two horizontally adjacent pieces of the same level merge into one piece of the next level, and the merge cascades.",
             "rules": ["Equal adjacent pieces merge into one piece of level + 1 in the left cell; the right cell empties.",
                       "After a merge, pieces slide left to close the gap, so a newly adjacent equal pair merges too; this repeats until no pair is left.",
                       "Each merge scores the level it produced."],
             "parameters": {"score_per_merge": "the merged level"}},
            {"id": "drop-ramp", "name": "Drop-level ramp", "tier": "mvp", "progression_role": "introduced",
             "description": "The level of the next piece rises with the number of merges made, so the track fills faster over time.",
             "rules": ["The next piece's level is 1 + floor(merges / 4), capped at 4.",
                       "The ramp is data-driven: one table, no hand-built levels."],
             "parameters": {"merges_per_level_up": 4, "max_drop_level": 4}},
            {"id": "full-track", "name": "Full track ends the run", "tier": "mvp", "progression_role": "core",
             "description": "The run ends when every column holds a piece and no merge is left.",
             "rules": ["When no column is empty after a drop resolves, the run is over.",
                       "The final score and the personal best are shown on the result card."]},
        ],
        "actions": [
            {"id": "drop", "action": "Drop the next piece into a column", "tier": "mvp", "mechanic": "drop",
             "touch": "Tap a column", "mouse": "Click a column",
             "keyboard": "Keys 1-7 drop into that column; Space or Enter drops into the first empty column",
             "gamepad": "D-pad picks a column, A drops"},
        ],
        "goals": {
            "moment": "Drop the piece where it starts a cascade.",
            "session": "Beat the personal best at least once.",
            "long_term": "Keep a run going until the drop ramp reaches its top level.",
        },
        "progression_steps": [
            {"id": "ramp-2", "tier": "mvp", "unlock_condition": "4 merges in one run", "grants": "Level-2 pieces join the drops"},
            {"id": "ramp-3", "tier": "mvp", "unlock_condition": "8 merges in one run", "grants": "Level-3 pieces join the drops"},
            {"id": "ramp-4", "tier": "mvp", "unlock_condition": "12 merges in one run", "grants": "Level-4 pieces, the top of the ramp"},
        ],
        "curve": [
            {"at": "Merges 0-3", "description": "Level-1 drops only; almost every drop can merge, so a first-time player sees a cascade before the track fills.",
             "parameters": {"drop_level": 1}},
            {"at": "Merges 4-11", "description": "Drop level rises by one every four merges; the track fills faster.",
             "parameters": {"merges_per_level_up": 4}},
            {"at": "Merges 12+", "description": "Drop level held at its cap of 4; only planning keeps the track open.",
             "parameters": {"max_drop_level": 4}},
        ],
        "assist": "After three runs that end before the first merge, the next run's first three drops are level 1.",
        "failure_condition": "Every column holds a piece and no merge is left.",
        "failure_feedback": "The full track flashes, the last piece shakes, and the result card shows score, merges and the best.",
        "rewards": [
            {"id": "merge", "tier": "mvp", "trigger": "A merge", "grants": "Score equal to the merged level",
             "feedback": "The merged piece pops up a size; the score rolls up."},
            {"id": "cascade", "tier": "mvp", "trigger": "Two or more merges from one drop",
             "grants": "The cascade's merges all score", "feedback": "Each cascade step raises pitch; a word stamps on screen."},
            {"id": "new-best", "tier": "mvp", "trigger": "Run ends above the personal best", "grants": "New best, saved",
             "feedback": "Best counter bursts; fanfare."},
        ],
        "hud": [
            {"id": "score", "tier": "mvp", "shows": "Score", "anchor": "top-center", "updates_on": "Each merge",
             "feedback": "Rolls up"},
            {"id": "next-piece", "tier": "mvp", "shows": "Level of the next piece to drop", "anchor": "top-right",
             "updates_on": "Each drop", "feedback": "Grows when the ramp raises the level"},
            {"id": "best", "tier": "mvp", "shows": "Personal best", "anchor": "top-left", "updates_on": "Run start and new best"},
        ],
        "tutorial": {
            "approach": "diegetic",
            "rationale": "Tap-a-column is self-explanatory once the columns read as targets; the first merge teaches the rest.",
            "steps": [
                {"id": "first-drop", "tier": "mvp", "trigger": "First run, first drop",
                 "prompt": "The columns pulse and a hand taps one",
                 "completes_on": "The first drop"},
                {"id": "first-merge", "tier": "mvp", "trigger": "First run, second drop",
                 "prompt": "The column beside the first piece glows: drop there to merge",
                 "completes_on": "The first merge"},
            ],
        },
        "assets": [
            {"id": "pieces", "type": "sprite", "tier": "mvp", "description": "Tower pieces, one per level, with a merge state",
             # One drawing per level the rules reach: derived below from the mechanics'
             # parameters (drop_merge_top_level), never a fixed number.
             "count": None, "source_preference": "procedural", "est_cost": 0, "spec": "Vector, 96px, level readable by numeral and size",
             "role": "target", "dimension": "2d",
             "readability": "Each level a distinct size and silhouette with its numeral, never told apart by colour alone; the numeral legible at 48 px on a phone, the next level obviously bigger"},
            {"id": "track-frame", "type": "ui", "tier": "mvp", "description": "Track frame and column backing",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "9-slice",
             "role": "environment", "dimension": "2d",
             "readability": "Seven column slots that read as seven places to drop; an empty slot obviously empty, a full one obviously taken"},
            {"id": "merge-vfx", "type": "vfx", "tier": "mvp", "description": "Merge burst and cascade streak",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets",
             "role": "vfx", "dimension": "2d",
             "readability": "A burst where two pieces became one, and a streak along a cascade, so the player sees which merge scored"},
            {"id": "backdrop", "type": "texture", "tier": "mvp", "description": "Background behind the track",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Gradient plus texture overlay",
             "role": "background", "dimension": "2d",
             "readability": "A quiet ground behind the track, lower in contrast than the track frame so the pieces lead"},
        ],
        "audio": [
            {"id": "music-loop", "type": "music", "tier": "mvp",
             "description": "Bright, playful play loop of at least 60 s, seamless",
             "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "music-title", "type": "music", "tier": "mvp",
             "description": "Calmer title variant of the play loop, at least 30 s, seamless",
             "trigger": "Title screen; crossfades to the play loop on the first drop", "loop": True,
             "source_preference": "library", "est_cost": 40},
            {"id": "sfx-drop", "type": "sfx", "tier": "mvp", "description": "Piece drop thunk", "trigger": "Drop",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-merge", "type": "sfx", "tier": "mvp", "description": "Merge pop, pitched per cascade step",
             "trigger": "Merge", "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-combo", "type": "sfx", "tier": "mvp", "description": "Cascade stinger, rising with its length",
             "trigger": "Cascade of two or more merges", "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-game-over", "type": "sfx", "tier": "mvp", "description": "Game-over sting; the music ducks under it",
             "trigger": "Run ends", "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-reward", "type": "sfx", "tier": "mvp", "description": "Reward chime",
             "trigger": "Rewarded placement granted", "loop": False, "source_preference": "library", "est_cost": 5},
        ],
        "post_mvp": [
            {"id": "next-two", "name": "Two-piece preview", "description": "Show the next two pieces instead of one."},
        ],
        "optional": [
            {"id": "piece-skins", "name": "Piece skins", "description": "Cosmetic tower skins unlocked by best score."},
        ],
    },

    "merge-puzzle": {
        "label": "Grid puzzle",
        "keywords": ["puzzle", "match", "merge", "tile", "block", "grid", "swap", "sort", "connect", "board"],
        "signature": ["swap", "match", "match-3", "grid", "board", "tile", "tiles"],
        "dimension": "2d",
        "structure": "level",
        "camera": "Fixed, board centred, no scrolling.",
        "orientation": "portrait",
        "identity_affinity": ["paper-diorama", "riso-arcade", "lacquer-brass"],
        "fantasy": "Seeing the move nobody else would, and watching the board collapse because of it.",
        "core_loop": "Scan the board -> make a move -> pieces resolve and cascade -> the goal counter falls -> clear the level -> the next board raises the goal.",
        "pillars": [
            "One move is always legible: the player can predict what it will do",
            "Cascades are the reward, and they are loud",
            "A level fits inside one bus stop",
        ],
        "run_seconds": 90,
        "first_reward_s": 25,
        "content_units": 20,
        "content_unit_kind": "level",
        "genre": {"family": "puzzle", "node": "match-3", "ending": "finite"},
        "difficulty_axes": ["depth", "move-limit", "board-complexity", "piece-variety"],
        "mastery": {
            "model": "reading",
            "statement": "A better player reads the cascade a move will start before making "
                         "it, so the goal counters fall in fewer moves than the budget allows.",
            "signals": ["moves", "goal-counters", "level"],
        },
        "retention_hooks": ["progression", "collection"],
        "return_reason": "There is a next level waiting and the last one ended on a good cascade.",
        "progression_model": "linear-levels",
        "difficulty_model": "level-authored",
        "mechanics": [
            {"id": "board", "name": "Board", "tier": "mvp", "progression_role": "core",
             "description": "A 7x7 grid of pieces in five colours.",
             "rules": ["The board is 7x7; every cell holds one piece.",
                       "A new board never starts with a resolvable group already on it.",
                       "If no move exists, the board reshuffles with a visible animation and no penalty."],
             "parameters": {"cols": 7, "rows": 7, "colours": 5}},
            {"id": "swap-resolve", "name": "Swap and resolve", "tier": "mvp", "progression_role": "core",
             "description": "Swapping two adjacent pieces resolves lines of three or more of one colour.",
             "rules": ["Only orthogonally adjacent pieces swap.",
                       "A swap that forms no line of three reverts and does not cost a move.",
                       "Resolved pieces clear, pieces above fall, new pieces fill from the top; new lines resolve as cascades."],
             "parameters": {"min_line": 3, "fall_ms": 180}},
            {"id": "level-goal", "name": "Level goal", "tier": "mvp", "progression_role": "core",
             "description": "Each level asks for a number of pieces of given colours within a move limit.",
             "rules": ["Clearing a goal colour decrements its counter.",
                       "All counters at zero clears the level; remaining moves become bonus score.",
                       "Moves at zero with counters left fails the level."],
             "parameters": {"moves_level_1": 20, "moves_min": 12}},
            {"id": "special-pieces", "name": "Special pieces", "tier": "post-mvp", "progression_role": "variation",
             "description": "A line of four makes a row-clearer; an L or T of five makes a bomb.",
             "rules": ["Line of four creates a row-clearer at the swap cell.",
                       "L or T shape creates a 3x3 bomb."]},
        ],
        "actions": [
            {"id": "swap", "action": "Swap two adjacent pieces", "tier": "mvp", "mechanic": "swap-resolve",
             "touch": "Drag a piece onto a neighbour, or tap one then the other", "mouse": "Drag, or click one then the other",
             "keyboard": "Arrows move the cursor, Space selects, arrow swaps", "gamepad": "D-pad cursor, A select"},
        ],
        "goals": {
            "moment": "Find a swap that clears a goal colour.",
            "session": "Clear two or three levels.",
            "long_term": "Clear every level in the set.",
        },
        "progression_steps": [
            {"id": "levels-1-4", "tier": "mvp", "unlock_condition": "Available from the start", "grants": "Levels 1-4, one goal colour"},
            {"id": "levels-5-8", "tier": "mvp", "unlock_condition": "Clear level 4", "grants": "Two goal colours per level"},
            {"id": "levels-9-12", "tier": "mvp", "unlock_condition": "Clear level 8", "grants": "Tighter move limits"},
        ],
        "curve": [
            {"at": "Levels 1-2", "description": "Generous moves, one colour; cannot realistically be failed.", "parameters": {"moves": 20, "goal": 12}},
            {"at": "Levels 3-8", "description": "Second goal colour; moves tighten by one per level.", "parameters": {"moves": 18, "goal": 18}},
            {"at": "Levels 9-12", "description": "Move limits at their tightest; the last level of each four is a spike followed by a relief level.", "parameters": {"moves": 14, "goal": 24}},
        ],
        "assist": "After two fails on one level, the next attempt starts with three extra moves.",
        "failure_condition": "Moves reach zero with goal counters remaining.",
        "failure_feedback": "The board dims, remaining counters shake, and the fail card shows how close the player was.",
        "rewards": [
            {"id": "cascade", "tier": "mvp", "trigger": "Two or more cascades from one move",
             "grants": "Cascade bonus score", "feedback": "Each cascade step raises pitch; a word ('Nice', 'Great', 'Superb') stamps on screen."},
            {"id": "level-clear", "tier": "mvp", "trigger": "All goal counters reach zero",
             "grants": "Level cleared, 1-3 stars by remaining moves", "feedback": "Stars stamp in one by one with a chord."},
            {"id": "set-complete", "tier": "post-mvp", "trigger": "Clear levels 4, 8 and 12",
             "grants": "Collection card", "feedback": "Card flips into the collection."},
        ],
        "hud": [
            {"id": "moves", "tier": "mvp", "shows": "Moves remaining", "anchor": "top-left",
             "updates_on": "Each valid swap", "feedback": "Turns the danger colour at 3"},
            {"id": "goals", "tier": "mvp", "shows": "Goal counters per colour", "anchor": "top-center",
             "updates_on": "Each clear", "feedback": "Counter ticks down with a pop"},
            {"id": "level", "tier": "mvp", "shows": "Level number", "anchor": "top-right", "updates_on": "Level start"},
        ],
        "tutorial": {
            "approach": "guided-first-run",
            "rationale": "The swap rule is one sentence, but showing it once removes the only real barrier.",
            "steps": [
                {"id": "first-swap", "tier": "mvp", "trigger": "Level 1 start, first time",
                 "prompt": "A hand drags one highlighted piece onto its neighbour; the rest of the board is dimmed",
                 "completes_on": "The player makes that swap"},
                {"id": "goal-pointer", "tier": "mvp", "trigger": "After the first clear",
                 "prompt": "The goal counter pulses as it ticks down",
                 "completes_on": "Automatically after 1.5 s"},
            ],
        },
        "assets": [
            {"id": "pieces", "type": "sprite", "tier": "mvp", "description": "Five piece colours with idle and clear states",
             "count": 5, "source_preference": "procedural", "est_cost": 0, "spec": "Vector, 96px, distinct by shape as well as colour",
             "role": "target", "dimension": "2d",
             "readability": "Five pieces distinct by shape as well as colour, each recognisable at 40 px in a full board, the goal colours matching the goal counters' icons"},
            {"id": "board-frame", "type": "ui", "tier": "mvp", "description": "Board frame and cell backing",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "9-slice",
             "role": "environment", "dimension": "2d",
             "readability": "A board whose cells are plainly a grid, with the cell backing quieter than every piece"},
            {"id": "clear-vfx", "type": "vfx", "tier": "mvp", "description": "Piece clear burst and cascade streak",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets",
             "role": "vfx", "dimension": "2d",
             "readability": "A burst on each cleared cell and a streak along a cascade, readable without hiding the pieces falling in"},
            {"id": "specials", "type": "sprite", "tier": "post-mvp", "description": "Row-clearer and bomb pieces",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Vector, 96px",
             "role": "target", "dimension": "2d",
             "readability": "Row-clearer and bomb told apart from ordinary pieces by an unmistakable mark at 40 px"},
            {"id": "backdrop", "type": "texture", "tier": "mvp", "description": "Background behind the board",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Gradient plus texture overlay",
             "role": "background", "dimension": "2d",
             "readability": "A quiet ground behind the board, lower in contrast than the board so the pieces lead"},
        ],
        "audio": [
            {"id": "music-calm", "type": "music", "tier": "mvp", "description": "Unhurried loop under play",
             "trigger": "Level start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "sfx-swap", "type": "sfx", "tier": "mvp", "description": "Swap click", "trigger": "Swap",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-clear", "type": "sfx", "tier": "mvp", "description": "Clear pop, pitched per cascade step",
             "trigger": "Clear", "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-stars", "type": "sfx", "tier": "mvp", "description": "Star stamp chord", "trigger": "Level clear",
             "loop": False, "source_preference": "library", "est_cost": 5},
        ],
        "post_mvp": [
            {"id": "level-set-2", "name": "Second level set", "description": "Levels 13-24 with blockers."},
        ],
        "optional": [
            {"id": "collection-cards", "name": "Collection cards", "description": "A card per completed set of four levels."},
            {"id": "blockers", "name": "Board blockers", "description": "Ice and crate cells that need adjacent clears."},
        ],
    },

    "arena-dodge": {
        "label": "3D arena dodger",
        "keywords": ["3d", "three-dimensional", "arena", "drive", "driving", "dodge", "dodger", "walls", "wall", "obstacle", "obstacles", "steer", "endless", "neon"],
        "signature": ["wall", "walls", "dodge", "dodger", "steer between", "rush toward", "obstacle", "obstacles"],
        "dimension": "3d",
        "structure": "run",
        "camera": "Third-person chase camera, slightly high, locked behind the craft; no player camera control.",
        "orientation": "landscape",
        "identity_affinity": ["neon-night", "signal-brutal", "solar-bleach"],
        "fantasy": "Threading a gap at a speed that should not be survivable.",
        "core_loop": "Drive into the arena -> walls rush toward the craft -> steer between them -> score climbs with time and every wall cleared -> the walls speed up -> a crash ends the run -> drive again at once.",
        "pillars": [
            "The gap is always readable before it arrives",
            "Every crash is the player's mistake, never the camera's",
            "Back in a run within one second of crashing",
        ],
        "run_seconds": 60,
        "first_reward_s": 10,
        "content_units": 3,
        "content_unit_kind": "run-segment",
        "genre": {"family": "arcade", "node": "arcade", "ending": "endless"},
        "difficulty_axes": ["speed", "density", "variety", "precision"],
        "mastery": {
            "model": "execution",
            "statement": "A better pilot picks the gap while the wall is still far away and "
                         "arrives already lined up, instead of steering at the last moment.",
            "signals": ["score", "best"],
        },
        "retention_hooks": ["progression", "streak"],
        "return_reason": "I know I can hold the line through one more speed-up.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "steering", "name": "Steering", "tier": "mvp", "progression_role": "core",
             "description": "The craft drives forward on its own; the player steers it left and right across the arena.",
             "rules": ["The craft slides sideways at a fixed steer speed and cannot leave the arena's width.",
                       "Forward speed is never player-controlled; the walls' speed carries the drive."],
             "parameters": {"arena_half_width": 4, "steer_speed": 6}},
            {"id": "walls", "name": "Rushing walls", "tier": "mvp", "progression_role": "core",
             "description": "Walls spawn ahead and rush toward the craft; the player steers between them.",
             "rules": ["Walls spawn at a fixed distance ahead at a fixed interval and move toward the craft.",
                       "Every wall row leaves a gap the craft can pass through.",
                       "A wall that passes the craft without a hit counts as cleared."],
             "parameters": {"spawn_interval_s": 0.9, "spawn_distance": 40}},
            {"id": "crash", "name": "Crash ends the run", "tier": "mvp", "progression_role": "core",
             "description": "Hitting a wall is a crash, and a crash ends the run.",
             "rules": ["Any overlap of the craft with a wall is a crash.",
                       "The result card shows the score and the personal best."]},
            {"id": "speed-ramp", "name": "Speed ramp and score", "tier": "mvp", "progression_role": "mastery",
             "description": "The walls speed up the longer the drive lasts; score climbs with time survived and every wall cleared.",
             "rules": ["Wall speed starts at 8 arena units per second and rises by 0.35 every second survived.",
                       "Score rises 10 per second survived plus 5 per wall cleared."],
             "parameters": {"base_speed": 8, "speed_ramp_per_s": 0.35, "points_per_s": 10, "points_per_wall": 5}},
        ],
        "actions": [
            {"id": "steer", "action": "Steer left or right", "tier": "mvp", "mechanic": "steering",
             "touch": "Hold and drag: the craft follows the finger's horizontal position",
             "mouse": "The craft follows the pointer's horizontal position",
             "keyboard": "Left/Right arrows or A/D", "gamepad": "Left stick"},
        ],
        "goals": {
            "moment": "Line up for the next gap.",
            "session": "Beat the personal best.",
            "long_term": "Survive into the third speed tier.",
        },
        "progression_steps": [
            {"id": "tier-2", "tier": "mvp", "unlock_condition": "Survive 20 s in one run", "grants": "Speed tier 2 and its palette"},
            {"id": "tier-3", "tier": "mvp", "unlock_condition": "Survive 45 s in one run", "grants": "Speed tier 3 and its palette"},
        ],
        "curve": [
            {"at": "0-15 s", "description": "Slow walls and wide gaps, so a first-time player clears walls before crashing.",
             "parameters": {"speed": 8}},
            {"at": "15-45 s", "description": "Walls speed up 0.35 units per second each second.",
             "parameters": {"speed_ramp_per_s": 0.35}},
            {"at": "45 s+", "description": "The ramp continues; only reading gaps early keeps the run alive.",
             "parameters": {}},
        ],
        "assist": "After three runs under 10 s, the next run's first 10 s use the opening speed.",
        "failure_condition": "The craft crashes into a wall.",
        "failure_feedback": "Hit-stop for 150 ms, the wall flashes, the camera pulls up, then the result card with score and best.",
        "rewards": [
            {"id": "wall-cleared", "tier": "mvp", "trigger": "A wall passes the craft without a hit", "grants": "Score +5",
             "feedback": "The wall's edge flashes as it passes; a short whoosh."},
            {"id": "tier-up", "tier": "mvp", "trigger": "Speed tier changes", "grants": "New palette",
             "feedback": "The arena's neon shifts hue; a riser."},
            {"id": "new-best", "tier": "mvp", "trigger": "Run ends above the personal best", "grants": "New best, saved",
             "feedback": "Best counter bursts."},
        ],
        "hud": [
            {"id": "score", "tier": "mvp", "shows": "Score", "anchor": "top-center", "updates_on": "Every frame",
             "feedback": "Digits roll rather than jump"},
            {"id": "best", "tier": "mvp", "shows": "Personal best", "anchor": "top-left", "updates_on": "Run start and new best"},
        ],
        "tutorial": {
            "approach": "guided-first-run",
            "rationale": "Steering is one idea; the first wall shows it once.",
            "steps": [
                {"id": "steer-prompt", "tier": "mvp", "trigger": "First run start",
                 "prompt": "Left and right arrows glow; the first wall's gap sits off to one side",
                 "completes_on": "The player clears the first wall"},
            ],
        },
        "assets": [
            {"id": "craft", "type": "model", "tier": "mvp", "description": "Player craft",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Low-poly GLB built from a model spec: hull, canopy, two fins, engine glow; 800-3k triangles, flat-shaded",
             "role": "player", "dimension": "3d",
             "readability": "A craft with a hull, canopy and fins and a glowing engine at the back, its nose plainly pointing down the arena: readable at 80 px wide from the chase camera, and never the walls' colour"},
            {"id": "arena-kit", "type": "model", "tier": "mvp", "description": "Arena floor and side rails",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Low-poly GLB modules built from a model spec: floor tile with lane lines, side rail; vertex colours",
             "role": "environment", "dimension": "3d",
             "readability": "A floor whose lines run toward the horizon so speed reads, and side rails that mark the arena's edge; both dimmer than the craft and the walls"},
            {"id": "wall", "type": "model", "tier": "mvp", "description": "Neon wall segment",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Low-poly GLB built from a model spec: framed panel with emissive strips; under 1k triangles",
             "role": "threat", "dimension": "3d",
             "readability": "A wall panel with a lit frame and emissive strips, its gap obvious from 40 units away: 'do not touch' before it arrives, in the identity's warning colour"},
            {"id": "crash-vfx", "type": "vfx", "tier": "mvp", "description": "Crash burst",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Instanced particles",
             "role": "vfx", "dimension": "3d",
             "readability": "A burst at the point of contact that shows where the craft hit, gone before the result card"},
            {"id": "sky", "type": "texture", "tier": "mvp", "description": "Gradient sky behind the arena",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Shader gradient, no texture fetch",
             "role": "background", "dimension": "3d",
             "readability": "A gradient sky that sets the horizon, darker than the walls so every wall stands out against it"},
        ],
        "audio": [
            {"id": "music-drive", "type": "music", "tier": "mvp",
             "description": "Driving loop of at least 60 s, seamless; its intensity rises with speed",
             "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "music-drive-layer", "type": "music", "tier": "mvp",
             "description": "Intensity layer of the driving loop, at least 60 s, same length, faded in with speed",
             "trigger": "Run start, in lock-step with music-drive", "loop": True,
             "source_preference": "library", "est_cost": 20},
            {"id": "music-title", "type": "music", "tier": "mvp",
             "description": "Calmer title variant of the driving loop, at least 30 s, seamless",
             "trigger": "Title screen; crossfades to the driving loop on run start", "loop": True,
             "source_preference": "library", "est_cost": 40},
            {"id": "sfx-engine", "type": "sfx", "tier": "mvp",
             "description": "Engine hum loop; pitch follows speed, filter and pan follow steering",
             "trigger": "During a run", "loop": True, "source_preference": "procedural", "est_cost": 0},
            {"id": "sfx-pass", "type": "sfx", "tier": "mvp", "description": "Wall pass whoosh", "trigger": "Wall cleared",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-near-miss", "type": "sfx", "tier": "mvp", "description": "Near-miss whoosh",
             "trigger": "A wall passes with little room to spare", "loop": False,
             "source_preference": "library", "est_cost": 5},
            {"id": "sfx-crash", "type": "sfx", "tier": "mvp", "description": "Crash impact", "trigger": "Crash",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-game-over", "type": "sfx", "tier": "mvp", "description": "Game-over sting; the music ducks under it",
             "trigger": "Run ends, after the crash", "loop": False, "source_preference": "library", "est_cost": 5},
        ],
        "post_mvp": [
            {"id": "moving-gaps", "name": "Moving gaps", "description": "Wall rows whose gap slides while they approach."},
        ],
        "optional": [
            {"id": "craft-variants", "name": "Craft variants", "description": "Cosmetic crafts unlocked by best score."},
        ],
    },

    "arena-3d": {
        "label": "3D arena",
        "keywords": ["3d", "three-dimensional", "arena", "drive", "driving", "racing", "race", "flight", "fly", "voxel", "drift", "kart", "physics"],
        "signature": ["gate", "gates", "checkpoint", "checkpoints", "time trial", "lap", "race", "racing", "clock"],
        "dimension": "3d",
        "structure": "run",
        "camera": "Third-person chase camera, slightly high, locked behind the player; no player camera control.",
        "orientation": "landscape",
        "identity_affinity": ["solar-bleach", "signal-brutal", "neon-night"],
        "fantasy": "Throwing something heavy through space with total control.",
        "core_loop": "Steer through the arena -> hit targets in sequence -> the clock extends -> the course tightens -> the clock runs out -> retry to beat the time.",
        "pillars": [
            "The camera never fights the player",
            "Physics you can predict after one try",
            "Loads in under five seconds on a mid-range phone",
        ],
        "run_seconds": 75,
        "first_reward_s": 15,
        "content_units": 3,
        "content_unit_kind": "round",
        "genre": {"family": "arcade", "node": "arcade", "ending": "endless"},
        "difficulty_axes": ["speed", "density", "variety", "precision"],
        "mastery": {
            "model": "execution",
            "statement": "A better pilot takes the gates in a line that sets up the next one, "
                         "so the clock is extended before it ever looks short.",
            "signals": ["time", "gates"],
        },
        "retention_hooks": ["progression", "collection"],
        "return_reason": "I know a faster line through the second arena.",
        "progression_model": "unlock-track",
        "difficulty_model": "level-authored",
        "mechanics": [
            {"id": "steering", "name": "Steering", "tier": "mvp", "progression_role": "core",
             "description": "The player vehicle accelerates automatically; the player only steers.",
             "rules": ["Forward speed ramps to max in 1.5 s and is never player-controlled in the MVP.",
                       "Steering input maps to yaw rate, not to position.",
                       "Touching the arena edge bounces the vehicle and removes 30% of speed; it never ends the run."],
             "parameters": {"max_speed": 22.0, "yaw_rate_deg_s": 140, "wall_speed_loss": 0.3}},
            {"id": "checkpoints", "name": "Target gates", "tier": "mvp", "progression_role": "core",
             "description": "Gates light up one at a time; the round is a race against the clock, and passing the lit gate extends it.",
             "rules": ["Exactly one gate is lit; passing it lights the next.",
                       "Each lit gate passed adds time to the clock.",
                       "The run ends when the clock reaches zero."],
             "parameters": {"start_clock_s": 20, "gate_bonus_s": 4}},
            {"id": "boost", "name": "Boost pads", "tier": "post-mvp", "progression_role": "variation",
             "description": "Pads on the floor that add a short speed burst.",
             "rules": ["Boost adds 40% speed for 1.2 s."],
             "parameters": {"boost": 0.4, "boost_s": 1.2}},
        ],
        "actions": [
            {"id": "steer", "action": "Steer left or right", "tier": "mvp", "mechanic": "steering",
             "touch": "Hold left or right half of the screen", "mouse": "Move pointer left/right of centre",
             "keyboard": "Left/Right arrows or A/D", "gamepad": "Left stick"},
        ],
        "goals": {
            "moment": "Line up for the next lit gate.",
            "session": "Unlock the next arena.",
            "long_term": "Beat the target time in every arena.",
        },
        "progression_steps": [
            {"id": "arena-2", "tier": "mvp", "unlock_condition": "Pass 10 gates in arena 1", "grants": "Arena 2"},
            {"id": "arena-3", "tier": "mvp", "unlock_condition": "Pass 12 gates in arena 2", "grants": "Arena 3"},
        ],
        "curve": [
            {"at": "Arena 1", "description": "Wide, open; gates close together.", "parameters": {"gate_spacing_m": 30}},
            {"at": "Arena 2", "description": "Pillars between gates; bonus time shrinks.", "parameters": {"gate_bonus_s": 3.5}},
            {"at": "Arena 3", "description": "Narrow lanes and sharp turns.", "parameters": {"gate_bonus_s": 3}},
        ],
        "assist": "After three runs under 5 gates, the next run starts with +5 s on the clock.",
        "failure_condition": "The clock reaches zero.",
        "failure_feedback": "Slow motion for one second, camera pulls up, the result card shows gates passed against the best.",
        "rewards": [
            {"id": "gate-pass", "tier": "mvp", "trigger": "Pass the lit gate", "grants": "Clock time",
             "feedback": "Gate shatters into light; the clock flashes the added seconds."},
            {"id": "arena-unlock", "tier": "mvp", "trigger": "Unlock condition met", "grants": "Next arena",
             "feedback": "Arena card slides in on the result screen."},
            {"id": "new-best", "tier": "mvp", "trigger": "Run ends above the arena best", "grants": "New best, saved",
             "feedback": "Best counter bursts."},
        ],
        "hud": [
            {"id": "clock", "tier": "mvp", "shows": "Remaining time", "anchor": "top-center",
             "updates_on": "Every frame", "feedback": "Turns the danger colour under 5 s"},
            {"id": "gates", "tier": "mvp", "shows": "Gates passed this run", "anchor": "top-left", "updates_on": "Gate passed"},
            {"id": "gate-arrow", "tier": "mvp", "shows": "Off-screen arrow to the lit gate", "anchor": "center",
             "updates_on": "Every frame while the gate is off-screen"},
        ],
        "tutorial": {
            "approach": "guided-first-run",
            "rationale": "Steering-only control needs one demonstration of which half of the screen does what.",
            "steps": [
                {"id": "steer-prompt", "tier": "mvp", "trigger": "First run start",
                 "prompt": "Left and right hold zones glow; the first gate sits slightly off-line",
                 "completes_on": "The player passes the first gate"},
            ],
        },
        "assets": [
            {"id": "vehicle", "type": "model", "tier": "mvp", "description": "Player vehicle",
             "count": 1, "source_preference": "library", "est_cost": 30, "spec": "GLB, under 5k triangles, one material",
             "role": "player", "dimension": "3d",
             "readability": "A vehicle with wheels or thrusters, a cabin and a clear front, readable at 80 px wide from the chase camera and lit apart from the arena"},
            {"id": "arena-kit", "type": "model", "tier": "mvp", "description": "Modular floor, wall and pillar pieces",
             "count": 6, "source_preference": "procedural", "est_cost": 0, "spec": "Low-poly GLB modules built from model specs: floor, wall, pillar; vertex colours",
             "role": "environment", "dimension": "3d",
             "readability": "Floor, walls and pillars that frame the course and cast hard shadows; quieter than the vehicle and the lit gate"},
            {"id": "gate", "type": "model", "tier": "mvp", "description": "Target gate, lit and unlit",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Low-poly GLB ring gate built from a model spec, lit and unlit materials",
             "role": "target", "dimension": "3d",
             "readability": "A ring gate whose lit state glows in the accent and whose unlit state is dim: the next gate is the brightest thing in the arena and readable from across it"},
            {"id": "skybox", "type": "texture", "tier": "mvp", "description": "Gradient sky",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Shader gradient, no texture fetch",
             "role": "background", "dimension": "3d",
             "readability": "A gradient sky that sets the horizon and the time of day, never brighter than the lit gate"},
            {"id": "gate-vfx", "type": "vfx", "tier": "mvp", "description": "Gate shatter",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Instanced particles",
             "role": "vfx", "dimension": "3d",
             "readability": "A shatter on the passed gate that confirms the pass without hiding the next one"},
        ],
        "audio": [
            {"id": "music-drive", "type": "music", "tier": "mvp", "description": "Driving loop",
             "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "sfx-engine", "type": "sfx", "tier": "mvp", "description": "Engine hum, pitch follows speed",
             "trigger": "During run", "loop": True, "source_preference": "procedural", "est_cost": 0},
            {"id": "sfx-gate", "type": "sfx", "tier": "mvp", "description": "Gate chime", "trigger": "Gate passed",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-bump", "type": "sfx", "tier": "mvp", "description": "Wall bump", "trigger": "Wall contact",
             "loop": False, "source_preference": "library", "est_cost": 5},
        ],
        "post_mvp": [
            {"id": "ghost-replay", "name": "Ghost of best run", "description": "A translucent replay of the player's best run."},
        ],
        "optional": [
            {"id": "vehicle-variants", "name": "Vehicle variants", "description": "Cosmetic vehicles unlocked by arena clears."},
            {"id": "fourth-arena", "name": "Fourth arena", "description": "A night arena."},
        ],
    },

    "one-touch": {
        "label": "One-touch timing",
        "keywords": ["tap", "one-touch", "one touch", "timing", "stack", "jump", "hop", "flap", "reflex", "arcade"],
        "signature": ["timing", "one-touch", "one touch", "stack", "flap", "tap at"],
        "dimension": "2d",
        "structure": "run",
        "camera": "Fixed; the playfield scrolls vertically as the player climbs.",
        "orientation": "portrait",
        "identity_affinity": ["riso-arcade", "signal-brutal", "paper-diorama"],
        "fantasy": "Perfect timing, over and over, until it feels like instinct.",
        "core_loop": "Watch the moving piece -> tap at the right moment -> a clean hit builds the streak -> the tempo rises -> a miss ends the run -> retry at once.",
        "pillars": [
            "One input, and it is never ambiguous",
            "A perfect tap looks and sounds perfect",
            "Back in a run within one second of failing",
        ],
        "run_seconds": 45,
        "first_reward_s": 10,
        "content_units": 3,
        "content_unit_kind": "run-segment",
        "genre": {"family": "arcade", "node": "one-touch", "ending": "endless"},
        "difficulty_axes": ["speed", "density", "variety", "precision"],
        "mastery": {
            "model": "execution",
            "statement": "A better player taps to the sweep's rhythm rather than to the sight "
                         "of the target, so the streak survives the tempo rising.",
            "signals": ["score", "streak"],
        },
        "retention_hooks": ["progression", "streak"],
        "return_reason": "One more run - I only need a couple more perfects.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "timed-tap", "name": "Timed tap", "tier": "mvp", "progression_role": "core",
             "description": "A piece sweeps across a target; a tap locks it in place.",
             "rules": ["The piece sweeps at the current tempo; one tap locks it.",
                       "Overlap of 90% or more with the target is a perfect; any overlap is a hit; none is a miss.",
                       "A miss ends the run."],
             "parameters": {"start_sweep_s": 1.6, "perfect_overlap": 0.9}},
            {"id": "streak", "name": "Perfect streak", "tier": "mvp", "progression_role": "mastery",
             "description": "Consecutive perfects build a streak that multiplies score.",
             "rules": ["Each perfect adds 1 to the streak; a hit resets it to 0.",
                       "Score per lock is 10 times (1 + streak)."],
             "parameters": {"base_points": 10}},
            {"id": "tempo", "name": "Tempo ramp", "tier": "mvp", "progression_role": "core",
             "description": "Sweep speed rises with each lock.",
             "rules": ["Sweep time falls 3% per lock down to a floor.",
                       "Tempo tier changes every 10 locks, with a visual shift."],
             "parameters": {"sweep_step": 0.03, "sweep_floor_s": 0.55, "tier_every": 10}},
        ],
        "actions": [
            {"id": "tap", "action": "Lock the piece", "tier": "mvp", "mechanic": "timed-tap",
             "touch": "Tap anywhere", "mouse": "Click anywhere", "keyboard": "Space or Enter", "gamepad": "A"},
        ],
        "goals": {
            "moment": "Land the next lock as a perfect.",
            "session": "Beat the personal best.",
            "long_term": "Reach the third tempo tier.",
        },
        "progression_steps": [
            {"id": "tier-2", "tier": "mvp", "unlock_condition": "10 locks in one run", "grants": "Tempo tier 2 and its palette"},
            {"id": "tier-3", "tier": "mvp", "unlock_condition": "20 locks in one run", "grants": "Tempo tier 3 and its palette"},
        ],
        "curve": [
            {"at": "Locks 1-5", "description": "Slow sweep; generous target.", "parameters": {"sweep_s": 1.6, "target_width": 1.0}},
            {"at": "Locks 6-20", "description": "Sweep speeds 3% per lock; target narrows 2% per lock.", "parameters": {"target_step": 0.02}},
            {"at": "Locks 21+", "description": "Floor tempo; only the target narrows, to a minimum.", "parameters": {"target_min": 0.45}},
        ],
        "assist": "After three runs under 5 locks, the first five locks of the next run use a wider target.",
        "failure_condition": "A tap with no overlap, or no tap before the sweep completes twice.",
        "failure_feedback": "The piece drops and shatters; 200 ms hit-stop, then the result card.",
        "rewards": [
            {"id": "perfect", "tier": "mvp", "trigger": "Perfect lock", "grants": "Streak +1",
             "feedback": "Ring flash and a rising note per streak step."},
            {"id": "tier-up", "tier": "mvp", "trigger": "Tempo tier changes", "grants": "New palette",
             "feedback": "The whole palette shifts; a short riser."},
            {"id": "new-best", "tier": "mvp", "trigger": "Run ends above the personal best", "grants": "New best, saved",
             "feedback": "Best counter bursts; fanfare."},
        ],
        "hud": [
            {"id": "score", "tier": "mvp", "shows": "Score", "anchor": "top-center", "updates_on": "Each lock",
             "feedback": "Rolls up"},
            {"id": "streak", "tier": "mvp", "shows": "Perfect streak (hidden at 0)", "anchor": "top-right",
             "updates_on": "Each lock", "feedback": "Grows with the streak"},
        ],
        "tutorial": {
            "approach": "diegetic",
            "rationale": "Tap-to-lock is self-explanatory once the target is visibly highlighted.",
            "steps": [
                {"id": "tap-prompt", "tier": "mvp", "trigger": "First run, first lock",
                 "prompt": "Target glows and a 'tap' glyph pulses in time with the sweep",
                 "completes_on": "The first lock"},
            ],
        },
        "assets": [
            {"id": "piece", "type": "sprite", "tier": "mvp", "description": "The moving piece and its locked state",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Vector",
             "role": "player", "dimension": "2d",
             "readability": "The moving piece as a solid slab in the lead accent with a hard outline, its edges crisp at any tempo so the overlap with the target can be judged at 48 px tall"},
            {"id": "target", "type": "sprite", "tier": "mvp", "description": "Target zone",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Vector",
             "role": "target", "dimension": "2d",
             "readability": "The target zone as an outlined slot in a contrasting colour, its edges as crisp as the piece's so 'perfect' is visible before the tap"},
            {"id": "lock-vfx", "type": "vfx", "tier": "mvp", "description": "Perfect ring and shatter",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets",
             "role": "vfx", "dimension": "2d",
             "readability": "A ring on a perfect and a shatter on a miss, each unmistakable from the other"},
            {"id": "backdrop", "type": "texture", "tier": "mvp", "description": "Per-tier background",
             "count": 3, "source_preference": "procedural", "est_cost": 0, "spec": "Shader gradient",
             "role": "background", "dimension": "2d",
             "readability": "A ground per tempo tier that shifts with the tier and never competes with the piece and the target"},
        ],
        "audio": [
            {"id": "music-pulse", "type": "music", "tier": "mvp", "description": "Minimal loop that thickens per tier",
             "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "sfx-lock", "type": "sfx", "tier": "mvp", "description": "Lock thunk; perfect adds a bell",
             "trigger": "Lock", "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-miss", "type": "sfx", "tier": "mvp", "description": "Shatter", "trigger": "Miss",
             "loop": False, "source_preference": "library", "est_cost": 5},
        ],
        "post_mvp": [
            {"id": "piece-variants", "name": "Piece shapes", "description": "Wider and narrower pieces mixed into later tiers."},
            {"id": "daily-seed", "name": "Seeded daily run", "description": "Same sequence for everyone for a day."},
        ],
        "optional": [
            {"id": "skins", "name": "Piece skins", "description": "Cosmetic skins unlocked by best score."},
        ],
    },
}

FALLBACK = "one-touch"

# The experience contract each archetype states (game-design build_spec.experience; checked by
# experience.py against core/reference/experience-rules.yaml): the objective a first-time
# player is shown and the metric it is measured in, how play is lost (and won, for levels),
# how every MVP action is acknowledged, what the first session teaches and its grace before
# failure, and which HUD element shows which metric. The author adds the pause action and
# the first-30-seconds budget from the session numbers.
def drop_merge_top_level(columns, merges_per_level_up, max_drop_level):
    """The highest piece level the drop-merge rules can produce: an exhaustive search of every
    track a run can reach. The rules are the archetype's mechanics, exactly: one row of
    `columns` cells; a drop lands in an empty column at level 1 + floor(merges /
    merges_per_level_up), capped at `max_drop_level`; equal adjacent pieces merge into level + 1
    in the left cell, the track compacts left and the scan repeats until no pair is left; a
    track with no empty column ends the run (its last drop's merges still count).

    The reachable top is not max_drop_level + columns - 1 in general (3 columns, cap 3: the
    ramp never reaches 3 before the track fills, so the top is 4, not 5); hence the search.
    The archetype's 7 columns, 4 merges per level and cap 4 reach level 10 (4,534 states; the
    template's randomised low drops, any level 1..ramp, reach the same 10 over 263,786)."""
    def resolve(track):
        track, merges = list(track), 0
        while True:
            for i in range(len(track) - 1):
                if track[i] and track[i] == track[i + 1]:
                    track[i] += 1
                    track[i + 1] = 0
                    merges += 1
                    filled = [c for c in track if c]
                    track = filled + [0] * (len(track) - len(filled))
                    break
            else:
                return tuple(track), merges

    cap = merges_per_level_up * max_drop_level  # past it the drop level no longer changes
    start = ((0,) * columns, 0)
    seen, stack, top = {start}, [start], 0
    while stack:
        track, merges = stack.pop()
        level = min(1 + merges // merges_per_level_up, max_drop_level)
        for column in range(columns):
            if track[column]:
                continue
            dropped = list(track)
            dropped[column] = level
            after, made = resolve(dropped)
            top = max(top, max(after))
            if all(after):
                continue  # the track is full: the run is over
            state = (after, min(merges + made, cap))
            if state not in seen:
                seen.add(state)
                stack.append(state)
    return top


def _derive_counts():
    """Counted assets whose number the rules decide."""
    drop_merge = ARCHETYPES["drop-merge"]
    params = {}
    for mechanic in drop_merge["mechanics"]:
        params.update(mechanic.get("parameters") or {})
    top = drop_merge_top_level(params["columns"], params["merges_per_level_up"],
                               params["max_drop_level"])
    for asset in drop_merge["assets"]:
        if asset["id"] == "pieces":
            asset["count"] = top
            asset["description"] = (f"Tower pieces, one per level the rules reach (1-{top}), "
                                    "with a merge state")


_derive_counts()


EXPERIENCE = {
    "lane-runner": {
        "goal": "Run as far as you can - switch lanes to dodge every obstacle.",
        "goal_metric": "distance",
        "lose": {"condition": "Touching an obstacle ends the run."},
        "actions": {
            "move-left": {"visual": "The runner slides one lane left at once, leaving a short trail.",
                          "audio": "Lane move whoosh"},
            "move-right": {"visual": "The runner slides one lane right at once, leaving a short trail.",
                           "audio": "Lane move whoosh"},
        },
        "teaches": ["move-left", "move-right"],
        "grace": {"until": "first-success"},
        "hud_metrics": {"score": "distance", "multiplier": "multiplier", "best-marker": "best"},
    },
    "drop-merge": {
        "goal": "Drop pieces so matching ones merge - keep the columns from filling up.",
        "goal_metric": "score",
        "lose": {"condition": "Every column is full and no merge is left."},
        "actions": {
            "drop": {"visual": "The piece falls into the chosen column and lands with a bounce.",
                     "audio": "Drop thud", "updates": ["score"]},
        },
        "teaches": ["drop"],
        "grace": {"until": "first-success"},
        "hud_metrics": {"score": "score", "next-piece": "next-piece", "best": "best"},
    },
    "merge-puzzle": {
        "goal": "Clear every goal counter before your moves run out.",
        "goal_metric": "goal-counters",
        "win": {"condition": "Every goal counter reaches zero.", "metric": "goal-counters"},
        "lose": {"condition": "Moves reach zero with goal counters left.", "metric": "moves"},
        "actions": {
            "swap": {"visual": "The two pieces slide into each other's place; a swap that matches nothing slides back.",
                     "audio": "Swap click", "updates": ["moves", "goal-counters"]},
        },
        "teaches": ["swap"],
        "grace": {"until": "first-success"},
        "hud_metrics": {"moves": "moves", "goals": "goal-counters", "level": "level"},
    },
    "arena-dodge": {
        "goal": "Steer through the gaps in the walls - how far can you get?",
        "goal_metric": "score",
        "lose": {"condition": "Crashing into a wall ends the run."},
        "actions": {
            "steer": {"visual": "The craft banks toward the input on the next frame.",
                      "audio": "Engine pitch follows the steer"},
        },
        "teaches": ["steer"],
        "grace": {"until": "first-success"},
        "hud_metrics": {"score": "score", "best": "best"},
    },
    "arena-3d": {
        "goal": "Fly through the lit gates before the clock runs out.",
        "goal_metric": "gates",
        "lose": {"condition": "The clock reaches zero.", "metric": "time"},
        "actions": {
            "steer": {"visual": "The craft turns toward the input on the next frame.",
                      "audio": "Engine pitch follows the steer"},
        },
        "teaches": ["steer"],
        "grace": {"until": "seconds", "seconds": 15},
        "hud_metrics": {"clock": "time", "gates": "gates"},
    },
    "one-touch": {
        "goal": "Tap when the sweep overlaps the target - land as many locks as you can.",
        "goal_metric": "score",
        "lose": {"condition": "A tap that misses, or two full sweeps without a tap once the first lock is landed."},
        "actions": {
            "tap": {"visual": "The sweep stops on the frame of the tap and the lock flashes.",
                    "audio": "Lock click; a perfect rings higher", "updates": ["score", "streak"]},
        },
        "teaches": ["tap"],
        "grace": {"until": "first-success"},
        "hud_metrics": {"score": "score", "streak": "streak"},
    },
}

# What brings a player back, per archetype (game-design 1.7.0 build_spec.depth): the loop
# above the run and what it persists, a goal ladder, content-variety items on a schedule, the
# beat a first session ends on, and the reasons to return. core/craft/
# retention-and-progression.md is the craft; core/reference/design-depth.yaml the bars.
#
# `features` are the post-mvp features the depth rests on: the author adds them unless the
# strategy excludes them, and an entry whose feature is excluded is tiered optional with the
# exclusion named - depth the strategy defers stays visible, never claimed. MVP entries rest
# only on the archetype's MVP mechanics, progression steps, rewards and hud: what the
# prototype builds. `at_s` is seconds into a run; `after_runs` is runs completed or stages
# cleared before the item appears.
DEPTH = {
    "lane-runner": {
        "features": [
            {"id": "run-missions", "name": "Run missions",
             "description": "Three active missions at a time (pass 40 rows, chain a x4 near-miss multiplier, "
                            "grab 10 pickups); finishing one replaces it with the next of a list of 30."},
            {"id": "distance-milestones", "name": "Distance milestones",
             "description": "Markers at 500 m, 1000 m and every 1000 m after, kept across sessions and "
                            "shown beside the lanes and on the title screen once crossed."},
        ],
        "meta": {"statement": "Run -> finish missions and cross distance milestones -> the next mission "
                              "and the next marker are waiting -> start the next run chasing them.",
                 "tier": "post-mvp", "delivered_by": "run-missions",
                 "persists": [
                     {"kind": "best-score", "what": "Best distance", "tier": "mvp", "delivered_by": "new-best"},
                     {"kind": "missions", "what": "Active missions and their progress", "tier": "post-mvp",
                      "delivered_by": "run-missions"},
                     {"kind": "collection", "what": "Distance milestones crossed",
                      "tier": "post-mvp", "delivered_by": "distance-milestones"},
                 ]},
        "goals": [
            {"id": "next-row", "horizon": "short", "goal": "Get through the next row without touching anything.",
             "measure": "rows passed", "tier": "mvp", "delivered_by": "obstacles"},
            {"id": "beat-best", "horizon": "mid", "goal": "Beat the best distance at least once this session.",
             "measure": "distance > best", "tier": "mvp", "delivered_by": "new-best"},
            {"id": "next-set", "horizon": "mid", "goal": "Reach the next obstacle set in this run.",
             "measure": "30 s, then 60 s survived", "tier": "mvp", "delivered_by": "set-2"},
            {"id": "missions-list", "horizon": "long", "goal": "Work through the mission list and every milestone.",
             "measure": "missions completed of 30", "tier": "post-mvp", "delivered_by": "run-missions"},
        ],
        "content": [
            {"id": "set-2", "kind": "obstacle", "name": "Obstacle set 2", "introduced": "30 s into a run",
             "at_s": 30, "rule": "Rows with two blocked lanes join the mix.", "tier": "mvp", "delivered_by": "set-2"},
            {"id": "set-3", "kind": "obstacle", "name": "Obstacle set 3", "introduced": "60 s into a run",
             "at_s": 60, "rule": "Staggered rows that need two switches join the mix.", "tier": "mvp",
             "delivered_by": "set-3"},
            {"id": "pickups", "kind": "pickup", "name": "Pickups", "introduced": "From the third run, 15 s into a run",
             "at_s": 15, "after_runs": 2, "rule": "A pickup in a free lane adds 50 to the score when touched.",
             "tier": "post-mvp", "delivered_by": "pickups"},
            {"id": "biome-2", "kind": "zone", "name": "Second visual theme", "introduced": "After 1000 m is first crossed",
             "after_runs": 5, "rule": "A new palette and obstacle skin from 1000 m on, every run after.",
             "tier": "post-mvp", "delivered_by": "second-biome"},
        ],
        "first_session_ends_on": "A new best or a crossed milestone, with the next mission shown on the result card.",
        "hooks": [
            {"id": "best-to-beat", "kind": "best-score", "statement": "My best line is right there and I know what I did wrong.",
             "tier": "mvp", "delivered_by": "new-best"},
            {"id": "next-mission", "kind": "missions", "statement": "One mission is two rows from done.",
             "tier": "post-mvp", "delivered_by": "run-missions"},
            {"id": "next-milestone", "kind": "collection", "statement": "The 1000 m marker is the one I have not crossed yet.",
             "tier": "post-mvp", "delivered_by": "distance-milestones"},
        ],
    },
    "drop-merge": {
        "features": [
            {"id": "stage-map", "name": "Stage map",
             "description": "Forty numbered stages, each a goal on the same track - build a level-6 tower within 40 drops, "
                            "score 300 with no column above level 3 - with one to three stars by drops left; clearing a "
                            "stage opens the next and pays coins."},
            {"id": "special-pieces", "name": "Special pieces",
             "description": "Wildcard (merges with any neighbour), bomb (clears its column and both neighbours) and freeze "
                            "(holds the drop ramp for 5 drops) join the drops from stages 3, 6 and 10 on, at most one in 12 drops."},
            {"id": "power-ups", "name": "Power-ups",
             "description": "Hammer (remove one piece), undo (take back the last drop) and shuffle (re-roll the next three "
                            "pieces): one charge each per stage, more bought with coins, never with money."},
            {"id": "coins", "name": "Coins",
             "description": "Coins earned only in play - one per merge, ten per stage star - spent on power-up charges and "
                            "tower themes; never sold."},
            {"id": "achievements", "name": "Achievements",
             "description": "Twelve achievements (a five-step cascade, a level-8 tower, 100 stage stars...), kept across sessions."},
            {"id": "daily-challenge", "name": "Daily challenge",
             "description": "One seeded run per day with the same drops for everyone, and a streak counter for days played."},
            {"id": "tower-themes", "name": "Tower themes",
             "description": "Cosmetic piece and track themes bought with coins."},
        ],
        "meta": {"statement": "Play a stage -> earn stars and coins -> open the next stage and buy power-up charges or a "
                              "theme -> come back for the next stage on the map.",
                 "tier": "post-mvp", "delivered_by": "stage-map",
                 "persists": [
                     {"kind": "best-score", "what": "Best endless score", "tier": "mvp", "delivered_by": "new-best"},
                     {"kind": "stage-progress", "what": "Stages cleared and stars per stage", "tier": "post-mvp",
                      "delivered_by": "stage-map"},
                     {"kind": "currency", "what": "Coin balance and power-up charges", "tier": "post-mvp",
                      "delivered_by": "coins"},
                     {"kind": "achievements", "what": "Achievements earned", "tier": "post-mvp",
                      "delivered_by": "achievements"},
                     {"kind": "cosmetics", "what": "Themes owned and selected", "tier": "post-mvp",
                      "delivered_by": "tower-themes"},
                 ]},
        "goals": [
            {"id": "next-cascade", "horizon": "short", "goal": "Drop the piece where it starts a cascade.",
             "measure": "merges from one drop", "tier": "mvp", "delivered_by": "merge-cascade"},
            {"id": "beat-best", "horizon": "mid", "goal": "Beat the best score at least once this session.",
             "measure": "score > best", "tier": "mvp", "delivered_by": "new-best"},
            {"id": "stage-goal", "horizon": "mid", "goal": "Clear this stage's tower goal within its drop limit.",
             "measure": "goal met, stars by drops left", "tier": "post-mvp", "delivered_by": "stage-map"},
            {"id": "ramp-top", "horizon": "long", "goal": "Keep a run going until the drop ramp reaches its top level.",
             "measure": "12 merges in one run", "tier": "mvp", "delivered_by": "ramp-4"},
            {"id": "map-complete", "horizon": "long", "goal": "Three-star every stage on the map.",
             "measure": "stars of 120", "tier": "post-mvp", "delivered_by": "stage-map"},
        ],
        "content": [
            {"id": "level-2-drops", "kind": "piece", "name": "Level-2 drops", "introduced": "After 4 merges, about 20 s in",
             "at_s": 20, "rule": "Level-2 pieces join the drops.", "tier": "mvp", "delivered_by": "ramp-2"},
            {"id": "level-3-drops", "kind": "piece", "name": "Level-3 drops", "introduced": "After 8 merges, about 40 s in",
             "at_s": 40, "rule": "Level-3 pieces join the drops.", "tier": "mvp", "delivered_by": "ramp-3"},
            {"id": "level-4-drops", "kind": "piece", "name": "Level-4 drops", "introduced": "After 12 merges, about 60 s in",
             "at_s": 60, "rule": "Level-4 pieces, the top of the ramp, join the drops.", "tier": "mvp",
             "delivered_by": "ramp-4"},
            {"id": "wildcard", "kind": "special-piece", "name": "Wildcard piece", "introduced": "From stage 3",
             "after_runs": 3, "rule": "Merges with either neighbour and takes its level + 1.", "tier": "post-mvp",
             "delivered_by": "special-pieces"},
            {"id": "bomb", "kind": "special-piece", "name": "Bomb piece", "introduced": "From stage 6",
             "after_runs": 6, "rule": "Clears its column and both neighbours, scoring their levels.", "tier": "post-mvp",
             "delivered_by": "special-pieces"},
            {"id": "freeze", "kind": "special-piece", "name": "Freeze piece", "introduced": "From stage 10",
             "after_runs": 10, "rule": "Holds the drop level for the next 5 drops.", "tier": "post-mvp",
             "delivered_by": "special-pieces"},
            {"id": "hammer", "kind": "power-up", "name": "Hammer", "introduced": "From stage 2",
             "after_runs": 2, "rule": "Removes one chosen piece; the track slides left.", "tier": "post-mvp",
             "delivered_by": "power-ups"},
        ],
        "first_session_ends_on": "A new best or a cleared stage, with the next stage's goal on the result card.",
        "hooks": [
            {"id": "cascade-again", "kind": "best-score",
             "statement": "I saw the cascade that would have saved that track, and I want to set it up again.",
             "tier": "mvp", "delivered_by": "new-best"},
            {"id": "next-stage", "kind": "stage-map", "statement": "The next stage is open and I have two stars to earn back.",
             "tier": "post-mvp", "delivered_by": "stage-map"},
            {"id": "daily-run", "kind": "daily-seed", "statement": "There is a new daily track and my streak is on day 4.",
             "tier": "post-mvp", "delivered_by": "daily-challenge"},
            {"id": "next-theme", "kind": "next-unlock", "statement": "Forty more coins buys the theme I want.",
             "tier": "post-mvp", "delivered_by": "tower-themes"},
        ],
    },
    "merge-puzzle": {
        "features": [
            {"id": "level-stars", "name": "Level stars",
             "description": "One to three stars per level by moves left, kept across sessions; replaying a level "
                            "keeps the most stars."},
            {"id": "booster-charges", "name": "Boosters",
             "description": "Row-clear and colour-clear boosters earned by three-starring a level, one charge each, "
                            "never sold."},
        ],
        "meta": {"statement": "Clear a level -> earn stars and open the next level -> spend boosters on the hard ones "
                              "-> come back for the next set.",
                 "tier": "mvp", "delivered_by": "levels-5-8",
                 "persists": [
                     {"kind": "stage-progress", "what": "Levels cleared", "tier": "mvp", "delivered_by": "levels-5-8"},
                     {"kind": "collection", "what": "Stars per level", "tier": "post-mvp", "delivered_by": "level-stars"},
                     {"kind": "unlocks", "what": "Booster charges", "tier": "post-mvp", "delivered_by": "booster-charges"},
                 ]},
        "goals": [
            {"id": "next-swap", "horizon": "short", "goal": "Find a swap that clears a goal colour.",
             "measure": "goal counter falls", "tier": "mvp", "delivered_by": "swap-resolve"},
            {"id": "clear-level", "horizon": "mid", "goal": "Clear two or three levels this session.",
             "measure": "levels cleared", "tier": "mvp", "delivered_by": "level-clear"},
            {"id": "clear-set", "horizon": "long", "goal": "Clear every level in the set.",
             "measure": "levels cleared of 12", "tier": "mvp", "delivered_by": "levels-9-12"},
            {"id": "all-stars", "horizon": "long", "goal": "Three-star every level.",
             "measure": "stars of 36", "tier": "post-mvp", "delivered_by": "level-stars"},
        ],
        "content": [
            {"id": "two-goals", "kind": "level-set", "name": "Two goal colours", "introduced": "From level 5",
             "after_runs": 4, "rule": "Levels ask for two goal colours at once.", "tier": "mvp", "delivered_by": "levels-5-8"},
            {"id": "tight-moves", "kind": "modifier", "name": "Tighter move limits", "introduced": "From level 9",
             "after_runs": 8, "rule": "Move limits drop by a quarter.", "tier": "mvp", "delivered_by": "levels-9-12"},
            {"id": "specials", "kind": "special-piece", "name": "Special pieces", "introduced": "From level 6",
             "after_runs": 6, "rule": "A four-match makes a row-clearer; a five-match a bomb.", "tier": "post-mvp",
             "delivered_by": "special-pieces"},
            {"id": "boosters", "kind": "power-up", "name": "Boosters", "introduced": "After the first three-star clear",
             "after_runs": 3, "rule": "A row-clear or colour-clear booster can be spent before a move.",
             "tier": "post-mvp", "delivered_by": "booster-charges"},
            {"id": "blocker-cells", "kind": "obstacle", "name": "Board blockers", "introduced": "From level 13",
             "after_runs": 12, "rule": "Ice and crate cells that need adjacent clears.", "tier": "optional"},
        ],
        "first_session_ends_on": "A cleared level boundary, with the next level's goal shown.",
        "hooks": [
            {"id": "next-level", "kind": "stage-map", "statement": "There is a next level waiting.",
             "tier": "mvp", "delivered_by": "levels-5-8"},
            {"id": "missing-stars", "kind": "collection", "statement": "I left stars on level 7.",
             "tier": "post-mvp", "delivered_by": "level-stars"},
        ],
    },
    "arena-dodge": {
        "features": [
            {"id": "zones", "name": "Zones",
             "description": "Every 500 m the arena changes zone - palette, skyline and one new obstacle type: moving walls "
                            "(500 m), laser gates that blink on a 1.2 s cycle (1000 m), closing gates (1500 m) - with a "
                            "2 s calm stretch at each border."},
            {"id": "pickups", "name": "Pickups",
             "description": "Shield (absorbs one hit), magnet (pulls coins for 6 s) and boost (+30 % speed and invulnerable "
                            "for 3 s), one in every 8 wall rows."},
            {"id": "coins", "name": "Coins",
             "description": "Coins in lines between walls, earned only in play and spent in the garage; never sold."},
            {"id": "near-miss-combo", "name": "Near-miss combo",
             "description": "Passing a wall within 0.8 units raises a score multiplier by 0.5 up to x4; a hit or 4 s with "
                            "no near-miss resets it."},
            {"id": "garage", "name": "Ship garage",
             "description": "Five ships with distinct models bought with coins, each with one trait (wider shield, "
                            "faster steer...), and three upgrade steps for pickup durations."},
            {"id": "missions", "name": "Missions",
             "description": "Three active missions (reach 1500 m, chain a x3 combo, grab 3 shields in one run); finishing "
                            "one pays coins and draws the next."},
            {"id": "daily-run", "name": "Daily run",
             "description": "One seeded run per day, the same walls for everyone, with a streak counter for days played."},
        ],
        "meta": {"statement": "Run -> collect coins and finish missions -> buy a ship or an upgrade in the garage -> "
                              "push the next distance milestone with it.",
                 "tier": "post-mvp", "delivered_by": "garage",
                 "persists": [
                     {"kind": "best-score", "what": "Best score", "tier": "mvp", "delivered_by": "new-best"},
                     {"kind": "currency", "what": "Coin balance", "tier": "post-mvp", "delivered_by": "coins"},
                     {"kind": "upgrades", "what": "Ships owned, the selected ship, upgrade steps", "tier": "post-mvp",
                      "delivered_by": "garage"},
                     {"kind": "missions", "what": "Active missions and progress", "tier": "post-mvp",
                      "delivered_by": "missions"},
                 ]},
        "goals": [
            {"id": "next-gap", "horizon": "short", "goal": "Line up for the next gap.", "measure": "walls passed",
             "tier": "mvp", "delivered_by": "walls"},
            {"id": "beat-best", "horizon": "mid", "goal": "Beat the best score this session.", "measure": "score > best",
             "tier": "mvp", "delivered_by": "new-best"},
            {"id": "next-zone", "horizon": "mid", "goal": "Reach the next zone border in this run.",
             "measure": "distance band reached", "tier": "post-mvp", "delivered_by": "zones"},
            {"id": "tier-3", "horizon": "long", "goal": "Survive into the third speed tier.", "measure": "45 s survived",
             "tier": "mvp", "delivered_by": "tier-3"},
            {"id": "full-garage", "horizon": "long", "goal": "Own every ship and max its upgrades.",
             "measure": "ships owned of 5", "tier": "post-mvp", "delivered_by": "garage"},
        ],
        "content": [
            {"id": "speed-tier-2", "kind": "modifier", "name": "Speed tier 2", "introduced": "20 s into a run",
             "at_s": 20, "rule": "Speed steps up and the palette shifts.", "tier": "mvp", "delivered_by": "tier-2"},
            {"id": "speed-tier-3", "kind": "modifier", "name": "Speed tier 3", "introduced": "45 s into a run",
             "at_s": 45, "rule": "Speed steps up again and the palette shifts.", "tier": "mvp", "delivered_by": "tier-3"},
            {"id": "pickups", "kind": "pickup", "name": "Shield, magnet and boost", "introduced": "From the second run, 10 s in",
             "at_s": 10, "after_runs": 1, "rule": "One pickup in every 8 wall rows.", "tier": "post-mvp",
             "delivered_by": "pickups"},
            {"id": "combo", "kind": "modifier", "name": "Near-miss combo", "introduced": "At the first near-miss",
             "at_s": 5, "rule": "Each pass within 0.8 units raises the multiplier by 0.5, up to x4.",
             "tier": "post-mvp", "delivered_by": "near-miss-combo"},
            {"id": "moving-walls", "kind": "obstacle", "name": "Moving walls", "introduced": "At 500 m",
             "at_s": 35, "rule": "Wall gaps slide sideways at 1.5 units/s while they approach.", "tier": "post-mvp",
             "delivered_by": "zones"},
            {"id": "lasers", "kind": "hazard", "name": "Laser gates", "introduced": "At 1000 m",
             "at_s": 60, "rule": "A gate that blinks on and off on a 1.2 s cycle; pass while it is off.",
             "tier": "post-mvp", "delivered_by": "zones"},
            {"id": "closing-gates", "kind": "obstacle", "name": "Closing gates", "introduced": "At 1500 m",
             "at_s": 80, "rule": "Two walls that close toward each other; the gap shrinks as they near.",
             "tier": "post-mvp", "delivered_by": "zones"},
        ],
        "first_session_ends_on": "A new best or a new zone reached, with coins and a mission shown on the result card.",
        "hooks": [
            {"id": "best-to-beat", "kind": "best-score", "statement": "I crashed just short of my best and I know why.",
             "tier": "mvp", "delivered_by": "new-best"},
            {"id": "next-ship", "kind": "next-unlock", "statement": "Sixty more coins and I can buy the next ship.",
             "tier": "post-mvp", "delivered_by": "garage"},
            {"id": "missions", "kind": "missions", "statement": "Two of my three missions are nearly done.",
             "tier": "post-mvp", "delivered_by": "missions"},
            {"id": "daily", "kind": "daily-seed", "statement": "Today's run is new and my streak is on day 3.",
             "tier": "post-mvp", "delivered_by": "daily-run"},
        ],
    },
    "arena-3d": {
        "features": [
            {"id": "arena-medals", "name": "Arena medals",
             "description": "Bronze, silver and gold target times per arena, kept across sessions."},
        ],
        "meta": {"statement": "Race an arena -> beat its target time for a medal -> unlock the next arena -> come back "
                              "for the medals left.",
                 "tier": "mvp", "delivered_by": "arena-2",
                 "persists": [
                     {"kind": "unlocks", "what": "Arenas unlocked", "tier": "mvp", "delivered_by": "arena-2"},
                     {"kind": "best-score", "what": "Best per arena", "tier": "mvp", "delivered_by": "new-best"},
                     {"kind": "collection", "what": "Medals per arena", "tier": "post-mvp", "delivered_by": "arena-medals"},
                 ]},
        "goals": [
            {"id": "next-gate", "horizon": "short", "goal": "Line up for the next lit gate.", "measure": "gates passed",
             "tier": "mvp", "delivered_by": "checkpoints"},
            {"id": "next-arena", "horizon": "mid", "goal": "Unlock the next arena.", "measure": "gates in one run",
             "tier": "mvp", "delivered_by": "arena-unlock"},
            {"id": "all-medals", "horizon": "long", "goal": "Gold in every arena.", "measure": "golds of 3",
             "tier": "post-mvp", "delivered_by": "arena-medals"},
        ],
        "content": [
            {"id": "arena-2", "kind": "zone", "name": "Arena 2", "introduced": "After 10 gates in arena 1",
             "after_runs": 2, "rule": "A new layout with tighter gate spacing.", "tier": "mvp", "delivered_by": "arena-2"},
            {"id": "arena-3", "kind": "zone", "name": "Arena 3", "introduced": "After 12 gates in arena 2",
             "after_runs": 4, "rule": "A new layout with gates on two heights.", "tier": "mvp", "delivered_by": "arena-3"},
            {"id": "boost-pads", "kind": "pickup", "name": "Boost pads", "introduced": "From arena 2, 20 s in",
             "at_s": 20, "after_runs": 2, "rule": "A pad adds a short speed burst.", "tier": "post-mvp",
             "delivered_by": "boost"},
            {"id": "ghost", "kind": "event", "name": "Ghost of best run", "introduced": "After the first finished run",
             "after_runs": 1, "rule": "A translucent replay of the best run races alongside.", "tier": "post-mvp",
             "delivered_by": "ghost-replay"},
        ],
        "first_session_ends_on": "A newly unlocked arena, shown on the result card.",
        "hooks": [
            {"id": "next-arena", "kind": "next-unlock", "statement": "Arena 3 is one good run away.",
             "tier": "mvp", "delivered_by": "arena-unlock"},
            {"id": "medals", "kind": "collection", "statement": "I only have bronze on arena 2.",
             "tier": "post-mvp", "delivered_by": "arena-medals"},
        ],
    },
    "one-touch": {
        "features": [
            {"id": "lock-milestones", "name": "Lock milestones",
             "description": "Markers at 25, 50 and 100 locks in one run, kept across sessions and shown "
                            "on the title screen once crossed."},
        ],
        "meta": {"statement": "Play -> cross a lock milestone -> it is marked for good -> chase the next milestone.",
                 "tier": "post-mvp", "delivered_by": "lock-milestones",
                 "persists": [
                     {"kind": "best-score", "what": "Best score", "tier": "mvp", "delivered_by": "new-best"},
                     {"kind": "collection", "what": "Lock milestones crossed", "tier": "post-mvp",
                      "delivered_by": "lock-milestones"},
                 ]},
        "goals": [
            {"id": "next-lock", "horizon": "short", "goal": "Land the next lock as a perfect.", "measure": "perfects",
             "tier": "mvp", "delivered_by": "timed-tap"},
            {"id": "beat-best", "horizon": "mid", "goal": "Beat the best score this session.", "measure": "score > best",
             "tier": "mvp", "delivered_by": "new-best"},
            {"id": "tempo-3", "horizon": "long", "goal": "Reach the third tempo tier.", "measure": "20 locks in one run",
             "tier": "mvp", "delivered_by": "tier-3"},
        ],
        "content": [
            {"id": "tempo-2", "kind": "modifier", "name": "Tempo tier 2", "introduced": "After 10 locks, about 15 s in",
             "at_s": 15, "rule": "The sweep speeds up.", "tier": "mvp", "delivered_by": "tier-2"},
            {"id": "tempo-3", "kind": "modifier", "name": "Tempo tier 3", "introduced": "After 20 locks, about 30 s in",
             "at_s": 30, "rule": "The sweep speeds up again.", "tier": "mvp", "delivered_by": "tier-3"},
            {"id": "shapes", "kind": "piece", "name": "Piece shapes", "introduced": "From the third run, 20 s in",
             "at_s": 20, "after_runs": 2, "rule": "Wider and narrower pieces mixed into later tiers.",
             "tier": "post-mvp", "delivered_by": "piece-variants"},
            {"id": "seeded-day", "kind": "event", "name": "Seeded daily run", "introduced": "Once a day",
             "after_runs": 1, "rule": "The same sequence for everyone for a day.", "tier": "post-mvp",
             "delivered_by": "daily-seed"},
        ],
        "first_session_ends_on": "A new best, with the next milestone shown on the result card.",
        "hooks": [
            {"id": "best-to-beat", "kind": "best-score", "statement": "One more perfect and I had it.",
             "tier": "mvp", "delivered_by": "new-best"},
            {"id": "next-milestone", "kind": "collection", "statement": "Fifty locks is the marker I have not crossed.",
             "tier": "post-mvp", "delivered_by": "lock-milestones"},
        ],
    },
}

# The content each archetype commits to (game-design 1.9.0 build_spec.content; checked by
# content.py against the archetype's genre family in core/reference/genre-models.yaml): what
# one unit of play is, how the units are generated, and every unit the MVP player meets with
# its purpose, objective, the mechanics it asks for and introduces, its difficulty on the
# family's axes, how long it runs, how it is won and lost, and what must be true of it once
# it is built. A run archetype lists the representative segments of its ramp (`parametric`);
# a level archetype lists every level (`authored`). Difficulty lives here and nowhere else.
CONTENT = {
    "lane-runner": {
        "unit_kind": "run-segment",
        "generation": {
            "mode": "parametric",
            "parameters": {"lanes": 3, "start_speed": 6.0, "speed_cap": 12.0,
                           "row_gap_s": 1.1, "min_row_gap_s": 0.45, "obstacle_sets": 3},
            "expected_units": 6,
        },
        "units": [
            {"id": "seg-opening", "index": 1, "tier": "mvp", "purpose": "teach",
             "objective": "Bank 20 s of distance through single-obstacle rows at the opening speed of 6.0",
             "start_state": "The runner starts in the middle lane with an empty track ahead",
             "end_state": "Twenty seconds of distance are banked and the second obstacle set joins",
             "mechanics": ["lane-switch", "obstacles", "distance-score"],
             "introduces": ["lane-switch", "obstacles", "distance-score"],
             "difficulty": {"speed": 0.2, "density": 0.18, "variety": 0.15, "precision": 0.3},
             "expected_duration_s": 20,
             "success": "The runner reaches 20 s of distance without touching one of the single obstacles",
             "failure": "The runner touches a single obstacle and the result card shows a distance under 20 s",
             "acceptance": [
                 "Segment 1 spawns one-obstacle rows 1.1 s apart at speed 6.0 for its first 20 s",
                 "A first-time player banks a near-miss inside segment 1 before any row can be hit",
             ],
             "variation_from_previous": [],
             "parameters": {"speed": 6.0, "row_gap_s": 1.1, "obstacles_per_row": 1}},
            {"id": "seg-two-rows", "index": 2, "tier": "mvp", "purpose": "test",
             "objective": "Hold a lane through two-obstacle rows from 20 s to 60 s and keep the multiplier at x2",
             "start_state": "The runner carries its distance and multiplier into the faster rows",
             "end_state": "Sixty seconds of distance are banked and the third set joins",
             "mechanics": ["lane-switch", "obstacles", "distance-score"],
             "difficulty": {"speed": 0.4, "density": 0.18, "variety": 0.15, "precision": 0.3},
             "expected_duration_s": 40,
             "success": "The runner passes 60 s of distance with a near-miss multiplier of at least 2 banked",
             "failure": "The runner clips a two-obstacle row and the run ends before 60 s of distance",
             "acceptance": [
                 "Segment 2 spawns two-obstacle rows 0.8 s apart and raises speed 3% every 5 s",
                 "A bot that never changes lane dies inside segment 2 in at least 9 of 10 attempts",
             ],
             "variation_from_previous": ["pattern_set", "tempo"],
             "parameters": {"speed_step": 0.03, "row_gap_s": 0.8, "obstacles_per_row": 2}},
            {"id": "seg-all-sets", "index": 3, "tier": "mvp", "purpose": "climax",
             "objective": "Survive past 60 s with all three obstacle sets in the pool and speed at its 12.0 cap",
             "start_state": "Every obstacle set is in the pattern pool and the speed ramp is near its cap",
             "end_state": "The run ends on a hit, with the distance stamped as a best or not",
             "mechanics": ["lane-switch", "obstacles", "distance-score"],
             "difficulty": {"speed": 0.62, "density": 0.45, "variety": 0.5, "precision": 0.3},
             "expected_duration_s": 60,
             "success": "The run continues past 60 s at the 12.0 speed cap with every obstacle set in the pool",
             "failure": "The runner hits a capped-speed row and the best distance is stamped on the result card",
             "acceptance": [
                 "Segment 3 draws from all 3 obstacle sets with rows 0.45 s apart and speed capped at 12.0",
                 "Every row of segment 3 still leaves one passable lane at the capped speed",
             ],
             "variation_from_previous": ["pattern_set", "hazard_kind", "tempo"],
             "parameters": {"speed_cap": 12.0, "row_gap_s": 0.45, "obstacle_sets": 3}},
        ],
    },

    "drop-merge": {
        "unit_kind": "run-segment",
        "generation": {
            "mode": "parametric",
            "parameters": {"columns": 7, "merges_per_level_up": 4, "max_drop_level": 4},
            "expected_units": 6,
        },
        "units": [
            {"id": "ramp-opening", "index": 1, "tier": "mvp", "purpose": "teach",
             "objective": "Make 3 merges on the seven-column track while every drop is a level-1 piece",
             "start_state": "An empty seven-column track with a level-1 piece in hand",
             "end_state": "Three merges are banked and the drop ramp starts to rise",
             "mechanics": ["track", "drop", "merge-cascade", "full-track"],
             "introduces": ["track", "drop", "merge-cascade", "full-track"],
             "difficulty": {"speed": 0.15, "density": 0.2, "variety": 0.12, "precision": 0.25},
             "expected_duration_s": 20,
             "success": "Three merges land inside the first 20 s with at least 4 columns still free",
             "failure": "All seven columns fill before the third merge and the run ends at the result card",
             "acceptance": [
                 "Segment 1 drops only level-1 pieces for its first 3 merges, so a first drop can always merge",
                 "The track holds exactly 7 columns and one row, and a dropped piece settles in 0.2 s",
             ],
             "variation_from_previous": [],
             "parameters": {"drop_level": 1, "free_columns_min": 4}},
            {"id": "ramp-rising", "index": 2, "tier": "mvp", "purpose": "test",
             "objective": "Reach 8 merges while the drop level rises one step every 4 merges",
             "start_state": "A part-filled track with the drop ramp at level 2",
             "end_state": "Merge 8 is banked and the ramp stands at level 3",
             "mechanics": ["track", "drop", "merge-cascade", "drop-ramp", "full-track"],
             "introduces": ["drop-ramp"],
             "difficulty": {"speed": 0.32, "density": 0.2, "variety": 0.12, "precision": 0.25},
             "expected_duration_s": 25,
             "success": "Merge 8 lands with the drop level at 3 and two columns still free",
             "failure": "The track fills between merges 4 and 8 while the drop level is still rising",
             "acceptance": [
                 "The drop level in segment 2 is one plus the merges made divided by 4, never higher",
                 "A bot always dropping into the leftmost free column fills the track before merge 8",
             ],
             "variation_from_previous": ["introduces", "tempo"],
             "parameters": {"drop_level": 3, "merges_target": 8}},
            {"id": "ramp-crowded", "index": 3, "tier": "mvp", "purpose": "twist",
             "objective": "Resolve a cascade of 2 merges from a track holding 5 pieces of mixed levels",
             "start_state": "Five pieces of three different levels sit on the track",
             "end_state": "A cascade has freed a column and the ramp is close to its cap",
             "mechanics": ["track", "drop", "merge-cascade", "drop-ramp", "full-track"],
             "difficulty": {"speed": 0.32, "density": 0.2, "variety": 0.3, "precision": 0.25},
             "expected_duration_s": 25,
             "success": "A cascade of 2 merges frees a column on a track that held 5 pieces",
             "failure": "No equal neighbours are left on a 6-piece track and the next drop ends the run",
             "acceptance": [
                 "A cascade in segment 3 resolves left to right and compacts the track between merges",
                 "Pieces of level 1 to 4 are told apart by shape as well as colour at 48 px",
             ],
             "variation_from_previous": ["pattern_set", "objective"],
             "parameters": {"pieces_on_track": 5, "cascade_length": 2}},
            {"id": "ramp-capped", "index": 4, "tier": "mvp", "purpose": "climax",
             "objective": "Hold the track past merge 12 with the drop level pinned at its cap of 4",
             "start_state": "The ramp is pinned at 4 and most columns hold a piece",
             "end_state": "The run ends on a full track with no merge left",
             "mechanics": ["track", "drop", "merge-cascade", "drop-ramp", "full-track"],
             "difficulty": {"speed": 0.55, "density": 0.5, "variety": 0.48, "precision": 0.25},
             "expected_duration_s": 20,
             "success": "Merge 12 lands with the drop level pinned at 4 and one column kept free",
             "failure": "Every column holds a piece with no equal neighbours and the best score is stamped",
             "acceptance": [
                 "The drop level in segment 4 never passes 4 however many merges the run has made",
                 "A full track with no merge left ends the run inside 1 s and offers an immediate retry",
             ],
             "variation_from_previous": ["hazard_kind", "tempo", "objective"],
             "parameters": {"drop_level": 4, "merges_target": 12}},
        ],
    },

    "arena-dodge": {
        "unit_kind": "run-segment",
        "generation": {
            "mode": "parametric",
            "parameters": {"wall_speed": 8.0, "speed_step": 0.35, "gap_widths": 3.0,
                           "min_gap_widths": 1.6},
            "expected_units": 6,
        },
        "units": [
            {"id": "tier-opening", "index": 1, "tier": "mvp", "purpose": "teach",
             "objective": "Steer through 4 wall gaps in the first 15 s at the opening wall speed",
             "start_state": "The craft enters the arena on the centre line with the first wall far off",
             "end_state": "Four gaps are behind the craft and the speed ramp starts",
             "mechanics": ["steering", "walls", "crash", "speed-ramp"],
             "introduces": ["steering", "walls", "crash", "speed-ramp"],
             "difficulty": {"speed": 0.18, "density": 0.15, "variety": 0.12, "precision": 0.28},
             "expected_duration_s": 15,
             "success": "Four wall gaps are cleared inside 15 s without the craft touching a wall",
             "failure": "The craft crashes into one of the opening walls before 15 s have passed",
             "acceptance": [
                 "Gaps in tier 1 are at least 3 craft widths across and walls approach at 8 units a second",
                 "A first-time player clears 4 gaps of tier 1 before any crash is possible",
             ],
             "variation_from_previous": [],
             "parameters": {"wall_speed": 8.0, "gap_widths": 3.0, "gaps": 4}},
            {"id": "tier-quickening", "index": 2, "tier": "mvp", "purpose": "test",
             "objective": "Survive from 15 s to 45 s while wall speed climbs 0.35 units a second",
             "start_state": "The craft carries its score into a steadily faster arena",
             "end_state": "Forty-five seconds of survival are banked and the gaps begin to narrow",
             "mechanics": ["steering", "walls", "crash", "speed-ramp"],
             "difficulty": {"speed": 0.4, "density": 0.15, "variety": 0.12, "precision": 0.28},
             "expected_duration_s": 30,
             "success": "The craft reaches 45 s of survival with the wall speed above 14 units a second",
             "failure": "The craft clips a wall edge while the speed ramp is still climbing",
             "acceptance": [
                 "Wall speed in tier 2 rises 0.35 units a second each second, read from the play probe",
                 "A bot holding one steering direction crashes inside tier 2 in 10 of 10 attempts",
             ],
             "variation_from_previous": ["tempo", "pattern_set"],
             "parameters": {"speed_step": 0.35, "gap_widths": 2.4}},
            {"id": "tier-capped", "index": 3, "tier": "mvp", "purpose": "climax",
             "objective": "Pass 45 s with the narrowest gaps and the full speed ramp in play",
             "start_state": "The arena is at its narrowest and the ramp has not stopped",
             "end_state": "The run ends in a crash and the best survival time is stamped",
             "mechanics": ["steering", "walls", "crash", "speed-ramp"],
             "difficulty": {"speed": 0.6, "density": 0.42, "variety": 0.4, "precision": 0.28},
             "expected_duration_s": 45,
             "success": "The run passes 45 s with gaps down to 1.6 craft widths and the ramp still rising",
             "failure": "The craft crashes past 45 s and the result card stamps the best survival time",
             "acceptance": [
                 "Every wall of tier 3 still leaves one gap reachable from the craft's current line",
                 "Gaps in tier 3 narrow to 1.6 craft widths and no narrower, read from the arena data",
             ],
             "variation_from_previous": ["hazard_kind", "tempo", "objective"],
             "parameters": {"gap_widths": 1.6, "walls_per_screen": 2}},
        ],
    },

    "arena-3d": {
        "unit_kind": "round",
        "generation": {
            "mode": "parametric",
            "parameters": {"arenas": 3, "start_clock_s": 30, "gate_bonus_s": 3.0,
                           "min_gate_bonus_s": 2.0},
            "expected_units": 6,
        },
        "units": [
            {"id": "arena-one", "index": 1, "tier": "mvp", "purpose": "teach",
             "objective": "Pass 10 gates of the open arena before the 30 s clock runs out",
             "start_state": "The craft starts at the centre of an open arena with 30 s on the clock",
             "end_state": "Ten gates are behind the craft and arena 2 is unlocked",
             "mechanics": ["steering", "checkpoints"],
             "introduces": ["steering", "checkpoints"],
             "difficulty": {"speed": 0.2, "density": 0.18, "variety": 0.15, "precision": 0.3},
             "expected_duration_s": 25,
             "success": "Ten gates are passed in arena 1 and each one adds 3 s to the clock",
             "failure": "The clock reaches zero in arena 1 with fewer than 10 gates passed",
             "acceptance": [
                 "Gates in arena 1 stand 60 units apart and each pays 3 s onto the clock",
                 "The next gate of arena 1 is in frame, or its arrow is, at every moment of the round",
             ],
             "variation_from_previous": [],
             "parameters": {"gates": 10, "gate_bonus_s": 3.0}},
            {"id": "arena-two", "index": 2, "tier": "mvp", "purpose": "test",
             "objective": "Pass 12 gates of the pillared arena with the bonus time cut to 2 s",
             "start_state": "The craft enters an arena with pillars standing between its gates",
             "end_state": "Twelve gates are behind the craft and arena 3 is unlocked",
             "mechanics": ["steering", "checkpoints"],
             "difficulty": {"speed": 0.2, "density": 0.35, "variety": 0.15, "precision": 0.3},
             "expected_duration_s": 25,
             "success": "Twelve gates are passed in arena 2 with pillars between them and 2 s a gate",
             "failure": "The clock reaches zero in arena 2, or the craft is stopped dead by a pillar",
             "acceptance": [
                 "Arena 2 places 8 pillars between its gates and pays 2 s a gate onto the clock",
                 "A line that ignores the pillars of arena 2 runs the clock out in 9 of 10 attempts",
             ],
             "variation_from_previous": ["hazard_kind", "pattern_set"],
             "parameters": {"gates": 12, "pillars": 8}},
            {"id": "arena-three", "index": 3, "tier": "mvp", "purpose": "climax",
             "objective": "Pass 14 gates of the narrow arena where every gate needs a sharp turn",
             "start_state": "The craft enters lanes 20 units across with gates set at hard angles",
             "end_state": "The clock runs out and the best gate count is stamped",
             "mechanics": ["steering", "checkpoints"],
             "difficulty": {"speed": 0.5, "density": 0.5, "variety": 0.45, "precision": 0.3},
             "expected_duration_s": 25,
             "success": "Fourteen gates are passed in arena 3 with its lanes 20 units across",
             "failure": "The clock reaches zero in arena 3 and the best gate count is stamped",
             "acceptance": [
                 "Lanes in arena 3 are 20 units across and every gate turn is 45 degrees or sharper",
                 "Arena 3 opens only after 12 gates of arena 2, read from the progression data",
             ],
             "variation_from_previous": ["pattern_set", "tempo", "objective"],
             "parameters": {"gates": 14, "lane_units": 20}},
        ],
    },

    "one-touch": {
        "unit_kind": "run-segment",
        "generation": {
            "mode": "parametric",
            "parameters": {"sweep_s": 1.6, "sweep_floor_s": 0.6, "target_degrees": 40,
                           "min_target_degrees": 12},
            "expected_units": 6,
        },
        "units": [
            {"id": "tempo-opening", "index": 1, "tier": "mvp", "purpose": "teach",
             "objective": "Land the first 5 locks while the sweep is slow and the target is wide",
             "start_state": "The sweep turns slowly across a target covering 40 degrees",
             "end_state": "Five locks are landed and the tempo begins to rise",
             "mechanics": ["timed-tap", "streak", "tempo"],
             "introduces": ["timed-tap", "streak", "tempo"],
             "difficulty": {"speed": 0.18, "density": 0.12, "variety": 0.1, "precision": 0.25},
             "expected_duration_s": 12,
             "success": "Five locks land inside 12 s with the sweep still at its opening speed",
             "failure": "A tap misses the wide target inside the first 5 locks and the run ends",
             "acceptance": [
                 "The sweep in tier 1 takes 1.6 s a turn and the target covers 40 degrees",
                 "A first-time player lands 1 lock of tier 1 inside 4 s of the first sweep",
             ],
             "variation_from_previous": [],
             "parameters": {"sweep_s": 1.6, "target_degrees": 40, "locks": 5}},
            {"id": "tempo-narrowing", "index": 2, "tier": "mvp", "purpose": "test",
             "objective": "Hold a streak of 10 while the target narrows 2% a lock",
             "start_state": "The streak stands at 5 and every lock takes a little more off the target",
             "end_state": "Twenty locks are landed and the tempo reaches its floor",
             "mechanics": ["timed-tap", "streak", "tempo"],
             "difficulty": {"speed": 0.18, "density": 0.12, "variety": 0.1, "precision": 0.45},
             "expected_duration_s": 18,
             "success": "Locks 6 to 20 land with the streak unbroken and the target under 30 degrees",
             "failure": "A tap with no overlap breaks the streak between locks 6 and 20",
             "acceptance": [
                 "The target in tier 2 narrows 2% a lock while the sweep speeds up 3% a lock",
                 "A bot tapping on a fixed 500 ms interval fails tier 2 inside 8 locks",
             ],
             "variation_from_previous": ["tempo", "objective"],
             "parameters": {"target_step": 0.02, "sweep_step": 0.03, "locks": 20}},
            {"id": "tempo-floor", "index": 3, "tier": "mvp", "purpose": "climax",
             "objective": "Pass lock 21 with the sweep at its floor tempo and the target at its minimum",
             "start_state": "The sweep is at its fastest and the target at its narrowest",
             "end_state": "The run ends on a missed tap and the best lock count is stamped",
             "mechanics": ["timed-tap", "streak", "tempo"],
             "difficulty": {"speed": 0.55, "density": 0.35, "variety": 0.32, "precision": 0.6},
             "expected_duration_s": 25,
             "success": "Lock 21 lands with the sweep at its 0.6 s floor and the target at 12 degrees",
             "failure": "Two full sweeps pass without a landed tap once the floor tempo is reached",
             "acceptance": [
                 "The sweep of tier 3 never drops below 0.6 s a turn however long the run lasts",
                 "The target of tier 3 holds at 12 degrees and narrows no further",
             ],
             "variation_from_previous": ["tempo", "pattern_set", "objective"],
             "parameters": {"sweep_floor_s": 0.6, "min_target_degrees": 12, "locks": 21}},
        ],
    },
}

# The grid puzzle's twenty levels, as a table: the purpose the level serves, the goal colours
# in play, how long it is designed to take, which axis it raises over the level before it, and
# the variety dimensions it changes. The move budget is 25 minus the level number, so every
# level states a different budget and the tightness against the clean solution rises.
_LEVELS = (
    # n, purpose, colours, seconds, difficulty, variation
    (1, "teach", 1, 30, (0.1, 0.1, 0.15, 0.15), []),
    (2, "teach", 1, 34, (0.18, 0.1, 0.15, 0.15), ["objective", "pacing"]),
    (3, "test", 2, 38, (0.18, 0.18, 0.15, 0.15), ["objective", "board_shape"]),
    (4, "twist", 2, 42, (0.18, 0.18, 0.15, 0.25), ["rule_twist", "board_shape"]),
    (5, "breather", 2, 36, (0.18, 0.18, 0.15, 0.25), ["pacing", "board_shape"]),
    (6, "test", 2, 44, (0.26, 0.18, 0.15, 0.25), ["objective", "blocker_set"]),
    (7, "twist", 2, 48, (0.26, 0.26, 0.15, 0.25), ["rule_twist", "pacing"]),
    (8, "test", 2, 50, (0.26, 0.26, 0.25, 0.25), ["board_shape", "blocker_set"]),
    (9, "breather", 3, 46, (0.26, 0.26, 0.25, 0.25), ["pacing", "objective"]),
    (10, "twist", 3, 54, (0.26, 0.26, 0.25, 0.35), ["rule_twist", "blocker_set"]),
    (11, "test", 3, 58, (0.34, 0.26, 0.25, 0.35), ["objective", "pacing"]),
    (12, "climax", 3, 62, (0.44, 0.36, 0.25, 0.45), ["board_shape", "rule_twist", "pacing"]),
    (13, "test", 3, 66, (0.48, 0.38, 0.28, 0.48), ["objective", "board_shape"]),
    (14, "twist", 3, 68, (0.5, 0.4, 0.28, 0.5), ["rule_twist", "blocker_set"]),
    (15, "breather", 3, 70, (0.5, 0.4, 0.3, 0.5), ["pacing", "objective"]),
    (16, "test", 4, 72, (0.54, 0.44, 0.3, 0.54), ["objective", "blocker_set"]),
    (17, "twist", 4, 74, (0.56, 0.46, 0.32, 0.56), ["rule_twist", "board_shape"]),
    (18, "test", 4, 76, (0.58, 0.48, 0.32, 0.58), ["objective", "pacing"]),
    (19, "breather", 4, 78, (0.58, 0.48, 0.34, 0.58), ["pacing", "blocker_set"]),
    (20, "climax", 4, 80, (0.64, 0.54, 0.34, 0.62), ["board_shape", "rule_twist", "objective"]),
)
_PUZZLE_AXES = ("depth", "move-limit", "board-complexity", "piece-variety")
_PUZZLE_MVP = 12


def _grid_levels():
    """The grid puzzle's levels from `_LEVELS`: levels 1-12 are the MVP, 13-20 the set a
    release carries. Every level states a different move budget, a different solution length
    and a different designed duration, so no two levels accept the same thing."""
    units = []
    for number, purpose, colours, seconds, readings, variation in _LEVELS:
        # Disjoint number spaces, deliberately: a level's number, its move budget and its
        # solution length never collide with another level's, so no two acceptance lines read
        # alike (content.acceptance_specific).
        goals = 12 + 2 * number
        moves = 24 + number
        solution = moves - 4
        mvp = number <= _PUZZLE_MVP
        palette = f"{colours} goal colour" + ("" if colours == 1 else "s")
        units.append({
            "id": f"level-{number:02d}",
            "index": number,
            "tier": "mvp" if mvp else "post-mvp",
            "purpose": purpose if mvp else "bonus",
            "objective": (f"Clear the {goals} counters of level {number}, in {palette}, "
                          f"inside {moves} moves"),
            "start_state": f"A 7x7 board set out as level {number}, with {palette} counted",
            "end_state": f"Level {number} is cleared and its star count is stamped on the map",
            "mechanics": ["board", "swap-resolve", "level-goal"],
            "introduces": ["board", "swap-resolve", "level-goal"] if number == 1 else [],
            "difficulty": dict(zip(_PUZZLE_AXES, readings)),
            "expected_duration_s": seconds,
            "success": (f"Every goal counter of level {number} reaches zero with at least 1 of "
                        f"its {moves} moves unspent"),
            "failure": (f"The {moves} moves of level {number} run out with goal counters left, "
                        f"and the same board is offered again"),
            "acceptance": [
                f"A recorded solution clears level {number} in {solution} moves of its {moves}, "
                f"and the level data stores that length",
                f"A bot swapping at random fails level {number} in more than 90% of attempts "
                f"inside its {seconds} s",
            ],
            "variation_from_previous": list(variation),
            "parameters": {"moves": moves, "goal_counters": goals, "goal_colours": colours,
                           "solution_moves": solution},
        })
    return units


CONTENT["merge-puzzle"] = {
    "unit_kind": "level",
    "generation": {"mode": "authored",
                   "parameters": {"cols": 7, "rows": 7, "goal_colours_max": 4}},
    "units": _grid_levels(),
}


def _attach_content():
    """Every archetype carries its own content block, so an author reads one shape."""
    for archetype_id, block in CONTENT.items():
        ARCHETYPES[archetype_id]["content"] = block


_attach_content()

_WORD = re.compile(r"[a-z0-9][a-z0-9-]*")


def _text(strategy):
    parts = [strategy.get("one_liner", ""), strategy.get("why_this_opportunity", "")]
    parts += strategy.get("mvp") or []
    parts += strategy.get("prototype_must_prove") or []
    parts.append((strategy.get("audience") or {}).get("player_description", ""))
    return " ".join(parts).lower()


def concept_text(strategy):
    """The strategy's statement of the game itself: one-liner, core mechanic, core loop.

    Never the person's brief: research selected a concept the catalog declares buildable
    (`design_archetype`), and a brief's words re-picking the archetype would undo that. The
    brief is carried as `brief`; the `agent` author designs from it."""
    concept = strategy.get("concept") or {}
    parts = [strategy.get("one_liner", ""), concept.get("core_mechanic", ""), concept.get("core_loop", "")]
    return " ".join(p for p in parts if p).lower()


def _hits(terms, text):
    """Terms present in `text` as whole words (a hyphen separates words: seven-column)."""
    return [t for t in terms if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text)]


def dimension_of(strategy):
    """'2d' or '3d' when the strategy's research handoff states the art's dimension, else
    None. The value is research's (art.dimension), whatever its tier: a strategy that says
    2D is never designed as 3D by a keyword match."""
    research = (strategy or {}).get("research")
    if not isinstance(research, dict):
        return None
    value = (((research.get("art") or {}).get("dimension")) or {}).get("value")
    return value if value in ("2d", "3d") else None


def select(strategy, pinned=None):
    """Pick an archetype id for this strategy. Returns (id, reason).

    Only archetypes of the strategy's dimension (dimension_of) are considered when it states
    one; KeyError when no archetype renders it. Signature hits in the concept rank first,
    keyword hits in the whole strategy second, and declaration order breaks what is left, so
    the choice is stable.
    """
    if pinned:
        if pinned not in ARCHETYPES:
            raise KeyError(f"unknown archetype {pinned!r}; known: {', '.join(sorted(ARCHETYPES))}")
        return pinned, "pinned by the workflow step"

    dimension = dimension_of(strategy)
    candidates = {a: spec for a, spec in ARCHETYPES.items()
                  if dimension is None or spec.get("dimension") == dimension}
    if not candidates:
        raise KeyError(f"no design archetype renders {dimension}; the strategy's art is "
                       f"{dimension} - configure the agent design author (design: "
                       f"{{author: agent}}) to design it")
    text = _text(strategy)
    concept = concept_text(strategy)
    words = set(_WORD.findall(text))
    scores = {}
    for archetype_id, archetype in candidates.items():
        signature = _hits(archetype.get("signature") or [], concept)
        hits = [k for k in archetype["keywords"] if (k in words if " " not in k else k in text)]
        if signature or hits:
            scores[archetype_id] = (signature, hits)
    if not scores:
        fallback = FALLBACK if FALLBACK in candidates else next(iter(candidates))
        return fallback, ("no archetype keyword in the strategy; fell back to the simplest "
                          "shape" + (f" that renders {dimension}" if dimension else ""))
    order = list(ARCHETYPES)
    best = max(scores, key=lambda a: (len(scores[a][0]), len(scores[a][1]), -order.index(a)))
    signature, hits = scores[best]
    within = f" (among the {dimension} archetypes)" if dimension else ""
    if signature:
        return best, (f"strategy's concept names its core mechanic ({', '.join(signature)})"
                      + (f" and mentions {', '.join(hits)}" if hits else "") + within)
    return best, f"strategy mentions {', '.join(hits)}{within}"
