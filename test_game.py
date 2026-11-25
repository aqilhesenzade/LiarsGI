"""
test_game.py -- run with:   python -m unittest -v test_game

Covers the data structures, the rules engine, the probability model, the bot,
a headless run of the pygame GUI, and an audit that EVERY function documents its Time/Space complexity.
"""

import ast
import os
import random
import unittest
from pathlib import Path

from bot import Bot, odds_rows, p_play_is_lie, p_target_at_least, candidate_plays, softmax
from ds import LinkedList, MaxHeap, Stack
from engine import Color, Game, Play, cards_to_str, HAND_SIZE

HERE = Path(__file__).parent


class TestLinkedList(unittest.TestCase):
    def test_insert_sorted_keeps_order_and_size(self):
        ll = LinkedList()
        for v in [3, 1, 2, 2, 0, 5]:
            ll.insert_sorted(v)
        self.assertEqual(ll.to_list(), [0, 1, 2, 2, 3, 5])
        self.assertEqual(len(ll), 6)

    def test_remove_first_head_middle_tail_missing(self):
        ll = LinkedList()
        for v in [1, 2, 3, 4]:
            ll.insert_sorted(v)
        self.assertTrue(ll.remove_first(1))      # head
        self.assertTrue(ll.remove_first(3))      # middle
        self.assertTrue(ll.remove_first(4))      # tail
        self.assertFalse(ll.remove_first(9))     # missing
        self.assertEqual(ll.to_list(), [2])
        self.assertEqual(len(ll), 1)

    def test_remove_only_first_duplicate(self):
        ll = LinkedList()
        for v in [2, 2, 2]:
            ll.insert_sorted(v)
        ll.remove_first(2)
        self.assertEqual(ll.to_list(), [2, 2])

    def test_empty_and_clear(self):
        ll = LinkedList()
        self.assertTrue(ll.is_empty())
        ll.insert_sorted(1)
        ll.clear()
        self.assertTrue(ll.is_empty())
        self.assertEqual(len(ll), 0)


class TestStack(unittest.TestCase):
    def test_lifo(self):
        s = Stack()
        for i in range(5):
            s.push(i)
        self.assertEqual(s.peek(), 4)
        self.assertEqual([s.pop() for _ in range(5)], [4, 3, 2, 1, 0])
        self.assertTrue(s.is_empty())

    def test_empty_errors(self):
        s = Stack()
        with self.assertRaises(IndexError):
            s.pop()
        with self.assertRaises(IndexError):
            s.peek()


