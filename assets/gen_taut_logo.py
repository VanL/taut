#!/usr/bin/env python3
"""Generate the taut logo SVG: six-strand woven wreath + TAUT wordmark.

Strategy: six identical ellipses ("petals") arranged tangentially around a
ring. Adjacent petals cross at exactly two points. We sample each ellipse,
find the crossing parameters numerically, then render: (1) every full petal
stacked, (2) for each petal, short re-drawn "over" segments (white casing +
color) at the crossings where the weave says it passes on top. Over/under
rule: between neighbors k and k+1, petal k is on top at one crossing and
petal k+1 at the other -> consistent rotational weave, every strand both
over and under.
"""

import math

CX, CY = 600.0, 300.0
N = 6
D = 98.0  # petal center distance from logo center
RX, RY = 116.0, 45.0
COLOR_W, CASE_W = 30.0, 42.0
SAMPLES = 4096
COLORS = ["#E23E57", "#F0862B", "#E8B92E", "#33A65E", "#2F7FD0", "#8A4FBE"]


def petal_point(k: int, t: float) -> tuple[float, float]:
    """Point on petal k at ellipse parameter t (radians)."""
    ang = 2 * math.pi * k / N
    # ellipse in local frame (major axis along x), then rotate by ang+90deg,
    # then translate to petal center which sits at angle ang, distance D.
    lx, ly = RX * math.cos(t), RY * math.sin(t)
    rot = ang + math.pi / 2
    x = lx * math.cos(rot) - ly * math.sin(rot)
    y = lx * math.sin(rot) + ly * math.cos(rot)
    cx = CX + D * math.cos(ang)
    cy = CY + D * math.sin(ang)
    return cx + x, cy + y


def sample(k: int):
    pts = []
    for i in range(SAMPLES):
        t = 2 * math.pi * i / SAMPLES
        pts.append(petal_point(k, t))
    return pts


def arclen_fractions(pts):
    """Cumulative arc-length fraction at each sample index."""
    total = 0.0
    cum = [0.0]
    for i in range(1, len(pts) + 1):
        a = pts[i - 1]
        b = pts[i % len(pts)]
        total += math.hypot(b[0] - a[0], b[1] - a[1])
        cum.append(total)
    return [c / total for c in cum[:-1]], total


def crossings(pts_a, pts_b):
    """Find the two crossing points between two sampled closed curves.
    Returns list of (idx_a, idx_b) sample indices, clustered."""
    pairs = []
    step = 8  # coarse scan then refine
    for i in range(0, SAMPLES, step):
        ax, ay = pts_a[i]
        for j in range(0, SAMPLES, step):
            bx, by = pts_b[j]
            if (ax - bx) ** 2 + (ay - by) ** 2 < 36.0:  # within 6px
                pairs.append((i, j))
    # cluster by proximity in index space of curve a
    clusters: list[list[tuple[int, int]]] = []
    for p in sorted(pairs):
        for c in clusters:
            if min(abs(p[0] - q[0]) % SAMPLES for q in c) < 200:
                c.append(p)
                break
        else:
            clusters.append([p])
    out = []
    for c in clusters:
        # refine: densest pair in cluster
        best = min(
            ((i, j) for i, j in c),
            key=lambda ij: (
                (pts_a[ij[0]][0] - pts_b[ij[1]][0]) ** 2
                + (pts_a[ij[0]][1] - pts_b[ij[1]][1]) ** 2
            ),
        )
        out.append(best)
    return out


def fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def ellipse_attrs(k: int) -> str:
    ang = 360.0 * k / N
    pcx = CX + D * math.cos(math.radians(ang))
    pcy = CY + D * math.sin(math.radians(ang))
    return (
        f'cx="{fmt(pcx)}" cy="{fmt(pcy)}" rx="{fmt(RX)}" ry="{fmt(RY)}" '
        f'transform="rotate({fmt(ang + 90)} {fmt(pcx)} {fmt(pcy)})"'
    )


