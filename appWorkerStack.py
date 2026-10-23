
import logging
import time
from collections import deque

from PyQt6 import QtCore
from appWorker import Worker


class WorkerStack(QtCore.QObject):
    """
    Manages a pool of Worker threads with a central task queue.

    HIGH and NORMAL priority tasks wait in one FIFO queue (HIGH first). A task goes to a worker
    only when that worker is idle, so no task waits behind a long task of a busy worker while
    another worker is free.

    LOW priority tasks have BARRIER semantics: they are held in a
    deferred list and only dispatched when no high/normal task is queued or running.
    This guarantees finalization tasks (like plot_all) run after all regular work is done.

    Priority levels:
        'high'   (0)  — Queued before the normal tasks
        'normal' (5)  — Default. Given to the next idle worker
        'low'    (10) — Barrier: deferred until no high/normal task is queued or running

    Usage:
        # Normal (default — no 'priority' key needed):
        app.worker_task.emit({'fcn': my_func, 'params': [arg1, arg2]})

        # Low priority — waits for ALL normal tasks to complete first:
        app.worker_task.emit({'fcn': cleanup_func, 'params': [], 'priority': 'low'})
    """

    thread_exception = QtCore.pyqtSignal(object)

    # Priority constants (lower number = higher priority)
    PRIORITY_HIGH = 0
    PRIORITY_NORMAL = 5
    PRIORITY_LOW = 10  # Barrier: deferred until all other tasks complete

    # Map string names to numeric values
    _PRIORITY_MAP = {
        'high': PRIORITY_HIGH,
        'normal': PRIORITY_NORMAL,
        'low': PRIORITY_LOW
    }

    def __init__(self, workers_number):
        super(WorkerStack, self).__init__()

        self.workers = []
        self.threads = []
        self.load = {}                              # {'worker_name': 1 if it runs a task else 0}
        self.worker_map = {}                        # 'worker_name' -> Worker instance

        self._high_queue = deque()                  # HIGH tasks waiting for an idle worker
        self._normal_queue = deque()                # NORMAL tasks waiting for an idle worker
        self._deferred_tasks = []                   # LOW priority tasks waiting for barrier
        self._low_running = set()                   # workers that run a LOW task now

        # Create workers crew
        for i in range(0, workers_number):
            worker = Worker(self, 'Slogger-' + str(i))
            thread = QtCore.QThread()

            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.task_completed.connect(self.on_task_completed)

            thread.start(QtCore.QThread.Priority.LowPriority)

            self.workers.append(worker)
            self.threads.append(thread)
            self.load[worker.name] = 0
            self.worker_map[worker.name] = worker

    def add_task(self, task):
        """
        Add a task for execution. It waits in the central queue until a worker is idle.

        HIGH tasks go before the queued NORMAL tasks. LOW tasks are deferred until no high/normal
        task is queued or running (barrier).

        :param task: dict with keys:
            'fcn'      — callable to execute (required)
            'params'   — list of arguments (required)
            'priority' — 'high', 'normal' (default), 'low', or numeric 0-10 (optional)
        """
        priority = task.get('priority', 'normal')

        # Accept both string names and numeric values
        if isinstance(priority, str):
            priority = self._PRIORITY_MAP.get(priority, self.PRIORITY_NORMAL)

        if priority >= self.PRIORITY_LOW:
            self._deferred_tasks.append(task)
        elif priority <= self.PRIORITY_HIGH:
            self._high_queue.append(task)
        else:
            self._normal_queue.append(task)
        self._dispatch()

    def on_task_completed(self, worker_name):
        """Called via signal when a worker finishes its current task."""
        worker_name = str(worker_name)
        self.load[worker_name] -= 1
        self._low_running.discard(worker_name)
        self._dispatch()

    def pending_count(self):
        """
        Return the number of tasks that are queued or run now, including the deferred low priority tasks.
        """
        return len(self._high_queue) + len(self._normal_queue) + sum(self.load.values()) + len(self._deferred_tasks)

    def _dispatch(self):
        """Give a queued task to each idle worker. The only path that starts a task (GUI thread)."""
        for worker_name in self.load:
            if self.load[worker_name]:
                continue
            low = False
            if self._high_queue:
                task = self._high_queue.popleft()
            elif self._normal_queue:
                task = self._normal_queue.popleft()
            elif self._deferred_tasks and len(self._low_running) == sum(self.load.values()):
                # the barrier: only LOW tasks run now
                task = self._deferred_tasks.pop(0)
                low = True
            else:
                break
            self.load[worker_name] = 1
            if low:
                self._low_running.add(worker_name)
            self.worker_map[worker_name].worker_task_signal.emit(
                {'worker_name': worker_name, 'fcn': task['fcn'], 'params': task['params']}
            )

    def __del__(self):
        self.quit()

    def quit(self, timeout_ms=3000):
        """Stop all worker threads within a shared timeout."""
        for thread in self.threads:
            thread.requestInterruption()
            thread.quit()

        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        for thread in self.threads:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if thread.wait(remaining_ms) or not thread.isRunning():
                continue

            logging.getLogger('base').warning("Forcing worker thread shutdown after timeout.")
            thread.terminate()
            if not thread.wait(1000):
                logging.getLogger('base').error("Worker thread did not terminate after forced shutdown.")
