"""Evidence: where a market scan's facts come from, and the rules they must obey to count.

Three collectors, one output shape. Each produces `Source` records - a document that was
read - carrying `Observation`s - one falsifiable statement each, with the verbatim excerpt it
rests on and, optionally, machine-readable `facts` the analysis can use.

    ReferenceCollector   core/reference/platforms/*.yaml - the factory's own platform
                         profiles. Most are `status: unverified`, so what they say becomes a
                         hypothesis, never an observation.
    SnapshotCollector    <corpus>/snapshots/*.json - pages captured before the run, by a
                         person or an agent with web access. The normal way evidence enters.
    LiveCollector        <corpus>/probes.yaml - pages fetched during the run and searched
                         for a pattern. Off unless asked for; tests replace the fetcher.

What is refused, and why:

  * an observation with no excerpt - a statement nobody can check against its source is a
    hypothesis in disguise, and this is where the disguise is stripped;
  * a source dated after the scan - nothing can be observed in the future, so a future
    `observed_at` means the date, and probably the content, was made up;
  * a snapshot file that is not valid JSON or lacks its identity - that is a broken input,
    and the step fails rather than quietly scanning less than it was given.

A source older than the scoring model's evidence TTL is kept, marked stale, and its claims
carry lower confidence. Old evidence is still evidence; it is just not current.
"""

import glob
import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone

from wgflib import paths
from wgflib.yamllite import YamlError, load_file

__all__ = [
    "EvidenceError",
    "Observation",
    "Source",
    "Gap",
    "FACT_KEYS",
    "SOURCE_KINDS",
    "ReferenceCollector",
    "SnapshotCollector",
    "LiveCollector",
    "UrllibFetcher",
    "FetchError",
    "parse_time",
    "format_time",
]

SOURCE_KINDS = (
    "portal-listing", "portal-docs", "analytics", "playtest", "market-report",
    "competitor-teardown", "community", "internal-history", "other",
)

# The machine-readable facts a source may assert. Anything else in `facts` is ignored and
# reported, because an analysis that silently drops a fact it cannot read looks identical
# to one that read it.
FACT_KEYS = {
    "ads.rewarded": bool,
    "ads.interstitial": bool,
    "ads.banner": bool,
    "iap": bool,
    "max_bundle_mb": (int, float),
    "locales_required": list,
    "sdk_required": bool,
    "mobile_support_expected": bool,
    "web_exclusive": bool,
    "review_days": list,
    "monthly_players": (int, float),
    "category": dict,
    "reference_title": dict,
}

_SNAPSHOT_ID = re.compile(r"^snap-[a-z0-9][a-z0-9-]*$")
_PROBE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
# A source may be up to a day "ahead" of the scan: clocks and time zones disagree.
_CLOCK_SKEW = timedelta(days=1)


class EvidenceError(ValueError):
    """An evidence input is malformed. Not retryable: the file will be just as broken."""


class FetchError(RuntimeError):
    """A live fetch failed. Retryable: networks recover."""


