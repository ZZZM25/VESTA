# -*- coding: utf-8 -*-
"""实验入口。

用法:
  python experiments/run.py --exp e1          # ADS 构建时间
  python experiments/run.py --exp e234        # VO 构建/验证时间 + VO 大小(一趟产出三组)
  python experiments/run.py --exp e5          # 更新时间
  python experiments/run.py --exp e6          # 泄露量表
  python experiments/run.py --exp all
  可选: --sizes 500 1000 --reps 3 --schemes VESTA MHT
"""
import argparse
import csv
import gc
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sim.simulator import generate_round, make_absent_elements
from vesta.scheme import Vesta
from baselines.mht import MHT
from baselines.smt import SMT

RESULTS = ROOT / "results"
FIGS = ROOT / "figs"
RESULTS.mkdir(exist_ok=True)
FIGS.mkdir(exist_ok=True)

SIZES = [500, 1000, 2000, 5000, 10000]
REPS = 10
SEED = 42
# E2/E3/E4 每轮抽样数(VESTA witness 生成昂贵,样本少但均值稳定)
SAMPLES = {"VESTA-256": 10, "VESTA-2048": 10, "MHT": 100, "SMT": 100}
SCHEMES = {"VESTA-256": lambda: Vesta(256),
           "VESTA-2048": lambda: Vesta(2048),
           "MHT": MHT,
           "SMT": SMT}

COLORS = {"VESTA-256": "#295A8C", "VESTA-2048": "#529442",
          "MHT": "#637384", "SMT": "#BD8C7B"}
MARKERS = {"VESTA-256": "o", "VESTA-2048": "v", "MHT": "s", "SMT": "D"}


def now_ms():
    return time.perf_counter_ns() / 1e6


def write_csv(name, header, rows):
    path = RESULTS / name
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  saved {path.relative_to(ROOT)} ({len(rows)} rows)")


def agg(rows, key_cols, val_col):
    """按 key 聚合 -> {key: (mean, std)}"""
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in rows:
        buckets[tuple(r[c] for c in key_cols)].append(float(r[val_col]))
    out = {}
    for k, vs in buckets.items():
        m = sum(vs) / len(vs)
        sd = (sum((v - m) ** 2 for v in vs) / len(vs)) ** 0.5
        out[k] = (m, sd)
    return out


def line_plot(data, schemes, xs, title, ylabel, fname, logy=True):
    """data: {(scheme, x): (mean, std)}"""
    plt.figure(figsize=(5, 3.6))
    for s in schemes:
        ys = [data[(s, x)][0] for x in xs]
        es = [data[(s, x)][1] for x in xs]
        plt.errorbar(xs, ys, yerr=es, label=s, color=COLORS[s],
                     marker=MARKERS[s], capsize=3, linewidth=1.5)
    plt.xlabel("Facts per round")
    plt.ylabel(ylabel)
    plt.title(title)
    if logy:
        plt.yscale("log")
    plt.xscale("log")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGS / fname, dpi=300)
    plt.close()
    print(f"  saved figs/{fname}")


# ---------------- E1: ADS 构建时间 ----------------
def run_e1(sizes, reps, schemes, ds):
    print(f"[E1] ADS construction time ({ds})")
    rows = []
    for n in sizes:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            for sname in schemes:
                ads = SCHEMES[sname]()
                t0 = now_ms()
                ads.build(facts)
                t1 = now_ms()
                rows.append([sname, n, rep, round(t1 - t0, 3)])
                print(f"  E1 n={n} rep={rep} {sname}: {t1-t0:.1f} ms")
                del ads
                gc.collect()
    write_csv(f"e1_build_{ds}.csv", ["scheme", "size", "rep", "build_ms"], rows)
    data = agg(rows, [0, 1], 3)
    line_plot(data, schemes, sizes, f"ADS Construction ({ds})",
              "Construction time (ms)", f"e1_build_{ds}.png")


# ---------------- E2/E3/E4: VO 构建 / 验证 / 大小 ----------------
def run_e234(sizes, reps, schemes, ds):
    print(f"[E2/3/4] VO generation / verification / size ({ds})")
    rows_gen, rows_ver, rows_size = [], [], []
    for n in sizes:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            rng = random.Random(SEED + rep)
            for sname in schemes:
                ads = SCHEMES[sname]()
                ads.build(facts)
                k = SAMPLES[sname]
                mem_targets = rng.sample(facts, k)
                non_targets = make_absent_elements(facts, k, seed=SEED + rep)

                for pi, targets, gen in (
                        ("mem", mem_targets, ads.gen_mem),
                        ("nonmem", non_targets, ads.gen_nonmem)):
                    vos = []
                    t0 = now_ms()
                    for z in targets:
                        vos.append(gen(z))
                    t1 = now_ms()
                    rows_gen.append([sname, n, rep, pi,
                                     round((t1 - t0) / len(targets), 4)])

                    t0 = now_ms()
                    ok = all(ads.verify(vo) for vo in vos)
                    t1 = now_ms()
                    assert ok, f"{sname} {pi} verification failed!"
                    rows_ver.append([sname, n, rep, pi,
                                     round((t1 - t0) / len(vos), 4)])

                    avg_sz = sum(ads.vo_size(vo) for vo in vos) / len(vos)
                    rows_size.append([sname, n, rep, pi, round(avg_sz, 1)])
                print(f"  E234 n={n} rep={rep} {sname}: done")
                del ads
                gc.collect()
    hdr = ["scheme", "size", "rep", "pi"]
    write_csv(f"e2_vogen_{ds}.csv", hdr + ["gen_ms"], rows_gen)
    write_csv(f"e3_verify_{ds}.csv", hdr + ["verify_ms"], rows_ver)
    write_csv(f"e4_vosize_{ds}.csv", hdr + ["size_bytes"], rows_size)

    for rows, ylab, title, fname in (
            (rows_gen, "VO generation time (ms)", f"VO Generation ({ds})", f"e2_vogen_{ds}.png"),
            (rows_ver, "Verification time (ms)", f"VO Verification ({ds})", f"e3_verify_{ds}.png"),
            (rows_size, "VO size (bytes)", f"VO Size ({ds})", f"e4_vosize_{ds}.png")):
        fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
        for ax, pi, sub in ((axes[0], "mem", "Membership"),
                            (axes[1], "nonmem", "Non-membership")):
            sel = [r for r in rows if r[3] == pi]
            data = agg(sel, [0, 1], 4)
            for s in schemes:
                ys = [data[(s, x)][0] for x in sizes]
                es = [data[(s, x)][1] for x in sizes]
                ax.errorbar(sizes, ys, yerr=es, label=s, color=COLORS[s],
                            marker=MARKERS[s], capsize=3, linewidth=1.5)
            ax.set_title(sub)
            ax.set_xlabel("Facts per round")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.grid(alpha=0.3)
        axes[0].set_ylabel(ylab)
        axes[0].legend()
        fig.suptitle(title)
        fig.tight_layout()
        fig.savefig(FIGS / fname, dpi=300)
        plt.close(fig)
        print(f"  saved figs/{fname}")


