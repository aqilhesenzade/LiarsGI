"""
cli.py -- Play "Liar's Cards" in the terminal (the safe, no-install demo).

Run:   python cli.py            (you vs the bot)
       python cli.py --bots     (bot vs bot, you just watch -- great for explaining the heap)
       python cli.py --help     (all options)

Controls while it is YOUR turn:
    r / g / b / rg / "r b" / rr ...   play 1 or 2 cards of those colours
    c                                 call LIE on the previous play
    ?                                 toggle the probability coach
    x                                 toggle x-ray (shows the bot's hand + its heap ranking)
    q                                 quit

What you see (every screen is drawn from the game's own data structures):
    YOUR HAND  = the linked list   (head > R > R > G > ... > None)
    THE PILE   = the stack         (TOP is the play a call will pop)
    BOT'S MIND = the max-heap      (x-ray: ranked moves + soft-max chance)

Complexity notation: h = cards in a hand (<= 9), k = cards in a play (<= 2),
c = candidate bot moves (<= 10), K = moves kept from the heap (3),
r = rows printed (a small constant).  All functions here are O(h) or better.
"""

import argparse
import os
import re
import shutil
import sys
import time

import art
from engine import Game, Color, COLOR_NAMES, COLOR_LETTERS, cards_to_str
from bot import Bot, p_play_is_lie, odds_rows

HUMAN = 0
BOT = 1
WIDTH = 78                   # total width of every framed line
INNER = WIDTH - 4            # usable width between the frame's side bars
_ANSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")


# --------------------------------------------------------------------------
# Tiny text helpers
# --------------------------------------------------------------------------
def _can_print(text):
    """True if the terminal's encoding can print `text` (box lines, hearts, arrows).

    Time:  O(len(text))
    Space: O(1)
    """
    try:
        text.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def visible_len(text):
    """Length of `text` as the eye sees it: ANSI colour codes take no room.

    Time:  O(len(text))
    Space: O(len(text))
    """
    return len(_ANSI.sub("", text))


def pad(text, width, align="left"):
    """Pad `text` with spaces to `width` visible characters (left / right / center aligned).

    Time:  O(len(text))
    Space: O(width)
    """
    gap = max(0, width - visible_len(text))
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def center(text):
    """Centre `text` on the full table width.

    Time:  O(len(text))
    Space: O(WIDTH)
    """
    return pad(text, WIDTH, "center")


