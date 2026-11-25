"""
test_web.py -- run with:   python -m unittest -v test_web

Tests the JSON bridge the browser uses (webapi.py).  The page itself is only a screen on top of this bridge,
so these tests cover what really matters: the browser can never move out of turn, never learns the pile's
colours before a call, and a whole match can be played through the same calls the page makes.
"""

import json
import random
import unittest

import webapi


def call(name, **args):
    """One bridge call, as the page makes it (JSON text in, JSON text out).

    Time:  O(the chosen call)
    Space: O(the chosen call)
    """
    return json.loads(webapi.dispatch(name, json.dumps(args)))


def new(**args):
    """Start a match and return its first state.

    Time:  O(h^2)
    Space: O(h)
    """
    out = call("new_match", **args)
    assert out["ok"], out
    return out["state"]


class TestBridgeBasics(unittest.TestCase):
    def test_new_match_state(self):
        s = new(hp=3, seed=1)
        self.assertEqual(s["names"], ["You", "Bot"])
        self.assertEqual(s["hp"], [3, 3])
        self.assertEqual(s["counts"], [9, 9])
        self.assertEqual(s["current"], 0)
        self.assertEqual(sorted(s["hands"][0]).count(s["target"]) in (2, 3, 4), True)
        self.assertEqual(sorted(sum(1 for c in s["hands"][0] if c == k) for k in (0, 1, 2)), [2, 3, 4])
        self.assertEqual(s["pile"], [])
        self.assertFalse(s["can_call"])

    def test_bot_hand_hidden_unless_peeking(self):
        self.assertIsNone(new(seed=2)["hands"][1])
        self.assertEqual(len(new(seed=2, peek=True)["hands"][1]), 9)
        self.assertIsNone(call("set_peek", peek=False)["state"]["hands"][1])
        self.assertEqual(len(call("set_peek", peek=True)["state"]["hands"][1]), 9)

    def test_same_seed_same_cards(self):
        self.assertEqual(new(seed=9)["hands"][0], new(seed=9)["hands"][0])

    def test_everything_is_json_text(self):
        new(seed=3)
        self.assertIsInstance(webapi.dispatch("state", "{}"), str)
        self.assertIsInstance(webapi.dispatch("nonsense", "not json at all"), str)

    def test_errors_do_not_raise(self):
        self.assertFalse(call("nonsense")["ok"])
        self.assertFalse(json.loads(webapi.dispatch("state", "{broken"))["ok"])
        self.assertFalse(call("human_play", cards="zero")["ok"])

    def test_calls_before_a_match_are_refused(self):
        webapi._session = None
        self.assertFalse(call("state")["ok"])
        self.assertFalse(call("human_play", cards=[0])["ok"])


class TestTurnOrder(unittest.TestCase):
    def test_bot_refused_on_your_turn(self):
        new(seed=4)
        self.assertFalse(call("bot_move")["ok"])

    def test_you_refused_on_bots_turn(self):
        new(seed=4, bot_first=True)
        self.assertFalse(call("human_play", cards=[0])["ok"])
        self.assertFalse(call("human_call")["ok"])

    def test_alternation_after_a_play(self):
        new(seed=5)
        self.assertTrue(call("human_play", cards=[0])["ok"])
        self.assertFalse(call("human_play", cards=[0])["ok"], "cannot play twice in a row")
        self.assertFalse(call("human_call")["ok"], "cannot call on your own play")
        bot = call("bot_move")
        self.assertTrue(bot["ok"])
        if bot["kind"] == "play":
            self.assertFalse(call("bot_move")["ok"], "bot cannot move twice in a row")
            self.assertEqual(call("state")["state"]["current"], 0)

    def test_cannot_call_an_empty_pile(self):
        new(seed=6)
        self.assertFalse(call("human_call")["ok"])

    def test_bad_card_choices_refused(self):
        s = new(seed=7)
        for bad in ([], [0, 1, 2], [0, 0], [-1], [9], [True], [1.5], ["0"]):
            self.assertFalse(call("human_play", cards=bad)["ok"], bad)
        self.assertEqual(call("state")["state"]["counts"], s["counts"], "refused moves change nothing")

    def test_next_round_only_after_a_call(self):
        new(seed=8)
        self.assertFalse(call("next_round")["ok"])


