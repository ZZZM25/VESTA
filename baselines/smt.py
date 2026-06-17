# -*- coding: utf-8 -*-
"""基线2:稀疏 Merkle 树(SMT),深度 256,不做路径压缩。

键 = SHA256(事实);成员与非成员证明同形:256 条兄弟哈希;
非成员 = 指向默认空叶的路径(不泄露邻居明文);
更新 = 每条 O(256) 次哈希,增量插入。
"""
from utils import serialize, sha256

DEPTH = 256
EMPTY = b"\x00" * 32

# 各层默认哈希(自底向上),全局预计算一次
DEFAULTS = [EMPTY]
for _ in range(DEPTH):
    DEFAULTS.append(sha256(DEFAULTS[-1] + DEFAULTS[-1]))


def _leaf_hash(fact):
    return sha256(b"\x01" + serialize(fact))


class SMT:
    name = "SMT"

    def __init__(self):
        # nodes[d]: 第 d 层(0=叶)的非默认节点 {前缀整数: 哈希}
        self.nodes = [dict() for _ in range(DEPTH + 1)]

    @property
    def root(self):
        return self.nodes[DEPTH].get(0, DEFAULTS[DEPTH])

    def _key(self, fact):
        return int.from_bytes(sha256(serialize(fact)), "big")

    def _insert(self, fact):
        key = self._key(fact)
        h = _leaf_hash(fact)
        cur = key
        self.nodes[0][cur] = h
        for d in range(1, DEPTH + 1):
            sib = cur ^ 1
            sib_h = self.nodes[d - 1].get(sib, DEFAULTS[d - 1])
            if cur & 1:
                h = sha256(sib_h + h)
            else:
                h = sha256(h + sib_h)
            cur >>= 1
            self.nodes[d][cur] = h

    def build(self, facts):
        self.nodes = [dict() for _ in range(DEPTH + 1)]
        for f in facts:
            self._insert(f)

    def update(self, new_facts):
        for f in new_facts:
            self._insert(f)

    def ads_bytes(self):
        n_nodes = sum(len(d) for d in self.nodes)
        return n_nodes * (32 + 8)   # 每个非默认节点:哈希32B + 前缀索引8B

    def _siblings(self, key):
        sibs = []
        cur = key
        for d in range(DEPTH):
            sibs.append(self.nodes[d].get(cur ^ 1, DEFAULTS[d]))
            cur >>= 1
        return sibs

    def gen_mem(self, fact):
        key = self._key(fact)
        assert key in self.nodes[0]
        return {"z": fact, "pi": "mem", "wit": self._siblings(key),
                "meta": {"round": 1}}

    def gen_nonmem(self, fact):
        key = self._key(fact)
        assert key not in self.nodes[0]
        return {"z": fact, "pi": "nonmem", "wit": self._siblings(key),
                "meta": {"round": 1}}

    def verify(self, vo):
        key = self._key(vo["z"])
        h = _leaf_hash(vo["z"]) if vo["pi"] == "mem" else DEFAULTS[0]
        cur = key
        for sib_h in vo["wit"]:
            if cur & 1:
                h = sha256(sib_h + h)
            else:
                h = sha256(h + sib_h)
            cur >>= 1
        return h == self.root

    def vo_size(self, vo):
        return len(serialize(vo["z"])) + 1 + 8 + 32 * DEPTH
