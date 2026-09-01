#!/usr/bin/env python3
"""CLI script — find the minimum number of moves to solve a Phil level.

Usage
-----
Single JSON file with "floor" and "top" keys:
    python solve_level.py --level level.json

Separate files for each layer:
    python solve_level.py --floor floor.json --top top.json

Optional flags:
    --max-depth N           BFS depth limit (default: 20)
    --spike-revival N       Moves after which retracted spikes revive (default: never)

Output
------
Prints a JSON object to stdout:
    {
      "solvable": true,
      "min_moves": 3,
      "moves": [
        {"block_row": 2, "block_col": 4, "direction": "left"},
        ...
      ]
    }

Cell values must match the BlockType enum strings defined in
app/models/level.py.  Valid floor values: "empty", "static", "hole",
"quicksand", "ice_floor".  Valid top values: "empty", "static", "phil",
"goal", "move_one", "ice", "bounce", "spike".

Example level.json
------------------
{
  "floor": [
    ["empty", "empty", "empty"],
    ["empty", "hole",  "empty"],
    ["empty", "empty", "empty"]
  ],
  "top": [
    ["phil",     "empty",    "empty"],
    ["move_one", "empty",    "empty"],
    ["empty",    "empty",    "goal"]
  ]
}
"""

import argparse
import json
import sys

# Allow running from the repo root without installing the package.
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.models.level import BlockType
from app.solver.solver import solve


def _parse_grid(raw: list[list[str]]) -> list[list[BlockType]]:
    """Convert a 2-D list of strings into a 2-D list of BlockType values.

    Raises ValueError with a descriptive message if any cell string is not a
    recognised BlockType value.

    Args:
        raw: 2-D list of strings as parsed from JSON.

    Returns:
        2-D list of BlockType enum members.
    """
    result: list[list[BlockType]] = []
    valid = {bt.value for bt in BlockType}
    for r, row in enumerate(raw):
        parsed_row: list[BlockType] = []
        for c, cell in enumerate(row):
            if cell not in valid:
                raise ValueError(
                    f"Unknown cell value {cell!r} at [{r}][{c}]. "
                    f"Valid values: {sorted(valid)}"
                )
            parsed_row.append(BlockType(cell))
        result.append(parsed_row)
    return result


def main() -> None:
    """Entry point — parse arguments, run solver, print JSON result."""
    parser = argparse.ArgumentParser(
        description="Find the minimum moves to solve a Phil level.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--level",
        metavar="FILE",
        help='JSON file with "floor" and "top" keys.',
    )
    parser.add_argument(
        "--floor",
        metavar="FILE",
        help="JSON file containing the floor (bottom layer) 2-D array.",
    )
    parser.add_argument(
        "--top",
        metavar="FILE",
        help="JSON file containing the top-layer 2-D array.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=20,
        metavar="N",
        help="BFS depth limit in player moves (default: 20).",
    )
    parser.add_argument(
        "--spike-revival",
        type=int,
        default=None,
        metavar="N",
        help="Moves after which retracted spikes revive (default: never).",
    )

    args = parser.parse_args()

    # --- Load raw grids ---

    if args.level:
        with open(args.level) as f:
            data = json.load(f)
        raw_floor = data["floor"]
        raw_top = data["top"]
    elif args.floor and args.top:
        with open(args.floor) as f:
            raw_floor = json.load(f)
        with open(args.top) as f:
            raw_top = json.load(f)
    else:
        parser.error("Provide --level OR both --floor and --top.")
        return  # unreachable; satisfies type checkers

    # --- Parse and validate ---

    try:
        floor_grid = _parse_grid(raw_floor)
        top_grid = _parse_grid(raw_top)
    except (ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)

    # --- Solve ---

    result = solve(
        floor_grid=floor_grid,
        top_grid=top_grid,
        max_depth=args.max_depth,
        spike_revival_moves=args.spike_revival,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
