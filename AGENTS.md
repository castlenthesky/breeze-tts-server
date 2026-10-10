- `server/yggdrasil_breeze_api.py` (HTTP) and `server/yggdrasil_breeze_fast.py` (runtime
  subclass, eager-module swap, codec decode) import upstream (never fork or patch it); the
  `Dockerfile` pins upstream (`BREEZE_COMMIT`) and every package (`docker/requirements.lock`).
  The runtime subclass installs only while upstream hashes to `UPSTREAM_SHA256` — on a bump,
  diff the loop, rerun the parity tests, then update the hashes. Its lean loop is off
  (`BREEZE_LEAN_LOOP: "0"`): measured 2026-10-07 in `full` mode, 0.911 vs 0.907 steady × —
  noise; re-measure (`validation/breeze_matrix.py --only perf_ --no-asr`, ≥2 runs) first
- Keep `/v1/audio/speech` backward compatible with upstream's fields and defaults, and bump
  `API_VERSION` on an API change. A restart drops any request in flight (one at a time):
  check `/health` → `busy` first
- `tests/test_overlay.py` stubs upstream and torch (no GPU); `tests/test_runtime_torch.py` needs
  real CPU torch in its own session (+ `BREEZE_UPSTREAM_SRC` for parity). Synthetic audio only —
  no real-person voices in tests or validation; never commit weights, `data/` or `.env`
