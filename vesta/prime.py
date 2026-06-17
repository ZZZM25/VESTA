# -*- coding: utf-8 -*-
"""PrimeRep:事实 -> 素数代表(论文 5.2.1 素数表示阶段)。

规范序列化 -> SHA-256 -> 截 128 位 -> 不小于该整数的最小素数。
"""
import gmpy2
from utils import serialize, sha256

PRIME_BITS = 128


def prime_rep(fact):
    h = sha256(serialize(fact))
    x = int.from_bytes(h[: PRIME_BITS // 8], "big")
    # 论文 5.2.1:"不小于该整数的最小素数"(x 本身是素数则取 x)
    if gmpy2.is_prime(x):
        return gmpy2.mpz(x)
    return gmpy2.next_prime(x)
