# -*- coding: utf-8 -*-
"""gMission 数据解析。

文件格式:
  首行: <worker数> <task数> <参数> <总记录数>
  任务行:   arrival t x y dur reward
  worker行: arrival w x y cap radius dur success
"""
from dataclasses import dataclass
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class TaskEvent:
    arrival: float
    x: float
    y: float
    dur: float      # 截止时长(e = arrival + dur)
    reward: float


@dataclass
class WorkerEvent:
    arrival: float
    x: float
    y: float
    cap: int
    radius: float
    dur: float      # 在线时长
    success: float  # 完成成功率


def load_file(idx: int, dataset: str = "gMission"):
    """读取 data_0{idx}.txt,返回按到达时间排序的事件列表。"""
    path = DATA_ROOT / dataset / f"data_{idx:02d}.txt"
    events = []
    with open(path) as f:
        lines = f.read().splitlines()
    for line in lines[1:]:  # 跳过头部
        tok = line.split()
        if len(tok) < 2:
            continue
        if tok[1] == "t":
            events.append(TaskEvent(float(tok[0]), float(tok[2]), float(tok[3]),
                                    float(tok[4]), float(tok[5])))
        elif tok[1] == "w":
            events.append(WorkerEvent(float(tok[0]), float(tok[2]), float(tok[3]),
                                      int(float(tok[4])), float(tok[5]),
                                      float(tok[6]), float(tok[7])))
    events.sort(key=lambda e: e.arrival)
    return events


def load_stream(start_idx: int, n_files: int = 10, dataset: str = "gMission"):
    """从 data_{start_idx} 开始顺序拼接多个文件成一条连续事件流。

    后续文件的时间整体平移,保证到达时间单调。"""
    stream = []
    offset = 0.0
    for i in range(n_files):
        evs = load_file((start_idx + i) % 10, dataset)
        for e in evs:
            e.arrival += offset
        stream.extend(evs)
        offset = stream[-1].arrival + 1.0
    return stream
