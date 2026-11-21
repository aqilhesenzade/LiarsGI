"""
gui.py -- pygame front-end for "Liar's Cards".  Same engine and bot as the CLI.

Run:   pip install pygame
       python gui.py              (you vs the bot)
       python gui.py --bots       (bot vs bot, you just watch)
       python gui.py --help

Controls:  click cards (or press R / G / B) to pick 1-2, Enter = play, C = call LIE,
           Space = skip an animation, Backspace/Esc = clear picks,
           R on the game-over screen = rematch, F11 = fullscreen.

Your hand is the engine's linked list and the pile is its stack; the screen just shows them.
Everything is drawn at the window's real pixel size with smoothed edges, so it stays sharp
when the window is resized or goes fullscreen.

Complexity notation: h = cards in a hand (<= 9), p = plays on the pile, c = moves the bot ranks (<= 10).
Drawing functions are O(h + p) per frame -- all small constants here.
"""

import argparse
import math
import os
import sys
import time

import pygame

from bot import Bot
from engine import COLOR_LETTERS, COLOR_NAMES, Color, Game

# --------------------------------------------------------------------------
# Look & feel
# --------------------------------------------------------------------------
W, H = 1280, 720          # the design space: every position below is in these units

BG = (21, 26, 36)
PANEL = (32, 41, 57)
EDGE = (55, 68, 91)
FELT = (27, 55, 54)
TEXT = (232, 237, 243)
MUTED = (140, 153, 171)
GOLD = (240, 185, 75)
GOOD = (98, 202, 142)
BAD = (234, 92, 92)
BACK = (44, 56, 82)
BACK_LINE = (72, 89, 124)
HEART_ON = (232, 80, 98)
HEART_OFF = (58, 68, 90)
WHITE = (255, 255, 255)
INK = (28, 28, 28)
CARD_COL = {Color.RED: (214, 69, 80), Color.GREEN: (48, 158, 102), Color.BLUE: (62, 124, 186)}

# Open, friendly humanist sans-serifs first (Nunito if installed, then each OS's own UI font),
# then Verdana / DejaVu, which are wide and very legible.  pygame's default font is the last resort.
FONT_NAMES = "nunito,segoeui,avenirnext,avenir,helveticaneue,ubuntu,cantarell,notosans,verdana,dejavusans,arial"
SS = 4                    # shapes are drawn SS times too big, then averaged down: that is the smoothing

# layout (design space; View maps it onto the real window)
CX = W // 2
BOT_Y, BOT_CW, BOT_CH, BOT_GAP = 73, 44, 62, 10
ME_Y, ME_CW, ME_CH, ME_GAP = 584, 66, 92, 14
BOT_PLATE = pygame.Rect(24, 62, 220, 84)
ME_PLATE = pygame.Rect(24, 584, 220, 84)
STACK_R = pygame.Rect(24, 158, 1232, 336)
BTN_PLAY = pygame.Rect(792, 506, 250, 46)
BTN_CALL = pygame.Rect(1056, 506, 200, 46)

FONTS = {}
TILES, DISCS, HEARTS, CARDS, VEILS, LAYERS = {}, {}, {}, {}, {}, {}     # caches of smoothed sprites


# --------------------------------------------------------------------------
# Window <-> design space
# --------------------------------------------------------------------------
class View:
    """Maps the 1280x720 design space onto the real window: one uniform scale, centred."""

    def __init__(self):
        """Start with a 1:1 mapping.

        Time:  O(1)
        Space: O(1)
        """
        self.k, self.ox, self.oy = 1.0, 0, 0

    def fit(self, size):
        """Fit the design space into a window of `size`; True when the scale changed.

        The scale moves in steps of 1/32, so fonts and sprites are rebuilt only now and then
        while a window edge is being dragged, not on every pixel of movement.

        Time:  O(1)
        Space: O(1)
        """
        ww, wh = size
        k = max(0.4, int(min(ww / W, wh / H) * 32) / 32)
        changed = k != self.k
        self.k = k
        self.ox, self.oy = int((ww - W * k) / 2), int((wh - H * k) / 2)
        return changed

    def to_design(self, pos):
        """A window pixel -> design units (used for the mouse).

        Time:  O(1)
        Space: O(1)
        """
        return ((pos[0] - self.ox) / self.k, (pos[1] - self.oy) / self.k)


V = View()


def to_px(v):
    """A length in design units -> whole pixels.

    Time:  O(1)
    Space: O(1)
    """
    return int(round(v * V.k))


def point_px(pt):
    """A design-space point -> window pixels.

    Time:  O(1)
    Space: O(1)
    """
    return V.ox + to_px(pt[0]), V.oy + to_px(pt[1])


def rect_px(rect):
    """A design-space rect (a Rect or an (x, y, w, h) tuple) -> pixel Rect.

    Edges are rounded rather than sizes, so rects that touch in design space never gain a gap.

    Time:  O(1)
    Space: O(1)
    """
    x, y, w, h = rect
    x0, y0 = V.ox + to_px(x), V.oy + to_px(y)
    return pygame.Rect(x0, y0, V.ox + to_px(x + w) - x0, V.oy + to_px(y + h) - y0)


def mouse_pos():
    """The mouse in design units.

    Time:  O(1)
    Space: O(1)
    """
    return V.to_design(pygame.mouse.get_pos())


