"""
webapi.py -- the bridge between the browser and the game code.

The web page (web/app.js) runs THIS file together with ds.py, engine.py and bot.py inside the browser,
using Pyodide (CPython compiled to WebAssembly).  JavaScript only draws things and handles clicks;
every rule and every bot decision is still computed by the same Python the desktop version uses.

All data crosses the bridge as JSON text:   dispatch(name, json_text) -> json_text

    new_match   {hp, seed, spectator, easy, bot_first, peek}   start a match
    state       {}                                              what the screen may show right now
    human_play  {cards: [hand indexes]}                         you place 1-2 cards
    human_call  {}                                              you call LIE
    bot_move    {}                                              the current bot plays or calls
    next_round  {}                                              deal the next round (after a call)
    set_peek    {peek: bool}                                    show / hide the bot's hand and ranking
    coach       {}                                              the maths behind the bot's last play

The Python side refuses moves made out of turn, so the bot can never act while it is your turn.

Complexity notation: h = cards in a hand (<= 9), p = plays on the pile, c = moves the bot ranks (<= 10).
"""

import json
import time

from bot import Bot, odds_rows, p_play_is_lie
from engine import Game


class Session:
    """One running match: the Game, its bots and the "peek" setting. Seat 0 is the human unless `spectator`."""

    def __init__(self, hp=3, seed=None, spectator=False, easy=False, bot_first=False, peek=False):
        """Start a match (round 1 is dealt immediately), with the same bot options as gui.py.

        Time:  O(h^2 + W)  (dealing the first round, allocating the bots' memory)
        Space: O(h + W)
        """
        names = ("Bot A", "Bot B") if spectator else ("You", "Bot")
        self.spectator = bool(spectator)
        self.peek = bool(peek) or self.spectator          # two bots playing: nothing is hidden
        self.game = Game(names=names, hp_max=int(hp), seed=seed, first=1 if bot_first else 0)
        kw = {"temperature": 2.0, "top_k": 5} if easy else {}
        base = seed if seed is not None else int(time.time() * 1000) % 1_000_000
        if self.spectator:
            self.bots = [Bot(base, **kw), Bot(base + 1, **kw)]
        else:
            self.bots = [None, Bot(base, **kw)]

    # ---- reading ------------------------------------------------------------
    def state(self):
        """Everything the screen is allowed to show. The pile holds only WHO played and HOW MANY cards.

        The bot's hand is included only while peeking; pile colours are never sent (a call reveals them).

        Time:  O(h + p)
        Space: O(h + p)
        """
        g = self.game
        hands = [[int(c) for c in p.hand] for p in g.players]
        return {
            "round": g.round_no,
            "target": int(g.target),
            "hp_max": g.hp_max,
            "names": [p.name for p in g.players],
            "hp": [p.hp for p in g.players],
            "current": g.current_index,
            "must_call": g.must_call(g.current_index),
            "can_call": not g.table.is_empty(),
            "round_over": g.round_over,
            "game_over": g.game_over,
            "winner": g.winner,
            "counts": [len(h) for h in hands],
            "hands": [hands[0], hands[1] if self.peek else None],
            "pile": [{"player": play.player, "size": len(play.cards)} for play in g.table.to_list()],
            "placed": [p.played for p in g.players],
            "rounds": len(g.history),
            "caught": sum(1 for r in g.history if r.was_lie),
            "spectator": self.spectator,
            "peek": self.peek,
        }

    def coach(self):
        """The maths shown to the human: P(the bot's last play is a lie) and the 'could it be honest?' table.

        Time:  O(1)  (a fixed 5-row table)
        Space: O(1)
        """
        g = self.game
        rows = [[m, p] for m, p in odds_rows()]
        if self.spectator or g.round_over or g.table.is_empty() or g.table.peek().player == 0:
            return {"ok": True, "active": False, "rows": rows}
        opp = g.players[1]
        return {"ok": True, "active": True, "rows": rows, "placed": opp.played,
                "p_lie": p_play_is_lie(opp.played, len(g.table.peek().cards))}

    @staticmethod
    def result(res):
        """A CallResult as plain data (this is where the popped cards are finally revealed).

        Time:  O(k)
        Space: O(k)
        """
        return {"caller": res.caller, "accused": res.accused, "cards": [int(c) for c in res.play.cards],
                "was_lie": res.was_lie, "loser": res.loser}

    def think(self, idx, decision):
        """The bot's ranking as plain data, for the 'bot's mind' panel (only sent while peeking).

        Time:  O(c)
        Space: O(c)
        """
        heap = [{"label": o.label, "score": round(o.score, 3), "chosen": o is decision.chosen}
                for o in decision.heap]
        ranking = [{"label": o.label, "score": round(o.score, 3), "prob": round(p, 3)}
                   for o, p in zip(decision.ranking, decision.probs)]
        return {"ranking": ranking, "heap": heap, "chosen": decision.chosen.label,
                "eager": round(decision.eager, 3), "states": decision.states,
                "memory": self.bots[idx].memory.text()}

    # ---- acting -------------------------------------------------------------
    def human_play(self, cards):
        """Place the cards at these positions of your hand (0-based, 1 or 2 of them) face-down on the pile.

        Time:  O(h)
        Space: O(k)
        """
        g = self.game
        if self.spectator or g.current_index != 0:
            return {"ok": False, "error": "it is not your turn"}
        if g.round_over or g.game_over:
            return {"ok": False, "error": "the round is over"}
        hand = [int(c) for c in g.players[0].hand]
        if (len(set(cards)) != len(cards) or
                any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(hand) for i in cards)):
            return {"ok": False, "error": "those cards are not in your hand"}
        try:
            play = g.play(tuple(hand[i] for i in cards))
        except ValueError as err:
            return {"ok": False, "error": str(err)}
        return {"ok": True, "kind": "play", "player": 0, "size": len(play.cards), "state": self.state()}

    def human_call(self):
        """Call LIE on the bot's last play.

        Time:  O(k)
        Space: O(k)
        """
        g = self.game
        if self.spectator or g.current_index != 0:
            return {"ok": False, "error": "it is not your turn"}
        try:
            res = g.call()
        except ValueError as err:
            return {"ok": False, "error": str(err)}
        return {"ok": True, "kind": "call", "result": self.result(res), "state": self.state()}

    def bot_move(self):
        """Let the bot whose turn it is decide and act. Refused when it is a human's turn.

        Time:  O(h + c + S + K log c)  (observe, score the moves, heapify, pop the top K; S = look-ahead states)
        Space: O(c + S)
        """
        g = self.game
        idx = g.current_index
        if self.bots[idx] is None:
            return {"ok": False, "error": "it is not the bot's turn"}
        if g.round_over or g.game_over:
            return {"ok": False, "error": "the round is over"}
        decision = self.bots[idx].decide(g.observe(idx))
        out = {"ok": True, "player": idx, "action": decision.action}
        if decision.action == "call":
            out["kind"] = "call"
            out["result"] = self.result(g.call())
        else:
            play = g.play(decision.cards)
            out["kind"] = "play"
            out["size"] = len(play.cards)
            if self.peek:
                out["cards"] = [int(c) for c in play.cards]
        if self.peek:
            out["think"] = self.think(idx, decision)
        out["state"] = self.state()
        return out

    def next_round(self):
        """Deal the next round (only after a call, and only while the match goes on).

        Time:  O(h^2)
        Space: O(h)
        """
        g = self.game
        if not g.round_over or g.game_over:
            return {"ok": False, "error": "the round is not over"}
        g.next_round()
        return {"ok": True, "state": self.state()}

    def set_peek(self, peek):
        """Show or hide the bot's hand and ranking (always on when two bots play).

        Time:  O(h + p)
        Space: O(h + p)
        """
        self.peek = bool(peek) or self.spectator
        return {"ok": True, "state": self.state()}


