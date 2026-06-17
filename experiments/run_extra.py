# -*- coding: utf-8 -*-
"""补充实验 A1/A2/A4。

A1 争议裁决(对应论文 5.2.3):
   - 违规 bundle:6 个元素证明(3成员+1非成员+2取值成员),测生成/验证/大小;
   - 桶号不一致 bundle(VESTA worst case):k 个非成员证明 + 1 个成员证明。
A2 批量 witness 预计算(RootFactor):naive 单个生成 vs 批量摊销。
A4 平台侧 ADS 存储开销。

用法: python experiments/run_extra.py --exp a1|a2|a4|all [--dataset gMission]
"""
import argparse
import csv
import gc
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 全局样式:新罗马、黑色、无网格
plt.rcParams.update({
    "font.family": "Times New Roman",
    "mathtext.fontset": "stix",
    "text.color": "black",
    "axes.labelcolor": "black",
    "axes.edgecolor": "black",
    "xtick.color": "black",
    "ytick.color": "black",
    "axes.grid": False,
})

from sim.simulator import generate_round
from vesta.scheme import Vesta
from baselines.mht import MHT
from baselines.smt import SMT

RESULTS = ROOT / "results"
FIGS = ROOT / "figs" / "paper"
FIGS.mkdir(exist_ok=True, parents=True)
IMAGE_EX = ROOT.parent / "image_ex"

SIZES = [500, 1000, 2000, 5000, 10000]
SEED = 42
SCHEMES = {"VESTA-256": lambda: Vesta(256),
           "VESTA-2048": lambda: Vesta(2048),
           "MHT": MHT,
           "SMT": SMT}
COLORS = {"VESTA-256": "#295A8C", "VESTA-2048": "#529442",
          "MHT": "#637384", "SMT": "#BD8C7B"}

# 字体大一号
FS_LABEL = 13
FS_TICK = 12
FS_LEGEND = 11


def grouped_bar(ax, xs, series):
    """series: list of {ys, color, label};以分组柱状绘制(无误差棒)。"""
    n = len(series)
    total_w = 0.8
    bw = total_w / n
    idx = list(range(len(xs)))
    for i, sr in enumerate(series):
        pos = [j - total_w / 2 + bw * (i + 0.5) for j in idx]
        ax.bar(pos, sr["ys"], width=bw, label=sr.get("label"),
               color=sr["color"], edgecolor="black", linewidth=0.4)
    ax.set_xticks(idx)
    ax.set_xticklabels([str(x) for x in xs])


def finish(ax, ncol=None, gap=0.06):
    """图例放框内顶部:自动缩字号防超宽 + 按图例高度自适应留白(贴近柱子、不重叠)。"""
    handles, labels = ax.get_legend_handles_labels()
    if ncol is None:
        ncol = len(labels)
    if len(labels) == 6 and ncol == 2:
        order = [0, 2, 4, 1, 3, 5]
        handles = [handles[i] for i in order]
        labels = [labels[i] for i in order]
    fig = ax.figure
    fs = FS_LEGEND
    while True:
        leg = ax.legend(handles, labels, loc="upper center", ncol=ncol,
                        frameon=False, fontsize=fs, columnspacing=1.0,
                        handletextpad=0.4, handlelength=1.3, labelspacing=0.3)
        fig.canvas.draw()
        if leg.get_window_extent().width <= ax.get_window_extent().width * 0.96 \
                or fs <= 7:
            break
        fs -= 1
    legH = leg.get_window_extent().height / ax.get_window_extent().height
    heights = [p.get_height() for p in ax.patches if p.get_height() > 0]
    if heights:
        dmax = max(heights)
        y0 = ax.get_ylim()[0]
        f_bar = max(0.5, 1.0 - legH - gap)
        ax.set_ylim(y0, y0 * (dmax / y0) ** (1.0 / f_bar))


def now_ms():
    return time.perf_counter_ns() / 1e6


