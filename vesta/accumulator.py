# -*- coding: utf-8 -*-
"""RSA 累加器(论文 3.2 + 5.2.1):Acc、成员/非成员 witness、增量更新。

平台不知道 trapdoor,所以所有运算都是诚实的大数模幂。
"""
import random
import gmpy2

MOD_BITS = 2048   # 默认(安全变体);效率变体用 256(对齐 Wu2023)


def setup(bits: int = MOD_BITS, seed: int = 42):
    """一次性 setup(论文中由 auditor 执行,不计入测量)。

    偏差说明:论文 5.2.1 要求 p,q 为安全素数;此处用普通随机素数代替,
    因为 setup 是一次性操作、不参与任何计时,且实验中不使用 trapdoor,
    安全素数与否不影响所有被测操作的代价。"""
    rs = random.Random(seed)
    half = bits // 2
    p = gmpy2.next_prime(rs.getrandbits(half) | (1 << (half - 1)) | 1)
    q = gmpy2.next_prime(rs.getrandbits(half) | (1 << (half - 1)) | 1)
    N = p * q
    a = gmpy2.mpz(rs.randrange(2, 1 << 64))
    g = gmpy2.powmod(a, 2, N)  # 落入二次剩余群
    return N, g


def tree_prod(xs):
    """二叉树乘法(Wu2023 同款),计算素数乘积。"""
    if not xs:
        return gmpy2.mpz(1)
    xs = list(xs)
    while len(xs) > 1:
        nxt = [xs[i] * xs[i + 1] for i in range(0, len(xs) - 1, 2)]
        if len(xs) % 2:
            nxt.append(xs[-1])
        xs = nxt
    return xs[0]


class RSAAccumulator:
    def __init__(self, N, g):
        self.N = N
        self.g = g
        self.E = gmpy2.mpz(1)   # 总指数(所有素数之积),平台缓存
        self.acc = g

    def build(self, primes):
        self.primes = list(primes)
        self.E = tree_prod(self.primes)
        self.acc = gmpy2.powmod(self.g, self.E, self.N)
        return self.acc

    def all_mem_witnesses(self):
        """分治批量预计算全部成员 witness(RootFactor 风格)。

        递归对半分:左半的 witness 底数先升幂右半乘积,反之亦然;
        总代价 O(log n) 个全长模幂,摊销到单 witness 仅毫秒级。"""
        def rec(base, xs):
            if len(xs) == 1:
                return {xs[0]: base}
            mid = len(xs) // 2
            left, right = xs[:mid], xs[mid:]
            base_l = gmpy2.powmod(base, tree_prod(right), self.N)
            base_r = gmpy2.powmod(base, tree_prod(left), self.N)
            out = rec(base_l, left)
            out.update(rec(base_r, right))
            return out
        return rec(self.g, self.primes)

    def update(self, new_primes):
        """轮内追加:Acc' = Acc^(prod new) mod N。

        论文 5.2.1 Update 段的素性校验由 auditor/挑战者在链下执行,
        不属于平台更新动作,故不在此处(亦不计入 E5 测时)。"""
        pr = tree_prod(new_primes)
        self.E *= pr
        self.acc = gmpy2.powmod(self.acc, pr, self.N)
        return self.acc

    # ---- witness 生成(平台侧) ----
    def mem_witness(self, x):
        assert self.E % x == 0, "element not in accumulator"
        return gmpy2.powmod(self.g, self.E // x, self.N)

    def nonmem_witness(self, x):
        g0, a, b = gmpy2.gcdext(self.E, x)   # a*E + b*x = 1
        assert g0 == 1, "element unexpectedly divides E"
        B = gmpy2.powmod(self.g, b, self.N)
        return (a, B)

    # ---- 验证(verifier 侧,只依赖公开 N,g,acc) ----
    def verify_mem(self, x, w, acc=None):
        acc = self.acc if acc is None else acc
        return gmpy2.powmod(w, x, self.N) == acc

    def verify_nonmem(self, x, wit, acc=None):
        acc = self.acc if acc is None else acc
        a, B = wit
        lhs = gmpy2.powmod(acc, a, self.N) * gmpy2.powmod(B, x, self.N) % self.N
        return lhs == self.g