def make_fonts():
    """Create the font set at the current pixel scale (system fonts, pygame's default as fallback).

    Time:  O(1)
    Space: O(1)
    """
    def f(size, bold=False):
        """One system font; `size` is in design units.

        Time:  O(1)
        Space: O(1)
        """
        return pygame.font.SysFont(FONT_NAMES, max(8, to_px(size)), bold=bold)
    FONTS.update(huge=f(44, True), big=f(30, True), mid=f(21, True), body=f(20),
                 small=f(17), tiny=f(14), card_big=f(40, True), card_small=f(24, True))


def rescale():
    """Rebuild everything that depends on the pixel scale: fonts and cached sprites.

    Time:  O(1)  (a fixed set of fonts)
    Space: O(1)
    """
    make_fonts()
    for cache in (TILES, DISCS, HEARTS, CARDS, VEILS, LAYERS):
        cache.clear()


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------
def lighten(color, amount=0.35):
    """Mix a colour towards white.

    Time:  O(1)
    Space: O(1)
    """
    return tuple(int(v + (255 - v) * amount) for v in color)


def ease_out(t):
    """Cubic ease-out on t in [0, 1] (fast start, soft landing).

    Time:  O(1)
    Space: O(1)
    """
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t):
    """Smoothstep on t in [0, 1]: gentle start, gentle landing (used for fades, flips and flights).

    Time:  O(1)
    Space: O(1)
    """
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def text(surf, msg, font, color, pos, anchor="topleft", alpha=255):
    """Render a line of text with its `anchor` corner at `pos` (design units); `alpha` 0-255 fades it.

    Time:  O(len(msg))
    Space: O(len(msg))
    """
    img = FONTS[font].render(msg, True, color)
    r = img.get_rect()
    setattr(r, anchor, point_px(pos))
    if alpha >= 255:
        surf.blit(img, r)
    elif alpha > 0:
        img.set_alpha(alpha)
        surf.blit(img, r)
    return r


def corner_tiles(fill, edge, b, r):
    """The four r x r corner pieces of a smooth rounded box, as (top-left, top-right, bottom-left, bottom-right).

    A full 2r x 2r box is drawn SS times too big and averaged down, which smooths the curve.
    `edge` None means no border; `fill` None means a ring with a see-through middle.

    Time:  O((r * SS)^2) the first time these arguments are seen, O(1) after
    Space: O(r^2)
    """
    key = (fill, edge, b, r)
    tiles = TILES.get(key)
    if tiles is None:
        n = 2 * r * SS
        big = pygame.Surface((n, n), pygame.SRCALPHA)
        outer = edge if edge is not None else fill
        big.fill(outer + (0,))                    # invisible, but the right colour: no dark fringe when averaged
        box = big.get_rect()
        pygame.draw.rect(big, outer, box, border_radius=r * SS)
        if edge is not None:
            inner = box.inflate(-2 * b * SS, -2 * b * SS)
            pygame.draw.rect(big, fill if fill is not None else outer + (0,), inner,
                             border_radius=max(0, (r - b) * SS))
        small = pygame.transform.smoothscale(big, (2 * r, 2 * r))
        tl = small.subsurface((0, 0, r, r)).copy()
        tiles = (tl, pygame.transform.flip(tl, True, False), pygame.transform.flip(tl, False, True),
                 pygame.transform.flip(tl, True, True))
        TILES[key] = tiles
    return tiles


