"""The design contract beyond the counts: references, the beat chart, the moments. ADVISORY.

Two release-tier designs met every count of content.py - units, groups, elements, structure
kinds, a climax per group - and still played like a genre's first draft: the opening unit
introduced six mechanics (content.introductions_one_at_a_time exempts the opening unit; it
holds every unit after it), a climax was held only to distinct art, risk/reward and "a
decision every few seconds" were prose (core/craft/core-loop-and-difficulty.md), the designed
play was five minutes, and the design rested on no teardown of the genre's leaders
(core/craft/competitive-teardown.md). `view` reads a design at its quality tier against
core/reference/quality-benchmark.yaml `design` (1.7.0), on what game-design 1.18.0 declares,
for the twelve `design.*` rules of core/reference/design-consistency-rules.yaml (2.6.0):

  * `references`: the teardown records of the genre's leaders the strategy's research carries
    at teardown depth (fixture records are test data and never count), at least
    `references.min_teardowns`, compared on every dimension of `references.dimensions` with
    the design line that answers it. A game the research did not tear down is never a
    reference. When the research carries too few, the reference is UNKNOWN - reported, never
    filled in by the designer, and never a pass;
  * introductions placed: the opening unit introduces the core verb (mechanics of
    `progression_role: core`) and at most `beats.opening_max_new_mechanics` more mechanics;
    every later unit that debuts something (content.unit_debuts - the reading
    content.introductions_one_at_a_time counts, so the two cannot disagree on what a debut
    is) is a teach, breather or twist. How MANY a later unit debuts is
    content.introductions_one_at_a_time's alone (lesson L29): it is not counted here;
  * a teach unit that directly follows a breather is no harder on any axis than it;
  * every unit's `beat`: a falsifiable claim and its test, and the player's most frequent
    decision and how often it recurs (at most `beats.max_decision_interval_s`);
  * every group (the whole sequence without groups) has a twist and ends in a climax, every
    climax declares the state, phase, rule, arena or objective it changes - art alone is not
    a climax - and every group offers a harder line for a payoff;
  * signature moments of each kind - an end-of-unit payoff, a combo escalation, a rare
    spectacle - each built into a unit;
  * every meta system included for its player value or declined with a reason, and every
    meta-loop entry the design persists among the included ones;
  * a finite game carries the market's designed play (`designed_play.finite_min_s`), and a
    timed secondary goal is calibrated on people or set at least
    `par_calibration.min_human_to_bot_ratio` times the bot's time.

Every rule is ADVISORY: severity `warning` in the ruleset, so check-tiers.yaml classifies it
`advisory`, a breach is a warning carried to G3, and no design is refused, repaired or routed
on it. The bars are uncalibrated - `proposed` or `hypothesis`, no release has been measured
against them - and the references need a teardown corpus the Factory does not ship yet.
What would make one blocking is in docs/factory-quality-benchmark.md.

The bars apply at the tier that states them (`release`). Below it (`mvp`), and at a tier
with no bars (`premium`), nothing is breached and each rule's note says what a release would
be warned of. A design with no quality tier, or a run pinned to a benchmark before 1.7.0 (no
`design` block), is held to nothing here and each rule says why.
"""

import re

from . import content as content_rules

__all__ = ["RULES", "BENCHMARK_PATH", "BENCHMARK_SECTION", "META_PERSISTED", "Unreadable",
           "design_bars", "view"]

# The rules, in evaluation order, with what each means in one line. The ruleset
# (design-consistency-rules.yaml) lists the same ids; the agent author is shown this table.
RULES = (
    ("design.references_grounded",
     "At its tier the design rests on teardown records of the genre's leaders the research "
     "carries, compared on every reference dimension with the design line that answers it"),
    ("design.introductions_placed",
     "The opening unit introduces the core verb and at most one more mechanic; every later "
     "debut is in a teach, breather or twist unit"),
    ("design.teach_eases",
     "A teach unit right after a breather is no harder on any axis than that breather"),
    ("design.beat_chart_stated",
     "Every unit states its beat: a falsifiable claim, its test, and the player's decision"),
    ("design.group_arc",
     "Every group has a twist and ends in a climax"),
    ("design.climax_changes_state",
     "Every climax changes the state, phase, rules, arena or objective - not only the art"),
    ("design.risk_reward_offered",
     "Every group offers a harder line for a payoff"),
    ("design.decision_cadence",
     "The player's most frequent decision recurs every few seconds"),
    ("design.signature_moments",
     "The game has an end-of-unit payoff, a combo escalation and a rare spectacle, each in a unit"),
    ("design.meta_systems_justified",
     "Every meta system is included for a player value or declined, and every persisted one "
     "is included"),
    ("design.designed_play_market",
     "A finite game carries the designed play the genre's leaders carry"),
    ("design.par_calibrated",
     "A timed goal is calibrated on people, or at least the bar's multiple of the bot's time"),
)
PREFIX = "design."

