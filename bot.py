"""
bot.py -- the probability model and the heap-driven bot for "Liar's Cards".

THE MATH (all of it fits on one slide)
  A hand has the colours split 2:3:4 in a random order, and the target colour is random,
  so the number T of TARGET cards in any hand is 2, 3 or 4, each with probability 1/3.

  1. Can a player honestly have placed n target cards?      P(T >= n)
         n <= 2 : 100%    n = 3 : 67%    n = 4 : 33%    n >= 5 : 0%   (impossible!)
  2. So if the opponent has placed n cards this round, at least one of them is
     *provably* a lie with probability  F = 1 - P(T >= n)   ("forced lie").
  3. Otherwise the opponent may still be bluffing: assume each card is a bluff with
     probability b (BLUFF_PRIOR), so an m-card play contains a bluff with prob 1-(1-b)^m.

         P(last play is a LIE) = F + (1 - F) * (1 - (1 - b)^m)

THE BOT
  Every legal move gets an expected-value score (measured in hearts).  The scores go into a
  MAX-HEAP, the bot pops the TOP_K best moves, and picks one with soft-max probabilities.
  It usually plays the best move but not always -- a *mixed strategy*, so it cannot be read
  like a book.

Data structure used: MaxHeap (priority queue) -- see ds.py.
Complexity notation: c = candidate moves (always <= 10: 1 call + at most 9 plays),
K = TOP_K (a small constant).
"""

import math
import random
from dataclasses import dataclass

from ds import MaxHeap
from engine import Color, SPLIT, cards_to_str

BLUFF_PRIOR = 0.20      # assumed chance that any single card in an unforced play is a bluff
TOP_K = 3               # how many heap-ranked moves the bot chooses between
TEMPERATURE = 0.30      # soft-max temperature: lower = more predictable bot


# --------------------------------------------------------------------------
# Probability model (shared by the bot AND the coach shown to the human)
# --------------------------------------------------------------------------
def p_target_at_least(m):
    """P(T >= m): the chance a hand holds at least m target cards (T is 2, 3 or 4, equally likely).

    Time:  O(1)  (SPLIT has 3 entries)
    Space: O(1)
    """
    return sum(1 for t in SPLIT if t >= m) / len(SPLIT)


def odds_rows(max_cards=5):
    """Rows (m, P(T >= m)) for m = 1..max_cards, used by the coach table.

    Time:  O(max_cards)
    Space: O(max_cards)
    """
    return [(m, p_target_at_least(m)) for m in range(1, max_cards + 1)]


def p_play_is_lie(placed, last_size, bluff=BLUFF_PRIOR):
    """P(the opponent's last play is a lie) given `placed` cards in total and `last_size` in that play.

    forced = P(opponent cannot have been honest so far); otherwise it still bluffs per card.

    Time:  O(1)
    Space: O(1)
    """
    forced = 1.0 - p_target_at_least(placed)
    unforced_bluff = 1.0 - (1.0 - bluff) ** last_size
    return forced + (1.0 - forced) * unforced_bluff


def call_probability(suspicion):
    """How likely a typical opponent is to call, given how suspicious a play looks (a sigmoid).

    suspicion 0.36 -> ~25%,  0.50 -> 50%,  0.73 -> ~85%,  1.00 -> ~98%.

    Time:  O(1)
    Space: O(1)
    """
    return 1.0 / (1.0 + math.exp(-8.0 * (suspicion - 0.5)))


# --------------------------------------------------------------------------
# Candidate moves
# --------------------------------------------------------------------------
@dataclass
class Option:
    """One scored candidate move (the items stored in the heap)."""
    score: float            # expected change in (my hearts - opponent hearts)
    tie: float              # random tie-breaker so equal scores are not always ordered the same way
    label: str
    action: str             # "play" or "call"
    cards: tuple = ()


@dataclass
class Decision:
    """What the bot decided, plus the heap ranking it chose from (for the x-ray display)."""
    action: str
    cards: tuple
    ranking: list           # the TOP_K best Options, best first
    probs: list             # soft-max probability of each ranked option
    heap: list              # the heap's backing array right after heapify (for drawing the tree)
    chosen: object          # the Option that was actually picked (one of `ranking`)


