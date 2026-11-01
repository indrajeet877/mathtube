# MathTube

The maths and AI videos Hacker News commenters have recommended most, ranked by how many **different accounts** linked each one.

This is a static site: `index.html`, `app.js`, `styles.css`, and `data/videos.json`. Nothing is tracked. Thumbnails are loaded from the video host.

Inspired by [Andrej Karpathy's HackerTube](https://karpathy.bearblog.dev/hacker-tube/).

## Snapshot in this commit

Figures below are copied from `data/videos.json` (regenerating the file will change them):

| | |
| --- | --- |
| Comments scanned | 40,497 |
| Of which contained a video link | 6,116 |
| Distinct linked videos before filters | 5,500 |
| Published videos | 338 |
| Distinct-recommender minimum | 2 |
| Earliest scanned comment | 2007-02-25 |
| Latest scanned comment | 2026-11-01 |
| Videos dropped as off-topic | 263 |
| Videos dropped because oEmbed returned no title | 84 |

The page does not hard-code these. The header counts `meta.comments_scanned`, `videos.length`, and the years of `meta.scanned_from` / `meta.scanned_to`. Each card's recommender count is the number of distinct `sources[].author` values, and its year range is the min and max of `sources[].created_at`.

## Reproduce

Python 3 standard library only.

```bash
python3 scripts/build.py --self-test
python3 scripts/build.py
python3 -m http.server
```

Open `http://127.0.0.1:8000/`. `file://` will not load the JSON.

`python3 scripts/build.py --from-cache` reclassifies from `data/cache/` without calling Algolia again. `python3 scripts/build.py --verify` re-fetches the Hacker News item for every source comment on the top 30 videos and checks the author and video id.

The cache directory is gitignored. The committed inputs are `scripts/build.py` and `data/videos.json`.

## Method

### What was searched

The public Algolia Hacker News index (`hn.algolia.com/api/v1/search` and `search_by_date`), `tags=comment`, from 2006-10 through the time of the run.

Typo tolerance, plural ignoring, and stop-word removal are turned **off**. With typo tolerance on, the index treats "vimeo" like "video" and "statquest" like "statues".

Each phrase in `PHRASES` inside `scripts/build.py` is probed. If it has at most 1,000 matching comments, those comments are downloaded. If it has more, the phrase is crossed with `youtube`, `youtu.be`, `vimeo`, and `ted.com`, because a single query cannot return more than 1,000 hits. When a window still reports more hits than it returns, it is split on `created_at_i` until each piece fits. That is the whole pagination strategy. It is not a scan of every Hacker News comment ever written.

### What counts as a recommendation

A comment counts only when it contains a real video URL, not merely the word "YouTube".

Supported URLs:

- YouTube `watch?v=`, `youtu.be/`, `embed/`, `shorts/`, `live/`, `v/`, including `m.youtube.com` and `youtube-nocookie.com`
- YouTube playlists (`list=`), including `watch?v=videoseries&list=`
- Vimeo numeric ids
- TED talk slugs

Timestamps and extra query parameters are stripped. A `watch` URL that also carries a playlist id is stored as the video, not the playlist. The same 11-character YouTube id reached by any of those shapes is one video.

Ranking uses **distinct comment authors** (case-insensitive), not raw mention counts. The same person linking a video twice counts once. Deleted comments and empty authors are ignored. A video is published only when at least two distinct authors linked it (`meta.min_recommenders`).

Ties break by more linking comments, then earlier first link, then title.

### Titles

Title, channel, and thumbnail come from the provider oEmbed endpoint (YouTube, Vimeo, TED). If oEmbed fails, the builder tries noembed.com and, for YouTube, the watch page's `og:title`. If there is still no title, the video is dropped. Titles are never filled in by hand.

### What is kept

Inclusion is a keyword ruleset in `scripts/build.py` (`RULES`, `transformer_signal`, `classify`). The longest matching specific phrase wins, so "linear algebra" beats "algebra" and "algebraic topology" beats "topology".

A video is kept when:

1. The **title** matches a specific phrase (for example "linear algebra", "Riemann hypothesis", "convex optimization", "neural network", "category theory"), or a broader word such as "calculus" or "probability" **and** an educational cue (lecture, course, introduction, explained, chapter, …), or
2. The channel is a known maths channel (3Blue1Brown, Numberphile, Mathologer, Michael Penn, Oxford Mathematics, Stand-up Maths, and the others listed as `STRICT_CHANNELS`) and the title is not on the blocklist. The topic then comes from the title, or from a field phrase in the comment text next to the link, or else "Mathematics". A maths-channel video linked from a machine-learning thread is not retagged as ML theory unless the title itself is about ML.
3. The channel is an ML or course channel (`TOPIC_CHANNELS`, including MIT OpenCourseWare and Andrej Karpathy) **and** the title matches, or the title is a generic "Lecture N" and the text next to the link names a field.

A comment that mentions mathematics while linking an unrelated video does **not** qualify. The Toy Story / "it's all linear algebra" case stays out because the title does not match and the channel is not a maths channel.

Off-topic titles are removed even if a maths word is present: music videos, trailers, gameplay, crypto, exam-prep and coaching material, startup pitches, Darwin-themed "mathematical" talks, game-cheat talks, comedy routines, and parodies. A podcast title is removed unless the title also contains a hard maths phrase such as "linear algebra" or "theorem", so a Strang linear-algebra interview can stay and a generic AI podcast does not.

### Topics

Each video gets one tag, in the order the rules are listed: Transformers, Information theory, Olympiad, Number theory, Linear algebra, Topology, Analysis, Algebra, Category theory, Geometry, Combinatorics, Logic & set theory, Calculus, Optimisation, Probability, ML theory, Mathematics. "Lambda calculus" is logic, not calculus. "Ring theory" does not match inside "string theory".

### Why HN recommends it

Each card links to two or three source comments (`https://news.ycombinator.com/item?id=…`), chosen from distinct authors, preferring comments whose text near the URL contains a field phrase or a recommendation word. The excerpt is that text, trimmed. The full set of source comments is in `sources` and is what the recommender count is computed from.

## Limits

- This is the slice of Hacker News that matched the phrase list, not the full comment firehose. A maths video that was only ever linked with no maths word and no known channel or title in the comment is missing. Poetic titles on unknown channels are missing unless a known maths channel posted them.
- The classifier is keywords, not a person. It will keep a shallow video with a matching title, and it will miss a good lecture whose title is a joke and whose channel is unfamiliar.
- "Comments scanned" means unique comments returned by those queries, including ones that did not contain a video URL.
- Usernames are whatever Algolia stored. People rename accounts. On the top 30, 566 source comments were re-fetched from the official HN API: every one still contained the video id; two rows for the linear-algebra playlist were the same thread author under an older name.
- One person with two accounts counts twice. Two comments from one account count once.
- Videos whose oEmbed (and fallbacks) returned no title are omitted rather than shown with a guessed title. Playlists and individual videos in them are separate entries.
- Vimeo and TED are included when the queries find them. Almost everything that survived is YouTube.
- The corpus ends at the build time recorded in `meta.generated_at`.

## Site

GitHub Pages, if enabled for this repository, serves the root of the default branch:

https://indrajeet877.github.io/mathtube/