# The benchmark as the run pins it (new-game `pinned_references`), relative to the Factory root.
BENCHMARK_PATH = "core/reference/quality-benchmark.yaml"
BENCHMARK_SECTION = "design"
# depth.meta_loop.persists kinds that are meta systems a player chooses to engage with (the
# rest - best-score, settings, stage-progress - are records, not systems).
META_PERSISTED = ("currency", "upgrades", "cosmetics", "achievements", "missions", "streak",
                  "collection", "unlocks")
_MOMENT_KINDS = (("end-of-unit-payoff", "min_end_of_unit_payoff"),
                 ("combo-escalation", "min_combo_escalation"),
                 ("rare-spectacle", "min_rare_spectacle"))
# A secondary goal is timed when its kind, id or description says so.
_TIMED = re.compile(r"(?<![a-z])(par|time|timer|timed|seconds|clock|speed|fast)(?![a-z])")


class Unreadable:
    """The run's pinned benchmark could not be read: every rule says so, none is breached."""

    def __init__(self, reason):
        self.reason = str(reason)


def design_bars(benchmark, tier):
    """{(section, key): value} - every quality-benchmark `design` bar stated at `tier`."""
    bars = {}
    if not isinstance(benchmark, dict):
        return bars
    for section, block in (benchmark.get(BENCHMARK_SECTION) or {}).items():
        for key, entry in (block or {}).items():
            if isinstance(entry, dict) and tier and entry.get(tier) is not None:
                bars[(section, key)] = entry[tier]
    return bars


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _ids(units, most=6):
    named = [str(u.get("id")) for u in units[:most]]
    return ", ".join(named) + (f" and {len(units) - most} more" if len(units) > most else "")


class _Read:
    """One design, read the way every rule reads it."""

    def __init__(self, design, strategy, bars, tier):
        self.design = design or {}
        self.strategy = strategy
        self.bars = bars
        self.tier = tier
        self.spec = self.design.get("build_spec") or {}
        content = self.spec.get("content")
        self.content = content if isinstance(content, dict) else {}
        self.mode = (self.content.get("generation") or {}).get("mode")
        self.units = [u for u in content_rules.units_of(self.design)
                      if u.get("tier") != "optional"]
        self.mechanics = {m.get("id"): m for m in self.spec.get("mechanics") or []
                          if isinstance(m, dict) and m.get("id")}
        genre = self.design.get("genre")
        self.genre = genre if isinstance(genre, dict) else {}

    def bar(self, section, key):
        return self.bars.get((section, key))

    def groups(self):
        """[(group id, its units in order)]; the whole sequence is one group without groups."""
        order, members = [], {}
        for unit in self.units:
            group = unit.get("group") or "the sequence"
            if group not in members:
                order.append(group)
            members.setdefault(group, []).append(unit)
        return [(group, members[group]) for group in order]

    def beat(self, unit):
        beat = unit.get("beat")
        return beat if isinstance(beat, dict) else {}

    def where(self, unit, field=None):
        at = f"build_spec.content.units[{unit.get('id')}]"
        return f"{at}.{field}" if field else at

    def research(self):
        """The research the references are checked against: the strategy's (the pinned input)
        - never what the design itself says it rests on. With no strategy (a design replayed on
        its own), the research the design carried."""
        source = self.strategy if self.strategy is not None else self.design
        research = (source or {}).get("research")
        return research if isinstance(research, dict) else {}

    def teardowns(self):
        """({game id: competitor} the research carries at teardown depth that are evidence,
        [fixture game ids] - test data, never evidence)."""
        found, fixture = {}, []
        for c in self.research().get("competitors") or []:
            if isinstance(c, dict) and c.get("depth") == "teardown" and c.get("game"):
                if c.get("fixture"):
                    fixture.append(str(c["game"]))
                else:
                    found[str(c["game"])] = c
        return found, sorted(fixture)


# -- the rules ---------------------------------------------------------------------------
# Each returns (problems, note).


