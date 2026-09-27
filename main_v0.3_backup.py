"""StellarDust — atelier de conception d'outils d'Existence.

v0.3 : refonte UX.
- éditeur de graphe réel (ports glisser-déposer, liaisons courbes supprimables,
  zoom/pan, menu contextuel, glisser depuis la palette, annuler/rétablir) ;
- un seul fil de navigation (Définition → Construction → Paramètres → Test →
  Publication) au lieu de trois systèmes d'onglets concurrents ;
- surface de test qui dessine vraiment avec les réglages du moteur ET du graphe
  (pression tablette, inclinaison, vitesse) ;
- sauvegarde automatique complète (positions, réglages, définition) par Creator,
  export JSON, validation lisible et cliquable ;
- plus aucune donnée factice ni bouton mort.
"""
from __future__ import annotations

import json
import math
import random
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QDrag, QFont, QImage, QKeySequence, QLinearGradient,
    QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QRadialGradient, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QStackedWidget, QStatusBar, QTabWidget,
    QTextEdit, QToolBox, QVBoxLayout, QWidget,
)

try:
    from core_bridge import StellarDustCore
except ImportError:
    StellarDustCore = None


ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "stardust_state.json"
STARDUST_BUILD_ID = "0.3.1-engine-link"
CREATIVE_CORE_ROOT = Path("/home/deanos/Documents/CreativeSysteme v1.0")
MIME_NODE = "application/x-stardust-node"

# ─── Palette ────────────────────────────────────────────────────────────────
C = {
    "bg": "#0B1224", "panel": "#111A31", "panel2": "#0E172B", "line": "#243251",
    "text": "#EAF0FF", "muted": "#7F91B8", "dim": "#56678C", "accent": "#8C9EFF",
    "primary": "#7667E8", "ok": "#5CE1B9", "warn": "#F5C56B", "err": "#FF7A8A",
}

CREATOR_MODE_ALIASES = {
    "blend": "blend", "blend_creator": "blend", "blend-creator": "blend",
    "fusion_creator": "blend", "fusion-creator": "blend",
    "brush_engine": "brush_engine", "brush-engine": "brush_engine",
    "brush_engine_creator": "brush_engine",
}


@dataclass(frozen=True)
class CreatorDefinition:
    """Définition stable d'un Creator hébergeable par StellarDust."""
    module_id: str
    mode: str
    label: str
    description: str
    output_kind: str
    inputs: tuple[str, ...]


CREATOR_DEFINITIONS = {
    "brush_engine": CreatorDefinition(
        "brush_engine_creator", "brush_engine", "Brush Engine Creator",
        "Construire des moteurs de pinceau contrôlés par CreativeCore.",
        "brush_engine", ("pointer", "pressure", "velocity", "tilt"),
    ),
    "fusion_creator": CreatorDefinition(
        "fusion_creator", "blend", "Fusion Creator",
        "Construire des comportements de fusion et de composition.",
        "blend_definition", ("layer", "mask", "selection"),
    ),
}


def creator_mode(value: str) -> str:
    return CREATOR_MODE_ALIASES.get(str(value or "").strip().casefold(), "brush_engine")


def creator_def(mode: str) -> CreatorDefinition:
    return CREATOR_DEFINITIONS["fusion_creator" if mode == "blend" else "brush_engine"]


# ─── Types de nœuds ─────────────────────────────────────────────────────────
# param: (key, label, kind, default, extra)  kind ∈ number|choice|bool
BLEND_MODES = ["normal", "multiply", "screen", "overlay", "darken", "lighten"]

CURVES = ["linéaire", "douce (ease-in)", "forte (ease-out)", "en S", "inversée"]
NODE_TYPES = {
    "Input": dict(label="Entrée", category="Entrées", color="#6CC8FF", ins=0, outs=1,
                  help="Signal venant de l'utilisateur (stylet, calque…), normalisé entre 0 et 1.",
                  params=[("source", "Source", "choice", "pressure", ["pressure", "velocity", "tilt", "random", "pointer", "layer", "mask", "selection"]),
                          ("gain", "Gain", "number", 1.0, (0.0, 4.0, 0.05)),
                          ("curve", "Courbe", "choice", "linéaire", CURVES),
                          ("min", "Sortie min", "number", 0.0, (0.0, 1.0, 0.01)),
                          ("max", "Sortie max", "number", 1.0, (0.0, 1.0, 0.01))]),
    "Dynamics": dict(label="Dynamique", category="Comportement", color="#8C9EFF", ins=1, outs=1,
                     help="Fait varier N'IMPORTE QUEL paramètre du moteur selon le signal reçu (0 → Min, 1 → Max).",
                     params=[("target", "Paramètre piloté", "engine_key", "size", "float"),
                             ("mode", "Mode", "choice", "multiplier", ["multiplier", "ajouter", "remplacer"]),
                             ("min", "Min", "number", 0.1, (0.0, 2.0, 0.01)),
                             ("max", "Max", "number", 1.0, (0.0, 2.0, 0.01)),
                             ("curve", "Courbe", "choice", "linéaire", CURVES),
                             ("amount", "Intensité", "number", 1.0, (0.0, 1.0, 0.01)),
                             ("invert", "Inverser le signal", "bool", False, None)]),
    "EngineParam": dict(label="Paramètre moteur", category="Moteur", color="#F5C56B", ins=1, outs=1,
                        help="Fixe la valeur d'un paramètre de CreativeCore pour cet outil (remplace la valeur de l'onglet Moteur).",
                        params=[("key", "Paramètre", "engine_key", "hardness", "any"),
                                ("value", "Valeur", "engine_value", 0.8, None)]),
    "Condition": dict(label="Condition", category="Comportement", color="#C596FF", ins=1, outs=1,
                      help="Coupe le signal selon un seuil (avec transition douce optionnelle).",
                      params=[("threshold", "Seuil", "number", 0.5, (0.0, 1.0, 0.01)),
                              ("direction", "Laisser passer", "choice", "au-dessus", ["au-dessus", "en-dessous"]),
                              ("soft", "Transition", "number", 0.0, (0.0, 0.5, 0.01))]),
    "Shape": dict(label="Forme", category="Forme", color="#FF9ECF", ins=1, outs=1,
                  help="Forme de la touche : taille, rondeur, angle, espacement, dureté.",
                  params=[("sizeScale", "Échelle taille", "number", 1.0, (0.1, 4.0, 0.05)),
                          ("roundness", "Rondeur", "number", 1.0, (0.05, 1.0, 0.01)),
                          ("angle", "Angle", "number", 0.0, (-180.0, 180.0, 1.0)),
                          ("spacing", "Espacement", "number", 0.15, (0.02, 2.0, 0.01)),
                          ("hardness", "Dureté", "number", 0.8, (0.0, 1.0, 0.01))]),
    "Scatter": dict(label="Dispersion", category="Forme", color="#FF9ECF", ins=1, outs=1,
                    help="Disperse et fait varier chaque touche.",
                    params=[("scatter", "Dispersion", "number", 0.5, (0.0, 3.0, 0.05)),
                            ("sizeJitter", "Variation taille", "number", 0.2, (0.0, 1.0, 0.01)),
                            ("randomOpacity", "Variation opacité", "number", 0.0, (0.0, 1.0, 0.01)),
                            ("rotationJitter", "Variation rotation", "number", 30.0, (0.0, 360.0, 1.0))]),
    "Blend": dict(label="Fusion", category="Composition", color="#C596FF", ins=1, outs=1,
                  help="Mode de fusion appliqué au résultat.",
                  params=[("mode", "Mode", "choice", "normal", BLEND_MODES),
                          ("channel", "Canal", "choice", "RGB", ["RGB", "R", "G", "B", "Alpha"]),
                          ("contribution", "Contribution", "number", 1.0, (0.0, 1.0, 0.01))]),
    "Mask": dict(label="Masque", category="Composition", color="#C596FF", ins=1, outs=1,
                 help="Limite l'effet (atténue l'opacité).",
                 params=[("amount", "Intensité", "number", 1.0, (0.0, 1.0, 0.01)),
                         ("source", "Source", "choice", "layer", ["layer", "selection", "texture", "curve"])]),
    "Output": dict(label="Sortie", category="Sorties", color="#5CE1B9", ins=1, outs=0,
                   help="Ce que l'outil produit. Seuls les nœuds reliés à une sortie comptent.",
                   params=[("resource_type", "Produit", "choice", "brush_engine", ["brush_engine", "blend_definition", "blend_result", "effect"])]),
}
PALETTE = {
    "brush_engine": ["Input", "Dynamics", "Condition", "EngineParam", "Shape", "Scatter", "Blend", "Mask", "Output"],
    "blend": ["Input", "Condition", "Blend", "Mask", "Output"],
}

# Schéma de secours si CreativeCore n'est pas trouvé : l'app reste utilisable.
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


def discover_existence_modules() -> dict[str, bool]:
    config = Path.home() / ".config" / "existence" / "apps.json"
    try:
        apps = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fusion_creator": False}
    fusion = next((item for item in apps if isinstance(item, dict) and item.get("id") == "fusion_creator"), None)
    connected = bool(
        fusion and fusion.get("orbit_of") == "stardust"
        and fusion.get("app_kind") == "orbital_module"
        and fusion.get("availability_state", "available") == "available"
        and fusion.get("lifecycle_state", "available") != "closed"
    )
    return {"fusion_creator": connected}


_CAPS_CACHE: dict | None = None


