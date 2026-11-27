/*
 * app.js -- the screen for "Liar's Cards" in the browser.
 *
 * All rules and all bot decisions come from Python (ds.py, engine.py, bot.py) running inside the
 * page via Pyodide; webapi.py is the JSON bridge.  This file only draws the state it is given and
 * turns clicks into bridge calls.  Nothing here knows the cards of the pile or how the bot thinks.
 *
 * Complexity (h = cards in a hand <= 9, p = plays on the pile): every redraw is O(h + p) for the hand and the
 * pile; a bridge call costs what its Python function costs (see webapi.py and COMPLEXITY.md).  Nothing here loops
 * over more than those few items.
 *
 * Page options (for testing):  ?fast  no animation delays   ?seed=42  fixed shuffle
 *                              ?debug  record bridge calls in window.__calls
 *                              ?pyodide=/url/  where Pyodide lives   ?src=/url/  where the .py files live
 */
"use strict";
(() => {
  const params = new URLSearchParams(location.search);
  const FAST = params.has("fast");
  const DEBUG = params.has("debug");
  const PYODIDE_VERSION = "0.27.7";
  // Pyodide is served from this site (web/pyodide/); the public CDN is only a fallback.
  const PYODIDE_BASES = params.get("pyodide")
    ? [params.get("pyodide")]
    : ["pyodide/", "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/"];
  const BOOT_TIMEOUT_MS = 60000;
  const SRC_BASE = params.get("src") || "../";
  const PY_FILES = ["ds.py", "engine.py", "bot.py", "webapi.py"];
  const PREF_KEY = "liarscards.prefs";

  const COLORS = [
    { cls: "c-red", name: "RED", letter: "R" },
    { cls: "c-green", name: "GREEN", letter: "G" },
    { cls: "c-blue", name: "BLUE", letter: "B" },
  ];

  // ------------------------------------------------------------------ small helpers
  const $ = (id) => document.getElementById(id);
  const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");
  const loses = (name) => name + (name === "You" ? " lose" : " loses");

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const HEART_PATH = "M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z";
  function heart(off, lost) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", (off ? "off" : "") + (lost ? " lost" : ""));
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", HEART_PATH);
    svg.appendChild(p);
    return svg;
  }

  let toastTimer = 0;
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
  }

  // sleeps that a key press / click can cut short ("skip animation")
  let skippers = [];
  function wait(ms) {
    if (FAST || ms <= 0) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => { clearTimeout(timer); skippers = skippers.filter((f) => f !== done); resolve(); };
      const timer = setTimeout(done, ms);
      skippers.push(done);
    });
  }
  const skip = () => skippers.slice().forEach((f) => f());

  // ------------------------------------------------------------------ Python / bridge
  let bridge = null;
  let bridgePromise = null;

  function call(name, args) {
    if (DEBUG) (window.__calls = window.__calls || []).push(name);
    return bridge(name, args);
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("could not load " + src));
      document.head.appendChild(s);
    });
  }

  function setPyStatus(msg, isError) {
    const el = $("py-status");
    el.textContent = msg;
    el.classList.toggle("err", !!isError);
  }

  async function bootFrom(base) {
    const indexURL = new URL(base, document.baseURI).href;
    await loadScript(indexURL + "pyodide.js");
    const py = await window.loadPyodide({ indexURL });
    for (const f of PY_FILES) {
      const res = await fetch(SRC_BASE + f, { cache: "no-cache" });
      if (!res.ok) throw new Error("could not fetch " + f + " (HTTP " + res.status + ")");
      py.FS.writeFile("/home/pyodide/" + f, await res.text());
    }
    py.runPython("import sys\nif '/home/pyodide' not in sys.path:\n    sys.path.insert(0, '/home/pyodide')");
    const mod = py.pyimport("webapi");
    return (name, args) => JSON.parse(mod.dispatch(name, JSON.stringify(args || {})));
  }

  // try each Pyodide location in turn; a location that hangs is given up after BOOT_TIMEOUT_MS
  async function bootPython() {
    let lastErr = null;
    for (const base of PYODIDE_BASES) {
      let timer;
      try {
        const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("timed out loading " + base)), BOOT_TIMEOUT_MS); });
        return await Promise.race([bootFrom(base), timeout]);
      } catch (err) {
        console.warn("Pyodide from " + base + " failed:", err);
        lastErr = err;
      } finally {
        clearTimeout(timer);
      }
    }
    throw lastErr;
  }

  function startBoot() {
    $("btn-retry").hidden = true;
    const buttons = [$("btn-vs"), $("btn-watch")];
    buttons.forEach((b) => { b.disabled = true; });
    setPyStatus("Loading…");
    bridgePromise = bootPython().then(
      (b) => {
        bridge = b;
        buttons.forEach((b) => { b.disabled = false; });
        setPyStatus("");
        document.body.dataset.ready = "1";
      },
      (err) => {
        console.error(err);
        setPyStatus("Could not start the game: " + err.message + ". Check your connection and try again.", true);
        $("btn-retry").hidden = false;
      }
    );
  }

  // ------------------------------------------------------------------ match settings
  // No settings screen: 2 hearts, the sharp bot, you open round 1.  (?hp=N and ?seed=N are for testing only.)
  const HP = parseInt(params.get("hp"), 10) || 2;
  const SEED = /^\d+$/.test(params.get("seed") || "") ? parseInt(params.get("seed"), 10) : null;

  // ------------------------------------------------------------------ game state
  let S = null;               // the last state sent by Python
  let gen = 0;                // bumped for every new match, so stale async work can stop itself
  let acceptInput = false;    // true only while it is the human's turn and nothing is animating
  let lastOpts = null;
  let hpView = null;          // hearts shown during a reveal (before the lost heart is taken)
  let lostFlash = null;       // {player, index} heart to play the "break" animation on
  let revealResolve = null;
  let lastRound = 0;
  let handKey = "";
  let pileCount = 0;
  let pileRound = 0;
  const sel = new Set();      // indexes (into the hand shown) of the cards picked to play

  const botName = () => S.names[1];
  const targetInfo = () => COLORS[S.target];

  // ------------------------------------------------------------------ drawing
  function cardEl(color, opts) {
    const o = opts || {};
    const c = COLORS[color];
    const el = h(o.button ? "button" : "div", {
      class: "card " + c.cls + (o.small ? " small" : ""),
      type: o.button ? "button" : false,
      "data-color": c.letter,
      "aria-label": o.label || c.name.toLowerCase() + " card",
    },
      h("span", { class: "corner", "aria-hidden": "true" }, c.letter),
      h("span", { class: "mid", "aria-hidden": "true" }, c.letter),
      h("span", { class: "corner br", "aria-hidden": "true" }, c.letter));
    return el;
  }

  function backEl(small) {
    return h("div", { class: "card back" + (small ? " small" : ""), "aria-hidden": "true" },
      h("span", { class: "mid" }, "?"));
  }

  function renderHearts(i) {
    const hp = hpView ? hpView[i] : S.hp[i];
    const box = $("hearts-" + i);
    box.replaceChildren();
    for (let k = 0; k < S.hp_max; k++) {
      const lost = lostFlash && lostFlash.player === i && lostFlash.index === k;
      box.appendChild(heart(k >= hp, lost));
    }
    box.setAttribute("aria-label", S.names[i] + " has " + plural(hp, "heart") + " of " + S.hp_max);
  }

  function renderSeats() {
    for (let i = 0; i < 2; i++) {
      $("name-" + i).textContent = S.names[i];
      renderHearts(i);
      $("seat-" + i).classList.toggle("turn", S.current === i && !S.round_over && !S.game_over);
    }
  }

  function renderOppHand() {
    const box = $("hand-1");
    box.classList.add("opp-hand");
    const key = "b" + S.counts[1] + "|" + S.round;
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.replaceChildren();
    for (let k = 0; k < S.counts[1]; k++) box.appendChild(backEl(true));
  }

  function renderMyHand() {
    const box = $("hand-0");
    const hand = S.hand;
    const key = (S.spectator ? "b" + S.counts[0] : hand.join("")) + "|" + S.round + "|" + S.spectator;
    if (key !== handKey) {
      handKey = key;
      box.replaceChildren();
      box.classList.toggle("opp-hand", S.spectator);
      if (S.spectator) {
        for (let k = 0; k < S.counts[0]; k++) box.appendChild(backEl(true));
      } else {
        hand.forEach((c, i) => {
          const el = cardEl(c, { button: true, label: COLORS[c].name.toLowerCase() + " card, " + (i + 1) + " of " + hand.length });
          el.addEventListener("click", () => toggleCard(i));
          box.appendChild(el);
        });
      }
    }
    if (S.spectator) return;
    const locked = !acceptInput;
    box.classList.toggle("locked", locked);
    [...box.children].forEach((el, i) => {
      el.classList.toggle("sel", sel.has(i));
      el.setAttribute("aria-pressed", sel.has(i) ? "true" : "false");
      el.disabled = locked;
    });
  }

  function renderPile() {
    const box = $("pile");
    if (pileRound !== S.round || S.pile.length < pileCount) {
      box.replaceChildren();
      pileCount = 0;
      pileRound = S.round;
    }
    if (S.pile.length === 0) {
      box.replaceChildren();
      pileCount = 0;
      return;
    }
    if (pileCount === 0) box.replaceChildren();
    for (let i = pileCount; i < S.pile.length; i++) {
      const p = S.pile[i];
      const play = h("div", { class: "play", "data-player": p.player },
        Array.from({ length: p.size }, () => backEl(true)),
        h("span", { class: "tag" }, S.names[p.player] + " ×" + p.size));
      box.appendChild(play);
    }
    pileCount = S.pile.length;
    [...box.children].forEach((el, i) => el.classList.toggle("top", i === S.pile.length - 1));
    box.setAttribute("aria-label", "Pile: " + plural(S.pile.length, "face-down play"));
  }

  function renderHud() {
    $("hud-round").textContent = S.round;
    const t = targetInfo();
    const chip = $("target-chip");
    chip.textContent = t.name;
    chip.className = "chip " + t.cls;
    if (S.round !== lastRound) {
      lastRound = S.round;
      chip.classList.remove("pulse");
      void chip.offsetWidth;
      chip.classList.add("pulse");
    }
  }

  function setStatus(...nodes) { $("status").replaceChildren(...nodes); }

  function statusForHuman() {
    const t = targetInfo().name;
    if (S.must_call) return "You have no cards left, so you must call LIE!";
    if (S.can_call) {
      const top = S.pile[S.pile.length - 1];
      return botName() + " placed " + plural(top.size, "card") + " and claims " + (top.size === 1 ? "it is " : "they are all ") + t + ". Believe it, or call LIE?";
    }
    return "";
  }

  function renderControls() {
    const myTurn = acceptInput && !S.spectator;
    $("btn-play").disabled = !(myTurn && !S.must_call && sel.size >= 1 && sel.size <= 2);
    $("btn-call").disabled = !(myTurn && S.can_call);
    $("btn-clear").disabled = !(myTurn && sel.size > 0);
    const n = sel.size;
    $("btn-play").textContent = n ? "Place " + plural(n, "card") : "Place cards";
    $("actions").hidden = S.spectator;
    $("game").dataset.turn = acceptInput ? "human" : "wait";
  }

  function render() {
    renderHud();
    renderSeats();
    renderOppHand();
    renderMyHand();
    renderPile();
    renderControls();
  }

  // ------------------------------------------------------------------ log
  function log(text, cls) {
    const ol = $("log");
    ol.append(h("li", { class: cls || "" }, text));
    while (ol.children.length > 80) ol.firstChild.remove();
    ol.scrollTop = ol.scrollHeight;
  }

  function logRound() {
    log("Round " + S.round + " · target " + targetInfo().name + " · " + S.names[S.current] + (S.names[S.current] === "You" ? " open" : " opens"), "round");
  }

  function letters(cards) { return cards.map((c) => COLORS[c].letter).join(" "); }

  function logCall(res) {
    const lie = res.was_lie ? "a LIE" : "honest";
    const cls = S.spectator ? "" : res.loser === 0 ? "bad" : "good";
    log(S.names[res.caller] + " called LIE on " + S.names[res.accused] + "'s play [" + letters(res.cards) + "]: " + lie + ". " + loses(S.names[res.loser]) + " a heart.", cls);
  }

  // ------------------------------------------------------------------ turn flow
  async function advance(token) {
    while (token === gen) {
      if (S.round_over || S.game_over) return;
      const botTurn = S.spectator || S.current === 1;
      if (!botTurn) {
        acceptInput = true;
        render();
        setStatus(statusForHuman());
        return;
      }
      acceptInput = false;
      render();
      const who = S.names[S.current];
      setStatus(h("span", { class: "think" }, who + " is thinking"));
      await wait(S.spectator ? 900 + Math.random() * 500 : 600 + Math.random() * 600);
      if (token !== gen) return;
      const r = call("bot_move");
      if (!r.ok) { toast(r.error); return; }
      S = r.state;
      if (r.kind === "call") {
        logCall(r.result);
        await reveal(r.result, token);
        return;
      }
      log(S.names[r.player] + " placed " + plural(r.size, "card") + (r.cards ? " [" + letters(r.cards) + "]" : ""));
      render();
      await wait(300);
    }
  }

  async function humanPlay() {
    if (!acceptInput || sel.size < 1 || sel.size > 2) return;
    const token = gen;
    const cards = [...sel].sort((a, b) => a - b);
    const mine = cards.map((i) => S.hand[i]);
    acceptInput = false;
    const r = call("human_play", { cards });
    if (!r.ok) { acceptInput = true; toast(r.error); render(); return; }
    sel.clear();
    S = r.state;
    log("You placed " + plural(r.size, "card") + " [" + letters(mine) + "]", "me");
    render();
    await advance(token);
  }

  async function humanCall() {
    if (!acceptInput || !S.can_call) return;
    const token = gen;
    acceptInput = false;
    const r = call("human_call");
    if (!r.ok) { acceptInput = true; toast(r.error); render(); return; }
    sel.clear();
    S = r.state;
    logCall(r.result);
    await reveal(r.result, token);
  }

  function toggleCard(i) {
    if (!acceptInput) return;
    if (sel.has(i)) sel.delete(i);
    else if (sel.size >= 2) { toast("A play is 1 or 2 cards"); return; }
    else sel.add(i);
    renderMyHand();
    renderControls();
  }

  function pickLetter(letter) {
    if (!acceptInput) return;
    const hand = S.hand;
    const idxs = hand.map((c, i) => (COLORS[c].letter === letter ? i : -1)).filter((i) => i >= 0);
    if (!idxs.length) { toast("You hold no " + COLORS.find((c) => c.letter === letter).name.toLowerCase() + " card"); return; }
    const free = idxs.find((i) => !sel.has(i));
    if (free !== undefined) {
      if (sel.size >= 2) { toast("A play is 1 or 2 cards"); return; }
      sel.add(free);
    } else {
      idxs.forEach((i) => sel.delete(i));
    }
    renderMyHand();
    renderControls();
  }

  // ------------------------------------------------------------------ reveal + game over
  function flipCard(color) {
    const front = cardEl(color);
    front.classList.add("face", "front");
    const back = backEl(false);
    back.classList.add("face");
    return h("span", { class: "flip" }, h("div", { class: "inner" }, back, front));
  }

  function waitForNext(spectatorAuto) {
    return new Promise((resolve) => {
      revealResolve = resolve;
      $("reveal-next").onclick = () => resolve();
      if (spectatorAuto) wait(3200).then(resolve);
    });
  }

  async function reveal(res, token) {
    acceptInput = false;
    const dlg = $("reveal");
    const next = $("reveal-next");
    const t = targetInfo();
    const oldHp = S.hp.slice();
    oldHp[res.loser] += 1;
    hpView = oldHp;
    render();
    setStatus(S.names[res.caller] + " called LIE!");

    $("reveal-title").className = "";
    $("reveal-title").textContent = S.names[res.caller] + " called LIE!";
    $("reveal-sub").textContent = S.names[res.accused] + " placed " + plural(res.cards.length, "card") + " and claimed " + (res.cards.length === 1 ? "it is " : "they are all ") + t.name + ". The pile's top play is turned over:";
    const verdict = $("reveal-verdict");
    verdict.className = "verdict";
    verdict.textContent = "";
    const row = $("reveal-cards");
    const flips = res.cards.map((c) => flipCard(c));
    row.style.minHeight = "";
    row.replaceChildren(...flips);
    $("reveal-menu").hidden = true;
    next.disabled = true;
    next.textContent = "…";
    if (!dlg.open) dlg.showModal();

    await wait(850);
    if (token !== gen) return;
    flips.forEach((f, i) => f.classList.add("flipped", res.cards[i] === S.target ? "ok" : "bad"));
    await wait(900);
    if (token !== gen) return;

    hpView = null;
    lostFlash = { player: res.loser, index: S.hp[res.loser] };
    render();
    lostFlash = null;
    const loser = S.names[res.loser];
    if (!S.spectator) verdict.classList.add(res.loser === 0 ? "lie" : "honest");   // red when it hurts you, green when it hurts the bot
    verdict.textContent = (res.was_lie ? "LIE! " : "Honest! ") + loses(loser) + " a heart (" + S.hp[res.loser] + " left).";
    setStatus(verdict.textContent);
    next.textContent = S.game_over ? "See result" : "Next round";
    next.disabled = false;
    next.focus();

    await waitForNext(S.spectator);
    revealResolve = null;
    if (token !== gen) return;

    if (S.game_over) {
      await gameOver(token);
      return;
    }
    dlg.close();
    const r = call("next_round");
    if (!r.ok) { toast(r.error); return; }
    S = r.state;
    sel.clear();
    logRound();
    render();
    await advance(token);
  }

  async function gameOver(token) {
    const dlg = $("reveal");
    const next = $("reveal-next");
    const youWon = !S.spectator && S.winner === 0;
    const title = $("reveal-title");
    title.textContent = S.spectator ? S.names[S.winner] + " wins the match!" : youWon ? "You win!" : botName() + " wins.";
    title.className = youWon || S.spectator ? "win" : "";
    $("reveal-sub").textContent = S.spectator
      ? "Two bots, " + plural(S.rounds, "round") + "."
      : youWon ? "You out-bluffed the bot." : "The bot read you this time. Rematch?";
    $("reveal-cards").style.minHeight = "0";
    $("reveal-cards").replaceChildren(h("p", { class: "stats" },
      plural(S.rounds, "round") + " played · " + plural(S.caught, "lie") + " caught"));
    $("reveal-verdict").textContent = "";
    $("reveal-verdict").className = "verdict";
    next.textContent = "Play again";
    next.disabled = false;
    next.focus();
    $("reveal-menu").hidden = false;
    log("Match over: " + (S.spectator ? S.names[S.winner] : youWon ? "you" : botName()) + " won.", "round");
    setStatus(title.textContent);
    await new Promise((resolve) => {
      revealResolve = resolve;
      next.onclick = () => { dlg.close(); startMatch(Object.assign({}, lastOpts, { seed: null })); resolve(); };
      $("reveal-menu").onclick = () => { dlg.close(); showStart(); resolve(); };
    });
    revealResolve = null;
  }

  // ------------------------------------------------------------------ screens
  function cancelPending() {
    gen++;
    acceptInput = false;
    skip();
    if (revealResolve) { const r = revealResolve; revealResolve = null; r(); }
    const dlg = $("reveal");
    if (dlg.open) dlg.close();
  }

  function showStart() {
    cancelPending();
    $("game").hidden = true;
    $("start").hidden = false;
    $("btn-menu").hidden = true;
  }

  function startMatch(opts) {
    cancelPending();
    const token = gen;
    lastOpts = opts;
    const r = call("new_match", { hp: opts.hp, seed: opts.seed, spectator: opts.watch, easy: false, bot_first: false });
    if (!r.ok) { toast(r.error); return; }
    S = r.state;
    sel.clear();
    hpView = null;
    lostFlash = null;
    lastRound = 0;
    handKey = "";
    pileCount = 0;
    pileRound = 0;
    $("hand-1").dataset.key = "";
    $("pile").replaceChildren();
    $("log").replaceChildren();
    $("start").hidden = true;
    $("game").hidden = false;
    $("btn-menu").hidden = false;
    logRound();
    render();
    advance(token);
    $("game").scrollIntoView({ block: "start" });
  }

  // ------------------------------------------------------------------ wiring
  function openDialog(id) { const d = $(id); if (!d.open) d.showModal(); }

  function init() {
    if (window.matchMedia("(max-width: 960px)").matches) $("log-panel").open = false;
    $("btn-vs").addEventListener("click", () => { if (bridge) startMatch({ watch: false, hp: HP, seed: SEED }); });
    $("btn-watch").addEventListener("click", () => { if (bridge) startMatch({ watch: true, hp: HP, seed: SEED }); });
    $("btn-retry").addEventListener("click", startBoot);
    $("btn-menu").addEventListener("click", showStart);
    $("btn-rules").addEventListener("click", () => openDialog("rules"));
    $("btn-hood").addEventListener("click", () => openDialog("hood"));
    document.querySelectorAll("dialog [data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));
    $("reveal").addEventListener("cancel", (e) => e.preventDefault());   // Esc must not skip the reveal

    $("btn-play").addEventListener("click", humanPlay);
    $("btn-call").addEventListener("click", humanCall);
    $("btn-clear").addEventListener("click", () => { sel.clear(); if (S) { renderMyHand(); renderControls(); } });

    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === " ") {
        skip();
        return;
      }
      if (document.querySelector("dialog[open]") || !S || $("game").hidden) return;
      const tag = e.target.tagName;
      if (tag === "INPUT" && e.target.type !== "checkbox") return;
      if (!acceptInput) return;
      const k = e.key.toLowerCase();
      if (k === "r" || k === "g" || k === "b") { pickLetter(k.toUpperCase()); }
      else if (e.key === "Enter") {
        const isOtherButton = tag === "BUTTON" && !e.target.classList.contains("card");
        if (isOtherButton) return;
        e.preventDefault();
        humanPlay();
      } else if (k === "c") { humanCall(); }
      else if (e.key === "Escape" || e.key === "Backspace") { sel.clear(); renderMyHand(); renderControls(); }
    });

    startBoot();
  }

  init();
})();
