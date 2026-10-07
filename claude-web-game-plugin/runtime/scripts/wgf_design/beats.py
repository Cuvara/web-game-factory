"""The design a release is held to beyond its counts: references, the beat chart, the moments.

Two release-tier designs met every count of content.py - units, groups, elements, structure
kinds, a climax per group - and still played like a genre's first draft. A teach unit
introduced six mechanics (content.py checks only that a mechanic is introduced before it is
used), a climax was held only to distinct art, risk/reward and "a decision every few seconds"
were prose (core/craft/core-loop-and-difficulty.md), the designed play was five minutes, and
the design rested on no teardown of the genre's leaders (core/craft/competitive-teardown.md).
`check` holds a design at its quality tier to core/reference/quality-benchmark.yaml `design`
(1.7.0), on what game-design 1.15.0 declares (rules design.*):

  * `references`: the teardown records of the genre's leaders the strategy's research carries
    at teardown depth, at least `references.min_teardowns`, compared on every dimension of
    `references.dimensions` with the design line that answers it. A game the research did not
    tear down is never a reference. When the research carries too few, the design says
    `status: unknown` and the step routes the run to research (`research_gap`): a designer
    cannot write a teardown it did not play;
  * one mechanic introduced per unit (the game's first unit may also introduce the core verb,
    the mechanics of `progression_role: core`), in a teach, breather or twist unit - never on
    a test or a climax - and a teach unit no harder than the breather before it;
  * every unit's `beat`: a falsifiable claim and the observation that would falsify it, the
    most frequent decision and how often it recurs (at most `beats.max_decision_interval_s`);
  * every group (the whole sequence without groups) has a twist and ends in a climax, and
    every climax declares the state, phase, rule, arena or objective it changes - art alone
    is not a climax; every group offers a harder line for a payoff;
  * signature moments of each kind - an end-of-unit payoff, a combo or chain escalation, a
    rare spectacle - each built into a unit;
  * every meta system included for its player value or declined with a reason, and every
    meta-loop entry the design persists among the included ones;
  * a finite game carries the market's designed play (`designed_play.finite_min_s`), and a
    timed secondary goal is calibrated on people or set at least
    `par_calibration.min_human_to_bot_ratio` times the bot's time.

The bars bind at the tier that states them (`release`). Below it (`mvp`) the release bars are
read as advice: each rule records what a release would refuse, as a note and a warning, and
breaches nothing - so an MVP design written before 1.15.0 is judged as it was. A design with
no quality tier, or a run pinned to a benchmark before 1.7.0 (no `design` block), is held to
nothing here and each rule says why.
"""

import re

from . import content as content_rules

__all__ = ["RULES", "BENCHMARK_PATH", "BENCHMARK_SECTION", "META_PERSISTED", "design_bars",
           "check"]