def rounded(surf, rect, fill, edge=None, bw=0, radius=12):
    """A rounded box with smooth corners; `rect`, `bw` (border width) and `radius` are in design units.

    The straight parts are plain rects and only the four corners are cached smooth tiles,
    so even a full-width panel costs a handful of fills per frame.

    Time:  O(1)
    Space: O(1)
    """
    box = rect_px(rect)
    x0, y0, x1, y1 = box.left, box.top, box.right, box.bottom
    w, h = box.w, box.h
    b = max(1, to_px(bw)) if (edge is not None and bw) else 0
    if fill is None and not b:
        return
    r = min(to_px(radius), w // 2, h // 2)
    if r < 2:                                     # too small to round: plain rect
        if fill is not None:
            surf.fill(fill, box)
        if b:
            pygame.draw.rect(surf, edge, box, b)
        return
    b = min(b, r)
    if fill is not None:
        surf.fill(fill, (x0 + b, y0 + r, w - 2 * b, h - 2 * r))
        surf.fill(fill, (x0 + r, y0 + b, w - 2 * r, r - b))
        surf.fill(fill, (x0 + r, y1 - r, w - 2 * r, r - b))
    if b:
        surf.fill(edge, (x0, y0 + r, b, h - 2 * r))
        surf.fill(edge, (x1 - b, y0 + r, b, h - 2 * r))
        surf.fill(edge, (x0 + r, y0, w - 2 * r, b))
        surf.fill(edge, (x0 + r, y1 - b, w - 2 * r, b))
    tl, tr, bl, br = corner_tiles(fill, edge if b else None, b, r)
    surf.blit(tl, (x0, y0))
    surf.blit(tr, (x1 - r, y0))
    surf.blit(bl, (x0, y1 - r))
    surf.blit(br, (x1 - r, y1 - r))


def panel(surf, rect, edge=EDGE, fill=PANEL):
    """A rounded panel.

    Time:  O(1)
    Space: O(1)
    """
    rounded(surf, rect, fill, edge, 2, 14)


def disc(surf, center, radius, color):
    """A smooth filled circle; `center` and `radius` are in design units.

    Time:  O((radius * SS)^2) the first time a size is used, O(1) after
    Space: O(radius^2)
    """
    cx, cy = point_px(center)
    r = max(1, to_px(radius))
    key = (color, r)
    spr = DISCS.get(key)
    if spr is None:
        big = pygame.Surface((2 * r * SS, 2 * r * SS), pygame.SRCALPHA)
        big.fill(color + (0,))
        pygame.draw.circle(big, color, (r * SS, r * SS), r * SS)
        spr = DISCS[key] = pygame.transform.smoothscale(big, (2 * r, 2 * r))
    surf.blit(spr, (cx - r, cy - r))


def draw_heart(surf, cx, cy, size, filled):
    """A smooth heart centred on (cx, cy), drawn from the classic heart curve (no font glyph needed).

    Time:  O(size^2) the first time a size is used, O(1) after
    Space: O(size^2)
    """
    col = HEART_ON if filled else HEART_OFF
    side = max(6, to_px(size * 1.1))
    key = (col, side)
    spr = HEARTS.get(key)
    if spr is None:
        n = side * SS
        scale = n * 0.94 / 32
        pts = []
        for i in range(120):
            t = 2 * math.pi * i / 120
            x = 16 * math.sin(t) ** 3
            y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            pts.append((n / 2 + x * scale, n / 2 - (y + 2.5) * scale))
        big = pygame.Surface((n, n), pygame.SRCALPHA)
        big.fill(col + (0,))
        pygame.draw.polygon(big, col, pts)
        spr = HEARTS[key] = pygame.transform.smoothscale(big, (side, side))
    x, y = point_px((cx, cy))
    surf.blit(spr, spr.get_rect(center=(x, y)))


def card_sprite(color, pw, ph, radius, font):
    """One cached card of pw x ph pixels: a coloured face with its letter, or a patterned back.

    `radius` is in design units.

    Time:  O(pw * ph * SS^2) the first time a size is used, O(1) after
    Space: O(pw * ph)
    """
    key = (color, pw, ph, radius, font)
    spr = CARDS.get(key)
    if spr is not None:
        return spr
    u = V.k * SS                                  # big pixels per design unit
    big = pygame.Surface((pw * SS, ph * SS), pygame.SRCALPHA)
    box = big.get_rect()
    rad = int(radius * u)
    if color is None:
        big.fill(BACK_LINE + (0,))
        pygame.draw.rect(big, BACK, box, border_radius=rad)
        inner = box.inflate(-int(10 * u), -int(10 * u))
        if inner.w > 4 and inner.h > 4:
            big.set_clip(inner)
            for off in range(-inner.h, inner.w, max(2, int(10 * u))):
                pygame.draw.line(big, BACK_LINE, (inner.x + off, inner.bottom), (inner.x + off + inner.h, inner.y),
                                 max(1, int(2 * u)))
            big.set_clip(None)
        pygame.draw.rect(big, BACK_LINE, box, max(1, int(2 * u)), border_radius=rad)
    else:
        base = CARD_COL[color]
        big.fill(base + (0,))
        pygame.draw.rect(big, base, box, border_radius=rad)
        m = int(4 * u)
        pygame.draw.rect(big, lighten(base), box.inflate(-2 * m, -2 * m), max(1, int(2 * u)),
                         border_radius=int(max(2, radius - 2) * u))
    spr = pygame.transform.smoothscale(big, (pw, ph))
    if color is not None:
        img = FONTS[font].render(COLOR_LETTERS[color], True, WHITE)
        spr.blit(img, img.get_rect(center=spr.get_rect().center))
    CARDS[key] = spr
    return spr


def draw_card(surf, rect, color=None, outline=None, squash=1.0, grow=1.0, font="card_big"):
    """One card: face-up if `color` is a Color (letter on a colour), else a patterned back.

    `squash` < 1 narrows it horizontally (the flip); `grow` < 1 shrinks it about its centre
    (the pop-in and the flight).  Both resample the cached sprite, so they stay smooth.

    Time:  O(1)
    Space: O(1)
    """
    x, y, w, h = rect
    radius = max(4, min(10, int(w) // 6))
    r = rect_px(rect)
    spr = card_sprite(color, r.w, r.h, radius, font)
    size = (max(2, int(r.w * grow * squash)), max(2, int(r.h * grow)))
    if size != spr.get_size():
        spr = pygame.transform.smoothscale(spr, size)
    surf.blit(spr, spr.get_rect(center=r.center))
    if outline:
        rounded(surf, pygame.Rect(x, y, w, h).inflate(6, 6), None, outline, 3, radius + 3)


def veil(surf, alpha):
    """Darken the whole window by `alpha` (0-255).

    Time:  O(pixels)
    Space: O(pixels) the first time, then reused
    """
    if alpha <= 0:
        return
    size = surf.get_size()
    v = VEILS.get(size)
    if v is None:
        v = VEILS[size] = pygame.Surface(size)
        v.fill((8, 11, 18))
    v.set_alpha(alpha)
    surf.blit(v, (0, 0))


def fade_layer(surf):
    """A cleared, see-through layer the size of `surf`: draw a popup on it, then blit it with set_alpha to fade it.

    Time:  O(pixels)
    Space: O(pixels) the first time a size is seen, then reused
    """
    size = surf.get_size()
    layer = LAYERS.get(size)
    if layer is None:
        layer = LAYERS[size] = pygame.Surface(size, pygame.SRCALPHA)
    layer.fill((0, 0, 0, 0))
    return layer


def row_rects(n, cx, y, w, h, gap):
    """Rects for n cards in a row, centred on x = cx.

    Time:  O(n)
    Space: O(n)
    """
    x0 = cx - (n * w + (n - 1) * gap) / 2
    return [pygame.Rect(round(x0 + i * (w + gap)), y, w, h) for i in range(n)]


def stack_layout(plays):
    """Card rects for every play on the pile, bottom play first (the top play ends up highest).

    Entries are packed closer together when the pile grows tall.

    Time:  O(p)
    Space: O(p)
    """
    cw, ch = 54, 74
    base = STACK_R.bottom - 30
    top_limit = STACK_R.y + 24
    n = len(plays)
    step = 56 if n < 2 else min(56, (base - ch - top_limit) / (n - 1))
    cx = STACK_R.centerx + 20
    out = []
    for i, play in enumerate(plays):
        k = len(play.cards)
        width = k * cw + (k - 1) * 8
        y = int(base - ch - i * step)
        out.append([pygame.Rect(cx - width // 2 + j * (cw + 8), y, cw, ch) for j in range(k)])
    return out


class Flyer:
    """A card sliding from the hand to the pile (a short push animation)."""

    def __init__(self, start, end, t0, dur, until):
        """Remember where the card starts, where it lands, when, and when it may be dropped.

        Time:  O(1)
        Space: O(1)
        """
        self.start, self.end, self.t0, self.dur, self.until = start, end, t0, dur, until

    def pose(self, now):
        """(centre x, centre y, size relative to the landing size) at time `now`, or None before the start.

        Time:  O(1)
        Space: O(1)
        """
        if now < self.t0:
            return None
        e = ease_in_out((now - self.t0) / self.dur)
        s, d = self.start, self.end
        return (s.centerx + (d.centerx - s.centerx) * e,
                s.centery + (d.centery - s.centery) * e,
                (s.w + (d.w - s.w) * e) / d.w)


# --------------------------------------------------------------------------
# The application
# --------------------------------------------------------------------------
class App:
    """Game window state machine: intro -> (human | bot_wait) -> settle -> ... -> reveal -> intro ... -> over."""

    # seconds (all scaled by the speed option)
    INTRO = 1.8                                            # "Round N" toast, fades in and out
    FLIGHT, STAGGER, SETTLE = 0.6, 0.1, 0.9               # card flight, gap between 2 cards, pause after a play
    REVEAL_POP, REVEAL_FLIP, REVEAL_END = 1.0, 1.8, 3.9    # cards pop in / finish flipping / popup gone
    REVEAL_FADE = 0.4                                      # popup fade-in, and fade-out at the end

    def __init__(self, spectator=False, hp=3, seed=None, easy=False, bot_first=False,
                 speed=1.0, now=None):
        """Store the options and start the first match.

        Time:  O(h^2)  (dealing the first round)
        Space: O(h)
        """
        self.spectator, self.hp, self.seed, self.easy = spectator, hp, seed, easy
        self.first = 1 if bot_first else 0
        self.speed = speed
        self.matches = 0
        self.new_match(time.perf_counter() if now is None else now)   # real clock: the intro must play

    def new_match(self, now):
        """Create a fresh Game and bots (a rematch uses the next seed).

        Time:  O(h^2)
        Space: O(h)
        """
        seed = None if self.seed is None else self.seed + self.matches
        names = ("Bot A", "Bot B") if self.spectator else ("You", "Bot")
        self.game = Game(names=names, hp_max=self.hp, seed=seed, first=self.first)
        kw = {"temperature": 2.0, "top_k": 5} if self.easy else {}
        base = seed if seed is not None else int(time.time() * 1000) % 1_000_000
        if self.spectator:
            self.bots, self.humans = [Bot(base, **kw), Bot(base + 1, **kw)], [False, False]
        else:
            self.bots, self.humans = [None, Bot(base, **kw)], [True, False]
        self.matches += 1
        self.shown_hp = [self.hp, self.hp]
        self.selected, self.flyers, self.appear = [], [], {}
        self.result = None
        self.hp_synced = True
        self.set_state("intro", now)

    # ---- small helpers ------------------------------------------------------
    def set_state(self, state, now):
        """Switch state and remember when it began.

        Time:  O(1)
        Space: O(1)
        """
        self.state, self.t0 = state, now

    def dur(self, seconds):
        """Scale a duration by the speed option (--fast makes everything shorter).

        Time:  O(1)
        Space: O(1)
        """
        return seconds * self.speed

    def hand_rects(self):
        """Rects of player 0's hand (bottom row), lifted when a card is selected.

        Time:  O(h)
        Space: O(h)
        """
        n = len(self.game.players[0].hand)
        rects = row_rects(n, CX, ME_Y, ME_CW, ME_CH, ME_GAP)
        return [r.move(0, -16) if i in self.selected else r for i, r in enumerate(rects)]

    def bot_rects(self):
        """Rects of player 1's hand (top row).

        Time:  O(h)
        Space: O(h)
        """
        return row_rects(len(self.game.players[1].hand), CX, BOT_Y, BOT_CW, BOT_CH, BOT_GAP)

    def can_play(self):
        """True when the human has picked 1-2 cards and is allowed to play them.

        Time:  O(1)
        Space: O(1)
        """
        return (self.state == "human" and 1 <= len(self.selected) <= 2
                and not self.game.must_call(0))

    def can_call(self):
        """True when the human may call LIE right now.

        Time:  O(1)
        Space: O(1)
        """
        return self.state == "human" and not self.game.table.is_empty()

    # ---- turn flow ----------------------------------------------------------
    def begin_turn(self, now):
        """Hand control to the human, or start the bot's thinking pause.

        Time:  O(1)
        Space: O(1)
        """
        self.selected = []
        if self.humans[self.game.current_index]:
            self.set_state("human", now)
        else:
            self.set_state("bot_wait", now)

    def start_flight(self, idx, starts, now):
        """After a play: slide card backs from `starts` to the new top of the pile.

        Time:  O(p)
        Space: O(k)
        """
        g = self.game
        ends = stack_layout(g.table.to_list())[-1]
        gap, fly = self.dur(self.STAGGER), self.dur(self.FLIGHT)
        land = now + gap * (len(ends) - 1) + fly            # the last card touches down
        for j, (s, e) in enumerate(zip(starts, ends)):
            self.flyers.append(Flyer(s, e, now + gap * j, fly, land + 0.03))
        self.appear[len(g.table) - 1] = land
        self.set_state("settle", now)

    def do_play(self, idx, cards, starts, now):
        """Apply a play to the engine and start the flight animation.

        Time:  O(h + p)
        Space: O(k)
        """
        self.game.play(cards)
        self.start_flight(idx, starts, now)

    def do_call(self, idx, now):
        """Apply a call to the engine (pops the stack) and start the reveal sequence.

        Time:  O(k)
        Space: O(1)
        """
        self.result = self.game.call()
        self.hp_synced = False
        self.set_state("reveal", now)

    def bot_act(self, now):
        """Let the current bot decide and act.

        Time:  O(h + c + K log c)
        Space: O(c)
        """
        g = self.game
        idx = g.current_index
        decision = self.bots[idx].decide(g.observe(idx))
        if decision.action == "call":
            self.do_call(idx, now)
        else:
            src = pygame.Rect(CX - BOT_CW // 2, BOT_Y, BOT_CW, BOT_CH) if idx == 1 else \
                pygame.Rect(CX - ME_CW // 2, ME_Y, ME_CW, ME_CH)
            starts = [src.move(j * 14, 0) for j in range(len(decision.cards))]
            self.do_play(idx, decision.cards, starts, now)

    def human_play(self, now):
        """Play the selected cards.

        Time:  O(h + p)
        Space: O(h)
        """
        if not self.can_play():
            return
        hand = self.game.players[0].hand.to_list()
        rects = self.hand_rects()
        cards = tuple(hand[i] for i in self.selected)
        starts = [rects[i] for i in self.selected]
        self.do_play(0, cards, starts, now)

    def human_call(self, now):
        """Call LIE on the bot's last play.

        Time:  O(k)
        Space: O(1)
        """
        if self.can_call():
            self.do_call(0, now)

    def finish_round(self, now):
        """After the reveal: end the match, or deal the next round.

        Time:  O(h^2)
        Space: O(h)
        """
        g = self.game
        self.shown_hp = [p.hp for p in g.players]
        self.hp_synced = True
        if g.game_over:
            self.set_state("over", now)
            return
        g.next_round()
        self.selected, self.flyers, self.appear = [], [], {}
        self.set_state("intro", now)

    def update(self, now):
        """Advance timers; called once per frame with the current time in seconds.

        Time:  O(1)
        Space: O(1)
        """
        el = now - self.t0
        if self.state == "intro" and el > self.dur(self.INTRO):
            self.begin_turn(now)
        elif self.state == "bot_wait" and el > self.dur(0.9):
            self.bot_act(now)
        elif self.state == "settle" and el > self.dur(self.SETTLE):
            self.begin_turn(now)
        elif self.state == "reveal":
            if not self.hp_synced and el > self.dur(self.REVEAL_FLIP):
                self.shown_hp = [p.hp for p in self.game.players]
                self.hp_synced = True
            if el > self.dur(self.REVEAL_END):
                self.finish_round(now)

    # ---- input --------------------------------------------------------------
    def skip_reveal(self, now):
        """Jump to the start of the reveal's fade-out (so it still ends smoothly); ignores stray clicks.

        Time:  O(1)
        Space: O(1)
        """
        fade_start = self.dur(self.REVEAL_END - self.REVEAL_FADE)
        if self.dur(self.REVEAL_FADE) < now - self.t0 < fade_start:
            self.t0 = now - fade_start

    def skip_intro(self, now):
        """Jump to the start of the round toast's fade-out (only once it has fully faded in).

        Time:  O(1)
        Space: O(1)
        """
        total = self.dur(self.INTRO)
        if 0.3 * total < now - self.t0 < 0.72 * total:
            self.t0 = now - 0.72 * total

    def toggle_pick(self, i):
        """Select or unselect card i of the hand (at most two).

        Time:  O(1)
        Space: O(1)
        """
        if i in self.selected:
            self.selected.remove(i)
        elif len(self.selected) < 2:
            self.selected.append(i)

    def pick_color(self, color):
        """Keyboard shortcut: select the first unselected card of that colour.

        Time:  O(h)
        Space: O(h)
        """
        if len(self.selected) >= 2:
            return
        for i, card in enumerate(self.game.players[0].hand):
            if card == color and i not in self.selected:
                self.selected.append(i)
                return

    def handle_event(self, ev, now):
        """React to one pygame event (keyboard or mouse).

        Time:  O(h)
        Space: O(h)
        """
        if ev.type == pygame.KEYDOWN:
            ch = ev.unicode.lower() if ev.unicode else ""
            if self.state == "over" and ch == "r":
                self.new_match(now)
            elif self.state == "reveal" and ev.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.skip_reveal(now)
            elif self.state == "intro" and ev.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.skip_intro(now)
            elif self.state == "human":
                if ch in ("r", "g", "b"):
                    self.pick_color(Color("rgb".index(ch)))
                elif ch == "c":
                    self.human_call(now)
                elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if self.game.must_call(0):
                        self.human_call(now)
                    else:
                        self.human_play(now)
                elif ev.key in (pygame.K_BACKSPACE, pygame.K_ESCAPE):
                    self.selected = []
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = V.to_design(ev.pos)
            if self.state == "reveal":
                self.skip_reveal(now)
            elif self.state == "intro":
                self.skip_intro(now)
            elif self.state == "human":
                if BTN_PLAY.collidepoint(pos):
                    self.human_play(now)
                elif BTN_CALL.collidepoint(pos):
                    self.human_call(now)
                else:
                    for i, r in enumerate(self.hand_rects()):
                        if r.collidepoint(pos) and not self.game.must_call(0):
                            self.toggle_pick(i)
                            break

    # ---- drawing: zones -----------------------------------------------------
    def draw_header(self, s):
        """Title, the target colour chip and the round number.

        Time:  O(1)
        Space: O(1)
        """
        g = self.game
        text(s, "Liar's Cards", "big", TEXT, (24, 10))
        chip = pygame.Rect(0, 0, 250, 40)
        chip.center = (CX, 28)
        rounded(s, chip, CARD_COL[g.target], GOLD, 3, 20)
        text(s, "Target: %s" % COLOR_NAMES[g.target].title(), "mid", WHITE, chip.center, "center")
        text(s, "Round %d" % g.round_no, "mid", MUTED, (W - 24, 17), "topright")

    def draw_plate(self, s, rect, idx, subtitle):
        """Name plate: name, hearts, card count; a gold bar marks whose turn it is.

        Time:  O(hp_max)
        Space: O(1)
        """
        g = self.game
        player = g.players[idx]
        panel(s, rect)
        turn = self.state in ("human", "bot_wait") and g.current_index == idx
        if turn:
            rounded(s, pygame.Rect(rect.x, rect.y + 10, 5, rect.h - 20), GOLD, radius=3)
        text(s, player.name, "mid", TEXT, (rect.x + 20, rect.y + 10))
        text(s, subtitle, "small", MUTED, (rect.right - 16, rect.y + 14), "topright")
        for k in range(g.hp_max):
            draw_heart(s, rect.x + 34 + k * 34, rect.y + 56, 28, k < self.shown_hp[idx])

    def draw_hand(self, s, idx, rects, face_up, gold_target=False, mine=False):
        """Draw a hand as a plain row of cards.

        Time:  O(h)
        Space: O(h)
        """
        g = self.game
        cards = g.players[idx].hand.to_list()
        mouse = mouse_pos()
        for i, (card, r) in enumerate(zip(cards, rects)):
            hover = mine and self.state == "human" and r.collidepoint(mouse) and not g.must_call(0)
            sel = mine and i in self.selected
            draw_card(s, r, card if face_up else None, outline=GOLD if sel else (TEXT if hover else None),
                      font="card_big" if mine else "card_small")
            if gold_target and card == g.target:
                disc(s, (r.centerx, r.bottom + 9), 4, GOLD)

    def draw_bot_zone(self, s):
        """Top row: the opponent's name plate and hand (face-down unless two bots are playing).

        Time:  O(h)
        Space: O(h)
        """
        n = len(self.game.players[1].hand)
        self.draw_plate(s, BOT_PLATE, 1, "%d cards" % n)
        self.draw_hand(s, 1, self.bot_rects(), face_up=self.spectator)

    def draw_me_zone(self, s):
        """Bottom row: your name plate and your hand.

        Time:  O(h)
        Space: O(h)
        """
        n = len(self.game.players[0].hand)
        self.draw_plate(s, ME_PLATE, 0, "%d cards" % n)
        self.draw_hand(s, 0, self.hand_rects(), face_up=True, gold_target=True, mine=True)

    def draw_stack(self, s, now):
        """The pile on the felt: bottom play at the base, top play highest, each tagged with who played it.

        Time:  O(p)
        Space: O(p)
        """
        g = self.game
        panel(s, STACK_R, edge=CARD_COL[g.target], fill=FELT)
        plays = g.table.to_list()
        for i, (play, rects) in enumerate(zip(plays, stack_layout(plays))):
            if self.appear.get(i, 0) > now:
                continue
            for r in rects:
                draw_card(s, r)
            tag = pygame.Rect(0, 0, 66, 24)
            tag.midright = (rects[0].x - 24, rects[0].centery)
            rounded(s, tag, EDGE, radius=12)
            text(s, g.players[play.player].name, "tiny", TEXT, tag.center, "center")

    def draw_actions(self, s, now):
        """One line of prompt plus the Play / Call buttons.

        Time:  O(1)
        Space: O(1)
        """
        g = self.game
        if self.state == "human":
            if g.must_call(0):
                msg = "No cards left. Call LIE."
            elif g.table.is_empty():
                msg = "Pick 1 or 2 cards to play."
            else:
                msg = "Pick 1 or 2 cards, or call LIE."
        elif self.state == "bot_wait":
            msg = "%s is thinking%s" % (g.players[g.current_index].name, "." * (1 + int(now * 3) % 3))
        else:
            msg = ""
        text(s, msg, "body", TEXT, (24, BTN_PLAY.centery), "midleft")
        if self.spectator:
            return
        forced = g.must_call(0) and self.state == "human"
        n = len(self.selected)
        self.draw_button(s, BTN_PLAY, "Play %d card%s" % (n, "" if n == 1 else "s") if n else "Play selected",
                         self.can_play(), GOLD)
        pulse = 0.5 + 0.5 * math.sin(now * 6)
        self.draw_button(s, BTN_CALL, "Call LIE", self.can_call(), BAD if not forced else lighten(BAD, 0.4 * pulse))

    def draw_button(self, s, rect, label, enabled, color):
        """A big action button (greyed out when disabled).

        Time:  O(1)
        Space: O(1)
        """
        hover = enabled and rect.collidepoint(mouse_pos())
        fill = (lighten(color, 0.15) if hover else color) if enabled else EDGE
        rounded(s, rect, fill, radius=12)
        text(s, label, "mid", INK if enabled else MUTED, rect.center, "center")

    # ---- drawing: overlays --------------------------------------------------
    def draw_intro(self, s, now):
        """Round toast shown while a new round is dealt: the veil and each line fade in one after another, then out.

        Time:  O(1)
        Space: O(1)
        """
        g = self.game
        u = (now - self.t0) / self.dur(self.INTRO)               # 0 -> 1 over the toast
        fade_out = 1.0 - ease_in_out((u - 0.72) / 0.28)
        veil(s, int(170 * min(ease_in_out(u / 0.22), fade_out)))
        opener = g.players[g.current_index].name
        lines = (("Round %d" % g.round_no, "huge", TEXT, 300),
                 ("Target: %s" % COLOR_NAMES[g.target].title(), "mid", GOLD, 352),
                 ("%s open%s." % (opener, "" if self.humans[g.current_index] else "s"), "body", MUTED, 392))
        for i, (msg, font, color, y) in enumerate(lines):
            f_in = ease_in_out((u - 0.07 * i) / 0.22)             # each line starts a little after the last
            text(s, msg, font, color, (W // 2, y + 14 * (1.0 - f_in)), "center",
                 alpha=int(255 * min(f_in, fade_out)))

    def draw_reveal(self, s, now):
        """The call sequence: the popup fades in, the popped play appears face-down, flips, verdict fades in, popup fades out.

        Time:  O(k)
        Space: O(k)
        """
        g, res = self.game, self.result
        el = now - self.t0
        pop_t, flip_t = self.dur(self.REVEAL_POP), self.dur(self.REVEAL_FLIP)
        fade = self.dur(self.REVEAL_FADE)
        k = min(ease_in_out(el / fade),
                1.0 - ease_in_out((el - (self.dur(self.REVEAL_END) - fade)) / fade))   # popup opacity
        veil(s, int(190 * k))
        if k <= 0:
            return
        t = s if k >= 0.999 else fade_layer(s)         # while fading, draw on a layer and blend it in one go
        box = pygame.Rect(0, 0, 640, 330)
        box.center = (W // 2, H // 2 - 10)
        panel(t, box, edge=GOLD)
        text(t, "%s called LIE!" % g.players[res.caller].name, "big", TEXT, (box.centerx, box.y + 42), "center")
        n = len(res.play.cards)
        cw, ch = 96, 134
        grow = ease_out(el / (pop_t * 0.7))
        flip = ease_in_out((el - pop_t) / max(0.01, flip_t - pop_t))
        squash = max(0.05, abs(math.cos(math.pi * flip)))
        for j in range(n):
            r = pygame.Rect(0, 0, cw, ch)
            r.center = (box.centerx + (j - (n - 1) / 2) * (cw + 20), box.y + 138)
            draw_card(t, r, res.play.cards[j] if flip >= 0.5 else None, squash=squash,
                      grow=max(0.0, min(1.0, 0.55 + 0.45 * grow)))
        if el > flip_t:
            lie = res.was_lie
            verb = "lose" if self.humans[res.loser] else "loses"
            v1 = ease_in_out((el - flip_t) / self.dur(0.35))
            v2 = ease_in_out((el - flip_t - self.dur(0.2)) / self.dur(0.35))
            text(t, "It was a lie!" if lie else "It was the truth!", "huge", BAD if lie else GOOD,
                 (box.centerx, box.y + 248 + 10 * (1.0 - v1)), "center", alpha=int(255 * v1))
            text(t, "%s %s a heart." % (g.players[res.loser].name, verb), "mid", TEXT,
                 (box.centerx, box.y + 294 + 10 * (1.0 - v2)), "center", alpha=int(255 * v2))
        if t is not s:
            t.set_alpha(int(255 * k))
            s.blit(t, (0, 0))

    def draw_over(self, s, now):
        """Game-over screen (fades in).

        Time:  O(1)
        Space: O(1)
        """
        g = self.game
        k = ease_in_out((now - self.t0) / self.dur(0.6))
        veil(s, int(215 * k))
        if k <= 0:
            return
        if self.spectator:
            head, col = "%s wins the match" % g.players[g.winner].name, GOLD
        elif g.winner == 0:
            head, col = "You win!", GOOD
        else:
            head, col = "The Bot wins this time", BAD
        text(s, head, "huge", col, (W // 2, 300 + 12 * (1.0 - k)), "center", alpha=int(255 * k))
        text(s, "Press R for a rematch", "body", MUTED, (W // 2, 352 + 12 * (1.0 - k)), "center", alpha=int(255 * k))

    def draw_flyers(self, s, now):
        """Cards in flight towards the pile.

        Time:  O(k)
        Space: O(k)
        """
        self.flyers = [f for f in self.flyers if now < f.until]
        for f in self.flyers:
            pose = f.pose(now)
            if pose is not None:
                cx, cy, grow = pose
                w, h = f.end.w, f.end.h
                draw_card(s, (cx - w / 2, cy - h / 2, w, h), grow=grow)

    def draw(self, s, now):
        """Draw one complete frame.

        Time:  O(h + p)
        Space: O(h + p)
        """
        s.fill(BG)
        self.draw_header(s)
        self.draw_bot_zone(s)
        self.draw_stack(s, now)
        self.draw_actions(s, now)
        self.draw_me_zone(s)
        self.draw_flyers(s, now)
        if self.state == "intro":
            self.draw_intro(s, now)
        elif self.state == "reveal":
            self.draw_reveal(s, now)
        elif self.state == "over":
            self.draw_over(s, now)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def build_parser():
    """Command-line options (same names as the CLI where they exist).

    Time:  O(1)
    Space: O(1)
    """
    ap = argparse.ArgumentParser(description="Liar's Cards - pygame front-end.")
    ap.add_argument("--bots", action="store_true", help="bot vs bot: just watch")
    ap.add_argument("--easy", action="store_true", help="a more random, easier-to-beat bot")
    ap.add_argument("--hp", type=int, default=3, help="hearts per player (default 3)")
    ap.add_argument("--seed", type=int, default=None, help="fix the shuffle for a repeatable demo")
    ap.add_argument("--bot-first", action="store_true", help="the bot opens round 1")
    ap.add_argument("--fast", action="store_true", help="shorter pauses and animations")
    ap.add_argument("--fullscreen", action="store_true", help="start fullscreen (F11 toggles)")
    return ap


def enable_dpi_awareness():
    """Windows only: say we draw real pixels, so the OS does not stretch (and blur) the window.

    Time:  O(1)
    Space: O(1)
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def open_window(fullscreen):
    """Open a resizable window that fits the desktop (or the whole desktop when `fullscreen`).

    Time:  O(1)
    Space: O(1)
    """
    if fullscreen:
        try:
            return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        except pygame.error:
            pass
    info = pygame.display.Info()
    k = 1.0
    if info.current_w > 0 and info.current_h > 0:
        k = max(0.75, min(2.0, 0.92 * info.current_w / W, 0.85 * info.current_h / H))
    k = int(k * 32) / 32
    return pygame.display.set_mode((int(W * k), int(H * k)), pygame.RESIZABLE)


def main(argv=None):
    """Open the window and run the event loop until it is closed.

    Time:  O(F * (h + p))  (F frames drawn)
    Space: O(h + p)
    """
    args = build_parser().parse_args(argv)
    enable_dpi_awareness()
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    pygame.init()
    pygame.display.set_caption("Liar's Cards")
    open_window(args.fullscreen)
    V.fit(pygame.display.get_surface().get_size())
    rescale()
    app = App(spectator=args.bots, hp=args.hp, seed=args.seed, easy=args.easy, bot_first=args.bot_first,
              speed=0.45 if args.fast else 1.0, now=time.perf_counter())
    clock = pygame.time.Clock()
    running = True
    while running:
        now = time.perf_counter()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                pygame.display.toggle_fullscreen()
            else:
                app.handle_event(ev, now)
        screen = pygame.display.get_surface()      # fetched every frame: resizing / fullscreen can replace it
        if V.fit(screen.get_size()):
            rescale()
        app.update(now)
        app.draw(screen, now)
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()


if __name__ == "__main__":
    main()