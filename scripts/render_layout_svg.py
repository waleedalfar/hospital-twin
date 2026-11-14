"""Draws shared/layout.json as one top-down SVG (all floors side by side) so a person can check it by eye.

    uv run --directory backend python ../scripts/render_layout_svg.py ../docs/evidence/cp1/layout.svg
"""

import sys
from pathlib import Path

from twin.sim.layout_model import Layout, load_layout

SCALE = 14
PAD = 3
FLOOR_W = 46
COLORS = {"walk": "#2453b0", "door": "#e58a2e", "elevator": "#e5484d"}


def draw(layout: Layout) -> str:
    out: list[str] = []
    width = (FLOOR_W * 4 + PAD) * SCALE
    height = 52 * SCALE
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'font-family="monospace" font-size="9"><rect width="100%" height="100%" fill="#ffffff"/>'
    )
    for floor in layout.floors:
        ox = (PAD + 21 + floor.level * FLOOR_W) * SCALE
        oz = (PAD + 15) * SCALE

        def px(x: float, _ox: float = ox) -> float:
            return _ox + x * SCALE

        def pz(z: float, _oz: float = oz) -> float:
            return _oz + z * SCALE

        out.append(f'<text x="{px(-20)}" y="{pz(-15)}" font-size="14">Floor {floor.level}: {floor.name}</text>')
        for room in floor.rooms:
            if room.kind == "outside":
                continue
            r = room.rect
            out.append(
                f'<rect x="{px(r.x1)}" y="{pz(r.z1)}" width="{(r.x2 - r.x1) * SCALE}" height="{(r.z2 - r.z1) * SCALE}" '
                f'fill="#f6f2e8" stroke="#1d1a2c" stroke-width="2" fill-opacity="0.6"/>'
            )
            out.append(f'<text x="{px(r.x1) + 4}" y="{pz(r.z1) + 12}" font-size="11" fill="#1d1a2c">{room.id}</text>')
        for door in floor.doors:
            if door.axis == "x":
                a, b = (px(door.start), pz(door.at)), (px(door.end), pz(door.at))
            else:
                a, b = (px(door.at), pz(door.start)), (px(door.at), pz(door.end))
            out.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#ffffff" stroke-width="4"/>')
            out.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#3fb68b" stroke-width="2"/>')
        for prop in layout.props:
            if prop.floor != floor.level:
                continue
            f = prop.footprint
            out.append(
                f'<rect x="{px(f.x1)}" y="{pz(f.z1)}" width="{prop.w * SCALE}" height="{prop.d * SCALE}" '
                f'fill="{"#c99a63" if prop.blocks else "#d6efe2"}" stroke="#7a5a36" stroke-width="0.5"/>'
            )
        for bed in layout.beds:
            if bed.floor != floor.level:
                continue
            out.append(
                f'<rect x="{px(bed.x - 0.55)}" y="{pz(bed.z - 1.05)}" width="{1.1 * SCALE}" height="{2.1 * SCALE}" '
                f'fill="#8ec0ea" stroke="#1d1a2c"/>'
            )
            label_z = bed.z + (2.0 if bed.head == "north" else -1.4)
            out.append(f'<text x="{px(bed.x - 0.9)}" y="{pz(label_z)}" font-size="8">{bed.id}</text>')
        for edge in layout.graph.edges:
            a_node, b_node = layout.nodes[edge.a], layout.nodes[edge.b]
            if a_node.floor != floor.level or b_node.floor != floor.level:
                continue
            out.append(
                f'<line x1="{px(a_node.x)}" y1="{pz(a_node.z)}" x2="{px(b_node.x)}" y2="{pz(b_node.z)}" '
                f'stroke="{COLORS[edge.kind]}" stroke-width="1"/>'
            )
        for node in layout.graph.nodes:
            if node.floor == floor.level:
                out.append(f'<circle cx="{px(node.x)}" cy="{pz(node.z)}" r="2" fill="#2453b0"/>')
        for seat in layout.seats:
            if seat.floor == floor.level:
                out.append(f'<circle cx="{px(seat.x)}" cy="{pz(seat.z)}" r="3.5" fill="#7a5cc2"/>')
        for spot in layout.spots:
            if spot.floor == floor.level:
                out.append(f'<circle cx="{px(spot.x)}" cy="{pz(spot.z)}" r="3" fill="#2fa39a"/>')
    legend_y = 48 * SCALE
    out.append(
        f'<text x="{PAD * SCALE}" y="{legend_y}" font-size="13">blue lines: walking graph | orange: through a door | '
        f"green: door gaps | light blue: beds | brown: furniture | purple dots: seats | teal dots: work spots</text>"
    )
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draw(load_layout()), encoding="utf-8")
    print(f"Wrote {target}")
