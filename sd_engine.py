"""Types de nœuds, schéma moteur CreativeCore et évaluation du graphe (sans Qt)."""

from __future__ import annotations

import sys
from pathlib import Path

from sd_curves import eval_curve, normalize_curve

CREATIVE_CORE_ROOT = Path("/home/deanos/Documents/CreativeSysteme v1.0")
BLEND_MODES = ["normal", "multiply", "screen", "overlay", "darken", "lighten"]
LINEAR = [[0, 0], [1, 1]]

# param : (clé, libellé, type, défaut, extra) — type ∈ number|choice|bool|engine_key|engine_value|curve
# "inline" : paramètres affichés et modifiables directement sur le nœud.
NODE_TYPES = {
    "Input": dict(label="Entrée", category="Signaux", color="#6CC8FF", ins=0, outs=1,
                  help="Signal venant de l'utilisateur, normalisé entre 0 et 1, puis façonné par la courbe.",
                  inline=["source", "gain", "curve"],
                  params=[("source", "Source", "choice", "pressure", ["pressure", "velocity", "tilt", "direction", "random", "distance", "pointer", "layer", "mask", "selection"]),
                          ("gain", "Gain", "number", 1.0, (0.0, 4.0, 0.05)),
                          ("curve", "Courbe", "curve", LINEAR, None),
                          ("min", "Sortie min", "number", 0.0, (0.0, 1.0, 0.01)),
                          ("max", "Sortie max", "number", 1.0, (0.0, 1.0, 0.01))]),
    "Constant": dict(label="Constante", category="Signaux", color="#6CC8FF", ins=0, outs=1,
                     help="Valeur fixe entre 0 et 1 (utile pour régler un Combiner ou une Condition).",
                     inline=["value"], params=[("value", "Valeur", "number", 0.5, (0.0, 1.0, 0.01))]),
    "Curve": dict(label="Courbe", category="Logique", color="#9FE7FF", ins=1, outs=1,
                  help="Remappe le signal entrant avec une courbe libre.",
                  inline=["curve"], params=[("curve", "Courbe", "curve", [[0, 0], [0.5, 0.2], [1, 1]], None)]),
    "Combine": dict(label="Combiner", category="Logique", color="#9FE7FF", ins=1, outs=1,
                    help="Combine TOUS les signaux reliés à son entrée (ex. pression × vitesse).",
                    inline=["op"],
                    params=[("op", "Opération", "choice", "multiplier", ["moyenne", "multiplier", "additionner", "soustraire", "minimum", "maximum", "différence", "écran"])]),
    "Condition": dict(label="Condition", category="Logique", color="#C596FF", ins=1, outs=1,
                      help="Teste le signal (au-dessus, en-dessous, entre, hors de) et produit une porte ou laisse passer.",
                      inline=["test", "a", "b"],
                      params=[("test", "Si le signal est", "choice", "au-dessus", ["au-dessus", "en-dessous", "entre", "hors de"]),
                              ("a", "Seuil A", "number", 0.5, (0.0, 1.0, 0.01)),
                              ("b", "Seuil B", "number", 0.8, (0.0, 1.0, 0.01)),
                              ("soft", "Transition", "number", 0.05, (0.0, 0.5, 0.01)),
                              ("output", "Sortie", "choice", "laisser passer", ["laisser passer", "porte 0/1", "bloquer (inverse)"])]),
    "Dynamics": dict(label="Dynamique", category="Moteur", color="#8C9EFF", ins=1, outs=1,
                     help="Fait varier un paramètre CreativeCore : signal 0 → Min, signal 1 → Max (après la courbe).",
                     inline=["target", "min", "max", "curve"],
                     params=[("target", "Pilote", "engine_key", "size", "float"),
                             ("mode", "Mode", "choice", "multiplier", ["multiplier", "ajouter", "remplacer"]),
                             ("min", "Min", "number", 0.1, (0.0, 2.0, 0.01)),
                             ("max", "Max", "number", 1.0, (0.0, 2.0, 0.01)),
                             ("curve", "Courbe", "curve", LINEAR, None),
                             ("amount", "Intensité", "number", 1.0, (0.0, 1.0, 0.01)),
                             ("invert", "Inverser le signal", "bool", False, None)]),
    "EngineParam": dict(label="Paramètre moteur", category="Moteur", color="#F5C56B", ins=1, outs=1,
                        help="Fixe la valeur d'un paramètre CreativeCore pour cet outil.",
                        inline=["key", "value"],
                        params=[("key", "Paramètre", "engine_key", "hardness", "any"),
                                ("value", "Valeur", "engine_value", 0.8, None)]),
    "Shape": dict(label="Forme", category="Forme", color="#FF9ECF", ins=1, outs=1,
                  help="Forme de la touche.",
                  inline=["sizeScale", "roundness", "angle", "hardness"],
                  params=[("sizeScale", "Échelle", "number", 1.0, (0.1, 4.0, 0.05)),
                          ("roundness", "Rondeur", "number", 1.0, (0.05, 1.0, 0.01)),
                          ("angle", "Angle", "number", 0.0, (-180.0, 180.0, 1.0)),
                          ("spacing", "Espacement", "number", 0.15, (0.02, 2.0, 0.01)),
                          ("hardness", "Dureté", "number", 0.8, (0.0, 1.0, 0.01))]),
    "Scatter": dict(label="Dispersion", category="Forme", color="#FF9ECF", ins=1, outs=1,
                    help="Disperse et fait varier chaque touche.",
                    inline=["scatter", "sizeJitter", "rotationJitter"],
                    params=[("scatter", "Dispersion", "number", 0.5, (0.0, 3.0, 0.05)),
                            ("sizeJitter", "Var. taille", "number", 0.2, (0.0, 1.0, 0.01)),
                            ("randomOpacity", "Var. opacité", "number", 0.0, (0.0, 1.0, 0.01)),
                            ("rotationJitter", "Var. rotation", "number", 30.0, (0.0, 360.0, 1.0))]),
    "Blend": dict(label="Fusion", category="Composition", color="#C596FF", ins=1, outs=1,
                  help="Mode de fusion appliqué au résultat.",
                  inline=["mode", "contribution"],
                  params=[("mode", "Mode", "choice", "normal", BLEND_MODES),
                          ("channel", "Canal", "choice", "RGB", ["RGB", "R", "G", "B", "Alpha"]),
                          ("contribution", "Contribution", "number", 1.0, (0.0, 1.0, 0.01))]),
    "Mask": dict(label="Masque", category="Composition", color="#C596FF", ins=1, outs=1,
                 help="Atténue l'effet.",
                 inline=["amount"],
                 params=[("amount", "Intensité", "number", 1.0, (0.0, 1.0, 0.01)),
                         ("source", "Source", "choice", "layer", ["layer", "selection", "texture", "curve"])]),
    "Output": dict(label="Sortie", category="Sorties", color="#5CE1B9", ins=1, outs=0,
                   help="Ce que l'outil produit. Seuls les nœuds reliés à une Sortie comptent.",
                   inline=["resource_type"],
                   params=[("resource_type", "Produit", "choice", "brush_engine", ["brush_engine", "blend_definition", "blend_result", "effect"])]),
}
PALETTE = {
    "brush_engine": ["Input", "Constant", "Curve", "Combine", "Condition", "Dynamics", "EngineParam", "Shape", "Scatter", "Blend", "Mask", "Output"],
    "blend": ["Input", "Constant", "Curve", "Combine", "Condition", "Blend", "Mask", "Output"],
}

