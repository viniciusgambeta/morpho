"""Imprime um resumo de um ou mais bench_*.json (uma linha por execução)."""
import json, sys

def f(v, nd=1):
    return "-" if v is None else f"{v:.{nd}f}"

for path in sys.argv[1:]:
    r = json.load(open(path, encoding="utf-8"))
    p, g, sc = r["paced"], r["gpu"], r["swap_check"]
    lat = p["latency_ms"] or {}
    prof = "  ".join(f"{k}={v['ms']:.1f}ms/{v['calls']}" for k, v in r["profile_ms_per_call"].items())
    sw = r["session_providers"].get("swapper") or r["session_providers"].get("swapper.session_class") or "?"
    print(f"== {r['tag']}  [{r['flavor']} {r['commit']}]  modelo={r['swapper_model']}  cli={' '.join(r['cli'])}  set={r['overrides']}")
    print(f"   vazao {f(r['throughput_fps'])} fps (parado {f(r['throughput_rest_fps'])} / movimento {f(r['throughput_motion_fps'])})"
          f" | ritmado {f(p['fps'])} fps, entregue {f(p['delivered_pct'], 0)}%, latencia p50 {f(lat.get('p50'), 0)} / p95 {f(lat.get('p95'), 0)} ms")
    print(f"   troca aplicada em {f(sc['frames_changed_pct'], 0)}% dos quadros ({f(sc['mean_pixels_changed_pct'])}% dos pixels)"
          f" | partida a frio {f(r['cold_start']['total_s'])} s | VRAM +{f(g['delta_vram_mib'], 0)} MiB (pico {f(g['peak_vram_mib'], 0)})"
          f" | GPU {f((g['throughput_pass'] or {}).get('gpu_util_mean_pct'), 0)}% {f((g['throughput_pass'] or {}).get('power_mean_w'), 0)} W")
    tp, pp = g["throughput_pass"] or {}, g["paced_pass"] or {}
    print(f"   clock da GPU (MHz): vazao {f(tp.get('clock_min_mhz'), 0)}-{f(tp.get('clock_max_mhz'), 0)}"
          f" | ritmado {f(pp.get('clock_min_mhz'), 0)}-{f(pp.get('clock_max_mhz'), 0)}")
    print(f"   sessao swapper: {sw}")
    print(f"   perfil: {prof}")
