# -*- coding: utf-8 -*-
"""模拟层:扮演平台,把 gMission 事件流转成一轮的事实流(不计时)。

事实类型(与论文第5章一一对应):
  ("Task", tid, rid, com_l, r, e, d)      发布存证(5.1)
  ("TaskKey", tid)                         发布存证(5.1)
  ("TaskCount", k, n_k)                    轮末计数(5.1)
  ("Priority", wid, pb)                    轮始快照(5.2.1)
  ("Load", wid, cb)                        轮始快照(5.2.1)
  ("Eligible", tid, wid)                   分配事实(5.2.1)
  ("Assign", tid, wid)                     分配事实(5.2.1)
  ("Done", tid, wid, h_sig)                完成事实(5.3.1)
  ("DoneKey", tid, wid)                    完成事实(5.3.1)
"""
import math
import random
import hashlib

from sim.loader import load_stream, TaskEvent, WorkerEvent

# 桶边界(公开系统参数, m_P = m_L = 5)
PRIORITY_BOUNDS = [7200, 3600, 1800, 600]   # 秒;等待>=7200s -> 桶1(最高优先)
LOAD_CAP = 4                                 # 负载 0/1/2/3/>=4 -> 桶1..5


def beta_p(waiting: float) -> int:
    for i, b in enumerate(PRIORITY_BOUNDS):
        if waiting >= b:
            return i + 1
    return 5


def beta_l(load: int) -> int:
    return min(load, LOAD_CAP) + 1


class _Worker:
    __slots__ = ("wid", "x", "y", "cap", "radius", "online_from", "online_to",
                 "success", "load", "last_assign")

    def __init__(self, wid, ev: WorkerEvent):
        self.wid = wid
        self.x, self.y = ev.x, ev.y
        self.cap = ev.cap
        self.radius = ev.radius
        self.online_from = ev.arrival
        self.online_to = ev.arrival + ev.dur
        self.success = ev.success
        self.load = 0           # 已分配未完成数(论文 5.2.1 的 c_w)
        self.last_assign = None  # 上次被分配时间(优先级 p_w 的依据)

WARMUP_FRAC = 0.1  # 前10%事件作为"历史轮",产生真实的负载与等待时间


def _try_assign(t: TaskEvent, pool, rng, e_ddl):
    """资格谓词 + 贪心分配,返回 (候选列表, 被选worker或None, 是否完成)。"""
    cands = []
    for w in pool:
        if w.online_from <= e_ddl and w.online_to >= t.arrival:
            if math.hypot(w.x - t.x, w.y - t.y) <= w.radius:
                cands.append(w)
    avail = [w for w in cands if w.load < w.cap]
    if not avail:
        return cands, None, False
    w_star = min(avail, key=lambda w: math.hypot(w.x - t.x, w.y - t.y))
    done = rng.random() < w_star.success
    return cands, w_star, done


def generate_round(target_n: int, start_file: int, k: int = 1, seed: int = 42,
                   dataset: str = "gMission"):
    """生成恰好 target_n 条事实的一个结算轮。

    前 WARMUP_FRAC 的事件作为"历史轮"静默处理(worker 入池、任务静默
    分配/完成,只更新负载和上次分配时间,不产事实),使轮始快照的
    Priority/Load 桶具有论文 5.2.1 的语义:c_w = 历史轮已分配未完成数,
    p_w = 距上次被分配的等待时间。"""
    rng = random.Random(seed * 1000 + start_file)
    stream = load_stream(start_file, dataset=dataset)
    facts = []
    pool = []          # 平台已注册的 worker
    wid_seq = 0
    j = 0              # 轮内任务序号(密集编号)

    # ---- 历史轮预热(静默,不产事实) ----
    n_warm = max(1, int(len(stream) * WARMUP_FRAC))
    for ev in stream[:n_warm]:
        if isinstance(ev, WorkerEvent):
            wid_seq += 1
            pool.append(_Worker(f"w{wid_seq}", ev))
        else:
            _, w_star, done = _try_assign(ev, pool, rng,
                                          ev.arrival + ev.dur)
            if w_star is not None:
                w_star.last_assign = ev.arrival
                if done:
                    pass            # 已完成:不计入未完成负载
                else:
                    w_star.load += 1

    round_start = stream[n_warm].arrival

    # ---- 轮始快照:已注册 worker 的 Priority / Load(5.2.1) ----
    for w in pool:
        since = w.last_assign if w.last_assign is not None else w.online_from
        waiting = max(0.0, round_start - since)
        facts.append(("Priority", w.wid, beta_p(waiting)))
        facts.append(("Load", w.wid, beta_l(w.load)))

    # ---- 顺序消费本轮事件 ----
    for ev in stream[n_warm:]:
        if len(facts) >= target_n - 1:
            break
        if isinstance(ev, WorkerEvent):
            wid_seq += 1
            pool.append(_Worker(f"w{wid_seq}", ev))
            continue

        # 任务事件:发布存证(5.1)
        t: TaskEvent = ev
        j += 1
        tid = f"{k}-{j}"
        rid = f"r{rng.randrange(100)}"
        com_l = hashlib.sha256(
            f"{t.x:.6f},{t.y:.6f},{rng.getrandbits(128)}".encode()).hexdigest()
        e_ddl = t.arrival + t.dur
        facts.append(("Task", tid, rid, com_l, t.reward, round(e_ddl, 1),
                      t.dur))
        facts.append(("TaskKey", tid))

        # 分配事实(5.2.1):资格谓词 + 贪心分配
        cands, w_star, done = _try_assign(t, pool, rng, e_ddl)
        for w in cands:
            facts.append(("Eligible", tid, w.wid))
        if w_star is not None:
            facts.append(("Assign", tid, w_star.wid))
            w_star.load += 1
            w_star.last_assign = t.arrival
            # 完成事实(5.3.1):auditor 签名用随机字节模拟,
            # Done 与 DoneKey 原子地同时插入(第6章 completeness 的前提)
            if done:
                sig = rng.getrandbits(512).to_bytes(64, "big")
                h_sig = hashlib.sha256(sig).hexdigest()
                facts.append(("Done", tid, w_star.wid, h_sig))
                facts.append(("DoneKey", tid, w_star.wid))
                w_star.load -= 1   # 完成后不再计入未完成负载

    # ---- 轮末计数,截断到精确 target_n ----
    facts.append(("TaskCount", k, j))
    return facts[:target_n]


def make_absent_elements(facts, m: int, seed: int = 42):
    """构造 m 个保证不在事实集中的元素(用于非成员证明)。"""
    rng = random.Random(seed + 7)
    present = set(facts)
    out = []
    i = 0
    while len(out) < m:
        i += 1
        z = ("DoneKey", f"9-{rng.randrange(10**6)}", f"wx{i}")
        if z not in present:
            out.append(z)
    return out
