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

__all__ = ["ARCHETYPES", "FALLBACK", "select"]

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
        "content_unit_kind": "obstacle sets",
        "retention_hooks": ["progression", "streak"],
        "return_reason": "I was so close to my best, and I know exactly what I did wrong.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "lane-switch", "name": "Lane switching", "tier": "mvp",
             "description": "The player occupies one of three lanes and moves one lane per input.",
             "rules": ["Three lanes; the player starts in the middle one.",
                       "One input moves exactly one lane; inputs during a move are queued, at most one.",
                       "A lane move completes in 120 ms; the player is collidable in the destination lane from its midpoint."],
             "parameters": {"lanes": 3, "move_ms": 120, "input_queue": 1}},
            {"id": "obstacles", "name": "Obstacles", "tier": "mvp",
             "description": "Obstacles spawn ahead in patterns drawn from obstacle sets and approach at the run speed.",
             "rules": ["At least one lane is always passable in every spawned row.",
                       "Contact with an obstacle ends the run.",
                       "Patterns come from the active obstacle set; sets unlock by elapsed run time."],
             "parameters": {"start_speed": 6.0, "row_gap_s": 1.1, "min_row_gap_s": 0.45}},
            {"id": "distance-score", "name": "Distance score", "tier": "mvp",
             "description": "Score is distance travelled, with a multiplier for consecutive near-misses.",
             "rules": ["Score increases continuously with distance.",
                       "Passing an obstacle in an adjacent lane within 150 ms is a near-miss and adds 1 to the multiplier, max 5.",
                       "A lane change that is not a near-miss leaves the multiplier as it is; a run end resets it."],
             "parameters": {"max_multiplier": 5, "near_miss_ms": 150}},
            {"id": "pickups", "name": "Pickups", "tier": "post-mvp",
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
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Vector-drawn; 8 run frames, 2 hit frames, 128px"},
            {"id": "obstacles", "type": "sprite", "tier": "mvp", "description": "Obstacle shapes, one per set",
             "count": 3, "source_preference": "procedural", "est_cost": 0, "spec": "Vector-drawn, lane-width, readable at 64px"},
            {"id": "track", "type": "texture", "tier": "mvp", "description": "Scrolling lane surface and parallax background",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Tileable 512px, 2 parallax layers"},
            {"id": "pickup", "type": "sprite", "tier": "post-mvp", "description": "Pickup collectible",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "64px, idle spin"},
            {"id": "hit-vfx", "type": "vfx", "tier": "mvp", "description": "Hit burst and near-miss streak",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets"},
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
        "content_unit_kind": "piece levels in the drop ramp",
        "retention_hooks": ["progression", "streak"],
        "return_reason": "I saw the cascade that would have saved that track, and I want to set it up again.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "track", "name": "Seven-column track", "tier": "mvp",
             "description": "A single row of seven column cells; each cell is empty or holds one numbered piece.",
             "rules": ["The track has seven columns and one row; a column holds at most one piece.",
                       "A piece shows its level as a numeral and as a size or shape, never by colour alone.",
                       "A new run starts with an empty track."],
             "parameters": {"columns": 7}},
            {"id": "drop", "name": "Drop a piece", "tier": "mvp",
             "description": "The player drops the next numbered piece into the column they choose with one tap.",
             "rules": ["The next piece's level is shown before it is dropped.",
                       "A drop lands in the chosen column only if that column is empty; a drop onto a full column is refused and costs nothing.",
                       "Every drop is resolved (merges and cascades) before the next drop is accepted."]},
            {"id": "merge-cascade", "name": "Merge and cascade", "tier": "mvp",
             "description": "Two horizontally adjacent pieces of the same level merge into one piece of the next level, and the merge cascades.",
             "rules": ["Equal adjacent pieces merge into one piece of level + 1 in the left cell; the right cell empties.",
                       "After a merge, pieces slide left to close the gap, so a newly adjacent equal pair merges too; this repeats until no pair is left.",
                       "Each merge scores the level it produced."],
             "parameters": {"score_per_merge": "the merged level"}},
            {"id": "drop-ramp", "name": "Drop-level ramp", "tier": "mvp",
             "description": "The level of the next piece rises with the number of merges made, so the track fills faster over time.",
             "rules": ["The next piece's level is 1 + floor(merges / 4), capped at 4.",
                       "The ramp is data-driven: one table, no hand-built levels."],
             "parameters": {"merges_per_level_up": 4, "max_drop_level": 4}},
            {"id": "full-track", "name": "Full track ends the run", "tier": "mvp",
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
             "count": 6, "source_preference": "procedural", "est_cost": 0, "spec": "Vector, 96px, level readable by numeral and size"},
            {"id": "track-frame", "type": "ui", "tier": "mvp", "description": "Track frame and column backing",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "9-slice"},
            {"id": "merge-vfx", "type": "vfx", "tier": "mvp", "description": "Merge burst and cascade streak",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets"},
        ],
        "audio": [
            {"id": "music-loop", "type": "music", "tier": "mvp", "description": "Calm loop",
             "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "sfx-drop", "type": "sfx", "tier": "mvp", "description": "Piece drop thunk", "trigger": "Drop",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-merge", "type": "sfx", "tier": "mvp", "description": "Merge pop, pitched per cascade step",
             "trigger": "Merge", "loop": False, "source_preference": "library", "est_cost": 5},
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
        "content_units": 12,
        "content_unit_kind": "levels",
        "retention_hooks": ["progression", "collection"],
        "return_reason": "There is a next level waiting and the last one ended on a good cascade.",
        "progression_model": "linear-levels",
        "difficulty_model": "level-authored",
        "mechanics": [
            {"id": "board", "name": "Board", "tier": "mvp",
             "description": "A 7x7 grid of pieces in five colours.",
             "rules": ["The board is 7x7; every cell holds one piece.",
                       "A new board never starts with a resolvable group already on it.",
                       "If no move exists, the board reshuffles with a visible animation and no penalty."],
             "parameters": {"cols": 7, "rows": 7, "colours": 5}},
            {"id": "swap-resolve", "name": "Swap and resolve", "tier": "mvp",
             "description": "Swapping two adjacent pieces resolves lines of three or more of one colour.",
             "rules": ["Only orthogonally adjacent pieces swap.",
                       "A swap that forms no line of three reverts and does not cost a move.",
                       "Resolved pieces clear, pieces above fall, new pieces fill from the top; new lines resolve as cascades."],
             "parameters": {"min_line": 3, "fall_ms": 180}},
            {"id": "level-goal", "name": "Level goal", "tier": "mvp",
             "description": "Each level asks for a number of pieces of given colours within a move limit.",
             "rules": ["Clearing a goal colour decrements its counter.",
                       "All counters at zero clears the level; remaining moves become bonus score.",
                       "Moves at zero with counters left fails the level."],
             "parameters": {"moves_level_1": 20, "moves_min": 12}},
            {"id": "special-pieces", "name": "Special pieces", "tier": "post-mvp",
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
             "count": 5, "source_preference": "procedural", "est_cost": 0, "spec": "Vector, 96px, distinct by shape as well as colour"},
            {"id": "board-frame", "type": "ui", "tier": "mvp", "description": "Board frame and cell backing",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "9-slice"},
            {"id": "clear-vfx", "type": "vfx", "tier": "mvp", "description": "Piece clear burst and cascade streak",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets"},
            {"id": "specials", "type": "sprite", "tier": "post-mvp", "description": "Row-clearer and bomb pieces",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Vector, 96px"},
            {"id": "backdrop", "type": "texture", "tier": "mvp", "description": "Background behind the board",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Gradient plus texture overlay"},
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
        "content_unit_kind": "speed tiers",
        "retention_hooks": ["progression", "streak"],
        "return_reason": "I know I can hold the line through one more speed-up.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "steering", "name": "Steering", "tier": "mvp",
             "description": "The craft drives forward on its own; the player steers it left and right across the arena.",
             "rules": ["The craft slides sideways at a fixed steer speed and cannot leave the arena's width.",
                       "Forward speed is never player-controlled; the walls' speed carries the drive."],
             "parameters": {"arena_half_width": 4, "steer_speed": 6}},
            {"id": "walls", "name": "Rushing walls", "tier": "mvp",
             "description": "Walls spawn ahead and rush toward the craft; the player steers between them.",
             "rules": ["Walls spawn at a fixed distance ahead at a fixed interval and move toward the craft.",
                       "Every wall row leaves a gap the craft can pass through.",
                       "A wall that passes the craft without a hit counts as cleared."],
             "parameters": {"spawn_interval_s": 0.9, "spawn_distance": 40}},
            {"id": "crash", "name": "Crash ends the run", "tier": "mvp",
             "description": "Hitting a wall is a crash, and a crash ends the run.",
             "rules": ["Any overlap of the craft with a wall is a crash.",
                       "The result card shows the score and the personal best."]},
            {"id": "speed-ramp", "name": "Speed ramp and score", "tier": "mvp",
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
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Primitive geometry, emissive edges"},
            {"id": "arena-kit", "type": "model", "tier": "mvp", "description": "Arena floor and side rails",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Primitive geometry, vertex colours"},
            {"id": "wall", "type": "model", "tier": "mvp", "description": "Neon wall segment",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Box plus emissive material"},
            {"id": "crash-vfx", "type": "vfx", "tier": "mvp", "description": "Crash burst",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Instanced particles"},
        ],
        "audio": [
            {"id": "music-drive", "type": "music", "tier": "mvp", "description": "Driving loop",
             "trigger": "Run start", "loop": True, "source_preference": "library", "est_cost": 40},
            {"id": "sfx-pass", "type": "sfx", "tier": "mvp", "description": "Wall pass whoosh", "trigger": "Wall cleared",
             "loop": False, "source_preference": "library", "est_cost": 5},
            {"id": "sfx-crash", "type": "sfx", "tier": "mvp", "description": "Crash impact", "trigger": "Crash",
             "loop": False, "source_preference": "library", "est_cost": 5},
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
        "content_unit_kind": "arenas",
        "retention_hooks": ["progression", "collection"],
        "return_reason": "I know a faster line through the second arena.",
        "progression_model": "unlock-track",
        "difficulty_model": "level-authored",
        "mechanics": [
            {"id": "steering", "name": "Steering", "tier": "mvp",
             "description": "The player vehicle accelerates automatically; the player only steers.",
             "rules": ["Forward speed ramps to max in 1.5 s and is never player-controlled in the MVP.",
                       "Steering input maps to yaw rate, not to position.",
                       "Touching the arena edge bounces the vehicle and removes 30% of speed; it never ends the run."],
             "parameters": {"max_speed": 22.0, "yaw_rate_deg_s": 140, "wall_speed_loss": 0.3}},
            {"id": "checkpoints", "name": "Target gates", "tier": "mvp",
             "description": "Gates light up one at a time; passing the lit gate extends the clock.",
             "rules": ["Exactly one gate is lit; passing it lights the next.",
                       "Each lit gate passed adds time to the clock.",
                       "The run ends when the clock reaches zero."],
             "parameters": {"start_clock_s": 20, "gate_bonus_s": 4}},
            {"id": "boost", "name": "Boost pads", "tier": "post-mvp",
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
             "count": 1, "source_preference": "library", "est_cost": 30, "spec": "GLB, under 5k triangles, one material"},
            {"id": "arena-kit", "type": "model", "tier": "mvp", "description": "Modular floor, wall and pillar pieces",
             "count": 6, "source_preference": "procedural", "est_cost": 0, "spec": "Primitive geometry, vertex colours"},
            {"id": "gate", "type": "model", "tier": "mvp", "description": "Target gate, lit and unlit",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Torus plus emissive material"},
            {"id": "skybox", "type": "texture", "tier": "mvp", "description": "Gradient sky",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Shader gradient, no texture fetch"},
            {"id": "gate-vfx", "type": "vfx", "tier": "mvp", "description": "Gate shatter",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Instanced particles"},
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
        "content_unit_kind": "tempo tiers",
        "retention_hooks": ["progression", "streak"],
        "return_reason": "One more run - I only need a couple more perfects.",
        "progression_model": "skill-only",
        "difficulty_model": "time-ramp",
        "mechanics": [
            {"id": "timed-tap", "name": "Timed tap", "tier": "mvp",
             "description": "A piece sweeps across a target; a tap locks it in place.",
             "rules": ["The piece sweeps at the current tempo; one tap locks it.",
                       "Overlap of 90% or more with the target is a perfect; any overlap is a hit; none is a miss.",
                       "A miss ends the run."],
             "parameters": {"start_sweep_s": 1.6, "perfect_overlap": 0.9}},
            {"id": "streak", "name": "Perfect streak", "tier": "mvp",
             "description": "Consecutive perfects build a streak that multiplies score.",
             "rules": ["Each perfect adds 1 to the streak; a hit resets it to 0.",
                       "Score per lock is 10 times (1 + streak)."],
             "parameters": {"base_points": 10}},
            {"id": "tempo", "name": "Tempo ramp", "tier": "mvp",
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
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Vector"},
            {"id": "target", "type": "sprite", "tier": "mvp", "description": "Target zone",
             "count": 1, "source_preference": "procedural", "est_cost": 0, "spec": "Vector"},
            {"id": "lock-vfx", "type": "vfx", "tier": "mvp", "description": "Perfect ring and shatter",
             "count": 2, "source_preference": "procedural", "est_cost": 0, "spec": "Particle presets"},
            {"id": "backdrop", "type": "texture", "tier": "mvp", "description": "Per-tier background",
             "count": 3, "source_preference": "procedural", "est_cost": 0, "spec": "Shader gradient"},
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

_WORD = re.compile(r"[a-z0-9][a-z0-9-]*")


def _text(strategy):
    parts = [strategy.get("one_liner", ""), strategy.get("why_this_opportunity", "")]
    parts += strategy.get("mvp") or []
    parts += strategy.get("prototype_must_prove") or []
    parts.append((strategy.get("audience") or {}).get("player_description", ""))
    return " ".join(parts).lower()


def concept_text(strategy):
    """The strategy's statement of the game itself: one-liner, core mechanic, core loop."""
    concept = strategy.get("concept") or {}
    parts = [strategy.get("one_liner", ""), concept.get("core_mechanic", ""), concept.get("core_loop", "")]
    return " ".join(p for p in parts if p).lower()


def _hits(terms, text):
    """Terms present in `text` as whole words (a hyphen separates words: seven-column)."""
    return [t for t in terms if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text)]


def select(strategy, pinned=None):
    """Pick an archetype id for this strategy. Returns (id, reason).

    Signature hits in the concept rank first, keyword hits in the whole strategy second, and
    declaration order breaks what is left, so the choice is stable.
    """
    if pinned:
        if pinned not in ARCHETYPES:
            raise KeyError(f"unknown archetype {pinned!r}; known: {', '.join(sorted(ARCHETYPES))}")
        return pinned, "pinned by the workflow step"

    text = _text(strategy)
    concept = concept_text(strategy)
    words = set(_WORD.findall(text))
    scores = {}
    for archetype_id, archetype in ARCHETYPES.items():
        signature = _hits(archetype.get("signature") or [], concept)
        hits = [k for k in archetype["keywords"] if (k in words if " " not in k else k in text)]
        if signature or hits:
            scores[archetype_id] = (signature, hits)
    if not scores:
        return FALLBACK, "no archetype keyword in the strategy; fell back to the simplest shape"
    order = list(ARCHETYPES)
    best = max(scores, key=lambda a: (len(scores[a][0]), len(scores[a][1]), -order.index(a)))
    signature, hits = scores[best]
    if signature:
        return best, (f"strategy's concept names its core mechanic ({', '.join(signature)})"
                      + (f" and mentions {', '.join(hits)}" if hits else ""))
    return best, f"strategy mentions {', '.join(hits)}"