# ---- the single entry point used by JavaScript ------------------------------
_session = None


def dispatch(name, payload_json="{}"):
    """Run one API call by name; take and return JSON text. Errors come back as {"ok": false, "error": ...}.

    Time:  O(the chosen call)
    Space: O(the chosen call)
    """
    global _session
    try:
        args = json.loads(payload_json) if payload_json else {}
        if name == "new_match":
            _session = Session(hp=args.get("hp", 3), seed=args.get("seed"), spectator=args.get("spectator", False),
                               easy=args.get("easy", False), bot_first=args.get("bot_first", False),
                               peek=args.get("peek", False))
            out = {"ok": True, "state": _session.state()}
        elif _session is None:
            out = {"ok": False, "error": "no match yet: call new_match first"}
        elif name == "state":
            out = {"ok": True, "state": _session.state()}
        elif name == "coach":
            out = _session.coach()
        elif name == "human_play":
            out = _session.human_play(args.get("cards", []))
        elif name == "human_call":
            out = _session.human_call()
        elif name == "bot_move":
            out = _session.bot_move()
        elif name == "next_round":
            out = _session.next_round()
        elif name == "set_peek":
            out = _session.set_peek(args.get("peek", False))
        else:
            out = {"ok": False, "error": "unknown call: %s" % name}
    except (ValueError, TypeError, KeyError) as err:
        out = {"ok": False, "error": "%s: %s" % (type(err).__name__, err)}
    return json.dumps(out)