def _references(r):
    least = _num(r.bar("references", "min_teardowns"))
    wanted = [str(d) for d in r.bar("references", "dimensions") or []]
    if least is None and not wanted:
        return [], f"tier {r.tier} states no references bar"
    least = int(least or 0)
    available, fixture = r.teardowns()
    refs = r.design.get("references")
    refs = refs if isinstance(refs, dict) else None
    problems = []
    if len(available) < least:
        # UNKNOWN, never a pass and never the designer's to fill in.
        problems.append(
            f"UNKNOWN: the research carries {len(available)} teardown record(s) of the genre's "
            f"leaders{' (' + ', '.join(sorted(available)) + ')' if available else ''}"
            f"{'; ' + ', '.join(fixture) + ' are fixture records, never evidence' if fixture else ''}"
            f" and a {r.tier}-tier design rests on {least} (quality-benchmark "
            f"design.references.min_teardowns): record {least - len(available)} more "
            f"(core/craft/competitive-teardown.md, `python3 scripts/wgf-corpus.py template`) and "
            f"research again")
        if refs is not None and refs.get("status") != "unknown":
            problems.append("references.status is not 'unknown' though the research carries too "
                            "few teardowns: a design never claims references the research does "
                            "not hold")
        claimed = [str(t.get("game")) for t in (refs or {}).get("teardowns") or []
                   if isinstance(t, dict) and str(t.get("game")) not in available]
        if claimed:
            problems.append(f"references.teardowns names {', '.join(claimed)}, which the "
                            f"research did not tear down: a reference is a teardown record, "
                            f"never a game remembered")
        return problems, f"UNKNOWN: {len(available)} teardown(s) of {least}"
    if refs is None:
        problems.append(f"references is missing: compare the design with {least} or more of the "
                        f"research's teardowns ({', '.join(sorted(available))}) on "
                        f"{', '.join(wanted)}, each with the design line that answers it")
        return problems, None
    if refs.get("status") != "grounded":
        problems.append(f"references.status is {refs.get('status')!r} but the research carries "
                        f"{len(available)} teardown record(s): compare the design with them")
    named = [str(t.get("game")) for t in refs.get("teardowns") or [] if isinstance(t, dict)]
    foreign = [g for g in named if g not in available]
    if foreign:
        problems.append(f"references.teardowns names {', '.join(foreign)}, which the research "
                        f"did not tear down ({', '.join(sorted(available))} it did): a "
                        f"reference is a teardown record, never a game remembered")
    grounded = sorted(set(named) - set(foreign))
    if len(grounded) < least:
        problems.append(f"references.teardowns names {len(grounded)} teardown record(s); a "
                        f"{r.tier}-tier design rests on {least} (quality-benchmark "
                        f"design.references.min_teardowns)")
    lines = {}
    for line in refs.get("dimensions") or []:
        if isinstance(line, dict):
            lines.setdefault(str(line.get("dimension")), []).append(line)
    missing = [d for d in wanted if d not in lines]
    if missing:
        problems.append(f"references.dimensions has no line for {', '.join(missing)}: what the "
                        f"references do there, and the design line that answers it")
    for dimension, entries in sorted(lines.items()):
        for line in entries:
            games = [str(g) for g in line.get("games") or []]
            stray = [g for g in games if g not in grounded]
            if not games or stray:
                problems.append(f"references.dimensions[{dimension}] reads "
                                f"{', '.join(stray) if stray else 'no game'}: each line reads "
                                f"the design's own teardowns ({', '.join(grounded) or 'none'})")
    return problems, f"{len(grounded)} teardown(s): {', '.join(grounded)}"


def _introductions(r):
    most = _num(r.bar("beats", "opening_max_new_mechanics"))
    allowed = r.bar("beats", "introduce_in")
    if most is None and not allowed:
        return [], f"tier {r.tier} states no introduction bar"
    problems = []
    debuts = content_rules.unit_debuts(r.units)
    if most is not None and debuts:
        opening, new = debuts[0]
        extra = [str(i) for i in new or [] if i in r.mechanics
                 and r.mechanics[i].get("progression_role") != "core"]
        if len(extra) > most:
            problems.append(f"{r.where(opening)} (the opening unit) introduces {len(extra)} "
                            f"mechanics beside the core verb ({', '.join(extra)}); it teaches "
                            f"the core verb and {most:g} more at most (quality-benchmark "
                            f"design.beats.opening_max_new_mechanics): give each of the rest a "
                            f"unit of its own")
    if allowed:
        for unit, new in debuts[1:]:
            if new and unit.get("purpose") not in allowed:
                problems.append(f"{r.where(unit)} debuts {', '.join(new)} on a "
                                f"{unit.get('purpose')!r} unit: something new arrives in a "
                                f"{', '.join(allowed)} unit, never on a test or a peak")
    points = sum(1 for _u, new in debuts if new)
    return problems, (f"{points} unit(s) debut something; how many each debuts after the "
                      f"opening is content.introductions_one_at_a_time's")


