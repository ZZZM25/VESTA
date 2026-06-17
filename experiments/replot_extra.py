# -*- coding: utf-8 -*-
"""仅从已有 results/*.csv 重绘 A1/A2/A4 图(不重算实验)。

复用 run_extra 的新样式(柱状图、新罗马、无网格、color 板)。
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: F401  (rcParams set in run_extra)

from experiments.run_extra import (
    RESULTS, SIZES, COLORS, grouped_bar, style, save, agg, finish,
)

DATASETS = ["gMission", "EverySender"]
SCHEMES = ["VESTA-256", "VESTA-2048", "MHT", "SMT"]


def read_rows(name):
    """读 CSV 为位置索引的 list(跳过表头),数值列保持字符串由 agg 转 float。"""
    with open(RESULTS / name) as f:
        return [row for row in csv.reader(f)][1:]


def replot_a1_bundle(ds):
    tag = ds.lower()
    rows = read_rows(f"a1_violation_{ds}.csv")  # scheme,size,rep,gen,ver,size
    d = agg(rows, [0, 1], 5)
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    series = [{"ys": [d[(s, str(n))][0] / 1024 for n in SIZES],
               "es": [d[(s, str(n))][1] / 1024 for n in SIZES],
               "color": COLORS[s], "label": s} for s in SCHEMES]
    grouped_bar(ax, SIZES, series)
    style(ax, "Facts per round", "Bundle size (KB)")
    finish(ax)
    save(fig, f"a1_bundle_size_{tag}.png")


def replot_a1_bucket(ds):
    tag = ds.lower()
    rows = read_rows(f"a1_bucket_{ds}.csv")  # k,rep,gen_ms,verify_ms,size
    ks = sorted({int(r[0]) for r in rows})
    dg = agg(rows, [0], 2)
    dv = agg(rows, [0], 3)
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    series = [
        {"ys": [dg[(str(k),)][0] for k in ks],
         "es": [dg[(str(k),)][1] for k in ks],
         "color": "#295A8C", "label": "Generation"},
        {"ys": [dv[(str(k),)][0] for k in ks],
         "es": [dv[(str(k),)][1] for k in ks],
         "color": "#ADDEEF", "label": "Verification"},
    ]
    grouped_bar(ax, ks, series)
    style(ax, "Ruled-out task set size", "Time (ms)")
    finish(ax)
    save(fig, f"a1_bucket_{tag}.png")


def replot_a4(ds):
    tag = ds.lower()
    rows = read_rows(f"a4_storage_{ds}.csv")  # scheme,size,rep,bytes
    d = agg(rows, [0, 1], 3)
    fig, ax = plt.subplots(figsize=(3.6, 2.9))
    series = [{"ys": [d[(s, str(n))][0] / 2**20 for n in SIZES], "es": None,
               "color": COLORS[s], "label": s} for s in SCHEMES]
    grouped_bar(ax, SIZES, series)
    style(ax, "Facts per round", "ADS storage (MB)")
    finish(ax)
    save(fig, f"a4_storage_{tag}.png")


if __name__ == "__main__":
    for ds in DATASETS:
        replot_a1_bundle(ds)
        replot_a1_bucket(ds)
        replot_a4(ds)
    print("A-figures replotted from CSV.")
