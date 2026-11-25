"""
bot_lab.py -- three live experiments that explain the upgraded bot (made for the class presentation).

    python bot_lab.py            menu
    python bot_lab.py memo       1. recursion  vs  recursion + MEMOIZATION   (weeks 1 and 6)
    python bot_lab.py learn      2. watch the bot's circular-queue memory learn an opponent (weeks 2 and 4)
    python bot_lab.py arena      3. classic bot vs upgraded bot against 7 scripted opponent styles
    python bot_lab.py learn --style never_call --auto --seed 3

Complexity notation: M = matches played, T = turns per match, c = candidate bot moves (<= 10),
S = distinct look-ahead states (O(h^3)), K = TOP_K, W = WINDOW, h = cards in a hand (<= 9).
"""

import argparse
import random
import time

from bot import Bot, WINDOW, keep_q, p_play_is_lie, call_probability
from engine import Color, Game, cards_to_str

STYLES = {
    "never_call":  "plays honest cards first and NEVER calls (unless forced)",
    "always_call": "calls the very first chance it gets",
    "threshold":   "plays honest cards first, calls when the lie-chance is above 50%",
    "sigmoid":     "calls with the same 'typical opponent' odds the bot assumes",
    "paranoid":    "calls 55% of the time whatever it sees",
    "bluffer":     "bluffs on 40% of its plays, calls above 50%",
    "random":      "plays random cards, calls 30% of the time at random",
}


# --------------------------------------------------------------------------
# Scripted opponents (stand-ins for a human, so the experiments are repeatable)
# --------------------------------------------------------------------------
def honest_first(obs):
    """One card: a target card if the hand has one, otherwise the first colour available.

    Time:  O(1)  (3 colours)
    Space: O(1)
    """
    if obs.my_counts[obs.target] > 0:
        return (Color(obs.target),)
    for color in Color:
        if obs.my_counts[color] > 0:
            return (color,)
    return ()


def two_honest(obs):
    """Two target cards if the hand has them, otherwise a single honest-first card.

    Time:  O(1)
    Space: O(1)
    """
    if obs.my_counts[obs.target] >= 2:
        return (Color(obs.target), Color(obs.target))
    return honest_first(obs)


class Scripted:
    """An opponent that follows one of the STYLES, with its own random generator."""

    def __init__(self, style, seed=0):
        """Create the opponent.

        Time:  O(1)
        Space: O(1)
        """
        if style not in STYLES:
            raise ValueError("unknown style: %s" % style)
        self.style = style
        self.rng = random.Random(seed)

    def act(self, obs):
        """Return ('call',) or ('play', cards) for the observation `obs`.

        Time:  O(1)
        Space: O(1)
        """
        style, rng = self.style, self.rng
        if obs.must_call:
            return ("call",)
        lie_chance = p_play_is_lie(obs.opp_played, obs.last_size) if not obs.table_empty else 0.0
        if style == "always_call" and not obs.table_empty:
            return ("call",)
        if style == "threshold" and lie_chance > 0.5:
            return ("call",)
        if style == "sigmoid" and not obs.table_empty and rng.random() < call_probability(lie_chance):
            return ("call",)
        if style == "paranoid" and not obs.table_empty and rng.random() < 0.55:
            return ("call",)
        if style == "bluffer" and lie_chance > 0.5:
            return ("call",)
        if style == "random":
            if not obs.table_empty and rng.random() < 0.30:
                return ("call",)
            colors = [color for color in Color if obs.my_counts[color] > 0]
            return ("play", (rng.choice(colors),))
        if style == "bluffer" and rng.random() < 0.40:
            others = [color for color in Color if color != obs.target and obs.my_counts[color] > 0]
            if others:
                return ("play", (others[0],))
        if style == "threshold" and rng.random() < 0.30:
            return ("play", two_honest(obs))
        return ("play", honest_first(obs))


# --------------------------------------------------------------------------
# Running matches
# --------------------------------------------------------------------------
def step(game, idx, move):
    """Apply ('call',) or ('play', cards) for player idx; start the next round if the match goes on.

    Time:  O(h)   (play) or O(k) (call); a new round costs O(h^2)
    Space: O(k)
    """
    if move[0] == "call":
        game.call()
    else:
        game.play(move[1])
    if game.round_over and not game.game_over:
        game.next_round()


