# DRAFT (not posted): llmvision upstream issue for card LLMVISION-TIMEOUT-LEAK-UPSTREAM-1

Drafted 2026-11-17 ~02:06 CST, read-only probe. Nothing was posted or sent.

## Premise check (read this first)

The card says: "when the caller cancels/times out a llmvision call, the provider HTTP request keeps
running and is billed." **The installed code does not support that.** Evidence:

- `__init__.py:669-715` (`image_analyzer`) and `:718-753` (`video_analyzer`) are plain `async def` handlers that
  `await request.call(call)` directly. No `asyncio.shield`, no `create_task` / `async_create_task`,
  no `ensure_future` anywhere in `__init__.py` (grep: only a `hass.async_create_task` at `:233`, in
  config-entry migration, unrelated).
- `providers.py:157` `Request.call` awaits `provider_instance.vision_request(call)` (`:~215`) inline. Its
  `except Exception` does not catch `asyncio.CancelledError` (a `BaseException`), so a cancel propagates.
- `providers.py:527-538` `_post` awaits `self.session.post(...)` on the shared HA session
  (`async_get_clientsession`, `:76`, `:437`) with no shield. A cancel while awaiting the response aborts the
  aiohttp request on the client side.
- HA core: with `blocking=True`, `ServiceRegistry.async_call` does `response_data = await coro` where
  `coro = self._execute_service(handler, service_call)`, which does `await target(service_call)` for a coroutine
  handler (HA 2026.2.3 source in URA's `.venv-ha`, `core.py` `async_call` / `_execute_service`). So the caller's
  `asyncio.wait_for` cancel reaches the llmvision handler. **Not verified against the live core (2026.11.1);
  the local HA package is older.**
- URA wraps the call in `asyncio.wait_for(_call(), timeout=...)` with `blocking=True, return_response=True`
  (`perimeter_enrichment.py:~432-443`), so URA is on the propagating path.

What this does NOT show: whether a provider keeps generating, or bills, after the client closes the socket.
That is provider-side behaviour; unknown from our evidence. URA's own docstring only says "The provider MAY still
bill" (`perimeter_enrichment.py:25-28`), not that it was observed. No billing or provider-side measurement exists
in this repo for it (none found; not searched beyond the files above).

**What URA actually documented as the leak is different and is real in the code:** a cancel during clip fetch /
ffmpeg leaves a temp file and an ffmpeg process (`const.py:3759-3766` comment, `IDENTITY_FUSION_CAMERAS_MANUAL.md:514-517`,
commits a10cd299 and 9407eaef). Recommendation: retitle the card to "llmvision temp file + ffmpeg leak on
cancel" (not billing), and post the issue below only if the operator wants it. If the operator still wants a
billing claim, first measure it (provider usage dashboard vs a deliberately cancelled call); do not assert it.

---

## Draft issue

**Title:** `add_video` leaks a temp file and leaves ffmpeg running when the service call is cancelled (clip download / ffmpeg stage)

### Environment
- Home Assistant Core 2026.11.1 (`/config/.HA_VERSION`)
- llmvision 1.7.1 (`custom_components/llmvision/manifest.json`)
- Service: `llmvision.video_analyzer` (also reachable via `image_analyzer` paths that call `add_video`)

### What happens
When a caller cancels or times out a `llmvision.video_analyzer` call while llmvision is downloading the clip or
running ffmpeg, the cancellation propagates correctly to the handler, but cleanup is skipped:
1. `media_handlers.py:664` creates `tempfile.NamedTemporaryFile(delete=False, ...)`. It is removed only at
   `:841-845`, on the normal path, not in a `finally`. A `CancelledError` raised at `await self._fetch(...)`
   (`:666`) or later skips the removal, so one temp file per cancelled call remains.
2. ffmpeg is started with `asyncio.create_subprocess_exec` (`:701`, `:735`). The only termination code is in the
   `except asyncio.TimeoutError` branch (`:829-834`), which does not run on `CancelledError`. On cancel the
   process is not killed and keeps running until its stdout pipe closes or it exits.
3. Separately, `:833-834` reads `if ffmpeg_process.returncode is not None: ffmpeg_process.terminate()`.
   `returncode is not None` means the process has already exited, so this terminates nothing in the case it
   is meant for; it looks inverted (`is None`).

### Expected behaviour
Cancelling the call removes the temp file and terminates/reaps the ffmpeg subprocess.

### Minimal repro
Any caller that cancels a blocking service call. Run from a Developer Tools > Template-free context such as a
custom script or pyscript with `hass` available:

```python
import asyncio

async def repro(hass, slow_clip_url):
    async def call():
        return await hass.services.async_call(
            "llmvision", "video_analyzer",
            {
                "provider": "<any configured provider entry id>",
                "message": "describe",
                "video_file": slow_clip_url,   # an http(s) URL served slowly, so the cancel lands mid-download/ffmpeg
                "max_frames": 4,
            },
            blocking=True, return_response=True,
        )
    try:
        await asyncio.wait_for(call(), timeout=2)
    except asyncio.TimeoutError:
        pass
```

Then on the HA host: `ls -l /tmp/tmp*.mp4` (a new file remains per run) and `pgrep -a ffmpeg` (a process may remain
while ffmpeg is still reading). Note: we have not run this repro; it is derived from reading the code, so please
treat the exact fields (`video_file` vs `event_id`, URL vs local path) as needing confirmation. The temp-file path
is only taken for `http(s)` sources (`media_handlers.py:662-664`).

### Code pointers (llmvision 1.7.1)
- `media_handlers.py:664` temp file created with `delete=False`
- `media_handlers.py:666` `await self._fetch(...)` (cancel point before cleanup is reachable)
- `media_handlers.py:701`, `:735` `create_subprocess_exec` (no kill on cancel)
- `media_handlers.py:818` `await ffmpeg_process.wait()` (cancel point)
- `media_handlers.py:829-834` timeout-only termination, condition looks inverted
- `media_handlers.py:841-845` temp file removal not in `finally`

### Suggested fix
Wrap from temp-file creation through frame extraction in `try/finally`. In the `finally`: if the process exists and
`returncode is None`, call `kill()` (or `terminate()` then `wait()`), and `os.remove(temp_file_path)` guarded by
`os.path.exists`. Use `except asyncio.CancelledError: ...; raise` only if extra work is needed. Fix the
`returncode is not None` condition to `is None`.

### Evidence from our side
- A caller with a 90 s `asyncio.wait_for` around the service call (blocking, return_response) sees the
  cancellation reach the handler; we have not measured the leak rate. At about 14 calls/day, with calls normally
  finishing in under 20 s, we expect it to be rare. We have not observed a leaked file or process directly; this
  report is from reading the source.
- We initially suspected that the provider request itself keeps running after a cancel. On reading
  `providers.py:527-538` and the handlers, it does not appear to be shielded, so we are not claiming that.
