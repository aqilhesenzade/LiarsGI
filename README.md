# Liar's Cards — a tiny bluffing game built on Data Structures

A 2-player, pygame version of the Liar's Bar idea, made for the CSCI 353 project.
One match takes **about 1.5–3 minutes** (3 hearts each, ~4 rounds, ~9 moves per side).
Python 3.8+ and `pygame` are all you need.

```
pip install pygame
python gui.py             # you vs the bot
python gui.py --bots      # bot vs bot: you only watch (best way to explain the heap)
python gui.py --help      # --easy  --seed N  --hp N  --fast  --bot-first  --fullscreen
python -m unittest -v test_game
python -m unittest -v test_bot_upgrade   # tests of the bot upgrades
python bot_lab.py                         # 3 live experiments for the presentation (memo / learn / arena)
```

**Tip for the live demo:** run the window fullscreen (`F11`) so the back row can see the pile, the target chip and
the hearts. `--seed N` makes the shuffle repeatable, so the demonstration can be rehearsed.

## Rules

1. Each round a random **target colour** is announced. Each player gets **9 cards** split **2 : 3 : 4** over
   Red / Green / Blue (which colour gets which number is random).
2. Players alternate. On your turn you **play 1 or 2 cards** face-down, claiming *"all target colour"* (no passing) —
   **or** you **call LIE** on the opponent's previous play (impossible for the first play of a round).
3. A call reveals the top play: if it contained a non-target card the **liar** loses 1 heart, otherwise the **caller** does.
4. A player who has run out of cards **must** call. The round ends at every call. 0 hearts = you lose.

*Refinements added to the original idea:* hearts instead of instant death (more rounds = more probability to
show), forced call on empty hand (guarantees every round ends), and the round opener alternates.

Controls: click cards (or press R / G / B) · Enter = play · C = call LIE · Space skips an animation ·
Backspace/Esc clears the selection · F11 = fullscreen.

### What the window shows

* **Top plate:** the bot's name, hearts and card count; the bot's hand is face-down.
* **Felt board:** the pile as a stack, with the most recent play on top.
* **Bottom plate:** your name, hearts and card count, then your hand (the linked list) face-up. Small gold dots
  mark the cards that match the target colour.
* **Header:** the current target colour chip and the round number. The Play / Call buttons sit over the felt.

A round opens with a **card-dealing animation**: cards fly from the deck, alternating between the hands, and your
cards flip face-up as they land. The header hides the target while a **target-colour selector** spins and slows
down onto the chosen colour.

A call plays a short animation: the top play is popped face-down, flips over, and the verdict
(**It was a lie!** / **It was the truth!**) decides who loses a heart. The lost heart flashes, shrinks and bursts
into small shards next to the name plate, with a floating **−1**.

## Files

| File | Purpose |
|---|---|
| `ds.py` | The four hand-made data structures: `LinkedList`, `Stack`, `MaxHeap`, `CircularQueue` |
| `engine.py` | Rules only (no printing / input): `Game`, `Player`, `Play`, `CallResult`, `Observation` |
| `bot.py` | Probability model (`p_play_is_lie`, `odds_rows`) + the `Bot`: heap ranking, recursive memoized look-ahead, circular-queue opponent memory |
| `gui.py` | pygame front-end: dealing / target-selection / heart-loss animations; it *draws* the linked list, the stack and the heap tree |
| `bot_lab.py` | Presentation experiments: recursion vs memoization, watch the bot learn, classic-vs-upgraded arena |
| `test_bot_upgrade.py` | 19 tests for `CircularQueue`, `OpponentMemory`, the planner and bot strength |
| `test_game.py` | 39 unit tests, incl. a headless GUI run and an audit that **every function documents Time & Space** |
| `gen_complexity.py` | Rebuilds `COMPLEXITY.md` from the docstrings (`python gen_complexity.py`) |
| `COMPLEXITY.md` | Time/space of all 172 functions (generated from the docstrings) |

The engine knows nothing about the UI, so `gui.py` reuses `engine.py` + `bot.py` unchanged.

## Where each syllabus topic is used