def creative_core_capabilities() -> dict:
    """Schémas canoniques de Creative Core (mis en cache), sinon schéma intégré."""
    global _CAPS_CACHE
    if _CAPS_CACHE is not None:
        return _CAPS_CACHE
    result = {"available": False, "brush": dict(FALLBACK_BRUSH), "blend": {"blend_modes": BLEND_MODES, "channels": ["RGB", "R", "G", "B", "Alpha"]}}
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
            except Exception as exc:  # noqa: BLE001 — module optionnel
                result["blend_error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
    _CAPS_CACHE = result
    return result


_FIELDS_CACHE: dict | None = None


def engine_fields() -> dict:
    """{clé: dict(label, group, kind, lo, hi, step, default)} depuis le schéma moteur réel."""
    global _FIELDS_CACHE
    if _FIELDS_CACHE is None:
        brush = creative_core_capabilities()["brush"]
        out = {}
        for group, fields in brush["float_groups"].items():
            for key, text, lo, hi, step in fields:
                out[key] = dict(label=text, group=group, kind="float", lo=float(lo), hi=float(hi), step=float(step),
                                default=brush["settings"].get(key, lo))
            for key, text in brush["bool_groups"].get(group, []):
                out[key] = dict(label=text, group=group, kind="bool", default=bool(brush["settings"].get(key, False)))
        _FIELDS_CACHE = out
    return _FIELDS_CACHE


def field_label(key):
    f = engine_fields().get(key)
    return f"{f['label']} ({key})" if f else key


def apply_curve(x, curve):
    x = max(0.0, min(1.0, x))
    if curve.startswith("douce"):
        return x * x
    if curve.startswith("forte"):
        return math.sqrt(x)
    if curve == "en S":
        return x * x * (3 - 2 * x)
    if curve == "inversée":
        return 1.0 - x
    return x


def label(text, color=None, size=None, bold=False, wrap=False):
    w = QLabel(text)
    css = []
    if color:
        css.append(f"color:{color};")
    if size:
        css.append(f"font-size:{size}px;")
    if bold:
        css.append("font-weight:700;")
    w.setStyleSheet("".join(css))
    w.setWordWrap(wrap)
    return w


class SectionTitle(QLabel):
    def __init__(self, text):
        super().__init__(text.upper())
        self.setStyleSheet(f"color:{C['muted']}; font-size:10px; font-weight:700; letter-spacing:1px; padding:10px 0 4px;")


# ─── Paramètres moteur ─────────────────────────────────────────────────────
class CapabilityEditor(QFrame):
    """Éditeur des paramètres internes du moteur, construit depuis le schéma réel."""
    changed = Signal()
    link_requested = Signal(str, str)   # (clé, "fixed" | "pressure" | "velocity" | "tilt" | "random")

    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        self.creator_id = creator_id
        self.schema = creative_core_capabilities()
        self.values: dict = {}
        self.controls: dict = {}
        self.rows: dict = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        if creator_id == "blend":
            self._build_blend(root)
        else:
            self._build_brush(root)

    def _build_brush(self, root):
        brush = self.schema["brush"]
        root.addWidget(label(brush.get("backend", ""), C["ok"] if self.schema["available"] else C["warn"], 11, wrap=True))
        root.addWidget(label("Valeurs de base du moteur. ◆ = modifié par le graphe. Clic droit sur un paramètre pour le piloter depuis le graphe.",
                             C["muted"], 10, wrap=True))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer les paramètres…")
        self.filter.textChanged.connect(self._apply_filter)
        root.addWidget(self.filter)
        box = QToolBox()
        for group, fields in brush["float_groups"].items():
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(4, 4, 4, 4)
            for key, text, minimum, maximum, step in fields:
                control = QDoubleSpinBox()
                control.setRange(float(minimum), float(maximum))
                control.setSingleStep(float(step))
                control.setDecimals(2 if float(step) >= 0.01 else 3)
                control.setValue(float(brush["settings"].get(key, minimum)))
                control.valueChanged.connect(lambda v, k=key: self._set(k, v))
                self._register(form, key, text, control, control.value())
            for key, text in brush["bool_groups"].get(group, []):
                control = QCheckBox()
                control.setChecked(bool(brush["settings"].get(key, False)))
                control.toggled.connect(lambda v, k=key: self._set(k, v))
                self._register(form, key, text, control, control.isChecked())
            box.addItem(page, group)
        root.addWidget(box, 1)
        for key, value in brush["settings"].items():
            self.values.setdefault(key, value)

    def _register(self, form, key, text, control, value):
        lab = QLabel(text)
        lab.setToolTip(f"{key}\nClic droit : piloter depuis le graphe")
        lab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lab.customContextMenuRequested.connect(lambda pos, k=key, l=lab: self._link_menu(k, l.mapToGlobal(pos)))
        control.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        control.customContextMenuRequested.connect(lambda pos, k=key, c=control: self._link_menu(k, c.mapToGlobal(pos)))
        form.addRow(lab, control)
        self.controls[key] = control
        self.rows[key] = (lab, control, text)
        self.values[key] = value

    def _build_blend(self, root):
        blend = self.schema.get("blend") or {}
        form = QFormLayout()
        mode = QComboBox()
        mode.addItems(blend.get("blend_modes") or BLEND_MODES)
        mode.currentTextChanged.connect(lambda v: self._set("mode", v))
        channel = QComboBox()
        channel.addItems(blend.get("channels") or ["RGB"])
        channel.currentTextChanged.connect(lambda v: self._set("channel", v))
        form.addRow("Mode par défaut", mode)
        form.addRow("Canal", channel)
        self.controls = {"mode": mode, "channel": channel}
        self.values = {"mode": mode.currentText(), "channel": channel.currentText()}
        root.addLayout(form)
        root.addStretch()

    def _set(self, key, value):
        self.values[key] = value
        self.changed.emit()

    def _link_menu(self, key, global_pos):
        menu = QMenu(self)
        menu.addSection(field_label(key))
        acts = {menu.addAction("Fixer via un nœud Paramètre moteur"): "fixed"}
        if engine_fields().get(key, {}).get("kind") == "float":
            menu.addSeparator()
            for src, text in (("pressure", "pression"), ("velocity", "vitesse"), ("tilt", "inclinaison"), ("random", "aléatoire")):
                acts[menu.addAction(f"Piloter par la {text}")] = src
        chosen = menu.exec(global_pos)
        if chosen in acts:
            self.link_requested.emit(key, acts[chosen])

    def mark_driven(self, driven: dict):
        """Signale dans l'onglet les paramètres pris en charge par le graphe."""
        for key, (lab, control, text) in self.rows.items():
            who = driven.get(key)
            if who:
                lab.setText(f"◆ {text}")
                lab.setStyleSheet(f"color:{C['warn']}; font-weight:700;")
                lab.setToolTip(f"{key}\nPiloté par le graphe :\n• " + "\n• ".join(who))
            else:
                lab.setText(text)
                lab.setStyleSheet("")
                lab.setToolTip(f"{key}\nClic droit : piloter depuis le graphe")

    def _apply_filter(self, text):
        text = text.casefold().strip()
        for key, (lab, control, name) in self.rows.items():
            visible = not text or text in name.casefold() or text in key.casefold()
            lab.setVisible(visible)
            control.setVisible(visible)

    def load(self, values: dict):
        for key, value in (values or {}).items():
            control = self.controls.get(key)
            if control is None:
                continue
            control.blockSignals(True)
            try:
                if isinstance(control, QDoubleSpinBox):
                    control.setValue(float(value))
                elif isinstance(control, QCheckBox):
                    control.setChecked(bool(value))
                elif isinstance(control, QComboBox):
                    control.setCurrentText(str(value))
                self.values[key] = value
            except (TypeError, ValueError):
                pass
            finally:
                control.blockSignals(False)

    def snapshot(self) -> dict:
        return dict(self.values)


# ─── Graphe : items ─────────────────────────────────────────────────────────
NODE_W, NODE_H = 196, 76


class PortItem(QGraphicsEllipseItem):
    def __init__(self, node, kind):
        super().__init__(-7, -7, 14, 14, node)
        self.node, self.kind = node, kind  # kind: "in" | "out"
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._style(False)
        self.setPos(NODE_W if kind == "out" else 0, NODE_H / 2)
        self.setToolTip("Glisse vers l'entrée d'un autre nœud" if kind == "out" else "Entrée")

    def _style(self, hot):
        self.setBrush(QBrush(QColor(self.node.color if hot else C["bg"])))
        self.setPen(QPen(QColor(self.node.color), 2))

    def hoverEnterEvent(self, e):
        self._style(True)
        self.setScale(1.3)

    def hoverLeaveEvent(self, e):
        self._style(False)
        self.setScale(1.0)


class NodeItem(QGraphicsRectItem):
    def __init__(self, node_id, node_type, title=None, config=None, x=0.0, y=0.0):
        super().__init__(0, 0, NODE_W, NODE_H)
        spec = NODE_TYPES.get(node_type, NODE_TYPES["Condition"])
        self.node_id, self.node_type, self.spec = node_id, node_type, spec
        self.title = title or spec["label"]
        self.color = spec["color"]
        self.config = {p[0]: p[3] for p in spec["params"]}
        self.config.update(config or {})
        self.edges: list = []
        self.issue = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.in_port = PortItem(self, "in") if spec["ins"] else None
        self.out_port = PortItem(self, "out") if spec["outs"] else None
        self.setPos(x, y)
        self.setToolTip(spec["help"])

    @property
    def subtitle(self):
        parts = []
        for key, text, kind, _d, _e in self.spec["params"][:2]:
            value = self.config.get(key)
            if kind == "engine_key":
                parts.append(engine_fields().get(value, {}).get("label", str(value)))
                continue
            if kind == "engine_value":
                value = f"{value:g}" if isinstance(value, float) else value
                parts.append(f"= {value}")
                continue
            if kind == "number":
                value = f"{float(value):g}"
            elif kind == "bool":
                value = "oui" if value else "non"
            parts.append(f"{text.lower()} {value}")
        return " · ".join(parts)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.edges:
                edge.update_path()
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        sel = self.isSelected()
        painter.setPen(QPen(QColor("#FFFFFF" if sel else self.color), 2.4 if sel else 1.6))
        painter.setBrush(QColor("#1A2748" if sel else "#152039"))
        painter.drawRoundedRect(r, 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.color))
        painter.drawRoundedRect(QRectF(10, 14, 4, NODE_H - 28), 2, 2)
        painter.setPen(QColor("#F4F7FF"))
        painter.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        painter.drawText(QRectF(24, 10, NODE_W - 34, 22), Qt.AlignmentFlag.AlignVCenter, self.title)
        painter.setPen(QColor(self.color))
        painter.setFont(QFont("Inter", 7, QFont.Weight.Bold))
        painter.drawText(QRectF(24, 30, NODE_W - 34, 14), Qt.AlignmentFlag.AlignVCenter, self.node_type.upper())
        painter.setPen(QColor("#94A6C9"))
        painter.setFont(QFont("Inter", 8))
        text = painter.fontMetrics().elidedText(self.subtitle, Qt.TextElideMode.ElideRight, NODE_W - 34)
        painter.drawText(QRectF(24, 46, NODE_W - 34, 18), Qt.AlignmentFlag.AlignVCenter, text)
        if self.issue:
            painter.setBrush(QColor(C["err"] if self.issue[0] == "error" else C["warn"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(NODE_W - 12, 12), 5, 5)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, source: NodeItem, target: NodeItem):
        super().__init__()
        self.source, self.target = source, target
        self._hover = False
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setToolTip("Clic pour sélectionner · Suppr pour retirer la liaison")
        self._hover = False
        source.edges.append(self)
        target.edges.append(self)
        self.update_path()

    def update_path(self):
        a = self.source.pos() + QPointF(NODE_W, NODE_H / 2)
        b = self.target.pos() + QPointF(0, NODE_H / 2)
        self.setPath(bezier(a, b))
        self._restyle()

    def _restyle(self):
        hot = self.isSelected() or self._hover
        color = QColor(C["err"] if self.isSelected() else (self.source.color if hot else "#4A5E8C"))
        self.setPen(QPen(color, 3.2 if hot else 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

    def shape(self):
        s = QPainterPathStroker()
        s.setWidth(14)
        return s.createStroke(self.path())

    def hoverEnterEvent(self, e):
        self._hover = True
        self._restyle()

    def hoverLeaveEvent(self, e):
        self._hover = False
        self._restyle()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            QTimer.singleShot(0, self._restyle)
        return super().itemChange(change, value)

    def detach(self):
        for n in (self.source, self.target):
            if self in n.edges:
                n.edges.remove(self)


def bezier(a: QPointF, b: QPointF) -> QPainterPath:
    path = QPainterPath(a)
    dx = max(60.0, abs(b.x() - a.x()) * 0.5)
    path.cubicTo(a + QPointF(dx, 0), b - QPointF(dx, 0), b)
    return path


# ─── Graphe : vue ───────────────────────────────────────────────────────────
class GraphView(QGraphicsView):
    node_selected = Signal(object)      # NodeItem | None
    graph_changed = Signal(object)      # model
    interaction_message = Signal(str)
    history_changed = Signal()

    def __init__(self, creator_id="brush_engine", core=None):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(-4000, -4000, 8000, 8000)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self.setStyleSheet(f"border:1px solid {C['line']}; border-radius:10px; background:{C['bg']};")
        self.creator_id = creator_id
        self.core = core
        self.nodes: list[NodeItem] = []
        self.node_by_id: dict[str, NodeItem] = {}
        self.edge_items: list[EdgeItem] = []
        self._drag_port = None
        self._temp = None
        self._panning = None
        self._press_positions = {}
        self._param_key = None
        self.undo_stack: list[str] = []
        self.redo_stack: list[str] = []
        self.scene().selectionChanged.connect(self.emit_selected_node)
        self.centerOn(300, 200)

    # compat : anciennes API
    @property
    def edges(self):
        return [(e.source.node_id, e.target.node_id) for e in self.edge_items]

    def emit_selected_node(self):
        try:
            sel = [i for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        except RuntimeError:
            return
        self.node_selected.emit(sel[0] if len(sel) == 1 else None)

    # ── core natif ──
    def _core(self, command, **payload):
        if self.core is None:
            return {"ok": True, "result": True}
        try:
            return self.core.command(command, **payload)
        except Exception as exc:  # noqa: BLE001 — le moteur a planté : on passe en secours
            self.core = None
            self.interaction_message.emit(f"StellarDustCore arrêté ({exc}) · mode de secours")
            return {"ok": True, "result": True}

    def resync_core(self):
        if self.core is None:
            return
        self._core("reset", creator=self.creator_id)
        for n in self.nodes:
            self._core("add_node", id=n.node_id, type=n.node_type)
            for k, v in n.config.items():
                self._core("set_parameter", key=f"node.{n.node_id}.{k}", value=str(v))
        for e in self.edge_items:
            self._core("connect", **{"from": e.source.node_id, "to": e.target.node_id})

    # ── modèle ──
    def model(self):
        nodes = [{"id": n.node_id, "type": n.node_type, "title": n.title, "config": dict(n.config),
                  "x": round(n.pos().x(), 1), "y": round(n.pos().y(), 1)} for n in self.nodes]
        return nodes, self.edges

    def rebuild(self, model=None):
        """Reconstruit la scène depuis un modèle (tolère les anciens formats incomplets)."""
        self.scene().clearSelection()
        self.scene().clear()
        self.nodes, self.node_by_id, self.edge_items = [], {}, []
        nodes, edges = model if model is not None else ([], [])
        for i, data in enumerate(nodes or []):
            if not isinstance(data, dict) or not data.get("id"):
                continue
            ntype = data.get("type") if data.get("type") in NODE_TYPES else "Condition"
            node = NodeItem(str(data["id"]), ntype, data.get("title"), data.get("config") or {},
                            float(data.get("x", 80 + (i % 4) * 240)), float(data.get("y", 80 + (i // 4) * 120)))
            if node.node_id in self.node_by_id:
                continue
            self.scene().addItem(node)
            self.nodes.append(node)
            self.node_by_id[node.node_id] = node
        for edge in edges or []:
            a, b = (edge.get("from"), edge.get("to")) if isinstance(edge, dict) else tuple(edge)[:2]
            s, t = self.node_by_id.get(a), self.node_by_id.get(b)
            if s and t and s.out_port and t.in_port and (a, b) not in self.edges:
                self._add_edge_item(s, t)
        self.resync_core()

    def _add_edge_item(self, s, t):
        e = EdgeItem(s, t)
        self.scene().addItem(e)
        self.edge_items.append(e)
        return e

    def _changed(self):
        self.graph_changed.emit(self.model())

    # ── historique ──
    def push_undo(self):
        self.undo_stack.append(json.dumps(self.model()))
        del self.undo_stack[:-80]
        self.redo_stack.clear()
        self.history_changed.emit()

    def _restore_json(self, blob):
        nodes, edges = json.loads(blob)
        self.rebuild((nodes, [tuple(e) for e in edges]))
        self._changed()

    def undo(self):
        if not self.undo_stack:
            self.interaction_message.emit("Rien à annuler")
            return
        self.redo_stack.append(json.dumps(self.model()))
        self._restore_json(self.undo_stack.pop())
        self._param_key = None
        self.history_changed.emit()
        self.interaction_message.emit("Annulé")

    def redo(self):
        if not self.redo_stack:
            self.interaction_message.emit("Rien à rétablir")
            return
        self.undo_stack.append(json.dumps(self.model()))
        self._restore_json(self.redo_stack.pop())
        self.history_changed.emit()
        self.interaction_message.emit("Rétabli")

    # ── opérations ──
    def _new_id(self, node_type):
        base, index = node_type.lower(), 1
        node_id = base
        while node_id in self.node_by_id:
            index += 1
            node_id = f"{base}_{index}"
        return node_id

    def add_node(self, node_type, pos: QPointF | None = None, config=None):
        if node_type not in NODE_TYPES:
            return None
        node_id = self._new_id(node_type)
        if not self._core("add_node", id=node_id, type=node_type).get("ok"):
            return None
        self.push_undo()
        if pos is None:
            pos = self.mapToScene(self.viewport().rect().center()) - QPointF(NODE_W / 2, NODE_H / 2)
            while any((n.pos() - pos).manhattanLength() < 30 for n in self.nodes):
                pos += QPointF(24, 24)
        node = NodeItem(node_id, node_type, None, config, pos.x(), pos.y())
        for k, v in node.config.items():
            self._core("set_parameter", key=f"node.{node_id}.{k}", value=str(v))
        self.scene().addItem(node)
        self.nodes.append(node)
        self.node_by_id[node_id] = node
        self.scene().clearSelection()
        node.setSelected(True)
        self._changed()
        return node

    def _reaches(self, start, goal):
        stack, seen = [start], set()
        while stack:
            cur = stack.pop()
            if cur == goal:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(t for s, t in self.edges if s == cur)
        return False

    def connect_pair(self, source, target):
        if source is target or not source.out_port or not target.in_port:
            self.interaction_message.emit("Liaison impossible : relie une sortie (●→) à une entrée (→●)")
            return False
        if (source.node_id, target.node_id) in self.edges:
            self.interaction_message.emit("Ces nœuds sont déjà reliés")
            return False
        if self._reaches(target.node_id, source.node_id):
            self.interaction_message.emit("Liaison refusée : elle créerait une boucle")
            return False
        if not self._core("connect", **{"from": source.node_id, "to": target.node_id}).get("ok"):
            self.interaction_message.emit("StellarDustCore a refusé la liaison")
            return False
        self.push_undo()
        self._add_edge_item(source, target)
        self.interaction_message.emit(f"Relié : {source.title} → {target.title}")
        self._changed()
        return True

    def set_node_parameter(self, node, key, value):
        if node is None or node.node_id not in self.node_by_id:
            return False
        if self._param_key != (node.node_id, key):
            self.push_undo()
            self._param_key = (node.node_id, key)
        node.config[key] = value
        self._core("set_parameter", key=f"node.{node.node_id}.{key}", value=str(value))
        node.update()
        self._changed()
        return True

    def rename_node(self, node, title):
        title = title.strip() or node.spec["label"]
        if title != node.title:
            self.push_undo()
            node.title = title
            node.update()
            self._changed()

    def delete_selected(self):
        items = self.scene().selectedItems()
        nodes = [i for i in items if isinstance(i, NodeItem)]
        edges = [i for i in items if isinstance(i, EdgeItem)]
        if not nodes and not edges:
            return False
        self.push_undo()
        doomed = set(edges)
        for n in nodes:
            doomed.update(n.edges)
        for e in doomed:
            e.detach()
            self.edge_items.remove(e)
            self.scene().removeItem(e)
        for n in nodes:
            self.nodes.remove(n)
            self.node_by_id.pop(n.node_id, None)
            self.scene().removeItem(n)
        self.resync_core()   # le CLI natif n'a pas de "disconnect" : on rejoue
        self.interaction_message.emit(f"Supprimé : {len(nodes)} nœud(s), {len(doomed)} liaison(s)")
        self._changed()
        return True

    def duplicate_selected(self):
        nodes = [i for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        for n in nodes:
            copy = self.add_node(n.node_type, n.pos() + QPointF(30, 30), dict(n.config))
            if copy:
                copy.title = n.title
        return bool(nodes)

    def connect_selected(self):
        sel = [i for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        return len(sel) == 2 and self.connect_pair(sel[0], sel[1])

    def auto_layout(self):
        if not self.nodes:
            return
        self.push_undo()
        depth = {}

        def d(nid, guard=0):
            if nid in depth:
                return depth[nid]
            parents = [s for s, t in self.edges if t == nid]
            depth[nid] = 0 if not parents or guard > 50 else 1 + max(d(p, guard + 1) for p in parents)
            return depth[nid]
        for n in self.nodes:
            d(n.node_id)
        rows = {}
        for n in sorted(self.nodes, key=lambda n: (depth[n.node_id], n.pos().y())):
            col = depth[n.node_id]
            n.setPos(col * 270, rows.get(col, 0) * 110)
            rows[col] = rows.get(col, 0) + 1
        self.fit()
        self._changed()

    def fit(self):
        if not self.nodes:
            self.resetTransform()
            self.centerOn(300, 200)
            return
        rect = self.scene().itemsBoundingRect().adjusted(-80, -80, 80, 80)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1.2:
            self.resetTransform()
            self.scale(1.2, 1.2)
            self.centerOn(rect.center())

    def zoom(self, factor):
        s = self.transform().m11() * factor
        if 0.25 <= s <= 2.5:
            self.scale(factor, factor)

    def select_node(self, node_id):
        node = self.node_by_id.get(node_id)
        if node:
            self.scene().clearSelection()
            node.setSelected(True)
            self.centerOn(node)

    def mark_issues(self, issues):
        for n in self.nodes:
            n.issue = None
        for level, _text, nid in issues:
            node = self.node_by_id.get(nid)
            if node and (node.issue is None or level == "error"):
                node.issue = (level, _text)
        for n in self.nodes:
            n.setToolTip(n.spec["help"] + (f"\n⚠ {n.issue[1]}" if n.issue else ""))
            n.update()

    # ── rendu ──
    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(C["bg"]))
        step = 32
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        painter.setPen(QPen(QColor("#111D36"), 1))
        for x in range(left, int(rect.right()) + step, step):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()) + step, step):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)

    def drawForeground(self, painter, rect):
        if self.nodes:
            return
        painter.save()
        painter.resetTransform()
        vr = QRectF(self.viewport().rect())
        painter.setPen(QColor("#AAB9D6"))
        painter.setFont(QFont("Inter", 15, QFont.Weight.Bold))
        painter.drawText(vr.adjusted(0, -40, 0, -40), Qt.AlignmentFlag.AlignCenter, "Atelier vide")
        painter.setPen(QColor(C["muted"]))
        painter.setFont(QFont("Inter", 10))
        painter.drawText(vr.adjusted(0, 10, 0, 10), Qt.AlignmentFlag.AlignCenter,
                         "Glisse un composant depuis la palette, fais un clic droit ici,\n"
                         "ou utilise « Modèle de départ » pour un graphe prêt à l'emploi.")
        painter.restore()

    # ── interactions ──
    def wheelEvent(self, event):
        self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)

    def _port_at(self, pos):
        for item in self.items(pos):
            if isinstance(item, PortItem):
                return item
        return None

    def _node_at(self, pos):
        for item in self.items(pos):
            if isinstance(item, NodeItem):
                return item
            if isinstance(item, PortItem):
                return item.node
        return None

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self._panning = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            port = self._port_at(pos)
            if port is not None:
                if port.kind == "in":   # tirer depuis une entrée = détacher la liaison existante
                    existing = [e for e in port.node.edges if e.target is port.node]
                    if existing:
                        edge = existing[-1]
                        src = edge.source
                        self.push_undo()
                        edge.detach()
                        self.edge_items.remove(edge)
                        self.scene().removeItem(edge)
                        self.resync_core()
                        self._changed()
                        self.undo_stack.pop()  # le re-branchement sera une seule étape
                        self.undo_stack.append(json.dumps(self._last_model_with(src, port.node)))
                        port = src.out_port
                    else:
                        return
                self._drag_port = port
                self._temp = QGraphicsPathItem()
                self._temp.setPen(QPen(QColor(port.node.color), 2, Qt.PenStyle.DashLine))
                self._temp.setZValue(10)
                self.scene().addItem(self._temp)
                self._update_temp(self.mapToScene(pos))
                return
            self._press_positions = {n.node_id: QPointF(n.pos()) for n in self.nodes}
        super().mousePressEvent(event)

    def _last_model_with(self, src, tgt):
        nodes, edges = self.model()
        return nodes, edges + [(src.node_id, tgt.node_id)]

    def _update_temp(self, scene_pos):
        a = self._drag_port.node.pos() + QPointF(NODE_W, NODE_H / 2)
        self._temp.setPath(bezier(a, scene_pos))

    def mouseMoveEvent(self, event):
        if self._panning is not None:
            delta = event.position() - self._panning
            self._panning = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return
        if self._temp is not None:
            self._update_temp(self.mapToScene(event.position().toPoint()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning is not None:
            self._panning = None
            self.unsetCursor()
            return
        if self._temp is not None:
            source = self._drag_port.node
            self.scene().removeItem(self._temp)
            self._temp, self._drag_port = None, None
            target = self._node_at(event.position().toPoint())
            if target is not None and target is not source:
                self.connect_pair(source, target)
            elif target is None:
                self._quick_add_menu(event.position().toPoint(), source)
            return
        super().mouseReleaseEvent(event)
        moved = any(n.node_id in self._press_positions and (n.pos() - self._press_positions[n.node_id]).manhattanLength() > 2
                    for n in self.nodes)
        if moved:
            before = self._press_positions
            nodes, edges = self.model()
            for data in nodes:
                if data["id"] in before:
                    data["x"], data["y"] = before[data["id"]].x(), before[data["id"]].y()
            self.undo_stack.append(json.dumps((nodes, edges)))
            self.redo_stack.clear()
            self.history_changed.emit()
            self._changed()
        self._press_positions = {}

    def _quick_add_menu(self, view_pos, connect_from=None):
        menu = QMenu(self)
        scene_pos = self.mapToScene(view_pos)
        for t in PALETTE.get(self.creator_id, PALETTE["brush_engine"]):
            spec = NODE_TYPES[t]
            if connect_from is not None and not spec["ins"]:
                continue
            act = menu.addAction(f"{spec['label']}  ·  {spec['category']}")
            act.setData(t)
        if connect_from is None and self.nodes:
            menu.addSeparator()
            menu.addAction("Organiser le graphe").setData("__layout")
            menu.addAction("Tout afficher (F)").setData("__fit")
        chosen = menu.exec(self.mapToGlobal(view_pos))
        if not chosen:
            return
        key = chosen.data()
        if key == "__layout":
            self.auto_layout()
        elif key == "__fit":
            self.fit()
        else:
            node = self.add_node(key, scene_pos - QPointF(0 if connect_from else NODE_W / 2, NODE_H / 2))
            if node and connect_from is not None:
                self.connect_pair(connect_from, node)

    def contextMenuEvent(self, event):
        node = self._node_at(event.pos())
        if node is None:
            for item in self.items(event.pos()):
                if isinstance(item, EdgeItem):
                    self.scene().clearSelection()
                    item.setSelected(True)
                    menu = QMenu(self)
                    if menu.addAction("Supprimer la liaison") == menu.exec(event.globalPos()):
                        self.delete_selected()
                    return
            self._quick_add_menu(event.pos())
            return
        if not node.isSelected():
            self.scene().clearSelection()
            node.setSelected(True)
        menu = QMenu(self)
        dup = menu.addAction("Dupliquer  (Ctrl+D)")
        dele = menu.addAction("Supprimer  (Suppr)")
        chosen = menu.exec(event.globalPos())
        if chosen == dup:
            self.duplicate_selected()
        elif chosen == dele:
            self.delete_selected()

    def mouseDoubleClickEvent(self, event):
        if self._node_at(event.position().toPoint()) is None:
            self._quick_add_menu(event.position().toPoint())
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            return
        if event.key() == Qt.Key.Key_F:
            self.fit()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_NODE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_NODE):
            event.acceptProposedAction()

    def dropEvent(self, event):
        t = bytes(event.mimeData().data(MIME_NODE)).decode()
        pos = self.mapToScene(event.position().toPoint()) - QPointF(NODE_W / 2, NODE_H / 2)
        self.add_node(t, pos)
        event.acceptProposedAction()

    # ── compat Existence ──
    def native_snapshot(self):
        nodes, edges = self.model()
        snap = {"format": "StellarDustGraph", "version": 2, "creator": self.creator_id,
                "nodes": nodes, "connections": [{"from": a, "to": b} for a, b in edges]}
        if self.core is not None:
            response = self._core("snapshot")
            if response.get("ok") and isinstance(response.get("result"), dict):
                snap["native"] = response["result"]
        return snap

    def native_validate(self):
        return self._core("validate") if self.core is not None else {"ok": True, "result": []}


# ─── Analyse du graphe ─────────────────────────────────────────────────────
def active_nodes(model):
    """Nœuds qui alimentent une sortie (ou tous si aucune sortie)."""
    nodes, edges = model
    outs = [n["id"] for n in nodes if n["type"] == "Output"]
    if not outs:
        return nodes, False
    parents = {}
    for a, b in edges:
        parents.setdefault(b, []).append(a)
    keep, stack = set(), list(outs)
    while stack:
        cur = stack.pop()
        if cur in keep:
            continue
        keep.add(cur)
        stack.extend(parents.get(cur, []))
    return [n for n in nodes if n["id"] in keep], True


def upstream_sources(node_id, model):
    """Entrées (configs) et condition en amont d'un nœud."""
    nodes, edges = model
    by_id = {n["id"]: n for n in nodes}
    parents = {}
    for a, b in edges:
        parents.setdefault(b, []).append(a)
    found, stack, seen = [], list(parents.get(node_id, [])), set()
    condition = None
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id:
            continue
        seen.add(cur)
        n = by_id[cur]
        cfg = n.get("config") or {}
        if n["type"] == "Input":
            found.append({"source": cfg.get("source", "pressure"), "gain": float(cfg.get("gain", 1.0)),
                          "curve": cfg.get("curve", "linéaire"), "min": float(cfg.get("min", 0.0)),
                          "max": float(cfg.get("max", 1.0))})
        if n["type"] == "Condition" and condition is None:
            condition = {"threshold": float(cfg.get("threshold", 0.5)),
                         "below": cfg.get("direction") == "en-dessous", "soft": float(cfg.get("soft", 0.0))}
        stack.extend(parents.get(cur, []))
    return found, condition


def effective_settings(engine: dict, model) -> dict:
    """Combine les paramètres moteur et le graphe → réglages de rendu."""
    s = dict(engine)
    s.setdefault("size", 12.0)
    s["dynamics"] = []
    s["composition"] = "normal"
    s["mask"] = 1.0
    driven = {}
    fields = engine_fields()
    nodes, has_output = active_nodes(model)
    for n in nodes:
        cfg = n.get("config") or {}
        t = n["type"]
        title = n.get("title") or t
        if t == "EngineParam" and cfg.get("key"):
            key = cfg["key"]
            value = cfg.get("value")
            f = fields.get(key, {})
            s[key] = bool(value) if f.get("kind") == "bool" else float(value or 0.0)
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
            sources, condition = upstream_sources(n["id"], model)
            key = cfg.get("target", "size")
            s["dynamics"].append({"target": key, "mode": cfg.get("mode", "multiplier"),
                                  "min": float(cfg.get("min", 0.1)), "max": float(cfg.get("max", 1.0)),
                                  "curve": cfg.get("curve", "linéaire"), "amount": float(cfg.get("amount", 1.0)),
                                  "invert": bool(cfg.get("invert", False)),
                                  "sources": sources or [{"source": "pressure", "gain": 1.0, "curve": "linéaire", "min": 0.0, "max": 1.0}],
                                  "condition": condition})
            names = "+".join(src["source"] for src in sources) or "pression"
            driven.setdefault(key, []).append(f"{title} (← {names})")
        elif t == "Blend":
            s["composition"] = cfg.get("mode", "normal")
            s["mask"] *= float(cfg.get("contribution", 1.0))
        elif t == "Mask":
            s["mask"] *= float(cfg.get("amount", 1.0))
    s["has_output"] = has_output
    s["driven"] = driven
    return s


def signal_value(src, raw):
    x = max(0.0, min(1.0, raw * src.get("gain", 1.0)))
    x = apply_curve(x, src.get("curve", "linéaire"))
    return src.get("min", 0.0) + (src.get("max", 1.0) - src.get("min", 0.0)) * x


def apply_dynamics(p: dict, raw_signals: dict) -> dict:
    """Applique chaque Dynamique au dictionnaire de réglages p (copie modifiée)."""
    fields = engine_fields()
    for dyn in p.get("dynamics", []):
        vals = [signal_value(src, raw_signals.get(src["source"], raw_signals.get("pressure", 1.0))) for src in dyn["sources"]]
        sig = sum(vals) / len(vals)
        cond = dyn.get("condition")
        if cond:
            t, soft = cond["threshold"], max(1e-6, cond["soft"])
            gate = max(0.0, min(1.0, (sig - t) / soft + 0.5)) if cond["soft"] > 0 else float(sig >= t)
            sig *= (1.0 - gate) if cond["below"] else gate
        if dyn["invert"]:
            sig = 1.0 - sig
        k = apply_curve(sig, dyn["curve"])
        level = dyn["min"] + (dyn["max"] - dyn["min"]) * k
        key = dyn["target"]
        f = fields.get(key, {})
        base = p.get(key, f.get("default", 0.0))
        if isinstance(base, bool) or f.get("kind") == "bool":
            p[key] = level >= 0.5
            continue
        base = float(base or 0.0)
        if dyn["mode"] == "ajouter":
            span = (f.get("hi", 1.0) - f.get("lo", 0.0)) if f else 1.0
            target = base + level * span
        elif dyn["mode"] == "remplacer":
            lo, hi = (f.get("lo", 0.0), f.get("hi", 1.0)) if f else (0.0, 1.0)
            target = lo + (hi - lo) * min(1.0, level)
        else:
            target = base * level
        value = base + (target - base) * dyn["amount"]
        if f:
            value = max(f["lo"], min(f["hi"], value)) if key not in ("angle",) else value
        p[key] = value
    return p


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
    for n in nodes:
        if n["id"] not in linked and len(nodes) > 1:
            issues.append(("warning", f"« {n.get('title', n['id'])} » n'est relié à rien", n["id"]))
    active, _ = active_nodes(model)
    active_ids = {n["id"] for n in active}
    for n in nodes:
        if n["type"] == "Output":
            srcs, _ = upstream_sources(n["id"], model)
            if not srcs:
                issues.append(("error", f"« {n.get('title', n['id'])} » ne reçoit aucune Entrée", n["id"]))
        elif "Output" in types and n["id"] in linked and n["id"] not in active_ids:
            issues.append(("warning", f"« {n.get('title', n['id'])} » n'atteint aucune Sortie (ignoré)", n["id"]))
    return issues


# ─── Panneaux ───────────────────────────────────────────────────────────────
class Inspector(QFrame):
    """Propriétés du nœud sélectionné."""
    node_parameter_changed = Signal(object, str, object)
    node_renamed = Signal(object, str)

    def __init__(self, creator_id="brush_engine"):
        super().__init__()
        self.node = None
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(4, 4, 4, 4)
        self.body = QWidget()
        self.layout_.addWidget(self.body)
        self.layout_.addStretch()
        self.capability_editor = None  # compat : l'éditeur moteur vit dans son propre onglet
        self.show_node(None)

    def show_node(self, node):
        self.node = node
        self.body.deleteLater()
        self.body = QWidget()
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        self.layout_.insertWidget(0, self.body)
        if node is None:
            lay.addWidget(label("Aucun nœud sélectionné", "#C3D0EA", 14, True))
            lay.addWidget(label("Clique un nœud du graphe pour régler ses propriétés.\n\n"
                                "Astuces :\n• glisse du rond de droite d'un nœud vers un autre pour les relier\n"
                                "• relâche dans le vide pour créer un nœud déjà relié\n"
                                "• clic droit / double-clic : ajouter un nœud\n"
                                "• Suppr : supprimer · Ctrl+Z : annuler · F : tout afficher\n"
                                "• molette : zoom · clic milieu ou Alt+glisser : se déplacer",
                                C["muted"], 11, wrap=True))
            return
        spec = node.spec
        lay.addWidget(label(spec["label"].upper(), node.color, 10, True))
        name = QLineEdit(node.title)
        name.setStyleSheet("font-size:15px; font-weight:700; padding:8px;")
        name.editingFinished.connect(lambda: self.node_renamed.emit(node, name.text()))
        lay.addWidget(name)
        lay.addWidget(label(spec["help"], C["muted"], 11, wrap=True))
        form = QFormLayout()
        form.setContentsMargins(0, 10, 0, 0)
        fields = engine_fields()

        def number_row(key, value, lo, hi, step):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 1000)
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setDecimals(3 if step < 0.01 else 2)
            spin.setFixedWidth(82)
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = lo
            spin.setValue(value)
            span = (hi - lo) or 1.0
            slider.setValue(int((value - lo) / span * 1000))
            slider.valueChanged.connect(lambda v: spin.setValue(lo + span * v / 1000))
            spin.valueChanged.connect(lambda v: (slider.blockSignals(True), slider.setValue(int((v - lo) / span * 1000)), slider.blockSignals(False)))
            spin.valueChanged.connect(lambda v, k=key: self.node_parameter_changed.emit(node, k, round(v, 4)))
            h.addWidget(slider, 1)
            h.addWidget(spin)
            return row

        for key, text, kind, default, extra in spec["params"]:
            value = node.config.get(key, default)
            if kind == "number":
                form.addRow(text, number_row(key, value, *extra))
            elif kind == "choice":
                combo = QComboBox()
                combo.addItems(extra)
                combo.setCurrentText(str(value))
                combo.currentTextChanged.connect(lambda v, k=key: self.node_parameter_changed.emit(node, k, v))
                form.addRow(text, combo)
            elif kind == "engine_key":
                combo = QComboBox()
                combo.setMaxVisibleItems(20)
                group = None
                for fk, f in fields.items():
                    if extra == "float" and f["kind"] != "float":
                        continue
                    if f["group"] != group:
                        group = f["group"]
                        if combo.count():
                            combo.insertSeparator(combo.count())
                    combo.addItem(f"{f['group']} › {f['label']}", fk)
                idx = combo.findData(value)
                combo.setCurrentIndex(max(0, idx))
                combo.setToolTip("Tous les paramètres de CreativeCore sont disponibles")

                def on_key(_i, c=combo, k=key):
                    new = c.currentData()
                    self.node_parameter_changed.emit(node, k, new)
                    if "value" in node.config and node.node_type == "EngineParam":
                        self.node_parameter_changed.emit(node, "value", fields.get(new, {}).get("default", 0.0))
                    QTimer.singleShot(0, lambda: self.show_node(node) if self.node is node else None)
                combo.currentIndexChanged.connect(on_key)
                form.addRow(text, combo)
            elif kind == "engine_value":
                f = fields.get(node.config.get("key"), {})
                if f.get("kind") == "bool":
                    check = QCheckBox("activé")
                    check.setChecked(bool(value))
                    check.toggled.connect(lambda v, k=key: self.node_parameter_changed.emit(node, k, v))
                    form.addRow(text, check)
                else:
                    form.addRow(text, number_row(key, value, f.get("lo", 0.0), f.get("hi", 1.0), f.get("step", 0.01)))
            else:
                check = QCheckBox()
                check.setChecked(bool(value))
                check.toggled.connect(lambda v, k=key: self.node_parameter_changed.emit(node, k, v))
                form.addRow(text, check)
        link = None
        if node.node_type == "Dynamics":
            f = fields.get(node.config.get("target"), {})
            link = (f"Pilote <b>{field_label(node.config.get('target'))}</b> · valeur moteur actuelle utilisée comme base"
                    f"<br>multiplier : base × (Min→Max) · ajouter : base + (Min→Max) × plage · remplacer : Min→Max de la plage"
                    + (f" [{f['lo']:g} – {f['hi']:g}]" if f.get("kind") == "float" else ""))
        elif node.node_type == "EngineParam":
            f = fields.get(node.config.get("key"), {})
            link = f"Remplace <b>{field_label(node.config.get('key'))}</b> (défaut moteur : {f.get('default', '?')})"
        if link:
            info = QLabel(link)
            info.setWordWrap(True)
            info.setStyleSheet(f"color:{C['warn']}; font-size:11px; background:#221D12; border-radius:6px; padding:7px;")
            lay.addWidget(info)
        lay.addLayout(form)
        reset = QPushButton("Réinitialiser les réglages")
        reset.setObjectName("secondary")

        def do_reset():
            for k, _t, _kind, d, _e in spec["params"]:
                self.node_parameter_changed.emit(node, k, d)
            self.show_node(node)
        reset.clicked.connect(do_reset)
        lay.addWidget(reset)
        ins = sum(1 for e in node.edges if e.target is node)
        outs = sum(1 for e in node.edges if e.source is node)
        lay.addWidget(label(f"{ins} entrée(s) · {outs} sortie(s) · id {node.node_id}", C["dim"], 10))
        if node.issue:
            lay.addWidget(label(f"⚠ {node.issue[1]}", C["err"] if node.issue[0] == "error" else C["warn"], 11, wrap=True))


@dataclass
class Resource:
    name: str
    kind: str
    status: str = "Brouillon"
    version: int = 1
    consumers: str = "Nebula"
    uri_override: str = ""

    @property
    def uri(self) -> str:
        if self.uri_override:
            return self.uri_override
        slug = "-".join(self.name.lower().split())
        return f"resource://existence/stardust/{self.kind}/{slug}"


class PaletteButton(QPushButton):
    """Bouton de palette : clic = ajouter au centre, glisser = déposer sur le graphe."""
    def __init__(self, node_type, on_click):
        spec = NODE_TYPES[node_type]
        super().__init__(f"  {spec['label']}")
        self.node_type = node_type
        self._press = None
        self.setObjectName("paletteButton")
        self.setStyleSheet(f"#paletteButton {{ border-left:3px solid {spec['color']}; }}")
        self.setToolTip(spec["help"] + "\nClic : ajouter · Glisser : déposer sur le graphe")
        self.clicked.connect(lambda: on_click(node_type))

    def mousePressEvent(self, e):
        self._press = e.position()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position() - self._press).manhattanLength() > 8:
            self._press = None
            self.setDown(False)
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(MIME_NODE, self.node_type.encode())
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(e)


class LivePreview(QFrame):
    """Surface de test : dessine réellement avec le moteur + le graphe."""

    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        self.creator_id = creator_id
        self.settings_provider = None
        self.image = QImage()
        self.color = QColor("#EAF0FF")
        self.background = QColor("#141E36")
        self.last = None
        self.distance_left = 0.0
        self.tablet_active = False
        self.simulate_pressure = True
        self.stroke_settings = None
        self.stroke = []   # compat
        self.samples = []  # compat
        self.setMinimumHeight(200)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking, True)

    def _ensure(self):
        if self.image.size() != self.size():
            new = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
            new.fill(Qt.GlobalColor.transparent)
            if not self.image.isNull():
                p = QPainter(new)
                p.drawImage(0, 0, self.image)
                p.end()
            self.image = new

    def resizeEvent(self, e):
        self._ensure()
        super().resizeEvent(e)

    def paintEvent(self, event):
        self._ensure()
        p = QPainter(self)
        p.fillRect(self.rect(), self.background)
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        for x in range(0, self.width(), 32):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32):
            p.drawLine(0, y, self.width(), y)
        p.drawImage(0, 0, self.image)
        if self.image.isNull() or not getattr(self, "_drew", False):
            p.setPen(QColor(C["muted"]))
            p.setFont(QFont("Inter", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Dessine ici pour tester ton moteur\n(stylet : pression et inclinaison réelles · souris : pression simulée par la vitesse)")
        p.end()

    def clear(self):
        self.image.fill(Qt.GlobalColor.transparent)
        self._drew = False
        self.update()

    def _settings(self):
        return self.settings_provider() if self.settings_provider else {"size": 12.0}

    def _begin(self, pos, pressure, tilt):
        self.stroke_settings = self._settings()
        self.last = (pos, pressure, tilt)
        self.distance_left = 0.0
        self._drew = True
        self._dab(pos, pressure, tilt, 0.0)

    def _dab_params(self, pressure, velocity, tilt):
        base = self.stroke_settings or {}
        v = min(1.0, velocity / 40.0)
        s = apply_dynamics(dict(base), {"pressure": pressure, "velocity": v, "tilt": tilt,
                                        "random": random.random(), "pointer": 1.0})
        self._current = s
        size = float(s.get("size", 12.0))
        opacity = float(s.get("opacity", 1.0)) * float(s.get("flow", 1.0))
        angle = float(s.get("angle", 0.0))
        spacing = float(s.get("spacing", 0.15))
        minimum = float(s.get("minimumSize", 0.05))
        if s.get("pressureSize", True):
            size *= max(minimum, pressure)
        if s.get("pressureOpacity"):
            opacity *= max(float(s.get("minimumOpacity", 0.0)), pressure)
        if s.get("pressureFlow"):
            opacity *= max(float(s.get("minimumFlow", 0.0)), pressure)
        size *= max(0.2, 1.0 - float(s.get("velocitySize", 0.0)) * v)
        opacity *= max(0.05, 1.0 - float(s.get("velocityOpacity", 0.0)) * v)
        opacity *= max(0.05, 1.0 - float(s.get("velocityFlow", 0.0)) * v)
        size *= max(0.2, 1.0 - float(s.get("tiltSize", 0.0)) * tilt)
        opacity *= max(0.05, 1.0 - float(s.get("tiltOpacity", 0.0)) * tilt)
        angle += float(s.get("tiltAngle", 0.0)) * tilt * 90.0
        spacing *= 1.0 + float(s.get("velocitySpacing", 0.0)) * v + float(s.get("pressureSpacing", 0.0)) * pressure
        jitter = float(s.get("sizeJitter", 0.0)) + float(s.get("randomSize", 0.0))
        if jitter:
            size *= 1.0 - random.random() * min(1.0, jitter)
        ro = float(s.get("randomOpacity", 0.0))
        if ro:
            opacity *= 1.0 - random.random() * ro
        angle += (random.random() - 0.5) * float(s.get("rotationJitter", 0.0))
        return max(0.5, size), max(0.0, min(1.0, opacity * s.get("mask", 1.0))), angle, max(0.01, spacing)

    def _dab(self, pos, pressure, tilt, velocity):
        size, opacity, angle, _sp = self._dab_params(pressure, velocity, tilt)
        s = self._current
        scatter = float(s.get("scatter", 0.0))
        if scatter:
            pos = pos + QPointF((random.random() - 0.5) * size * scatter * 2, (random.random() - 0.5) * size * scatter * 2)
        hardness = max(0.0, min(0.99, float(s.get("hardness", 0.8))))
        roundness = max(0.05, float(s.get("roundness", 1.0)))
        p = QPainter(self.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mode = {"multiply": QPainter.CompositionMode.CompositionMode_Multiply,
                "screen": QPainter.CompositionMode.CompositionMode_Screen,
                "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
                "darken": QPainter.CompositionMode.CompositionMode_Darken,
                "lighten": QPainter.CompositionMode.CompositionMode_Lighten}.get(s.get("composition"), QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setCompositionMode(mode)
        p.translate(pos)
        p.rotate(angle)
        p.scale(1.0, roundness)
        r = size / 2
        grad = QRadialGradient(QPointF(0, 0), r)
        c0 = QColor(self.color)
        c0.setAlphaF(opacity)
        c1 = QColor(self.color)
        c1.setAlphaF(0.0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(hardness, c0)
        grad.setColorAt(1.0, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(0, 0), r, r)
        p.end()

    def _to(self, pos, pressure, tilt):
        if self.last is None:
            return
        lp, lpr, lt = self.last
        dist = math.hypot(pos.x() - lp.x(), pos.y() - lp.y())
        if dist < 0.01:
            return
        velocity = dist
        size, _o, _a, spacing = self._dab_params(pressure, velocity, tilt)
        step = max(0.75, size * spacing)
        t = step - self.distance_left
        while t <= dist:
            f = t / dist
            self._dab(QPointF(lp.x() + (pos.x() - lp.x()) * f, lp.y() + (pos.y() - lp.y()) * f),
                      lpr + (pressure - lpr) * f, lt + (tilt - lt) * f, velocity)
            t += step
        self.distance_left = dist - (t - step)
        self.last = (pos, pressure, tilt)
        self.update()

    def _mouse_pressure(self, pos):
        if not self.simulate_pressure or self.last is None:
            return 0.8
        lp = self.last[0]
        speed = math.hypot(pos.x() - lp.x(), pos.y() - lp.y())
        target = max(0.15, min(1.0, 1.1 - speed / 30.0))
        return self.last[1] * 0.7 + target * 0.3

    def tabletEvent(self, e):
        self.tablet_active = True
        pos = e.position()
        tilt = min(1.0, math.hypot(e.xTilt(), e.yTilt()) / 60.0)
        t = e.type()
        if t == QEvent.Type.TabletPress:
            self._begin(pos, e.pressure(), tilt)
        elif t == QEvent.Type.TabletMove and self.last is not None and e.pressure() > 0:
            self._to(pos, e.pressure(), tilt)
        elif t == QEvent.Type.TabletRelease:
            self.last = None
            QTimer.singleShot(200, lambda: setattr(self, "tablet_active", False))
        e.accept()

    def mousePressEvent(self, e):
        if self.creator_id != "blend" and not self.tablet_active and e.button() == Qt.MouseButton.LeftButton:
            self._begin(e.position(), 0.5, 0.0)
            self.update()

    def mouseMoveEvent(self, e):
        if not self.tablet_active and self.last is not None:
            self._to(e.position(), self._mouse_pressure(e.position()), 0.0)

    def mouseReleaseEvent(self, e):
        if not self.tablet_active:
            self.last = None


class FusionTestBench(QFrame):
    """Surface de test spécialisée de Fusion Creator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_a = self._sample_image(QColor("#E85D9E"), QColor("#6D5BEA"))
        self.image_b = self._sample_image(QColor("#F7C65D"), QColor("#22B8CF"))
        self.result = QImage()
        self.contribution = 1.0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Mode"))
        self.mode = QComboBox()
        self.mode.addItems(BLEND_MODES)
        self.mode.currentTextChanged.connect(self.render_result)
        controls.addWidget(self.mode)
        for slot, text in (("a", "Charger l'image A…"), ("b", "Charger l'image B…")):
            b = QPushButton(text)
            b.setObjectName("secondary")
            b.clicked.connect(lambda _=False, s=slot: self._load_image(s))
            controls.addWidget(b)
        controls.addStretch()
        root.addLayout(controls)
        previews = QHBoxLayout()
        self.input_a = self._image_panel("IMAGE A (fond)")
        self.input_b = self._image_panel("IMAGE B (dessus)")
        self.output = self._image_panel("RÉSULTAT")
        for panel, _ in (self.input_a, self.input_b, self.output):
            previews.addWidget(panel, 1)
        root.addLayout(previews, 1)
        self.status = label("", C["ok"], 11)
        root.addWidget(self.status)
        self.render_result()

    @staticmethod
    def _sample_image(first, second):
        image = QImage(420, 260, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        gradient = QLinearGradient(0, 0, image.width(), image.height())
        gradient.setColorAt(0, first)
        gradient.setColorAt(1, second)
        painter.fillRect(image.rect(), gradient)
        painter.setBrush(QColor(255, 255, 255, 90))
        painter.drawEllipse(90, 50, 150, 150)
        painter.end()
        return image

    @staticmethod
    def _image_panel(title):
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.addWidget(label(title, "#AAB9D6", 10, True))
        image = QLabel()
        image.setMinimumSize(200, 140)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setStyleSheet(f"background:{C['bg']}; border:1px solid {C['line']}; border-radius:8px;")
        layout.addWidget(image, 1)
        return frame, image

    def _load_image(self, slot):
        path, _ = QFileDialog.getOpenFileName(self, "Charger une image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        image = QImage(path) if path else QImage()
        if image.isNull():
            return
        if slot == "a":
            self.image_a = image
        else:
            self.image_b = image
        self.render_result()

    def apply_graph(self, settings):
        self.contribution = float(settings.get("mask", 1.0))
        mode = settings.get("composition", "normal")
        if self.mode.findText(mode) >= 0:
            self.mode.setCurrentText(mode)
        self.render_result()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._show)

    def render_result(self):
        if self.image_a.isNull() or self.image_b.isNull():
            return
        result = self.image_a.convertToFormat(QImage.Format.Format_ARGB32)
        overlay = self.image_b.scaled(result.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
        mode = {
            "normal": QPainter.CompositionMode.CompositionMode_SourceOver,
            "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
            "screen": QPainter.CompositionMode.CompositionMode_Screen,
            "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
            "darken": QPainter.CompositionMode.CompositionMode_Darken,
            "lighten": QPainter.CompositionMode.CompositionMode_Lighten,
        }.get(self.mode.currentText(), QPainter.CompositionMode.CompositionMode_SourceOver)
        painter = QPainter(result)
        painter.setOpacity(self.contribution)
        painter.setCompositionMode(mode)
        painter.drawImage(0, 0, overlay)
        painter.end()
        self.result = result
        self._show()
        self.status.setText(f"Résultat · mode {self.mode.currentText()} · contribution {self.contribution:.0%} · {result.width()}×{result.height()}")

    def _show(self):
        for image, panel in ((self.image_a, self.input_a[1]), (self.image_b, self.input_b[1]), (self.result, self.output[1])):
            if not image.isNull():
                panel.setPixmap(QPixmap.fromImage(image).scaled(panel.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def validate(self) -> bool:
        return not self.result.isNull()

    def snapshot(self) -> dict:
        return {
            "mode": self.mode.currentText(),
            "input_a": {"width": self.image_a.width(), "height": self.image_a.height()},
            "input_b": {"width": self.image_b.width(), "height": self.image_b.height()},
            "result": {"width": self.result.width(), "height": self.result.height(), "valid": not self.result.isNull()},
        }


class DefinitionPanel(QFrame):
    changed = Signal()

    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        d = creator_def(creator_id)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Donne une identité à ton outil. Ces informations accompagnent la ressource publiée.", C["muted"], 12, wrap=True))
        layout.addWidget(SectionTitle("Nom"))
        self.name = QLineEdit("Nouveau mélange" if creator_id == "blend" else "Nouveau pinceau")
        self.name.setPlaceholderText("Nom de la ressource (obligatoire)")
        self.name.setStyleSheet("font-size:18px; padding:10px;")
        layout.addWidget(self.name)
        layout.addWidget(SectionTitle("Description"))
        self.description = QTextEdit()
        self.description.setPlaceholderText("Ce que produit l'outil, dans quel contexte l'utiliser…")
        self.description.setMaximumHeight(110)
        layout.addWidget(self.description)
        grid = QFormLayout()
        grid.setContentsMargins(0, 10, 0, 0)
        self.inputs = QLineEdit(", ".join(d.inputs))
        self.outputs = QLineEdit(d.output_kind)
        self.compatibility = QLineEdit("Nebula")
        self.consumers_hint = label("Séparer par des virgules", C["dim"], 10)
        grid.addRow("Entrées attendues", self.inputs)
        grid.addRow("Type produit", self.outputs)
        grid.addRow("Compatible avec", self.compatibility)
        layout.addLayout(grid)
        layout.addWidget(self.consumers_hint)
        layout.addStretch()
        for w in (self.name, self.inputs, self.outputs, self.compatibility):
            w.textChanged.connect(self.changed)
        self.description.textChanged.connect(self.changed)

    def load(self, data):
        if not isinstance(data, dict):
            return
        name = data.get("name")
        if name and name not in ("Untitled Brush Engine", "Blend Definition"):
            self.name.setText(name)
        self.description.setPlainText(data.get("description", ""))
        for key, w in (("inputs", self.inputs), ("outputs", self.outputs), ("compatibility", self.compatibility)):
            if data.get(key):
                w.setText(str(data[key]))

    def snapshot(self):
        return {"name": self.name.text().strip(), "description": self.description.toPlainText(), "inputs": self.inputs.text(),
                "outputs": self.outputs.text(), "compatibility": self.compatibility.text()}


class ParameterOrganizationPanel(QFrame):
    """Choix des paramètres exposés à l'utilisateur final (depuis le vrai schéma)."""
    changed = Signal()

    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Coche ce que l'utilisateur final pourra régler dans Nebula. Le reste reste interne au moteur "
                               "(réglable dans l'onglet « Moteur » à droite).", C["muted"], 12, wrap=True))
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer…")
        self.filter.textChanged.connect(self._filter)
        top.addWidget(self.filter, 1)
        self.count = label("", C["ok"], 11)
        top.addWidget(self.count)
        layout.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.col = QVBoxLayout(content)
        self.checks: dict[str, QCheckBox] = {}
        if creator_id == "blend":
            groups = {"Fusion": [("mode", "Mode de fusion"), ("channel", "Canal"), ("contribution", "Contribution"),
                                 ("mask", "Masque"), ("curve", "Courbe")]}
            default = {"mode", "contribution"}
        else:
            brush = creative_core_capabilities()["brush"]
            groups = {}
            for g, fields in brush["float_groups"].items():
                groups[g] = [(f[0], f[1]) for f in fields] + list(brush["bool_groups"].get(g, []))
            default = {"size", "opacity", "flow"}
        for g, fields in groups.items():
            self.col.addWidget(SectionTitle(g))
            for key, text in fields:
                check = QCheckBox(text)
                check.setChecked(key in default)
                check.toggled.connect(self._update)
                self.checks[key] = check
                self.col.addWidget(check)
        self.col.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self._update()

    def _filter(self, text):
        t = text.casefold()
        for key, c in self.checks.items():
            c.setVisible(not t or t in c.text().casefold() or t in key.casefold())

    def _update(self):
        self.count.setText(f"{len(self.snapshot())} exposé(s)")
        self.changed.emit()

    def load(self, keys):
        if not isinstance(keys, list):
            return
        legacy = {"Taille": "size", "Opacité": "opacity", "Flow": "flow", "Espacement": "spacing", "Mode de fusion": "mode"}
        wanted = {legacy.get(k, k) for k in keys}
        for key, c in self.checks.items():
            c.blockSignals(True)
            c.setChecked(key in wanted)
            c.blockSignals(False)
        self._update()

    def snapshot(self):
        return [key for key, c in self.checks.items() if c.isChecked()]


class ResourceDock(QFrame):
    """Ressources produites par l'atelier (aucune donnée factice)."""
    resource_created = Signal(object)

    def __init__(self, resource_registry=None, creator_id="brush_engine", capability_provider=None,
                 graph_provider=None, definition_provider=None, bench_provider=None):
        super().__init__()
        self.resource_registry = resource_registry
        self.creator_id = creator_id
        self.capability_provider = capability_provider
        self.graph_provider = graph_provider
        self.definition_provider = definition_provider
        self.bench_provider = bench_provider
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(label("Chaque publication ou export crée une version de ta ressource.", C["muted"], 11, wrap=True))
        self.list = QListWidget()
        self.list.setSpacing(3)
        layout.addWidget(self.list, 1)
        self.empty = label("Aucune ressource pour l'instant.\nVa à l'étape Publication quand ton outil est prêt.", C["dim"], 11, wrap=True)
        layout.addWidget(self.empty)

    def add_resource(self, resource: Resource):
        item = QListWidgetItem(f"{resource.name}\n{resource.kind} · v{resource.version} · {resource.status}")
        item.setToolTip(resource.uri)
        item.setData(Qt.ItemDataRole.UserRole, resource)
        self.list.insertItem(0, item)
        self.empty.setVisible(False)

    def resources(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def next_version(self, name, kind):
        versions = [r.version for r in self.resources() if r.name == name and r.kind == kind]
        return max(versions, default=0) + 1

    def metadata(self, name):
        metadata = {"name": name, "creator": creator_def(self.creator_id).module_id, "build": STARDUST_BUILD_ID}
        if self.capability_provider:
            metadata["parameters"] = self.capability_provider()
        if self.graph_provider:
            metadata["graph"] = self.graph_provider()
        if self.definition_provider:
            metadata["tool_definition"] = self.definition_provider()
        if self.bench_provider and self.creator_id == "blend":
            metadata["test_bench"] = self.bench_provider()
        return metadata

    def publish(self, name, kind, consumers):
        """Publie dans Existence. Retourne (ok, message)."""
        if self.resource_registry is None:
            return False, "Mode autonome : pas de registre Existence. Utilise « Exporter » pour obtenir un fichier."
        try:
            stored = self.resource_registry.create("stardust", kind, name, metadata=self.metadata(name),
                                                   access={"read": ["*"], "write": ["stardust"], "reference": ["*"]})
        except Exception as exc:  # noqa: BLE001
            return False, f"Échec de publication : {exc}"
        stored = stored if isinstance(stored, dict) else {}
        res = Resource(name, kind, "Publié", int(stored.get("version", self.next_version(name, kind))), consumers)
        self.add_resource(res)
        self.resource_created.emit(stored or res)
        return True, f"Publié dans Existence · {name} v{res.version}"

    def publish_selected(self):  # compat
        defn = (self.definition_provider() or {}).get("definition", {}) if self.definition_provider else {}
        return self.publish(defn.get("name") or "Sans nom", creator_def(self.creator_id).output_kind, defn.get("compatibility", "Nebula"))


# ─── Fenêtre principale ────────────────────────────────────────────────────
STEPS = ["Définition", "Construction", "Paramètres", "Test", "Publication"]


class StellarDust(QMainWindow):
    def __init__(self, resource_registry=None, creator_id="brush_engine", connected_creators=None, module_manifests=None):
        super().__init__()
        creator_id = creator_mode(creator_id)
        self.setWindowTitle(f"StellarDust · {STARDUST_BUILD_ID}")
        self.setProperty("stardustBuildId", STARDUST_BUILD_ID)
        self.resize(1480, 900)
        self.setMinimumSize(1060, 660)
        self.resource_registry = resource_registry
        raw = dict(connected_creators) if connected_creators is not None else discover_existence_modules()
        self.connected_creators = {"fusion_creator": bool(raw.get("fusion_creator", raw.get("blend_creator", False)))}
        manifests = dict(module_manifests or {})
        if "fusion_creator" not in manifests and "blend_creator" in manifests:
            manifests["fusion_creator"] = manifests["blend_creator"]
        self.module_manifests = manifests
        self.creator_definitions = dict(CREATOR_DEFINITIONS)
        if creator_id == "blend" and not self.connected_creators["fusion_creator"]:
            creator_id = "brush_engine"
        self.creator_id = creator_id
        self.state_all = self._read_state_file()
        self._loading = False
        self._dirty = False
        self._last_saved = None
        self.step = 1
        self.native_module_surface = None
        self.core = self._create_core(creator_id)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(700)
        self.save_timer.timeout.connect(self.save_state)
        self.validate_timer = QTimer(self)
        self.validate_timer.setSingleShot(True)
        self.validate_timer.setInterval(150)
        self.validate_timer.timeout.connect(self._revalidate)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._topbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.sidebar_host = QFrame()
        self.sidebar_host.setObjectName("sidebar")
        self.sidebar_host.setFixedWidth(220)
        QVBoxLayout(self.sidebar_host).setContentsMargins(14, 16, 14, 16)
        body.addWidget(self.sidebar_host)
        self.center = QStackedWidget()
        body.addWidget(self.center, 1)
        self.right_tabs = QTabWidget()
        self.right_tabs.setMinimumWidth(330)
        self.right_tabs.setMaximumWidth(420)
        self.right_panel = self.right_tabs
        body.addWidget(self.right_tabs)
        outer.addLayout(body, 1)
        self.setStatusBar(QStatusBar())
        self.core_label = label("", C["dim"], 10)
        self.statusBar().addPermanentWidget(self.core_label)
        self.save_label = label("", C["dim"], 10)
        self.statusBar().addPermanentWidget(self.save_label)

        self.graph = GraphView(self.creator_id, self.core)
        self.graph.interaction_message.connect(lambda m: self.toast(m))
        self.graph.graph_changed.connect(lambda _m: self._touch())
        self.graph.history_changed.connect(self._update_history_buttons)
        self.graph.node_selected.connect(self._on_node_selected)
        self._build_creator_ui()
        self._shortcuts()
        self._select_step(1)
        self.toast("Bienvenue · commence par la Construction, ou choisis un modèle de départ")

    # ── état fichier ──
    def _read_state_file(self):
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"creators": {}}
        if not isinstance(payload, dict) or payload.get("application") != "StellarDust":
            return {"creators": {}}
        if "creators" not in payload:   # migration v2 → v3
            mode = creator_mode(payload.get("creator", ""))
            payload = {"creators": {mode: {
                "graph": payload.get("graph") or {}, "definition": payload.get("definition") or {},
                "exposed": payload.get("parameters") if isinstance(payload.get("parameters"), list) else [],
                "bench": payload.get("fusion_test_bench") or {},
            }}, "last_creator": mode}
        payload.setdefault("creators", {})
        return payload

    def _creator_state(self):
        return {
            "graph": {"nodes": self.graph.model()[0], "connections": [{"from": a, "to": b} for a, b in self.graph.edges]},
            "definition": self.definition_panel.snapshot(),
            "exposed": self.parameter_panel.snapshot(),
            "engine": self.engine_editor.snapshot(),
            "bench": self.fusion_bench.snapshot() if self.fusion_bench else {},
            "resources": [r.__dict__ for r in self.resources.resources()],
        }

    def save_state(self):
        if self._loading or not hasattr(self, "definition_panel"):
            return
        self.state_all.setdefault("creators", {})[self.creator_id] = self._creator_state()
        payload = {"application": "StellarDust", "state_version": 3, "build": STARDUST_BUILD_ID,
                   "saved_at": datetime.now().isoformat(timespec="seconds"), "last_creator": self.creator_id,
                   "creators": self.state_all["creators"]}
        try:
            tmp = STATE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(STATE_FILE)
            self._dirty = False
            self._last_saved = datetime.now()
            self.save_label.setText(f"✓ Enregistré {self._last_saved:%H:%M:%S}")
        except OSError:
            self.save_label.setText("Sauvegarde locale indisponible (dossier en lecture seule)")

    def save_current(self):
        """Ctrl+S : sauvegarde immédiate (ne publie pas)."""
        self.save_timer.stop()
        self.save_state()
        self.toast("Projet enregistré")

    def _touch(self):
        if self._loading:
            return
        self._dirty = True
        self.save_label.setText("● Modifications non enregistrées")
        self.save_timer.start()
        self.validate_timer.start()
        self._refresh_preview_settings()

    def _restore_state(self):
        data = self.state_all.get("creators", {}).get(self.creator_id) or {}
        self._loading = True
        try:
            graph = data.get("graph") or {}
            self.graph.rebuild((graph.get("nodes") or [], graph.get("connections") or []))
            self.definition_panel.load(data.get("definition") or {})
            if data.get("exposed"):
                self.parameter_panel.load(data["exposed"])
            self.engine_editor.load(data.get("engine") or {})
            if self.fusion_bench and (data.get("bench") or {}).get("mode"):
                self.fusion_bench.mode.setCurrentText(data["bench"]["mode"])
            for r in data.get("resources") or []:
                try:
                    self.resources.add_resource(Resource(**r))
                except TypeError:
                    pass
        finally:
            self._loading = False
        QTimer.singleShot(0, self.graph.fit)
        self._revalidate()
        self._refresh_preview_settings()

    # ── construction UI ──
    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("toolbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 10, 18, 10)
        logo = QLabel(f"✦ STELLAR<span style='color:{C['accent']}'>DUST</span>")
        logo.setTextFormat(Qt.TextFormat.RichText)
        logo.setStyleSheet("font-size:15px; font-weight:800; letter-spacing:2px;")
        row.addWidget(logo)
        row.addSpacing(24)
        self.step_buttons = {}
        for i, name in enumerate(STEPS):
            b = QPushButton(f"{i + 1}  {name}")
            b.setObjectName("workflowStep")
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, s=i: self._select_step(s))
            self.step_buttons[i] = b
            row.addWidget(b)
            if i < len(STEPS) - 1:
                row.addWidget(label("›", C["dim"], 14))
        row.addStretch()
        self.badge = QLabel()
        self.badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge.mousePressEvent = lambda _e: self._select_step(4)
        row.addWidget(self.badge)
        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("Annuler (Ctrl+Z)")
        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("Rétablir (Ctrl+Maj+Z)")
        for b in (self.undo_btn, self.redo_btn):
            b.setObjectName("topButton")
            b.setFixedWidth(36)
            row.addWidget(b)
        self.undo_btn.clicked.connect(lambda: self.graph.undo())
        self.redo_btn.clicked.connect(lambda: self.graph.redo())
        save = QPushButton("Enregistrer")
        save.setObjectName("topButton")
        save.setToolTip("Ctrl+S · la sauvegarde est aussi automatique")
        save.clicked.connect(self.save_current)
        row.addWidget(save)
        export = QPushButton("Exporter…")
        export.setObjectName("topButton")
        export.setToolTip("Ctrl+E · exporte la ressource en fichier JSON")
        export.clicked.connect(self.export_resource)
        row.addWidget(export)
        state = QLabel("◉ Existence" if self.resource_registry is not None else "○ Autonome")
        state.setToolTip("Connecté au registre Existence" if self.resource_registry is not None
                         else "Lancé seul : la publication est remplacée par l'export de fichier")
        state.setStyleSheet(f"color:{C['ok'] if self.resource_registry is not None else C['muted']}; padding-left:10px; font-size:11px;")
        row.addWidget(state)
        return bar

    def _build_sidebar(self):
        lay = self.sidebar_host.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        lay.addWidget(SectionTitle("Creator"))
        self.creator_buttons = {}
        for mode, text in (("brush_engine", "◈  Brush Engine"), ("blend", "◌  Fusion")):
            b = QPushButton(text)
            b.setProperty("active", mode == self.creator_id)
            if mode == "blend" and not self.connected_creators["fusion_creator"]:
                b.setEnabled(False)
                b.setText("◌  Fusion · non branché")
                b.setToolTip("Fusion Creator n'est pas branché sur StellarDust dans Existence")
            b.clicked.connect(lambda _=False, m=mode: self.set_creator(m))
            self.creator_buttons[mode] = b
            lay.addWidget(b)
        self.fusion_button = self.creator_buttons["blend"]
        lay.addWidget(SectionTitle("Composants"))
        lay.addWidget(label("Clic pour ajouter, ou glisse sur le graphe", C["dim"], 10, wrap=True))
        cat = None
        for t in PALETTE[self.creator_id]:
            spec = NODE_TYPES[t]
            if spec["category"] != cat:
                cat = spec["category"]
                lay.addWidget(label(cat, C["muted"], 10))
            lay.addWidget(PaletteButton(t, self._add_graph_node))
        lay.addSpacing(6)
        tpl = QPushButton("✦  Modèle de départ")
        tpl.setObjectName("secondary")
        tpl.setToolTip("Remplace le graphe par un exemple fonctionnel")
        tpl.clicked.connect(self.load_template)
        lay.addWidget(tpl)
        lay.addStretch()
        self.module_status = label("", C["muted"], 10, wrap=True)
        lay.addWidget(self.module_status)
        self._update_module_status()

    def _update_module_status(self):
        if self.connected_creators["fusion_creator"]:
            m = self.module_manifests.get("fusion_creator", {})
            self.module_status.setText(f"✓ {m.get('name', 'Fusion Creator')} v{m.get('version', '?')} branché")
        else:
            self.module_status.setText("Modules : Fusion Creator non branché")

    def _page(self, title, subtitle, content, footer=None):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 18, 24, 14)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label(title, "#F4F7FF", 22, True))
        col.addWidget(label(subtitle, C["muted"], 12, wrap=True))
        head.addLayout(col, 1)
        if footer is not None:
            head.addWidget(footer)
        lay.addLayout(head)
        lay.addSpacing(8)
        lay.addWidget(content, 1)
        return page

    def _nav(self, prev_step, next_step):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        if prev_step is not None:
            b = QPushButton(f"‹ {STEPS[prev_step]}")
            b.setObjectName("secondary")
            b.clicked.connect(lambda: self._select_step(prev_step))
            h.addWidget(b)
        if next_step is not None:
            b = QPushButton(f"{STEPS[next_step]} ›")
            b.setObjectName("primary")
            b.clicked.connect(lambda: self._select_step(next_step))
            h.addWidget(b)
        return box

    def _build_creator_ui(self):
        blend = self.creator_id == "blend"
        d = creator_def(self.creator_id)
        self._build_sidebar()
        self.graph.setParent(None)  # le graphe survit à la reconstruction des pages
        while self.center.count():
            w = self.center.widget(0)
            self.center.removeWidget(w)
            w.deleteLater()

        # 0 Définition
        self.definition_panel = DefinitionPanel(self.creator_id)
        self.definition_panel.changed.connect(self._touch)
        self.center.addWidget(self._page("Définition", f"{d.label} · {d.description}", self.definition_panel, self._nav(None, 1)))

        # 1 Construction
        gwrap = QWidget()
        gl = QVBoxLayout(gwrap)
        gl.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        for text, tip, fn in (("Organiser", "Range les nœuds de gauche à droite", self.graph.auto_layout),
                              ("Tout afficher", "F", self.graph.fit),
                              ("−", "Zoom arrière (molette)", lambda: self.graph.zoom(1 / 1.2)),
                              ("+", "Zoom avant (molette)", lambda: self.graph.zoom(1.2))):
            b = QPushButton(text)
            b.setObjectName("secondary")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            tools.addWidget(b)
        tools.addStretch()
        self.graph_status = label("", C["muted"], 11)
        tools.addWidget(self.graph_status)
        gl.addLayout(tools)
        self.graph.creator_id = self.creator_id
        gl.addWidget(self.graph, 1)
        self.center.addWidget(self._page("Construction",
                                         "Relie des Entrées à une Sortie. Seuls les nœuds qui atteignent une Sortie influencent l'outil.",
                                         gwrap, self._nav(0, 2)))

        # 2 Paramètres
        self.parameter_panel = ParameterOrganizationPanel(self.creator_id)
        self.parameter_panel.changed.connect(self._touch)
        self.center.addWidget(self._page("Paramètres exposés", "Ce que l'utilisateur final pourra modifier.", self.parameter_panel, self._nav(1, 3)))

        # 3 Test
        test = QWidget()
        tl = QVBoxLayout(test)
        tl.setContentsMargins(0, 0, 0, 0)
        self.preview = LivePreview(self.creator_id)
        self.fusion_bench = FusionTestBench(self) if blend else None
        if blend:
            tl.addWidget(self.fusion_bench, 1)
        else:
            bar = QHBoxLayout()
            clear = QPushButton("Effacer")
            clear.setObjectName("secondary")
            clear.clicked.connect(self.preview.clear)
            color = QPushButton("Couleur…")
            color.setObjectName("secondary")
            color.clicked.connect(self._pick_color)
            sim = QCheckBox("Pression simulée (souris)")
            sim.setChecked(True)
            sim.toggled.connect(lambda v: setattr(self.preview, "simulate_pressure", v))
            bg = QCheckBox("Fond clair")
            bg.toggled.connect(self._toggle_bg)
            for w in (clear, color, sim, bg):
                bar.addWidget(w)
            bar.addStretch()
            self.preview_hint = label("", C["warn"], 11)
            bar.addWidget(self.preview_hint)
            tl.addLayout(bar)
            tl.addWidget(self.preview, 1)
        self.center.addWidget(self._page("Test", "Essaie l'outil en conditions réelles. Les réglages du graphe et du moteur s'appliquent en direct.",
                                         test, self._nav(2, 4)))

        # 4 Publication
        pub = QWidget()
        pl = QVBoxLayout(pub)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(SectionTitle("Vérifications"))
        self.issue_list = QListWidget()
        self.issue_list.setMaximumHeight(220)
        self.issue_list.itemDoubleClicked.connect(self._goto_issue)
        pl.addWidget(self.issue_list)
        self.summary = label("", "#C3D0EA", 12, wrap=True)
        pl.addWidget(self.summary)
        actions = QHBoxLayout()
        self.publish_btn = QPushButton("Publier dans Existence")
        self.publish_btn.setObjectName("primary")
        self.publish_btn.clicked.connect(self.publish)
        exp = QPushButton("Exporter en fichier…")
        exp.setObjectName("secondary")
        exp.clicked.connect(self.export_resource)
        actions.addWidget(self.publish_btn)
        actions.addWidget(exp)
        actions.addStretch()
        pl.addLayout(actions)
        pl.addStretch()
        self.center.addWidget(self._page("Publication", "Vérifie, puis publie ou exporte une nouvelle version.", pub, self._nav(3, None)))

        # panneau droit
        while self.right_tabs.count():
            w = self.right_tabs.widget(0)
            self.right_tabs.removeTab(0)
            if w is not None:
                w.deleteLater()
        self.inspector = Inspector(self.creator_id)
        self.inspector.node_parameter_changed.connect(self._on_node_parameter_changed)
        self.inspector.node_renamed.connect(lambda n, t: self.graph.rename_node(n, t))
        self.right_tabs.addTab(self._scroll(self.inspector), "Nœud")
        self.engine_editor = CapabilityEditor(self.creator_id)
        self.engine_editor.changed.connect(self._touch)
        self.engine_editor.link_requested.connect(self.link_engine_param)
        self.inspector.capability_editor = self.engine_editor  # compat
        self.right_tabs.addTab(self.engine_editor, "Moteur")
        self.resources = ResourceDock(self.resource_registry, self.creator_id, self.engine_editor.snapshot,
                                      self.graph.native_snapshot, lambda: {"definition": self.definition_panel.snapshot(),
                                                                           "exposed_parameters": self.parameter_panel.snapshot()},
                                      lambda: self.fusion_bench.snapshot() if self.fusion_bench else {})
        self.right_tabs.addTab(self.resources, "Ressources")
        self.native_module_surface = self._native_module_surface(self.creator_id)
        if self.native_module_surface is not None:
            self.right_tabs.addTab(self.native_module_surface, "Module")
        self.preview.settings_provider = self._preview_settings
        if self.resource_registry is None:
            self.publish_btn.setEnabled(False)
            self.publish_btn.setToolTip("Mode autonome : lance StellarDust depuis Existence pour publier, ou exporte en fichier")
        self.core_label.setText("Moteur natif ✓" if self.core is not None else "Moteur natif absent (./build_core.sh) · mode de secours")
        self._restore_state()
        self._update_history_buttons()

    @staticmethod
    def _scroll(w):
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QFrame.Shape.NoFrame)
        s.setWidget(w)
        return s

    def _shortcuts(self):
        def sc(keys, fn):
            QShortcut(QKeySequence(keys), self, activated=fn)
        sc("Ctrl+S", self.save_current)
        sc("Ctrl+E", self.export_resource)
        sc("Ctrl+Z", lambda: self.graph.undo())
        sc("Ctrl+Shift+Z", lambda: self.graph.redo())
        sc("Ctrl+Y", lambda: self.graph.redo())
        sc("Ctrl+D", lambda: self.graph.duplicate_selected())
        for i in range(len(STEPS)):
            sc(f"Ctrl+{i + 1}", lambda s=i: self._select_step(s))

    # ── navigation ──
    def _select_step(self, step):
        self.step = step
        self.center.setCurrentIndex(step)
        for i, b in self.step_buttons.items():
            b.setProperty("activeStep", i == step)
            b.style().unpolish(b)
            b.style().polish(b)
        if step == 1:
            self.right_tabs.setCurrentIndex(0)
            self.graph.setFocus()
            if not getattr(self, "_fitted", False):
                self._fitted = True
                QTimer.singleShot(30, self.graph.fit)
        if step == 3:
            self._refresh_preview_settings()
            if self.fusion_bench:
                self.fusion_bench.apply_graph(self._preview_settings())
        if step == 4:
            self._revalidate()

    # compat anciens appels
    def _set_view(self, view):
        self._select_step({"Graphe de conception": 1, "Prévisualisation": 3, "Validation": 4, "Paramètres": 2}.get(view, 1))

    def _select_creation_step(self, step):
        self._select_step(min(step, 4))

    # ── graphe ──
    def _add_graph_node(self, node_type="Input"):
        if self.step != 1:
            self._select_step(1)
        node = self.graph.add_node(node_type)
        if node is None:
            self.toast("StellarDustCore a refusé ce nœud")
        else:
            self.toast(f"{node.title} ajouté · glisse depuis son rond de droite pour le relier")

    def _on_node_selected(self, node):
        try:
            self.inspector.show_node(node)
        except RuntimeError:
            return
        self.graph._param_key = None
        if node is not None:
            self.right_tabs.setCurrentIndex(0)

    def _on_node_parameter_changed(self, node, key, value):
        self.graph.set_node_parameter(node, key, value)

    def _delete_graph_node(self):
        if not self.graph.delete_selected():
            self.toast("Sélectionne un nœud ou une liaison à supprimer")

    def _validate_graph(self):
        self._revalidate()
        self._select_step(4)

    def load_template(self):
        if self.creator_id == "blend":
            nodes = [dict(id="input", type="Input", config={"source": "layer"}, x=0, y=0),
                     dict(id="input_2", type="Input", config={"source": "mask"}, x=0, y=130),
                     dict(id="blend", type="Blend", config={"mode": "multiply", "contribution": 0.8}, x=280, y=40),
                     dict(id="mask", type="Mask", config={"amount": 0.9}, x=560, y=40),
                     dict(id="output", type="Output", config={"resource_type": "blend_definition"}, x=840, y=40)]
            edges = [("input", "blend"), ("input_2", "blend"), ("blend", "mask"), ("mask", "output")]
        else:
            nodes = [dict(id="input", type="Input", title="Pression", config={"source": "pressure"}, x=0, y=0),
                     dict(id="input_2", type="Input", title="Vitesse", config={"source": "velocity"}, x=0, y=140),
                     dict(id="dynamics", type="Dynamics", title="Taille ← pression", config={"target": "size", "min": 0.15, "max": 1.0, "curve": "douce (ease-in)"}, x=280, y=0),
                     dict(id="dynamics_2", type="Dynamics", title="Opacité ← vitesse", config={"target": "opacity", "min": 0.35, "max": 1.0, "invert": True}, x=280, y=140),
                     dict(id="engineparam", type="EngineParam", title="Fixe Dureté", config={"key": "hardness", "value": 0.45}, x=560, y=200),
                     dict(id="shape", type="Shape", title="Pointe ovale", config={"roundness": 0.55, "angle": 35.0, "spacing": 0.08, "hardness": 0.6}, x=560, y=60),
                     dict(id="output", type="Output", config={"resource_type": "brush_engine"}, x=840, y=60)]
            edges = [("input", "dynamics"), ("input_2", "dynamics_2"), ("dynamics", "shape"), ("dynamics_2", "shape"), ("shape", "output"), ("input", "engineparam"), ("engineparam", "output")]
        if self.graph.nodes:
            self.graph.push_undo()
        self.graph.rebuild((nodes, edges))
        self.graph.fit()
        self.graph._changed()
        self._select_step(1)
        self.toast("Modèle chargé · va à l'étape Test pour l'essayer (Ctrl+Z pour revenir)")

    def link_engine_param(self, key, how):
        """Crée dans le graphe les nœuds qui pilotent un paramètre moteur."""
        self._select_step(1)
        g = self.graph
        out = next((n for n in g.nodes if n.node_type == "Output"), None)
        anchor = (out.pos() - QPointF(280, 0)) if out else None
        if how == "fixed":
            node = g.add_node("EngineParam", anchor, {"key": key, "value": self.engine_editor.values.get(key, engine_fields().get(key, {}).get("default", 0.0))})
            if node:
                node.title = f"Fixe {engine_fields().get(key, {}).get('label', key)}"
        else:
            inp = next((n for n in g.nodes if n.node_type == "Input" and n.config.get("source") == how), None)
            if inp is None:
                inp = g.add_node("Input", (anchor - QPointF(280, 0)) if anchor else None, {"source": how})
                if inp:
                    inp.title = {"pressure": "Pression", "velocity": "Vitesse", "tilt": "Inclinaison", "random": "Aléatoire"}[how]
            node = g.add_node("Dynamics", anchor + QPointF(0, 110) if anchor else None, {"target": key})
            if node:
                node.title = f"{engine_fields().get(key, {}).get('label', key)} ← {inp.title if inp else how}"
                if inp:
                    g.connect_pair(inp, node)
        if node is not None and out is not None:
            g.connect_pair(node, out)
        if node is not None:
            g.scene().clearSelection()
            node.setSelected(True)
            node.update()
            self.toast(f"Lié au graphe : {field_label(key)} · règle le nœud dans l'onglet Nœud")

    def _update_history_buttons(self):
        self.undo_btn.setEnabled(bool(self.graph.undo_stack))
        self.redo_btn.setEnabled(bool(self.graph.redo_stack))

    # ── test ──
    def _preview_settings(self):
        return effective_settings(self.engine_editor.snapshot(), self.graph.model())

    def _refresh_preview_settings(self):
        if not hasattr(self, "preview_hint") or self.creator_id == "blend":
            return
        try:
            s = self._preview_settings()
        except RuntimeError:
            return
        self.preview_hint.setText("" if s["has_output"] else "Aucune Sortie : tous les nœuds sont appliqués")
        self.engine_editor.mark_driven(s.get("driven", {}))

    def _pick_color(self):
        c = QColorDialog.getColor(self.preview.color, self, "Couleur de test")
        if c.isValid():
            self.preview.color = c

    def _toggle_bg(self, light):
        self.preview.background = QColor("#F1EEE6" if light else "#141E36")
        if light and self.preview.color == QColor("#EAF0FF"):
            self.preview.color = QColor("#1B1B24")
        elif not light and self.preview.color == QColor("#1B1B24"):
            self.preview.color = QColor("#EAF0FF")
        self.preview.update()

    # ── validation / publication ──
    def _revalidate(self):
        if not hasattr(self, "issue_list"):
            return
        native = self.graph.native_validate()
        native_errors = [] if native.get("ok") else [e for e in native.get("result", []) if isinstance(e, str)
                                                      and "at least one node" not in e]
        model = self.graph.model()
        issues = graph_issues(model, native_errors, self.definition_panel.snapshot())
        if self.creator_id == "blend" and self.fusion_bench and not self.fusion_bench.validate():
            issues.append(("error", "Le banc de test de fusion n'a pas de résultat", None))
        self.issues = issues
        self.graph.mark_issues(issues)
        errors = [i for i in issues if i[0] == "error"]
        self.issue_list.clear()
        if not issues:
            it = QListWidgetItem("✓  Tout est bon · l'outil est prêt à être publié")
            it.setForeground(QColor(C["ok"]))
            self.issue_list.addItem(it)
        for level, text, nid in issues:
            it = QListWidgetItem(("✕  " if level == "error" else "⚠  ") + text + ("   (double-clic pour voir)" if nid else ""))
            it.setForeground(QColor(C["err"] if level == "error" else C["warn"]))
            it.setData(Qt.ItemDataRole.UserRole, nid)
            self.issue_list.addItem(it)
        if errors:
            self.badge.setText(f"  ✕ {len(errors)} problème(s)  ")
            self.badge.setStyleSheet(f"color:{C['err']}; background:#3A1C25; padding:6px 10px; border-radius:11px; font-size:10px; font-weight:700;")
        elif issues:
            self.badge.setText(f"  ⚠ {len(issues)} avertissement(s)  ")
            self.badge.setStyleSheet(f"color:{C['warn']}; background:#3A2D18; padding:6px 10px; border-radius:11px; font-size:10px; font-weight:700;")
        else:
            self.badge.setText("  ✓ Prêt  ")
            self.badge.setStyleSheet(f"color:{C['ok']}; background:#123A30; padding:6px 10px; border-radius:11px; font-size:10px; font-weight:700;")
        self.badge.setToolTip("Voir les vérifications")
        nodes, edges = model
        defn = self.definition_panel.snapshot()
        name = defn["name"] or "Sans nom"
        version = self.resources.next_version(name, creator_def(self.creator_id).output_kind)
        self.summary.setText(f"<b>{name}</b> · {creator_def(self.creator_id).output_kind} · prochaine version v{version}<br>"
                             f"{len(nodes)} nœud(s), {len(edges)} liaison(s), {len(self.parameter_panel.snapshot())} paramètre(s) exposé(s)")
        self.graph_status.setText(f"{len(nodes)} nœud(s) · {len(edges)} liaison(s)")
        if self.resource_registry is not None:
            self.publish_btn.setEnabled(not errors)
            self.publish_btn.setToolTip("Corrige les erreurs d'abord" if errors else "")

    def _goto_issue(self, item):
        nid = item.data(Qt.ItemDataRole.UserRole)
        if nid:
            self._select_step(1)
            self.graph.select_node(nid)
        elif "nom" in item.text():
            self._select_step(0)
            self.definition_panel.name.setFocus()

    def _resource_payload(self):
        defn = self.definition_panel.snapshot()
        return {
            "protocol": "existence.resource.v1", "namespace": "resource://existence/stardust",
            "kind": creator_def(self.creator_id).output_kind, "name": defn["name"] or "Sans nom",
            "created_at": datetime.now().isoformat(timespec="seconds"), "id": str(uuid.uuid4()),
            "metadata": self.resources.metadata(defn["name"] or "Sans nom"),
        }

    def publish(self):
        self._revalidate()
        if any(i[0] == "error" for i in self.issues):
            self.toast("Publication bloquée : corrige les erreurs listées")
            return
        defn = self.definition_panel.snapshot()
        ok, msg = self.resources.publish(defn["name"], creator_def(self.creator_id).output_kind, defn["compatibility"])
        self.toast(msg)
        if ok:
            self.right_tabs.setCurrentWidget(self.resources)
            self._touch()
            self._revalidate()

    def export_resource(self):
        self._revalidate()
        payload = self._resource_payload()
        slug = "-".join(payload["name"].lower().split()) or "ressource"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la ressource", str(Path.home() / f"{slug}.stardust.json"),
                                              "Ressource StellarDust (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError as exc:
            self.toast(f"Export impossible : {exc}")
            return
        version = self.resources.next_version(payload["name"], payload["kind"])
        self.resources.add_resource(Resource(payload["name"], payload["kind"], "Exporté", version, "", f"file://{path}"))
        self._touch()
        warn = " (avec des erreurs non corrigées)" if any(i[0] == "error" for i in self.issues) else ""
        self.toast(f"Exporté{warn} → {path}")

    # ── Creators ──
    def set_creator(self, creator_id):
        creator_id = creator_mode(creator_id)
        if creator_id == self.creator_id:
            return
        if creator_id == "blend" and not self.connected_creators["fusion_creator"]:
            self.toast("Fusion Creator n'est pas branché sur StellarDust")
            return
        self.save_timer.stop()
        self.save_state()
        self.creator_id = creator_id
        if self.core is not None:
            self.core.close()
        self.core = self._create_core(creator_id)
        self.graph.core = self.core
        self.graph.undo_stack.clear()
        self.graph.redo_stack.clear()
        self._fitted = False
        self._build_creator_ui()
        self._select_step(self.step)
        self.toast(f"{creator_def(creator_id).label} ouvert")

    def _refresh_creator_context(self):  # compat
        self._build_sidebar()

    def refresh_creator_connection(self, connected: bool):
        """Applique un changement d'orbite Existence à l'UI."""
        self.connected_creators["fusion_creator"] = bool(connected)
        if not connected and self.creator_id == "blend":
            self.set_creator("brush_engine")
        else:
            self._build_sidebar()
        self.toast("Fusion Creator connecté" if connected else "Fusion Creator débranché")

    @staticmethod
    def _create_core(creator_id):
        if StellarDustCore is None:
            return None
        try:
            return StellarDustCore(creator_id)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return None

    def _native_module_surface(self, creator_id):
        if creator_id != "blend" or not self.connected_creators.get("fusion_creator"):
            return None
        try:
            root = str(CREATIVE_CORE_ROOT)
            if root not in sys.path:
                sys.path.insert(0, root)
            from UI.docks.blend_creator_dock import BlendCreatorDock
            surface = BlendCreatorDock(self)
            surface.setWindowFlags(Qt.WindowType.Widget)
            return surface
        except Exception as exc:  # noqa: BLE001
            self.toast(f"Interface Fusion Creator indisponible : {exc}")
            return None

    def toast(self, message, ms=6000):
        if self.statusBar() is not None:
            self.statusBar().showMessage(message, ms)

    def closeEvent(self, event):
        self.save_timer.stop()
        self.save_state()
        if self.core is not None:
            self.core.close()
        super().closeEvent(event)


STYLE = f"""
    * {{ font-family: Inter, "Noto Sans", Arial; }}
    QMainWindow, #root {{ background:{C['bg']}; color:{C['text']}; }}
    QWidget {{ color:#DCE4F7; }}
    QLabel {{ background:transparent; }}
    #toolbar {{ background:{C['panel']}; border-bottom:1px solid {C['line']}; }}
    #sidebar {{ background:{C['panel2']}; border-right:1px solid {C['line']}; }}
    #panel {{ background:{C['panel']}; border:1px solid {C['line']}; border-radius:10px; }}
    QPushButton {{ color:#A9B8D5; background:transparent; border:0; border-radius:7px; padding:8px 10px; text-align:left; font-size:12px; }}
    QPushButton:hover {{ background:#1A2947; color:#F4F7FF; }}
    QPushButton:disabled {{ color:#44557A; }}
    QPushButton[active="true"] {{ background:#24365B; color:#FFFFFF; }}
    #workflowStep {{ text-align:center; padding:6px 12px; border-radius:14px; }}
    QPushButton[activeStep="true"] {{ background:#263862; color:#FFFFFF; border:1px solid {C['accent']}; }}
    QPushButton[activeStep="false"] {{ color:{C['muted']}; }}
    #topButton {{ background:#182442; color:#C3D0EA; padding:6px 12px; margin-left:4px; text-align:center; }}
    #primary {{ background:{C['primary']}; color:#FFFFFF; font-weight:700; text-align:center; padding:9px 16px; }}
    #primary:hover {{ background:#8577F0; }}
    #primary:disabled {{ background:#2A2F55; color:#6B7299; }}
    #secondary {{ background:#1A2947; color:#C9D5ED; text-align:center; padding:7px 12px; }}
    #paletteButton {{ background:#131E38; margin:1px 0; padding:7px 8px; }}
    #paletteButton:hover {{ background:#1C2B4B; }}
    QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit {{ background:{C['bg']}; border:1px solid #2A3A5A; border-radius:6px; color:#DCE4F7; padding:5px 7px; font-size:12px; }}
    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{ border:1px solid {C['accent']}; }}
    QComboBox QAbstractItemView {{ background:{C['panel']}; color:#DCE4F7; selection-background-color:#263862; }}
    QCheckBox {{ font-size:12px; color:#C3D0EA; spacing:8px; padding:3px 0; }}
    QSlider::groove:horizontal {{ height:4px; background:#2A3A5A; border-radius:2px; }}
    QSlider::handle:horizontal {{ width:14px; margin:-5px 0; border-radius:7px; background:{C['accent']}; }}
    QListWidget {{ background:{C['panel2']}; border:1px solid {C['line']}; border-radius:8px; color:#C3D0EA; font-size:12px; padding:4px; }}
    QListWidget::item {{ padding:7px; border-radius:6px; }}
    QListWidget::item:selected {{ background:#1C2B4B; color:#FFFFFF; }}
    QTabWidget::pane {{ border:0; border-left:1px solid {C['line']}; background:{C['panel']}; padding:10px; }}
    QTabBar::tab {{ background:{C['panel2']}; color:{C['muted']}; padding:9px 16px; border:0; }}
    QTabBar::tab:selected {{ background:{C['panel']}; color:#FFFFFF; border-bottom:2px solid {C['accent']}; }}
    QToolBox::tab {{ background:#152039; color:#C3D0EA; border-radius:6px; padding:6px; font-weight:700; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; }}
    QScrollBar:vertical {{ background:transparent; width:8px; }}
    QScrollBar::handle:vertical {{ background:#2A3A5A; border-radius:4px; min-height:30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
    QMenu {{ background:{C['panel']}; border:1px solid {C['line']}; color:#DCE4F7; padding:4px; }}
    QMenu::item {{ padding:6px 18px; border-radius:4px; }}
    QMenu::item:selected {{ background:#263862; }}
    QToolTip {{ background:{C['panel']}; color:#DCE4F7; border:1px solid {C['line']}; padding:6px; }}
    QStatusBar {{ background:{C['panel']}; color:#AAB9D6; border-top:1px solid {C['line']}; font-size:11px; }}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = StellarDust()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