def _teach_eases(r):
    if r.bar("beats", "teach_no_harder_than_breather") is not True:
        return [], f"tier {r.tier} states no teach bar"
    problems, checked = [], 0
    for before, unit in zip(r.units, r.units[1:]):
        if unit.get("purpose") != "teach" or before.get("purpose") != "breather":
            continue
        checked += 1
        harder = []
        for axis, value in sorted((unit.get("difficulty") or {}).items()):
            prior = _num((before.get("difficulty") or {}).get(axis))
            if _num(value) is not None and prior is not None and value > prior:
                harder.append(f"{axis} {prior:g} -> {value:g}")
        if harder:
            problems.append(f"{r.where(unit, 'difficulty')} teaches at {', '.join(harder)}, "
                            f"harder than the breather {before.get('id')} right before it: a "
                            f"teach unit is the safe place to meet something new")
    return problems, f"{checked} teach unit(s) right after a breather"


def _beat_chart(r):
    if r.bar("beats", "beat_per_unit") is not True:
        return [], f"tier {r.tier} states no beat bar"
    missing = [u for u in r.units if not r.beat(u)]
    problems = []
    if missing:
        problems.append(f"{_ids(missing)} state no beat: give each unit a `beat` - the claim "
                        f"a playtest could falsify, the observation that would (`test`), and "
                        f"the player's most frequent `decision` and how often it recurs")
    claims = {}
    for unit in r.units:
        claim = _norm(r.beat(unit).get("claim"))
        if claim:
            claims.setdefault(claim, []).append(unit)
    for same in (units for units in claims.values() if len(units) > 1):
        problems.append(f"{_ids(same)} make the same claim: a beat says what THIS unit does "
                        f"to the player")
    stated = len(r.units) - len(missing)
    return problems, f"{stated} of {len(r.units)} unit(s) state their beat"


def _group_arc(r):
    least = _num(r.bar("beats", "min_twist_per_group"))
    if least is None:
        return [], f"tier {r.tier} states no group-arc bar"
    problems = []
    for group, units in r.groups():
        twists = sum(1 for u in units if u.get("purpose") == "twist")
        if twists < least:
            problems.append(f"{group} has {twists} twist unit(s): every group re-reads an old "
                            f"skill through a new rule at least {least:g} time(s) (quality-"
                            f"benchmark design.beats.min_twist_per_group)")
        if units[-1].get("purpose") != "climax":
            problems.append(f"{group} ends on {units[-1].get('id')} "
                            f"({units[-1].get('purpose')}), not a climax: a group closes on "
                            f"its hardest, most changed unit")
    return problems, f"{len(r.groups())} group(s)"


def _climax_changes(r):
    if r.bar("beats", "climax_changes_state") is not True:
        return [], f"tier {r.tier} states no climax bar"
    climaxes = [u for u in r.units if u.get("purpose") == "climax"]
    flat = [u for u in climaxes if not (r.beat(u).get("climax") or {}).get("change")]
    problems = []
    if flat:
        problems.append(f"{_ids(flat)} are climax units that declare no change: state in "
                        f"`beat.climax` the state, phase, rule, arena or objective that changes "
                        f"mid-unit and what the player does differently after it - a new "
                        f"drawing alone is the same unit wearing a costume")
    return problems, f"{len(climaxes) - len(flat)} of {len(climaxes)} climax(es) change state"


def _risk_reward(r):
    least = _num(r.bar("beats", "min_risk_reward_per_group"))
    if least is None:
        return [], f"tier {r.tier} states no risk/reward bar"
    problems, offered = [], 0
    for group, units in r.groups():
        count = sum(1 for u in units if r.beat(u).get("risk_reward"))
        offered += count
        if count < least:
            problems.append(f"{group} offers {count} harder line(s) for a payoff; every group "
                            f"offers {least:g} (quality-benchmark "
                            f"design.beats.min_risk_reward_per_group): a unit's "
                            f"`beat.risk_reward` names the riskier option and what it pays")
    return problems, f"{offered} unit(s) offer a harder line for a payoff"