class Style:
    """Colours, card art and frame glyphs; degrades to plain ASCII when the terminal needs it."""

    PALETTE = {"gold": "38;5;220", "dim": "38;5;245", "good": "38;5;84", "bad": "38;5;203",
               "frame": "38;5;67", "heart": "38;5;197", "ice": "38;5;117"}
    TILE_BG = {Color.RED: "48;5;160", Color.GREEN: "48;5;28", Color.BLUE: "48;5;27"}
    LETTER_FG = {Color.RED: "38;5;203", Color.GREEN: "38;5;78", Color.BLUE: "38;5;75"}
    BACK = "48;5;17;38;5;75"

    def __init__(self, use_color):
        """Decide whether to use ANSI colours and which glyph set the terminal can print.

        Time:  O(1)
        Space: O(1)
        """
        self.color = bool(use_color) and not os.environ.get("NO_COLOR")
        if self.color and os.name == "nt":
            os.system("")                      # enables ANSI codes in Windows 10+ consoles
        self.uni = _can_print("╔═╗║╚╝╠╣┌─┐│└┘▒░▶◀▲█•❯")
        if self.uni:
            self.tl, self.h, self.tr, self.v = "╔", "═", "╗", "║"
            self.bl, self.br, self.ml, self.mr = "╚", "╝", "╠", "╣"
            self.sl = ("┌", "─", "┐", "│", "└", "┘")
            self.arrow, self.back_arrow, self.up = "▶", "◀", "▲"
            self.fill, self.hollow, self.dot, self.prompt = "█", "░", "•", "❯"
            self.shade = ("▒", "░")
            self.spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        else:
            self.tl, self.h, self.tr, self.v = "+", "=", "+", "|"
            self.bl, self.br, self.ml, self.mr = "+", "+", "+", "+"
            self.sl = ("+", "-", "+", "|", "+", "+")
            self.arrow, self.back_arrow, self.up = ">", "<", "^"
            self.fill, self.hollow, self.dot, self.prompt = "#", "-", "*", ">"
            self.shade = ("#", "+")
            self.spin = "|/-\\"
        self.heart, self.empty = ("\u2665", "\u2661") if _can_print("\u2665\u2661") else ("#", ".")

    # ---- plain colouring ---------------------------------------------------
    def paint(self, text, name=None, bold=False):
        """Wrap `text` in a named palette colour (and/or bold) when colours are on.

        Time:  O(len(text))
        Space: O(len(text))
        """
        if not self.color:
            return text
        codes = (["1"] if bold else []) + ([self.PALETTE[name]] if name else [])
        return "\033[%sm%s\033[0m" % (";".join(codes), text) if codes else text

    def bold(self, text):
        """Bold text (if colours are on).

        Time:  O(len(text))
        Space: O(len(text))
        """
        return self.paint(text, bold=True)

    def dim(self, text):
        """Grey text for secondary information.

        Time:  O(len(text))
        Space: O(len(text))
        """
        return self.paint(text, "dim")

    def letter(self, color):
        """One coloured colour-letter (R / G / B) used in the linked-list line.

        Time:  O(1)
        Space: O(1)
        """
        ch = COLOR_LETTERS[color]
        return "\033[%s;1m%s\033[0m" % (self.LETTER_FG[color], ch) if self.color else ch

    # ---- cards -------------------------------------------------------------
    def card_rows(self, color, face=True, width=5):
        """Three text rows of one BIG card, each exactly `width` columns (width 5, 3 or 1).

        Colour mode draws a solid tile; plain mode draws a boxed card (always 5 wide).
        `color` is a Color, `face=False` draws the patterned back instead.

        Time:  O(1)
        Space: O(1)
        """
        ch = COLOR_LETTERS[color] if face else "?"
        if not self.color:
            tl, hz, tr, vt, bl, br = self.sl
            inside = " %s " % ch if face else self.shade[0] * 3
            return [tl + hz * 3 + tr, vt + inside + vt, bl + hz * 3 + br]
        rows = []
        for r in range(3):
            if face:
                body = ch.center(width) if (r == 1 and width >= 3) else " " * width
                rows.append("\033[%s;97;1m%s\033[0m" % (self.TILE_BG[color], body))
            else:
                body = "".join(self.shade[(r + c) % 2] for c in range(width))
                rows.append("\033[%sm%s\033[0m" % (self.BACK, body))
        return rows

    def tiles(self, cards, face=True):
        """Three lines showing `cards` side by side as big cards.

        Time:  O(k)
        Space: O(k)
        """
        parts = [self.card_rows(c, face) for c in cards]
        return [" ".join(p[r] for p in parts) for r in range(3)]

    def mini(self, color, face=True):
        """One small 3-character card for single-line rows (hand of the bot, the pile).

        Time:  O(1)
        Space: O(1)
        """
        if not self.color:
            return "[%s]" % (COLOR_LETTERS[color] if face else "?")
        if face:
            return "\033[%s;97;1m %s \033[0m" % (self.TILE_BG[color], COLOR_LETTERS[color])
        return "\033[%sm%s\033[0m" % (self.BACK, self.shade[0] + self.shade[1] + self.shade[0])

    def minis(self, cards, face=True):
        """A row of small cards.

        Time:  O(k)
        Space: O(k)
        """
        return " ".join(self.mini(c, face) for c in cards)

    def chip(self, color):
        """The target colour as a coloured label, e.g. ' RED '.

        Time:  O(1)
        Space: O(1)
        """
        if not self.color:
            return "[%s]" % COLOR_NAMES[color]
        return "\033[%s;97;1m %s \033[0m" % (self.TILE_BG[color], COLOR_NAMES[color])

    def big_tile(self, color):
        """A large target-colour block (17 x 5) for the round splash screen.

        Time:  O(1)
        Space: O(1)
        """
        name = COLOR_NAMES[color]
        if not self.color:
            tl, hz, tr, vt, bl, br = self.sl
            blank = vt + " " * 15 + vt
            return [tl + hz * 15 + tr, blank, vt + name.center(15) + vt, blank, bl + hz * 15 + br]
        rows = []
        for r in range(5):
            body = name.center(17) if r == 2 else " " * 17
            rows.append("\033[%s;97;1m%s\033[0m" % (self.TILE_BG[color], body))
        return rows

    # ---- hearts and bars ---------------------------------------------------
    def hearts(self, hp, hp_max):
        """Hearts string such as '♥♥♡' (red full hearts, grey empty ones).

        Time:  O(hp_max)
        Space: O(hp_max)
        """
        return self.paint(self.heart * hp, "heart") + self.dim(self.empty * (hp_max - hp))

    def bar(self, fraction, width=12):
        """A horizontal probability bar, e.g. '██████░░░░░░'.

        Time:  O(width)
        Space: O(width)
        """
        full = int(round(max(0.0, min(1.0, fraction)) * width))
        return self.paint(self.fill * full, "gold") + self.dim(self.hollow * (width - full))

    # ---- frame -------------------------------------------------------------
    def edge(self, left, title, right):
        """A horizontal frame line (top / divider / bottom) with an optional title.

        Time:  O(WIDTH)
        Space: O(WIDTH)
        """
        label = (" %s " % title) if title else ""
        fill = WIDTH - 4 - visible_len(label)
        return (self.paint(left + self.h * 2, "frame") + label
                + self.paint(self.h * fill + right, "frame"))

    def row(self, content=""):
        """One framed text row: side bar, content padded to INNER columns, side bar.

        Time:  O(INNER)
        Space: O(INNER)
        """
        bar = self.paint(self.v, "frame")
        return bar + " " + pad(content, INNER) + " " + bar