class TestSecrecy(unittest.TestCase):
    def test_pile_never_shows_colours(self):
        new(seed=10)
        call("human_play", cards=[0, 1])
        state = call("state")["state"]
        self.assertEqual(state["pile"], [{"player": 0, "size": 2}])
        self.assertNotIn("cards", json.dumps(state["pile"]))

    def test_bot_play_hides_cards_unless_peeking(self):
        new(seed=11, bot_first=True)
        self.assertNotIn("cards", call("bot_move"))
        new(seed=11, bot_first=True, peek=True)
        out = call("bot_move")
        self.assertIn("think", out)
        self.assertTrue(out["kind"] == "call" or len(out["cards"]) == out["size"])

    def test_think_hidden_unless_peeking(self):
        new(seed=12, bot_first=True)
        self.assertNotIn("think", call("bot_move"))

    def test_a_call_reveals_the_play(self):
        new(seed=13)
        call("human_play", cards=[0])
        bot = call("bot_move")
        if bot["kind"] == "play":
            res = call("human_call")["result"]
            self.assertEqual(len(res["cards"]), bot["size"])
            self.assertEqual(res["accused"], 1)
            self.assertEqual(res["was_lie"], any(c != call("state")["state"]["target"] for c in res["cards"]))
            self.assertEqual(res["loser"], 1 if res["was_lie"] else 0)


class TestWholeMatches(unittest.TestCase):
    def play_out(self, seed, **opts):
        """Play a match through the bridge with a random human; return how many rounds it took.

        Time:  O(R * T * bot move)
        Space: O(R)
        """
        rng = random.Random(seed)
        s = new(seed=seed, **opts)
        rounds, steps = 0, 0
        while not s["game_over"]:
            steps += 1
            self.assertLess(steps, 800, "match does not end")
            if s["round_over"]:
                s = call("next_round")["state"]
                continue
            if s["spectator"] or s["current"] == 1:
                out = call("bot_move")
                self.assertTrue(out["ok"], out)
            else:
                hand = s["hands"][0]
                if s["can_call"] and (s["must_call"] or rng.random() < 0.3):
                    out = call("human_call")
                else:
                    n = 1 if len(hand) < 2 or rng.random() < 0.5 else 2
                    out = call("human_play", cards=rng.sample(range(len(hand)), n))
                self.assertTrue(out["ok"], out)
            before = s["hp"]
            s = out["state"]
            if out["kind"] == "call":
                rounds += 1
                lost = [b - a for a, b in zip(s["hp"], before)]
                self.assertEqual(sorted(lost), [0, 1], "exactly one heart per call")
                self.assertTrue(s["round_over"])
        self.assertIsNotNone(s["winner"])
        self.assertEqual(s["hp"][1 - s["winner"]], 0, "the loser is out of hearts")
        self.assertGreater(s["hp"][s["winner"]], 0)
        return rounds

    def test_matches_with_a_human(self):
        for seed in range(12):
            self.play_out(seed, hp=1 + seed % 3, bot_first=seed % 2 == 1, easy=seed % 4 == 3)

    def test_two_bots(self):
        for seed in range(6):
            self.play_out(seed, hp=2, spectator=True)

    def test_spectator_cannot_play(self):
        s = new(seed=14, spectator=True)
        self.assertTrue(s["peek"] and s["hands"][1] is not None)
        self.assertFalse(call("human_play", cards=[0])["ok"])
        self.assertFalse(call("human_call")["ok"])
        self.assertFalse(call("coach")["active"])


class TestCoach(unittest.TestCase):
    def test_coach_after_a_bot_play(self):
        new(seed=15)
        self.assertFalse(call("coach")["active"])
        call("human_play", cards=[0])
        bot = call("bot_move")
        coach = call("coach")
        if bot["kind"] == "play":
            self.assertTrue(coach["active"])
            self.assertTrue(0.0 <= coach["p_lie"] <= 1.0)
        self.assertEqual([m for m, _ in coach["rows"]], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
