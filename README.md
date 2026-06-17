# VESTA 实验代码

链下实验:事实集/完备元素构造、VO 构造、验证。

## 运行

```bash
pip install gmpy2 matplotlib numpy
python experiments/run.py --exp all         
python experiments/run.py --exp e1 --sizes 500 --reps 2   
```

输出:`results/*.csv`(原始数据)、`figs/*.png`(300dpi)、`results/e6_leakage.tex`(LaTeX 表)。

## 代码 ↔ 论文第5章 映射

| 代码 | 论文 |
|---|---|
| `sim/simulator.py` 事实生成 | 5.1 Task/TaskKey/TaskCount;5.2.1 四类分配事实(轮始快照);5.3.1 Done/DoneKey(原子插入) |
| `vesta/prime.py` | 5.2.1 Prime representation(分隔符拼接→SHA256→截128位→不小于其的最小素数) |
| `vesta/accumulator.py` | 3.2 累加器定义;5.2.1 Accumulation(每轮一个 Acc)与 Update(Acc'=Acc^∏x) |
| `vesta/scheme.py` VO 五元组 (z,π,wit,payload,meta) | 5.2.2 Definition(VO) |
| `baselines/mht.py` | 排序 Merkle 树(非成员证明暴露两邻居明文,即 Intro Challenge 2 批判的泄露) |
| `baselines/smt.py` | 稀疏 Merkle 树,深度256,无压缩 |
| `experiments/run.py` E1–E6 | 实验章六组指标 |

## 与论文的已声明偏差(均不影响测量结论)

1. **Setup 用普通素数**而非安全素数:setup 一次性、不计时、实验不用 trapdoor;
2. **Update 的素性校验不计时**:论文中该校验由 auditor/挑战者链下执行,非平台动作;
3. **元素级 vs 请求级**:E2–E4 按单元素证明测量;论文的 `done` 正向请求 = 2 个元素证明 + 64B payload(sig)+ 一次验签,可由元素级数据线性合成;
4. **模拟参数**:轮 = 事实数攒满目标即关;前 10% 事件为"历史轮"预热(产生真实负载/等待时间);贪心分配;按数据集成功率字段抽样完成;桶 m_P=m_L=5;seed=42。

## 数据

`gMission/data_0x.txt`(GOMA 仓库格式):
任务行 `arrival t x y dur reward`;worker 行 `arrival w x y cap radius dur success`。
10 个文件 = 10 次独立重复(第 r 次从 data_0r 起拼接)。
