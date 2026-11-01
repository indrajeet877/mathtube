#!/usr/bin/env python3
"""Build MathTube's data/videos.json from the public Hacker News comment index.

Stdlib only. Run from anywhere:

    python3 scripts/build.py
    python3 scripts/build.py --self-test
    python3 scripts/build.py --from-cache
    python3 scripts/build.py --verify

The Algolia HN API caps a single query at 1,000 retrievable hits. Windows whose
reported nbHits exceed the hits actually returned are split on created_at_i.
Typo tolerance is disabled: with it on, "vimeo" matches "video" and "statquest"
matches "statues".
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
WINDOWS = CACHE / "windows"
OEMBED_PATH = CACHE / "oembed.json"
COMMENTS_PATH = CACHE / "comments.json"
OUT_PATH = ROOT / "data" / "videos.json"

UA = "MathTubeBuilder/1.0 (+https://github.com/indrajeet877/mathtube)"
ALGOLIA = "https://hn.algolia.com/api/v1/search_by_date"
FIREBASE = "https://hacker-news.firebaseio.com/v0/item/{id}.json"

# HN launched October 2006. End is "now" at runtime.
RANGE_START = 1160000000
MIN_RECOMMENDERS = 2
HITS_PER_PAGE = 1000

HOSTS = ("youtube", "youtu.be", "vimeo", "ted.com")

# Phrases crossed with a video host when the bare phrase exceeds 1,000 comments.
# Apostrophes are omitted on purpose; Algolia phrase queries use double quotes.
PHRASES = (
    "mathematics",
    "mathematical",
    "mathematician",
    "math lecture",
    "maths lecture",
    "mathematics lecture",
    "math course",
    "mathematics course",
    "linear algebra",
    "vector space",
    "eigenvalue",
    "eigenvector",
    "singular value decomposition",
    "gaussian elimination",
    "matrix calculus",
    "gilbert strang",
    "essence of linear algebra",
    "18.06",
    "number theory",
    "prime number",
    "prime numbers",
    "riemann hypothesis",
    "riemann zeta",
    "modular arithmetic",
    "quadratic reciprocity",
    "elliptic curve",
    "algebraic number theory",
    "analytic number theory",
    "p-adic",
    "fermat theorem",
    "real analysis",
    "complex analysis",
    "functional analysis",
    "measure theory",
    "lebesgue",
    "hilbert space",
    "banach space",
    "fourier series",
    "fourier transform",
    "fourier analysis",
    "epsilon-delta",
    "metric space",
    "taylor series",
    "calculus",
    "calculus lecture",
    "multivariable calculus",
    "vector calculus",
    "differential equations",
    "partial differential",
    "navier-stokes",
    "topology",
    "algebraic topology",
    "general topology",
    "point-set topology",
    "homotopy",
    "cohomology",
    "homology",
    "fundamental group",
    "manifold",
    "differential geometry",
    "algebraic geometry",
    "differential topology",
    "knot theory",
    "hyperbolic geometry",
    "euclidean geometry",
    "non-euclidean",
    "abstract algebra",
    "group theory",
    "ring theory",
    "galois theory",
    "commutative algebra",
    "representation theory",
    "lie group",
    "lie algebra",
    "category theory",
    "homological algebra",
    "combinatorics",
    "graph theory",
    "generating function",
    "generating functions",
    "probabilistic method",
    "probability theory",
    "probability lecture",
    "stochastic process",
    "stochastic processes",
    "markov chain",
    "markov chains",
    "monte carlo",
    "bayesian inference",
    "bayes theorem",
    "random variable",
    "probability",
    "set theory",
    "incompleteness theorem",
    "axiom of choice",
    "continuum hypothesis",
    "model theory",
    "proof theory",
    "type theory",
    "homotopy type theory",
    "proof assistant",
    "computability theory",
    "computational complexity",
    "math olympiad",
    "mathematical olympiad",
    "imo shortlist",
    "putnam",
    "olympiad",
    "information theory",
    "shannon entropy",
    "mutual information",
    "kolmogorov complexity",
    "kolmogorov",
    "channel capacity",
    "convex optimization",
    "convex optimisation",
    "mathematical optimization",
    "mathematical optimisation",
    "gradient descent",
    "lagrange multiplier",
    "linear programming",
    "machine learning",
    "deep learning",
    "neural network",
    "neural networks",
    "backpropagation",
    "backprop",
    "statistical learning",
    "learning theory",
    "vc dimension",
    "universal approximation",
    "kernel method",
    "kernel methods",
    "gaussian process",
    "gaussian processes",
    "variational inference",
    "reinforcement learning",
    "bias-variance",
    "automatic differentiation",
    "support vector machine",
    "convolutional neural",
    "cs229",
    "cs231n",
    "cs224n",
    "attention is all you need",
    "self-attention",
    "multi-head attention",
    "transformer architecture",
    "transformer model",
    "transformers explained",
    "illustrated transformer",
    "vision transformer",
    "large language model",
    "3blue1brown",
    "numberphile",
    "mathologer",
    "grant sanderson",
    "terence tao",
    "michael penn",
    "richard borcherds",
    "eigenchris",
    "mathemaniac",
    "oxford mathematics",
    "blackpenredpen",
    "pbs infinite series",
    "standupmaths",
    "steve brunton",
    "yannic kilcher",
    "statquest",
    "mathematical monk",
    "bright side of mathematics",
    "faculty of khan",
    "andrej karpathy",
    "karpathy",
    "andrew ng",
    "geoffrey hinton",
    "yann lecun",
    "vi hart",
    "tadashi tokieda",
    "hannah fry",
    "matt parker",
    "essence of calculus",
    "lockdown math",
    "quantum information",
    "principal component analysis",
    "naive bayes",
)

# Known maths channels. Poetic titles are kept. Matching is a casefold substring
# of the oEmbed author_name.
STRICT_CHANNELS = (
    "3blue1brown",
    "numberphile",
    "mathologer",
    "michael penn",
    "richard borcherds",
    "oxford mathematics",
    "bright side of mathematics",
    "faculty of khan",
    "dr peyam",
    "blackpenredpen",
    "flammable maths",
    "mathemaniac",
    "eigenchris",
    "aleph 0",
    "pbs infinite series",
    "math the beautiful",
    "mathematical monk",
    "standupmaths",
    "stand-up maths",
    "another roof",
    "morphocular",
    "epsilondelta",
    "trefor bazett",
    "wrath of math",
    "the math sorcerer",
    "prime newtons",
    "sybermath",
    "vi hart",
    "tadashi tokieda",
    "matt parker",
    "hannah fry",
    "think twice math",
    "seeing theory",
)

# Channels that are on-topic only when a lexicon phrase actually matches.
TOPIC_CHANNELS = (
    "statquest",
    "mutual information",
    "yannic kilcher",
    "artem kirsanov",
    "steve brunton",
    "deeplearningai",
    "deep learning ai",
    "andrej karpathy",
    "serrano.academy",
    "alexander amini",
    "mit opencourseware",
    "stanford online",
)

# Pop channels: the title itself must match. A mathy parent comment is not enough.
TITLE_ONLY_CHANNELS = (
    "two minute papers",
    "lex fridman",
    "ted-ed",
    "tedx",
)

# Longer specific phrases are tried first so "linear algebra" beats "algebra".
# specific=True phrases are enough on their own. specific=False also needs an
# educational cue in the same text (lecture, course, introduction, ...).
_RAW_RULES: list[tuple[str, bool, str]] = [
    ("Information theory", True, r"compression is intelligence"),
    ("Information theory", True, r"entropy.{0,60}compression|compression.{0,60}entropy"),
    ("Information theory", True, r"information theory"),
    ("Information theory", True, r"shannon entropy"),
    ("Information theory", True, r"mutual information"),
    ("Information theory", True, r"kolmogorov complexity"),
    ("Information theory", True, r"channel capacity"),
    ("Information theory", True, r"algorithmic information"),
    ("Information theory", True, r"rate[- ]distortion"),
    ("Olympiad", True, r"mathematical olympiad"),
    ("Olympiad", True, r"math olympiad"),
    ("Olympiad", True, r"imo shortlist"),
    ("Olympiad", True, r"international mathematical olympiad"),
    ("Olympiad", True, r"putnam (competition|exam|seminar|problem)"),
    ("Olympiad", True, r"\busamo\b"),
    ("Olympiad", True, r"olympiad (math|problem|training|lecture|solution)"),
    ("Number theory", True, r"algebraic number theory"),
    ("Number theory", True, r"analytic number theory"),
    ("Number theory", True, r"number theory"),
    ("Number theory", True, r"riemann hypothesis"),
    ("Number theory", True, r"riemann zeta"),
    ("Number theory", True, r"prime numbers?"),
    ("Number theory", True, r"quadratic reciprocity"),
    ("Number theory", True, r"modular arithmetic"),
    ("Number theory", True, r"elliptic curves?"),
    ("Number theory", True, r"p-adic"),
    ("Number theory", True, r"fermat'?s?( last)? theorem"),
    ("Number theory", True, r"\bramanujan\b"),
    ("Linear algebra", True, r"essence of linear algebra"),
    ("Linear algebra", True, r"singular value decomposition"),
    ("Linear algebra", True, r"gaussian elimination"),
    ("Linear algebra", True, r"linear algebra"),
    ("Linear algebra", True, r"vector spaces?"),
    ("Linear algebra", True, r"eigenvalues?"),
    ("Linear algebra", True, r"eigenvectors?"),
    ("Linear algebra", True, r"matrix calculus"),
    ("Linear algebra", True, r"gilbert strang"),
    ("Linear algebra", True, r"\b18\.06\b"),
    ("Linear algebra", True, r"inner products?"),
    ("Topology", True, r"algebraic topology"),
    ("Topology", True, r"differential topology"),
    ("Topology", True, r"point-set topology"),
    ("Topology", True, r"general topology"),
    ("Topology", True, r"fundamental groups?"),
    ("Topology", True, r"\bcohomology\b"),
    ("Topology", True, r"\bhomotopy\b"),
    ("Topology", True, r"\bhomology\b"),
    ("Topology", True, r"knot theory"),
    ("Topology", True, r"\btopology\b"),
    ("Analysis", True, r"functional analysis"),
    ("Analysis", True, r"complex analysis"),
    ("Analysis", True, r"real analysis"),
    ("Analysis", True, r"fourier analysis"),
    ("Analysis", True, r"measure theory"),
    ("Analysis", True, r"hilbert spaces?"),
    ("Analysis", True, r"banach spaces?"),
    ("Analysis", True, r"fourier (series|transform)"),
    ("Analysis", True, r"epsilon-delta"),
    ("Analysis", True, r"metric spaces?"),
    ("Analysis", True, r"taylor series"),
    ("Analysis", True, r"lebesgue"),
    ("Analysis", True, r"navier[- ]stokes"),
    ("Analysis", True, r"partial differential"),
    ("Analysis", True, r"differential equations"),
    ("Analysis", True, r"harmonic analysis"),
    ("Analysis", True, r"\banalysis lecture\b"),
    ("Algebra", True, r"abstract algebra"),
    ("Algebra", True, r"commutative algebra"),
    ("Algebra", True, r"homological algebra"),
    ("Algebra", True, r"representation theory"),
    ("Algebra", True, r"group theory"),
    ("Algebra", True, r"\bring theory\b"),
    ("Algebra", True, r"galois theory"),
    ("Algebra", True, r"lie algebras?"),
    ("Algebra", True, r"lie groups?"),
    ("Algebra", True, r"\bgalois\b"),
    ("Category theory", True, r"category theory"),
    ("Category theory", True, r"\byoneda\b"),
    ("Geometry", True, r"differential geometry"),
    ("Geometry", True, r"algebraic geometry"),
    ("Geometry", True, r"hyperbolic geometry"),
    ("Geometry", True, r"euclidean geometry"),
    ("Geometry", True, r"non-euclidean"),
    ("Geometry", True, r"projective geometry"),
    ("Geometry", True, r"\btrigonometry\b"),
    ("Geometry", True, r"trigonometric"),
    ("Combinatorics", True, r"extremal combinatorics"),
    ("Combinatorics", True, r"analytic combinatorics"),
    ("Combinatorics", True, r"\bcombinatorics\b"),
    ("Combinatorics", True, r"graph theory"),
    ("Combinatorics", True, r"generating functions?"),
    ("Combinatorics", True, r"probabilistic method"),
    ("Logic & set theory", True, r"lambda calculus"),
    ("Logic & set theory", True, r"homotopy type theory"),
    ("Logic & set theory", True, r"incompleteness theorems?"),
    ("Logic & set theory", True, r"axiom of choice"),
    ("Logic & set theory", True, r"continuum hypothesis"),
    ("Logic & set theory", True, r"computability theory"),
    ("Logic & set theory", True, r"computational complexity"),
    ("Logic & set theory", True, r"proof theory"),
    ("Logic & set theory", True, r"model theory"),
    ("Logic & set theory", True, r"set theory"),
    ("Logic & set theory", True, r"type theory"),
    ("Logic & set theory", True, r"proof assistant"),
    ("Logic & set theory", True, r"\bgoedel\b"),
    ("Logic & set theory", True, r"g[oö]del"),
    ("Calculus", True, r"essence of calculus"),
    ("Calculus", True, r"multivariable calculus"),
    ("Calculus", True, r"vector calculus"),
    ("Calculus", True, r"calculus (lecture|course|textbook)"),
    ("Calculus", True, r"integral calculus"),
    ("Calculus", True, r"differential calculus"),
    ("Optimisation", True, r"convex optimi[sz]ation"),
    ("Optimisation", True, r"mathematical optimi[sz]ation"),
    ("Optimisation", True, r"lagrange multipliers?"),
    ("Optimisation", True, r"linear programming"),
    ("Optimisation", True, r"stochastic gradient"),
    ("Probability", True, r"probability theory"),
    ("Probability", True, r"probability (lecture|course)"),
    ("Probability", True, r"stochastic processes?"),
    ("Probability", True, r"markov chains?"),
    ("Probability", True, r"monte carlo"),
    ("Probability", True, r"bayesian inference"),
    ("Probability", True, r"bayes(ian| theorem|' theorem)?"),
    ("Probability", True, r"random variables?"),
    ("Probability", True, r"gaussian (distribution|integral)"),
    ("ML theory", True, r"universal approximation"),
    ("ML theory", True, r"statistical learning"),
    ("ML theory", True, r"learning theory"),
    ("ML theory", True, r"machine learning"),
    ("ML theory", True, r"deep learning"),
    ("ML theory", True, r"neural networks?"),
    ("ML theory", True, r"back[- ]?propagation"),
    ("ML theory", True, r"\bbackprop\b"),
    ("ML theory", True, r"gradient descent"),
    ("ML theory", True, r"vc dimension"),
    ("ML theory", True, r"kernel methods?"),
    ("ML theory", True, r"gaussian processes?"),
    ("ML theory", True, r"variational inference"),
    ("ML theory", True, r"reinforcement learning"),
    ("ML theory", True, r"bias[- ]variance"),
    ("ML theory", True, r"automatic differentiation"),
    ("ML theory", True, r"support vector machines?"),
    ("ML theory", True, r"convolutional neural"),
    ("ML theory", True, r"recurrent neural"),
    ("ML theory", True, r"principal component analysis"),
    ("ML theory", True, r"naive bayes"),
    ("ML theory", True, r"\bcs229\b"),
    ("ML theory", True, r"\bcs231n\b"),
    ("ML theory", True, r"\bcs224n\b"),
    ("Mathematics", True, r"\bmathematics\b"),
    ("Mathematics", True, r"\bmathematical\b"),
    ("Mathematics", True, r"\bmathematicians?\b"),
    ("Mathematics", True, r"\bmaths\b"),
    ("Mathematics", True, r"3blue1brown"),
    ("Mathematics", True, r"numberphile"),
    ("Mathematics", True, r"mathologer"),
    ("Mathematics", True, r"\bramanujan\b"),
    ("Mathematics", True, r"\beuler\b"),
    ("Mathematics", True, r"\briemann\b"),
    ("Mathematics", True, r"\blemma\b"),
    ("Mathematics", True, r"\btheorem\b"),
    ("Mathematics", True, r"quantum information"),
    ("Calculus", False, r"\bcalculus\b"),
    ("Probability", False, r"\bprobability\b"),
    ("Geometry", False, r"\bgeometry\b"),
    ("Algebra", False, r"\balgebra\b"),
    ("Optimisation", False, r"\boptimi[sz]ation\b"),
    ("Analysis", False, r"\bmanifolds?\b"),
    ("Mathematics", False, r"\bproofs?\b"),
]

EDU_CUE = re.compile(
    r"\b(lectures?|courses?|introduction|intro\b|explained|explanation|tutorial|"
    r"chapters?|lessons?|seminars?|colloqui(?:um|a)|derivation|essence|professor|"
    r"opencourseware|\bocw\b|homework|recitation|syllabus|textbook|beginners?|"
    r"walkthrough|problem set|recap)\b"
    r"|\b(part|chapter|lecture|lec|week|session)\s*\d+"
    r"|\bwhat (is|are)\b|\bwhy (do|does|is|are)\b|\b101\b",
    re.I,
)

OFFTOPIC = re.compile(
    r"official (music )?video|\blyrics?\b|\bkaraoke\b|\bnightcore\b|"
    r"official trailer|\bgameplay\b|\bwalkthrough\b|let'?s play|\bspeedrun\b|"
    r"\bunboxing\b|\bvlog\b|\basmr\b|\bminecraft\b|\bfortnite\b|\broblox\b|"
    r"\bamong us\b|geometry dash|\bbitcoin\b|\bethereum\b|\bcrypto(?:currency)?\b|"
    r"\bnft\b|\bblockchain\b|\bforex\b|\bdropship|\bfull movie\b|"
    r"music video|\bsuper bowl\b|\bworld cup\b|\bday trad|\bstock price\b|"
    r"\bmake money\b|\bget rich\b|\bpassive income\b|"
    r"counter[- ]strike|\bcsgo\b|\bcs:go\b|\bvideo games\b|"
    r"comedy routine|stand-up comedy|\bparody\b|"
    r"\bdarwin\b|theory of evolution|"
    r"structure and interpretation|\b6\.001\b",
    re.I,
)

EXAM_PREP = re.compile(
    r"\bjee\b|\bneet\b|\biit[\s-]?jee\b|\bcbse\b|\bncert\b|"
    r"\bbyju'?s?\b|\bunacademy\b|\bvedantu\b|physics\s*wallah|"
    r"allen career|allen kota|\bclass\s*(9|10|11|12)\b",
    re.I,
)

SOFT_JUNK = re.compile(
    r"\bmarketing\b|\bsalary\b|\bresume\b|career advice|\bstartups?\b|"
    r"\bentrepreneur\b|\bmotivational\b|self[- ]help|\bfor business\b|"
    r"side hustle|\bpodcast\b",
    re.I,
)

PURE_MATH = re.compile(
    r"linear algebra|number theory|topology|real analysis|complex analysis|"
    r"functional analysis|theorem|lemma|cohomology|homotopy|galois|riemann|"
    r"fourier|differential equation|group theory|category theory|combinatorics|"
    r"information theory|convex optim|olympiad|eigenvalue|manifold|hilbert|"
    r"measure theory|abstract algebra|set theory|calculus|probability theory|"
    r"\bmathematics\b|\bmathematical\b|fourier|neural network|transformer",
    re.I,
)

GENERIC_LECTURE = re.compile(
    r"^(lecture|lec\.?|week|session|part|chapter|video|episode)\s*\d+\b|"
    r"\b(lecture|week|session)\s+\d+\b",
    re.I,
)

ACADEMIC_CHANNEL = re.compile(
    r"mit opencourseware|opencourseware|\bstanford\b|\bharvard\b|\boxford\b|"
    r"\bprinceton\b|\bcambridge\b|\byale\b|\bcaltech\b|eth zurich|eth zürich|"
    r"uc berkeley|carnegie mellon|institute for advanced study|\bcoursera\b|"
    r"university of|collège de france|college de france",
    re.I,
)

REC_WORDS = re.compile(
    r"\b(recommend\w*|watch|lecture|course|explanat\w*|explains|taught|beautiful|"
    r"excellent|favourite|favorite|brilliant|worth (a )?watch|highly)\b",
    re.I,
)

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
PROTO_RE = re.compile(
    r"//(?:www\.|m\.)?(?:youtube(?:-nocookie)?\.com|youtu\.be|vimeo\.com|ted\.com)[^\s<>\"']+",
    re.I,
)

_request_lock = threading.Lock()
REQUESTS = {"algolia": 0, "oembed": 0, "firebase": 0}


def _compile_rules() -> list[tuple[str, bool, re.Pattern[str]]]:
    # Longer patterns first so a specific phrase wins over a word it contains.
    ordered = sorted(_RAW_RULES, key=lambda item: len(item[2]), reverse=True)
    return [(topic, specific, re.compile(pat, re.I)) for topic, specific, pat in ordered]


RULES = _compile_rules()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def phrase_query(phrase: str) -> str:
    phrase = phrase.strip()
    if " " in phrase:
        return f'"{phrase}"'
    return phrase


def http_json(url: str, timeout: int = 45, kind: str = "algolia", soft: bool = False):
    last: Exception | None = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.load(resp)
            with _request_lock:
                REQUESTS[kind] = REQUESTS.get(kind, 0) + 1
            return payload
        except urllib.error.HTTPError as exc:
            last = exc
            if soft and exc.code in (401, 403, 404):
                with _request_lock:
                    REQUESTS[kind] = REQUESTS.get(kind, 0) + 1
                return None
            if exc.code in (429, 500, 502, 503, 504) or (soft and exc.code >= 500):
                time.sleep(1.1 * (attempt + 1))
                continue
            if soft:
                return None
            raise
        except Exception as exc:  # noqa: BLE001 - network errors are retried
            last = exc
            time.sleep(0.7 * (attempt + 1))
    if soft:
        return None
    raise RuntimeError(f"request failed: {url[:160]} ({last})")


def algolia_url(query: str, start: int, end: int, page: int = 0) -> str:
    params = {
        "tags": "comment",
        "hitsPerPage": str(HITS_PER_PAGE),
        "page": str(page),
        "query": query,
        "typoTolerance": "false",
        "ignorePlurals": "false",
        "removeStopWords": "false",
        "analytics": "false",
        "attributesToRetrieve": "author,comment_text,created_at,created_at_i,objectID",
        "numericFilters": f"created_at_i>={start},created_at_i<{end}",
    }
    return ALGOLIA + "?" + urllib.parse.urlencode(params)


def window_cache_path(query: str, start: int, end: int) -> Path:
    key = hashlib.sha1(f"{query}|{start}|{end}".encode()).hexdigest()
    return WINDOWS / f"{key}.json"


def fetch_window(query: str, start: int, end: int) -> tuple[str, list[dict]]:
    path = window_cache_path(query, start, end)
    if path.exists():
        cached = json.loads(path.read_text())
        if cached.get("query") == query and cached.get("start") == start and cached.get("end") == end:
            if cached.get("split"):
                return "split", []
            return "ok", cached.get("hits") or []

    data = http_json(algolia_url(query, start, end, 0))
    hits = list(data.get("hits") or [])
    nb = int(data.get("nbHits") or 0)
    if len(hits) >= HITS_PER_PAGE and nb > len(hits) and (end - start) > 120:
        path.write_text(json.dumps({"query": query, "start": start, "end": end, "split": True}))
        return "split", []

    page = 1
    while nb > len(hits) and page < 5:
        more = http_json(algolia_url(query, start, end, page))
        batch = more.get("hits") or []
        if not batch:
            break
        hits.extend(batch)
        page += 1
        if len(batch) < HITS_PER_PAGE:
            break
        if len(hits) >= HITS_PER_PAGE and nb > len(hits) and (end - start) > 120:
            path.write_text(json.dumps({"query": query, "start": start, "end": end, "split": True}))
            return "split", []

    slim = []
    for hit in hits:
        author = (hit.get("author") or "").strip()
        text = hit.get("comment_text") or ""
        created = hit.get("created_at") or ""
        if not author or not text or not created or author.lower() in {"[deleted]", "deleted"}:
            continue
        slim.append(
            {
                "id": str(hit.get("objectID")),
                "author": author,
                "created_at": created,
                "created_at_i": int(hit.get("created_at_i") or 0),
                "text": text,
            }
        )
    path.write_text(
        json.dumps({"query": query, "start": start, "end": end, "split": False, "hits": slim})
    )
    return "ok", slim


def fetch_query(query: str, end: int) -> list[dict]:
    stack = [(RANGE_START, end)]
    found: list[dict] = []
    while stack:
        start, stop = stack.pop()
        kind, hits = fetch_window(query, start, stop)
        if kind == "split":
            mid = (start + stop) // 2
            if mid <= start or mid >= stop:
                found.extend(hits)
                continue
            stack.append((mid, stop))
            stack.append((start, mid))
            continue
        found.extend(hits)
    return found


def probe_count(query: str, end: int) -> int:
    params = {
        "tags": "comment",
        "hitsPerPage": "0",
        "query": query,
        "typoTolerance": "false",
        "ignorePlurals": "false",
        "removeStopWords": "false",
        "analytics": "false",
        "numericFilters": f"created_at_i>={RANGE_START},created_at_i<{end}",
    }
    url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(params)
    data = http_json(url)
    return int(data.get("nbHits") or 0)


def queries_for_phrase(phrase: str, end: int) -> list[str]:
    query = phrase_query(phrase)
    try:
        count = probe_count(query, end)
    except Exception as exc:  # noqa: BLE001
        print(f"probe failed for {query!r}: {exc}", flush=True)
        count = 1001
    if count <= 0:
        return []
    if count > 1000:
        return [f"{host} {query}" for host in HOSTS]
    return [query]


def plain_text(raw_html: str) -> str:
    text = html.unescape(raw_html or "")
    text = TAG_RE.sub(" ", text)
    return WS_RE.sub(" ", text).strip()


def iter_urls(raw_html: str) -> list[str]:
    text = html.unescape(raw_html or "")
    found = URL_RE.findall(text)
    found.extend("https:" + match for match in PROTO_RE.findall(text))
    cleaned = []
    seen = set()
    for url in found:
        url = url.rstrip(").,;]>\"'")
        if url not in seen:
            seen.add(url)
            cleaned.append(url)
    return cleaned


def extract_from_url(url: str) -> tuple[str, str] | None:
    low = url.lower()
    if "youtube" in low or "youtu.be" in low:
        video = re.search(r"[?&]v=([A-Za-z0-9_-]{11})\b", url)
        if video and video.group(1) != "videoseries":
            return ("youtube", video.group(1))
        short = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})\b", url, re.I)
        if short:
            return ("youtube", short.group(1))
        embed = re.search(r"/(?:embed|shorts|live|v)/([A-Za-z0-9_-]{11})\b", url, re.I)
        if embed:
            return ("youtube", embed.group(1))
        playlist = re.search(r"[?&]list=([A-Za-z0-9_-]{13,80})\b", url)
        if playlist:
            return ("playlist", playlist.group(1))
        return None
    if "vimeo.com" in low:
        match = re.search(r"vimeo\.com/(?:[\w-]+/)*(\d{6,12})\b", url, re.I)
        if match:
            return ("vimeo", match.group(1))
        return None
    if "ted.com/talks/" in low:
        match = re.search(r"ted\.com/talks/(?:lang/[a-z]{2}/)?([a-z0-9_]{8,})", url, re.I)
        if match and match.group(1).lower() != "lang":
            return ("ted", match.group(1).lower())
    return None


def extract_videos(raw_html: str) -> list[tuple[str, str]]:
    found = []
    seen = set()
    for url in iter_urls(raw_html):
        item = extract_from_url(url)
        if item and item not in seen:
            seen.add(item)
            found.append(item)
    return found


def canonical_url(provider: str, video_id: str) -> str:
    if provider == "youtube":
        return f"https://www.youtube.com/watch?v={video_id}"
    if provider == "playlist":
        return f"https://www.youtube.com/playlist?list={video_id}"
    if provider == "vimeo":
        return f"https://vimeo.com/{video_id}"
    if provider == "ted":
        return f"https://www.ted.com/talks/{video_id}"
    raise ValueError(provider)


def transformer_signal(text: str) -> bool:
    lowered = text.lower()
    phrases = (
        "attention is all you need",
        "self-attention",
        "multi-head attention",
        "multihead attention",
        "vision transformer",
        "transformer architecture",
        "transformer model",
        "transformers explained",
        "illustrated transformer",
        "swin transformer",
        "transformer network",
        "large language model",
    )
    if any(phrase in lowered for phrase in phrases):
        return True
    if re.fullmatch(r"transformers?(?:\s+explained)?", lowered.strip()):
        return True
    if re.search(r"\btransformers?\b", lowered) and re.search(
        r"\b(attention|neural|language|gpt|bert|llm|token|embedding|encoder|decoder|deep learning|machine learning)\b",
        lowered,
    ):
        return True
    if re.search(r"\bpartition\b", lowered):
        return False
    if re.search(r"\b(gpt|chatgpt|llms?)\b", lowered) and re.search(
        r"\b(build|scratch|spelled|spell|intro|lecture|implement|code|tokeni[sz]er|tokens?|deep dive|explained|attention|talk|architecture|model|paper|language)\b",
        lowered,
    ):
        return True
    return False


def match_topic(text: str, specific_only: bool = False, skip_topics: tuple[str, ...] = ()) -> str | None:
    if not text:
        return None
    if transformer_signal(text) and "Transformers" not in skip_topics:
        return "Transformers"
    for topic, specific, pattern in RULES:
        if topic in skip_topics:
            continue
        if specific and pattern.search(text):
            # "network topology" is not the mathematical field.
            if topic == "Topology" and re.search(r"network topology", text, re.I):
                if not re.search(r"algebraic topology|general topology|point-set|homotopy|manifold", text, re.I):
                    continue
            return topic
    if specific_only:
        return None
    if EDU_CUE.search(text):
        for topic, specific, pattern in RULES:
            if not specific and pattern.search(text):
                return topic
    return None


def channel_has(channel: str, names: tuple[str, ...]) -> bool:
    lowered = channel.casefold()
    return any(name.casefold() in lowered for name in names)


def hard_reject(title: str, channel: str) -> bool:
    if EXAM_PREP.search(title) or EXAM_PREP.search(channel):
        return True
    if OFFTOPIC.search(title):
        return True
    if SOFT_JUNK.search(title) and not PURE_MATH.search(title):
        return True
    return False


def title_topic(title: str) -> str | None:
    """Topic established by the title alone, with educational cues for broad words."""
    return match_topic(title, specific_only=False)


def classify(title: str, channel: str, context: str = "", windows: list[str] | None = None) -> str | None:
    title = (title or "").strip()
    channel = (channel or "").strip()
    if windows is None:
        windows = [context] if context else []
    if not title or hard_reject(title, channel):
        return None

    from_title = title_topic(title)
    # A field named next to the link can fill in a poetic title. The bare word
    # "mathematical" cannot, and neither can a different recommendation later
    # in the same comment (callers pass one window per comment).
    from_context = None
    for window in windows:
        from_context = match_topic(window, specific_only=True, skip_topics=("Mathematics",))
        if from_context:
            break

    if channel_has(channel, TITLE_ONLY_CHANNELS) or re.search(r"\b(ted|tedx)\b", channel, re.I):
        return from_title

    if channel_has(channel, STRICT_CHANNELS):
        if from_title:
            return from_title
        # ML threads often link a pure-math video as intuition. Don't retag it.
        if from_context and from_context not in {"ML theory", "Transformers"}:
            return from_context
        return "Mathematics"

    if channel_has(channel, TOPIC_CHANNELS):
        if from_title:
            return from_title
        if GENERIC_LECTURE.search(title) and from_context:
            return from_context
        return None

    if from_title:
        return from_title

    if GENERIC_LECTURE.search(title) and ACADEMIC_CHANNEL.search(channel) and from_context:
        return from_context
    return None


def excerpt_around(plain: str, video_id: str, limit: int = 220) -> str:
    if not plain:
        return ""
    idx = plain.lower().find(video_id.lower())
    if idx < 0:
        snippet = plain[:limit]
    else:
        start = max(0, idx - 120)
        snippet = plain[start : start + limit + 40]
        if start > 0:
            snippet = snippet.split(" ", 1)[-1]
    snippet = snippet.strip()
    if len(snippet) > limit:
        snippet = snippet[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return snippet


def comment_window(plain: str, video_id: str, radius: int = 200) -> str:
    idx = plain.lower().find(video_id.lower())
    if idx < 0:
        return plain[: radius * 2]
    return plain[max(0, idx - radius) : idx + radius]


def highlight_score(plain: str, window: str, nlinks: int) -> int:
    score = 0
    if match_topic(window, specific_only=True):
        score += 6
    if REC_WORDS.search(window):
        score += 4
    length = len(plain)
    if 70 <= length <= 700:
        score += 3
    elif length > 40:
        score += 1
    if nlinks == 1:
        score += 2
    return score


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def save_comments(comments: dict[str, dict]) -> None:
    COMMENTS_PATH.write_text(json.dumps(list(comments.values())))


def load_comments() -> dict[str, dict]:
    if not COMMENTS_PATH.exists():
        return {}
    rows = json.loads(COMMENTS_PATH.read_text())
    return {row["id"]: row for row in rows}


def collect_comments(end: int) -> tuple[dict[str, dict], list[str]]:
    print(f"probing {len(PHRASES)} phrases", flush=True)
    queries: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(queries_for_phrase, phrase, end): phrase for phrase in PHRASES}
        for future in as_completed(futures):
            queries.extend(future.result())
    # Preserve order and drop duplicates.
    seen = set()
    ordered = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            ordered.append(query)
    print(f"{len(ordered)} search queries", flush=True)

    comments: dict[str, dict] = {}
    lock = threading.Lock()

    def run(query: str) -> None:
        hits = fetch_query(query, end)
        with lock:
            for hit in hits:
                comments.setdefault(hit["id"], hit)
        print(f"  {len(hits):5d} hits  {query}", flush=True)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run, ordered))
    return comments, ordered


def group_videos(comments: dict[str, dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for comment in comments.values():
        videos = extract_videos(comment["text"])
        if not videos:
            continue
        plain = plain_text(comment["text"])
        for provider, video_id in videos:
            window = comment_window(plain, video_id)
            grouped.setdefault((provider, video_id), []).append(
                {
                    "id": comment["id"],
                    "author": comment["author"],
                    "created_at": comment["created_at"],
                    "plain": plain,
                    "window": window,
                    "nlinks": len(videos),
                    "score": highlight_score(plain, window, len(videos)),
                }
            )
    return grouped


def context_for(entries: list[dict]) -> str:
    # Windows around each link, best comments first, so a distant aside
    # ("it's all linear algebra") does not classify a different video.
    ordered = sorted(entries, key=lambda entry: (-entry["score"], entry["created_at"]))
    return "\n".join(entry["window"] for entry in ordered[:5])


def distinct_authors(entries: list[dict]) -> int:
    return len({entry["author"].casefold() for entry in entries})


def oembed_url(provider: str, video_id: str) -> str:
    target = canonical_url(provider, video_id)
    if provider in {"youtube", "playlist"}:
        return "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(target, safe="")
    if provider == "vimeo":
        return "https://vimeo.com/api/oembed.json?url=" + urllib.parse.quote(target, safe="")
    if provider == "ted":
        return "https://www.ted.com/services/v1/oembed.json?url=" + urllib.parse.quote(target, safe="")
    raise ValueError(provider)


def meta_from_oembed(payload: dict | None) -> dict | None:
    if not payload:
        return None
    title = (payload.get("title") or "").strip()
    if not title or title.casefold() in {"youtube", "vimeo", "ted", "private video", "deleted video", "video unavailable"}:
        return None
    channel = (payload.get("author_name") or "").strip() or "Unknown channel"
    thumb = (payload.get("thumbnail_url") or "").strip()
    return {"title": title, "channel": channel, "thumbnail": thumb}


def meta_from_watch_page(video_id: str) -> dict | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(250_000).decode("utf-8", "replace")
    except Exception:
        return None
    match = re.search(r'<meta property="og:title" content="([^"]+)"', body)
    if not match:
        match = re.search(r"<title>([^<]+)</title>", body)
    if not match:
        return None
    title = html.unescape(match.group(1)).strip()
    title = re.sub(r"\s+-\s+YouTube$", "", title).strip()
    if not title or title.casefold() in {"youtube", "video unavailable"}:
        return None
    channel_match = re.search(r'<link itemprop="name" content="([^"]+)"', body)
    channel = html.unescape(channel_match.group(1)).strip() if channel_match else "Unknown channel"
    return {
        "title": title,
        "channel": channel or "Unknown channel",
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    }


def fetch_meta(provider: str, video_id: str) -> dict | None:
    payload = http_json(oembed_url(provider, video_id), timeout=25, kind="oembed", soft=True)
    meta = meta_from_oembed(payload)
    if meta:
        return meta
    noembed = http_json(
        "https://noembed.com/embed?url=" + urllib.parse.quote(canonical_url(provider, video_id), safe=""),
        timeout=25,
        kind="oembed",
        soft=True,
    )
    meta = meta_from_oembed(noembed)
    if meta:
        return meta
    if provider == "youtube":
        return meta_from_watch_page(video_id)
    return None


def attach_metadata(keys: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    cache: dict[str, dict] = load_json(OEMBED_PATH, {})
    lock = threading.Lock()
    found: dict[tuple[str, str], dict] = {}

    def one(key: tuple[str, str]) -> None:
        provider, video_id = key
        cache_key = f"{provider}:{video_id}"
        with lock:
            cached = cache.get(cache_key)
        if cached is None:
            try:
                meta = fetch_meta(provider, video_id)
            except Exception as exc:  # noqa: BLE001
                print(f"oembed error {cache_key}: {exc}", flush=True)
                meta = None
            record = meta if meta else {"error": True}
            with lock:
                cache[cache_key] = record
                if len(cache) % 40 == 0:
                    OEMBED_PATH.write_text(json.dumps(cache))
            cached = record
        return key, cached

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, keys))
    for key, cached in results:
        if cached and not cached.get("error") and cached.get("title"):
            found[key] = cached
    OEMBED_PATH.write_text(json.dumps(cache))
    return found


def build_records(grouped, metas) -> tuple[list[dict], dict]:
    published = []
    dropped_topic = 0
    dropped_title = 0
    for key, entries in grouped.items():
        if distinct_authors(entries) < MIN_RECOMMENDERS:
            continue
        meta = metas.get(key)
        if not meta:
            dropped_title += 1
            continue
        # De-duplicate comments and keep one row per comment id.
        by_id = {}
        for entry in entries:
            by_id.setdefault(entry["id"], entry)
        rows = list(by_id.values())
        ordered_rows = sorted(rows, key=lambda row: (-row["score"], row["created_at"]))
        topic = classify(
            meta["title"],
            meta["channel"],
            windows=[row["window"] for row in ordered_rows[:8]],
        )
        if not topic:
            dropped_topic += 1
            continue
        rows.sort(key=lambda row: (-row["score"], -len(row["plain"]), row["created_at"]))
        seen_authors = set()
        highlights = []
        for row in rows:
            author_key = row["author"].casefold()
            if author_key in seen_authors:
                continue
            seen_authors.add(author_key)
            highlights.append(
                {
                    "id": row["id"],
                    "author": row["author"],
                    "created_at": row["created_at"],
                    "excerpt": excerpt_around(row["plain"], key[1]),
                }
            )
            if len(highlights) == 3:
                break
        sources = [
            {"id": row["id"], "author": row["author"], "created_at": row["created_at"]}
            for row in sorted(rows, key=lambda row: row["created_at"])
        ]
        provider, video_id = key
        thumb = meta.get("thumbnail") or ""
        if not thumb and provider == "youtube":
            thumb = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        published.append(
            {
                "provider": provider,
                "video_id": video_id,
                "url": canonical_url(provider, video_id),
                "title": meta["title"],
                "channel": meta["channel"],
                "thumbnail": thumb,
                "topic": topic,
                "sources": sources,
                "highlights": highlights,
            }
        )

    def sort_key(video: dict):
        authors = len({s["author"].casefold() for s in video["sources"]})
        earliest = min(s["created_at"] for s in video["sources"])
        return (-authors, -len(video["sources"]), earliest, video["title"].casefold())

    published.sort(key=sort_key)
    return published, {"dropped_topic": dropped_topic, "dropped_untitled": dropped_title}


def write_output(videos: list[dict], comments: dict[str, dict], queries: list[str], extra: dict) -> dict:
    created = [c["created_at"] for c in comments.values() if c.get("created_at")]
    link_comments = 0
    for comment in comments.values():
        if extract_videos(comment["text"]):
            link_comments += 1
    meta = {
        "generated_at": now_iso(),
        "comments_scanned": len(comments),
        "comments_with_video_links": link_comments,
        "min_recommenders": MIN_RECOMMENDERS,
        "videos_published": len(videos),
        "scanned_from": min(created) if created else "",
        "scanned_to": max(created) if created else "",
        "algolia_requests": REQUESTS.get("algolia", 0),
        "queries": queries,
        "dropped_untitled": extra.get("dropped_untitled", 0),
        "dropped_offtopic": extra.get("dropped_topic", 0),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"meta": meta, "videos": videos}, ensure_ascii=False, indent=2) + "\n")
    return meta


def print_report(videos: list[dict], meta: dict) -> None:
    print("\n=== REPORT ===", flush=True)
    print(f"comments_scanned {meta['comments_scanned']}", flush=True)
    print(f"comments_with_video_links {meta['comments_with_video_links']}", flush=True)
    print(f"videos {len(videos)}", flush=True)
    print(f"range {meta['scanned_from']} .. {meta['scanned_to']}", flush=True)
    print(f"dropped_offtopic {meta['dropped_offtopic']} dropped_untitled {meta['dropped_untitled']}", flush=True)
    for index, video in enumerate(videos[:15], 1):
        count = len({s["author"].casefold() for s in video["sources"]})
        link = f"https://news.ycombinator.com/item?id={video['highlights'][0]['id']}"
        print(
            f"{index:2d}. [{count}] {video['title']} | {video['channel']} | {video['topic']} | {link}",
            flush=True,
        )


def self_test() -> None:
    cases = [
        ("https://www.youtube.com/watch?v=fNk_zzaMoSs", ("youtube", "fNk_zzaMoSs")),
        ("https://youtu.be/fNk_zzaMoSs?t=43", ("youtube", "fNk_zzaMoSs")),
        ("https://www.youtube.com/watch?v=fNk_zzaMoSs&list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab&t=10s", ("youtube", "fNk_zzaMoSs")),
        ("https://www.youtube.com/embed/fNk_zzaMoSs", ("youtube", "fNk_zzaMoSs")),
        ("https://www.youtube.com/shorts/fNk_zzaMoSs", ("youtube", "fNk_zzaMoSs")),
        ("https://m.youtube.com/watch?v=fNk_zzaMoSs", ("youtube", "fNk_zzaMoSs")),
        ("https://www.youtube-nocookie.com/embed/fNk_zzaMoSs", ("youtube", "fNk_zzaMoSs")),
        ("https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab", ("playlist", "PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab")),
        ("https://www.youtube.com/watch?v=videoseries&list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab", ("playlist", "PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab")),
        ("https://vimeo.com/17207564", ("vimeo", "17207564")),
        ("https://www.ted.com/talks/hannah_fry_the_mathematics_of_love", ("ted", "hannah_fry_the_mathematics_of_love")),
        ("https://www.youtube.com/@3blue1brown", None),
        ("https://www.youtube.com/user/numberphile", None),
    ]
    for url, expected in cases:
        got = extract_from_url(url)
        assert got == expected, (url, got, expected)
    escaped = "See https:&#x2F;&#x2F;youtu.be&#x2F;fNk_zzaMoSs?t=12"
    assert extract_videos(escaped) == [("youtube", "fNk_zzaMoSs")]
    multi = extract_videos(
        'a https://youtu.be/fNk_zzaMoSs and https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    )
    assert multi == [("youtube", "fNk_zzaMoSs"), ("youtube", "dQw4w9WgXcQ")]

    def expect(title, channel, context, topic):
        got = classify(title, channel, context)
        assert got == topic, (title, got, topic)

    expect("Vectors | Chapter 1, Essence of linear algebra", "3Blue1Brown", "", "Linear algebra")
    expect("Toy Story 2 Almost Deleted", "Disney", "now it's all linear algebra", None)
    expect("But what is a neural network? | Deep learning, chapter 1", "3Blue1Brown", "", "ML theory")
    expect("Gradient descent, how neural networks learn | Chapter 2, Deep learning", "3Blue1Brown", "", "ML theory")
    expect("Attention is All You Need (Transformer Architecture)", "Yannic Kilcher", "", "Transformers")
    expect("How does a power transformer work?", "Practical Engineering", "linear algebra", None)
    expect("Official Music Video", "Vevo", "the mathematics of rhythm", None)
    expect("Introduction to Probability", "Harvard University", "", "Probability")
    expect("The probability this is clickbait", "Some Channel", "", None)
    expect("Lecture 1: Convex Optimization I", "Stanford University", "", "Optimisation")
    expect("Bitcoin explained simply", "CoinBureau", "information theory of mining", None)
    expect("Algebraic Topology lecture 1", "uni", "", "Topology")
    expect("Abstract Algebra", "uni", "", "Algebra")
    expect("Essence of calculus, chapter 1", "3Blue1Brown", "", "Calculus")
    expect("Freaky dot patterns", "Numberphile", "this is about prime numbers", "Number theory")
    expect("Freaky dot patterns", "Numberphile", "", "Mathematics")
    expect("JEE Advanced mathematics trick", "coaching", "", None)
    expect("Machine learning for startups", "Some Channel", "", None)
    expect("The Illustrated Transformer", "Jay Alammar", "", "Transformers")
    expect("Information theory lecture", "MIT OpenCourseWare", "", "Information theory")
    expect("The mathematics of love", "TED", "", "Mathematics")
    expect("CS229: Machine Learning Lecture", "Stanford", "", "ML theory")
    expect("Category Theory 1.1: Motivation and Philosophy", "Bartosz Milewski", "", "Category theory")
    expect("Lambda Calculus: PyCon 2019 Tutorial", "David Beazley", "", "Logic & set theory")
    expect("Using Deep Learning to Combat Cheating in CSGO", "GDC", "deep learning model", None)
    expect("MarI/O - Machine Learning for Video Games", "SethBling", "machine learning", None)
    expect("Mathematical Challenges to Darwin’s Theory of Evolution", "Hoover Institution", "", None)
    expect("Stand-up comedy routine about Spreadsheets", "Stand-up Maths", "fourier series", None)
    expect("How They Fool Ya (live) | Math parody of Hallelujah", "3Blue1Brown", "", None)
    expect(
        "Lecture 1A | MIT 6.001 Structure and Interpretation, 1986",
        "MIT OpenCourseWare",
        "this can only happen within mathematical truths",
        None,
    )
    expect(
        "Gilbert Strang: Linear Algebra, Teaching, and MIT OpenCourseWare | Lex Fridman Podcast #52",
        "Lex Fridman",
        "",
        "Linear algebra",
    )
    expect(
        "Yann Lecun: Meta AI, Open Source, Limits of LLMs | Lex Fridman Podcast #416",
        "Lex Fridman",
        "machine learning",
        None,
    )
    expect(
        "ASTOUNDING: 1 + 2 + 3 + 4 + 5 + ... = -1/12",
        "Numberphile",
        "a theorem from string theory",
        "Mathematics",
    )
    expect(
        "ASTOUNDING: 1 + 2 + 3 + 4 + 5 + ... = -1/12",
        "Numberphile",
        "this is about the Riemann Hypothesis",
        "Number theory",
    )
    expect(
        "Thinking outside the 10-dimensional box",
        "3Blue1Brown",
        "gradient descent gets stuck in high dimensions",
        "Mathematics",
    )
    expect("Lecture 1A | MIT 6.001 Structure and Interpretation, 1986", "MIT OpenCourseWare", "incompleteness theorem", None)
    expect("MIT 6.034 Artificial Intelligence, Fall 2010", "MIT OpenCourseWare", "ghrist's calculus lectures", None)
    expect("Ring theory lecture", "uni", "", "Algebra")
    expect("Let's build GPT: from scratch, in code, spelled out.", "Andrej Karpathy", "", "Transformers")
    expect("Deep Dive into LLMs like ChatGPT", "Andrej Karpathy", "", "Transformers")
    expect("Let's build the GPT Tokenizer", "Andrej Karpathy", "", "Transformers")
    print("self-test ok", flush=True)


def verify() -> int:
    data = json.loads(OUT_PATH.read_text())
    videos = data["videos"][:30]
    failures = []
    jobs = []
    for index, video in enumerate(videos, 1):
        for source in video["sources"]:
            jobs.append((index, video, source))

    def check(job):
        index, video, source = job
        item = http_json(FIREBASE.format(id=source["id"]), timeout=30, kind="firebase", soft=True)
        problems = []
        if not item or item.get("deleted") or item.get("dead"):
            problems.append(f"#{index} missing comment {source['id']}")
            return problems
        author = item.get("by") or ""
        text = html.unescape(item.get("text") or "")
        if author != source["author"]:
            problems.append(f"#{index} author {source['id']} data={source['author']} firebase={author}")
        if video["video_id"].lower() not in text.lower():
            problems.append(f"#{index} video id {video['video_id']} not in {source['id']}")
        return problems

    with ThreadPoolExecutor(max_workers=12) as pool:
        for problems in pool.map(check, jobs):
            failures.extend(problems)
    for line in failures:
        print(line, flush=True)
    print(f"verified_comments {len(jobs)} failures {len(failures)}", flush=True)
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        self_test()
        return 0
    if "--verify" in argv:
        return verify()

    self_test()
    CACHE.mkdir(parents=True, exist_ok=True)
    WINDOWS.mkdir(parents=True, exist_ok=True)
    end = int(time.time()) + 3600

    if "--from-cache" in argv and COMMENTS_PATH.exists():
        comments = load_comments()
        previous = {}
        if OUT_PATH.exists():
            previous = json.loads(OUT_PATH.read_text()).get("meta") or {}
        queries = previous.get("queries") or []
        print(f"loaded {len(comments)} cached comments", flush=True)
    else:
        comments, queries = collect_comments(end)
        if not comments:
            print("no comments retrieved; the HN search request shape is wrong", flush=True)
            return 1
        save_comments(comments)
        print(f"saved {len(comments)} comments", flush=True)

    grouped = group_videos(comments)
    eligible = [key for key, entries in grouped.items() if distinct_authors(entries) >= MIN_RECOMMENDERS]
    print(f"{len(grouped)} distinct videos with links, {len(eligible)} with >= {MIN_RECOMMENDERS} recommenders", flush=True)
    metas = attach_metadata(eligible)
    print(f"metadata for {len(metas)} / {len(eligible)}", flush=True)
    videos, extra = build_records(grouped, metas)
    meta = write_output(videos, comments, queries, extra)
    print_report(videos, meta)
    print(f"wrote {OUT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