def _cadence(r):
    most = _num(r.bar("beats", "max_decision_interval_s"))
    if most is None:
        return [], f"tier {r.tier} states no decision-cadence bar"
    slow, longest = [], 0
    for unit in r.units:
        every = _num((r.beat(unit).get("decision") or {}).get("every_s"))
        if every is None:
            continue
        longest = max(longest, every)
        if every > most:
            slow.append(f"{unit.get('id')} ({every:g} s)")
    problems = []
    if slow:
        problems.append(f"the decision recurs too rarely in {', '.join(slow)}: a player makes "
                        f"a nameable choice every {most:g} s or more often (quality-benchmark "
                        f"design.beats.max_decision_interval_s) - add the choice, not a timer")
    return problems, f"the slowest stated decision recurs every {longest:g} s"


def _moments(r):
    bars = [(kind, _num(r.bar("signature_moments", key))) for kind, key in _MOMENT_KINDS]
    bars = [(kind, least) for kind, least in bars if least is not None]
    if not bars:
        return [], f"tier {r.tier} states no signature-moment bar"
    moments = [m for m in r.content.get("signature_moments") or [] if isinstance(m, dict)]
    known = {m.get("id") for m in moments}
    used = {r.beat(u).get("signature_moment") for u in r.units} - {None}
    problems = []
    for kind, least in bars:
        count = sum(1 for m in moments if m.get("kind") == kind)
        if count < least:
            problems.append(f"build_spec.content.signature_moments has {count} {kind}; the game "
                            f"has {least:g} (quality-benchmark design.signature_moments): a "
                            f"moment a player retells, with what triggers it")
    stray = sorted(str(u) for u in used - known)
    if stray:
        problems.append(f"units name the signature moment(s) {', '.join(stray)}, which "
                        f"build_spec.content.signature_moments does not declare")
    idle = sorted(str(m) for m in known - used)
    if idle:
        problems.append(f"the signature moment(s) {', '.join(idle)} are built into no unit: "
                        f"name each in the `beat.signature_moment` of a unit that stages it")
    return problems, f"{len(moments)} signature moment(s)"


def _meta(r):
    if r.bar("meta_systems", "justified") is not True:
        return [], f"tier {r.tier} states no meta-system bar"
    systems = [m for m in r.content.get("meta_systems") or [] if isinstance(m, dict)]
    problems = []
    if not systems:
        problems.append("build_spec.content.meta_systems is empty: include each system above "
                        "the units for what the player gets from it, or decline it with why")
    decided = {}
    for entry in systems:
        decided.setdefault(entry.get("system"), set()).add(entry.get("decision"))
    both = sorted(str(s) for s, d in decided.items() if len(d) > 1)
    if both:
        problems.append(f"build_spec.content.meta_systems both includes and declines "
                        f"{', '.join(both)}")
    persists = (((r.spec.get("depth") or {}).get("meta_loop") or {}).get("persists") or [])
    kept = sorted({str(p.get("kind")) for p in persists if isinstance(p, dict)
                   and p.get("kind") in META_PERSISTED and p.get("tier") != "optional"})
    unjustified = [k for k in kept if "include" not in decided.get(k, set())]
    if unjustified:
        problems.append(f"build_spec.depth.meta_loop persists {', '.join(unjustified)}, which "
                        f"build_spec.content.meta_systems does not include for a player value")
    included = sorted(str(s) for s, d in decided.items() if "include" in d)
    return problems, f"{len(systems)} meta system(s) decided, {len(included)} included"


def _designed_play(r):
    floor = _num(r.bar("designed_play", "finite_min_s"))
    if floor is None:
        return [], f"tier {r.tier} states no market designed-play bar"
    if r.genre.get("ending") != "finite":
        return [], (f"the game's ending is {r.genre.get('ending')!r}: market designed play is "
                    f"a finite game's bar")
    durations = [_num(u.get("expected_duration_s")) or 0 for u in r.units]
    if r.mode in (None, "authored"):
        total, how = sum(durations), f"the {len(durations)} units"
    else:
        many = (r.content.get("generation") or {}).get("expected_units") or \
            (r.design.get("scope") or {}).get("content_units") or len(durations)
        mean = sum(durations) / float(len(durations)) if durations else 0
        total, how = mean * many, f"{many} {r.mode} units at the listed units' mean {mean:g} s"
    problems = []
    if total < floor - 1e-9:
        problems.append(f"{how} carry {total:g} s of designed play; a {r.tier}-tier finite game "
                        f"carries {floor:g} s, what the genre's leaders carry (quality-"
                        f"benchmark design.designed_play.finite_min_s, a hypothesis): "
                        f"{floor - total:g} s short - more units and more to do in them, "
                        f"not slower ones")
    return problems, f"{total:g} s designed; the market bar is {floor:g} s (a hypothesis)"