def write_csv(name, header, rows):
    with open(RESULTS / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  saved results/{name} ({len(rows)} rows)")


def agg(rows, kc, vc):
    b = defaultdict(list)
    for r in rows:
        b[tuple(r[c] for c in kc)].append(float(r[vc]))
    return {k: (sum(v) / len(v),
                (sum((x - sum(v) / len(v)) ** 2 for x in v) / len(v)) ** 0.5)
            for k, v in b.items()}


def style(ax, xl, yl):
    ax.set_xlabel(xl, fontsize=FS_LABEL)
    ax.set_ylabel(yl, fontsize=FS_LABEL)
    ax.set_yscale("log")
    ax.tick_params(labelsize=FS_TICK)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(FIGS / name, dpi=300)
    plt.close(fig)
    if IMAGE_EX.exists():
        shutil.copy(FIGS / name, IMAGE_EX / name)
    print(f"  saved figs/paper/{name}")


# ---------------- A1: 争议裁决 ----------------
def violation_targets(facts):
    """组装违规 bundle 的6个目标:eligible成员、assign非成员、竞争者assign成员、
    双方priority取值、本人load取值(论文 5.2.3)。

    小轮次可能缺某些事实类型(快照占满),此时用任意已承诺事实代位:
    witness 的生成/验证代价与事实内容无关,不影响测量。"""
    fs = set(facts)

    def pick(typ, fallback_i):
        return next((f for f in facts if f[0] == typ),
                    facts[fallback_i % len(facts)])

    elig = next((f for f in facts
                 if f[0] == "Eligible" and ("Assign", f[1], f[2]) not in fs),
                None)
    if elig is not None:
        absent = ("Assign", elig[1], elig[2])
    else:                       # 无合适 Eligible 时,用等价代价的合成缺席元素
        elig = pick("Eligible", 0)
        absent = ("Assign", "8-0", "wx-absent")
    assign = pick("Assign", 1)
    prios = [f for f in facts if f[0] == "Priority"][:2]
    while len(prios) < 2:
        prios.append(facts[len(prios) + 2])
    load = pick("Load", 4)
    return [("mem", elig), ("nonmem", absent), ("mem", assign),
            ("mem", prios[0]), ("mem", prios[1]), ("mem", load)]


def run_a1_violation(ds, reps=5):
    print(f"[A1] violation bundle ({ds})")
    rows = []
    for n in SIZES:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            targets = violation_targets(facts)
            for sname, cls in SCHEMES.items():
                ads = cls()
                ads.build(facts)
                t0 = now_ms()
                vos = [ads.gen_mem(z) if pi == "mem" else ads.gen_nonmem(z)
                       for pi, z in targets]
                t1 = now_ms()
                ok = all(ads.verify(vo) for vo in vos)
                t2 = now_ms()
                assert ok, f"{sname} bundle verification failed"
                size = sum(ads.vo_size(vo) for vo in vos)
                rows.append([sname, n, rep, round(t1 - t0, 3),
                             round(t2 - t1, 3), size])
                del ads
                gc.collect()
        print(f"  A1-violation n={n}: done")
    write_csv(f"a1_violation_{ds}.csv",
              ["scheme", "size", "rep", "gen_ms", "verify_ms", "size_bytes"],
              rows)
    # 图:bundle 总大小 vs 轮规模
    tag = ds.lower()
    d = agg(rows, [0, 1], 5)
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    series = [{"ys": [d[(s, n)][0] / 1024 for n in SIZES],
               "es": [d[(s, n)][1] / 1024 for n in SIZES],
               "color": COLORS[s], "label": s} for s in SCHEMES]
    grouped_bar(ax, SIZES, series)
    style(ax, "Facts per round", "Bundle size (KB)")
    finish(ax)
    save(fig, f"a1_bundle_size_{tag}.png")


def run_a1_bucket(ds, reps=3, base_n=2000, ks=(50, 100, 200, 500)):
    print(f"[A1] bucket-inconsistency bundle ({ds}, base={base_n})")
    rows = []
    for rep in range(reps):
        facts = generate_round(base_n, start_file=rep, seed=SEED, dataset=ds)
        ads = Vesta(2048)        # 桶号不一致用安全变体(保守/headline 配置)
        ads.build(facts)
        load_fact = next(f for f in facts if f[0] == "Load")
        for k in ks:
            absent = [("Assign", f"8-{i}", "wq1") for i in range(k)]
            t0 = now_ms()
            vos = [ads.gen_mem(load_fact)] + \
                  [ads.gen_nonmem(z) for z in absent]
            t1 = now_ms()
            ok = all(ads.verify(vo) for vo in vos)
            t2 = now_ms()
            assert ok
            size = sum(ads.vo_size(vo) for vo in vos)
            rows.append([k, rep, round(t1 - t0, 1), round(t2 - t1, 2), size])
            print(f"  A1-bucket k={k} rep={rep}: gen={t1-t0:.0f}ms")
        del ads
        gc.collect()
    write_csv(f"a1_bucket_{ds}.csv",
              ["k", "rep", "gen_ms", "verify_ms", "size_bytes"], rows)
    tag = ds.lower()
    dg = agg(rows, [0], 2)
    dv = agg(rows, [0], 3)
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    series = [
        {"ys": [dg[(k,)][0] for k in ks], "es": [dg[(k,)][1] for k in ks],
         "color": "#295A8C", "label": "Generation"},
        {"ys": [dv[(k,)][0] for k in ks], "es": [dv[(k,)][1] for k in ks],
         "color": "#ADDEEF", "label": "Verification"},
    ]
    grouped_bar(ax, ks, series)
    style(ax, "Ruled-out task set size", "Time (ms)")
    finish(ax)
    save(fig, f"a1_bucket_{tag}.png")


# ---------------- A2: 批量 witness 预计算 ----------------
def run_a2(ds, reps=5):
    print(f"[A2] batch witness precomputation ({ds})")
    rows = []
    for n in SIZES:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            ads = Vesta(2048)        # 批量预计算用安全变体
            ads.build(facts)
            t0 = now_ms()
            wits = ads.batch_mem_witnesses()
            t1 = now_ms()
            assert len(wits) == len(set(ads.acc.primes))
            rows.append([n, rep, round(t1 - t0, 1),
                         round((t1 - t0) / n, 4)])
            del ads, wits
            gc.collect()
        print(f"  A2 n={n}: done")
    write_csv(f"a2_batch_{ds}.csv",
              ["size", "rep", "total_ms", "amortized_ms"], rows)
    # 图:naive(取自 e2 csv)vs 批量摊销
    tag = ds.lower()
    naive_rows = list(csv.DictReader(open(RESULTS / f"e2_vogen_{ds}.csv")))
    nb = defaultdict(list)
    for r in naive_rows:
        if r["scheme"] == "VESTA-2048" and r["pi"] == "mem":
            nb[int(r["size"])].append(float(r["gen_ms"]))
    naive = {k: sum(v) / len(v) for k, v in nb.items()}
    d = agg(rows, [0], 3)
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    series = [
        {"ys": [naive[n] for n in SIZES], "es": None,
         "color": "#295A8C", "label": "On-demand"},
        {"ys": [d[(n,)][0] for n in SIZES],
         "es": [d[(n,)][1] for n in SIZES],
         "color": "#ADDEEF", "label": "Precomputed (amortized)"},
    ]
    grouped_bar(ax, SIZES, series)
    style(ax, "Facts per round", "Witness generation (ms)")
    finish(ax)
    save(fig, f"a2_batch_{tag}.png")


# ---------------- A4: ADS 存储 ----------------
def run_a4(ds, reps=3):
    print(f"[A4] ADS storage ({ds})")
    rows = []
    for n in SIZES:
        for rep in range(reps):
            facts = generate_round(n, start_file=rep, seed=SEED, dataset=ds)
            for sname, cls in SCHEMES.items():
                ads = cls()
                ads.build(facts)
                rows.append([sname, n, rep, ads.ads_bytes()])
                del ads
                gc.collect()
        print(f"  A4 n={n}: done")
    write_csv(f"a4_storage_{ds}.csv",
              ["scheme", "size", "rep", "bytes"], rows)
    tag = ds.lower()
    d = agg(rows, [0, 1], 3)
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    series = [{"ys": [d[(s, n)][0] / 2**20 for n in SIZES], "es": None,
               "color": COLORS[s], "label": s} for s in SCHEMES]
    grouped_bar(ax, SIZES, series)
    style(ax, "Facts per round", "ADS storage (MB)")
    finish(ax)
    save(fig, f"a4_storage_{tag}.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", default="all", choices=["a1", "a2", "a4", "all"])
    ap.add_argument("--dataset", default="all",
                    choices=["gMission", "EverySender", "all"])
    args = ap.parse_args()
    datasets = ["gMission", "EverySender"] if args.dataset == "all" \
        else [args.dataset]
    t0 = time.time()
    for ds in datasets:
        if args.exp in ("a1", "all"):
            run_a1_violation(ds)
            run_a1_bucket(ds)
        if args.exp in ("a2", "all"):
            run_a2(ds)
        if args.exp in ("a4", "all"):
            run_a4(ds)
    print(f"Total wall time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
