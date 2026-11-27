# Liar's Cards

A two-player bluffing card game built on data structures (CSCI 353 project). Play it in the browser or as a desktop app.

**Play online:** https://aqilhesenzade.github.io/LiarsGI/

```
python -m http.server 8000     # web version locally: open http://localhost:8000/
pip install pygame
python gui.py                  # desktop version (add --bots to watch two bots)
python -m unittest -v test_game test_web
python bot_lab.py              # experiments for the presentation
```

## Rules

1. Each round a random **target colour** is chosen. Each player gets **9 cards**, split **2 : 3 : 4** over red / green / blue.
2. On your turn, **place 1 or 2 cards** face-down (claiming they are all the target colour), or **call LIE** on the other player's last play.
3. The called play is revealed. A non-target card means the **liar** loses a heart, otherwise the **caller** does.
4. A player with no cards must call. Every call ends the round. 0 hearts = you lose. Both players start with 2 hearts in the web version.

Keys (web): `R` `G` `B` pick a card, `Enter` place, `C` call LIE, `Esc` clear, `Space` skip animations.

## Data structures

| Structure (week) | Used for | Why | Cost |
|---|---|---|---|
| **Linked list** (3) | a player's hand, kept sorted | cards leave from the middle: re-point one pointer | remove O(h) |
| **Stack** (4) | the pile of plays | a call only looks at the latest play | push / pop / peek O(1) |
| **Max-heap** (8) | the bot's ranking of its moves | it wants the best of ~10 moves, not a full sort | build O(c), pop O(log c) |
| **Circular queue** (2, 4) | the bot's memory of your last 8 reactions | oldest out, newest in, nothing shifts | enqueue / dequeue O(1) |
| **Recursion + memoization** (1, 6) | the bot's look-ahead through the round | same state is solved only once | ~220 states instead of ~52,000 calls |

Time and space complexity of every function is in its docstring and collected in [COMPLEXITY.md](COMPLEXITY.md)
(`python gen_complexity.py` rebuilds it; a unit test fails if a function is missing the lines).

## How the bot decides

The number of target cards in a hand is 2, 3 or 4 (1/3 each), so a player who has placed 5 cards must be lying.
The bot turns this into `P(last play is a lie)`, scores every move in hearts (a call is worth `2p - 1`),
`heapify`s the moves into a max-heap, pops the top 3 and picks one with soft-max probabilities, so it is not predictable.
Its circular-queue memory adjusts how often it expects you to call.

## Files

| File | Purpose |
|---|---|
| `ds.py` | `LinkedList`, `Stack`, `MaxHeap`, `CircularQueue` (written from scratch) |
| `engine.py` | the rules (no printing, no input) |
| `bot.py` | probability model and the bot |
| `gui.py` | desktop version (pygame) |
| `webapi.py`, `web/`, `index.html` | browser version: the same Python runs in the page with [Pyodide](https://pyodide.org) (copy included in `web/pyodide/`, so no CDN is needed); `webapi.py` is a small JSON bridge that refuses out-of-turn moves and never sends the pile's colours before a call |
| `bot_lab.py` | experiments: recursion vs memoization, watch the bot learn, bot arena |
| `test_game.py`, `test_web.py` | unit tests (rules, bot, GUI, bridge, complexity audit) |
| `gen_complexity.py`, `COMPLEXITY.md` | complexity table generated from the docstrings |