# The rules, in evaluation order, with what each means in one line. The agent author is shown
# this table beside content.RULES.
RULES = (
    ("design.references_grounded",
     "At its tier the design rests on teardown records of the genre's leaders the research "
     "carries, compared on every reference dimension with the design line that answers it"),
    ("design.one_mechanic_per_unit",
     "A unit introduces one mechanic at most (the first may add the core verb), in a teach, "
     "breather or twist unit"),
    ("design.teach_eases",
     "A teach unit is no harder on any axis than the breather before it"),
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
_TIMED = re.compile(r"(?<![a-z])(par|time|timer|timed|seconds|clock|gold|speed|fast)(?![a-z])")
_INTRODUCES_IN = ("teach", "breather", "twist")


def design_bars(benchmark, tier):
    """{(section, key): value} - every quality-benchmark `design` bar stated at `tier`."""
    bars = {}
    for section, block in ((benchmark or {}).get(BENCHMARK_SECTION) or {}).items():
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
        """{game id: competitor} the research carries at teardown depth."""
        return {str(c.get("game")): c for c in self.research().get("competitors") or []
                if isinstance(c, dict) and c.get("depth") == "teardown" and c.get("game")}


# -- the rules ---------------------------------------------------------------------------
# Each returns (problems, measured, note); references also returns the research gap.


def _references(r):
    least = _num(r.bar("references", "min_teardowns"))
    wanted = [str(d) for d in r.bar("references", "dimensions") or []]
    if least is None and not wanted:
        return [], None, f"tier {r.tier} states no references bar", None
    least = int(least or 0)
    available = r.teardowns()
    fixture = sorted(g for g, c in available.items() if c.get("fixture"))
    refs = r.design.get("references")
    refs = refs if isinstance(refs, dict) else None
    problems, gap = [], None
    if len(available) < least:
        gap = (f"the research carries {len(available)} teardown record(s) of the genre's leaders"
               f"{' (' + ', '.join(sorted(available)) + ')' if available else ''}; a "
               f"{r.tier}-tier design rests on {least} (quality-benchmark "
               f"design.references.min_teardowns): play and record {least - len(available)} "
               f"more of the genre's leaders (core/craft/competitive-teardown.md, "
               f"`python3 scripts/wgf-corpus.py template`) and run research again")
        if refs is None or refs.get("status") != "unknown":
            problems.append(f"references: the research carries {len(available)} teardown "
                            f"record(s) and the design needs {least} - say so: `references` "
                            f"with status 'unknown' and the reason, never a game the research "
                            f"did not tear down")
        claimed = [str(t.get("game")) for t in (refs or {}).get("teardowns") or []
                   if isinstance(t, dict) and str(t.get("game")) not in available]
        if claimed:
            problems.append(f"references.teardowns names {', '.join(claimed)}, which the "
                            f"research did not tear down: a reference is a teardown record, "
                            f"never a game remembered")
        return problems, len(available), gap, gap
    if refs is None:
        problems.append(f"references is missing: compare the design with {least} or more of the "
                        f"research's teardowns ({', '.join(sorted(available))}) on "
                        f"{', '.join(wanted)}, each with the design line that answers it")
        return problems, 0, None, None
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
    note = f"{len(grounded)} teardown(s): {', '.join(grounded)}"
    if fixture:
        note += f"; {', '.join(fixture)} fixture records - test data, never evidence"
    return problems, len(grounded), note, None


def _one_mechanic(r):
    most = _num(r.bar("beats", "max_mechanics_introduced_per_unit"))
    if most is None:
        return [], None, f"tier {r.tier} states no introduction bar"
    problems, worst = [], 0
    for position, unit in enumerate(r.units):
        new = [str(i) for i in unit.get("introduces") or [] if i in r.mechanics]
        if position == 0:
            new = [i for i in new if r.mechanics[i].get("progression_role") != "core"]
        worst = max(worst, len(new))
        if len(new) > most:
            problems.append(f"{r.where(unit, 'introduces')} introduces {len(new)} mechanics "
                            f"({', '.join(new)}); a unit introduces {most:g} at most "
                            f"(quality-benchmark design.beats.max_mechanics_introduced_per_unit"
                            f"): teach one, let the player use it, then the next")
        if new and unit.get("purpose") not in _INTRODUCES_IN:
            problems.append(f"{r.where(unit)} introduces {', '.join(new)} on a "
                            f"{unit.get('purpose')!r} unit: a mechanic arrives in a teach, a "
                            f"breather or a twist, never on a test or a peak")
    return problems, worst, f"at most {worst} mechanic(s) introduced in one unit"


def _teach_eases(r):
    if _num(r.bar("beats", "max_mechanics_introduced_per_unit")) is None:
        return [], None, f"tier {r.tier} states no beat bar"
    problems, breather, checked = [], None, 0
    for unit in r.units:
        if unit.get("purpose") == "teach" and breather is not None:
            checked += 1
            harder = []
            for axis, value in sorted((unit.get("difficulty") or {}).items()):
                before = _num((breather.get("difficulty") or {}).get(axis))
                if _num(value) is not None and before is not None and value > before:
                    harder.append(f"{axis} {before:g} -> {value:g}")
            if harder:
                problems.append(f"{r.where(unit, 'difficulty')} teaches at {', '.join(harder)}, "
                                f"harder than the breather {breather.get('id')} before it: a "
                                f"teach unit is the safe place to meet something new")
        if unit.get("purpose") == "breather":
            breather = unit
    return problems, checked, f"{checked} teach unit(s) after a breather"


def _beat_chart(r):
    if not r.bars:
        return [], None, f"tier {r.tier} states no beat bar"
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
    same = [units for units in claims.values() if len(units) > 1]
    for units in same:
        problems.append(f"{_ids(units)} make the same claim: a beat says what THIS unit does "
                        f"to the player")
    stated = len(r.units) - len(missing)
    return problems, stated, f"{stated} of {len(r.units)} unit(s) state their beat"


def _group_arc(r):
    least = _num(r.bar("beats", "min_twist_per_group"))
    if least is None:
        return [], None, f"tier {r.tier} states no group-arc bar"
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
    return problems, len(r.groups()), f"{len(r.groups())} group(s) with a twist and a climax"


def _climax_changes(r):
    if r.bar("beats", "climax_changes_state") is not True:
        return [], None, f"tier {r.tier} states no climax bar"
    climaxes = [u for u in r.units if u.get("purpose") == "climax"]
    flat = [u for u in climaxes if not (r.beat(u).get("climax") or {}).get("change")]
    problems = []
    if flat:
        problems.append(f"{_ids(flat)} are climax units that declare no change: state in "
                        f"`beat.climax` the state, phase, rule, arena or objective that changes "
                        f"mid-unit and what the player does differently after it - a new "
                        f"drawing alone is the same unit wearing a costume")
    return problems, len(climaxes) - len(flat), \
        f"{len(climaxes) - len(flat)} of {len(climaxes)} climax(es) change state"


def _risk_reward(r):
    least = _num(r.bar("beats", "min_risk_reward_per_group"))
    if least is None:
        return [], None, f"tier {r.tier} states no risk/reward bar"
    problems, offered = [], 0
    for group, units in r.groups():
        count = sum(1 for u in units if r.beat(u).get("risk_reward"))
        offered += count
        if count < least:
            problems.append(f"{group} offers {count} harder line(s) for a payoff; every group "
                            f"offers {least:g} (quality-benchmark "
                            f"design.beats.min_risk_reward_per_group): a unit's "
                            f"`beat.risk_reward` names the riskier option and what it pays")
    return problems, offered, f"{offered} unit(s) offer a harder line for a payoff"


def _cadence(r):
    most = _num(r.bar("beats", "max_decision_interval_s"))
    if most is None:
        return [], None, f"tier {r.tier} states no decision-cadence bar"
    slow = []
    longest = 0
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
    return problems, longest, f"the slowest decision recurs every {longest:g} s"


def _moments(r):
    bars = [(kind, _num(r.bar("signature_moments", key))) for kind, key in _MOMENT_KINDS]
    bars = [(kind, least) for kind, least in bars if least is not None]
    if not bars:
        return [], None, f"tier {r.tier} states no signature-moment bar"
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
    return problems, len(moments), f"{len(moments)} signature moment(s)"


def _meta(r):
    if r.bar("meta_systems", "justified") is not True:
        return [], None, f"tier {r.tier} states no meta-system bar"
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
    return problems, included, f"{len(systems)} meta system(s) decided, {len(included)} included"


def _designed_play(r):
    floor = _num(r.bar("designed_play", "finite_min_s"))
    if floor is None:
        return [], None, f"tier {r.tier} states no market designed-play bar"
    if r.genre.get("ending") != "finite":
        return [], None, (f"the game's ending is {r.genre.get('ending')!r}: designed play is a "
                          f"finite game's bar")
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
    return problems, round(total, 1), f"{total:g} s designed; the market floor is {floor:g} s"


def _par(r):
    ratio = _num(r.bar("par_calibration", "min_human_to_bot_ratio"))
    if ratio is None:
        return [], None, f"tier {r.tier} states no par-calibration bar"
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
                            f"design.par_calibration.min_human_to_bot_ratio) - a bot clears "
                            f"faster than a first-time player")
    return problems, len(timed), f"{len(timed)} timed goal(s)"


