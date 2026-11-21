# Liar's Cards — a tiny bluffing game built on Data Structures

A 2-player, terminal version of the Liar's Bar idea, made for the CSCI 353 project.
One match takes **about 1.5–3 minutes** (3 hearts each, ~4 rounds, ~9 moves per side).
No external libraries — Python 3.8+ only.

```
python cli.py            # you vs the bot (ASCII-art terminal UI)
python cli.py --bots     # bot vs bot: you only watch (best way to explain the heap)
python cli.py --help     # --easy  --coach  --xray  --seed N  --hp N  --fast  --bot-first  --no-color  --no-clear
python gui.py            # the same game in a pygame window (pip install pygame); also --bots --xray --coach --fast
python -m unittest -v test_game
```

**Tip for the live demo:** use a terminal at least **78 x 30** (Windows Terminal / VS Code terminal / macOS Terminal
all work; the old `cmd.exe` falls back to plain ASCII automatically). The screen is redrawn every turn, so make the
font big enough for the back row of the room.

## Rules

1. Each round a random **target colour** is announced. Each player gets **9 cards** split **2 : 3 : 4** over
   Red / Green / Blue (which colour gets which number is random).
2. Players alternate. On your turn you **play 1 or 2 cards** face-down, claiming *"all target colour"* (no passing) —
   **or** you **call LIE** on the opponent's previous play (impossible for the first play of a round).
3. A call reveals the top play: if it contained a non-target card the **liar** loses 1 heart, otherwise the **caller** does.
4. A player who has run out of cards **must** call. The round ends at every call. 0 hearts = you lose.

*Refinements added to the original idea:* hearts instead of instant death (more rounds = more probability to
show), forced call on empty hand (guarantees every round ends), and the round opener alternates.

Controls (CLI): `r` / `g` / `b` / `rg` / `r b` / `rr` play cards · `c` call LIE · `?` probability coach · `x` x-ray · `q` quit.
Controls (GUI): click cards (or press R / G / B) · Enter = play · C = call LIE · ? coach · X x-ray · Space skips an animation.

### What the terminal screen shows

```
╔══ LIAR'S CARDS ═══════════════════ round, target colour chip and both players' hearts ═╗
╠══ BOT ═════ his hand, face-down (x-ray turns them face-up) ═════════════════════════════╣
╠══ THE PILE • a stack (LIFO) ═ the top 3 plays, TOP ▶ marks what a call will pop() ══════╣
╠══ LAST MOVES ═══ what just happened ════════════════════════════════════════════════════╣
╠══ COACH / BOT'S MIND ═══ (optional) P(lie) bar  /  the bot's heap ranking ═══════════════╣
╠══ YOUR HAND • linked list ═ big colour cards, ▲ under target cards, head ▶ R ▶ G … None ╣
```

A call plays a short animation: the top play is popped face-down, flips over, and a big ASCII **LIE!** / **TRUTH!**
decides who loses a heart.

## Files

| File | Purpose |
|---|---|
| `ds.py` | The three hand-made data structures: `LinkedList`, `Stack`, `MaxHeap` |
| `engine.py` | Rules only (no printing / input): `Game`, `Player`, `Play`, `CallResult`, `Observation` |
| `bot.py` | Probability model (`p_play_is_lie`, `odds_rows`) + heap-driven `Bot` |
| `cli.py` | Terminal UI (`CLIGame`, `Style`) and `main()` - card art, animated reveal, coach, x-ray |
| `art.py` | The ASCII-art lettering (title, LIE!, TRUTH!, YOU WIN ...) - pure data |
| `gui.py` | pygame front-end; it *draws* the linked list, the stack and the heap tree |
| `test_game.py` | 45 unit tests, incl. a headless GUI run and an audit that **every function documents Time & Space** |
| `gen_complexity.py` | Rebuilds `COMPLEXITY.md` from the docstrings (`python gen_complexity.py`) |
| `COMPLEXITY.md` | Time/space of all 157 functions (generated from the docstrings) |

The engine knows nothing about the UI, so the CLI and the pygame GUI both reuse `engine.py` + `bot.py` unchanged.

## Where each syllabus topic is used

