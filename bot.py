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

TWO UPGRADES OVER THE "CLASSIC" BOT  (both can be switched off to compare)
  A. LOOK-AHEAD  (recursion + memoization, syllabus weeks 1 and 6).
     Classic scoring only looked one move deep and used a hand-tuned bonus for "the game goes on".
     That made it burn its honest target cards early and get stuck later.  Now the value of
     "the game goes on" is computed for real:
         V(state) = best of  CALL  or  any PLAY,   where a PLAY leads (if not called) to the
                    opponent's reply and then V(next state)  -- a recursive formula.
     A state is only (target cards left t, other cards left o, opp cards placed, last play size),
     so there are at most ~1300 different states and each is computed ONCE (memo dictionary).
     Without the memo the same recursion would be exponential; with it, it is O(h^3).
  B. OPPONENT MEMORY  (circular queue, syllabus weeks 2 and 4).
     Each time the bot plays it predicts "the opponent will call with probability q".  Next turn it
     sees what really happened and pushes (q, called?) into a fixed-size CircularQueue (the last
     WINDOW events).  If you call more often than predicted the bot raises q; if you never call it
     lowers q.  So the bot adapts to the person sitting in front of it.

Data structures used: MaxHeap (priority queue) and CircularQueue (sliding window) -- see ds.py.
Complexity notation: c = candidate moves (always <= 10: 1 call + at most 9 plays),
K = TOP_K (a small constant), h = cards in a hand (<= 9), S = distinct look-ahead states (O(h^3)),
W = WINDOW (memory size, a small constant).
"""

import math
import random
from dataclasses import dataclass

from ds import CircularQueue, MaxHeap
from engine import HAND_SIZE, Color, SPLIT, cards_to_str

BLUFF_PRIOR = 0.20      # assumed chance that any single card in an unforced play is a bluff
TOP_K = 3               # how many heap-ranked moves the bot chooses between
TEMPERATURE = 0.30      # soft-max temperature: lower = more predictable bot
WINDOW = 8              # how many of the opponent's recent reactions the bot remembers (queue size)
PRIOR_WEIGHT = 2.0      # "pretend I already saw this many opponents who match my model" -> calm start
OPP_TWO_CARD = 0.25     # look-ahead assumption: chance that the opponent's next play has 2 cards
Q_MIN, Q_MAX = 0.10, 0.98          # a (learned) call probability stays inside this range: nobody is 100% predictable


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
    eager: float = 0.5      # learned chance that this opponent calls a coin-flip-looking play (0.5 = no data yet)
    states: int = 0         # number of distinct look-ahead states the memo dictionary computed


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
# Upgrade A: look-ahead helpers (recursion + memoization)
# --------------------------------------------------------------------------
def abstract_moves(t, o):
    """Distinct plays as (cards, honest cards) pairs, given t target cards and o other cards in hand.

    Colours do not matter for the look-ahead -- only "how many of the cards I put down are target".
    (1,1) = one honest card, (2,1) = one honest + one lie card, (2,0) = two lie cards, and so on.

    Time:  O(1)  (at most 5 moves)
    Space: O(1)
    """
    moves = []
    if t >= 1:
        moves.append((1, 1))
    if o >= 1:
        moves.append((1, 0))
    if t >= 2:
        moves.append((2, 2))
    if t >= 1 and o >= 1:
        moves.append((2, 1))
    if o >= 2:
        moves.append((2, 0))
    return moves


def clamp_q(q):
    """Keep a call probability strictly inside (0, 1) so no future ever looks 100% certain.

    Time:  O(1)
    Space: O(1)
    """
    return min(Q_MAX, max(Q_MIN, q))


def keep_q(q):
    """Identity: used instead of the learned correction when adaptation is switched off.

    Time:  O(1)
    Space: O(1)
    """
    return q


# --------------------------------------------------------------------------
# Upgrade B: the opponent memory (circular queue)
# --------------------------------------------------------------------------
class OpponentMemory:
    """Sliding window of "what I predicted vs what the opponent did" -- a CircularQueue of the last W events.

    Running totals are updated in O(1) as items enter and leave the window, so asking for the
    current estimate never needs a walk over the queue.
    """

    def __init__(self, window=WINDOW, prior=PRIOR_WEIGHT):
        """Create an empty memory holding at most `window` events.

        Time:  O(W)  (allocates the ring buffer)
        Space: O(W)
        """
        self.events = CircularQueue(window)
        self.prior = prior
        self.sum_predicted = 0.0        # total of the predicted call chances inside the window
        self.sum_called = 0             # how many times the opponent really called inside the window

    def record(self, predicted, called):
        """Remember one event; if the window is full the OLDEST event is dequeued first.

        Time:  O(1)
        Space: O(1)
        """
        if self.events.is_full():
            old_pred, old_called = self.events.dequeue()
            self.sum_predicted = max(0.0, self.sum_predicted - old_pred)
            self.sum_called -= old_called
        flag = 1 if called else 0
        self.events.enqueue((predicted, flag))
        self.sum_predicted += predicted
        self.sum_called += flag

    def adjust(self, q):
        """Correct the model's call probability `q` with what this opponent has really done.

        Let n = events in the window, P = calls my model predicted, C = calls that really happened.
          * C >= P  (calls MORE than I thought): shrink the chance of "no call":
                    1 - q' = (1 - q) * (n - C + prior) / (n - P + prior)
          * C <  P  (calls LESS than I thought): shrink the chance of a call:
                    q' = q * (C + prior) / (P + prior)
        With no data both factors are 1 (q is unchanged); an opponent who always / never calls
        pushes q' towards 1 / 0 -- something a single multiplier could never do for a small q.

        Time:  O(1)
        Space: O(1)
        """
        n = len(self.events)
        if self.sum_called >= self.sum_predicted:
            keep = (n - self.sum_called + self.prior) / (n - self.sum_predicted + self.prior)
            return clamp_q(1.0 - (1.0 - q) * keep)
        return clamp_q(q * (self.sum_called + self.prior) / (self.sum_predicted + self.prior))

    def eager(self):
        """How likely this opponent is to call a play my model rates as a coin flip (0.50 = like my model).

        Time:  O(1)
        Space: O(1)
        """
        return self.adjust(0.5)

    def text(self):
        """One-line description for the x-ray panel, e.g. 'o o X o  (called 1/4, I expected 1.1) -> ...'.

        Time:  O(W)
        Space: O(W)
        """
        items = self.events.to_list()
        if not items:
            return "no data yet -> coin-flip play gets called 50%"
        marks = " ".join("X" if called else "o" for _, called in items)
        return "%s  (called %d/%d, I expected %.1f)  -> coin-flip play gets called %d%%" % (
            marks, self.sum_called, len(items), self.sum_predicted, round(100 * self.eager()))


# --------------------------------------------------------------------------
# The bot
# --------------------------------------------------------------------------
class Bot:
    """Scores every legal move, ranks them with a max-heap, then picks among the best few.

    lookahead=True  -> moves are scored by the recursive, memoized planner (Upgrade A)
    lookahead=False -> the original one-move-deep scoring with hand-tuned bonuses ("classic")
    adapt=True      -> the call-eagerness learned in the circular-queue memory is used (Upgrade B)
    """

    def __init__(self, seed=None, bluff=BLUFF_PRIOR, top_k=TOP_K, temperature=TEMPERATURE,
                 lookahead=True, adapt=True):
        """Create a bot with its own random generator (seed it for reproducible demos).

        Time:  O(W)  (the memory's ring buffer)
        Space: O(W)
        """
        self.rng = random.Random(seed)
        self.bluff = bluff
        self.top_k = top_k
        self.temperature = temperature
        self.lookahead = lookahead
        self.adapt = adapt
        self.memory = OpponentMemory()
        self.pending = None         # the call chance I predicted for my last play (None = nothing to check)
        self.last_states = 0        # size of the memo dictionary of the latest look-ahead (for the x-ray)

    # ---- Upgrade B: learning from what the opponent really did ------------------------
    def adjuster(self):
        """The function that turns the model's call probability into the learned one (identity if adapt=False).

        Time:  O(1)
        Space: O(1)
        """
        return self.memory.adjust if self.adapt else keep_q

    def eager(self):
        """The learned coin-flip call chance, for the x-ray display (0.5 if adaptation is off).

        Time:  O(1)
        Space: O(1)
        """
        return self.memory.eager() if self.adapt else 0.5

    def settle(self, obs):
        """At the start of my turn: did the opponent CALL my last play (new round) or just play on?

        If my last play is still in a running round, I have cards on the pile (`my_played > 0`);
        a fresh round always starts with `my_played == 0`.  The (prediction, outcome) pair goes
        into the circular-queue memory.

        Time:  O(1)
        Space: O(1)
        """
        if self.pending is None:
            return
        if self.adapt:
            self.memory.record(self.pending, obs.my_played == 0)
        self.pending = None

    def remember(self, obs, chosen):
        """After choosing: if I PLAYED against an opponent who can choose, store my prediction to check later.

        Time:  O(1)
        Space: O(1)
        """
        if chosen.action == "play" and obs.opp_left > 0:
            after = obs.my_played + len(chosen.cards)
            self.pending = call_probability(p_play_is_lie(after, len(chosen.cards)))
        else:
            self.pending = None

    # ---- Upgrade A: the recursive, memoized planner ----------------------------------------
    def play_value(self, t, o, opp_placed, m, h, adj, memo):
        """Expected hearts for putting down m cards (h of them target) with t target + o other cards in hand.

        q = chance the opponent calls (certain if it holds no cards).  Called: +1 if my play was honest, -1 if not.
        Not called: the opponent plays 1 card (or 2 with chance OPP_TWO_CARD) and I move again, worth
        value(...) of that new state -- this is the recursion.  `adj` is the learned call-probability correction.

        Time:  O(1) own work, plus the memoized calls to value()
        Space: O(1) own work (the recursion is at most h levels deep)
        """
        called = 1.0 if h == m else -1.0
        opp_left = HAND_SIZE - opp_placed
        if opp_left <= 0:
            return called                                   # the opponent has no cards: it MUST call
        t2, o2 = t - h, o - (m - h)
        my_placed = HAND_SIZE - (t2 + o2)
        q = clamp_q(adj(call_probability(p_play_is_lie(my_placed, m))))
        if opp_left >= 2:
            replies = ((1, 1.0 - OPP_TWO_CARD), (2, OPP_TWO_CARD))
        else:
            replies = ((1, 1.0),)
        later = 0.0
        for size, weight in replies:
            later += weight * self.value(t2, o2, opp_placed + size, size, adj, memo)
        return q * called + (1.0 - q) * later

    def value(self, t, o, opp_placed, last_size, adj, memo):
        """Best expected hearts when it is MY move: max( CALL , every possible PLAY ).  Memoized.

        The state is (t, o, opp_placed, last_size); `memo` remembers every state already solved,
        so each of the O(h^3) states is computed once instead of once per path leading to it.
        With no cards left I am forced to call.  Without the memo the same recursion is exponential in the cards left.

        Time:  O(S) over a whole look-ahead (S = distinct states <= O(h^3), each state costs O(1) work)
        Space: O(S)  (the memo dictionary) plus O(h) recursion depth
        """
        key = (t, o, opp_placed, last_size)
        if key in memo:
            return memo[key]
        best = 2.0 * p_play_is_lie(opp_placed, last_size, self.bluff) - 1.0     # CALL
        if t + o > 0:                                                           # a play is possible
            for m, h in abstract_moves(t, o):
                best = max(best, self.play_value(t, o, opp_placed, m, h, adj, memo))
        memo[key] = best
        return best

    def plan_score(self, obs, cards, adj, memo):
        """Score one concrete play with the planner (its colours are reduced to 'how many are target').

        Time:  O(k + S) the first time (count the cards, then look ahead); later calls reuse the memo
        Space: O(S)
        """
        target_in_hand = obs.my_counts[obs.target]
        t, o = target_in_hand, obs.my_left - target_in_hand
        h = sum(1 for card in cards if card == obs.target)
        return self.play_value(t, o, obs.opp_played, len(cards), h, adj, memo)

    # ---- choosing a move -----------------------------------------------------------------
    def options(self, obs):
        """Score every legal move (the 'call' option plus every distinct play).

        Time:  O(c + S)  with the look-ahead (O(c) for the classic scoring)
        Space: O(c + S)
        """
        opts = []
        adj = self.adjuster()
        memo = {}
        if not obs.table_empty:
            opts.append(Option(score_call(obs, self.bluff), self.rng.random(), "CALL LIE", "call"))
        if not obs.must_call:
            for cards in candidate_plays(obs.my_counts):
                honest = all(card == obs.target for card in cards)
                label = "play %s (%s)" % (cards_to_str(cards), "honest" if honest else "bluff")
                if self.lookahead:
                    score = self.plan_score(obs, cards, adj, memo)
                else:
                    score = score_play(obs, cards)
                opts.append(Option(score, self.rng.random(), label, "play", cards))
        self.last_states = len(memo)
        return opts

    def decide(self, obs):
        """Pick a move: heapify the scored options, pop the K best, sample one by soft-max.

        Time:  O(c + S + K log c)   (score the moves, heapify is O(c), snapshot O(c), K pops of O(log c))
        Space: O(c + S)
        """
        self.settle(obs)
        eager = self.eager()
        if obs.must_call:
            forced = Option(0.0, 0.0, "CALL LIE (forced)", "call")
            return Decision("call", (), [forced], [1.0], [forced], forced, eager, 0)
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
        self.remember(obs, chosen)
        return Decision(chosen.action, chosen.cards, ranking, probs, snapshot, chosen, eager, self.last_states)