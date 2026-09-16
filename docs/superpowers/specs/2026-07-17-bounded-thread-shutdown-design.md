# Bounded Thread Shutdown Design

## Goal

Make application shutdown deterministic when a FlatCAM worker thread does not
finish promptly. Request graceful shutdown first, wait no more than three
seconds across the complete worker stack, and force any remaining threads to
terminate.

## Scope

- Change `WorkerStack.quit()` to use a bounded shutdown sequence.
- Preserve the existing ArgsThread shutdown sequence.
- Preserve multiprocessing pool termination and joining.
- Preserve `os._exit(ret)` in `flatcam.py` because it prevents a documented
  Windows access violation during Qt/VisPy teardown.
- Do not treat the main-thread `QThreadStorage` messages as worker-thread
  failures. They are an expected consequence of `os._exit(ret)`.

## Shutdown Sequence

`WorkerStack.quit(timeout_ms=3000)` will:

1. Request interruption and call `quit()` on every worker thread before
   waiting for any one thread.
2. Apply one shared three-second deadline to the complete thread collection.
3. Wait only for the time remaining before that deadline.
4. Call `terminate()` on each thread that is still running after the deadline.
5. Wait up to one additional second for each forced termination to complete.
6. Log a warning for every thread that requires forced termination.

The shared deadline prevents shutdown duration from growing by three seconds
for every configured worker.

## Ownership

`WorkerStack` remains responsible for its worker threads. `AppLifecycle` calls
`workers.quit()` but does not duplicate thread iteration or manipulate the
stack's internal lists. This keeps shutdown behavior next to thread creation.

## Error Handling

- An already-stopped thread is skipped after the graceful quit request.
- A failed forced wait is logged, after which application shutdown continues.
- Shutdown must not wait indefinitely.
- `WorkerStack.__del__()` continues to call `quit()`, so cleanup outside the
  normal application path also remains bounded.

## Testing

Add focused unit tests using controlled thread doubles:

- all threads receive interruption and quit requests before waiting starts;
- threads that finish within the shared deadline are not terminated;
- a thread that exceeds the deadline is terminated and waited on again;
- the total graceful wait budget is shared rather than applied per thread;
- repeated `quit()` calls remain safe.

After implementation, run the complete unittest suite and the real desktop
startup/shutdown smoke test. The smoke test must reach the end of the App
constructor, close normally, and exit with code zero without forced process
termination.