def candidate_plays(counts):
    """All distinct 1- and 2-card plays the hand allows, e.g. (R,), (R,G), (B,B).

    Time:  O(1)  (at most 3 + 6 = 9 plays)
    Space: O(1)
    """
    plays = [(a,) for a in Color if counts[a] >= 1]
    for a in Color:
        for b in Color:
            if b < a:
                continue
            if (a == b and counts[a] >= 2) or (a != b and counts[a] >= 1 and counts[b] >= 1):
                plays.append((a, b))
    return plays


def score_call(obs, bluff):
    """Expected hearts gained by calling: +1 if the play was a lie, -1 if it was honest -> 2p - 1.

    Time:  O(1)
    Space: O(1)
    """
    p = p_play_is_lie(obs.opp_played, obs.last_size, bluff)
    return 2.0 * p - 1.0


def score_play(obs, cards):
    """Expected hearts for placing `cards`.

    q = chance the opponent calls (certain if it holds no cards).
    If called: +1 when honest, -1 when lying.  If not called the game goes on and we get a small
    bonus for keeping target cards (honest ammunition for later) and a penalty for emptying our hand
    (then WE are forced to call).

    Time:  O(1)
    Space: O(1)
    """
    target = obs.target
    honest = all(card == target for card in cards)
    after = obs.my_played + len(cards)
    if obs.opp_left == 0:
        q = 1.0
    else:
        q = call_probability(p_play_is_lie(after, len(cards)))
    left = obs.my_left - len(cards)
    target_left = obs.my_counts[target] - sum(1 for card in cards if card == target)
    if left == 0:
        cont = -0.30
    else:
        cont = 0.10 * min(target_left, 2)
    return q * (1.0 if honest else -1.0) + (1.0 - q) * cont


def softmax(scores, temperature):
    """Turn scores into probabilities that sum to 1 (higher score -> higher probability).

    Time:  O(K)
    Space: O(K)
    """
    top = max(scores)
    weights = [math.exp((s - top) / temperature) for s in scores]
    total = sum(weights)
    return [w / total for w in weights]


# --------------------------------------------------------------------------
# The bot
# --------------------------------------------------------------------------
class Bot:
    """Scores every legal move, ranks them with a max-heap, then picks among the best few."""

    def __init__(self, seed=None, bluff=BLUFF_PRIOR, top_k=TOP_K, temperature=TEMPERATURE):
        """Create a bot with its own random generator (seed it for reproducible demos).

        Time:  O(1)
        Space: O(1)
        """
        self.rng = random.Random(seed)
        self.bluff = bluff
        self.top_k = top_k
        self.temperature = temperature

    def options(self, obs):
        """Score every legal move (the 'call' option plus every distinct play).

        Time:  O(c)
        Space: O(c)
        """
        opts = []
        if not obs.table_empty:
            opts.append(Option(score_call(obs, self.bluff), self.rng.random(), "CALL LIE", "call"))
        if not obs.must_call:
            for cards in candidate_plays(obs.my_counts):
                honest = all(card == obs.target for card in cards)
                label = "play %s (%s)" % (cards_to_str(cards), "honest" if honest else "bluff")
                opts.append(Option(score_play(obs, cards), self.rng.random(), label, "play", cards))
        return opts

    def decide(self, obs):
        """Pick a move: heapify the scored options, pop the K best, sample one by soft-max.

        Time:  O(c + K log c)   (heapify is O(c), snapshot is O(c), each of the K pops is O(log c))
        Space: O(c)
        """
        if obs.must_call:
            forced = Option(0.0, 0.0, "CALL LIE (forced)", "call")
            return Decision("call", (), [forced], [1.0], [forced], forced)
        heap = MaxHeap(key=lambda o: (o.score, o.tie))
        heap.heapify(self.options(obs))
        snapshot = heap.to_list()               # keep the tree shape for the x-ray display
        ranking = [heap.pop() for _ in range(min(self.top_k, len(heap)))]
        probs = softmax([o.score for o in ranking], self.temperature)
        roll, acc, chosen = self.rng.random(), 0.0, ranking[-1]
        for opt, p in zip(ranking, probs):
            acc += p
            if roll < acc:
                chosen = opt
                break
        return Decision(chosen.action, chosen.cards, ranking, probs, snapshot, chosen)