def parse_move(text, counts):
    """Parse what the human typed.

    Returns ("call", (), None), ("play", cards, None) or (kind, (), error_text).
    `counts` is the human's [red, green, blue] hand counts.

    Time:  O(len(text))
    Space: O(k)
    """
    t = text.strip().lower()
    if t in ("c", "call", "l", "lie"):
        return "call", (), None
    letters = [ch for ch in t if ch not in " ,"]
    if not letters or any(ch not in "rgb" for ch in letters):
        return "error", (), "Type colours like  r  or  rb  (R/G/B),  c  to call LIE,  q  to quit."
    if len(letters) > 2:
        return "error", (), "You can play at most 2 cards."
    cards = tuple(Color("rgb".index(ch)) for ch in letters)
    need = [0, 0, 0]
    for card in cards:
        need[card] += 1
    for color in Color:
        if need[color] > counts[color]:
            return "error", (), "You do not have %d %s card(s)." % (need[color], COLOR_NAMES[color])
    return "play", cards, None


# --------------------------------------------------------------------------
# The CLI game
# --------------------------------------------------------------------------
class CLIGame:
    """Runs a whole match in the terminal (human vs bot, or bot vs bot)."""

    def __init__(self, game, bots, humans, style, delay=0.9, coach=False, xray=False, clear=True):
        """Store everything needed to run a match.

        `bots` and `humans` are lists indexed by player (None where not used).
        `delay` is the base pause in seconds (0 = no pauses and no animation, used by the tests).

        Time:  O(1)
        Space: O(1)
        """
        self.game = game
        self.bots = bots
        self.humans = humans
        self.st = style
        self.delay = delay
        self.coach = coach
        self.xray = xray
        self.clearing = clear
        self.spectator = not any(humans)     # bot-vs-bot: show every card
        self.feed = []                       # the last few things that happened this round
        self.last_decision = None            # the bot's latest heap ranking (for the x-ray block)

    # ---- output helpers ---------------------------------------------------
    def say(self, text=""):
        """Print one line immediately.

        Time:  O(len(text))
        Space: O(1)
        """
        print(text, flush=True)

    def pause(self, seconds=None):
        """Short sleep so the audience can follow what happens.

        Time:  O(1) (plus the sleep)
        Space: O(1)
        """
        time.sleep(self.delay if seconds is None else seconds)

    def animating(self):
        """True when we may use cursor tricks and animation (a real colour terminal, delay > 0).

        Time:  O(1)
        Space: O(1)
        """
        return bool(self.st.color) and self.delay > 0 and sys.stdout.isatty()

    def clear(self):
        """Wipe the screen so every turn starts from a clean table (only on a real colour terminal).

        Time:  O(1)
        Space: O(1)
        """
        if self.clearing and self.animating():
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()

    def wait(self, message):
        """Wait for Enter when presenting live (skipped when delay is 0).

        Time:  O(1) (plus the human's reaction time)
        Space: O(1)
        """
        if self.delay <= 0:
            return
        try:
            input("  " + self.st.dim(message) + " ")
        except EOFError:
            raise SystemExit("\nInput closed - bye!")

    def poss(self, idx):
        """'your' / 'Bot's' for sentences.

        Time:  O(1)
        Space: O(1)
        """
        return "your" if self.humans[idx] else self.game.players[idx].name + "'s"

    def event(self, text):
        """Print an event line now and remember it for the 'LAST MOVES' panel.

        Time:  O(1)
        Space: O(1)
        """
        self.say("  %s %s" % (self.st.paint(self.st.dot, "gold"), text))
        self.feed = (self.feed + [text])[-3:]

    def think(self, name):
        """Show a 'thinking' spinner for about `delay` seconds (a plain line when not animating).

        Time:  O(1) (plus the sleep)
        Space: O(1)
        """
        st = self.st
        label = "%s is thinking" % name
        if not self.animating():
            self.say("  %s..." % label)
            self.pause()
            return
        end, i = time.time() + self.delay, 0
        while time.time() < end:
            sys.stdout.write("\r  %s %s " % (st.paint(st.spin[i % len(st.spin)], "gold"), label))
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
        sys.stdout.write("\r" + " " * (len(label) + 8) + "\r")
        sys.stdout.flush()

    # ---- screens ------------------------------------------------------------
    def header(self):
        """The two-line banner: round number, target colour chip and both players' hearts.

        Time:  O(hp_max)
        Space: O(hp_max)
        """
        g, st = self.game, self.st
        a, b = g.players[0], g.players[1]
        right = "%s %s    %s %s" % (st.bold(a.name.upper()), st.hearts(a.hp, g.hp_max),
                                    st.bold(b.name.upper()), st.hearts(b.hp, g.hp_max))
        left = "%s   TARGET %s" % (st.bold("ROUND %d" % g.round_no), st.chip(g.target))
        line = pad(left, INNER - visible_len(right)) + right
        return [st.edge(st.tl, st.paint("LIAR'S CARDS", "gold", bold=True), st.tr), st.row(line)]

    def splash(self):
        """Title screen: ASCII-art logo, a card fan and the rules in three lines.

        Time:  O(r)
        Space: O(r)
        """
        st = self.st
        self.clear()
        self.say("")
        for line in art.TITLE:
            self.say(center(st.paint(line, "gold", bold=True)))
        self.say(center(st.dim("a tiny bluffing game  -  built on linked lists, stacks and heaps")))
        self.say("")
        parts = [st.card_rows(c) for c in Color] + [st.card_rows(Color.RED, face=False)]
        for r in range(3):
            self.say(center("  ".join(p[r] for p in parts)))
        self.say("")
        rules = ["Each round one colour is the TARGET. Both players hold 9 cards (2 : 3 : 4).",
                 "Play 1-2 cards face-down and claim they are all the target colour,",
                 "or call LIE on the previous play. Whoever is wrong loses a heart."]
        for line in rules:
            self.say(center(line))
        self.say("")
        self.wait("Press Enter to deal >")

    def round_splash(self):
        """Full-screen 'ROUND n' card that announces the target colour.

        Time:  O(r)
        Space: O(r)
        """
        g, st = self.game, self.st
        self.clear()
        self.say("\n")
        self.say(center(st.bold("%s  ROUND %d  %s" % (st.h * 6, g.round_no, st.h * 6))))
        self.say("")
        self.say(center("everyone is dealt 9 cards - claim this colour:"))
        self.say("")
        for line in st.big_tile(g.target):
            self.say(center(line))
        self.say("")
        opener = g.players[g.current_index]
        self.say(center(st.dim("%s open%s the round" % (opener.name, "" if self.humans[g.current_index] else "s"))))
        self.pause(self.delay * 1.3)

    def pile_rows(self):
        """Rows of the 'pile' panel: the top 3 plays of the stack, newest first.

        Time:  O(p)  (to_list copies the stack; only the top 3 plays are drawn)
        Space: O(p)
        """
        g, st = self.game, self.st
        plays = g.table.to_list()
        if not plays:
            return [st.row(st.dim("(empty)  -  the first play will be pushed here"))]
        out = []
        for i, play in enumerate(plays[::-1][:3]):
            face = self.spectator or (self.xray and play.player == BOT)
            prefix = st.paint("TOP %s " % st.arrow, "gold", bold=True) if i == 0 else "      "
            note = st.paint("pop() on a call", "gold") if i == 0 else ""
            left = "%s%s %s" % (prefix, pad(g.players[play.player].name, 6), st.minis(play.cards, face))
            out.append(st.row(pad(left, INNER - visible_len(note)) + note))
        if len(plays) > 3:
            out.append(st.row(st.dim("      ... %d more play(s) further down the stack" % (len(plays) - 3))))
        return out

    def coach_rows(self):
        """Rows of the coach panel: P(last play is a lie) as a bar plus the 'honest capacity' odds.

        Time:  O(1)  (a fixed 5-entry table)
        Space: O(1)
        """
        g, st = self.game, self.st
        other = g.players[BOT]
        lie = p_play_is_lie(other.played, len(g.table.peek().cards))
        verdict = st.paint("CALL IT", "good", bold=True) if lie >= 0.5 else st.dim("play on")
        odds = "  ".join("%d:%d%%" % (m, round(p * 100)) for m, p in odds_rows())
        return [
            st.row("%s placed %d card%s   P(last play is a LIE) %s %3d%%  %s" % (
                other.name, other.played, "" if other.played == 1 else "s",
                st.bar(lie, 12), round(lie * 100), verdict)),
            st.row(st.dim("honest chance by cards placed:  ") + odds),
        ]

    def mind_rows(self, decision):
        """Rows describing the bot's heap ranking (shared by the x-ray panel and the live print).

        Time:  O(K)
        Space: O(K)
        """
        st = self.st
        out = []
        for rank, (opt, prob) in enumerate(zip(decision.ranking, decision.probs), 1):
            mark = "  " + st.paint("%s chosen" % st.back_arrow, "gold", bold=True) if opt is decision.chosen else ""
            out.append("%d  %+.2f  %-19s %s %3d%%%s" % (rank, opt.score, opt.label, st.bar(prob, 12),
                                                         round(prob * 100), mark))
        return out

    def hand_line(self, cards):
        """The hand drawn as a linked list: head > R > R > G ... > None.

        Time:  O(h)
        Space: O(h)
        """
        st = self.st
        if not cards:
            return st.dim("head %s None" % st.arrow)
        body = (" %s " % st.arrow).join(st.letter(c) for c in cards)
        return st.dim("head %s " % st.arrow) + body + st.dim(" %s None" % st.arrow)

    def show_status(self):
        """Redraw the whole table: banner, bot hand, pile, last moves, (coach), (x-ray) and your hand.

        Time:  O(h + p)
        Space: O(h + p)
        """
        g, st = self.game, self.st
        me, bot = g.players[HUMAN], g.players[BOT]
        self.clear()
        lines = self.header()

        def zone(idx, big):
            """Lines of one player's hand zone (big tiles for the human, one-row minis otherwise).

            Time:  O(h)
            Space: O(h)
            """
            player = g.players[idx]
            cards = player.hand.to_list()
            counts = player.counts()
            face = big or self.spectator or (self.xray and idx == BOT)
            title = st.bold("YOUR HAND" if big else player.name.upper()) + st.dim(
                "  %s  %d card%s, %d placed" % (st.dot, len(cards), "" if len(cards) == 1 else "s", player.played))
            if face:
                title += st.dim("  %s  " % st.dot) + "  ".join("%s %d" % (st.letter(c), counts[c]) for c in Color)
            if big:
                title += st.dim("  %s  " % st.dot) + st.paint(st.up, "gold") + st.dim(" = target")
            out = [st.edge(st.ml, title, st.mr)]
            if not cards:
                out.append(st.row(st.dim("(no cards left - must call)")))
            elif big:
                out.extend(st.row(row) for row in st.tiles(cards))
                mark = [st.paint("  %s  " % st.up, "gold") if c == g.target else "     " for c in cards]
                out.append(st.row(" ".join(mark)))
                out.append(st.row(self.hand_line(cards)))
            else:
                out.append(st.row(st.minis(cards, face)))
                if self.spectator:
                    out.append(st.row(self.hand_line(cards)))
            return out

        lines += zone(BOT, big=False)
        lines.append(st.edge(st.ml, st.bold("THE PILE") + st.dim("  %s  a stack (LIFO)  %s  %d play(s), %d card(s)" % (
            st.dot, st.dot, len(g.table), me.played + bot.played)), st.mr))
        lines += self.pile_rows()
        lines.append(st.edge(st.ml, st.bold("LAST MOVES"), st.mr))
        recent = self.feed or ["(the round has just started)"]
        for i, text in enumerate(recent):
            lines.append(st.row(text if i == len(recent) - 1 else st.dim(text)))
        if self.coach and not g.table.is_empty() and self.humans[HUMAN]:
            lines.append(st.edge(st.ml, st.paint("COACH", "good", bold=True) + st.dim("  (toggle with ?)"), st.mr))
            lines += self.coach_rows()
        if self.xray and self.last_decision is not None and not self.spectator:
            lines.append(st.edge(st.ml, st.paint("BOT'S MIND", "ice", bold=True)
                                 + st.dim("  %s  max-heap, top 3 popped  (toggle with x)" % st.dot), st.mr))
            lines += [st.row(r) for r in self.mind_rows(self.last_decision)]
        lines += zone(HUMAN, big=bool(self.humans[HUMAN]))
        lines.append(st.edge(st.bl, "", st.br))
        for line in lines:
            self.say(line)

    # ---- turns ------------------------------------------------------------
    def human_turn(self):
        """Ask the human for a legal move and apply it; returns a CallResult or None.

        Time:  O(h) per attempt
        Space: O(1)
        """
        g, st = self.game, self.st
        me = g.players[HUMAN]
        forced = g.must_call(HUMAN)
        hint = st.dim("  colours e.g. rg  %s  c = call LIE  %s  ? coach  %s  x x-ray  %s  q quit"
                      % (st.dot, st.dot, st.dot, st.dot))
        if forced:
            self.say("  " + st.paint("You have no cards left - you MUST call LIE.", "bad", bold=True))
        else:
            self.say(hint)
        while True:
            if forced:
                prompt = "Press Enter to call LIE"
            elif g.table.is_empty():
                prompt = "You open the round - play 1-2 cards"
            else:
                prompt = "Play 1-2 cards, or c = call LIE"
            try:
                text = input("  %s %s " % (st.paint(st.prompt, "gold", bold=True), prompt + ":"))
            except EOFError:
                raise SystemExit("\nInput closed - bye!")
            t = text.strip().lower()
            if t in ("q", "quit", "exit"):
                raise SystemExit("Bye!")
            if t in ("?", "x"):
                if t == "?":
                    self.coach = not self.coach
                else:
                    self.xray = not self.xray
                self.show_status()
                self.say(hint)
                continue
            if forced:
                return g.call()
            kind, cards, error = parse_move(text, me.counts())
            if kind == "error":
                self.say(st.paint("  ! " + error, "bad"))
                continue
            if kind == "call":
                if g.table.is_empty():
                    self.say(st.paint("  ! Nothing to call yet - you are first, you must play.", "bad"))
                    continue
                return g.call()
            g.play(cards)
            self.event("You placed %d card%s face-down on the pile (push)." % (len(cards), "s" if len(cards) > 1 else ""))
            return None

    def show_mind(self, name, decision):
        """Print the bot's heap ranking as a small panel (x-ray and bot-vs-bot only).

        Time:  O(c)
        Space: O(c)
        """
        st = self.st
        tl, hz, _tr, vt, _bl, _br = st.sl
        self.say("  " + st.paint(tl + hz + " ", "frame") + st.paint("%s's mind" % name, "ice", bold=True)
                 + st.dim("  max-heap of %d moves, top %d popped, one picked by soft-max" % (
                     len(decision.heap), len(decision.ranking))))
        for row in self.mind_rows(decision):
            self.say("  " + st.paint(vt, "frame") + " " + row)
        scores = " ".join("%+.1f" % o.score for o in decision.heap)
        self.say("  " + st.paint(vt, "frame") + " " + st.dim("heap array: [ %s ]" % scores))

    def bot_turn(self, idx):
        """Let bot `idx` think and act; returns a CallResult or None.

        Time:  O(h + c + K log c)   (observe + score the moves + heapify + K heap pops)
        Space: O(c)
        """
        g = self.game
        name = g.players[idx].name
        self.think(name)
        decision = self.bots[idx].decide(g.observe(idx))
        self.last_decision = decision
        if self.xray or self.spectator:
            self.show_mind(name, decision)
            self.pause(self.delay * (1.4 if self.spectator else 0.6))
        if decision.action == "call":
            return g.call()
        play = g.play(decision.cards)
        shown = "  [%s]" % cards_to_str(play.cards) if (self.xray or self.spectator) else ""
        self.event("%s placed %d card%s face-down on the pile.%s" % (
            name, len(play.cards), "s" if len(play.cards) > 1 else "", shown))
        return None

    # ---- the dramatic reveal ----------------------------------------------
    def card_block(self, cards, face, width):
        """Three text lines of the popped cards at a given width (used by the flip animation).

        Time:  O(k)
        Space: O(k)
        """
        st = self.st
        rows = ["", "", ""]
        for card in cards:
            tile = st.card_rows(card, face, width)
            left = (5 - width) // 2 if st.color else 0
            right = 5 - width - left if st.color else 0
            for r in range(3):
                rows[r] += " " * left + tile[r] + " " * right + "  "
        return [center(row) for row in rows]

    def flip(self, cards):
        """Show the popped play face-down, then flip it face-up (an animation on a real terminal).

        Time:  O(k)  (a fixed number of animation frames)
        Space: O(k)
        """
        if self.animating():
            frames = [(False, 5)] * 4 + [(False, 3), (False, 1), (True, 1), (True, 3), (True, 5)]
        else:
            frames = [(True, 5)]
        first = True
        for face, width in frames:
            if not first:
                sys.stdout.write("\033[3A")
            for line in self.card_block(cards, face, width):
                self.say(line)
            first = False
            if len(frames) > 1:
                time.sleep(self.delay * 0.11)

    def hearts_line(self, hp_before, hp_after):
        """Print the hearts line; on a real terminal a lost heart is shown, then removed.

        Time:  O(hp_max)
        Space: O(hp_max)
        """
        g, st = self.game, self.st

        def line(hps):
            """The two players' hearts for the given hit points, centred.

            Time:  O(hp_max)
            Space: O(hp_max)
            """
            return center("   ".join("%s %s" % (st.bold(p.name.upper()), st.hearts(h, g.hp_max))
                                      for p, h in zip(g.players, hps)))

        if hp_before != hp_after and self.animating():
            self.say(line(hp_before))
            self.pause(self.delay * 0.7)
            sys.stdout.write("\033[1A")
        self.say(line(hp_after))

    def reveal(self, result):
        """Full-screen reveal after a call: the pop, the card flip, a big verdict, the new hearts.

        Time:  O(k)
        Space: O(k)
        """
        g, st = self.game, self.st
        before = [p.hp for p in g.players]
        before[result.loser] += 1                  # the engine already took the heart
        self.clear()
        for line in self.header():
            self.say(line)
        self.say(st.edge(st.bl, "", st.br))
        caller = g.players[result.caller].name
        self.say("")
        self.say(center(st.paint(">>>  %s called LIE on %s last play!  <<<" % (caller, self.poss(result.accused)),
                                 "gold", bold=True)))
        self.pause()
        self.say(center(st.dim("pop() takes the top play off the pile...")))
        self.say("")
        self.pause(self.delay * 0.7)
        self.flip(result.play.cards)
        self.pause(self.delay * 0.6)
        tone = "gold" if self.spectator else ("good" if result.loser != HUMAN else "bad")
        self.say("")
        for line in (art.LIE if result.was_lie else art.TRUTH):
            self.say(center(st.paint(line, tone, bold=True)))
        self.say("")
        loser = "you" if self.humans[result.loser] else g.players[result.loser].name
        verb = "lose" if self.humans[result.loser] else "loses"
        if result.was_lie:
            msg = "A card was not %s - %s %s a heart." % (COLOR_NAMES[g.target], loser, verb)
        else:
            msg = "Every card was %s - the caller was wrong, %s %s a heart." % (COLOR_NAMES[g.target], loser, verb)
        self.say(center(st.bold(msg)))
        self.say("")
        self.hearts_line(before, [p.hp for p in g.players])
        self.say("")

    def finale(self):
        """Game-over screen: big ASCII verdict and the match statistics.

        Time:  O(r)
        Space: O(r)
        """
        g, st = self.game, self.st
        winner = g.players[g.winner]
        self.say("")
        if self.humans[HUMAN]:
            won = g.winner == HUMAN
            lines, tone = (art.WIN, "good") if won else (art.LOSE, "bad")
            sub = "The bot's bluffs were not enough." if won else "The Bot wins this time. Play again?"
        else:
            lines, tone, sub = art.OVER, "gold", "%s wins the match." % winner.name
        for line in lines:
            self.say(center(st.paint(line, tone, bold=True)))
        self.say(center(st.bold(sub)))
        self.say("")
        caught = sum(1 for r in g.history if r.was_lie)
        self.say(center(st.dim("Rounds played: %d   |   calls that caught a real lie: %d of %d"
                               % (len(g.history), caught, len(g.history)))))
        self.say("")

    # ---- main loop --------------------------------------------------------
    def run(self):
        """Play rounds until somebody reaches 0 HP.

        Time:  O(R * T * h)  (R rounds, T turns per round)
        Space: O(h)
        """
        g = self.game
        self.splash()
        while not g.game_over:
            self.feed, self.last_decision = [], None
            self.round_splash()
            if self.humans[HUMAN] and g.current_index != HUMAN:
                self.show_status()                 # table is visible while the bot opens the round
            while not g.round_over:
                idx = g.current_index
                if idx == HUMAN and self.humans[HUMAN]:
                    self.show_status()
                    result = self.human_turn()
                else:
                    if self.spectator:
                        self.show_status()
                    result = self.bot_turn(idx)
                if result is not None:
                    self.reveal(result)
            if not g.game_over:
                if self.spectator:
                    self.pause(self.delay * 1.5)
                else:
                    self.wait("Press Enter for the next round >")
                g.next_round()
        self.finale()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def build_parser():
    """Command-line options.

    Time:  O(1)
    Space: O(1)
    """
    ap = argparse.ArgumentParser(description="Liar's Cards - a tiny bluffing game for a Data Structures demo.")
    ap.add_argument("--bots", action="store_true", help="bot vs bot: just watch (shows all cards + heap ranking)")
    ap.add_argument("--easy", action="store_true", help="a more random, easier-to-beat bot")
    ap.add_argument("--coach", action="store_true", help="start with the probability coach ON (toggle with ?)")
    ap.add_argument("--xray", action="store_true", help="start with x-ray ON (toggle with x)")
    ap.add_argument("--hp", type=int, default=3, help="hearts per player (default 3 = a 2-3 minute match)")
    ap.add_argument("--seed", type=int, default=None, help="fix the shuffle -> identical game every run")
    ap.add_argument("--bot-first", action="store_true", help="the bot opens round 1 (default: you do)")
    ap.add_argument("--fast", action="store_true", help="shorter pauses")
    ap.add_argument("--no-color", action="store_true", help="plain output (boxes and letters, no colours)")
    ap.add_argument("--no-clear", action="store_true", help="do not wipe the screen between turns")
    return ap