class TestMaxHeap(unittest.TestCase):
    def test_heapify_drain_is_descending_sort(self):
        rng = random.Random(1)
        for _ in range(50):
            data = [rng.randint(-20, 20) for _ in range(rng.randint(0, 25))]
            h = MaxHeap()
            h.heapify(data)
            self.assertEqual(h.drain(), sorted(data, reverse=True))

    def test_push_pop_matches_sorted(self):
        rng = random.Random(2)
        data = [rng.random() for _ in range(200)]
        h = MaxHeap()
        for x in data:
            h.push(x)
        self.assertEqual(h.peek(), max(data))
        self.assertEqual([h.pop() for _ in range(len(data))], sorted(data, reverse=True))

    def test_custom_key(self):
        h = MaxHeap(key=lambda t: t[0])
        h.heapify([(1, "a"), (9, "z"), (5, "m")])
        self.assertEqual(h.pop()[1], "z")

    def test_empty_errors(self):
        h = MaxHeap()
        with self.assertRaises(IndexError):
            h.pop()
        with self.assertRaises(IndexError):
            h.peek()

    def test_to_list_is_a_heap_ordered_copy(self):
        h = MaxHeap()
        h.heapify([3, 9, 1, 7, 5, 8])
        arr = h.to_list()
        self.assertEqual(arr[0], 9)
        for i in range(1, len(arr)):
            self.assertGreaterEqual(arr[(i - 1) // 2], arr[i])     # parent >= child
        arr.append(100)                                            # a copy: the heap is untouched
        self.assertEqual(len(h), 6)


class TestEngine(unittest.TestCase):
    def test_deal_is_9_cards_with_2_3_4_split(self):
        for seed in range(100):
            g = Game(seed=seed)
            for p in g.players:
                self.assertEqual(len(p.hand), HAND_SIZE)
                self.assertEqual(sorted(p.counts()), [2, 3, 4])
                hand = p.hand.to_list()
                self.assertEqual(hand, sorted(hand))      # sorted by colour

    def test_all_colours_get_each_count_over_many_deals(self):
        seen = set()
        for seed in range(200):
            seen.add(tuple(Game(seed=seed).players[0].counts()))
        self.assertEqual(len(seen), 6)                    # all 3! permutations of (2,3,4)

    def test_same_seed_same_game(self):
        a, b = Game(seed=5), Game(seed=5)
        self.assertEqual(a.target, b.target)
        self.assertEqual(a.players[0].hand.to_list(), b.players[0].hand.to_list())

    def test_play_removes_cards_and_switches_turn(self):
        g = Game(seed=1)
        card = g.players[0].hand.to_list()[0]
        g.play((card,))
        self.assertEqual(len(g.players[0].hand), 8)
        self.assertEqual(g.players[0].played, 1)
        self.assertEqual(g.current_index, 1)
        self.assertEqual(len(g.table), 1)

    def test_illegal_plays(self):
        g = Game(seed=1)
        with self.assertRaises(ValueError):
            g.play(())                                    # zero cards
        with self.assertRaises(ValueError):
            g.play((Color.RED, Color.RED, Color.RED))     # three cards
        with self.assertRaises(ValueError):
            g.call()                                      # nothing to call yet
        g.players[0].hand.clear()
        g.players[0].hand.insert_sorted(Color.RED)
        with self.assertRaises(ValueError):
            g.play((Color.GREEN,))                        # card not in hand
        with self.assertRaises(ValueError):
            g.play((Color.RED, Color.RED))                # only one red held

    def test_call_on_lie_punishes_liar(self):
        g = Game(seed=3)
        liar_card = next(c for c in Color if c != g.target and g.players[0].counts()[c] > 0)
        g.play((liar_card,))
        result = g.call()
        self.assertTrue(result.was_lie)
        self.assertEqual(result.loser, 0)
        self.assertEqual(g.players[0].hp, g.hp_max - 1)
        self.assertTrue(g.round_over)

    def test_call_on_truth_punishes_caller(self):
        g = Game(seed=3)
        g.players[0].hand.clear()
        for _ in range(3):
            g.players[0].hand.insert_sorted(g.target)
        g.play((g.target,))
        result = g.call()
        self.assertFalse(result.was_lie)
        self.assertEqual(result.loser, 1)
        self.assertEqual(g.players[1].hp, g.hp_max - 1)

    def test_game_over_and_winner(self):
        g = Game(seed=2, hp_max=1)
        card = next(c for c in Color if c != g.target and g.players[0].counts()[c] > 0)
        g.play((card,))
        g.call()
        self.assertTrue(g.game_over)
        self.assertEqual(g.winner, 1)

    def test_forced_call_when_hand_empty(self):
        g = Game(seed=4)
        g.players[1].hand.clear()
        g.play((g.players[0].hand.to_list()[0],))
        self.assertTrue(g.must_call(1))
        with self.assertRaises(ValueError):
            g.play((Color.RED,))
        g.call()                                          # allowed

    def test_next_round_resets_and_alternates_opener(self):
        g = Game(seed=6, first=0)
        self.assertEqual(g.current_index, 0)
        g.play((g.players[0].hand.to_list()[0],))
        g.call()
        g.next_round()
        self.assertEqual(g.round_no, 2)
        self.assertTrue(g.table.is_empty())
        self.assertEqual(g.current_index, 1)
        self.assertEqual(len(g.players[0].hand), HAND_SIZE)
        self.assertEqual(g.players[0].played, 0)

    def test_play_is_lie(self):
        self.assertFalse(Play(0, (Color.RED, Color.RED)).is_lie(Color.RED))
        self.assertTrue(Play(0, (Color.RED, Color.BLUE)).is_lie(Color.RED))

    def test_cards_to_str(self):
        self.assertEqual(cards_to_str((Color.RED, Color.BLUE)), "R B")


class TestProbability(unittest.TestCase):
    def test_honest_capacity_table(self):
        self.assertEqual([round(p, 4) for _, p in odds_rows()], [1.0, 1.0, 0.6667, 0.3333, 0.0])
        self.assertAlmostEqual(p_target_at_least(3), 2 / 3)

    def test_over_four_cards_is_certainly_a_lie(self):
        self.assertEqual(p_play_is_lie(5, 1), 1.0)
        self.assertEqual(p_play_is_lie(6, 2), 1.0)

    def test_lie_probability_grows_with_cards_placed(self):
        vals = [p_play_is_lie(n, 1) for n in range(1, 6)]
        self.assertEqual(vals, sorted(vals))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in vals))

    def test_two_card_play_is_more_suspicious_than_one(self):
        self.assertGreater(p_play_is_lie(2, 2), p_play_is_lie(2, 1))

    def test_softmax_sums_to_one_and_is_ordered(self):
        p = softmax([1.0, 0.5, -0.2], 0.3)
        self.assertAlmostEqual(sum(p), 1.0)
        self.assertEqual(p, sorted(p, reverse=True))

    def test_candidate_plays(self):
        self.assertEqual(len(candidate_plays([2, 3, 4])), 9)
        self.assertEqual(candidate_plays([1, 0, 0]), [(Color.RED,)])
        self.assertEqual(len(candidate_plays([0, 0, 0])), 0)