def play_scripted(make_bot, style, seed):
    """One full match, bot (player 1) vs a scripted opponent; True if the bot wins.

    Time:  O(T * (c + S))   (T turns, each costing one bot decision)
    Space: O(c + S)
    """
    game = Game(names=("Opponent", "Bot"), seed=seed, first=seed % 2)
    bot, opp = make_bot(seed), Scripted(style, seed * 7919 + 1)
    while not game.game_over:
        idx = game.current_index
        if idx == 1:
            decision = bot.decide(game.observe(1))
            step(game, 1, ("call",) if decision.action == "call" else ("play", decision.cards))
        else:
            step(game, 0, opp.act(game.observe(0)))
    return game.winner == 1


def play_bot_vs_bot(make_classic, make_upgraded, seed):
    """One full match, classic (player 0) vs upgraded (player 1); True if the upgraded bot wins.

    Time:  O(T * (c + S))
    Space: O(c + S)
    """
    game = Game(names=("Classic", "Upgraded"), seed=seed, first=seed % 2)
    bots = [make_classic(seed), make_upgraded(seed + 99991)]
    while not game.game_over:
        idx = game.current_index
        decision = bots[idx].decide(game.observe(idx))
        step(game, idx, ("call",) if decision.action == "call" else ("play", decision.cards))
    return game.winner == 1


def win_rate(make_bot, style, matches):
    """Fraction of `matches` matches the bot wins against a scripted style.

    Time:  O(M * T * (c + S))
    Space: O(c + S)
    """
    return sum(play_scripted(make_bot, style, s) for s in range(matches)) / matches


def make_classic(seed):
    """The original bot: one-move-deep scoring, no learning.

    Time:  O(W)
    Space: O(W)
    """
    return Bot(seed, lookahead=False, adapt=False)


def make_upgraded(seed):
    """The upgraded bot: recursive memoized look-ahead + circular-queue opponent memory.

    Time:  O(W)
    Space: O(W)
    """
    return Bot(seed)


# --------------------------------------------------------------------------
# Experiment 1: recursion vs recursion + memoization
# --------------------------------------------------------------------------
class CountingBot(Bot):
    """A Bot that counts how many times the recursive value() function is entered."""

    calls = 0

    def value(self, t, o, opp_placed, last_size, adj, memo):
        """Count the call, then do the normal memoized value().

        Time:  same as Bot.value
        Space: same as Bot.value
        """
        self.calls += 1
        return super().value(t, o, opp_placed, last_size, adj, memo)


class NoMemo(dict):
    """A memo dictionary that forgets everything -- turns the memoized recursion back into plain recursion."""

    def __contains__(self, key):
        """Never remember anything.

        Time:  O(1)
        Space: O(1)
        """
        return False

    def __setitem__(self, key, value):
        """Throw the value away.

        Time:  O(1)
        Space: O(1)
        """
        return None


def demo_memo():
    """Experiment 1: solve the same position with and without the memo dictionary and compare the work.

    Time:  O(sum of the plain recursions shown)  (the plain version is exponential -- that is the point)
    Space: O(S)
    """
    print("\n  Same position, same answer -- how much work does the recursion do?")
    print("  (opponent has placed 1 card, I must choose a move; t = my target cards, o = my other cards)\n")
    print("   cards left | plain recursion calls | WITH memo: distinct states | answer")
    for t, o in [(1, 2), (2, 2), (2, 3), (3, 3), (3, 4), (4, 4)]:
        plain, memoed = CountingBot(1), CountingBot(1)
        a = plain.value(t, o, 1, 1, keep_q, NoMemo())
        memo = {}
        b = memoed.value(t, o, 1, 1, keep_q, memo)
        assert abs(a - b) < 1e-9
        print("   %10d | %21d | %26d | %+.3f" % (t + o, plain.calls, len(memo), a))
    print("\n  Plain recursion explores every PATH (exponential in the cards left).")
    print("  The memo stores each STATE (t, o, opp_placed, last_size) the first time -> polynomial, O(h^3).")