def dash_seg(k: int, color: str, start_frac: float, end_frac: float) -> str:
    """Emit casing+color ellipse pair showing only [start,end] (fractions)."""
    length = (end_frac - start_frac) % 1.0
    seg = []
    for stroke, w in ((("#ffffff"), CASE_W), (color, COLOR_W)):
        seg.append(
            f'  <ellipse {ellipse_attrs(k)} fill="none" stroke="{stroke}" '
            f'stroke-width="{fmt(w)}" stroke-linecap="round" pathLength="100" '
            f'stroke-dasharray="{fmt(length * 100)} {fmt(100 - length * 100)}" '
            f'stroke-dashoffset="{fmt(-start_frac * 100)}"/>'
        )
    return "\n".join(seg)


def main() -> None:
    all_pts = [sample(k) for k in range(N)]
    fracs = []
    totals = []
    for pts in all_pts:
        f, total = arclen_fractions(pts)
        fracs.append(f)
        totals.append(total)

    # over-windows per petal: list of (start_frac, end_frac)
    over: list[list[tuple[float, float]]] = [[] for _ in range(N)]
    win_px = 36.0  # half-window in arc-length pixels around the crossing
    for k, step_n in [(k, s) for s in (1, 2) for k in range(N)]:
        nb = (k + step_n) % N
        cs = crossings(all_pts[k], all_pts[nb])
        if len(cs) < 2:
            continue  # second neighbors may not cross; fine

        # sort crossings by angle around logo center for a stable rule
        def center_angle(ij: tuple[int, int], *, petal_index: int = k) -> float:
            x, y = all_pts[petal_index][ij[0]]
            return math.atan2(y - CY, x - CX) % (2 * math.pi)

        cs_sorted = sorted(cs[:2], key=center_angle)
        # petal k over at the first (ccw-earlier) crossing; neighbor over at other
        ia, _ = cs_sorted[0]
        _, jb = cs_sorted[1]
        wa = win_px / totals[k]
        wb = win_px / totals[nb]
        over[k].append(((fracs[k][ia] - wa) % 1.0, (fracs[k][ia] + wa) % 1.0))
        over[nb].append(((fracs[nb][jb] - wb) % 1.0, (fracs[nb][jb] + wb) % 1.0))

    parts = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 780" role="img" '
        'aria-label="Taut logo: six colored strands woven into a ring above the wordmark TAUT">'
    )
    parts.append(
        "  <!-- Generated by assets/gen_taut_logo.py - compute the weave, do not hand-tune it. -->"
    )
    parts.append('  <rect width="1200" height="780" fill="#ffffff"/>')
    parts.append('  <g stroke-linecap="round" fill="none">')
    # base stack
    for k in range(N):
        for stroke, w in (("#ffffff", CASE_W), (COLORS[k], COLOR_W)):
            parts.append(
                f'  <ellipse {ellipse_attrs(k)} stroke="{stroke}" stroke-width="{fmt(w)}"/>'
            )
    parts.append("  <!-- over-segments: computed crossing windows -->")
    for k in range(N):
        for s, e in over[k]:
            parts.append(dash_seg(k, COLORS[k], s, e))
    parts.append("  </g>")
    # wordmark (unchanged from v1: geometric paths, no font dependency)
    parts.append('  <g fill="#39414B">')
    parts.append('    <path d="M340 560 h112 v30 h-41 v90 h-30 v-90 h-41 Z"/>')
    parts.append(
        '    <path fill-rule="evenodd" d="M484 680 L522 560 L558 560 L596 680 L566 680 '
        'L558.5 656 L521.5 656 L514 680 Z M529 630 L551 630 L540 593 Z"/>'
    )
    parts.append(
        '    <path d="M628 560 h30 v82 q0 14 22 14 q22 0 22 -14 v-82 h30 v84 '
        'q0 40 -52 40 q-52 0 -52 -40 Z"/>'
    )
    parts.append('    <path d="M760 560 h112 v30 h-41 v90 h-30 v-90 h-41 Z"/>')
    parts.append("  </g>")
    parts.append("</svg>")
    out = "/Users/van/Developer/taut/assets/taut-logo.svg"
    with open(out, "w") as fh:
        fh.write("\n".join(parts) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