# ---------------- E5: 更新时间 ----------------
def run_e5(reps, schemes, ds, base_n=5000,
           batches=(10, 50, 100, 500, 1000)):
    print(f"[E5] Update time ({ds}, base round = {base_n} facts)")
    rows = []
    for rep in range(reps):
        # 多生成 max(batches) 条作为追加材料
        all_facts = generate_round(base_n + max(batches), start_file=rep,
                                   seed=SEED, dataset=ds)
        base, extra = all_facts[:base_n], all_facts[base_n:]
        for b in batches:
            for sname in schemes:
                ads = SCHEMES[sname]()
                ads.build(base)
                t0 = now_ms()
                ads.update(extra[:b])
                t1 = now_ms()
                rows.append([sname, b, rep, round(t1 - t0, 3)])
                del ads
                gc.collect()
        print(f"  E5 rep={rep}: done")
    write_csv(f"e5_update_{ds}.csv", ["scheme", "batch", "rep", "update_ms"], rows)
    data = agg(rows, [0, 1], 3)
    plt.figure(figsize=(5, 3.6))
    for s in schemes:
        ys = [data[(s, b)][0] for b in batches]
        es = [data[(s, b)][1] for b in batches]
        plt.errorbar(batches, ys, yerr=es, label=s, color=COLORS[s],
                     marker=MARKERS[s], capsize=3, linewidth=1.5)
    plt.xlabel("Appended batch size")
    plt.ylabel("Update time (ms)")
    plt.title(f"Round Update ({ds}, base = {base_n} facts)")
    plt.xscale("log")
    plt.yscale("log")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGS / f"e5_update_{ds}.png", dpi=300)
    plt.close()
    print(f"  saved figs/e5_update_{ds}.png")


# ---------------- E6: 泄露量表 ----------------
def run_e6(n=5000):
    print("[E6] Leakage table (n = %d)" % n)
    logn = math.ceil(math.log2(n))
    requests = ["eligible", "assign", "priority(val)", "load(val)",
                "task", "done"]
    rows = []
    for req in requests:
        for pi in ("positive", "negative"):
            # (方案, 无关明文记录数, 结构哈希数);两个 VESTA 变体泄露相同
            vesta = (0, 0)
            if pi == "positive":
                mht = (0, logn)
                smt = (0, 256)
            else:
                mht = (2, 2 * logn)      # 两个邻居明文 + 两条路径
                smt = (0, 256)           # 无明文,但 256 结构哈希
            rows.append([req, pi,
                         vesta[0], vesta[1],
                         mht[0], mht[1],
                         smt[0], smt[1]])
    write_csv("e6_leakage.csv",
              ["request", "answer",
               "VESTA_records", "VESTA_hashes",
               "MHT_records", "MHT_hashes",
               "SMT_records", "SMT_hashes"], rows)
    # LaTeX 表格源码
    tex = [r"\begin{tabular}{llcccccc}", r"\toprule",
           r"Request & Answer & \multicolumn{2}{c}{VESTA} & "
           r"\multicolumn{2}{c}{MHT} & \multicolumn{2}{c}{SMT}\\",
           r" & & rec. & hash & rec. & hash & rec. & hash\\",
           r"\midrule"]
    for r in rows:
        tex.append(f"{r[0]} & {r[1]} & {r[2]} & {r[3]} & {r[4]} & "
                   f"{r[5]} & {r[6]} & {r[7]}\\\\")
    tex += [r"\bottomrule", r"\end{tabular}"]
    (RESULTS / "e6_leakage.tex").write_text("\n".join(tex))
    print("  saved results/e6_leakage.tex")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", default="all",
                    choices=["e1", "e234", "e5", "e6", "all"])
    ap.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--schemes", nargs="+", default=list(SCHEMES),
                    choices=list(SCHEMES))
    ap.add_argument("--dataset", default="gMission",
                    choices=["gMission", "EverySender"])
    args = ap.parse_args()

    t0 = time.time()
    if args.exp in ("e1", "all"):
        run_e1(args.sizes, args.reps, args.schemes, args.dataset)
    if args.exp in ("e234", "all"):
        run_e234(args.sizes, args.reps, args.schemes, args.dataset)
    if args.exp in ("e5", "all"):
        run_e5(args.reps, args.schemes, args.dataset)
    if args.exp in ("e6", "all"):
        run_e6()
    print(f"Total wall time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
