"""Deterministic non-verbal Logical Reasoning items.

Every generator builds the puzzle *and* its answer from the same random state, so the key is
correct by construction (no LLM involved). Each returns an `LRItem`; figures are PNGs written to
`<assets>/figs/`. Paths inside the item are relative to `assets`.

    item = GENERATORS["mirror_image"](rng=random.Random(7), assets=Path("out"), tag="q081")
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

LETTERS = "ABCD"
DPI = 200


@dataclass
class LRItem:
    stem: str
    options: list[str]                       # option texts ("" when the option is a figure)
    answer: str                              # "A".."D"
    solution: str
    stem_figure: str | None = None           # relative path
    stem_width: int = 60
    option_figures: list[str] | None = None  # 4 relative paths
    option_width: int = 20
    subtopic: str = ""
    params: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- helpers

def _canvas(w=2.0, h=2.0):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.03, facecolor="white")
    plt.close(fig)


def _trim(img: Image.Image, pad: int = 6) -> Image.Image:
    g = ImageOps.invert(img.convert("L"))
    box = g.getbbox()
    if not box:
        return img
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))


def _boxed(img: Image.Image, size: int | None = None, border: int = 3) -> Image.Image:
    """Centre `img` in a white square with a thin black frame (the corpus answer-figure look)."""
    s = size or int(max(img.width, img.height) * 1.15)
    sq = Image.new("RGB", (s, s), "white")
    sq.paste(img, ((s - img.width) // 2, (s - img.height) // 2))
    framed = ImageOps.expand(sq.crop((border, border, s - border, s - border)), border=border, fill="black")
    return framed


def _shuffle_options(rng: random.Random, correct, distractors: list):
    opts = [correct, *distractors[:3]]
    order = list(range(4))
    rng.shuffle(order)
    shuffled = [opts[i] for i in order]
    return shuffled, LETTERS[order.index(0)]


def _render_text(text: str, fontsize=30) -> Image.Image:
    fig = plt.figure(figsize=(len(text) * 0.42 + 0.4, 0.8))
    fig.text(0.5, 0.5, text, ha="center", va="center", fontsize=fontsize, family="DejaVu Sans",
             fontweight="bold")
    tmp = fig.canvas
    tmp.draw()
    arr = np.asarray(tmp.buffer_rgba())[..., :3]
    plt.close(fig)
    return _trim(Image.fromarray(arr))


def _render_poly(cells: list[tuple[int, int]], dot: tuple[int, int] | None = None, cell=40) -> Image.Image:
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    w, h = max(xs) + 1, max(ys) + 1
    fig, ax = _canvas(w, h)
    for (x, y) in cells:
        ax.add_patch(Rectangle((x, h - 1 - y), 1, 1, facecolor="#222" if (x, y) != dot else "white",
                               edgecolor="black", lw=1.6))
    if dot:
        ax.add_patch(Circle((dot[0] + .5, h - 1 - dot[1] + .5), .25, color="black"))
    fig.canvas.draw()
    arr = np.asarray(fig.canvas.buffer_rgba())[..., :3]
    plt.close(fig)
    return _trim(Image.fromarray(arr))


def _write(img: Image.Image, assets: Path, name: str) -> str:
    rel = f"figs/{name}.png"
    p = assets / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p)
    return rel


def _hstack(imgs: list[Image.Image], gap=30, labels: list[str] | None = None) -> Image.Image:
    h = max(i.height for i in imgs)
    lab_h = 40 if labels else 0
    w = sum(i.width for i in imgs) + gap * (len(imgs) - 1)
    out = Image.new("RGB", (w, h + lab_h), "white")
    x = 0
    for k, im in enumerate(imgs):
        out.paste(im, (x, (h - im.height) // 2))
        if labels:
            fig = plt.figure(figsize=(1, .3), dpi=200)
            fig.text(.5, .5, labels[k], ha="center", va="center", fontsize=13, family="serif")
            fig.canvas.draw()
            lab = _trim(Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[..., :3]), 2)
            plt.close(fig)
            out.paste(lab, (x + (im.width - lab.width) // 2, h + 8))
        x += im.width + gap
    return out


# ------------------------------------------------------------------- polyomino shapes

def _norm(cells):
    mx, my = min(c[0] for c in cells), min(c[1] for c in cells)
    return tuple(sorted((x - mx, y - my) for x, y in cells))


def _rot(cells):  # 90° clockwise
    return _norm([(-y, x) for x, y in cells])


def _flip(cells):
    return _norm([(-x, y) for x, y in cells])


def _random_polyomino(rng: random.Random, n: int) -> tuple:
    while True:
        cells = {(0, 0)}
        while len(cells) < n:
            x, y = rng.choice(sorted(cells))
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
            cells.add((x + dx, y + dy))
        shape = _norm(cells)
        rots = {shape}
        s = shape
        for _ in range(3):
            s = _rot(s)
            rots.add(s)
        if _flip(shape) not in rots and len(rots) == 4:  # chiral, no rotational symmetry
            return shape


# ------------------------------------------------------------------------- generators

ASYM = "FGJKLNPQRSZ2345679"


def _mirror_like(rng, assets, tag, water: bool) -> LRItem:
    use_text = rng.random() < 0.5
    if use_text:
        s = "".join(rng.sample(ASYM, rng.randint(4, 6)))
        base = _render_text(s)
        rev = _render_text(s[::-1])  # order reversed, glyphs unflipped: the classic trap
    else:
        cells = _random_polyomino(rng, rng.randint(5, 7))
        dot = rng.choice(cells)
        base = _render_poly(list(cells), dot)
        rev = base.rotate(90, expand=True, fillcolor="white")
    flipH = base.transpose(Image.FLIP_LEFT_RIGHT)
    flipV = base.transpose(Image.FLIP_TOP_BOTTOM)
    rot = base.transpose(Image.ROTATE_180)
    correct, wrong = (flipV, [flipH, rot, rev]) if water else (flipH, [flipV, rot, rev])
    imgs, ans = _shuffle_options(rng, correct, wrong)
    size = int(max(max(i.width, i.height) for i in imgs) * 1.15)
    opt_paths = [_write(_boxed(im, size), assets, f"{tag}_opt{L}") for L, im in zip(LETTERS, imgs)]
    # stem: the figure with the mirror line
    pad = 40
    W, H = base.width + pad * 3, base.height + pad * 2
    stem = Image.new("RGB", (W, H), "white")
    stem.paste(base, (pad, pad))
    arr = np.asarray(stem).copy()
    if water:
        arr[H - 12:H - 8, 10:W - 10] = 0
    else:
        arr[10:H - 10, W - 22:W - 18] = 0
    stem_img = Image.fromarray(arr)
    rel = _write(stem_img, assets, f"{tag}_stem")
    kind = "water image" if water else "mirror image"
    where = "below the figure (along the line shown)" if water else "to the right of the figure (along the line shown)"
    return LRItem(
        stem=f"Choose the correct {kind} of the given figure, if the {'water surface' if water else 'mirror'} "
             f"is placed {where}.",
        options=["", "", "", ""], answer=ans,
        solution=(f"In a {kind} the figure is inverted {'top to bottom' if water else 'left to right'}; "
                  f"{'left and right' if water else 'top and bottom'} remain unchanged. Only option ({ans}) "
                  f"shows this."),
        stem_figure=rel, stem_width=min(70, 18 + 8 * (len(s) if use_text else 3)), option_figures=opt_paths,
        option_width=20 if not use_text else 22, subtopic="Water image" if water else "Mirror image",
        params={"mode": "text" if use_text else "shape"})


def mirror_image(rng, assets, tag) -> LRItem:
    return _mirror_like(rng, assets, tag, water=False)


def water_image(rng, assets, tag) -> LRItem:
    return _mirror_like(rng, assets, tag, water=True)


def odd_figure(rng, assets, tag) -> LRItem:
    cells = _random_polyomino(rng, rng.randint(5, 7))
    variants = []
    s = cells
    for _ in range(4):
        variants.append(s)
        s = _rot(s)
    same = rng.sample(variants, 3)
    odd = rng.choice(variants)
    odd = _flip(odd)
    imgs = [_render_poly(list(v)) for v in same]
    odd_img = _render_poly(list(odd))
    shuffled, ans = _shuffle_options(rng, odd_img, imgs)
    size = int(max(max(i.width, i.height) for i in shuffled) * 1.2)
    paths = [_write(_boxed(im, size), assets, f"{tag}_opt{L}") for L, im in zip(LETTERS, shuffled)]
    return LRItem(
        stem="Select the figure which is different from the other three.",
        options=["", "", "", ""], answer=ans,
        solution=f"Three of the figures are rotations of the same figure; figure ({ans}) is its mirror image, "
                 f"which cannot be obtained by rotation.",
        option_figures=paths, option_width=18, subtopic="Odd figure out")


def rotation_series(rng, assets, tag) -> LRItem:
    step = rng.choice([45, 90, 135])
    direction = rng.choice([1, -1])  # 1 = clockwise
    a0 = rng.choice(range(0, 360, 45))
    cstep = rng.choice([1, 2, 3]) if step != 90 else rng.choice([1, 3])
    c0 = rng.randrange(4)
    corners = [(0.35, 1.65), (1.65, 1.65), (1.65, 0.35), (0.35, 0.35)]  # clockwise from top-left
    head = rng.choice(["arrow", "T"])

    def frame(k: int, ang_off=0, corner_off=0) -> Image.Image:
        fig, ax = _canvas(2, 2)
        ax.add_patch(Rectangle((0.03, 0.03), 1.94, 1.94, fill=False, lw=2.2))
        ang = math.radians(90 - (a0 + direction * step * k + ang_off))
        dx, dy = 0.62 * math.cos(ang), 0.62 * math.sin(ang)
        if head == "arrow":
            ax.add_patch(FancyArrowPatch((1 - dx, 1 - dy), (1 + dx, 1 + dy), arrowstyle="-|>",
                                         mutation_scale=22, lw=2.4, color="black"))
        else:
            ax.plot([1 - dx, 1 + dx], [1 - dy, 1 + dy], lw=2.6, color="black")
            px, py = -dy * 0.45, dx * 0.45
            ax.plot([1 + dx - px, 1 + dx + px], [1 + dy - py, 1 + dy + py], lw=2.6, color="black")
        cx, cy = corners[(c0 + cstep * k + corner_off) % 4]
        ax.add_patch(Circle((cx, cy), 0.17, color="black"))
        fig.canvas.draw()
        arr = np.asarray(fig.canvas.buffer_rgba())[..., :3]
        plt.close(fig)
        return _trim(Image.fromarray(arr), 2)

    probs = [frame(k) for k in range(4)]
    correct = frame(4)
    wrong = [frame(4, ang_off=direction * step), frame(4, corner_off=1), frame(4, ang_off=-direction * step,
                                                                                 corner_off=2)]
    shuffled, ans = _shuffle_options(rng, correct, wrong)
    stem_rel = _write(_hstack(probs, gap=0), assets, f"{tag}_stem")
    paths = [_write(im, assets, f"{tag}_opt{L}") for L, im in zip(LETTERS, shuffled)]
    turn = "clockwise" if direction == 1 else "anticlockwise"
    return LRItem(
        stem="Select a figure from the options which will continue the same series as established by the "
             "four problem figures.",
        options=["", "", "", ""], answer=ans,
        solution=(f"The {'arrow' if head == 'arrow' else 'T-shaped line'} rotates {step}° {turn} at each step, "
                  f"and the black dot moves {cstep} corner(s) clockwise at each step. Hence the next figure is "
                  f"({ans})."),
        stem_figure=stem_rel, stem_width=80, option_figures=paths, option_width=19, subtopic="Figure series",
        params={"step": step, "dir": direction, "cstep": cstep})


def paper_punch(rng, assets, tag) -> LRItem:
    """Square paper on a 4x4 grid of hole sites; 1–2 folds along the mid-lines; punch; unfold."""
    folds = rng.choice([["V"], ["H"], ["V", "H"], ["H", "V"]])
    # region left after folding: V folds right half onto left (keep x<2); H folds top onto bottom (keep y<2)
    xs = range(2) if "V" in folds else range(4)
    ys = range(2) if "H" in folds else range(4)
    sites = [(x, y) for x in xs for y in ys]
    holes = rng.sample(sites, rng.choice([1, 2]))

    def unfold(hs, which):
        out = set(hs)
        for f in reversed(which):
            out |= {(3 - x, y) for x, y in out} if f == "V" else {(x, 3 - y) for x, y in out}
        return frozenset(out)

    correct = unfold(holes, folds)
    cands = []
    if len(folds) == 2:
        cands += [unfold(holes, folds[:1]), unfold(holes, folds[1:])]
    cands.append(frozenset((3 - x, 3 - y) for x, y in correct) | frozenset(holes))  # point reflection trap
    cands.append(frozenset(holes))
    other = rng.choice([s for s in itertools.product(range(4), range(4)) if s not in correct])
    cands.append(correct | {other})
    cands.append(frozenset((y, x) for x, y in correct))
    wrong = []
    for c in cands:
        if c != correct and c not in wrong and len(c) > 0:
            wrong.append(c)
    while len(wrong) < 3:
        extra = frozenset(rng.sample(list(itertools.product(range(4), range(4))), len(correct)))
        if extra != correct and extra not in wrong:
            wrong.append(extra)

    def sheet(hs, w=4, h=4, fold_line=None, arrow=None) -> Image.Image:
        fig, ax = _canvas(w + .2, h + .2)
        ax.add_patch(Rectangle((.1, .1), w, h, fill=False, lw=2))
        for x, y in hs:
            ax.add_patch(Circle((.1 + x + .5, .1 + y + .5), .2, facecolor="white", edgecolor="black", lw=1.8))
        if fold_line == "V":
            ax.plot([.1 + w / 2] * 2, [.1, .1 + h], ls="--", lw=1.6, color="black")
        if fold_line == "H":
            ax.plot([.1, .1 + w], [.1 + h / 2] * 2, ls="--", lw=1.6, color="black")
        if arrow == "V":
            ax.add_patch(FancyArrowPatch((.1 + w * .82, .1 + h * .5), (.1 + w * .18, .1 + h * .5),
                                         connectionstyle="arc3,rad=.45", arrowstyle="-|>", mutation_scale=16, lw=1.6))
        if arrow == "H":
            ax.add_patch(FancyArrowPatch((.1 + w * .5, .1 + h * .82), (.1 + w * .5, .1 + h * .18),
                                         connectionstyle="arc3,rad=-.45", arrowstyle="-|>", mutation_scale=16, lw=1.6))
        fig.canvas.draw()
        arr = np.asarray(fig.canvas.buffer_rgba())[..., :3]
        plt.close(fig)
        return _trim(Image.fromarray(arr), 2)

    panels = [sheet([], 4, 4, folds[0], folds[0])]
    w, h = (2, 4) if folds[0] == "V" else (4, 2)
    if len(folds) == 2:
        panels.append(sheet([], w, h, folds[1], folds[1]))
        w, h = 2, 2
    panels.append(sheet(holes, w, h))
    stem_rel = _write(_hstack(panels, gap=40, labels=[f"({i + 1})" for i in range(len(panels))]),
                      assets, f"{tag}_stem")
    imgs, ans = _shuffle_options(rng, sheet(correct), [sheet(c) for c in wrong[:3]])
    paths = [_write(im, assets, f"{tag}_opt{L}") for L, im in zip(LETTERS, imgs)]
    n = len(correct)
    return LRItem(
        stem="A square sheet of paper is folded along the dotted line(s) in the direction shown and then "
             "punched as shown in the last figure. How will the sheet look when it is unfolded?",
        options=["", "", "", ""], answer=ans,
        solution=(f"Unfolding reflects each punched hole across every fold line ({len(folds)} fold"
                  f"{'s' if len(folds) > 1 else ''}), giving {n} holes placed symmetrically, as in option ({ans})."),
        stem_figure=stem_rel, stem_width=75 if len(folds) == 2 else 55, option_figures=paths, option_width=19,
        subtopic="Paper folding and punching", params={"folds": folds, "holes": holes})


# --- cube nets: roll a die over the net; the side that lands on each cell is that face.
NETS = [
    [(1, 0), (0, 1), (1, 1), (2, 1), (3, 1), (1, 2)],   # cross / T
    [(0, 0), (0, 1), (1, 1), (2, 1), (3, 1), (3, 2)],   # 1-4-1 Z
    [(0, 0), (0, 1), (1, 1), (2, 1), (3, 1), (2, 2)],
    [(0, 0), (1, 0), (1, 1), (2, 1), (3, 1), (3, 2)],   # 2-3-1
    [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (3, 2)],   # staircase
    [(0, 0), (1, 0), (2, 0), (2, 1), (3, 1), (4, 1)],   # 3-3
    [(1, 0), (0, 1), (1, 1), (2, 1), (3, 1), (3, 2)],
]
_ROLL = {  # moving +x (east): east side goes down
    (1, 0): lambda d: {**d, "B": d["E"], "E": d["T"], "T": d["W"], "W": d["B"]},
    (-1, 0): lambda d: {**d, "B": d["W"], "W": d["T"], "T": d["E"], "E": d["B"]},
    (0, 1): lambda d: {**d, "B": d["S"], "S": d["T"], "T": d["N"], "N": d["B"]},
    (0, -1): lambda d: {**d, "B": d["N"], "N": d["T"], "T": d["S"], "S": d["B"]},
}
_OPP = {"T": "B", "B": "T", "N": "S", "S": "N", "E": "W", "W": "E"}


def fold_net(cells: list[tuple[int, int]]) -> dict[tuple[int, int], str]:
    """Cell -> abstract die side id. Raises if the cells are not a valid cube net."""
    cellset = set(cells)
    start = cells[0]
    out = {start: "B"}
    stack = [(start, {k: k for k in "TBNSEW"})]
    while stack:
        (x, y), die = stack.pop()
        for d, roll in _ROLL.items():
            nb = (x + d[0], y + d[1])
            if nb in cellset and nb not in out:
                nd = roll(die)
                out[nb] = nd["B"]
                stack.append((nb, nd))
    if len(out) != 6 or len(set(out.values())) != 6:
        raise ValueError("not a cube net")
    return out


SYMBOLS = ["A", "B", "C", "D", "E", "F", "P", "Q", "R", "S", "T", "U", "1", "2", "3", "4", "5", "6"]


def cube_net(rng, assets, tag) -> LRItem:
    cells = rng.choice(NETS)
    if rng.random() < .5:
        cells = [(-x, y) for x, y in cells]
    if rng.random() < .5:
        cells = [(y, x) for x, y in cells]
    mx, my = min(c[0] for c in cells), min(c[1] for c in cells)
    cells = [(x - mx, y - my) for x, y in cells]
    side = fold_net(cells)
    pool = rng.choice([SYMBOLS[:6], SYMBOLS[6:12], SYMBOLS[12:]])
    labels = rng.sample(pool, 6)
    face = dict(zip(cells, labels))
    by_side = {side[c]: face[c] for c in cells}
    q_cell = rng.choice(cells)
    q_label = face[q_cell]
    opp = by_side[_OPP[side[q_cell]]]
    adjacent = [l for l in labels if l not in (q_label, opp)]
    shuffled, ans = _shuffle_options(rng, opp, rng.sample(adjacent, 3))
    W = max(c[0] for c in cells) + 1
    H = max(c[1] for c in cells) + 1
    fig, ax = _canvas(W + .2, H + .2)
    for (x, y) in cells:
        ax.add_patch(Rectangle((.1 + x, .1 + H - 1 - y), 1, 1, fill=False, lw=2))
        ax.text(.6 + x, .6 + H - 1 - y, face[(x, y)], ha="center", va="center", fontsize=22,
                family="DejaVu Sans", fontweight="bold")
    rel = f"figs/{tag}_stem.png"
    _save(fig, assets / rel)
    return LRItem(
        stem=f"The given sheet is folded to form a cube. Which symbol will be on the face opposite to the face "
             f"showing '{q_label}'?",
        options=shuffled, answer=ans,
        solution=(f"In a cube net, faces that are opposite never share an edge. Folding the sheet, the face "
                  f"'{q_label}' is opposite to '{opp}'; {', '.join(adjacent)} are all adjacent to it."),
        stem_figure=rel, stem_width=min(60, 12 * W + 4), subtopic="Cube folding (net)",
        params={"cells": cells, "labels": labels})


def number_grid(rng, assets, tag) -> LRItem:
    """3x3 grid; each row obeys one rule; the bottom-right cell is '?'."""
    rules = [
        ("a + b", lambda a, b: a + b, "the third number is the sum of the first two"),
        ("a × b", lambda a, b: a * b, "the third number is the product of the first two"),
        ("(a + b) × 2", lambda a, b: (a + b) * 2, "the third number is twice the sum of the first two"),
        ("a² + b", lambda a, b: a * a + b, "the third number is (first)² + second"),
        ("a × b − a", lambda a, b: a * b - a, "the third number is (first × second) − first"),
        ("a² − b²", lambda a, b: a * a - b * b, "the third number is (first)² − (second)²"),
    ]
    name, f, words = rng.choice(rules)
    rows = []
    while len(rows) < 3:
        a, b = rng.randint(2, 9), rng.randint(2, 9)
        if name == "a² − b²" and a <= b:
            a, b = b + rng.randint(1, 3), a
        r = (a, b, f(a, b))
        if r not in rows and all(r[0] != x[0] for x in rows):
            rows.append(r)
    ans_val = rows[2][2]
    a, b = rows[2][0], rows[2][1]
    cands = [ans_val + rng.choice([-2, -1, 1, 2]), ans_val + rng.choice([3, 4, 5, -3, -4]),
             a + b, a * b, a * a + b, (a + b) * 2, ans_val + 10]
    wrong = []
    for c in cands:
        if c != ans_val and c not in wrong and c > 0:
            wrong.append(c)
    shuffled, ans = _shuffle_options(rng, str(ans_val), [str(x) for x in wrong[:3]])
    fig, ax = _canvas(3.2, 3.2)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            ax.add_patch(Rectangle((.1 + j, .1 + 2 - i), 1, 1, fill=False, lw=2))
            ax.text(.6 + j, .6 + 2 - i, "?" if (i, j) == (2, 2) else str(v), ha="center", va="center",
                    fontsize=20, family="DejaVu Serif")
    rel = f"figs/{tag}_stem.png"
    _save(fig, assets / rel)
    return LRItem(
        stem="Find the missing number in the given figure.",
        options=shuffled, answer=ans,
        solution=(f"In each row, {words}: " + "; ".join(f"{r[0]}, {r[1]} → {r[2]}" for r in rows[:2])
                  + f". So, {a}, {b} → {ans_val}."),
        stem_figure=rel, stem_width=34, subtopic="Number matrix", params={"rule": name, "rows": rows})


def count_triangles(rng, assets, tag) -> LRItem:
    p = rng.randint(3, 5)          # lines from the apex, including both sides
    h = rng.randint(1, 2)          # lines parallel to the base
    total = math.comb(p, 2) * (h + 1)
    fig, ax = _canvas(3.2, 2.8)
    apex, bl, br = (1.6, 2.7), (.1, .1), (3.1, .1)
    ax.add_patch(Polygon([apex, bl, br], closed=True, fill=False, lw=2))
    for i in range(1, p - 1):
        x = bl[0] + (br[0] - bl[0]) * i / (p - 1)
        ax.plot([apex[0], x], [apex[1], .1], lw=1.8, color="black")
    for k in range(1, h + 1):
        t = k / (h + 1)
        y = apex[1] - (apex[1] - .1) * t
        xl = apex[0] - (apex[0] - bl[0]) * t
        xr = apex[0] + (br[0] - apex[0]) * t
        ax.plot([xl, xr], [y, y], lw=1.8, color="black")
    rel = f"figs/{tag}_stem.png"
    _save(fig, assets / rel)
    wrong = []
    for c in [math.comb(p, 2) * h, total + p, total - p + 1, math.comb(p, 2) + h, total + h + 1]:
        if c != total and c > 0 and c not in wrong:
            wrong.append(c)
    shuffled, ans = _shuffle_options(rng, str(total), [str(x) for x in wrong[:3]])
    return LRItem(
        stem="How many triangles are there in the given figure?",
        options=shuffled, answer=ans,
        solution=(f"There are {p} lines from the top vertex, so each horizontal strip base (the base and each of "
                  f"the {h} parallel line(s)) gives $^{{{p}}}C_2 = {math.comb(p, 2)}$ triangles. "
                  f"Total $= {math.comb(p, 2)} \\times {h + 1} = {total}$."),
        stem_figure=rel, stem_width=38, subtopic="Counting figures", params={"p": p, "h": h})


GENERATORS: dict[str, Callable[[random.Random, Path, str], LRItem]] = {
    "mirror_image": mirror_image,
    "water_image": water_image,
    "odd_figure": odd_figure,
    "rotation_series": rotation_series,
    "paper_punch": paper_punch,
    "cube_net": cube_net,
    "number_grid": number_grid,
    "count_triangles": count_triangles,
}
