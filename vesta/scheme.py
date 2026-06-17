# -*- coding: utf-8 -*-
"""VESTA 方案适配器:统一接口 build / update / gen_mem / gen_nonmem / verify / vo_size。

VO = {z, pi, wit, meta}(论文 Definition: verification object)。
"""
from utils import serialize, int_bytes
from vesta.prime import prime_rep
from vesta.accumulator import RSAAccumulator, setup

# 两个变体的一次性 setup(固定种子,不计时):
#   256  -> 效率变体(对齐 Wu2023,非密码学安全)
#   2048 -> 安全变体(强 RSA 假设下可证,挂安全分析)
_PARAMS = {256: setup(256), 2048: setup(2048)}


class Vesta:
    def __init__(self, bits=2048):
        self.bits = bits
        N, g = _PARAMS[bits]
        self.acc = RSAAccumulator(N, g)
        self.name = f"VESTA-{bits}"

    # ---- 构造(E1 计时范围:PrimeRep 全部 + 树乘 + 模幂) ----
    def build(self, facts):
        primes = [prime_rep(f) for f in facts]
        self.acc.build(primes)

    # ---- 更新(E5 计时范围:新元素 PrimeRep + 树乘 + 模幂) ----
    def update(self, new_facts):
        primes = [prime_rep(f) for f in new_facts]
        self.acc.update(primes)

    # ---- VO 构造(E2) ----
    # VO = (z, pi, wit, payload, meta),与论文 Definition(VO)五元组一致。
    # 基准测试按"元素级"出证明,payload 为 None;论文中 done 正向请求
    # 额外披露 payload = sig(64B)并需验签,请求级开销 = 2 个元素证明 + 64B。
    def gen_mem(self, fact):
        x = prime_rep(fact)
        w = self.acc.mem_witness(x)
        return {"z": fact, "pi": "mem", "wit": w, "payload": None,
                "meta": {"round": 1}}

    def gen_nonmem(self, fact):
        x = prime_rep(fact)
        wit = self.acc.nonmem_witness(x)
        return {"z": fact, "pi": "nonmem", "wit": wit, "payload": None,
                "meta": {"round": 1}}

    # ---- 批量预计算(A2 实验) ----
    def batch_mem_witnesses(self):
        return self.acc.all_mem_witnesses()

    # ---- 平台侧 ADS 存储(A4 实验,字节) ----
    def ads_bytes(self):
        n = len(self.acc.primes)
        e_bytes = (self.acc.E.bit_length() + 7) // 8
        acc_bytes = (self.acc.N.bit_length() + 7) // 8   # 一个群元素=模数大小
        return n * 16 + e_bytes + acc_bytes   # 素数表 + 缓存指数 + Acc

    # ---- 验证(E3 计时范围:重算 PrimeRep + witness 验证) ----
    def verify(self, vo):
        x = prime_rep(vo["z"])
        if vo["pi"] == "mem":
            return self.acc.verify_mem(x, vo["wit"])
        return self.acc.verify_nonmem(x, vo["wit"])

    # ---- VO 大小(E4,字节) ----
    def vo_size(self, vo):
        size = len(serialize(vo["z"])) + 1 + 8  # z + pi标志 + meta(轮号)
        if vo.get("payload"):
            size += len(vo["payload"])
        if vo["pi"] == "mem":
            size += int_bytes(vo["wit"])         # 一个群元素 (~256B)
        else:
            a, B = vo["wit"]
            size += int_bytes(a) + int_bytes(B)  # Bezout系数 + 群元素
        return size
