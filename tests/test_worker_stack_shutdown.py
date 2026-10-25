import unittest
from types import SimpleNamespace

from appWorkerStack import WorkerStack


class FakeThread:
    def __init__(self, name, events, wait_results, running=True):
        self.name = name
        self.events = events
        self.wait_results = list(wait_results)
        self.running = running

    def requestInterruption(self):
        self.events.append((self.name, 'interrupt'))

    def quit(self):
        self.events.append((self.name, 'quit'))

    def wait(self, timeout=None):
        self.events.append((self.name, 'wait', timeout))
        result = self.wait_results.pop(0) if self.wait_results else not self.running
        if result:
            self.running = False
        return result

    def isRunning(self):
        self.events.append((self.name, 'is_running'))
        return self.running

    def terminate(self):
        self.events.append((self.name, 'terminate'))


class TestWorkerStackShutdown(unittest.TestCase):
    @staticmethod
    def make_stack(*threads):
        stack = WorkerStack(workers_number=0)
        stack.threads = list(threads)
        return stack

    def test_forces_thread_that_exceeds_grace_period(self):
        events = []
        thread = FakeThread('blocked', events, wait_results=[False, True])
        stack = self.make_stack(thread)

        stack.quit(timeout_ms=0)

        self.assertIn(('blocked', 'terminate'), events)
        self.assertIn(('blocked', 'wait', 1000), events)


class FakeWorker:
    def __init__(self, name):
        self.name = name
        self.started = []
        self.worker_task_signal = SimpleNamespace(emit=self.started.append)


class TestWorkerStackDispatch(unittest.TestCase):
    @staticmethod
    def make_stack(count):
        stack = WorkerStack(workers_number=0)
        for i in range(count):
            worker = FakeWorker('w%d' % i)
            stack.load[worker.name] = 0
            stack.worker_map[worker.name] = worker
        return stack

    @staticmethod
    def task(name, priority=None):
        task = {'fcn': lambda: None, 'params': [], 'name': name}
        if priority:
            task['priority'] = priority
        return task

    @staticmethod
    def started(stack):
        return [(w.name, [t['fcn'] for t in w.started]) for w in stack.worker_map.values()]

    def test_task_does_not_wait_behind_a_long_task_while_a_worker_is_idle(self):
        stack = self.make_stack(2)
        long_task, short_task, third = (self.task(n) for n in 'abc')
        for task in (long_task, short_task, third):
            stack.add_task(task)
        w0, w1 = stack.worker_map['w0'], stack.worker_map['w1']
        self.assertEqual([t['fcn'] for t in w0.started], [long_task['fcn']])
        self.assertEqual([t['fcn'] for t in w1.started], [short_task['fcn']])
        stack.on_task_completed('w1')  # the long task of w0 still runs
        self.assertEqual([t['fcn'] for t in w1.started], [short_task['fcn'], third['fcn']])
        self.assertEqual(len(w0.started), 1)

    def test_high_task_goes_before_queued_normal_tasks(self):
        stack = self.make_stack(1)
        first, normal, high = self.task('a'), self.task('b'), self.task('c', 'high')
        for task in (first, normal, high):
            stack.add_task(task)
        worker = stack.worker_map['w0']
        stack.on_task_completed('w0')
        self.assertEqual([t['fcn'] for t in worker.started], [first['fcn'], high['fcn']])


if __name__ == '__main__':
    unittest.main()
