#!/usr/bin/env python3
"""
scen_tool.py — Langrisser Saturn SCEN.DAT parser / serializer.

SCEN.DAT structure (verified on Track1 SHA-1 771515a4...):
  A recursive tree of 32-bit big-endian offset tables + SJIS leaf strings.

  A "table" region [start, end):
    - first be32 (relative to `start`) = e0 = size of the table area in bytes.
    - table area [start, start+e0) holds ascending non-zero be32 offsets
      (relative to `start`), zero-padded to e0 bytes (reserved slots).
    - the R real entries carve children: child_i = [start+off_i, start+off_{i+1}),
      the last child runs to `end`. off_0 == e0, so child_0 begins right after
      the table area. Trailing padding inside a block is absorbed into the last
      child's raw bytes (the doc's "0x00 padding leaf").

  A "leaf" region: raw bytes (SJIS text with <0x0A control codes). Not a table.

Round-trip guarantee: serialize(parse(data)) == data  (validated in __main__).
"""
import struct, sys, io

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


def be32(data, off):
    return struct.unpack(">I", data[off:off + 4])[0]


class Node:
    __slots__ = ("kind", "start", "end", "table_size", "offs", "children", "raw")

    def __init__(self, kind, start, end):
        self.kind = kind          # "table" | "leaf"
        self.start = start
        self.end = end
        self.table_size = None    # table: e0 (bytes of table area incl. padding)
        self.offs = None          # table: list of R real relative offsets
        self.children = None      # table: list[Node]
        self.raw = None           # leaf: raw bytes


def try_table(data, start, end):
    """Return (table_size, [rel_offsets]) if [start,end) is a valid offset table, else None."""
    L = end - start
    if L < 8:
        return None
    e0 = be32(data, start)
    if e0 < 8 or e0 % 4 != 0 or e0 > L:
        return None
    offs = []
    prev = -1
    p = start
    limit = start + e0
    while p < limit:
        v = be32(data, p)
        if v == 0:
            break  # zero padding -> end of real entries
        if v <= prev or v > L:
            return None  # not strictly ascending / out of range -> not a table
        offs.append(v)
        prev = v
        p += 4
    # first real offset must equal the table area size (first child right after table)
    if not offs or offs[0] != e0:
        return None
    # remaining bytes in table area (after real entries) must be zero padding
    rest = data[start + len(offs) * 4: start + e0]
    if any(b != 0 for b in rest):
        return None
    return e0, offs


def parse_region(data, start, end, depth=0):
    node = Node("?", start, end)
    tbl = try_table(data, start, end) if depth < 24 else None
    if tbl is None:
        node.kind = "leaf"
        node.raw = data[start:end]
        return node
    e0, offs = tbl
    node.kind = "table"
    node.table_size = e0
    node.offs = offs
    node.children = []
    bounds = [start + o for o in offs] + [end]
    for i in range(len(offs)):
        c = parse_region(data, bounds[i], bounds[i + 1], depth + 1)
        node.children.append(c)
    return node


def parse(data):
    return parse_region(data, 0, len(data), 0)


def serialize(node, out=None):
    """Reconstruct bytes. Recomputes offsets from current child sizes;
    identical children -> identical bytes (round-trip)."""
    if out is None:
        out = bytearray()
    if node.kind == "leaf":
        out += node.raw
        return out
    # table: emit R offsets, zero-pad to table_size, then children.
    # child sizes may have changed; recompute relative offsets.
    child_bytes = [serialize(c, bytearray()) for c in node.children]
    rel = []
    cur = node.table_size
    for cb in child_bytes:
        rel.append(cur)
        cur += len(cb)
    header = bytearray()
    for r in rel:
        header += struct.pack(">I", r)
    # zero pad header up to table_size
    if len(header) > node.table_size:
        raise ValueError(f"table overflow: {len(header)} > {node.table_size} at {node.start:#x}")
    header += b"\x00" * (node.table_size - len(header))
    out += header
    for cb in child_bytes:
        out += cb
    return out


def iter_leaves(node, path=()):
    """Yield (path, Node) for every leaf, path = tuple of child indices."""
    if node.kind == "leaf":
        yield path, node
    else:
        for i, c in enumerate(node.children):
            yield from iter_leaves(c, path + (i,))


def tree_stats(node):
    n_tables = n_leaves = leaf_bytes = 0
    stack = [node]
    maxdepth = 0
    while stack:
        n = stack.pop()
        if n.kind == "leaf":
            n_leaves += 1
            leaf_bytes += len(n.raw)
        else:
            n_tables += 1
            stack.extend(n.children)
    return n_tables, n_leaves, leaf_bytes


if __name__ == "__main__":
    import os
    ORIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "original")
    for name in ("LANG1_SCEN.DAT", "LANG2_SCEN.DAT"):
        path = os.path.join(ORIG, name)
        with open(path, "rb") as f:
            data = f.read()
        tree = parse(data)
        rebuilt = bytes(serialize(tree))
        ok = rebuilt == data
        nt, nl, lb = tree_stats(tree)
        print(f"{name}: size={len(data):,}  tables={nt:,}  leaves={nl:,}  leaf_bytes={lb:,}")
        print(f"  ROUND-TRIP: {'PASS' if ok else 'FAIL'}", end="")
        if not ok:
            # locate first diff
            for i in range(min(len(data), len(rebuilt))):
                if data[i] != rebuilt[i]:
                    print(f"  first diff @ {i:#x} (len {len(data)} vs {len(rebuilt)})", end="")
                    break
            else:
                print(f"  length diff {len(data)} vs {len(rebuilt)}", end="")
        print()
