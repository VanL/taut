#!/usr/bin/env python3
"""
Generate a large, colorful SVG of a Turks Head Woggle Knot (pulled tight).
Uses matplotlib to create a vector SVG with interwoven parametric strands.
"""

from pathlib import Path

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np

# Output path
output_path = "./turks_head_woggle.svg"

# Figure setup - large for detail
fig, ax = plt.subplots(figsize=(14, 14), facecolor="#0f0f1a")
ax.set_aspect("equal")
ax.set_xlim(-1.35, 1.35)
ax.set_ylim(-1.35, 1.35)
ax.axis("off")

# Knot parameters for a dense, pulled-tight woggle look
cx, cy = 0.0, 0.0
r_mean = 0.78  # mean radius of the band center
band_width = 0.32  # total width of the woggle band
num_strands = 5  # number of colorful strands (leads)
num_bights = 7  # number of bights/waves around the circumference
num_revs = 2  # revolutions the pattern makes (for interweaving density)
amplitude = 0.045  # radial weave amplitude - small = pulled tight
linewidth = 11.0  # thick strands for substantial rope feel
shadow_offset = 0.022  # for subtle drop shadow

# Vibrant, colorful palette (plasma-like but custom for pop)
colors = [
    "#ff2d55",  # vibrant pink/red
    "#ff9500",  # orange
    "#ffcc00",  # yellow/gold
    "#34c759",  # green
    "#5ac8fa",  # cyan/blue
]

# Optional: create a nice gradient colormap as alternative (uncomment to use single strand gradient)
# cmap = plt.cm.plasma
# colors = [cmap(i) for i in np.linspace(0.15, 0.95, num_strands)]

# Subtle background ring (the "cylinder" base)
theta_bg = np.linspace(0, 2 * np.pi, 400)
r_outer = r_mean + band_width / 2 + 0.015
r_inner = r_mean - band_width / 2 - 0.015
ax.fill_between(
    r_outer * np.cos(theta_bg),
    r_outer * np.sin(theta_bg),
    r_inner * np.cos(theta_bg),
    r_inner * np.sin(theta_bg),
    color="#1c1c2e",
    alpha=0.6,
    zorder=1,
)

# Draw subtle edge rings for definition (pulled tight look)
for r_edge, lw, alpha in [
    (r_mean + band_width / 2 + 0.008, 3.5, 0.25),
    (r_mean - band_width / 2 - 0.008, 3.5, 0.25),
]:
    ax.plot(
        r_edge * np.cos(theta_bg),
        r_edge * np.sin(theta_bg),
        color="#3a3a4a",
        linewidth=lw,
        alpha=alpha,
        zorder=2,
        solid_capstyle="round",
    )

# Generate and draw each strand
for i in range(num_strands):
    phase = 2 * np.pi * i / num_strands
    # Distribute strands across the band width
    radial_offset = (i - (num_strands - 1) / 2) * (band_width / (num_strands + 0.5))

    # High resolution parameter
    t = np.linspace(0, 2 * np.pi * num_revs, 2500)

    # Main angular progression
    theta = t

    # Weave oscillation (sinusoidal for smooth interlace)
    weave = amplitude * np.sin(num_bights * t + phase)

    # Radial position (band center + offset + weave)
    r = r_mean + radial_offset + weave

    # Cartesian coordinates
    x = r * np.cos(theta)
    y = r * np.sin(theta)

    # Subtle drop shadow for depth (makes it look pulled/raised)
    ax.plot(
        x + shadow_offset,
        y - shadow_offset,
        color="#000000",
        linewidth=linewidth + 6,
        alpha=0.12,
        solid_capstyle="round",
        solid_joinstyle="round",
        zorder=3 + i * 0.1,
    )

    # Main colorful strand
    line = ax.plot(
        x,
        y,
        color=colors[i],
        linewidth=linewidth,
        solid_capstyle="round",
        solid_joinstyle="round",
        alpha=0.92,
        zorder=10 + i,
    )[0]

    # Add a thin bright highlight edge for rope-like sheen (optional but nice)
    line.set_path_effects(
        [
            path_effects.Stroke(
                linewidth=linewidth * 0.18, foreground="#ffffff", alpha=0.25
            ),
            path_effects.Normal(),
        ]
    )

# Add a very subtle center highlight or inner glow for the hole
ax.add_patch(plt.Circle((0, 0), r_inner + 0.01, color="#0a0a12", alpha=0.3, zorder=20))

# Optional small decorative center if wanted (none for clean woggle)
# ax.plot(0, 0, 'o', color='#2a2a3a', markersize=8, zorder=21)

# Save as clean SVG (vector, infinitely scalable, large detail)
plt.savefig(
    output_path,
    format="svg",
    bbox_inches="tight",
    pad_inches=0.15,
    facecolor=fig.get_facecolor(),
    edgecolor="none",
    dpi=300,  # high dpi helps raster fallbacks but SVG is vector anyway
)

output = Path(output_path)
output.write_text(
    "\n".join(line.rstrip() for line in output.read_text(encoding="utf-8").splitlines())
    + "\n",
    encoding="utf-8",
)

print(f"✅ Large colorful Turks Head woggle knot SVG saved to: {output_path}")
print(
    f"   Parameters: {num_strands} strands, {num_bights} bights, {num_revs} revolutions"
)
print(
    "   Tight weave (small amplitude), thick colorful ropes, dark dramatic background."
)