FALLBACK_BRUSH = {
    "settings": {"size": 12.0, "opacity": 1.0, "flow": 1.0, "hardness": 0.8, "spacing": 0.15,
                 "roundness": 1.0, "angle": 0.0, "scatter": 0.0, "sizeJitter": 0.0,
                 "rotationJitter": 0.0, "minimumSize": 0.05, "velocitySize": 0.0,
                 "velocityOpacity": 0.0, "tiltSize": 0.0, "pressureSize": True,
                 "pressureOpacity": False},
    "float_groups": {
        "Base": [("size", "Taille", 0.1, 400.0, 1.0), ("opacity", "Opacité", 0.0, 1.0, 0.01),
                 ("flow", "Flow", 0.0, 1.0, 0.01), ("hardness", "Dureté", 0.0, 1.0, 0.01),
                 ("spacing", "Espacement", 0.01, 5.0, 0.01), ("roundness", "Rondeur", 0.01, 1.0, 0.01),
                 ("angle", "Angle", -360.0, 360.0, 1.0), ("scatter", "Dispersion", 0.0, 5.0, 0.01),
                 ("sizeJitter", "Variation taille", 0.0, 1.0, 0.01),
                 ("rotationJitter", "Variation rotation", 0.0, 360.0, 1.0)],
        "Pression": [("minimumSize", "Taille minimale", 0.0, 1.0, 0.01),
                     ("velocitySize", "Vitesse → taille", 0.0, 1.0, 0.01),
                     ("velocityOpacity", "Vitesse → opacité", 0.0, 1.0, 0.01),
                     ("tiltSize", "Inclinaison → taille", 0.0, 1.0, 0.01)],
    },
    "bool_groups": {"Pression": [("pressureSize", "Pression → taille"), ("pressureOpacity", "Pression → opacité")]},
    "backend": "Schéma intégré (CreativeCore introuvable)",
}