_CHECKS = {
    "design.one_mechanic_per_unit": _one_mechanic,
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

assert set(_CHECKS) | {"design.references_grounded"} == {rule_id for rule_id, _ in RULES}


def _result(rule_id, measured, breached, note):
    return {"criterion_id": rule_id, "measured": measured, "breached": breached, "note": note}


def check(design, strategy=None, benchmark=None):
    """{problems, results, warnings, research_gap} for `design`.

    `problems` are what an author can repair, each prefixed with its rule id. `results` is one
    criterionResult per rule, recorded beside the content rules'. `warnings` are the rule ids a
    release would refuse that bind nothing at this tier. `research_gap` is set when the
    research carries too few teardowns for the tier - not the author's to repair: the run goes
    back to research. `benchmark` is core/reference/quality-benchmark.yaml as the run pinned
    it (read live when None).
    """
    tier, where = content_rules.quality_tier(design, strategy)
    if benchmark is None:
        benchmark = content_rules.load_benchmark()
    version = (benchmark or {}).get("version")
    out = {"problems": [], "results": [], "warnings": [], "research_gap": None}
    if tier is None:
        out["results"] = [_result(rule_id, None, False, f"no quality tier, so no design bar: "
                                                        f"{where}") for rule_id, _ in RULES]
        return out
    if BENCHMARK_SECTION not in (benchmark or {}):
        out["results"] = [_result(rule_id, None, False,
                                  f"quality-benchmark {version} states no design bars")
                          for rule_id, _ in RULES]
        return out
    bars = design_bars(benchmark, tier)
    binding = bool(bars)
    if not binding:
        # Below the tier the bars are stated for: what a release would refuse, as advice.
        bars = design_bars(benchmark, "release")
    r = _Read(design, strategy, bars, tier if binding else "release")
    for rule_id, _meaning in RULES:
        if rule_id == "design.references_grounded":
            found, measured, note, gap = _references(r)
        else:
            (found, measured, note), gap = _CHECKS[rule_id](r), None
        if binding:
            breached = bool(found or gap)
            out["results"].append(_result(rule_id, measured, breached,
                                          "; ".join(found) if found else note))
            out["problems"] += [f"[{rule_id}] {problem}" for problem in found]
            if gap:
                out["research_gap"] = gap
        else:
            advice = list(found) + ([gap] if gap and gap not in found else [])
            if advice:
                out["warnings"].append(rule_id)
            out["results"].append(_result(
                rule_id, measured, False,
                (f"advisory at tier {tier}, binding at release: " + "; ".join(advice))
                if advice else f"tier {tier}: {note}"))
    return out
