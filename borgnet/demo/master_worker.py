"""Master/worker kill-recovery demo on top of IAC Bus queue leasing.

A ``Master`` enqueues N tasks onto a bus queue and polls a results channel
until every task has been acked (or a deadline passes). ``Worker`` threads
claim tasks, simulate work, ack them, and report completion on the results
channel. A worker with ``die_after_claim=True`` claims one task and exits
without acking, simulating death mid-lease; the bus releases the lease after
``lease_seconds`` and a surviving worker completes the task.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from borgnet.logging import get_logger
from borgnet.transport.iac_bus import IacBusClient

_log = get_logger("demo.master_worker")


class Master:
    """Enqueues tasks and tracks their completion via a results channel."""

    def __init__(
        self,
        client: IacBusClient,
        queue: str,
        results_channel: str,
        num_tasks: int,
        poll_interval_s: float = 0.2,
    ):
        self.client = client
        self.queue = queue
        self.results_channel = results_channel
        self.num_tasks = num_tasks
        self.poll_interval_s = poll_interval_s
        self.task_ids: List[str] = []
        # task_id -> list of completion reports (>1 entry means a duplicate)
        self.completions: Dict[str, List[Dict[str, Any]]] = {}
        self._since_id: Optional[str] = None
        _log.debug(
            "Master initialized: queue=%s results_channel=%s num_tasks=%d",
            queue,
            results_channel,
            num_tasks,
        )

    def enqueue_tasks(self) -> List[str]:
        """Enqueue ``num_tasks`` tasks onto the queue; return their task ids."""
        for i in range(self.num_tasks):
            task_id = f"task-{i}"
            self.client.enqueue(
                queue=self.queue,
                sender="master",
                message={"task_id": task_id, "payload": f"work item {i}"},
            )
            self.task_ids.append(task_id)
        _log.info(
            "Master enqueued %d tasks onto queue=%s", self.num_tasks, self.queue
        )
        return list(self.task_ids)

    def poll_once(self) -> None:
        """Fetch completion reports newer than the last poll cursor."""
        messages = self.client.get_messages(
            channel=self.results_channel, since_id=self._since_id, limit=200
        )
        for msg in messages:
            self._since_id = msg["id"]
            try:
                report = json.loads(msg["message"])
            except (TypeError, ValueError):
                _log.warning("Ignoring malformed completion report: %r", msg)
                continue
            task_id = report.get("task_id")
            if task_id is None:
                continue
            self.completions.setdefault(task_id, []).append(report)
            _log.info(
                "Completion report: task=%s worker=%s (count=%d)",
                task_id,
                report.get("worker"),
                len(self.completions[task_id]),
            )

    def wait_for_completion(self, deadline_s: float) -> bool:
        """Poll until every task has at least one completion or deadline passes."""
        deadline = time.monotonic() + deadline_s
        while time.monotonic() < deadline:
            self.poll_once()
            if all(task_id in self.completions for task_id in self.task_ids):
                _log.info("Master: all %d tasks completed", self.num_tasks)
                return True
            time.sleep(self.poll_interval_s)
        missing = [t for t in self.task_ids if t not in self.completions]
        _log.warning(
            "Master deadline passed: %d/%d tasks completed (missing=%s)",
            len(self.task_ids) - len(missing),
            self.num_tasks,
            missing,
        )
        return False

    @property
    def duplicates(self) -> int:
        """Number of extra completions beyond the first per task."""
        return sum(len(reports) - 1 for reports in self.completions.values())


class Worker:
    """Claim -> work -> ack loop against a bus queue.

    With ``die_after_claim=True`` the worker claims a single task and then
    exits WITHOUT acking, leaving the lease to expire on the bus.
    """

    def __init__(
        self,
        client: IacBusClient,
        queue: str,
        results_channel: str,
        worker_id: str,
        lease_seconds: float = 5,
        work_seconds: float = 0.1,
        poll_interval_s: float = 0.1,
        die_after_claim: bool = False,
        start_delay_s: float = 0.0,
    ):
        self.client = client
        self.queue = queue
        self.results_channel = results_channel
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.work_seconds = work_seconds
        self.poll_interval_s = poll_interval_s
        self.die_after_claim = die_after_claim
        self.start_delay_s = start_delay_s
        self.stop_event = threading.Event()
        self.claimed_message_ids: List[str] = []
        self.claimed_task_ids: List[str] = []
        self.completed_task_ids: List[str] = []
        self.died = False
        _log.debug(
            "Worker initialized: id=%s queue=%s die_after_claim=%s",
            worker_id,
            queue,
            die_after_claim,
        )

    def run(self) -> None:
        """Main loop: claim, simulate work, ack, report completion."""
        if self.start_delay_s:
            time.sleep(self.start_delay_s)
        while not self.stop_event.is_set():
            claimed = self.client.claim(
                queue=self.queue,
                worker=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if claimed is None:
                time.sleep(self.poll_interval_s)
                continue

            message_id = claimed["id"]
            lease_id = claimed["lease_id"]
            body = claimed.get("message") or {}
            task_id = body.get("task_id", message_id) if isinstance(body, dict) else message_id
            self.claimed_message_ids.append(message_id)
            self.claimed_task_ids.append(task_id)

            if self.die_after_claim:
                self.died = True
                _log.warning(
                    "Worker %s DYING after claim: task=%s message_id=%s "
                    "(lease will expire in %ss)",
                    self.worker_id,
                    task_id,
                    message_id,
                    self.lease_seconds,
                )
                return

            time.sleep(self.work_seconds)
            self.client.ack(
                queue=self.queue,
                worker=self.worker_id,
                message_id=message_id,
                lease_id=lease_id,
            )
            self.completed_task_ids.append(task_id)
            self.client.post_message(
                channel=self.results_channel,
                sender=self.worker_id,
                message=json.dumps(
                    {
                        "task_id": task_id,
                        "message_id": message_id,
                        "worker": self.worker_id,
                        "lease_id": lease_id,
                    }
                ),
            )
            _log.info(
                "Worker %s completed task=%s message_id=%s",
                self.worker_id,
                task_id,
                message_id,
            )
        _log.debug("Worker %s stopped", self.worker_id)

    def stop(self) -> None:
        self.stop_event.set()


def run_demo(
    bus_url: str,
    token: Optional[str] = None,
    num_tasks: int = 8,
    num_workers: int = 3,
    lease_seconds: float = 5,
    work_seconds: float = 0.1,
    deadline_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Run the master/workers kill-recovery demo against a live IAC Bus.

    One worker dies after its first claim (without acking). The demo waits
    for the lease to expire, verifies a surviving worker completes the
    orphaned task, and that all tasks complete exactly once.

    Returns a dict with ``tasks_completed``, ``duplicates``,
    ``recovered_task_ids``, ``elapsed``, and ``success``.
    """
    if deadline_s is None:
        deadline_s = max(30.0, lease_seconds * 4 + num_tasks * work_seconds * 2)

    run_id = uuid.uuid4().hex[:8]
    queue = f"borg-demo-{run_id}"
    results_channel = f"borg-demo-results-{run_id}"
    client = IacBusClient(base_url=bus_url, token=token)

    _log.info(
        "Demo starting: queue=%s tasks=%d workers=%d lease=%ss deadline=%ss",
        queue,
        num_tasks,
        num_workers,
        lease_seconds,
        deadline_s,
    )

    master = Master(
        client=client,
        queue=queue,
        results_channel=results_channel,
        num_tasks=num_tasks,
    )
    master.enqueue_tasks()

    workers: List[Worker] = []
    threads: List[threading.Thread] = []
    for i in range(num_workers):
        # Worker 0 dies after its first claim; it starts first (no delay) so
        # it reliably claims a task before the healthy workers drain the queue.
        dies = i == 0
        worker = Worker(
            client=IacBusClient(base_url=bus_url, token=token),
            queue=queue,
            results_channel=results_channel,
            worker_id=f"worker-{i}{'-doomed' if dies else ''}",
            lease_seconds=lease_seconds,
            work_seconds=work_seconds,
            die_after_claim=dies,
            start_delay_s=0.0 if dies else 0.3,
        )
        workers.append(worker)
        thread = threading.Thread(
            target=worker.run, name=worker.worker_id, daemon=True
        )
        threads.append(thread)

    start = time.monotonic()
    for thread in threads:
        thread.start()

    master.wait_for_completion(deadline_s=deadline_s)
    elapsed = time.monotonic() - start

    for worker in workers:
        worker.stop()
    for thread in threads:
        thread.join(timeout=5)

    # Drain any last reports that arrived after the final poll (a worker may
    # have acked between the master's last poll and the stop signal).
    master.poll_once()
    all_done = all(task_id in master.completions for task_id in master.task_ids)

    dead_worker = workers[0]
    survivors = workers[1:]
    completed_by_survivors = {
        task_id for w in survivors for task_id in w.completed_task_ids
    }
    recovered_task_ids = sorted(
        task_id
        for task_id in dead_worker.claimed_task_ids
        if task_id in completed_by_survivors
    )

    result = {
        "tasks_completed": len(master.completions),
        "num_tasks": num_tasks,
        "duplicates": master.duplicates,
        "recovered_task_ids": recovered_task_ids,
        "dead_worker_claimed": list(dead_worker.claimed_task_ids),
        "elapsed": round(elapsed, 2),
        "success": (
            all_done
            and len(master.completions) == num_tasks
            and master.duplicates == 0
        ),
    }
    _log.info("Demo finished: %s", result)
    return result
