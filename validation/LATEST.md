# Breeze TTS 2 capability matrix — 20261010T204100Z

Server goldielocks (DGX Spark GB10) `:8500` · clone voice `narrator_m` · ASR off

| id | status (expect) | latency | audio | checks | ASR / body |
|---|---|---|---|---|---|
| ep_health | 200 (200) ✅ | 0.01s |  |  | {"status":"ok","sample_rate":24000,"api_version":"2026.10.07","busy":false,"fast_mode":"full"} |
| ep_openapi | 200 (200) ✅ | 0.02s |  |  | {"paths": ["/health", "/v1/audio/convert", "/v1/audio/speech", "/v1/capabilities", "/v1/voices", "/v1/voices/{voice_id}", "/v1/voices/{voice_id}/audio"], "speech_fields": ["cfg_scale", "cfg_scale_ins", "cfg_scale_ref", " |
| ep_convert | 422 (2xx|4xx) ✅ | 0.19s |  |  | {"detail":[{"type":"missing","loc":["body","source_audio"],"msg":"Field required","input":null}]} |
| ep_voices | 200 (200) ✅ | 0.02s |  |  | {"voices":[{"id":"fc_narrator","ref_text":"Long ago, before the rivers found their courses, the old roads ran straight through the mountains, and travellers spoke of lights that walked beside them in the dark.","instruct |
| ep_capabilities | 200 (200) ✅ | 0.01s |  |  | {"api_version":"2026.10.07","audio":{"sample_rate":24000,"sample_format":"s16le","channels":1},"codec_frame_rate":12.5,"fast_mode":{"mode":"full","stages":{"fast_backbone_decode":true,"fast_depth_decoder":true,"fast_code |
| design_plain | 200 (200) ✅ | 6.35s | 5.68s · F0 150.3 · -23.2 dBFS |  |  |
| design_instruct | 200 (200) ✅ | 7.37s | 6.64s · F0 164.9 · -20.6 dBFS |  |  |
| design_zh | 200 (200) ✅ | 4.27s | 3.68s · F0 422.7 · -20.3 dBFS |  |  |
| clone_basic | 200 (200) ✅ | 6.32s | 4.48s · F0 93.6 · -26.5 dBFS |  |  |
| clone_no_ref_text | 400 (400) ✅ | 0.16s |  |  | {"detail":"ref_audio and ref_text must be provided together or both omitted."} |
| direction_angry | 200 (200) ✅ | 3.73s | 3.2s · F0 92.8 · -24.4 dBFS |  |  |
| direction_british | 200 (200) ✅ | 4.23s | 3.6s · F0 140.3 · -23.9 dBFS |  |  |
| direction_whisper | 200 (200) ✅ | 6.22s | 5.44s · F0 78.5 · -33.0 dBFS |  |  |
| emotion_neutral | 200 (200) ✅ | 3.28s | 2.96s · F0 249.9 · -25.1 dBFS |  |  |
| emotion_angry | 200 (200) ✅ | 3.48s | 3.04s · F0 185.6 · -20.8 dBFS |  |  |
| emotion_sad | 200 (200) ✅ | 5.91s | 5.28s · F0 206.5 · -26.9 dBFS |  |  |
| emotion_happy | 200 (200) ✅ | 4.68s | 4.16s · F0 287.9 · -22.4 dBFS |  |  |
| emotion_whispering | 200 (200) ✅ | 5.65s | 5.12s · -31.8 dBFS |  |  |
| emotion_fearful | 200 (200) ✅ | 3.44s | 3.04s · F0 217.6 · -30.3 dBFS |  |  |
| tag_control_en_cfg1_s42 | 200 (200) ✅ | 3.09s | 2.72s · F0 171.7 · -22.9 dBFS |  |  |
| tag_control_en_cfg1_s7 | 200 (200) ✅ | 2.75s | 2.24s · F0 199.5 · -28.6 dBFS |  |  |
| tag_control_en_cfg3_s42 | 200 (200) ✅ | 3.04s | 2.64s · F0 167.8 · -24.5 dBFS |  |  |
| tag_control_en_cfg3_s7 | 200 (200) ✅ | 2.6s | 2.32s · F0 185.1 · -27.5 dBFS |  |  |
| tag_control_zh_cfg1_s42 | 200 (200) ✅ | 1.94s | 1.68s · F0 94.4 · -21.2 dBFS |  |  |
| tag_control_zh_cfg1_s7 | 200 (200) ✅ | 1.95s | 1.6s · F0 218.8 · -21.8 dBFS |  |  |
| tag_control_zh_cfg3_s42 | 200 (200) ✅ | 2.17s | 1.92s · F0 206.5 · -26.2 dBFS |  |  |
| tag_control_zh_cfg3_s7 | 200 (200) ✅ | 2.82s | 2.48s · F0 108.2 · -22.9 dBFS |  |  |
| tag_en_paren_laugh_cfg1_s42 | 200 (200) ✅ | 3.99s | 3.52s · F0 156.5 · -28.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.80s vs no-tag control |  |
| tag_en_paren_laugh_cfg1_s7 | 200 (200) ✅ | 4.93s | 4.24s · F0 200.1 · -29.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.00s vs no-tag control |  |
| tag_en_paren_laugh_cfg3_s42 | 200 (200) ✅ | 3.46s | 3.04s · F0 162.0 · -27.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_laugh_cfg3_s7 | 200 (200) ✅ | 2.59s | 2.24s · F0 184.0 · -22.5 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: -0.08s vs no-tag control |  |
| tag_en_paren_cough_cfg1_s42 | 200 (200) ✅ | 3.54s | 3.12s · F0 174.7 · -25.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_cough_cfg1_s7 | 200 (200) ✅ | 4.07s | 3.52s · F0 201.8 · -28.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.28s vs no-tag control |  |
| tag_en_paren_cough_cfg3_s42 | 200 (200) ✅ | 3.02s | 2.64s · F0 199.5 · -24.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.00s vs no-tag control |  |
| tag_en_paren_cough_cfg3_s7 | 200 (200) ✅ | 3.56s | 3.2s · F0 194.9 · -22.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.88s vs no-tag control |  |
| tag_en_paren_clears_throat_cfg1_s42 | 200 (200) ✅ | 3.17s | 2.72s · F0 128.6 · -22.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.00s vs no-tag control |  |
| tag_en_paren_clears_throat_cfg1_s7 | 200 (200) ✅ | 3.47s | 3.04s · F0 197.2 · -21.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.80s vs no-tag control |  |
| tag_en_paren_clears_throat_cfg3_s42 | 200 (200) ✅ | 3.03s | 2.72s · F0 151.2 · -26.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.08s vs no-tag control |  |
| tag_en_paren_clears_throat_cfg3_s7 | 200 (200) ✅ | 3.47s | 3.12s · F0 207.7 · -21.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.80s vs no-tag control |  |
| tag_en_paren_sigh_cfg1_s42 | 200 (200) ✅ | 5.96s | 5.28s · F0 181.9 · -27.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.56s vs no-tag control |  |
| tag_en_paren_sigh_cfg1_s7 | 200 (200) ✅ | 5.58s | 4.8s · F0 163.0 · -28.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.56s vs no-tag control |  |
| tag_en_paren_sigh_cfg3_s42 | 200 (200) ✅ | 3.24s | 2.88s · F0 152.1 · -26.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.24s vs no-tag control |  |
| tag_en_paren_sigh_cfg3_s7 | 200 (200) ✅ | 3.91s | 3.44s · F0 260.2 · -21.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.12s vs no-tag control |  |
| tag_zh_bracket_笑_cfg1_s42 | 200 (200) ✅ | 4.79s | 4.24s · F0 96.4 · -23.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.56s vs no-tag control |  |
| tag_zh_bracket_笑_cfg1_s7 | 200 (200) ✅ | 3.72s | 3.28s · F0 198.3 · -25.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.68s vs no-tag control |  |
| tag_zh_bracket_笑_cfg3_s42 | 200 (200) ✅ | 2.78s | 2.48s · F0 141.9 · -20.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.56s vs no-tag control |  |
| tag_zh_bracket_笑_cfg3_s7 | 200 (200) ✅ | 3.03s | 2.64s · F0 210.8 · -26.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.16s vs no-tag control |  |
| tag_zh_bracket_咳嗽_cfg1_s42 | 200 (200) ✅ | 3.83s | 3.36s · F0 229.2 · -24.5 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.68s vs no-tag control |  |
| tag_zh_bracket_咳嗽_cfg1_s7 | 200 (200) ✅ | 4.87s | 4.24s · F0 203.0 · -24.2 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.64s vs no-tag control |  |
| tag_zh_bracket_咳嗽_cfg3_s42 | 200 (200) ✅ | 3.01s | 2.64s · F0 187.2 · -18.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.72s vs no-tag control |  |
| tag_zh_bracket_咳嗽_cfg3_s7 | 200 (200) ✅ | 3.25s | 2.88s · F0 112.0 · -22.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_zh_bracket_清嗓子_cfg1_s42 | 200 (200) ✅ | 5.06s | 4.48s · F0 101.5 · -21.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.80s vs no-tag control |  |
| tag_zh_bracket_清嗓子_cfg1_s7 | 200 (200) ✅ | 4.96s | 4.32s · F0 240.7 · -21.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.72s vs no-tag control |  |
| tag_zh_bracket_清嗓子_cfg3_s42 | 200 (200) ✅ | 4.17s | 3.76s · F0 283.8 · -21.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.84s vs no-tag control |  |
| tag_zh_bracket_清嗓子_cfg3_s7 | 200 (200) ✅ | 3.2s | 2.8s · F0 177.7 · -24.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.32s vs no-tag control |  |
| tag_zh_bracket_叹气_cfg1_s42 | 200 (200) ✅ | 4.78s | 4.24s · F0 235.9 · -19.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.56s vs no-tag control |  |
| tag_zh_bracket_叹气_cfg1_s7 | 200 (200) ✅ | 3.89s | 3.44s · F0 215.1 · -25.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.84s vs no-tag control |  |
| tag_zh_bracket_叹气_cfg3_s42 | 200 (200) ✅ | 4.43s | 4.0s · F0 222.6 · -24.5 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.08s vs no-tag control |  |
| tag_zh_bracket_叹气_cfg3_s7 | 200 (200) ✅ | 3.61s | 3.2s · F0 300.0 · -22.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.72s vs no-tag control |  |
| tag_en_paren_laughs_cfg1_s42 | 200 (200) ✅ | 4.31s | 3.76s · F0 123.5 · -24.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.04s vs no-tag control |  |
| tag_en_paren_laughs_cfg1_s7 | 200 (200) ✅ | 4.62s | 4.08s · F0 211.4 · -26.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.84s vs no-tag control |  |
| tag_en_paren_laughs_cfg3_s42 | 200 (200) ✅ | 3.24s | 2.8s · F0 156.5 · -24.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.16s vs no-tag control |  |
| tag_en_paren_laughs_cfg3_s7 | 200 (200) ✅ | 3.03s | 2.72s · F0 185.6 · -22.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_sobs_cfg1_s42 | 200 (200) ✅ | 3.64s | 3.04s · F0 274.1 · -21.5 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.32s vs no-tag control |  |
| tag_en_paren_sobs_cfg1_s7 | 200 (200) ✅ | 4.43s | 3.92s · F0 208.9 · -22.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.68s vs no-tag control |  |
| tag_en_paren_sobs_cfg3_s42 | 200 (200) ✅ | 3.13s | 2.72s · F0 181.9 · -23.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.08s vs no-tag control |  |
| tag_en_paren_sobs_cfg3_s7 | 200 (200) ✅ | 3.31s | 2.96s · F0 206.5 · -22.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.64s vs no-tag control |  |
| tag_en_paren_gasps_cfg1_s42 | 200 (200) ✅ | 4.33s | 3.76s · F0 104.5 · -23.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.04s vs no-tag control |  |
| tag_en_paren_gasps_cfg1_s7 | 200 (200) ✅ | 7.2s | 6.32s · F0 213.8 · -23.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +4.08s vs no-tag control |  |
| tag_en_paren_gasps_cfg3_s42 | 200 (200) ✅ | 3.65s | 3.2s · F0 150.3 · -24.4 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.56s vs no-tag control |  |
| tag_en_paren_gasps_cfg3_s7 | 200 (200) ✅ | 3.91s | 3.44s · F0 184.0 · -24.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.12s vs no-tag control |  |
| tag_en_paren_whispers_cfg1_s42 | 200 (200) ✅ | 3.28s | 2.88s · F0 196.1 · -29.5 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.16s vs no-tag control |  |
| tag_en_paren_whispers_cfg1_s7 | 200 (200) ✅ | 3.66s | 3.2s · F0 159.3 · -34.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.96s vs no-tag control |  |
| tag_en_paren_whispers_cfg3_s42 | 200 (200) ✅ | 3.47s | 3.04s · F0 215.1 · -25.5 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_whispers_cfg3_s7 | 200 (200) ✅ | 2.02s | 1.76s · F0 223.9 · -20.4 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: -0.56s vs no-tag control |  |
| tag_en_paren_shouts_cfg1_s42 | 200 (200) ✅ | 3.27s | 2.8s · F0 215.7 · -22.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.08s vs no-tag control |  |
| tag_en_paren_shouts_cfg1_s7 | 200 (200) ✅ | 5.36s | 4.64s · F0 406.0 · -18.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.40s vs no-tag control |  |
| tag_en_paren_shouts_cfg3_s42 | 200 (200) ✅ | 3.63s | 3.2s · F0 229.2 · -22.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.56s vs no-tag control |  |
| tag_en_paren_shouts_cfg3_s7 | 200 (200) ✅ | 2.88s | 2.56s · F0 353.4 · -21.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.24s vs no-tag control |  |
| tag_en_paren_screams_cfg1_s42 | 200 (200) ✅ | 6.97s | 6.08s · F0 269.4 · -20.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +3.36s vs no-tag control |  |
| tag_en_paren_screams_cfg1_s7 | 200 (200) ✅ | 10.26s | 9.12s · F0 561.0 · -17.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +6.88s vs no-tag control |  |
| tag_en_paren_screams_cfg3_s42 | 200 (200) ✅ | 2.96s | 2.56s · F0 208.9 · -24.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: -0.08s vs no-tag control |  |
| tag_en_paren_screams_cfg3_s7 | 200 (200) ✅ | 3.3s | 2.96s · F0 205.3 · -23.5 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.64s vs no-tag control |  |
| tag_en_paren_sneezes_cfg1_s42 | 200 (200) ✅ | 5.0s | 4.32s · F0 261.0 · -25.2 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.60s vs no-tag control |  |
| tag_en_paren_sneezes_cfg1_s7 | 200 (200) ✅ | 6.04s | 5.2s · F0 242.8 · -27.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.96s vs no-tag control |  |
| tag_en_paren_sneezes_cfg3_s42 | 200 (200) ✅ | 4.1s | 3.68s · F0 195.5 · -24.4 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.04s vs no-tag control |  |
| tag_en_paren_sneezes_cfg3_s7 | 200 (200) ✅ | 3.56s | 3.2s · F0 203.0 · -26.2 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.88s vs no-tag control |  |
| tag_en_paren_coughs_cfg1_s42 | 200 (200) ✅ | 4.78s | 4.16s · F0 169.2 · -24.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.44s vs no-tag control |  |
| tag_en_paren_coughs_cfg1_s7 | 200 (200) ✅ | 5.22s | 4.56s · F0 166.8 · -32.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.32s vs no-tag control |  |
| tag_en_paren_coughs_cfg3_s42 | 200 (200) ✅ | 2.92s | 2.48s · F0 142.7 · -24.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: -0.16s vs no-tag control |  |
| tag_en_paren_coughs_cfg3_s7 | 200 (200) ✅ | 3.74s | 3.36s · F0 191.6 · -21.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.04s vs no-tag control |  |
| tag_en_paren_sighs_cfg1_s42 | 200 (200) ✅ | 4.17s | 3.68s · F0 120.3 · -24.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.96s vs no-tag control |  |
| tag_en_paren_sighs_cfg1_s7 | 200 (200) ✅ | 4.7s | 4.08s · F0 201.8 · -28.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.84s vs no-tag control |  |
| tag_en_paren_sighs_cfg3_s42 | 200 (200) ✅ | 3.02s | 2.64s · F0 148.6 · -27.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.00s vs no-tag control |  |
| tag_en_paren_sighs_cfg3_s7 | 200 (200) ✅ | 3.31s | 2.96s · F0 185.1 · -22.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.64s vs no-tag control |  |
| tag_en_paren_chuckles_cfg3_s42 | 200 (200) ✅ | 3.42s | 2.96s · F0 103.6 · -23.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.32s vs no-tag control |  |
| tag_en_paren_giggles_cfg3_s42 | 200 (200) ✅ | 3.24s | 2.88s · F0 158.3 · -23.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.24s vs no-tag control |  |
| tag_en_paren_crying_cfg3_s42 | 200 (200) ✅ | 3.05s | 2.72s · F0 153.4 · -22.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.08s vs no-tag control |  |
| tag_en_paren_whimpers_cfg3_s42 | 200 (200) ✅ | 4.79s | 4.32s · F0 166.8 · -23.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.68s vs no-tag control |  |
| tag_en_paren_groans_cfg3_s42 | 200 (200) ✅ | 3.22s | 2.88s · F0 141.9 · -24.2 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.24s vs no-tag control |  |
| tag_en_paren_inhales_cfg3_s42 | 200 (200) ✅ | 3.48s | 3.04s · F0 173.7 · -21.4 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_exhales_cfg3_s42 | 200 (200) ✅ | 3.31s | 2.96s · F0 138.3 · -26.4 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.32s vs no-tag control |  |
| tag_en_paren_breathing_heavily_cfg3_s42 | 200 (200) ✅ | 4.27s | 3.68s · F0 167.8 · -27.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.04s vs no-tag control |  |
| tag_en_paren_humming_cfg3_s42 | 200 (200) ✅ | 3.06s | 2.72s · F0 210.1 · -24.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.08s vs no-tag control |  |
| tag_en_paren_stutters_cfg3_s42 | 200 (200) ✅ | 2.77s | 2.4s · F0 130.5 · -25.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: -0.24s vs no-tag control |  |
| tag_en_paren_pause_cfg3_s42 | 200 (200) ✅ | 3.48s | 3.04s · F0 130.1 · -24.2 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_sniffs_cfg3_s42 | 200 (200) ✅ | 3.91s | 3.52s · F0 156.5 · -24.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.88s vs no-tag control |  |
| tag_en_paren_yawns_cfg3_s42 | 200 (200) ✅ | 3.23s | 2.8s · F0 210.1 · -29.2 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.16s vs no-tag control |  |
| tag_en_paren_hiccups_cfg3_s42 | 200 (200) ✅ | 3.91s | 3.44s · F0 355.5 · -25.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.80s vs no-tag control |  |
| tag_en_paren_gulps_cfg3_s42 | 200 (200) ✅ | 3.05s | 2.72s · F0 165.4 · -24.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.08s vs no-tag control |  |
| tag_en_paren_grunts_cfg3_s42 | 200 (200) ✅ | 4.18s | 3.76s · F0 137.4 · -25.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.12s vs no-tag control |  |
| tag_en_paren_scoffs_cfg3_s42 | 200 (200) ✅ | 3.17s | 2.72s · F0 174.2 · -24.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.08s vs no-tag control |  |
| tag_en_paren_snorts_cfg3_s42 | 200 (200) ✅ | 3.31s | 2.96s · F0 110.4 · -24.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.32s vs no-tag control |  |
| tag_en_paren_sneeze_cfg3_s42 | 200 (200) ✅ | 4.3s | 3.68s · F0 162.0 · -29.1 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.04s vs no-tag control |  |
| tag_en_paren_gasp_cfg3_s42 | 200 (200) ✅ | 2.8s | 2.4s · F0 119.3 · -26.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: -0.24s vs no-tag control |  |
| tag_en_paren_yawn_cfg3_s42 | 200 (200) ✅ | 3.48s | 3.04s · F0 204.2 · -23.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_chuckle_cfg3_s42 | 200 (200) ✅ | 3.47s | 3.04s · F0 177.7 · -24.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_paren_cry_cfg3_s42 | 200 (200) ✅ | 2.97s | 2.64s · F0 136.7 · -20.9 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.00s vs no-tag control |  |
| tag_en_paren_breath_cfg3_s42 | 200 (200) ✅ | 3.16s | 2.8s · F0 163.0 · -26.4 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.16s vs no-tag control |  |
| tag_en_paren_sob_cfg3_s42 | 200 (200) ✅ | 3.06s | 2.64s · F0 133.2 · -23.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ❌ tag_adds_audio: +0.00s vs no-tag control |  |
| tag_en_bracket_cough_cfg1_s42 | 200 (200) ✅ | 3.63s | 3.12s · F0 174.7 · -25.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.40s vs no-tag control |  |
| tag_en_bracket_cough_cfg1_s7 | 200 (200) ✅ | 4.09s | 3.52s · F0 203.0 · -28.0 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +1.28s vs no-tag control |  |
| tag_en_bracket_laugh_cfg1_s42 | 200 (200) ✅ | 3.99s | 3.52s · F0 156.5 · -28.7 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +0.80s vs no-tag control |  |
| tag_en_bracket_laugh_cfg1_s7 | 200 (200) ✅ | 4.91s | 4.24s · F0 200.7 · -29.3 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.00s vs no-tag control |  |
| tag_en_bracket_sigh_cfg1_s42 | 200 (200) ✅ | 5.97s | 5.28s · F0 181.9 · -27.8 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.56s vs no-tag control |  |
| tag_en_bracket_sigh_cfg1_s7 | 200 (200) ✅ | 5.54s | 4.8s · F0 164.9 · -28.6 dBFS | ❔ tag_not_read_aloud: tag words absent from transcript; ✅ tag_adds_audio: +2.56s vs no-tag control |  |
| clone_voice_young_f | 200 (200) ✅ | 5.21s | 4.0s · F0 245.6 · -22.8 dBFS |  |  |
| clone_voice_narrator_long | 200 (200) ✅ | 5.82s | 4.16s · F0 105.7 · -22.3 dBFS |  |  |
| clone_voice_child | 200 (200) ✅ | 6.14s | 4.88s · F0 322.2 · -27.1 dBFS |  |  |
| clone_ref_mp3 | 200 (200) ✅ | 5.49s | 4.64s · F0 89.4 · -26.2 dBFS |  |  |
| clone_ref_ogg | 200 (200) ✅ | 6.22s | 5.28s · F0 86.3 · -26.8 dBFS |  |  |
| clone_ref_m4a | 200 (200) ✅ | 5.21s | 3.92s · F0 92.3 · -26.8 dBFS |  |  |
| long_xl_design | 400 (200) ❌ | 0.01s |  |  | {"detail":"text is 1555 characters; send at most 1000 per request (~350 keeps long-form quality steady) and stitch"} |
| inject_text_s1 | 200 (2xx) ✅ | 4.62s | 4.08s · F0 182.9 · -21.9 dBFS |  |  |
| inject_text_ins_bos | 400 (2xx|4xx) ✅ | 0.07s |  |  | {"detail":"unbalanced inline instruction: write <ins_bos>instruction<ins_eos> before the text it directs (or send raw=true to pass markers to the model untouched)"} |
| inject_text_audio_tok | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"text contains audio-slot tokens ['<\|AUDIO\|>']; they mark where reference-audio codes go and break generation in text, so remove them"} |
| inject_text_audio_eos | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"text contains audio-slot tokens ['<\|audio_eos\|>']; they mark where reference-audio codes go and break generation in text, so remove them"} |
| inject_instruction_audio_tok | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"instruction contains audio-slot tokens ['<\|AUDIO\|>']; they mark where reference-audio codes go and break generation in text, so remove them"} |
| inject_clone_ref_text | 400 (4xx) ✅ | 0.06s |  |  | {"detail":"ref_text contains audio-slot tokens ['<\|AUDIO\|>']; they mark where reference-audio codes go and break generation in text, so remove them"} |
| inline_furious_inline_cfg1_s42 | 200 (200) ✅ | 4.52s | 3.92s · F0 282.9 · -21.5 dBFS |  |  |
| inline_furious_inline_cfg1_s7 | 200 (200) ✅ | 3.01s | 2.56s · F0 188.3 · -21.2 dBFS |  |  |
| inline_furious_inline_cfg3_s42 | 200 (200) ✅ | 2.85s | 2.48s · F0 247.0 · -20.0 dBFS |  |  |
| inline_furious_inline_cfg3_s7 | 200 (200) ✅ | 2.77s | 2.32s · F0 177.7 · -20.6 dBFS |  |  |
| inline_furious_control_cfg1_s42 | 200 (200) ✅ | 2.15s | 1.84s · F0 331.7 · -21.5 dBFS |  |  |
| inline_furious_control_cfg1_s7 | 200 (200) ✅ | 2.6s | 2.24s · F0 227.8 · -24.5 dBFS |  |  |
| inline_furious_control_cfg3_s42 | 200 (200) ✅ | 2.16s | 1.84s · F0 159.3 · -20.2 dBFS |  |  |
| inline_furious_control_cfg3_s7 | 200 (200) ✅ | 1.74s | 1.52s · F0 297.2 · -24.4 dBFS |  |  |
| inline_whisper_shout_inline_cfg1_s42 | 200 (200) ✅ | 5.23s | 4.56s · F0 370.1 · -20.5 dBFS |  |  |
| inline_whisper_shout_inline_cfg1_s7 | 200 (200) ✅ | 6.3s | 5.6s · F0 245.6 · -22.7 dBFS |  |  |
| inline_whisper_shout_inline_cfg3_s42 | 200 (200) ✅ | 5.19s | 4.56s · F0 370.1 · -20.5 dBFS |  |  |
| inline_whisper_shout_inline_cfg3_s7 | 200 (200) ✅ | 6.31s | 5.6s · F0 246.3 · -22.7 dBFS |  |  |
| inline_whisper_shout_control_cfg1_s42 | 200 (200) ✅ | 3.65s | 3.2s · F0 157.4 · -21.8 dBFS |  |  |
| inline_whisper_shout_control_cfg1_s7 | 200 (200) ✅ | 5.49s | 4.88s · F0 109.7 · -25.8 dBFS |  |  |
| inline_whisper_shout_control_cfg3_s42 | 200 (200) ✅ | 3.62s | 3.04s · F0 156.5 · -21.2 dBFS |  |  |
| inline_whisper_shout_control_cfg3_s7 | 200 (200) ✅ | 3.12s | 2.8s · F0 142.7 · -28.5 dBFS |  |  |
| inline_furious_raw_cfg1_s42 | 200 (200) ✅ | 1.83s | 1.44s · F0 181.9 · -18.2 dBFS |  |  |
| inline_s1clone_s1_s42 | 200 (200) ✅ | 7.23s | 6.32s · F0 88.4 · -27.6 dBFS |  |  |
| inline_s1clone_s1_s7 | 200 (200) ✅ | 7.66s | 6.64s · F0 112.6 · -23.9 dBFS |  |  |
| inline_s1clone_control_s42 | 200 (200) ✅ | 7.72s | 6.72s · F0 89.9 · -28.0 dBFS |  |  |
| inline_s1clone_control_s7 | 200 (200) ✅ | 7.48s | 6.56s · F0 95.2 · -25.8 dBFS |  |  |
| speed_field_0.7 | 200 (200) ✅ | 6.45s | 8.114s · F0 149.9 · -24.7 dBFS |  |  |
| speed_field_1.0 | 200 (200) ✅ | 6.56s | 5.68s · F0 150.3 · -23.3 dBFS |  |  |
| speed_field_1.3 | 200 (200) ✅ | 6.45s | 4.369s · F0 150.3 · -24.9 dBFS | ✅ speed_changes_duration: 8.114s / 5.68s / 4.369s (slow/1.0/fast) |  |
| speed_instr_slow | 200 (200) ✅ | 19.73s | 17.92s · F0 139.4 · -27.7 dBFS |  |  |
| speed_instr_normal | 200 (200) ✅ | 3.34s | 2.96s · F0 247.7 · -25.1 dBFS |  |  |
| speed_instr_fast | 200 (200) ✅ | 2.3s | 1.92s · F0 137.0 · -23.6 dBFS | ✅ speed_changes_duration: 17.92s / 2.96s / 1.92s (slow/1.0/fast) |  |
| seed_7_a | 200 (200) ✅ | 5.5s | 4.88s · F0 96.9 · -23.9 dBFS |  |  |
| seed_7_b | 200 (200) ✅ | 5.49s | 4.88s · F0 96.4 · -23.8 dBFS | ✅ same_seed_equivalent: not bit-identical, len 117120 vs 117120, corr 0.9969 |  |
| seed_8 | 200 (200) ✅ | 4.9s | 4.24s · F0 121.4 · -22.1 dBFS | ✅ diff_seed_differs:  |  |
| seed_clone_7_a | 200 (200) ✅ | 5.44s | 4.56s · F0 79.6 · -26.0 dBFS |  |  |
| seed_clone_7_b | 200 (200) ✅ | 5.43s | 4.56s · F0 80.1 · -25.9 dBFS | ✅ same_seed_equivalent: not bit-identical, len 109440 vs 109440, corr 0.9963 |  |
| long_design | 200 (200) ✅ | 54.5s | 48.72s · F0 98.0 · -24.0 dBFS | ✅ not_truncated: 48.72s for 145 words = 2.98 w/s (expect ≈56s @2.6 w/s); ASR ends '' |  |
| long_clone | 200 (200) ✅ | 64.24s | 57.36s · F0 80.6 · -28.1 dBFS | ✅ not_truncated: 57.36s for 145 words = 2.53 w/s (expect ≈56s @2.6 w/s); ASR ends '' |  |
| stream_design | 200 (200) ✅ | 6.39s | 5.68s · F0 150.8 · -23.3 dBFS | ✅ incremental: TTFB 0.182s of 6.39s (3%), 113 chunks, 10/50/90% bytes at [0.81, 3.25, 5.74]s; ❌ realtime: RTF 1.12; ❌ steady_state_realtime: steady 0.911× (from TTFB+1 s), 80 ms-frame interval med/p95 [85.6, 184.5] ms, 53.4% frames late; min prebuffer 0.81 s; ✅ matches_buffered_same_seed: vs design_plain: not bit-identical, len 136320 vs 136320, corr 0.9986 |  |
| stream_clone | 200 (200) ✅ | 5.32s | 4.48s · F0 94.2 · -26.5 dBFS | ✅ incremental: TTFB 0.314s of 5.32s (6%), 93 chunks, 10/50/90% bytes at [0.76, 2.73, 4.89]s; ❌ realtime: RTF 1.19; ❌ steady_state_realtime: steady 0.9× (from TTFB+1 s), 80 ms-frame interval med/p95 [75.1, 198.6] ms, 45.5% frames late; min prebuffer 0.92 s; ✅ matches_buffered_same_seed: vs clone_basic: not bit-identical, len 107520 vs 107520, corr 0.9967 |  |
| stream_direction | 200 (200) ✅ | 3.83s | 3.2s · F0 92.8 · -24.4 dBFS | ✅ incremental: TTFB 0.4s of 3.83s (10%), 64 chunks, 10/50/90% bytes at [0.66, 2.14, 3.47]s; ❌ realtime: RTF 1.2; ❌ steady_state_realtime: steady 0.92× (from TTFB+1 s), 80 ms-frame interval med/p95 [77.3, 181.4] ms, 48.1% frames late; min prebuffer 0.75 s; ✅ matches_buffered_same_seed: vs direction_angry: not bit-identical, len 76800 vs 76800, corr 0.9947 |  |
| stream_long | 200 (200) ✅ | 54.58s | 48.72s · F0 98.0 · -24.0 dBFS | ✅ incremental: TTFB 0.24s of 54.58s (0%), 980 chunks, 10/50/90% bytes at [5.52, 27.32, 49.1]s; ❌ realtime: RTF 1.12; ❌ steady_state_realtime: steady 0.897× (from TTFB+1 s), 80 ms-frame interval med/p95 [81.2, 193.9] ms, 50.7% frames late; min prebuffer 5.86 s; ✅ matches_buffered_same_seed: vs long_design: not bit-identical, len 1169280 vs 1169280, corr 0.9979 |  |
| stream_rtf_design_cfg1_short | 200 (200) ✅ | 6.6s | 5.68s · F0 150.3 · -23.3 dBFS | ✅ incremental: TTFB 0.408s of 6.6s (6%), 103 chunks, 10/50/90% bytes at [1.07, 3.49, 5.95]s; ❌ realtime: RTF 1.16; ❌ steady_state_realtime: steady 0.913× (from TTFB+1 s), 80 ms-frame interval med/p95 [79.9, 197.0] ms, 50.0% frames late; min prebuffer 1.05 s |  |
| stream_rtf_design_cfg4_short | 200 (200) ✅ | 3.41s | 2.96s · F0 247.7 · -25.1 dBFS | ✅ incremental: TTFB 0.328s of 3.41s (10%), 61 chunks, 10/50/90% bytes at [0.55, 1.87, 3.17]s; ❌ realtime: RTF 1.15; ❌ steady_state_realtime: steady 0.923× (from TTFB+1 s), 80 ms-frame interval med/p95 [75.0, 195.2] ms, 43.5% frames late; min prebuffer 0.61 s |  |
| stream_rtf_clone_short | 200 (200) ✅ | 5.23s | 4.48s · F0 94.2 · -26.4 dBFS | ✅ incremental: TTFB 0.233s of 5.23s (4%), 73 chunks, 10/50/90% bytes at [0.68, 2.65, 4.79]s; ❌ realtime: RTF 1.17; ❌ steady_state_realtime: steady 0.901× (from TTFB+1 s), 80 ms-frame interval med/p95 [86.0, 187.4] ms, 56.8% frames late; min prebuffer 0.83 s |  |
| stream_rtf_direction_cfg4_short | 200 (200) ✅ | 3.87s | 3.2s · F0 93.3 · -24.4 dBFS | ✅ incremental: TTFB 0.411s of 3.87s (11%), 60 chunks, 10/50/90% bytes at [0.66, 2.13, 3.45]s; ❌ realtime: RTF 1.21; ❌ steady_state_realtime: steady 0.944× (from TTFB+1 s), 80 ms-frame interval med/p95 [87.6, 172.7] ms, 57.1% frames late; min prebuffer 0.75 s |  |
| stream_rtf_design_cfg1_medium | 200 (200) ✅ | 15.81s | 14.0s · F0 102.7 · -22.5 dBFS | ✅ incremental: TTFB 0.19s of 15.81s (1%), 252 chunks, 10/50/90% bytes at [1.73, 7.94, 14.27]s; ❌ realtime: RTF 1.13; ❌ steady_state_realtime: steady 0.892× (from TTFB+1 s), 80 ms-frame interval med/p95 [85.0, 190.0] ms, 54.3% frames late; min prebuffer 1.89 s |  |
| stream_rtf_design_cfg4_medium | 200 (200) ✅ | 13.2s | 12.0s · F0 181.9 · -23.1 dBFS | ✅ incremental: TTFB 0.248s of 13.2s (2%), 250 chunks, 10/50/90% bytes at [1.4, 6.63, 11.91]s; ❌ realtime: RTF 1.1; ❌ steady_state_realtime: steady 0.917× (from TTFB+1 s), 80 ms-frame interval med/p95 [82.4, 189.0] ms, 52.9% frames late; min prebuffer 1.29 s |  |
| stream_rtf_clone_medium | 200 (200) ✅ | 18.12s | 15.84s · F0 92.5 · -26.8 dBFS | ✅ incremental: TTFB 0.519s of 18.12s (3%), 321 chunks, 10/50/90% bytes at [2.28, 9.32, 16.38]s; ❌ realtime: RTF 1.14; ❌ steady_state_realtime: steady 0.898× (from TTFB+1 s), 80 ms-frame interval med/p95 [83.0, 194.8] ms, 51.9% frames late; min prebuffer 2.44 s |  |
| stream_rtf_direction_cfg4_medium | 200 (200) ✅ | 15.63s | 14.16s · F0 89.4 · -24.7 dBFS | ✅ incremental: TTFB 0.247s of 15.63s (2%), 297 chunks, 10/50/90% bytes at [1.75, 7.93, 14.12]s; ❌ realtime: RTF 1.1; ❌ steady_state_realtime: steady 0.924× (from TTFB+1 s), 80 ms-frame interval med/p95 [84.9, 187.9] ms, 50.9% frames late; min prebuffer 1.61 s |  |
| stream_nonstream_flag | 200 (200) ✅ | 6.39s | 5.68s · F0 150.3 · -23.2 dBFS | ✅ matches_buffered_same_seed: vs design_plain: not bit-identical, len 136320 vs 136320, corr 0.9987 |  |
| stream_abort_recover | 200 (200) ✅ | Nones |  | ✅ next_request_succeeds_immediately: 1 attempt(s): [(200, 2.46)] (status, request latency s — latency on a 200 = lock linger absorbed by the 8 s wait); ✅ lock_released_eventually: recovered after 2.46s |  |
| stream_concurrent_409 | 200 (200) ✅ | Nones |  | ✅ concurrent_gets_409: 409 in 8.011s: {"detail":"An inference request is already running."}; ✅ first_stream_unharmed: {"status": 200, "bytes": 2338560} |  |
| stream_lock_wait | 200 (200) ✅ | Nones |  | ✅ concurrent_gets_200: 200 in 3.357s: <57600 bytes audio>; ✅ first_stream_unharmed: {"status": 200, "bytes": 92160} |  |
| speed_rubberband_0.85 | 200 (200) ✅ | 15.84s | 16.471s · F0 103.3 · -24.2 dBFS | ✅ speed_duration_accurate: 16.471s vs expected 16.47s (+0.0%); hdr X-Speed=0.85; ✅ no_stretch_artifacts: Δflatness -0.0014, flux ratio 0.99 vs 1.0 (heuristic) |  |
| speed_rubberband_1.0 | 200 (200) ✅ | 15.83s | 14.0s · F0 102.1 · -22.5 dBFS |  |  |
| speed_rubberband_1.15 | 200 (200) ✅ | 16.91s | 12.174s · F0 103.9 · -24.3 dBFS | ✅ speed_duration_accurate: 12.174s vs expected 12.17s (+0.0%); hdr X-Speed=1.15; ✅ no_stretch_artifacts: Δflatness +0.0017, flux ratio 1.02 vs 1.0 (heuristic) |  |
| speed_atempo_0.85 | 200 (200) ✅ | 16.15s | 16.461s · F0 100.9 · -22.4 dBFS | ✅ speed_duration_accurate: 16.461s vs expected 16.47s (-0.1%); hdr X-Speed=0.85; ✅ no_stretch_artifacts: Δflatness -0.0026, flux ratio 1.06 vs 1.0 (heuristic) |  |
| speed_atempo_1.0 | 200 (200) ✅ | 16.08s | 14.0s · F0 102.1 · -22.5 dBFS |  |  |
| speed_atempo_1.15 | 200 (200) ✅ | 16.56s | 12.18s · F0 104.5 · -22.5 dBFS | ✅ speed_duration_accurate: 12.18s vs expected 12.17s (+0.0%); hdr X-Speed=1.15; ✅ no_stretch_artifacts: Δflatness -0.0039, flux ratio 1.03 vs 1.0 (heuristic) |  |
| stream_speed_1.15 | 200 (200) ✅ | 16.02s | 12.174s · F0 102.7 · -24.2 dBFS | ✅ incremental: TTFB 2.819s of 16.02s (18%), 370 chunks, 10/50/90% bytes at [2.83, 8.4, 14.77]s; ❌ realtime: RTF 1.32; ❌ steady_state_realtime: steady 0.793× (from TTFB+1 s), 80 ms-frame interval med/p95 [85.6, 237.8] ms, 52.9% frames late; min prebuffer 4.11 s |  |
| fmt_wav_buffered | 200 (200) ✅ | 6.67s | 5.68s · F0 150.3 · -23.3 dBFS | ✅ wav_sizes_correct: {"riff_size": 272676, "data_size": 272640, "actual_data": 272640, "sr": 24000, "channels": 1, "bits": 16, "open_ended": false} |  |
| fmt_wav_stream | 200 (200) ✅ | 6.56s | 5.68s · F0 150.3 · -23.4 dBFS | ✅ incremental: TTFB 0.103s of 6.56s (2%), 121 chunks, 10/50/90% bytes at [0.83, 3.4, 5.84]s; ❌ realtime: RTF 1.15; ❌ steady_state_realtime: steady 0.894× (from TTFB+1 s), 80 ms-frame interval med/p95 [77.1, 241.7] ms, 47.5% frames late; min prebuffer 1.03 s; ✅ wav_open_ended_header: {"riff_size": 4294967295, "data_size": 4294967295, "actual_data": 272640, "sr": 24000, "channels": 1, "bits": 16, "open_ended": true} |  |
| limiter_default_angry | 200 (200) ✅ | 4.24s | 3.04s · F0 185.6 · -20.9 dBFS | ✅ limited: peak 0.761 (limiter off: 0.802) |  |
| limiter_off_angry | 200 (200) ✅ | 3.47s | 3.04s · F0 185.6 · -20.8 dBFS |  |  |
| limiter_scream_on_s42 | 200 (200) ✅ | 4.35s | 3.92s · F0 103.3 · -22.8 dBFS |  |  |
| limiter_scream_off_s42 | 200 (200) ✅ | 4.36s | 3.92s · F0 103.0 · -22.8 dBFS |  |  |
| limiter_scream_on_s7 | 200 (200) ✅ | 4.61s | 4.16s · F0 138.2 · -30.1 dBFS |  |  |
| limiter_scream_off_s7 | 200 (200) ✅ | 4.92s | 4.16s · F0 137.0 · -30.0 dBFS |  |  |
| emoseed_whispering_s42 | 200 (200) ✅ | 5.87s | 5.12s · -31.8 dBFS |  |  |
| emoseed_whispering_s7 | 200 (200) ✅ | 5.86s | 5.28s · F0 182.9 · -29.1 dBFS |  |  |
| emoseed_whispering_s123 | 200 (200) ✅ | 5.3s | 4.8s · -31.0 dBFS |  |  |
| emoseed_angry_s42 | 200 (200) ✅ | 3.43s | 3.04s · F0 185.6 · -20.8 dBFS |  |  |
| emoseed_angry_s7 | 200 (200) ✅ | 3.88s | 3.36s · -21.8 dBFS |  |  |
| emoseed_angry_s123 | 200 (200) ✅ | 4.08s | 3.12s · F0 158.3 · -21.7 dBFS |  |  |
| perf_design_cfg1_short | 200 (200) ✅ | 6.53s | 5.68s · F0 150.3 · -23.2 dBFS | ✅ incremental: TTFB 0.159s of 6.53s (2%), 115 chunks, 10/50/90% bytes at [0.81, 3.26, 5.86]s; ❌ realtime: RTF 1.15; ❌ steady_state_realtime: steady 0.9× (from TTFB+1 s), 80 ms-frame interval med/p95 [86.6, 184.4] ms, 55.2% frames late; min prebuffer 0.84 s |  |
| perf_design_cfg1_medium | 200 (200) ✅ | 15.76s | 14.0s · F0 101.5 · -22.5 dBFS | ✅ incremental: TTFB 0.136s of 15.76s (1%), 297 chunks, 10/50/90% bytes at [1.64, 8.06, 14.2]s; ❌ realtime: RTF 1.13; ❌ steady_state_realtime: steady 0.891× (from TTFB+1 s), 80 ms-frame interval med/p95 [68.8, 219.1] ms, 45.7% frames late; min prebuffer 1.84 s |  |
| perf_design_cfg4_medium | 200 (200) ✅ | 13.23s | 12.0s · F0 180.8 · -23.1 dBFS | ✅ incremental: TTFB 0.251s of 13.23s (2%), 255 chunks, 10/50/90% bytes at [1.39, 6.63, 11.91]s; ❌ realtime: RTF 1.1; ❌ steady_state_realtime: steady 0.915× (from TTFB+1 s), 80 ms-frame interval med/p95 [57.1, 220.7] ms, 41.2% frames late; min prebuffer 1.33 s |  |
| perf_clone_short | 200 (200) ✅ | 5.24s | 4.48s · F0 94.2 · -26.4 dBFS | ✅ incremental: TTFB 0.286s of 5.24s (6%), 93 chunks, 10/50/90% bytes at [0.74, 2.7, 4.76]s; ❌ realtime: RTF 1.17; ❌ steady_state_realtime: steady 0.919× (from TTFB+1 s), 80 ms-frame interval med/p95 [87.5, 186.4] ms, 54.5% frames late; min prebuffer 0.86 s |  |
| perf_clone_medium | 200 (200) ✅ | 17.85s | 15.84s · F0 92.5 · -26.8 dBFS | ✅ incremental: TTFB 0.24s of 17.85s (1%), 294 chunks, 10/50/90% bytes at [1.98, 9.03, 16.13]s; ❌ realtime: RTF 1.13; ❌ steady_state_realtime: steady 0.902× (from TTFB+1 s), 80 ms-frame interval med/p95 [81.6, 192.3] ms, 51.1% frames late; min prebuffer 2.15 s |  |
| perf_direction_cfg4_medium | 200 (200) ✅ | 15.64s | 14.16s · F0 91.5 · -24.6 dBFS | ✅ incremental: TTFB 0.264s of 15.64s (2%), 295 chunks, 10/50/90% bytes at [1.75, 7.94, 14.13]s; ❌ realtime: RTF 1.1; ❌ steady_state_realtime: steady 0.926× (from TTFB+1 s), 80 ms-frame interval med/p95 [86.7, 190.4] ms, 53.3% frames late; min prebuffer 1.61 s |  |
| perf_design_cfg1_long | 200 (200) ✅ | 42.46s | 37.92s · F0 130.9 · -21.0 dBFS | ✅ incremental: TTFB 0.217s of 42.46s (0%), 693 chunks, 10/50/90% bytes at [4.4, 21.18, 38.28]s; ❌ realtime: RTF 1.12; ❌ steady_state_realtime: steady 0.894× (from TTFB+1 s), 80 ms-frame interval med/p95 [84.3, 190.1] ms, 52.6% frames late; min prebuffer 4.62 s |  |
| perf_clone_long | 200 (200) ✅ | 38.42s | 34.16s · F0 90.9 · -27.9 dBFS | ✅ incremental: TTFB 0.354s of 38.42s (1%), 631 chunks, 10/50/90% bytes at [4.11, 19.49, 34.67]s; ❌ realtime: RTF 1.12; ❌ steady_state_realtime: steady 0.896× (from TTFB+1 s), 80 ms-frame interval med/p95 [84.3, 192.5] ms, 53.1% frames late; min prebuffer 4.41 s |  |
| dualcfg_buffered | 400 (400) ✅ | 0.29s |  |  | {"detail":"dual CFG (cfg_scale_ref/cfg_scale_ins) is disabled in fast mode 'full' on this server (eager only); use cfg_scale"} |
| dualcfg_stream_rejected | 400 (400) ✅ | 0.17s |  |  | {"detail":"dual CFG (cfg_scale_ref/cfg_scale_ins) is disabled in fast mode 'full' on this server (eager only); use cfg_scale"} |
| sampling_fields | 200 (200) ✅ | 5.51s | 4.88s · F0 166.8 · -21.9 dBFS |  |  |
| clone_longref_70w | 200 (200) ✅ | 33.55s | 29.6s · F0 120.7 · -23.5 dBFS | ✅ not_truncated: 29.6s for 72 words = 2.43 w/s (expect ≈28s @2.6 w/s); ASR ends ''; ✅ incremental: TTFB 0.569s of 33.55s (2%), 534 chunks, 10/50/90% bytes at [3.85, 17.05, 30.25]s; ❌ realtime: RTF 1.13; ❌ steady_state_realtime: steady 0.898× (from TTFB+1 s), 80 ms-frame interval med/p95 [83.6, 191.0] ms, 53.4% frames late; min prebuffer 4.11 s |  |
| voices_delete_pre | 404 (2xx|4xx) ✅ | 0.08s |  |  | {"detail":"no saved voice 'validator-narrator'"} |
| voices_create | 201 (2xx) ✅ | 0.18s |  |  | {"id":"validator-narrator","ref_text":"Long ago, before the rivers found their courses, the old roads ran straight through the mountains, and travellers spoke of lights that walked beside them in the dark.","instruction" |
| voices_list | 200 (200) ✅ | 0.01s |  | ✅ body_contains: validator-narrator | {"voices":[{"id":"fc_narrator","ref_text":"Long ago, before the rivers found their courses, the old roads ran straight through the mountains, and travellers spoke of lights that walked beside them in the dark.","instruct |
| voices_get | 200 (200) ✅ | 0.01s |  |  | {"id":"validator-narrator","ref_text":"Long ago, before the rivers found their courses, the old roads ran straight through the mountains, and travellers spoke of lights that walked beside them in the dark.","instruction" |
| voices_get_audio | 200 (200) ✅ | 0.05s | 11.68s · F0 98.6 · -23.6 dBFS |  |  |
| voices_synth | 200 (200) ✅ | 5.1s | 4.48s · F0 94.2 · -26.4 dBFS | ✅ matches_buffered_same_seed: vs clone_basic: not bit-identical, len 107520 vs 107520, corr 0.9978 |  |
| err_voice_and_ref | 400 (4xx) ✅ | 0.16s |  |  | {"detail":"send either voice or ref_audio, not both"} |
| voices_delete | 204 (2xx) ✅ | 0.01s | 0.0s |  |  |
| err_voice_unknown | 404 (4xx) ✅ | 0.01s |  |  | {"detail":"no saved voice 'validator-narrator'"} |
| convert_revoice | 200 (200) ✅ | 11.18s | 7.84s · F0 89.9 · -27.9 dBFS | ✅ duration_matched: 7.84s vs source 7.84s (1.00×) |  |
| err_missing_text | 400 (422) ❌ | 0.06s |  |  | {"detail":"text is empty. With curl, a value starting with '(', '@' or '<' must be sent with --form-string, not -F (-F sends it empty or as a file)"} |
| err_empty_text | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"text is empty. With curl, a value starting with '(', '@' or '<' must be sent with --form-string, not -F (-F sends it empty or as a file)"} |
| err_whitespace_text | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"text is empty. With curl, a value starting with '(', '@' or '<' must be sent with --form-string, not -F (-F sends it empty or as a file)"} |
| err_bad_seed | 422 (422) ✅ | 0.01s |  |  | {"detail":[{"type":"int_parsing","loc":["body","seed"],"msg":"Input should be a valid integer, unable to parse string as an integer","input":"abc"}]} |
| err_bad_cfg | 422 (422) ✅ | 0.01s |  |  | {"detail":[{"type":"float_parsing","loc":["body","cfg_scale"],"msg":"Input should be a valid number, unable to parse string as a number","input":"nan-ish"}]} |
| err_cfg_no_instruction | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"cfg_scale != 1 strengthens the instruction, so it needs one; send an instruction (e.g. 'Speak clearly and naturally.') or leave cfg_scale at 1"} |
| err_negative_cfg | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"cfg_scale must be greater than 0."} |
| err_garbage_ref_audio | 400 (4xx) ✅ | 0.14s |  |  | {"detail":"could not process ref_audio: [in#0 @ 0xb63adee10920] Error opening input: Invalid data found when processing input\nError opening input file /tmp/breeze_req_1du9z8h3/upload.wav.\nError opening input files: Inv |
| err_ref_text_only | 400 (2xx|4xx) ✅ | 0.01s |  |  | {"detail":"ref_audio and ref_text must be provided together or both omitted."} |
| err_bad_speed | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"speed must be in [0.5, 2.0], got -1.0"} |
| err_speed_high | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"speed must be in [0.5, 2.0], got 3.0"} |
| err_speed_engine | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"speed_engine must be one of rubberband, atempo"} |
| err_unknown_field | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"unknown field(s): foo; accepted: cfg_scale, cfg_scale_ins, cfg_scale_ref, depth_temperature, depth_top_k, depth_top_p, do_sample, instruction, limiter, max_new_tokens, raw, ref_audio, ref_text, repetition_pena |
| err_text_over_1000 | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"text is 1555 characters; send at most 1000 per request (~350 keeps long-form quality steady) and stitch"} |
| err_bad_response_format | 400 (4xx) ✅ | 0.01s |  |  | {"detail":"response_format must be 'pcm' or 'wav'"} |
| err_ref_over_60s | 400 (4xx) ✅ | 0.58s |  |  | {"detail":"ref_audio is 70.1s; keep it under 60s (3-30s of clean speech clones best)"} |

## perf subset

| id | audio s | TTFA s | audio s/wall s | steady × | 80ms-frame med/p95 ms | late % | prebuffer s |
|---|---|---|---|---|---|---|---|
| perf_design_cfg1_short | 5.68 | 0.159 | 0.87 | 0.9 | [86.6, 184.4] | 55.2 | 0.84 |
| perf_design_cfg1_medium | 14.0 | 0.136 | 0.89 | 0.891 | [68.8, 219.1] | 45.7 | 1.84 |
| perf_design_cfg4_medium | 12.0 | 0.251 | 0.91 | 0.915 | [57.1, 220.7] | 41.2 | 1.33 |
| perf_clone_short | 4.48 | 0.286 | 0.85 | 0.919 | [87.5, 186.4] | 54.5 | 0.86 |
| perf_clone_medium | 15.84 | 0.24 | 0.89 | 0.902 | [81.6, 192.3] | 51.1 | 2.15 |
| perf_direction_cfg4_medium | 14.16 | 0.264 | 0.91 | 0.926 | [86.7, 190.4] | 53.3 | 1.61 |
| perf_design_cfg1_long | 37.92 | 0.217 | 0.89 | 0.894 | [84.3, 190.1] | 52.6 | 4.62 |
| perf_clone_long | 34.16 | 0.354 | 0.89 | 0.896 | [84.3, 192.5] | 53.1 | 4.41 |

**steady-state median 0.901× (min 0.891, max 0.926)**