class TestBot(unittest.TestCase):
    def test_forced_call(self):
        g = Game(seed=4)
        g.players[1].hand.clear()
        g.play((g.players[0].hand.to_list()[0],))
        d = Bot(seed=1).decide(g.observe(1))
        self.assertEqual(d.action, "call")

    def test_ranking_is_best_first_and_probs_sum_to_one(self):
        g = Game(seed=9)
        d = Bot(seed=1).decide(g.observe(0))
        scores = [o.score for o in d.ranking]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertAlmostEqual(sum(d.probs), 1.0)

    def test_decision_carries_heap_and_chosen_for_the_gui(self):
        # Regression: gui.py draws d.heap and d.chosen; they used to be missing (AttributeError).
        g = Game(seed=9)
        d = Bot(seed=1).decide(g.observe(0))
        self.assertGreaterEqual(len(d.heap), len(d.ranking))
        self.assertIn(d.chosen, d.ranking)
        self.assertEqual(d.chosen.action, d.action)
        self.assertEqual(d.heap[0], d.ranking[0])                  # the root of the heap is the best move
        g2 = Game(seed=4)
        g2.players[1].hand.clear()
        g2.play((g2.players[0].hand.to_list()[0],))
        forced = Bot(seed=1).decide(g2.observe(1))
        self.assertIs(forced.chosen, forced.ranking[0])
        self.assertEqual(len(forced.heap), 1)

    def test_bot_never_makes_an_illegal_move_over_many_games(self):
        for seed in range(300):
            g = Game(names=("A", "B"), seed=seed, first=seed % 2)
            bots = [Bot(seed), Bot(seed + 1)]
            turns = 0
            while not g.game_over:
                while not g.round_over:
                    idx = g.current_index
                    d = bots[idx].decide(g.observe(idx))
                    if d.action == "call":
                        g.call()
                    else:
                        g.play(d.cards)                   # raises ValueError if illegal
                    turns += 1
                    self.assertLess(turns, 500)
                if not g.game_over:
                    g.next_round()
            self.assertIn(g.winner, (0, 1))

    def test_bot_calls_when_play_is_certainly_a_lie(self):
        g = Game(seed=1)
        # opponent (player 0) piles up 5 cards; the 5th makes an honest history impossible
        for i in range(5):
            card = g.players[0].hand.to_list()[0]
            g.play((card,))
            if i < 4:
                g.play((g.players[1].hand.to_list()[0],))
        obs = g.observe(1)
        self.assertEqual(obs.opp_played, 5)
        calls = sum(Bot(seed=s).decide(obs).action == "call" for s in range(200))
        self.assertGreater(calls, 100)                    # best option by far


