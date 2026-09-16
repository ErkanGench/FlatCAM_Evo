import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import appWorkerStack
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

    def test_requests_every_thread_to_stop_before_waiting(self):
        events = []
        first = FakeThread('first', events, wait_results=[True])
        second = FakeThread('second', events, wait_results=[True])
        stack = self.make_stack(first, second)

        stack.quit(timeout_ms=3000)

        first_wait = next(index for index, event in enumerate(events) if event[1] == 'wait')
        requests = [event for event in events[:first_wait] if event[1] in {'interrupt', 'quit'}]
        self.assertEqual(
            requests,
            [
                ('first', 'interrupt'),
                ('first', 'quit'),
                ('second', 'interrupt'),
                ('second', 'quit'),
            ]
        )
        self.assertNotIn(('first', 'terminate'), events)
        self.assertNotIn(('second', 'terminate'), events)

    def test_shares_one_timeout_budget_across_all_threads(self):
        events = []
        first = FakeThread('first', events, wait_results=[True])
        second = FakeThread('second', events, wait_results=[True])
        stack = self.make_stack(first, second)
        clock = iter([10.0, 11.0, 12.9])

        with patch.object(
                appWorkerStack,
                'time',
                SimpleNamespace(monotonic=lambda: next(clock)),
                create=True
        ):
            stack.quit(timeout_ms=3000)

        waits = [event for event in events if event[1] == 'wait']
        self.assertEqual(waits[0], ('first', 'wait', 2000))
        self.assertGreater(waits[1][2], 0)
        self.assertLessEqual(waits[1][2], 100)

    def test_forces_thread_that_exceeds_grace_period(self):
        events = []
        thread = FakeThread('blocked', events, wait_results=[False, True])
        stack = self.make_stack(thread)

        with self.assertLogs('base', level=logging.WARNING) as messages:
            stack.quit(timeout_ms=0)

        self.assertIn(('blocked', 'terminate'), events)
        self.assertIn(('blocked', 'wait', 1000), events)
        self.assertIn('Forcing worker thread shutdown', '\n'.join(messages.output))

    def test_repeated_shutdown_is_safe(self):
        events = []
        thread = FakeThread('worker', events, wait_results=[True, True])
        stack = self.make_stack(thread)

        stack.quit(timeout_ms=3000)
        stack.quit(timeout_ms=3000)

        self.assertEqual(events.count(('worker', 'quit')), 2)
        self.assertNotIn(('worker', 'terminate'), events)

    def test_logs_when_forced_termination_does_not_finish(self):
        events = []
        thread = FakeThread('blocked', events, wait_results=[False, False])
        stack = self.make_stack(thread)

        with self.assertLogs('base', level=logging.WARNING) as messages:
            stack.quit(timeout_ms=0)
        thread.running = False

        self.assertIn('did not terminate', '\n'.join(messages.output))


if __name__ == '__main__':
    unittest.main()