_CAPS = None
_FIELDS = None


def creative_core_capabilities() -> dict:
    global _CAPS
    if _CAPS is not None:
        return _CAPS
    result = {"available": False, "brush": dict(FALLBACK_BRUSH),
              "blend": {"blend_modes": BLEND_MODES, "channels": ["RGB", "R", "G", "B", "Alpha"]}}
    if CREATIVE_CORE_ROOT.exists():
        root = str(CREATIVE_CORE_ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            from TOOLS.brush_settings_state import DEFAULT_BRUSH_SETTINGS
            from UI.docks.brush_settings_dialog import FLOAT_GROUPS, BOOL_GROUPS
            result["brush"] = {
                "settings": dict(DEFAULT_BRUSH_SETTINGS),
                "float_groups": {k: list(v) for k, v in FLOAT_GROUPS.items()},
                "bool_groups": {k: list(v) for k, v in BOOL_GROUPS.items()},
                "backend": f"CreativeCore / BrushEngine · {len(DEFAULT_BRUSH_SETTINGS)} paramètres",
            }
            result["available"] = True
            try:
                from DOCUMENTS.blend_graph import backend_capabilities
                result["blend"] = backend_capabilities()
            except Exception as exc:  # noqa: BLE001
                result["blend_error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
    _CAPS = result
    return result


def engine_fields() -> dict:
    global _FIELDS
    if _FIELDS is None:
        brush = creative_core_capabilities()["brush"]
        out = {}
        for group, fields in brush["float_groups"].items():
            for key, text, lo, hi, step in fields:
                out[key] = dict(label=text, group=group, kind="float", lo=float(lo), hi=float(hi),
                                step=float(step), default=brush["settings"].get(key, lo))
            for key, text in brush["bool_groups"].get(group, []):
                out[key] = dict(label=text, group=group, kind="bool", default=bool(brush["settings"].get(key, False)))
        _FIELDS = out
    return _FIELDS


def field_label(key):
    f = engine_fields().get(key)
    return f"{f['label']} ({key})" if f else str(key)


def default_config(node_type):
    return {p[0]: (normalize_curve(p[3]) if p[2] == "curve" else p[3]) for p in NODE_TYPES[node_type]["params"]}


# ─── Analyse ────────────────────────────────────────────────────────────────
def _parents(edges):
    out = {}
    for a, b in edges:
        out.setdefault(b, []).append(a)
    return out


def active_nodes(model):
    nodes, edges = model
    outs = [n["id"] for n in nodes if n["type"] == "Output"]
    if not outs:
        return nodes, False
    parents = _parents(edges)
    keep, stack = set(), list(outs)
    while stack:
        cur = stack.pop()
        if cur in keep:
            continue
        keep.add(cur)
        stack.extend(parents.get(cur, []))
    return [n for n in nodes if n["id"] in keep], True


def has_upstream_input(node_id, model):
    nodes, edges = model
    types = {n["id"]: n["type"] for n in nodes}
    parents = _parents(edges)
    stack, seen = list(parents.get(node_id, [])), set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        if types.get(cur) in ("Input", "Constant"):
            return True
        stack.extend(parents.get(cur, []))
    return False


def topo_order(nodes, edges):
    ids = [n["id"] for n in nodes]
    idset = set(ids)
    indeg = {i: 0 for i in ids}
    children = {}
    for a, b in edges:
        if a in idset and b in idset:
            indeg[b] += 1
            children.setdefault(a, []).append(b)
    queue = [i for i in ids if indeg[i] == 0]
    order = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for c in children.get(cur, []):
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    return order + [i for i in ids if i not in order]


def compile_graph(engine: dict, model) -> dict:
    """Prépare le graphe : réglages statiques + ordre d'évaluation des signaux."""
    nodes, edges = model
    fields = engine_fields()
    s = dict(engine)
    s.setdefault("size", 12.0)
    driven = {}
    composition, mask = "normal", 1.0
    active, has_output = active_nodes(model)
    by_id = {n["id"]: dict(n, config=dict(n.get("config") or {})) for n in active}
    for n in by_id.values():
        cfg, t, title = n["config"], n["type"], n.get("title") or n["type"]
        for key, _l, kind, default, _e in NODE_TYPES.get(t, {"params": []})["params"]:
            if kind == "curve":
                cfg[key] = normalize_curve(cfg.get(key, default))
        if t == "EngineParam" and cfg.get("key"):
            key = cfg["key"]
            f = fields.get(key, {})
            s[key] = bool(cfg.get("value")) if f.get("kind") == "bool" else float(cfg.get("value") or 0.0)
            driven.setdefault(key, []).append(f"{title} (fixé)")
        elif t == "Shape":
            s["size"] = float(s["size"]) * float(cfg.get("sizeScale", 1.0))
            for k in ("roundness", "angle", "spacing", "hardness"):
                if k in cfg:
                    s[k] = float(cfg[k])
                    driven.setdefault(k, []).append(f"{title} (forme)")
        elif t == "Scatter":
            for k in ("scatter", "sizeJitter", "rotationJitter", "randomOpacity"):
                if k in cfg:
                    s[k] = float(cfg[k])
                    driven.setdefault(k, []).append(f"{title} (dispersion)")
        elif t == "Dynamics":
            driven.setdefault(cfg.get("target", "size"), []).append(f"{title} (dynamique)")
        elif t == "Blend":
            composition = cfg.get("mode", "normal")
            mask *= float(cfg.get("contribution", 1.0))
        elif t == "Mask":
            mask *= float(cfg.get("amount", 1.0))
    ids = set(by_id)
    act_edges = [(a, b) for a, b in edges if a in ids and b in ids]
    return {"base": s, "nodes": by_id, "order": topo_order(list(by_id.values()), act_edges),
            "parents": _parents(act_edges), "composition": composition, "mask": mask,
            "has_output": has_output, "driven": driven}


def _smooth(x, edge, soft):
    if soft <= 0:
        return 1.0 if x >= edge else 0.0
    t = max(0.0, min(1.0, (x - edge) / soft + 0.5))
    return t * t * (3 - 2 * t)


def _combine(op, vals):
    if not vals:
        return 0.0
    if op == "multiplier":
        r = 1.0
        for v in vals:
            r *= v
    elif op == "additionner":
        r = sum(vals)
    elif op == "soustraire":
        r = vals[0] - sum(vals[1:])
    elif op == "minimum":
        r = min(vals)
    elif op == "maximum":
        r = max(vals)
    elif op == "différence":
        r = abs(vals[0] - (vals[1] if len(vals) > 1 else 0.0))
    elif op == "écran":
        r = 1.0
        for v in vals:
            r *= (1.0 - v)
        r = 1.0 - r
    else:
        r = sum(vals) / len(vals)
    return max(0.0, min(1.0, r))


def evaluate(compiled: dict, raw: dict):
    """Évalue le graphe pour un échantillon (une touche). Renvoie (réglages, signaux)."""
    s = dict(compiled["base"])
    fields = engine_fields()
    values = {}
    parents = compiled["parents"]
    for nid in compiled["order"]:
        n = compiled["nodes"][nid]
        cfg, t = n["config"], n["type"]
        ins = [values[p] for p in parents.get(nid, []) if values.get(p) is not None]
        avg = sum(ins) / len(ins) if ins else None
        if t == "Input":
            x = max(0.0, min(1.0, float(raw.get(cfg.get("source", "pressure"), raw.get("pressure", 1.0))) * float(cfg.get("gain", 1.0))))
            x = eval_curve(cfg.get("curve", LINEAR), x)
            lo, hi = float(cfg.get("min", 0.0)), float(cfg.get("max", 1.0))
            values[nid] = lo + (hi - lo) * x
        elif t == "Constant":
            values[nid] = float(cfg.get("value", 0.5))
        elif t == "Curve":
            values[nid] = eval_curve(cfg.get("curve", LINEAR), avg if avg is not None else 0.0)
        elif t == "Combine":
            values[nid] = _combine(cfg.get("op", "moyenne"), ins)
        elif t == "Condition":
            x = avg if avg is not None else 0.0
            a, b, soft = float(cfg.get("a", cfg.get("threshold", 0.5))), float(cfg.get("b", 0.8)), float(cfg.get("soft", 0.0))
            above_a = _smooth(x, a, soft)
            below_b = 1.0 - _smooth(x, b, soft)
            gate = {"au-dessus": above_a, "en-dessous": 1.0 - above_a, "entre": above_a * below_b,
                    "hors de": 1.0 - above_a * below_b}.get(cfg.get("test", "au-dessus"), above_a)
            out = cfg.get("output", "laisser passer")
            values[nid] = gate if out.startswith("porte") else x * (1.0 - gate) if out.startswith("bloquer") else x * gate
        elif t == "Dynamics":
            x = avg if avg is not None else float(raw.get("pressure", 1.0))
            if cfg.get("invert"):
                x = 1.0 - x
            values[nid] = x
            k = eval_curve(cfg.get("curve", LINEAR), x)
            lo, hi = float(cfg.get("min", 0.1)), float(cfg.get("max", 1.0))
            level = lo + (hi - lo) * k
            key = cfg.get("target", "size")
            f = fields.get(key, {})
            base = s.get(key, f.get("default", 0.0))
            if isinstance(base, bool) or f.get("kind") == "bool":
                s[key] = level >= 0.5
                continue
            base = float(base or 0.0)
            mode = cfg.get("mode", "multiplier")
            if mode == "ajouter":
                target = base + level * ((f.get("hi", 1.0) - f.get("lo", 0.0)) if f else 1.0)
            elif mode == "remplacer":
                flo, fhi = (f.get("lo", 0.0), f.get("hi", 1.0)) if f else (0.0, 1.0)
                target = flo + (fhi - flo) * min(1.0, level)
            else:
                target = base * level
            value = base + (target - base) * float(cfg.get("amount", 1.0))
            if f and key != "angle":
                value = max(f["lo"], min(f["hi"], value))
            s[key] = value
        else:
            values[nid] = avg
    s["composition"] = compiled["composition"]
    s["mask"] = compiled["mask"]
    return s, values


def graph_issues(model, native_errors=(), definition=None):
    nodes, edges = model
    issues = []
    if definition is not None and not str(definition.get("name", "")).strip():
        issues.append(("error", "L'outil n'a pas de nom (étape Définition)", None))
    for err in native_errors or []:
        issues.append(("error", f"Moteur natif : {err}", None))
    if not nodes:
        return issues + [("error", "Le graphe est vide · ajoute au moins une Entrée et une Sortie", None)]
    types = [n["type"] for n in nodes]
    if "Input" not in types:
        issues.append(("error", "Aucune Entrée : l'outil ne reçoit aucun signal", None))
    if "Output" not in types:
        issues.append(("error", "Aucune Sortie : l'outil ne produit rien", None))
    elif types.count("Output") > 1:
        issues.append(("warning", "Plusieurs Sorties : seule la première sera publiée", None))
    linked = {a for a, _ in edges} | {b for _, b in edges}
    active, _ = active_nodes(model)
    active_ids = {n["id"] for n in active}
    parents = _parents(edges)
    for n in nodes:
        name = n.get("title", n["id"])
        if n["id"] not in linked and len(nodes) > 1:
            issues.append(("warning", f"« {name} » n'est relié à rien", n["id"]))
        elif n["type"] == "Output" and not has_upstream_input(n["id"], model):
            issues.append(("error", f"« {name} » ne reçoit aucune Entrée", n["id"]))
        elif "Output" in types and n["id"] in linked and n["id"] not in active_ids:
            issues.append(("warning", f"« {name} » n'atteint aucune Sortie (ignoré)", n["id"]))
        elif n["type"] in ("Curve", "Condition", "Combine") and not parents.get(n["id"]):
            issues.append(("warning", f"« {name} » n'a pas de signal en entrée", n["id"]))
        elif n["type"] == "Combine" and len(parents.get(n["id"], [])) < 2:
            issues.append(("warning", f"« {name} » ne combine qu'un seul signal", n["id"]))
        elif n["type"] == "Condition" and (n.get("config") or {}).get("test") in ("entre", "hors de") \
                and float((n.get("config") or {}).get("a", 0)) >= float((n.get("config") or {}).get("b", 1)):
            issues.append(("warning", f"« {name} » : le seuil A doit être inférieur au seuil B", n["id"]))
    return issues