def parse_time(text):
    if not isinstance(text, str):
        raise ValueError(f"not a timestamp: {text!r}")
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_time(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Observation:
    __slots__ = ("source", "index", "statement", "excerpt", "subject", "facts", "tags",
                 "metric")

    def __init__(self, source, index, statement, excerpt, subject=None, facts=None,
                 tags=None, metric=None):
        self.source = source
        self.index = index
        self.statement = statement
        self.excerpt = excerpt
        self.subject = dict(subject or {})
        self.facts = dict(facts or {})
        self.tags = list(tags or [])
        self.metric = metric

    @property
    def platform(self):
        return self.subject.get("platform") or self.source.platform


class Source:
    """One document read by the scan."""

    def __init__(self, id, source_uri, source_kind, observed_at, collector, title=None,
                 platform=None, digest=None, external=True):
        self.id = id
        self.source_uri = source_uri
        self.source_kind = source_kind
        self.observed_at = observed_at
        self.collector = collector
        self.title = title
        self.platform = platform
        self.digest = digest
        self.external = external
        self.fresh = True
        self.observations = []

    def to_dict(self):
        out = {
            "id": self.id,
            "source_uri": self.source_uri,
            "source_kind": self.source_kind,
            "observed_at": format_time(self.observed_at),
            "collector": self.collector,
            "fresh": self.fresh,
            "observations": len(self.observations),
        }
        if self.title:
            out["title"] = self.title
        if self.platform is not None:
            out["platform"] = self.platform
        return out


class Gap:
    def __init__(self, kind, description, source_id=None, platform=None):
        self.kind = kind
        self.description = description
        self.source_id = source_id
        self.platform = platform

    def to_dict(self):
        out = {"kind": self.kind, "description": self.description}
        if self.source_id:
            out["source_id"] = self.source_id
        if self.platform:
            out["platform"] = self.platform
        return out


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _display_path(path):
    """Repository-relative when inside the repository, so reports do not leak a home dir."""
    relative = os.path.relpath(os.path.abspath(path), paths.ROOT)
    return path if relative.startswith("..") else relative.replace(os.sep, "/")


def _clean_facts(facts, source_id, gaps):
    kept = {}
    for key, value in (facts or {}).items():
        expected = FACT_KEYS.get(key)
        if expected is None:
            gaps.append(Gap("rejected-observation", f"unknown fact key {key!r} ignored",
                            source_id=source_id))
        elif isinstance(value, bool) and expected is not bool:
            gaps.append(Gap("rejected-observation", f"fact {key!r} has the wrong type",
                            source_id=source_id))
        elif not isinstance(value, expected):
            gaps.append(Gap("rejected-observation", f"fact {key!r} has the wrong type",
                            source_id=source_id))
        else:
            kept[key] = value
    return kept


# -- reference: the factory's platform profiles ---------------------------------------------


class ReferenceCollector:
    """Reads platform profiles. Their content is instance-independent reference data, and
    most of it is marked unverified by its own authors - the analysis treats it that way."""

    id = "platform-profiles"
    kind = "reference"

    def __init__(self, directory):
        self.directory = directory

    def profiles(self, platform_ids=None):
        found = {}
        for path in sorted(glob.glob(os.path.join(self.directory, "*.yaml"))):
            pid = os.path.basename(path)[:-5]
            if platform_ids is not None and pid not in platform_ids:
                continue
            try:
                profile = load_file(path)
            except YamlError as exc:
                raise EvidenceError(f"{path}: {exc}")
            with open(path, "rb") as handle:
                profile["_digest"] = _digest(handle.read())
            profile["_path"] = _display_path(path)
            found[pid] = profile
        return found


# -- snapshots: evidence captured before the run --------------------------------------------


class SnapshotCollector:
    id = "snapshots"
    kind = "snapshot"

    def __init__(self, directory):
        self.directory = directory

    def status(self):
        if not os.path.isdir(self.directory):
            return "unavailable", f"no snapshot directory at {self.directory}"
        return None, None

    def collect(self, as_of, ttl_days, gaps):
        sources = []
        if not os.path.isdir(self.directory):
            return sources
        for path in sorted(glob.glob(os.path.join(self.directory, "*.json"))):
            with open(path, "rb") as handle:
                raw = handle.read()
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvidenceError(f"{os.path.basename(path)}: not valid JSON: {exc}")
            source = self._source(document, os.path.basename(path), _digest(raw), as_of,
                                  ttl_days, gaps)
            if source is not None:
                sources.append(source)
        return sources

    def _source(self, doc, name, digest, as_of, ttl_days, gaps):
        if not isinstance(doc, dict):
            raise EvidenceError(f"{name}: a snapshot must be a JSON object")
        sid = doc.get("id")
        if not isinstance(sid, str) or not _SNAPSHOT_ID.match(sid):
            raise EvidenceError(f"{name}: id must match snap-<kebab-case>, got {sid!r}")
        for key in ("source_uri", "source_kind", "observed_at"):
            if not doc.get(key):
                raise EvidenceError(f"{name}: missing {key}")
        if doc["source_kind"] not in SOURCE_KINDS:
            raise EvidenceError(f"{name}: unknown source_kind {doc['source_kind']!r}")
        try:
            observed_at = parse_time(doc["observed_at"])
        except ValueError:
            raise EvidenceError(f"{name}: observed_at is not an ISO 8601 timestamp")
        if not isinstance(doc.get("observations"), list):
            raise EvidenceError(f"{name}: observations must be a list")

        if observed_at > as_of + _CLOCK_SKEW:
            gaps.append(Gap("rejected-observation",
                            f"source is dated {doc['observed_at']}, after the scan; refused",
                            source_id=sid))
            return None

        source = Source(sid, doc["source_uri"], doc["source_kind"], observed_at, self.id,
                        title=doc.get("title"), platform=doc.get("platform"), digest=digest)
        source.fresh = (as_of - observed_at) <= timedelta(days=ttl_days)
        if not source.fresh:
            gaps.append(Gap("stale-source",
                            f"observed {doc['observed_at']}, older than {ttl_days} days",
                            source_id=sid, platform=source.platform))

        for index, item in enumerate(doc["observations"]):
            if not isinstance(item, dict):
                gaps.append(Gap("rejected-observation", f"observation {index} is not an object",
                                source_id=sid))
                continue
            statement = (item.get("statement") or "").strip()
            excerpt = (item.get("excerpt") or "").strip()
            if len(statement) < 8:
                gaps.append(Gap("rejected-observation",
                                f"observation {index} has no statement", source_id=sid))
                continue
            if not excerpt:
                gaps.append(Gap("rejected-observation",
                                f"observation {index} has no verbatim excerpt; "
                                f"an uncheckable statement is not an observation",
                                source_id=sid))
                continue
            metric = item.get("metric")
            if metric is not None and not (isinstance(metric, dict) and "name" in metric
                                           and isinstance(metric.get("value"), (int, float))):
                metric = None
            source.observations.append(Observation(
                source, index, statement, excerpt,
                subject={k: v for k, v in (item.get("subject") or {}).items()
                         if k in ("genre", "mechanic", "platform", "audience", "dimension")
                         and isinstance(v, str)},
                facts=_clean_facts(item.get("facts"), sid, gaps),
                tags=[t for t in item.get("tags") or [] if isinstance(t, str)],
                metric=metric,
            ))
        return source


# -- live: pages fetched during the run -----------------------------------------------------


class UrllibFetcher:
    """The only code in the module that touches the network. Standard library only."""

    def __init__(self, timeout=20, max_bytes=3_000_000):
        self.timeout = timeout
        self.max_bytes = max_bytes

    def __call__(self, url):
        import urllib.error
        import urllib.request

        if not url.startswith("https://"):
            raise FetchError(f"refusing non-https url {url}")
        request = urllib.request.Request(url, headers={
            "User-Agent": "wgf-discovery/1 (+market scan; respects robots and rate limits)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(self.max_bytes)
                charset = response.headers.get_content_charset() or "utf-8"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise FetchError(f"{url}: {exc}")
        return body.decode(charset, errors="replace")


_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def page_text(markup):
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", markup))).strip()


def page_title(markup):
    match = _TITLE.search(markup)
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip() if match else None


class LiveCollector:
    """Fetches each probe's page and searches it for the probe's pattern.

    A match becomes an observation whose excerpt is the text around the match - so the claim
    carries exactly the words it rests on. A miss is a gap, never a negative claim: a page
    not containing a word is not evidence that the portal lacks the feature.
    """

    id = "live-probes"
    kind = "live"

    def __init__(self, probes_path, fetcher=None, clock=None, context_chars=140):
        self.probes_path = probes_path
        self.fetcher = fetcher or UrllibFetcher()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.context_chars = context_chars

    def probes(self):
        if not os.path.exists(self.probes_path):
            return []
        try:
            document = load_file(self.probes_path) or {}
        except YamlError as exc:
            raise EvidenceError(f"{self.probes_path}: {exc}")
        probes = document.get("probes") or []
        for probe in probes:
            for key in ("id", "url", "pattern", "statement", "source_kind"):
                if not probe.get(key):
                    raise EvidenceError(f"probe {probe.get('id')!r}: missing {key}")
            if not _PROBE_ID.match(probe["id"]):
                raise EvidenceError(f"probe id {probe['id']!r} is not kebab-case")
            if probe["source_kind"] not in SOURCE_KINDS:
                raise EvidenceError(f"probe {probe['id']}: unknown source_kind")
        return probes

    def collect(self, gaps):
        sources, failures = [], 0
        probes = self.probes()
        pages = {}
        for probe in probes:
            url = probe["url"]
            if url not in pages:
                try:
                    pages[url] = (self.fetcher(url), self.clock())
                except FetchError as exc:
                    pages[url] = (None, None)
                    gaps.append(Gap("collector-failure", str(exc), platform=probe.get("platform")))
            markup, fetched_at = pages[url]
            if markup is None:
                failures += 1
                continue
            text = page_text(markup)
            match = re.search(probe["pattern"], text)
            sid = f"live-{probe['id']}"
            if not match:
                gaps.append(Gap("probe-miss",
                                f"pattern {probe['pattern']!r} not found at {url}; "
                                f"no claim made either way",
                                source_id=sid, platform=probe.get("platform")))
                continue
            start = max(0, match.start() - self.context_chars)
            end = min(len(text), match.end() + self.context_chars)
            source = Source(sid, url, probe["source_kind"], fetched_at, self.id,
                            title=page_title(markup), platform=probe.get("platform"),
                            digest=_digest(markup.encode("utf-8")))
            subject = dict(probe.get("subject") or {})
            if probe.get("platform"):
                subject.setdefault("platform", probe["platform"])
            source.observations.append(Observation(
                source, 0, probe["statement"], text[start:end].strip(), subject=subject,
                facts=_clean_facts(probe.get("facts"), sid, gaps),
                tags=list(probe.get("tags") or []) + ["live"],
            ))
            sources.append(source)
        return sources, len(probes), failures