| Topic (week) | Where | Why this structure | Advantage | Disadvantage |
|---|---|---|---|---|
| **Linked list** (3) | a player's **hand** — `LinkedList`, kept sorted by `insert_sorted` | cards leave from the *middle* of the hand | removing = re-pointing one pointer, no shifting | no random access; every search/insert walks the list: O(h) |
| **Stack** (4) | the **table pile** — `Stack` (array-backed) | a call only ever looks at the *latest* play: last in, first out | `push` / `pop` / `peek` are all O(1) | can only reach the top; the array occasionally has to grow |
| **Heap** (8) | the bot's **priority queue of moves** — `MaxHeap` | the bot wants the *best* of ~10 scored moves, not a full sort | `heapify` is O(c); each `pop` O(log c) | not sorted, only the root is guaranteed best |
| Complexity (1) | every function's docstring | course requirement | — | — |
| Arrays (2) | the `[red, green, blue]` counts and the heap's backing array | direct indexing by colour | O(1) access | fixed meaning of each index |

Linked list = *node-based*, stack and heap = *array-based*: one project shows both ways of storing a sequence.

## The probability (the part worth a slide)

Colours are split 2:3:4 in random order and the target is random, so the number **T** of target cards in any
hand is **2, 3 or 4 with probability 1/3 each**.

| Cards the opponent placed this round (n) | 1 | 2 | 3 | 4 | 5+ |
|---|---|---|---|---|---|
| P(they could be fully honest) = P(T ≥ n) | 100% | 100% | 67% | 33% | **0%** |

So placing a 5th card is a *guaranteed* lie. Before that, the model adds a per-card bluff chance *b* = 0.20:

`P(last play is a LIE) = F + (1 − F) · (1 − (1 − b)^m)`, with `F = 1 − P(T ≥ n)` and `m` = cards in that play.

Calling is worth `2p − 1` hearts (+1 if it was a lie, −1 if not), so **calling is profitable when p > 50%**.
The `?` coach shows this live to the human; the bot uses exactly the same function.

## How the bot thinks (`Bot.decide`)

1. Score every legal move in hearts (the call, and every distinct 1-/2-card play).
   For a play: chance the opponent calls × (+1 if honest, −1 if bluff) + small bonuses for keeping target cards
   and a penalty for emptying its hand (then *it* is forced to call).
2. `heapify` the scored moves into a **max-heap** — O(c).
3. `pop` the **top 3** — O(K log c).
4. Pick one with **soft-max probabilities** → a *mixed strategy*: usually the best move, sometimes a bluff, so it
   is unpredictable. `--easy` flattens the distribution (bot wins ≈ 67% vs a naive player instead of ≈ 91%).

`x` (or `--bots`) shows this heap ranking each turn - the top-3 moves with their soft-max chances, the chosen one
marked, plus the heap's backing array - e.g. `2  +0.27  play R (honest)  ████░░░░░░░░  36%  ◀ chosen`.

## Suggested 2–3 minute live demo

1. `python cli.py --seed 4 --coach` — fixed seed = same game every time, so it can be rehearsed.
2. Let a classmate play; whenever the coach shows a probability near 50 %, ask the class *"call or play?"* (interactive vote).
3. When the bot reveals a bluff, press `x` to show its hand and the heap ranking (Heap + soft-max).
4. Fallback if a student is slow: `python cli.py --bots` (bot vs bot, ~30 s; `--fast` ≈ 10 s).

## Ideas to extend (optional)

- pygame front-end calling the same `Game` / `Bot` objects.
- Learn the opponent's real bluff rate from `game.history` (Bayesian update of `b`).
- 3+ players: replace the alternating index with a circular **queue** of turns.
- Bot-vs-bot tournament to tune `TEMPERATURE` / `BLUFF_PRIOR`.

## Changelog of this version

- **Fixed `gui.py` crash:** the heap panel read `decision.heap` / `decision.chosen`, which `bot.Decision` did not
  have, so `--bots` mode crashed on the bot's first move and normal mode crashed as soon as X-ray was on.
  `Decision` now carries both (`MaxHeap.to_list()` snapshots the heap right after `heapify`).
- **Fixed GUI clock:** the first match started at time 0 instead of "now", so the round intro was skipped and
  `--bot-first` made the bot act instantly. Also: the reveal card no longer overlaps the verdict text, and a stray
  click cannot skip the first half second of a reveal.
- **New terminal UI** (`cli.py` + `art.py`): framed table, colour card tiles, linked-list hand line, stack pile with a
  `TOP` marker, ASCII-art title / verdicts, animated card flip, spinner while the bot thinks, "press Enter for the
  next round" pacing. Falls back to plain ASCII / no colour automatically.
- **Tests:** 35 -> 45 (heap snapshot, frame alignment, coloured + spectator CLI runs, headless GUI run that also
  asserts the bot never acts while it is your turn).
