"""Transparent confidence model (CLAUDE.md section 6, thresholds in config/thresholds.json).

Confidence is computed from named components, each in [0, 1]; it is never typed in.

  analytical confidence  = weighted mean of completeness, observations, consistency,
                           magnitude and evidence_quality (weights renormalised to sum to 1)
  validated confidence   = the same five components plus `validation`
                           (PASS 1.0 / WARN 0.5 / REJECT 0.0), with the full weight set

Analysis agents publish the analytical confidence; the Evidence Validation agent publishes
the validated one. Both carry their components so a reader can recompute them.
"""
from src.config import load_json, project_path

ANALYTICAL = ["completeness", "observations", "consistency", "magnitude", "evidence_quality"]


def _cfg():
    return load_json(project_path("config/thresholds.json"))["confidence"]


def components(completeness, n_observations, consistency, effect_sd, evidence_quality=1.0):
    cfg = _cfg()
    return {
        "completeness": round(max(0.0, min(1.0, completeness)), 3),
        "observations": round(min(1.0, n_observations / cfg["observations_saturation"]), 3),
        "consistency": round(max(0.0, min(1.0, consistency)), 3),
        "magnitude": round(min(1.0, abs(effect_sd) / cfg["magnitude_saturation_sd"]), 3),
        "evidence_quality": round(max(0.0, min(1.0, evidence_quality)), 3),
    }


def analytical(comp):
    w = _cfg()["weights"]
    total = sum(w[k] for k in ANALYTICAL)
    score = sum(w[k] * comp[k] for k in ANALYTICAL) / total
    return {"score": round(score, 2), "stage": "analytical", "components": comp}


def build(completeness, n_observations, consistency, effect_sd, evidence_quality=1.0):
    return analytical(components(completeness, n_observations, consistency, effect_sd, evidence_quality))


def combine(confidences):
    """Confidence of a finding built from several others (e.g. a risk): component-wise mean."""
    confidences = [c for c in confidences if c]
    if not confidences:
        return build(0, 0, 0, 0, 0)
    comp = {k: round(sum(c["components"][k] for c in confidences) / len(confidences), 3) for k in ANALYTICAL}
    return analytical(comp)


def validated(conf, verdict):
    cfg = _cfg()
    comp = dict(conf["components"])
    comp["validation"] = cfg["validation_factor"][verdict]
    score = sum(cfg["weights"][k] * comp[k] for k in comp)
    return {"score": round(score, 2), "stage": "validated", "components": comp}