def main(argv=None):
    """Parse options, build the game, bots and style, then run the match.

    Time:  O(R * T * h)  (same as CLIGame.run)
    Space: O(h)
    """
    args = build_parser().parse_args(argv)
    names = ("Bot A", "Bot B") if args.bots else ("You", "Bot")
    game = Game(names=names, hp_max=args.hp, seed=args.seed, first=1 if args.bot_first else 0)
    bot_kwargs = {"temperature": 2.0, "top_k": 5} if args.easy else {}
    base = args.seed if args.seed is not None else int(time.time())
    if args.bots:
        bots = [Bot(seed=base, **bot_kwargs), Bot(seed=base + 1, **bot_kwargs)]
        humans = [False, False]
    else:
        bots = [None, Bot(seed=base, **bot_kwargs)]
        humans = [True, False]
    style = Style(not args.no_color)
    cli = CLIGame(game, bots, humans, style, delay=0.25 if args.fast else 0.9,
                  coach=args.coach, xray=args.xray, clear=not args.no_clear)
    size = shutil.get_terminal_size((WIDTH, 30))
    if sys.stdout.isatty() and (size.columns < WIDTH or size.lines < 30):
        print(style.dim("Tip: enlarge the terminal to at least %d x 30 for the best view." % WIDTH))
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
