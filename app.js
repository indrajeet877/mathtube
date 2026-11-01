const $ = (id) => document.getElementById(id);

const state = {
  videos: [],
  topic: "All",
  query: "",
};

function recommenderCount(video) {
  return new Set(video.sources.map((source) => source.author.toLowerCase())).size;
}

function yearSpan(video) {
  let min = 9999;
  let max = 0;
  for (const source of video.sources) {
    const year = Number(source.created_at.slice(0, 4));
    if (year < min) min = year;
    if (year > max) max = year;
  }
  if (!max) return "";
  return min === max ? String(min) : `${min}–${max}`;
}

function compare(a, b) {
  const byRecommenders = recommenderCount(b) - recommenderCount(a);
  if (byRecommenders) return byRecommenders;
  const byMentions = b.sources.length - a.sources.length;
  if (byMentions) return byMentions;
  const earliest = (video) => video.sources.reduce((min, source) => Math.min(min, Date.parse(source.created_at)), Infinity);
  const byTime = earliest(a) - earliest(b);
  if (byTime) return byTime;
  return a.title.localeCompare(b.title);
}

function matches(video) {
  if (state.topic !== "All" && video.topic !== state.topic) return false;
  const needle = state.query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    video.title,
    video.channel,
    video.topic,
    ...video.highlights.map((item) => `${item.author} ${item.excerpt}`),
  ].join("\n").toLowerCase();
  return haystack.includes(needle);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function renderTopics() {
  const counts = new Map();
  for (const video of state.videos) {
    counts.set(video.topic, (counts.get(video.topic) || 0) + 1);
  }
  const topics = ["All", ...[...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || a.localeCompare(b))];
  const bar = $("topics");
  bar.replaceChildren();
  for (const topic of topics) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-pressed", topic === state.topic ? "true" : "false");
    const count = topic === "All" ? state.videos.length : counts.get(topic);
    button.textContent = `${topic} ${count}`;
    button.addEventListener("click", () => {
      state.topic = topic;
      renderTopics();
      renderList();
    });
    bar.appendChild(button);
  }
}

function renderList() {
  const list = $("list");
  const shown = state.videos.filter(matches);
  $("count").textContent = `Showing ${shown.length.toLocaleString("en-US")} of ${state.videos.length.toLocaleString("en-US")}`;
  list.replaceChildren();
  if (!shown.length) {
    list.appendChild(el("p", "empty", "No videos match that search."));
    return;
  }
  for (const video of shown) {
    const card = el("article", "card");
    card.appendChild(el("p", "rank", String(video.rank)));

    const thumb = el("a", "thumb");
    thumb.href = video.url;
    thumb.target = "_blank";
    thumb.rel = "noopener noreferrer";
    const img = document.createElement("img");
    img.src = video.thumbnail;
    img.alt = "";
    img.loading = "lazy";
    img.width = 320;
    img.height = 180;
    img.addEventListener("error", () => {
      img.remove();
    });
    thumb.appendChild(img);
    card.appendChild(thumb);

    const body = el("div", "body");
    const title = el("h2", "title");
    const titleLink = document.createElement("a");
    titleLink.href = video.url;
    titleLink.target = "_blank";
    titleLink.rel = "noopener noreferrer";
    titleLink.textContent = video.title;
    title.appendChild(titleLink);
    body.appendChild(title);
    body.appendChild(el("p", "channel", video.channel));

    const meta = el("div", "meta");
    const count = recommenderCount(video);
    const countLabel = count === 1 ? "1 recommender" : `${count.toLocaleString("en-US")} recommenders`;
    meta.appendChild(el("span", "recommenders", countLabel));
    meta.appendChild(el("span", "years", yearSpan(video)));
    meta.appendChild(el("span", "tag", video.topic));
    body.appendChild(meta);

    if (video.highlights.length) {
      body.appendChild(el("p", "why-label", "Why HN recommends it"));
      const links = el("ul", "why");
      for (const item of video.highlights.slice(0, 3)) {
        const li = document.createElement("li");
        const link = document.createElement("a");
        link.href = `https://news.ycombinator.com/item?id=${encodeURIComponent(item.id)}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `Comment by ${item.author}, ${item.created_at.slice(0, 4)}`;
        li.appendChild(link);
        if (item.excerpt) li.appendChild(el("p", "", item.excerpt));
        links.appendChild(li);
      }
      body.appendChild(links);
    }

    card.appendChild(body);
    list.appendChild(card);
  }
}

function showError(message) {
  $("subline").textContent = message;
  $("subline").classList.add("error");
}

async function main() {
  let response;
  try {
    response = await fetch("data/videos.json");
  } catch (error) {
    showError("Could not load data/videos.json. Serve this folder over HTTP.");
    return;
  }
  if (!response.ok) {
    showError(`Could not load data/videos.json (${response.status}).`);
    return;
  }
  const data = await response.json();
  const videos = Array.isArray(data.videos) ? data.videos.slice() : [];
  videos.sort(compare);
  videos.forEach((video, index) => {
    video.rank = index + 1;
  });
  state.videos = videos;

  const meta = data.meta || {};
  const from = (meta.scanned_from || "").slice(0, 4);
  const to = (meta.scanned_to || "").slice(0, 4);
  const scanned = Number(meta.comments_scanned);
  const range = from && to ? `${from}–${to}` : "";
  if (!Number.isFinite(scanned) || !videos.length) {
    showError("The data file has no countable corpus.");
    return;
  }
  $("subline").textContent = `${scanned.toLocaleString("en-US")} comments scanned · ${videos.length.toLocaleString("en-US")} videos · ${range}`;
  const minimum = Number(meta.min_recommenders) || 2;
  $("method").textContent = `Ranked by distinct Hacker News commenters (at least ${minimum} each). Comments come from the public HN Algolia index, searched for mathematics and AI-theory wording near YouTube, Vimeo, and TED links. Video IDs are normalised, titles and channels come from provider oEmbed, and off-topic links are dropped with the keyword rules in the README.`;

  $("q").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderList();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement !== $("q")) {
      event.preventDefault();
      $("q").focus();
    }
  });

  renderTopics();
  renderList();
}

main();