def _par(r):
    ratio = _num(r.bar("par_calibration", "min_human_to_bot_ratio"))
    if ratio is None:
        return [], f"tier {r.tier} states no par-calibration bar"
    timed = [g for g in r.content.get("secondary_goals") or [] if isinstance(g, dict)
             and _TIMED.search(" ".join(str(g.get(k) or "") for k in
                                        ("id", "kind", "description")).lower())]
    problems = []
    for goal in timed:
        par = goal.get("par") if isinstance(goal.get("par"), dict) else {}
        at = f"build_spec.content.secondary_goals[{goal.get('id')}]"
        if not par:
            problems.append(f"{at} is a timed goal with no `par` calibration: say whether its "
                            f"threshold comes from a person's playtest or is the bot's time "
                            f"times {ratio:g} or more")
        elif par.get("basis") == "bot-scaled" and (_num(par.get("ratio_to_bot")) or 0) < ratio:
            problems.append(f"{at}.par scales the bot's time by "
                            f"{par.get('ratio_to_bot')!r}; a par set from a bot is at least "
                            f"{ratio:g} times its time (quality-benchmark "
                            f"design.par_calibration.min_human_to_bot_ratio, a hypothesis) - "
                            f"a bot clears faster than a first-time player")
    return problems, f"{len(timed)} timed goal(s)"


_CHECKS = {
    "design.references_grounded": _references,
    "design.introductions_placed": _introductions,
    "design.teach_eases": _teach_eases,
    "design.beat_chart_stated": _beat_chart,
    "design.group_arc": _group_arc,
    "design.climax_changes_state": _climax_changes,
    "design.risk_reward_offered": _risk_reward,
    "design.decision_cadence": _cadence,
    "design.signature_moments": _moments,
    "design.meta_systems_justified": _meta,
    "design.designed_play_market": _designed_play,
    "design.par_calibrated": _par,
}

assert set(_CHECKS) == {rule_id for rule_id, _ in RULES}


def short(rule_id):
    """`design.group_arc` -> `group_arc`: the key the consistency projection reads."""
    return rule_id[len(PREFIX):]


def view(design, strategy=None, benchmark=None):
    """The consistency projection `design`: {"tier", "binding", "notes": {key: note},
    <key>: [problem]} for every rule (`key` is the rule id without `design.`).

    The problem lists are what the rules read: [] holds. They are filled only at a tier the
    benchmark states the bars for; below it each note says what a release would be warned of.
    `benchmark` is core/reference/quality-benchmark.yaml as the run pinned it (read live when
    None), or an `Unreadable` when the pinned copy could not be read.
    """
    out = {"tier": None, "binding": False, "notes": {}}
    for rule_id, _ in RULES:
        out[short(rule_id)] = []

    def say(note):
        for rule_id, _ in RULES:
            out["notes"][short(rule_id)] = note
        return out

    tier, where = content_rules.quality_tier(design, strategy)
    out["tier"] = tier
    if isinstance(benchmark, Unreadable):
        return say(f"advisory, not measured: the run's quality benchmark cannot be read "
                   f"({benchmark.reason})")
    if benchmark is None:
        benchmark = content_rules.load_benchmark()
    if tier is None:
        return say(f"no quality tier, so no design bar: {where}")
    if BENCHMARK_SECTION not in (benchmark or {}):
        return say(f"quality-benchmark {(benchmark or {}).get('version')} states no design bars")
    bars = design_bars(benchmark, tier)
    binding = bool(bars)
    out["binding"] = binding
    r = _Read(design, strategy, bars if binding else design_bars(benchmark, "release"),
              tier if binding else "release")
    for rule_id, _meaning in RULES:
        found, note = _CHECKS[rule_id](r)
        key = short(rule_id)
        if binding:
            out[key] = list(found)
            out["notes"][key] = (f"advisory: {note}" if note else "advisory")
        else:
            out["notes"][key] = (
                f"tier {tier} states no design bar; at release this would warn: "
                + "; ".join(found) if found else f"tier {tier} states no design bar"
                + (f"; at release: {note}" if note else ""))
    return out
