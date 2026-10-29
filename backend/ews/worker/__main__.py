"""python -m ews.worker (design/01 §1.2). M0: heartbeat only; the work is added in later milestones."""
from ews.common.process import run

if __name__ == "__main__":
    run("worker")