| Topic (week) | Where | Why this structure | Advantage | Disadvantage |
|---|---|---|---|---|
| **Linked list** (3) | a player's **hand** — `LinkedList`, kept sorted by `insert_sorted` | cards leave from the *middle* of the hand | removing = re-pointing one pointer, no shifting | no random access; every search/insert walks the list: O(h) |
| **Stack** (4) | the **table pile** — `Stack` (array-backed) | a call only ever looks at the *latest* play: last in, first out | `push` / `pop` / `peek` are all O(1) | can only reach the top; the array occasionally has to grow |
| **Heap** (8) | the bot's **priority queue of moves** — `MaxHeap` | the bot wants the *best* of ~10 scored moves, not a full sort | `heapify` is O(c); each `pop` O(log c) | not sorted, only the root is guaranteed best |
| **Queue** (4) | the bot's **memory of the opponent** — `CircularQueue` (array-based ring buffer) | only the last `WINDOW` = 8 reactions matter: oldest out, newest in | `enqueue` / `dequeue` are O(1) and nothing is ever shifted or re-allocated | fixed capacity: the bot forgets older behaviour |
| **Recursion + memoization / DP** (1, 6) | the bot's **look-ahead** — `Bot.value` / `Bot.play_value` with a memo dictionary | the value of "the game goes on" is defined in terms of the same function on a smaller state | memo: ~220 states instead of ~52,000 calls at 8 cards left (same answer) | uses O(S) extra memory; only as good as its opponent model |
| Complexity (1) | every function's docstring | course requirement | — | — |
| Arrays (2) | the `[red, green, blue]` counts, the heap's backing array and the queue's ring buffer | direct indexing | O(1) access | fixed meaning of each index |

Linked list = *node-based*, stack / heap / queue = *array-based*: one project shows both ways of storing a sequence.

## The probability (the part worth a slide)

Colours are split 2:3:4 in random order and the target is random, so the number **T** of target cards in any
hand is **2, 3 or 4 with probability 1/3 each**.

| Cards the opponent placed this round (n) | 1 | 2 | 3 | 4 | 5+ |
|---|---|---|---|---|---|
| P(they could be fully honest) = P(T ≥ n) | 100% | 100% | 67% | 33% | **0%** |

So placing a 5th card is a *guaranteed* lie. Before that, the model adds a per-card bluff chance *b* = 0.20:

`P(last play is a LIE) = F + (1 − F) · (1 − (1 − b)^m)`, with `F = 1 − P(T ≥ n)` and `m` = cards in that play.

Calling is worth `2p − 1` hearts (+1 if it was a lie, −1 if not), so **calling is profitable when p > 50%**.
The bot uses exactly this function to score a call and compare it with its card plays.

## How the bot thinks (`Bot.decide`)

1. **Settle** — if the bot played last turn, compare what it *predicted* (the opponent calls with chance q) with what
   *happened*, and push `(q, called?)` into the `CircularQueue` memory (Upgrade B).
2. **Score every legal move** in hearts (the call, and every distinct 1-/2-card play). A call is worth `2p − 1`.
   A play is worth `q·(+1 honest / −1 bluff) + (1−q)·(value of the rest of the round)`, and that second part is
   now computed by a **recursive, memoized look-ahead** (Upgrade A) instead of a hand-tuned bonus.
3. `heapify` the scored moves into a **max-heap** — O(c).
4. `pop` the **top 3** — O(K log c).
5. Pick one with **soft-max probabilities** → a *mixed strategy*: usually the best move, sometimes the runner-up, so it
   is unpredictable. `--easy` flattens the distribution (see the table below).

### Upgrade A — look-ahead by recursion + memoization (weeks 1 and 6)

```
value(state) = max( CALL ,  max over my plays of  q·(±1) + (1−q)·E[ value(next state) ] )
state        = (target cards left t, other cards left o, opponent cards placed, size of its last play)
```

* The recursion ends because every play uses up cards; with no cards the bot is forced to call.
* There are only ~1300 different states, but millions of paths lead to them → a **memo dictionary** stores each
  state the first time it is solved. At 8 cards left: **219 states instead of 51,717 recursive calls, same answer**
  (`python bot_lab.py memo`).
* It finds things the old one-move bot could not: e.g. when the opponent has already placed 4 cards and I hold honest
  cards, an honest play is a *forced win* (the opponent must either call an honest play or place a 5th card, which
  is a certain lie) — the classic bot valued that at +0.49 and preferred to call; the look-ahead values it at +1.00.

### Upgrade B — opponent memory in a circular queue (weeks 2 and 4)

```
queue (last 8 reactions):  o o X o X X      o = did not call my play,  X = called
q_used = adjust(q_model)   if the opponent calls MORE than I predicted: shrink the chance of "no call"
                           if it calls LESS than I predicted:           shrink the chance of a call
```

* With no data the correction does nothing; `PRIOR_WEIGHT` makes the first events move the estimate only gently.
* It learns from every turn (it sees whether you called or played on), not just from the rare reveals.
* Memory lives in the `Bot` object, so each new match starts with a blank memory (the GUI creates new bots per match).
* Visible in `python bot_lab.py learn`: against a never-calling opponent the bot's "coin-flip play gets called"
  estimate falls from 50% to ~15%; against an always-caller it climbs to ~80%.

### Measured strength (scripted opponents, 2000 matches each, seats alternate)

