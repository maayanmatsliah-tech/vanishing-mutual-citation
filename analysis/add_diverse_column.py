"""
Add a `diverse` column to the attributes table, reading straight from the CSVs
(no intermediate database).

Definition
  A paper is `diverse` (True) if the papers it CITES span >= THRESHOLD distinct
  fields, otherwise False. A cited paper's field is looked up in attributes;
  cited papers not present in attributes (unknown field) contribute no field.
  Papers with no outbound citations are False.

Inputs
  ATTR   attributes CSV: columns include `id` and `field`   (default data/attributes.csv)
  EDGES  edges CSV (adjacency): `source` + `targets` where targets is a
         ";"-joined list of cited ids                       (default data/edges.csv)

Output
  OUT    attributes CSV with one extra column `diverse` (True/False)
         (default data/attributes_with_diverse.csv -- a NEW file, the input is
         left untouched). Prints the diversity counts at the end.

Scale note
  Instead of a Python dict (which would need tens of GB for ~200M papers), the
  id -> field map is held as two sorted numpy arrays and queried with binary
  search. Peak memory is roughly: 8 bytes (id) + 2 bytes (field code) +
  1 byte (diverse flag) per paper, i.e. ~2-3 GB for 200M papers.

Env
  ATTR, EDGES, OUT  paths (see above)
  THRESHOLD         distinct cited fields needed to be diverse (default 3)
  CHUNK             rows per chunk when loading attributes (default 5_000_000)

Usage:  ./venv/bin/python add_diverse_column.py
"""

import csv
import os
import sys

import numpy as np

ATTR = os.environ.get("ATTR", "data/attributes.csv")
EDGES = os.environ.get("EDGES", "data/edges.csv")
OUT = os.environ.get("OUT", "data/attributes_with_diverse.csv")
THRESHOLD = int(os.environ.get("THRESHOLD", "3"))
CHUNK = int(os.environ.get("CHUNK", "5000000"))

# Target lists in the edges file can be very long single fields.
csv.field_size_limit(sys.maxsize)


def wid_to_int(s):
    """'W2794519871' -> 2794519871. OpenAlex work ids are 'W' + digits."""
    return int(s[1:]) if s[:1] in ("W", "w") else int(s)


def load_attributes(path):
    """Return (ids, codes, n_fields) where ids/codes are sorted-by-id numpy
    arrays mapping each paper id to a small integer field code."""
    field_codes = {}            # field string -> compact int code
    id_chunks, code_chunks = [], []
    ids_buf, codes_buf = [], []

    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        i_id, i_field = header.index("id"), header.index("field")
        for row in r:
            ids_buf.append(wid_to_int(row[i_id]))
            fld = row[i_field]
            c = field_codes.get(fld)
            if c is None:
                c = len(field_codes)
                field_codes[fld] = c
            codes_buf.append(c)
            if len(ids_buf) >= CHUNK:
                id_chunks.append(np.array(ids_buf, dtype=np.int64))
                code_chunks.append(np.array(codes_buf, dtype=np.int16))
                ids_buf.clear()
                codes_buf.clear()
    if ids_buf:
        id_chunks.append(np.array(ids_buf, dtype=np.int64))
        code_chunks.append(np.array(codes_buf, dtype=np.int16))

    ids = np.concatenate(id_chunks)
    codes = np.concatenate(code_chunks)
    order = np.argsort(ids, kind="stable")
    return ids[order], codes[order], len(field_codes)


def lookup(ids, key):
    """Index of `key` in sorted `ids`, or -1 if absent."""
    i = np.searchsorted(ids, key)
    if i < ids.shape[0] and ids[i] == key:
        return i
    return -1


def main():
    print(f"Loading attributes from {ATTR} ...", file=sys.stderr)
    ids, codes, n_fields = load_attributes(ATTR)
    N = ids.shape[0]
    print(f"  {N:,} papers, {n_fields} distinct fields", file=sys.stderr)

    # Pass over edges: mark each source diverse iff its cited papers (that we
    # know the field of) span >= THRESHOLD distinct fields.
    print(f"Scanning edges from {EDGES} ...", file=sys.stderr)
    diverse = np.zeros(N, dtype=bool)
    n_src = 0
    with open(EDGES, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        i_src, i_tgt = header.index("source"), header.index("targets")
        for row in r:
            tgt_str = row[i_tgt]
            if not tgt_str:
                continue
            n_src += 1
            t = np.fromiter(
                (wid_to_int(x) for x in tgt_str.split(";")), dtype=np.int64
            )
            idx = np.searchsorted(ids, t)
            np.clip(idx, 0, N - 1, out=idx)
            present = ids[idx] == t
            if not present.any():
                continue
            if np.unique(codes[idx[present]]).size >= THRESHOLD:
                s = lookup(ids, wid_to_int(row[i_src]))
                if s >= 0:
                    diverse[s] = True
            if n_src % 10_000_000 == 0:
                print(f"  {n_src:,} citing papers scanned", file=sys.stderr)

    # Rewrite attributes with the new column, preserving original row order.
    print(f"Writing {OUT} ...", file=sys.stderr)
    n_tot = n_div = 0
    with open(ATTR, newline="", encoding="utf-8") as f, \
         open(OUT, "w", newline="", encoding="utf-8") as g:
        r = csv.reader(f)
        w = csv.writer(g)
        header = next(r)
        i_id = header.index("id")
        w.writerow(header + ["diverse"])
        for row in r:
            s = lookup(ids, wid_to_int(row[i_id]))
            is_div = bool(s >= 0 and diverse[s])
            w.writerow(row + ["True" if is_div else "False"])
            n_tot += 1
            n_div += is_div

    pct = (n_div / n_tot * 100) if n_tot else 0.0
    print("\n=== diversity counts ===")
    print(f"  total papers : {n_tot:,}")
    print(f"  diverse=True : {n_div:,} ({pct:.1f}%)")
    print(f"  diverse=False: {n_tot - n_div:,} ({100 - pct:.1f}%)")
    print(f"  (diverse = cites papers from >= {THRESHOLD} distinct fields)")


if __name__ == "__main__":
    main()
