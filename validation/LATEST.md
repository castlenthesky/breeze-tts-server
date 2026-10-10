# Breeze TTS 2 capability matrix — 20261007T094730Z

Server goldielocks (DGX Spark GB10) `:8500` · clone voice `narrator_m` · ASR off

| id | status (expect) | latency | audio | checks | ASR / body |
|---|---|---|---|---|---|
| perf_design_cfg1_short | 200 (200) ✅ | 6.47s | 5.68s · F0 150.3 · -23.3 dBFS | ✅ incremental: TTFB 0.306s of 6.47s (5%), 82 chunks, 10/50/90% bytes at [0.83, 3.39, 5.81]s; ❌ realtime: RTF 1.14; ❌ steady_state_realtime: steady 0.899× (from TTFB+1 s), 80 ms-frame interval med/p95 [85.8, 171.5] ms, 57.9% frames late; min prebuffer 0.87 s |  |
| perf_design_cfg1_medium | 200 (200) ✅ | 15.59s | 14.0s · F0 102.1 · -22.5 dBFS | ✅ incremental: TTFB 0.194s of 15.59s (1%), 242 chunks, 10/50/90% bytes at [1.73, 7.89, 14.05]s; ❌ realtime: RTF 1.11; ❌ steady_state_realtime: steady 0.906× (from TTFB+1 s), 80 ms-frame interval med/p95 [78.7, 187.3] ms, 48.1% frames late; min prebuffer 1.73 s |  |
| perf_design_cfg4_medium | 200 (200) ✅ | 13.24s | 12.0s · F0 181.9 · -23.1 dBFS | ✅ incremental: TTFB 0.258s of 13.24s (2%), 187 chunks, 10/50/90% bytes at [1.4, 6.66, 11.92]s; ❌ realtime: RTF 1.1; ❌ steady_state_realtime: steady 0.915× (from TTFB+1 s), 80 ms-frame interval med/p95 [79.5, 193.0] ms, 50.0% frames late; min prebuffer 1.36 s |  |
| perf_clone_short | 200 (200) ✅ | 5.51s | 4.72s · F0 88.9 · -27.3 dBFS | ✅ incremental: TTFB 0.289s of 5.51s (5%), 79 chunks, 10/50/90% bytes at [0.74, 2.92, 4.99]s; ❌ realtime: RTF 1.17; ❌ steady_state_realtime: steady 0.928× (from TTFB+1 s), 80 ms-frame interval med/p95 [80.0, 192.3] ms, 51.1% frames late; min prebuffer 0.86 s |  |
| perf_clone_medium | 200 (200) ✅ | 15.83s | 14.16s · F0 95.2 · -26.0 dBFS | ✅ incremental: TTFB 0.218s of 15.83s (1%), 235 chunks, 10/50/90% bytes at [1.75, 7.99, 14.29]s; ❌ realtime: RTF 1.12; ❌ steady_state_realtime: steady 0.906× (from TTFB+1 s), 80 ms-frame interval med/p95 [85.8, 189.6] ms, 51.2% frames late; min prebuffer 1.77 s |  |
| perf_direction_cfg4_medium | 200 (200) ✅ | 15.05s | 13.6s · F0 81.5 · -30.5 dBFS | ✅ incremental: TTFB 0.285s of 15.05s (2%), 222 chunks, 10/50/90% bytes at [1.79, 7.61, 13.55]s; ❌ realtime: RTF 1.11; ❌ steady_state_realtime: steady 0.926× (from TTFB+1 s), 80 ms-frame interval med/p95 [83.5, 188.7] ms, 51.9% frames late; min prebuffer 1.57 s |  |
| perf_design_cfg1_long | 200 (200) ✅ | 42.07s | 37.92s · F0 130.9 · -21.0 dBFS | ✅ incremental: TTFB 0.179s of 42.07s (0%), 656 chunks, 10/50/90% bytes at [4.32, 21.08, 37.88]s; ❌ realtime: RTF 1.11; ❌ steady_state_realtime: steady 0.904× (from TTFB+1 s), 80 ms-frame interval med/p95 [83.6, 191.1] ms, 52.9% frames late; min prebuffer 4.3 s |  |
| perf_clone_long | 200 (200) ✅ | 33.17s | 29.52s · F0 93.6 · -26.0 dBFS | ✅ incremental: TTFB 0.527s of 33.17s (2%), 506 chunks, 10/50/90% bytes at [3.8, 16.82, 30.0]s; ❌ realtime: RTF 1.12; ❌ steady_state_realtime: steady 0.903× (from TTFB+1 s), 80 ms-frame interval med/p95 [83.5, 188.3] ms, 52.0% frames late; min prebuffer 3.75 s |  |

## perf subset

| id | audio s | TTFA s | audio s/wall s | steady × | 80ms-frame med/p95 ms | late % | prebuffer s |
|---|---|---|---|---|---|---|---|
| perf_design_cfg1_short | 5.68 | 0.306 | 0.88 | 0.899 | [85.8, 171.5] | 57.9 | 0.87 |
| perf_design_cfg1_medium | 14.0 | 0.194 | 0.9 | 0.906 | [78.7, 187.3] | 48.1 | 1.73 |
| perf_design_cfg4_medium | 12.0 | 0.258 | 0.91 | 0.915 | [79.5, 193.0] | 50.0 | 1.36 |
| perf_clone_short | 4.72 | 0.289 | 0.86 | 0.928 | [80.0, 192.3] | 51.1 | 0.86 |
| perf_clone_medium | 14.16 | 0.218 | 0.89 | 0.906 | [85.8, 189.6] | 51.2 | 1.77 |
| perf_direction_cfg4_medium | 13.6 | 0.285 | 0.9 | 0.926 | [83.5, 188.7] | 51.9 | 1.57 |
| perf_design_cfg1_long | 37.92 | 0.179 | 0.9 | 0.904 | [83.6, 191.1] | 52.9 | 4.3 |
| perf_clone_long | 29.52 | 0.527 | 0.89 | 0.903 | [83.5, 188.3] | 52.0 | 3.75 |

**steady-state median 0.906× (min 0.899, max 0.928)**