class TestGUI(unittest.TestCase):
    """Headless smoke test of the pygame front-end (skipped when pygame is not installed)."""

    def test_gui_runs_headless_in_every_mode_and_the_bot_never_acts_on_your_turn(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        try:
            import pygame
            import gui
        except ImportError:
            self.skipTest("pygame is not installed")
        pygame.init()
        screen = pygame.display.set_mode((gui.W, gui.H))
        gui.make_fonts()
        for spectator in (False, True):
            app = gui.App(spectator=spectator, hp=2, seed=3, speed=0.05, now=0.0)
            now = 0.0
            for _ in range(8000):
                now += 1 / 60
                g = app.game
                if app.state == "human":
                    self.assertEqual(g.current_index, 0)               # only YOU act in this state
                    if g.must_call(0):
                        app.human_call(now)
                    else:
                        app.selected = [0]
                        app.human_play(now)
                elif app.state == "bot_wait":
                    self.assertFalse(app.humans[g.current_index])      # the bot waits for ITS turn only
                if app.state == "over":
                    break
                app.update(now)
                app.draw(screen, now)
            self.assertEqual(app.state, "over", "spectator=%s" % spectator)
        pygame.quit()

    def test_the_first_round_intro_is_not_skipped(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        try:
            import gui
        except ImportError:
            self.skipTest("pygame is not installed")
        app = gui.App(seed=1, now=100.0)
        app.update(100.2)                                  # 0.2 s later: still showing the round intro
        self.assertEqual(app.state, "intro")

    def test_deal_and_target_selection_animations_land_on_the_real_values(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        try:
            import gui
        except ImportError:
            self.skipTest("pygame is not installed")
        app = gui.App(seed=3, now=0.0)
        self.assertEqual(app.visible_count(0, 0.0), 0)     # nothing dealt before the animation starts
        deal_end = max(f.t0 + f.dur for f in app.deal_events)
        self.assertEqual(app.visible_count(0, deal_end), len(app.game.players[0].hand))
        self.assertEqual(app.visible_count(1, deal_end), len(app.game.players[1].hand))
        lock = app.dur(app.TARGET_START + app.TARGET_SPIN)
        self.assertEqual(app.target_index(lock), app.game.target)   # the spin ends on the real target
        self.assertTrue(app.target_known(lock))

    def test_losing_a_heart_starts_its_animation(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        try:
            import gui
        except ImportError:
            self.skipTest("pygame is not installed")
        app = gui.App(seed=1, hp=3, now=0.0)
        app.game.players[1].hp = 2
        app.hp_synced = False
        app.sync_hearts(0.5)
        self.assertIn((1, 2), app.heart_anims)             # the third heart slot is breaking
        self.assertEqual(app.shown_hp, [3, 2])


class TestComplexityDocs(unittest.TestCase):
    """The course requires time AND space complexity for every function."""

    def test_every_function_documents_time_and_space(self):
        missing = []
        for name in ("ds.py", "engine.py", "bot.py", "bot_lab.py", "gui.py"):
            tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node) or ""
                    if "Time:" not in doc or "Space:" not in doc:
                        missing.append("%s:%s" % (name, node.name))
        self.assertEqual(missing, [], "functions without Time:/Space: lines in the docstring")


if __name__ == "__main__":
    unittest.main()
