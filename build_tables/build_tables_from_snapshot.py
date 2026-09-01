"""
Build attributes and edges tables by streaming the public OpenAlex snapshot from S3.

Outputs:
  attributes: id, year, field, author
  edges:      source, semicolon-delimited cited target IDs

Env:
  SAMPLE_N    Max rows to process (default: 100; 0 = unlimited)
  START_YEAR  Start publication year (default: 1975)
  END_YEAR    End publication year (default: 2025)
  ATTR_OUT    Output path for attributes CSV (default: data/sample_attributes.csv)
  EDGES_OUT   Output path for edges CSV (default: data/sample_edges.csv)
  PROGRESS    Checkpoint TSV file (default: data/.snapshot_progress.tsv)
"""

import csv
import gzip
import http.client
import json
import os
import sys
import time

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError

BUCKET = "openalex"
WORKS_PREFIX = "data/works/"

SAMPLE_N = int(os.environ.get("SAMPLE_N", "100"))
START_YEAR = int(os.environ.get("START_YEAR", "1975"))
END_YEAR = int(os.environ.get("END_YEAR", "2025"))
ATTR_OUT = os.environ.get("ATTR_OUT", "data/sample_attributes.csv")
EDGES_OUT = os.environ.get("EDGES_OUT", "data/sample_edges.csv")
PROGRESS = os.environ.get("PROGRESS", "data/.snapshot_progress.tsv")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "10"))

# Transient failures to retry a part on. A laptop sleeping mid-stream kills the
# S3 socket and the next read surfaces as one of these on wake.
RETRYABLE = (BotoCoreError, OSError, EOFError, http.client.IncompleteRead)


def make_client():
    """S3 client with generous timeouts and HTTP-level retries so brief network
    blips are handled below this code; longer outages bubble up as RETRYABLE."""
    return boto3.client(
        "s3",
        config=Config(
            signature_version=UNSIGNED,
            retries={"max_attempts": 5, "mode": "adaptive"},
            connect_timeout=30,
            read_timeout=120,
        ),
    )


def strip_prefix(oa_id: str) -> str:
    """'https://openalex.org/W123' -> 'W123'."""
    return oa_id.rsplit("/", 1)[-1]


def extract(work):
    """Return (attr_row, edge_rows) for one work, or None if it should be skipped."""
    year = work.get("publication_year")
    if year is None or year < START_YEAR or year > END_YEAR:
        return None
    wid = work.get("id")
    if not wid:
        return None
    wid = strip_prefix(wid)

    topics = work.get("topics") or []
    field = "Unknown"
    if topics and isinstance(topics[0], dict):
        field = (topics[0].get("field") or {}).get("display_name", "Unknown")

    authors = "; ".join(
        a["author"]["display_name"]
        for a in (work.get("authorships") or [])
        if a.get("author", {}).get("display_name")
    )

    attr_row = (wid, year, field, authors)
    targets = [strip_prefix(ref) for ref in (work.get("referenced_works") or [])]
    return attr_row, wid, targets


MAX_FOLDERS = int(os.environ.get("MAX_FOLDERS", "100000"))  # effectively all


def list_part_files(s3, limit_folders=MAX_FOLDERS):
    """Yield .gz part-file keys across the works partitions (folder by folder).
    SAMPLE_N in the caller stops early; for a full run this walks everything."""
    folders = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=WORKS_PREFIX, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            folders.append(cp["Prefix"])
            if len(folders) >= limit_folders:
                break
        if len(folders) >= limit_folders:
            break
    for folder in folders:
        for page in paginator.paginate(Bucket=BUCKET, Prefix=folder):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".gz"):
                    yield obj["Key"]


def load_progress():
    """Read the checkpoint: return (done_keys, attr_offset, edge_offset).

    Each line is '<key>\\t<attr_bytes>\\t<edge_bytes>' written after a part fully
    completes; the last line holds the authoritative byte offsets to resume from.
    """
    done = set()
    a_off = e_off = 0
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding="utf-8") as pf:
            for line in pf:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                done.add(parts[0])
                a_off, e_off = int(parts[1]), int(parts[2])
    return done, a_off, e_off


def main():
    s3 = make_client()

    done, a_off, e_off = load_progress()
    resuming = bool(done)

    if resuming:
        # Discard any partial part written after the last completed checkpoint.
        os.truncate(ATTR_OUT, a_off)
        os.truncate(EDGES_OUT, e_off)
        print(
            f"resuming: {len(done)} parts already done, "
            f"truncated to {a_off}/{e_off} bytes",
            file=sys.stderr,
        )

    n_attr = 0
    n_edge = 0
    with open(
        ATTR_OUT, "a" if resuming else "w", newline="", encoding="utf-8"
    ) as af, open(
        EDGES_OUT, "a" if resuming else "w", newline="", encoding="utf-8"
    ) as ef, open(
        PROGRESS, "a", encoding="utf-8"
    ) as cp:
        aw = csv.writer(af)
        ew = csv.writer(ef)
        if not resuming:
            aw.writerow(["id", "year", "field", "author"])
            ew.writerow(["source", "targets"])
            af.flush()
            ef.flush()

        for key in list_part_files(s3):
            if key in done:
                continue

            # Remember where this part starts so a mid-part failure can be rolled
            # back cleanly and the whole part re-streamed (no partial duplicates).
            start_a, start_e = af.tell(), ef.tell()
            start_na, start_ne = n_attr, n_edge

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    print(f"streaming s3://{BUCKET}/{key}", file=sys.stderr)
                    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"]
                    with gzip.open(body, "rb") as f:
                        for line in f:
                            work = json.loads(line)
                            got = extract(work)
                            if not got:
                                continue
                            attr_row, src, targets = got
                            aw.writerow(attr_row)
                            if targets:
                                ew.writerow([src, ";".join(targets)])
                            n_attr += 1
                            n_edge += len(targets)
                    break  # part streamed successfully
                except RETRYABLE as ex:
                    if attempt == MAX_RETRIES:
                        raise
                    wait = min(60, 2**attempt)
                    print(
                        f"  {type(ex).__name__} on {key} "
                        f"(attempt {attempt}/{MAX_RETRIES}); rolling back "
                        f"part, reconnecting, retrying in {wait}s",
                        file=sys.stderr,
                    )
                    af.flush()
                    af.truncate(start_a)
                    af.seek(0, os.SEEK_END)
                    ef.flush()
                    ef.truncate(start_e)
                    ef.seek(0, os.SEEK_END)
                    n_attr, n_edge = start_na, start_ne
                    time.sleep(wait)
                    s3 = make_client()

            # Part fully processed: durably flush both files, then checkpoint
            # their byte offsets. A crash before this point leaves the part
            # uncheckpointed, so the next run truncates and re-streams it.
            af.flush()
            os.fsync(af.fileno())
            ef.flush()
            os.fsync(ef.fileno())
            cp.write(f"{key}\t{af.tell()}\t{ef.tell()}\n")
            cp.flush()
            os.fsync(cp.fileno())

            if SAMPLE_N and n_attr >= SAMPLE_N:
                print(f"reached SAMPLE_N={SAMPLE_N}", file=sys.stderr)
                break
    print(f"wrote {n_attr} attribute rows, {n_edge} edge rows this session")


if __name__ == "__main__":
    main()