# --------------------------------------------------------------------------
# Experiment 2: watching the bot learn
# --------------------------------------------------------------------------
def demo_learn(style, auto=False, seed=3):
    """Experiment 2: play one match bot vs a scripted style, printing the bot's queue memory after each move.

    Time:  O(T * (c + S))
    Space: O(c + S)
    """
    print("\n  Opponent style: %s -- %s" % (style, STYLES[style]))
    print("  Memory legend: o = opponent did NOT call my play, X = it called.  Window = last %d events.\n" % WINDOW)
    game = Game(names=("Opponent", "Bot"), seed=seed, first=1)
    bot, opp = Bot(seed), Scripted(style, seed)
    shown_round = 0
    while not game.game_over:
        if game.round_no != shown_round:
            shown_round = game.round_no
            if shown_round > 1 and not auto:
                input("  [Enter] next round ")
            print("  --- Round %d   target %s   hearts: Opponent %d, Bot %d ---" % (
                shown_round, game.target.name, game.players[0].hp, game.players[1].hp))
        idx = game.current_index
        if idx == 1:
            decision = bot.decide(game.observe(1))
            label = decision.chosen.label
            print("  Bot: %-24s EV %+.2f  (look-ahead solved %d states)" % (
                label, decision.chosen.score, decision.states))
            print("       memory: %s" % bot.memory.text())
            step(game, 1, ("call",) if decision.action == "call" else ("play", decision.cards))
        else:
            move = opp.act(game.observe(0))
            print("  Opponent: %s" % ("CALLS LIE!" if move[0] == "call" else "plays " + cards_to_str(move[1])))
            step(game, 0, move)
        if game.history and len(game.history) == shown_round:
            res = game.history[-1]
            print("  => %s called, the play was %s: %s loses a heart.\n" % (
                game.players[res.caller].name, "a LIE" if res.was_lie else "honest", game.players[res.loser].name))
    print("  Match over: %s wins.  Final memory: %s" % (game.players[game.winner].name, bot.memory.text()))


# --------------------------------------------------------------------------
# Experiment 3: arena
# --------------------------------------------------------------------------
def demo_arena(matches=300):
    """Experiment 3: win-rate table, classic bot vs upgraded bot, against every scripted style.

    Time:  O(7 * M * T * (c + S))  (7 styles, two bots)
    Space: O(c + S)
    """
    print("\n  Bot win-rate over %d matches per style (higher is better)\n" % matches)
    print("   %-12s %8s %9s %7s" % ("opponent", "classic", "upgraded", "gain"))
    total_a = total_b = 0.0
    for style in STYLES:
        a = win_rate(make_classic, style, matches)
        b = win_rate(make_upgraded, style, matches)
        total_a, total_b = total_a + a, total_b + b
        print("   %-12s %7.0f%% %8.0f%% %+6.0f%%" % (style, 100 * a, 100 * b, 100 * (b - a)), flush=True)
    k = len(STYLES)
    print("   %-12s %7.0f%% %8.0f%% %+6.0f%%" % ("MEAN", 100 * total_a / k, 100 * total_b / k,
                                               100 * (total_b - total_a) / k))
    wins = sum(play_bot_vs_bot(make_classic, make_upgraded, s) for s in range(matches))
    print("\n  Head to head, classic vs upgraded: the upgraded bot wins %.0f%% of %d matches." % (
        100 * wins / matches, matches))


# --------------------------------------------------------------------------
# Menu / command line
# --------------------------------------------------------------------------
def pick_style():
    """Ask the audience which opponent style to face (returns a key of STYLES).

    Time:  O(len(STYLES)) plus the human's thinking time
    Space: O(len(STYLES))
    """
    names = list(STYLES)
    for i, name in enumerate(names, 1):
        print("   %d) %-12s %s" % (i, name, STYLES[name]))
    while True:
        raw = input("  Choose 1-%d: " % len(names)).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]


def menu():
    """Text menu so the lab can be driven live in front of the class.

    Time:  O(1) per choice, plus the chosen experiment
    Space: O(1)
    """
    while True:
        print("\n  BOT LAB   1) memoization   2) watch the bot learn   3) arena   q) quit")
        choice = input("  > ").strip().lower()
        if choice == "1":
            demo_memo()
        elif choice == "2":
            demo_learn(pick_style())
        elif choice == "3":
            demo_arena()
        elif choice in ("q", "quit", "exit"):
            return


def build_parser():
    """Command-line options.

    Time:  O(1)
    Space: O(1)
    """
    ap = argparse.ArgumentParser(description="Live experiments for the upgraded Liar's Cards bot")
    ap.add_argument("experiment", nargs="?", choices=["memo", "learn", "arena"], help="skip the menu")
    ap.add_argument("--style", choices=list(STYLES), help="opponent style for 'learn' (asked if missing)")
    ap.add_argument("--matches", type=int, default=300, help="matches per style in 'arena'")
    ap.add_argument("--seed", type=int, default=3, help="seed for 'learn' (same seed = same match)")
    ap.add_argument("--auto", action="store_true", help="'learn': do not wait for Enter between rounds")
    return ap


def main():
    """Run the chosen experiment, or the menu.

    Time:  O(experiment)
    Space: O(c + S)
    """
    args = build_parser().parse_args()
    if args.experiment == "memo":
        demo_memo()
    elif args.experiment == "learn":
        demo_learn(args.style or pick_style(), args.auto, args.seed)
    elif args.experiment == "arena":
        demo_arena(args.matches)
    else:
        menu()


if __name__ == "__main__":
    main()