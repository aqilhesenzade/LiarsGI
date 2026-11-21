"""
engine.py -- the rules of "Liar's Cards".  Pure game logic: no printing, no input().

RULES
  * Two players, 3 hearts (HP) each.
  * Every round: a random TARGET colour is announced and each player is dealt 9 cards,
    split 2 : 3 : 4 between R / G / B (which colour gets which number is random).
  * Players alternate.  On your turn you either
        - PLAY 1 or 2 cards face-down on the pile, claiming "these are all the target colour"
          (there is no pass), or
        - CALL LIE on the opponent's previous play (not allowed for the very first play).
  * A call pops the top of the pile (a stack) and reveals it:
        - it contained a non-target card -> the liar loses 1 heart,
        - it was honest                  -> the caller loses 1 heart.
  * A player with no cards left MUST call.  The round ends on every call; 0 hearts = game over.

Data structures used: LinkedList (hand), Stack (table pile) -- see ds.py.
Complexity notation: h = cards in a hand (<= 9), k = cards in a play (<= 2).
"""

import random
from dataclasses import dataclass
from enum import IntEnum

from ds import LinkedList, Stack


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
class Color(IntEnum):
    """The three card colours (their integer values double as array indexes)."""
    RED = 0
    GREEN = 1
    BLUE = 2


COLOR_NAMES = {Color.RED: "RED", Color.GREEN: "GREEN", Color.BLUE: "BLUE"}
COLOR_LETTERS = {Color.RED: "R", Color.GREEN: "G", Color.BLUE: "B"}

HAND_SIZE = 9            # cards dealt to each player every round
SPLIT = (2, 3, 4)        # per-colour counts; they add up to HAND_SIZE
MAX_PLAY = 2             # at most 2 cards per play
HP_DEFAULT = 3


def cards_to_str(cards):
    """Letters of the cards, e.g. (RED, BLUE) -> 'R B'.

    Time:  O(k)
    Space: O(k)
    """
    return " ".join(COLOR_LETTERS[c] for c in cards)


# --------------------------------------------------------------------------
# Small value objects
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Play:
    """What one player put face-down on the pile in a single turn."""
    player: int
    cards: tuple

    def is_lie(self, target):
        """True if at least one card differs from the claimed target colour.

        Time:  O(k)
        Space: O(1)
        """
        return any(card != target for card in self.cards)


@dataclass(frozen=True)
class CallResult:
    """The outcome of a 'LIE!' call (also stored in Game.history)."""
    caller: int
    accused: int
    play: Play
    was_lie: bool
    loser: int


@dataclass(frozen=True)
class Observation:
    """Everything a bot is allowed to know on its turn (no peeking at the other hand)."""
    target: Color
    my_counts: tuple        # (red, green, blue) cards in my hand
    my_left: int            # cards still in my hand
    my_played: int          # cards I have already placed this round
    opp_played: int         # cards the opponent has placed this round
    opp_left: int           # cards the opponent still holds
    last_size: int          # size of the top play on the pile (0 if the pile is empty)
    table_empty: bool
    must_call: bool         # True if I hold no cards and therefore have to call
    my_hp: int
    opp_hp: int


class Player:
    """One participant: a name, hit points, a hand (linked list) and a counter of placed cards."""

    def __init__(self, name, hp):
        """Create a player with an empty hand.

        Time:  O(1)
        Space: O(1)
        """
        self.name = name
        self.hp = hp
        self.hand = LinkedList()
        self.played = 0          # cards placed on the pile this round

    def counts(self):
        """[red, green, blue] card counts, found by walking the hand once.

        Time:  O(h)
        Space: O(1)
        """
        c = [0, 0, 0]
        for card in self.hand:
            c[card] += 1
        return c


