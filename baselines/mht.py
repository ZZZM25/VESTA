# -*- coding: utf-8 -*-
"""基线1:排序 Merkle 哈希树(MHT)。

成员证明 = log n 条兄弟路径;
非成员证明 = 左右相邻两个叶子的【明文记录】+ 各自路径(泄露来源);
更新 = 重建整树(排序树无法廉价插入)。
"""
import bisect
from utils import serialize, sha256


class MHT:
    name = "MHT"

    def __init__(self):
        self.levels = []
        self.records = []   # 排序后的 (leaf_hash, fact)
        self.keys = []

    def build(self, facts):
        recs = [(sha256(serialize(f)), f) for f in facts]
        recs.sort(key=lambda r: r[0])
        self.records = recs
        self.keys = [r[0] for r in recs]
        level = [r[0] for r in recs]
        self.levels = [level]
        while len(level) > 1:
            nxt = []
            for i in range(0, len(level), 2):
                right = level[i + 1] if i + 1 < len(level) else level[i]
                nxt.append(sha256(level[i] + right))
            level = nxt
            self.levels.append(level)

    @property
    def root(self):
        return self.levels[-1][0]

    def update(self, new_facts):
        all_facts = [f for _, f in self.records] + list(new_facts)
        self.build(all_facts)

    def ads_bytes(self):
        n_hashes = sum(len(level) for level in self.levels)
        rec_bytes = sum(len(serialize(f)) for _, f in self.records)
        return n_hashes * 32 + rec_bytes   # 全部树节点哈希 + 叶子明文记录

    def _path(self, idx):
        path = []
        for level in self.levels[:-1]:
            sib = idx ^ 1
            sib_hash = level[sib] if sib < len(level) else level[idx]
            path.append((sib_hash, idx & 1))
            idx >>= 1
        return path

    def gen_mem(self, fact):
        h = sha256(serialize(fact))
        idx = bisect.bisect_left(self.keys, h)
        assert idx < len(self.keys) and self.keys[idx] == h
        return {"z": fact, "pi": "mem", "wit": (idx, self._path(idx)),
                "meta": {"round": 1}}

    def gen_nonmem(self, fact):
        h = sha256(serialize(fact))
        i = bisect.bisect_left(self.keys, h)
        neighbors = []
        if i > 0:                       # 左邻居:明文记录 + 路径(泄露!)
            neighbors.append((i - 1, self.records[i - 1][1],
                              self._path(i - 1)))
        if i < len(self.keys):          # 右邻居
            neighbors.append((i, self.records[i][1], self._path(i)))
        return {"z": fact, "pi": "nonmem", "wit": neighbors,
                "meta": {"round": 1}}

    def _verify_path(self, leaf_hash, idx, path):
        h = leaf_hash
        for sib_hash, is_right in path:
            h = sha256(sib_hash + h) if is_right else sha256(h + sib_hash)
        return h == self.root

    def verify(self, vo):
        h = sha256(serialize(vo["z"]))
        if vo["pi"] == "mem":
            idx, path = vo["wit"]
            return self._verify_path(h, idx, path)
        # 非成员:邻居路径有效 + 相邻 + 目标哈希落在中间
        neighbors = vo["wit"]
        idxs = []
        for idx, rec, path in neighbors:
            rh = sha256(serialize(rec))
            if not self._verify_path(rh, idx, path):
                return False
            idxs.append((idx, rh))
        if len(idxs) == 2:
            (i1, h1), (i2, h2) = idxs
            return i2 == i1 + 1 and h1 < h < h2
        if len(idxs) == 1:               # 边界情形
            i1, h1 = idxs[0]
            return (i1 == 0 and h < h1) or \
                   (i1 == len(self.keys) - 1 and h > h1)
        return False

    def vo_size(self, vo):
        size = len(serialize(vo["z"])) + 1 + 8
        if vo["pi"] == "mem":
            idx, path = vo["wit"]
            size += 8 + 33 * len(path)            # 索引 + (哈希+方向位)*log n
        else:
            for idx, rec, path in vo["wit"]:
                size += 8 + len(serialize(rec)) + 33 * len(path)
        return size
