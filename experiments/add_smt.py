# -*- coding: utf-8 -*-
"""高效补数据:只算 SMT(全实验)+ VESTA-256/2048 预计算,合并进已有 CSV。

复用上次跑好的 VESTA-256/VESTA-2048/MHT 数据(不重算),仅:
  - 计算 SMT 的 e1/e234/e5/a4/a1_violation 行,幂等追加进对应 CSV;
  - 重算 a2 批量预计算(VESTA-256 与 VESTA-2048),写带 scheme 列的新格式。
"""
import csv
import gc
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim.simulator import generate_round, make_absent_elements
from vesta.scheme import Vesta
from baselines.smt import SMT
from experiments.run_extra import violation_targets

RESULTS = ROOT / "results"
SIZES = [500, 1000, 2000, 5000, 10000]
SEED = 42
DATASETS = ["gMission", "EverySender"]


def now():
    return time.perf_counter_ns() / 1e6


def merge_csv(name, header, new_rows, scheme="SMT"):
    """幂等合并:删掉已有的 scheme 行,追加新行(保留其他方案)。"""
    path = RESULTS / name
    head, keep = header, []
    if path.exists():
        with open(path) as f:
            r = list(csv.reader(f))
        head = r[0]
        keep = [row for row in r[1:] if row and row[0] != scheme]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(keep)
        w.writerows(new_rows)
    print(f"  merged {name}: +{len(new_rows)} SMT rows (kept {len(keep)})")


def smt_e1(ds, reps=10):
    rows = []
    for n in SIZES:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            a = SMT(); t0 = now(); a.build(facts); t1 = now()
            rows.append(["SMT", n, rep, round(t1 - t0, 3)])
            del a; gc.collect()
    merge_csv(f"e1_build_{ds}.csv", ["scheme", "size", "rep", "build_ms"], rows)


def smt_e234(ds, reps=10, k=100):
    gen, ver, siz = [], [], []
    for n in SIZES:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            rng = random.Random(SEED + rep)
            a = SMT(); a.build(facts)
            mem = rng.sample(facts, k)
            non = make_absent_elements(facts, k, seed=SEED + rep)
            for pi, targets, fn in (("mem", mem, a.gen_mem),
                                    ("nonmem", non, a.gen_nonmem)):
                t0 = now(); vos = [fn(z) for z in targets]; t1 = now()
                gen.append(["SMT", n, rep, pi, round((t1 - t0) / len(targets), 4)])
                t0 = now(); ok = all(a.verify(v) for v in vos); t1 = now()
                assert ok
                ver.append(["SMT", n, rep, pi, round((t1 - t0) / len(vos), 4)])
                avg = sum(a.vo_size(v) for v in vos) / len(vos)
                siz.append(["SMT", n, rep, pi, round(avg, 1)])
            del a; gc.collect()
        print(f"  SMT e234 n={n}: done")
    hdr = ["scheme", "size", "rep", "pi"]
    merge_csv(f"e2_vogen_{ds}.csv", hdr + ["gen_ms"], gen)
    merge_csv(f"e3_verify_{ds}.csv", hdr + ["verify_ms"], ver)
    merge_csv(f"e4_vosize_{ds}.csv", hdr + ["size_bytes"], siz)


def smt_e5(ds, reps=10, base_n=5000, batches=(10, 50, 100, 500, 1000)):
    rows = []
    for rep in range(reps):
        allf = generate_round(base_n + max(batches), start_file=rep,
                              seed=SEED, dataset=ds)
        base, extra = allf[:base_n], allf[base_n:]
        for b in batches:
            a = SMT(); a.build(base)
            t0 = now(); a.update(extra[:b]); t1 = now()
            rows.append(["SMT", b, rep, round(t1 - t0, 3)])
            del a; gc.collect()
        print(f"  SMT e5 rep={rep}: done")
    merge_csv(f"e5_update_{ds}.csv", ["scheme", "batch", "rep", "update_ms"], rows)


def smt_a4(ds, reps=3):
    rows = []
    for n in SIZES:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            a = SMT(); a.build(facts)
            rows.append(["SMT", n, rep, a.ads_bytes()])
            del a; gc.collect()
    merge_csv(f"a4_storage_{ds}.csv", ["scheme", "size", "rep", "bytes"], rows)


def smt_a1_violation(ds, reps=5):
    rows = []
    for n in SIZES:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            targets = violation_targets(facts)
            a = SMT(); a.build(facts)
            t0 = now()
            vos = [a.gen_mem(z) if pi == "mem" else a.gen_nonmem(z)
                   for pi, z in targets]
            t1 = now()
            ok = all(a.verify(v) for v in vos); t2 = now(); assert ok
            size = sum(a.vo_size(v) for v in vos)
            rows.append(["SMT", n, rep, round(t1 - t0, 3),
                         round(t2 - t1, 3), size])
            del a; gc.collect()
        print(f"  SMT a1-violation n={n}: done")
    merge_csv(f"a1_violation_{ds}.csv",
              ["scheme", "size", "rep", "gen_ms", "verify_ms", "size_bytes"],
              rows)


def a2_both(ds, reps=5):
    """批量预计算:VESTA-256 与 VESTA-2048,新格式带 scheme 列。"""
    rows = []
    for bits in (256, 2048):
        for n in SIZES:
            for rep in range(reps):
                facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
                a = Vesta(bits); a.build(facts)
                t0 = now(); wits = a.batch_mem_witnesses(); t1 = now()
                assert len(wits) == len(set(a.acc.primes))
                rows.append([f"VESTA-{bits}", n, rep, round(t1 - t0, 1),
                             round((t1 - t0) / n, 4)])
                del a, wits; gc.collect()
            print(f"  a2 VESTA-{bits} n={n}: done")
    with open(RESULTS / f"a2_batch_{ds}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scheme", "size", "rep", "total_ms", "amortized_ms"])
        w.writerows(rows)
    print(f"  wrote a2_batch_{ds}.csv ({len(rows)} rows)")


if __name__ == "__main__":
    t0 = time.time()
    for ds in DATASETS:
        print(f"=== {ds} ===")
        smt_e1(ds)
        smt_e234(ds)
        smt_e5(ds)
        smt_a4(ds)
        smt_a1_violation(ds)
        a2_both(ds)
    print(f"DONE in {time.time()-t0:.0f}s")