| Opponent style | classic bot | upgraded bot |
|---|---|---|
| never calls (only when forced) | 27% | **98%** |
| always calls | 94% | **100%** |
| calls when lie-chance > 50% | 86% | **100%** |
| calls with the bot's own "typical" odds | 86% | **94%** |
| calls 55% at random | 83% | 83% |
| bluffs 40%, calls > 50% | 90% | **99.5%** |
| plays random cards, calls 30% | 86% | **78% (worse)** |
| **mean** | **79%** | **93%** |

Head to head, upgraded vs classic: **87%** for the upgraded bot. `--easy` (`temperature=2.0, top_k=5`) still works as
a difficulty knob: mean 93% → 56% for the upgraded bot. (The old "≈91% / ≈67%" figures in the previous README came
from a different naive player, so they are not comparable.) `python bot_lab.py arena` reproduces this table.

### Advantages and disadvantages (say these out loud in the presentation)

| | Advantage | Disadvantage |
|---|---|---|
| Recursion + memo | looks several moves ahead; exact within its model; < 1 ms per decision | needs O(S) extra memory; answers are only as good as the opponent model |
| Circular queue memory | adapts to *you*; O(1) updates; bounded memory | forgets older behaviour; needs a few events before it trusts them; a clever opponent could mislead it |
| Max-heap + soft-max | O(c) build, cheap top-K; unpredictable | overkill for c ≤ 10 (a sort would be as fast) |
| The model itself | one slide of maths, explainable | assumes opponents spend honest cards first (so the 5th card is "certainly" a lie) — a player who bluffs *early* and saves honest cards for the end breaks that assumption, and a purely random player is the one style the upgrade plays worse against |

## Suggested 2–3 minute live demo

1. `python gui.py --seed 4` — fixed seed = same game every time, so it can be rehearsed.
2. Let a classmate play; when the choice is close, ask the class *"call or play?"* (interactive vote).
3. When the bot calls LIE or gets caught bluffing, point out the revealed card and the heart-loss animation. The
   decision came from the heap ranking + soft-max mixed strategy.
4. Fallback if a student is slow: `python gui.py --bots --fast` (bot vs bot, you just watch).
5. **Interactive recap of the syllabus** with `python bot_lab.py`:
   * `memo` — ask the class *"how many recursive calls will 8 cards need?"* before showing 51,717 vs 219 (recursion, DP).
   * `learn` — let the class pick the opponent style (always / never calls ...) and *predict* what the queue will look like.
   * `arena` — ask *"which style will beat the upgraded bot?"* and reveal `random` (disadvantage of model-based bots).

## Ideas to extend (optional)

- Learn the opponent's real *bluff* rate too (the bot already learns its *call* rate; bluffs are only revealed on calls, so there is little data).
- Add an optional debug panel that shows `bot.memory.text()` and `Decision.eager` / `Decision.states`.
- 3+ players: replace the alternating index with a circular **queue** of turns.
- Bot-vs-bot tournament to tune `TEMPERATURE` / `BLUFF_PRIOR`.

## Changelog of this version

- **GUI-only release:** the pygame window (`gui.py`) is now the only front-end.
- **Round intro animations:** cards fly from the deck to both hands (your cards flip face-up as they land), then a
  target-colour selector spins, slows down and lands on the round's target. The header shows `Target: ???` until
  the selector settles.
- **Losing-heart animation:** the lost heart flashes, shrinks and bursts into small shards, with a floating `−1`
  next to the name plate.
- **Fewer words:** the old round-opening prompt is gone; the Play / Call buttons carry the action.
- **Timing fixes:** the first match starts at "now", the reveal card no longer overlaps the verdict text, and a
  stray click cannot skip the first part of a reveal.
- **Tests:** 39 unit tests, including a headless GUI run that also asserts the bot never acts while it is your turn.

## Changelog of the bot upgrade

- **`ds.py`:** new `CircularQueue` (array ring buffer, O(1) enqueue/dequeue).
- **`bot.py`:** new `OpponentMemory`, recursive memoized planner (`Bot.value`, `Bot.play_value`, `Bot.plan_score`),
  `abstract_moves`, `clamp_q`, `keep_q`; `Bot(..., lookahead=True, adapt=True)` — pass `False, False` for the exact old
  bot (verified identical on 6,496 positions); `Decision` gained `eager` and `states` (both have defaults, so existing
  code keeps working). Every old public function is unchanged.
- **New:** `bot_lab.py` (3 presentation experiments), `test_bot_upgrade.py` (19 tests), `COMPLEXITY.md` regenerated (172 functions).
- `gui.py` works with the new bot as-is.

## Acknowledgement of AI assistance

The bot upgrade (look-ahead planner, circular-queue memory, lab and tests) was developed with the help of an AI assistant (Claude).
The syllabus requires AI-assisted contributions to be acknowledged: keep this section, and be ready to explain every
function in your own words during the presentation.