# --------------------------------------------------------------------------
# The game
# --------------------------------------------------------------------------
class Game:
    """Holds the whole match state and enforces the rules."""

    def __init__(self, names=("You", "Bot"), hp_max=HP_DEFAULT, seed=None, first=0):
        """Set up a match and start round 1.  `seed` makes the shuffle reproducible.

        Time:  O(h^2)  (dealing, see _deal_hand)
        Space: O(h)
        """
        self.rng = random.Random(seed)
        self.hp_max = hp_max
        self.players = [Player(n, hp_max) for n in names]
        self.table = Stack()               # the pile of face-down plays
        self.history = []                  # one CallResult per finished round
        self.first = first                 # who opens round 1 (then it alternates)
        self.round_no = 0
        self.target = None
        self.current_index = first
        self.round_over = False
        self.game_over = False
        self.winner = None
        self.next_round()

    # ---- dealing ----------------------------------------------------------
    def _deal_hand(self, player):
        """Deal 9 cards: colour counts are a random permutation of (2,3,4); cards arrive in random order.

        Each card is insert_sorted into the linked list, so the hand ends up sorted by colour.

        Time:  O(h^2)  (h insertions, each walking up to h nodes; h is at most 9)
        Space: O(h)
        """
        sizes = list(SPLIT)
        self.rng.shuffle(sizes)
        deck = []
        for color, n in zip(Color, sizes):
            deck.extend([color] * n)
        self.rng.shuffle(deck)
        player.hand.clear()
        for card in deck:
            player.hand.insert_sorted(card)
        player.played = 0

    def next_round(self):
        """Start a new round: new target colour, fresh hands, empty pile, opener alternates.

        Time:  O(h^2)
        Space: O(h)
        """
        self.round_no += 1
        self.target = self.rng.choice(list(Color))
        for player in self.players:
            self._deal_hand(player)
        self.table.clear()
        self.round_over = False
        self.current_index = (self.first + self.round_no - 1) % len(self.players)

    # ---- queries ----------------------------------------------------------
    def must_call(self, idx):
        """True if player idx has no cards left and the pile is not empty (so a call is forced).

        Time:  O(1)
        Space: O(1)
        """
        return len(self.players[idx].hand) == 0 and not self.table.is_empty()

    def observe(self, idx):
        """Build the Observation that bot `idx` is allowed to see.

        Time:  O(h)  (counting the hand)
        Space: O(1)
        """
        me, opp = self.players[idx], self.players[1 - idx]
        return Observation(
            target=self.target,
            my_counts=tuple(me.counts()),
            my_left=len(me.hand),
            my_played=me.played,
            opp_played=opp.played,
            opp_left=len(opp.hand),
            last_size=0 if self.table.is_empty() else len(self.table.peek().cards),
            table_empty=self.table.is_empty(),
            must_call=self.must_call(idx),
            my_hp=me.hp,
            opp_hp=opp.hp,
        )

    # ---- actions ----------------------------------------------------------
    def play(self, cards):
        """Current player places 1-2 cards face-down on the pile (a stack push).

        Raises ValueError for any illegal move (wrong size, cards not owned, forced call...).

        Time:  O(h)  (checking ownership + removing from the linked list)
        Space: O(k)
        """
        if self.round_over or self.game_over:
            raise ValueError("the round is over")
        idx = self.current_index
        if self.must_call(idx):
            raise ValueError("no cards left: you must call LIE")
        cards = tuple(Color(c) for c in cards)
        if not 1 <= len(cards) <= MAX_PLAY:
            raise ValueError("a play is 1 or 2 cards")
        player = self.players[idx]
        have = player.counts()
        for color in Color:
            if cards.count(color) > have[color]:
                raise ValueError("you do not hold those cards")
        for card in cards:
            player.hand.remove_first(card)
        player.played += len(cards)
        play = Play(idx, cards)
        self.table.push(play)
        self.current_index = 1 - idx
        return play

    def call(self):
        """Current player calls LIE: pop the top play, reveal it, and take a heart from the loser.

        Time:  O(k)
        Space: O(1)
        """
        if self.round_over or self.game_over:
            raise ValueError("the round is over")
        if self.table.is_empty():
            raise ValueError("nothing to call yet")
        caller = self.current_index
        play = self.table.pop()
        was_lie = play.is_lie(self.target)
        loser = play.player if was_lie else caller
        self.players[loser].hp -= 1
        result = CallResult(caller, play.player, play, was_lie, loser)
        self.history.append(result)
        self.round_over = True
        if self.players[loser].hp <= 0:
            self.game_over = True
            self.winner = 1 - loser
        return result
