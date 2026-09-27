"""StarDust — atelier de création d'outils d'Existence (26.0).

- Creators intégrés : Brush Engine (.csbr) et Fusion (.csbl), à base de graphe.
- Creators fournis par Existence : tout module qui déclare une interface
  `existence.creator.v1` (Palette Creator .cspl, Gradient Creator .csgr…).
  Existence possède le module et son interface ; StarDust la charge quand le
  module est branché et adapte ses étapes, sa validation, ses fichiers et sa
  publication. Débrancher le module dans Existence le retire de l'atelier.
"""
from __future__ import annotations

import importlib
import json
import math
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QAction, QBrush, QColor, QCursor, QFont, QImage, QKeySequence, QLinearGradient, QPainter, QPen, QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSplitter, QStackedWidget, QStatusBar, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from sd_engine import (  # noqa: E402
    BLEND_MODES, NODE_TYPES, PALETTE, compile_graph, creative_core_capabilities, engine_fields, evaluate,
    field_label, graph_issues, nebula_brush_preset,
)
from sd_graph import CapabilityEditor, GraphView, Inspector, PaletteButton  # noqa: E402
from sd_theme import STYLE, C, SectionTitle, label  # noqa: E402

try:
    from core_bridge import StarDustCore
except ImportError:
    StarDustCore = None

def _state_file() -> Path:
    """Session : à côté du code en développement, dans ~/.local/state une fois installé
    (le dossier d'un paquet n'est pas modifiable)."""
    legacy = ROOT / "stardust_state.json"
    if os.access(ROOT, os.W_OK):
        return legacy
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    target = base / "CreativeSystem" / "stardust" / "stardust_state.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


STATE_FILE = _state_file()
STARDUST_VERSION = "26.0"  # <année>.<release>
STARDUST_BUILD_ID = "26.0"
CS_GALAXY_ROOT = Path(os.environ.get("EXISTENCE_ROOT") or (
    "/usr/share/existence/existence" if Path("/usr/share/existence/existence").is_dir()
    else Path.home() / "Documents" / "Existence"))
NEBULA_ROOT = Path(os.environ.get("EXISTENCE_NEBULA_DIR") or (
    "/usr/share/existence/nebula" if Path("/usr/share/existence/nebula").is_dir()
    else Path.home() / "Documents" / "Nebula"))
EXISTENCE_APPS = Path.home() / ".config" / "existence" / "apps.json"
DOC_FORMAT = "creativesysteme.stellardust.document"

CREATOR_MODE_ALIASES = {
    "blend": "blend", "blend_creator": "blend", "blend-creator": "blend",
    "fusion_creator": "blend", "fusion-creator": "blend",
    "brush_engine": "brush_engine", "brush-engine": "brush_engine", "brush_engine_creator": "brush_engine",
    "palette": "palette_creator", "palette-creator": "palette_creator",
    "gradient": "gradient_creator", "gradient-creator": "gradient_creator",
}

BUILTIN_CREATORS = {
    "brush_engine": dict(label="Brush Engine", icon="◈", kind="brush_engine", ext="csbr", module=None, graph=True,
                         description="Moteurs de pinceau pilotés par CreativeCore."),
    "blend": dict(label="Fusion", icon="◌", kind="blend_definition", ext="csbl", module="fusion_creator", graph=True,
                  description="Comportements de fusion et de composition."),
}
GRAPH_STEPS = ["Définition", "Construction", "Paramètres", "Test", "Publication"]
MODULE_STEPS = ["Définition", "Édition", "Test", "Publication"]


def creator_mode(value: str) -> str:
    v = str(value or "").strip().casefold()
    return CREATOR_MODE_ALIASES.get(v, v or "brush_engine")


@dataclass(frozen=True)
class CreatorDefinition:   # compat
    module_id: str
    mode: str
    label: str
    description: str
    output_kind: str
    inputs: tuple


CREATOR_DEFINITIONS = {
    "brush_engine": CreatorDefinition("brush_engine_creator", "brush_engine", "Brush Engine Creator",
                                      "Construire des moteurs de pinceau.", "brush_engine", ("pointer", "pressure", "velocity", "tilt")),
    "fusion_creator": CreatorDefinition("fusion_creator", "blend", "Fusion Creator",
                                        "Construire des comportements de fusion.", "blend_definition", ("layer", "mask", "selection")),
}


def discover_existence_creators():
    """Mode autonome : lit les modules d'Existence et leur état branché."""
    manifests, plugged = {}, {}
    if CS_GALAXY_ROOT.exists():
        root = str(CS_GALAXY_ROOT)
        if root not in sys.path:
            sys.path.append(root)
        try:
            from modules.registry import default_registry
            reg = default_registry()
            found = list(reg.creators_for("stardust")) if hasattr(reg, "creators_for") else []
            for m in found + [reg.manifest("fusion_creator")]:
                if m is not None:
                    manifests[m.id] = m.to_dict()
        except Exception:  # noqa: BLE001
            pass
    try:
        apps = json.loads(EXISTENCE_APPS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        apps = []
    by_id = {a.get("id"): a for a in apps if isinstance(a, dict)}
    for module_id in manifests:
        app = by_id.get(module_id)
        hosts = list((app or {}).get("orbits") or []) + [(app or {}).get("orbit_of")]
        plugged[module_id] = bool(app and "stardust" in hosts and app.get("app_kind") == "orbital_module"
                                  and app.get("installed", True) and app.get("lifecycle_state", "available") != "closed")
    return manifests, plugged


def shared_library():
    """Bibliothèque centrale d'Existence (module Ressources), ou None."""
    if CS_GALAXY_ROOT.exists() and str(CS_GALAXY_ROOT) not in sys.path:
        sys.path.append(str(CS_GALAXY_ROOT))
    try:
        from modules.resource_center.library import SharedLibrary
        return SharedLibrary()
    except Exception:  # noqa: BLE001
        return None


def discover_existence_modules():  # compat
    return {"fusion_creator": discover_existence_creators()[1].get("fusion_creator", False)}


def load_creator_interface(manifest: dict, host: dict):
    """Charge l'interface d'un module possédé par Existence (existence.creator.v1)."""
    if CS_GALAXY_ROOT.exists() and str(CS_GALAXY_ROOT) not in sys.path:
        sys.path.append(str(CS_GALAXY_ROOT))
    try:
        from modules.creator_interface import create_creator
    except ImportError:
        module_name, attr = manifest["interface"].split(":", 1)
        return getattr(importlib.import_module(module_name), attr)(host)
    return create_creator(manifest, host)


# ─── Test : surfaces ───────────────────────────────────────────────────────
class LivePreview(QFrame):
    """Dessine réellement avec le moteur + le graphe (pression, inclinaison, vitesse, direction)."""

    def __init__(self, creator_id="brush_engine", parent=None, compact=False):
        super().__init__(parent)
        self.creator_id = creator_id
        self.settings_provider = None
        self.on_values = None
        self.image = QImage()
        self.color = QColor("#EAF0FF")
        self.background = QColor("#141E36")
        self.last = None
        self.distance_left = 0.0
        self.travel = 0.0
        self.tablet_active = False
        self.simulate_pressure = True
        self.compiled = None
        self._current = {}
        self._drew = False
        self._emit_t = 0.0
        self.compact = compact
        self.setMinimumHeight(160)
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

    def paintEvent(self, _e):
        self._ensure()
        p = QPainter(self)
        p.fillRect(self.rect(), self.background)
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        for x in range(0, self.width(), 32):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32):
            p.drawLine(0, y, self.width(), y)
        p.drawImage(0, 0, self.image)
        if not self._drew:
            p.setPen(QColor(C["muted"]))
            p.setFont(QFont("Inter", 10 if self.compact else 11))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                       "Dessine ici" if self.compact else
                       "Dessine ici pour tester ton moteur\n(stylet : pression et inclinaison réelles · souris : pression simulée par la vitesse)")
        p.end()

    def clear(self):
        self.image.fill(Qt.GlobalColor.transparent)
        self._drew = False
        self.update()

    def _begin(self, pos, pressure, tilt):
        self.compiled = self.settings_provider() if self.settings_provider else compile_graph({"size": 12.0}, ([], []))
        self.last = (pos, pressure, tilt)
        self.distance_left = 0.0
        self.travel = 0.0
        self._drew = True
        self._dab(pos, pressure, tilt, 0.0, 0.0)

    def _end(self):
        self.last = None
        if self.on_values:
            QTimer.singleShot(1200, lambda: self.last is None and self.on_values and self.on_values({}))

    def _dab_params(self, pressure, velocity, tilt, direction):
        v = min(1.0, velocity / 40.0)
        raw = {"pressure": pressure, "velocity": v, "tilt": tilt, "random": random.random(), "pointer": 1.0,
               "direction": direction, "distance": (self.travel / 600.0) % 1.0, "layer": 1.0, "mask": 1.0, "selection": 1.0}
        s, values = evaluate(self.compiled, raw)
        now = time.monotonic()
        if self.on_values and now - self._emit_t > 0.04:
            self._emit_t = now
            self.on_values(values)
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
        if self.compact:
            size *= 0.7
        return max(0.5, size), max(0.0, min(1.0, opacity * float(s.get("mask", 1.0)))), angle, max(0.01, spacing)

    def _dab(self, pos, pressure, tilt, velocity, direction):
        size, opacity, angle, _sp = self._dab_params(pressure, velocity, tilt, direction)
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
        dx, dy = pos.x() - lp.x(), pos.y() - lp.y()
        dist = math.hypot(dx, dy)
        if dist < 0.01:
            return
        direction = (math.degrees(math.atan2(dy, dx)) % 360.0) / 360.0
        size, _o, _a, spacing = self._dab_params(pressure, dist, tilt, direction)
        step = max(0.75, size * spacing)
        t = step - self.distance_left
        while t <= dist:
            f = t / dist
            self.travel += step
            self._dab(QPointF(lp.x() + dx * f, lp.y() + dy * f), lpr + (pressure - lpr) * f, lt + (tilt - lt) * f, dist, direction)
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
            self._end()
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
        if not self.tablet_active and self.last is not None:
            self._end()


class FusionTestBench(QFrame):
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

    def apply_graph(self, compiled):
        self.contribution = float(compiled.get("mask", 1.0))
        mode = compiled.get("composition", "normal")
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
        overlay = self.image_b.scaled(result.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        mode = {"normal": QPainter.CompositionMode.CompositionMode_SourceOver,
                "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
                "screen": QPainter.CompositionMode.CompositionMode_Screen,
                "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
                "darken": QPainter.CompositionMode.CompositionMode_Darken,
                "lighten": QPainter.CompositionMode.CompositionMode_Lighten}.get(self.mode.currentText(), QPainter.CompositionMode.CompositionMode_SourceOver)
        painter = QPainter(result)
        painter.setOpacity(self.contribution)
        painter.setCompositionMode(mode)
        painter.drawImage(0, 0, overlay)
        painter.end()
        self.result = result
        self._show()
        self.status.setText(f"Résultat · mode {self.mode.currentText()} · contribution {self.contribution:.0%}")

    def _show(self):
        for image, panel in ((self.image_a, self.input_a[1]), (self.image_b, self.input_b[1]), (self.result, self.output[1])):
            if not image.isNull():
                panel.setPixmap(QPixmap.fromImage(image).scaled(panel.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def validate(self):
        return not self.result.isNull()

    def snapshot(self):
        return {"mode": self.mode.currentText(), "result": {"width": self.result.width(), "height": self.result.height(), "valid": not self.result.isNull()}}


# ─── Définition / paramètres / ressources ──────────────────────────────────
class DefinitionPanel(QFrame):
    changed = Signal()

    def __init__(self, spec: dict, default_name="Sans nom", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Donne une identité à l'outil. Ces informations accompagnent le fichier et la ressource publiée.",
                               C["muted"], 12, wrap=True))
        layout.addWidget(SectionTitle("Nom"))
        self.name = QLineEdit(default_name)
        self.name.setPlaceholderText("Nom (obligatoire)")
        self.name.setStyleSheet("font-size:18px; padding:10px;")
        layout.addWidget(self.name)
        layout.addWidget(SectionTitle("Description"))
        self.description = QTextEdit()
        self.description.setPlaceholderText("Ce que produit l'outil, dans quel contexte l'utiliser…")
        self.description.setMaximumHeight(110)
        layout.addWidget(self.description)
        grid = QFormLayout()
        grid.setContentsMargins(0, 10, 0, 0)
        self.author = QLineEdit()
        self.author.setPlaceholderText("Deanos")
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("encre, texture, croquis…")
        self.compatibility = QLineEdit("Nebula")
        self.outputs = QLineEdit(spec["kind"])
        self.outputs.setReadOnly(True)
        self.inputs = QLineEdit("")   # compat
        grid.addRow("Auteur", self.author)
        grid.addRow("Étiquettes", self.tags)
        grid.addRow("Compatible avec", self.compatibility)
        grid.addRow("Type produit", self.outputs)
        layout.addLayout(grid)
        layout.addWidget(label(f"Fichier : .{spec['ext']}", C["dim"], 10))
        layout.addStretch()
        for w in (self.name, self.author, self.tags, self.compatibility):
            w.textChanged.connect(self.changed)
        self.description.textChanged.connect(self.changed)

    def load(self, data):
        if not isinstance(data, dict):
            return
        if data.get("name") and data["name"] not in ("Untitled Brush Engine", "Blend Definition"):
            self.name.setText(data["name"])
        self.description.setPlainText(data.get("description", ""))
        for key, w in (("author", self.author), ("tags", self.tags), ("compatibility", self.compatibility)):
            if data.get(key):
                w.setText(str(data[key]))

    def snapshot(self):
        return {"name": self.name.text().strip(), "description": self.description.toPlainText(), "author": self.author.text().strip(),
                "tags": self.tags.text().strip(), "compatibility": self.compatibility.text().strip(), "outputs": self.outputs.text()}


class ParameterOrganizationPanel(QFrame):
    changed = Signal()

    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label("Coche ce que l'utilisateur final pourra régler dans Nebula. Le reste reste interne.", C["muted"], 12, wrap=True))
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
        col = QVBoxLayout(content)
        self.checks = {}
        if creator_id == "blend":
            groups = {"Fusion": [("mode", "Mode de fusion"), ("channel", "Canal"), ("contribution", "Contribution"), ("mask", "Masque")]}
            default = {"mode", "contribution"}
        else:
            brush = creative_core_capabilities()["brush"]
            groups = {g: [(f[0], f[1]) for f in fields] + list(brush["bool_groups"].get(g, [])) for g, fields in brush["float_groups"].items()}
            default = {"size", "opacity", "flow"}
        for g, fields in groups.items():
            col.addWidget(SectionTitle(g))
            for key, text in fields:
                check = QCheckBox(text)
                check.setChecked(key in default)
                check.toggled.connect(self._update)
                self.checks[key] = check
                col.addWidget(check)
        col.addStretch()
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


@dataclass
class Resource:
    name: str
    kind: str
    status: str = "Brouillon"
    version: int = 1
    consumers: str = "Nebula"
    uri_override: str = ""

    @property
    def uri(self):
        return self.uri_override or f"resource://existence/stardust/{self.kind}/{'-'.join(self.name.lower().split())}"


class ResourceDock(QFrame):
    resource_created = Signal(object)

    def __init__(self, resource_registry=None, kind="brush_engine", payload_provider=None, module_id="brush_engine_creator"):
        super().__init__()
        self.resource_registry = resource_registry
        self.kind = kind
        self.module_id = module_id
        self.payload_provider = payload_provider
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(label("Chaque publication ou export crée une version de la ressource.", C["muted"], 11, wrap=True))
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        self.empty = label("Aucune ressource pour l'instant.", C["dim"], 11, wrap=True)
        layout.addWidget(self.empty)

    def add_resource(self, resource: Resource):
        item = QListWidgetItem(f"{resource.name}\n{resource.kind} · v{resource.version} · {resource.status}")
        item.setToolTip(resource.uri)
        item.setData(Qt.ItemDataRole.UserRole, resource)
        self.list.insertItem(0, item)
        self.empty.setVisible(False)

    def resources(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def next_version(self, name):
        return max((r.version for r in self.resources() if r.name == name and r.kind == self.kind), default=0) + 1

    def metadata(self, name):
        meta = {"name": name, "creator": self.module_id, "build": STARDUST_BUILD_ID}
        if self.payload_provider:
            meta.update(self.payload_provider())
        return meta

    def publish(self, name, consumers):
        if self.resource_registry is None:
            return False, "Mode autonome : pas de registre Existence. Utilise « Exporter » pour obtenir un fichier."
        try:
            stored = self.resource_registry.create("stardust", self.kind, name, metadata=self.metadata(name),
                                                   access={"read": ["*"], "write": ["stardust"], "reference": ["*"]})
        except Exception as exc:  # noqa: BLE001
            return False, f"Échec de publication : {exc}"
        stored = stored if isinstance(stored, dict) else {}
        res = Resource(name, self.kind, "Publié", int(stored.get("version", self.next_version(name))), consumers)
        self.add_resource(res)
        self.resource_created.emit(stored or res)
        return True, f"Publié dans Existence · {name} v{res.version}"


# ─── Fenêtre ────────────────────────────────────────────────────────────────
class StarDust(QMainWindow):
    def __init__(self, resource_registry=None, creator_id="brush_engine", connected_creators=None,
                 module_manifests=None, module_registry=None):
        super().__init__()
        self.setProperty("stardustBuildId", STARDUST_BUILD_ID)
        self.resize(1520, 920)
        self.setMinimumSize(1080, 680)
        self.resource_registry = resource_registry
        self.module_registry = module_registry
        if connected_creators is None and module_manifests is None:
            manifests, plugged = discover_existence_creators()
        else:
            manifests = dict(module_manifests or {})
            plugged = {}
            for k, v in dict(connected_creators or {}).items():
                key = "fusion_creator" if creator_mode(k) == "blend" else k
                plugged[key] = bool(v)
            if "blend_creator" in manifests and "fusion_creator" not in manifests:
                manifests["fusion_creator"] = manifests["blend_creator"]
        self.module_manifests = manifests
        self.plugged = plugged
        self.connected_creators = {"fusion_creator": plugged.get("fusion_creator", False)}  # compat
        self.creator_definitions = dict(CREATOR_DEFINITIONS)
        self.state_all = self._read_state_file()
        self._loading = False
        self._dirty = False
        self._fitted = False
        self._drop_pos = None
        self.doc_path = None
        self.step = 1
        self.iface = None
        self.fusion_bench = None
        self.preview = None
        self.mini_preview = None
        self.engine_editor = None
        self.parameter_panel = None
        self.native_module_surface = None
        self.issues = []
        requested = creator_mode(creator_id)
        if requested == "brush_engine":
            requested = creator_mode(self.state_all.get("last_creator", "brush_engine"))
        self.creator_id = requested if self.creator_available(requested) else "brush_engine"
        self.core = self._create_core(self.creator_id)

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
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setFixedWidth(228)
        side_scroll.setWidget(self.sidebar_host)
        QVBoxLayout(self.sidebar_host).setContentsMargins(14, 14, 14, 14)
        body.addWidget(side_scroll)
        self.center = QStackedWidget()
        body.addWidget(self.center, 1)
        self.right_tabs = QTabWidget()
        self.right_tabs.setMinimumWidth(330)
        self.right_tabs.setMaximumWidth(430)
        self.right_panel = self.right_tabs
        body.addWidget(self.right_tabs)
        outer.addLayout(body, 1)
        self.setStatusBar(QStatusBar())
        self.core_label = label("", C["dim"], 10)
        self.statusBar().addPermanentWidget(self.core_label)
        self.save_label = label("", C["dim"], 10)
        self.statusBar().addPermanentWidget(self.save_label)

        self.graph = GraphView(self.creator_id if self.spec.get("graph") else "brush_engine", self.core)
        self.graph.interaction_message.connect(self.toast)
        self.graph.graph_changed.connect(lambda _m: self._touch())
        self.graph.history_changed.connect(self._update_history_buttons)
        self.graph.node_selected.connect(self._on_node_selected)
        self.graph.curve_requested.connect(self._on_curve_requested)
        self.graph.engine_dropped.connect(self._on_engine_dropped)
        self._menus()
        self._build_creator_ui()
        self._select_step(1)

    # ── creators ──
    def all_creators(self):
        out = dict(BUILTIN_CREATORS)
        for mid, m in self.module_manifests.items():
            if m.get("interface_protocol") == "existence.creator.v1" and m.get("interface"):
                out[mid] = dict(label=m.get("name", mid).replace(" Creator", ""), icon=m.get("icon") or "◇",
                                kind=m.get("produces") or mid, ext=m.get("file_extension") or mid[:4], module=mid,
                                graph=False, description=f"Module Existence · v{m.get('version', '?')}", manifest=m)
        return out

    def creator_available(self, cid):
        spec = self.all_creators().get(cid)
        if spec is None:
            return False
        return spec["module"] is None or bool(self.plugged.get(spec["module"]))

    @property
    def spec(self):
        return self.all_creators().get(self.creator_id, BUILTIN_CREATORS["brush_engine"])

    @property
    def steps(self):
        return GRAPH_STEPS if self.spec.get("graph") else MODULE_STEPS

    def _host(self):
        return {"theme": dict(C), "host_id": "stardust", "build": STARDUST_BUILD_ID}

    # ── état de session ──
    def _read_state_file(self):
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"creators": {}, "recent": []}
        if not isinstance(payload, dict) or payload.get("application") != "StarDust":
            return {"creators": {}, "recent": []}
        if "creators" not in payload:   # v2
            mode = creator_mode(payload.get("creator", ""))
            payload = {"creators": {mode: {
                "definition": payload.get("definition") or {},
                "content": {"graph": payload.get("graph") or {},
                            "exposed": payload.get("parameters") if isinstance(payload.get("parameters"), list) else []}}},
                "last_creator": mode}
        for cid, data in list(payload["creators"].items()):
            if isinstance(data, dict) and "content" not in data:   # v3 → v4
                payload["creators"][cid] = {"definition": data.get("definition") or {}, "resources": data.get("resources") or [],
                                            "content": {k: data.get(k) for k in ("graph", "engine", "exposed", "bench")}}
        payload.setdefault("recent", [])
        return payload

    def _content(self):
        if self.spec.get("graph"):
            nodes, edges = self.graph.model()
            return {"graph": {"nodes": nodes, "connections": [{"from": a, "to": b} for a, b in edges]},
                    "engine": self.engine_editor.snapshot(), "exposed": self.parameter_panel.snapshot(),
                    "bench": self.fusion_bench.snapshot() if self.fusion_bench else {}}
        return self.iface.snapshot() if self.iface is not None else {}

    def _creator_state(self):
        return {"definition": self.definition_panel.snapshot(), "content": self._content(),
                "resources": [r.__dict__ for r in self.resources.resources()],
                "doc_path": str(self.doc_path) if self.doc_path else "", "dirty": self._dirty}

    def save_state(self):
        if self._loading or not hasattr(self, "definition_panel"):
            return
        try:
            self.state_all.setdefault("creators", {})[self.creator_id] = self._creator_state()
        except RuntimeError:
            return
        payload = {"application": "StarDust", "state_version": 4, "build": STARDUST_BUILD_ID,
                   "saved_at": datetime.now().isoformat(timespec="seconds"), "last_creator": self.creator_id,
                   "recent": self.state_all.get("recent", [])[:10], "creators": self.state_all["creators"]}
        try:
            tmp = STATE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(STATE_FILE)
        except OSError:
            self.save_label.setText("Session non sauvegardable (dossier en lecture seule)")

    def _apply_creator_state(self, data):
        self._loading = True
        try:
            data = data or {}
            content = data.get("content") or {}
            self.definition_panel.load(data.get("definition") or {})
            if self.spec.get("graph"):
                graph = content.get("graph") or {}
                self.graph.rebuild((graph.get("nodes") or [], graph.get("connections") or []))
                if content.get("exposed"):
                    self.parameter_panel.load(content["exposed"])
                self.engine_editor.load(content.get("engine") or {})
                if self.fusion_bench and (content.get("bench") or {}).get("mode"):
                    self.fusion_bench.mode.setCurrentText(content["bench"]["mode"])
            elif self.iface is not None and content:
                self.iface.load(content)
            for r in data.get("resources") or []:
                try:
                    self.resources.add_resource(Resource(**r))
                except TypeError:
                    pass
            self.doc_path = Path(data["doc_path"]) if data.get("doc_path") else None
            self._dirty = bool(data.get("dirty", False))
        finally:
            self._loading = False
        if self.spec.get("graph"):
            QTimer.singleShot(0, self.graph.fit)
        self._update_title()
        self._revalidate()
        self._refresh_drive_marks()

    def _touch(self):
        if self._loading:
            return
        self._dirty = True
        self._update_title()
        self.save_timer.start()
        self.validate_timer.start()
        self._refresh_drive_marks()

    def _update_title(self):
        name = self.doc_path.name if self.doc_path else f"sans titre.{self.spec['ext']}"
        self.setWindowTitle(f"{'● ' if self._dirty else ''}{name} — StarDust {STARDUST_VERSION} · {self.spec['label']}")
        if hasattr(self, "doc_label"):
            self.doc_label.setText(f"{name}{'  ●' if self._dirty else ''}")
            self.doc_label.setToolTip(str(self.doc_path) if self.doc_path else "Pas encore enregistré (Ctrl+S)")
        self.save_label.setText("● Non enregistré dans le fichier (session conservée)" if self._dirty else "✓ Fichier à jour")

    # ── menus ──
    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&Fichier")
        self.new_menu = f.addMenu("Nouveau")
        f.addAction(self._act("Ouvrir…", "Ctrl+O", self.open_document))
        self.recent_menu = f.addMenu("Récents")
        f.addSeparator()
        f.addAction(self._act("Enregistrer", "Ctrl+S", self.save_document))
        f.addAction(self._act("Enregistrer sous…", "Ctrl+Shift+S", lambda: self.save_document(as_new=True)))
        f.addSeparator()
        f.addAction(self._act("Exporter la ressource…", "Ctrl+E", self.export_resource))
        f.addAction(self._act("Publier dans les Ressources", "Ctrl+Shift+P", self.publish))
        e = mb.addMenu("&Édition")
        e.addAction(self._act("Annuler", "Ctrl+Z", self.undo))
        e.addAction(self._act("Rétablir", "Ctrl+Shift+Z", self.redo))
        e.addAction(self._act("Rétablir", "Ctrl+Y", self.redo))
        e.addSeparator()
        for text, key, fn in (("Copier les nœuds", "Ctrl+C", lambda: self.graph.copy_selected()),
                              ("Coller les nœuds", "Ctrl+V", lambda: self.graph.paste()),
                              ("Dupliquer", "Ctrl+D", lambda: self.graph.duplicate_selected()),
                              ("Tout sélectionner", "Ctrl+A", lambda: self.graph.select_all())):
            e.addAction(self._act(text, key, lambda f_=fn: self.spec.get("graph") and f_()))
        e.addAction(self._act("Chercher un nœud…", "Ctrl+K", lambda: self.spec.get("graph") and (self._select_step(1), self.graph.open_search())))
        v = mb.addMenu("&Affichage")
        v.addAction(self._act("Tout afficher", "", lambda: self.graph.fit()))
        v.addAction(self._act("Organiser le graphe", "Ctrl+L", lambda: self.graph.auto_layout()))
        v.addSeparator()
        for i in range(5):
            v.addAction(self._act(f"Étape {i + 1}", f"Ctrl+{i + 1}", lambda s=i: self._select_step(s)))
        h = mb.addMenu("&Aide")
        h.addAction(self._act("Raccourcis et gestes", "F1", self.show_help))
        self._refresh_file_menus()

    def _act(self, text, shortcut, fn):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(lambda _=False: fn())
        return a

    def _refresh_file_menus(self):
        self.new_menu.clear()
        for cid, spec in self.all_creators().items():
            text = f"{spec['icon']}  {spec['label']}  (.{spec['ext']})"
            ok = self.creator_available(cid)
            a = self.new_menu.addAction(text if ok else text + " — module non branché")
            a.setEnabled(ok)
            a.triggered.connect(lambda _=False, c=cid: self.new_document(c))
        self.recent_menu.clear()
        recent = [p for p in self.state_all.get("recent", []) if Path(p).exists()]
        for p in recent[:10]:
            a = self.recent_menu.addAction(Path(p).name)
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, path=p: self.open_document(path))
        self.recent_menu.setEnabled(bool(recent))

    def show_help(self):
        QMessageBox.information(self, "Raccourcis et gestes", (
            "GRAPHE\n"
            "• Tab / Espace / double-clic dans le vide : chercher et ajouter un nœud\n"
            "• Tirer du rond de droite vers un nœud : relier · relâcher dans le vide : nouveau nœud déjà relié\n"
            "• Tirer depuis une entrée : détacher · déposer un nœud sur une liaison : l'insérer\n"
            "• Sur un nœud : glisser une barre (Maj : précis, double-clic : défaut), clic ▾ : choix, clic sur la courbe : l'éditer\n"
            "• Ctrl+C / V / D · Ctrl+A · Suppr · F : tout afficher · Ctrl+L : organiser\n"
            "• Molette : zoom · clic milieu ou Alt+glisser : se déplacer · Alt en déplaçant un nœud : sans aimantation\n"
            "• Onglet Moteur : glisser un paramètre sur le graphe pour le piloter\n\n"
            "FICHIERS\n"
            "• Fichier › Nouveau · Ctrl+O ouvrir · Ctrl+S enregistrer · Ctrl+Maj+S enregistrer sous\n"
            "• .csbr brush · .csbl fusion · modules Existence : leur extension (.cspl palette, .csgr dégradé)\n"
            "• Ctrl+E exporter la ressource · Ctrl+Maj+P publier · Ctrl+1…5 : étapes"))

    # ── barre du haut ──
    def _topbar(self):
        bar = QFrame()
        bar.setObjectName("toolbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 8, 18, 8)
        logo = QLabel(f"✦ STELLAR<span style='color:{C['accent']}'>DUST</span>")
        logo.setTextFormat(Qt.TextFormat.RichText)
        logo.setStyleSheet("font-size:15px; font-weight:800; letter-spacing:2px;")
        row.addWidget(logo)
        self.doc_label = label("", "#C3D0EA", 11)
        row.addSpacing(10)
        row.addWidget(self.doc_label)
        row.addSpacing(18)
        self.steps_host = QWidget()
        self.steps_row = QHBoxLayout(self.steps_host)
        self.steps_row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.steps_host)
        row.addStretch()
        self.badge = QLabel()
        self.badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge.setToolTip("Voir les vérifications")
        self.badge.mousePressEvent = lambda _e: self._select_step(len(self.steps) - 1)
        row.addWidget(self.badge)
        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("Annuler (Ctrl+Z)")
        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("Rétablir (Ctrl+Maj+Z)")
        for b in (self.undo_btn, self.redo_btn):
            b.setObjectName("topButton")
            b.setFixedWidth(36)
            row.addWidget(b)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        save = QPushButton("Enregistrer")
        save.setObjectName("topButton")
        save.setToolTip("Ctrl+S")
        save.clicked.connect(self.save_document)
        row.addWidget(save)
        state = QLabel("◉ Existence" if self.resource_registry is not None else "○ Autonome")
        state.setToolTip("Connecté au registre Existence" if self.resource_registry is not None
                         else "Lancé seul : la publication est remplacée par l'export")
        state.setStyleSheet(f"color:{C['ok'] if self.resource_registry is not None else C['muted']}; padding-left:10px; font-size:11px;")
        row.addWidget(state)
        return bar

    def _build_steps(self):
        while self.steps_row.count():
            it = self.steps_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.step_buttons = {}
        for i, name in enumerate(self.steps):
            b = QPushButton(f"{i + 1}  {name}")
            b.setObjectName("workflowStep")
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, s=i: self._select_step(s))
            self.step_buttons[i] = b
            self.steps_row.addWidget(b)
            if i < len(self.steps) - 1:
                self.steps_row.addWidget(label("›", C["dim"], 14))

    # ── barre latérale ──
    def _build_sidebar(self):
        lay = self.sidebar_host.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        lay.addWidget(SectionTitle("Creators"))
        self.creator_buttons = {}
        for cid, spec in self.all_creators().items():
            b = QPushButton(f"{spec['icon']}  {spec['label']}")
            b.setProperty("active", cid == self.creator_id)
            if not self.creator_available(cid):
                b.setEnabled(False)
                b.setText(f"{spec['icon']}  {spec['label']} · non branché")
                b.setToolTip("Module Existence non branché sur StarDust.\nBranche-le sur StarDust dans la carte d'Existence.")
            else:
                b.setToolTip(f"{spec['description']}\nFichiers .{spec['ext']}")
            b.clicked.connect(lambda _=False, c=cid: self.set_creator(c))
            self.creator_buttons[cid] = b
            lay.addWidget(b)
        self.fusion_button = self.creator_buttons.get("blend")
        if self.spec.get("graph"):
            lay.addWidget(SectionTitle("Bibliothèque"))
            lay.addWidget(label("Clic : ajouter · glisser sur le graphe (ou sur une liaison pour l'insérer) · Tab : chercher",
                                C["dim"], 10, wrap=True))
            cat = None
            for t in PALETTE[self.creator_id]:
                nspec = NODE_TYPES[t]
                if nspec["category"] != cat:
                    cat = nspec["category"]
                    lay.addWidget(label(cat, C["muted"], 10))
                lay.addWidget(PaletteButton(t, self._add_graph_node))
            lay.addSpacing(6)
            tpl = QPushButton("✦  Modèle de départ")
            tpl.setObjectName("secondary")
            tpl.clicked.connect(self.load_template)
            lay.addWidget(tpl)
        else:
            m = self.spec.get("manifest", {})
            lay.addWidget(SectionTitle("Module"))
            lay.addWidget(label(f"{m.get('name', '')} v{m.get('version', '?')}\nFourni par Existence ({m.get('interface_protocol', '')})\n"
                                f"Produit : {m.get('produces', '')}\nFichiers : .{m.get('file_extension', '')}", C["muted"], 10, wrap=True))
        lay.addStretch()
        names = [self.all_creators()[k]["label"] for k, on in self.plugged.items() if on and k in self.all_creators()]
        if self.plugged.get("fusion_creator"):
            names.append("Fusion")
        lay.addWidget(label("Modules branchés : " + (", ".join(sorted(set(names))) if names else "aucun"), C["dim"], 10, wrap=True))

    def _page(self, title, subtitle, content, nav=None):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(22, 16, 22, 12)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label(title, "#F4F7FF", 20, True))
        col.addWidget(label(subtitle, C["muted"], 12, wrap=True))
        head.addLayout(col, 1)
        if nav is not None:
            head.addWidget(nav)
        lay.addLayout(head)
        lay.addSpacing(6)
        lay.addWidget(content, 1)
        return page

    def _nav(self, i):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        if i > 0:
            b = QPushButton(f"‹ {self.steps[i - 1]}")
            b.setObjectName("secondary")
            b.clicked.connect(lambda: self._select_step(i - 1))
            h.addWidget(b)
        if i < len(self.steps) - 1:
            b = QPushButton(f"{self.steps[i + 1]} ›")
            b.setObjectName("primary")
            b.clicked.connect(lambda: self._select_step(i + 1))
            h.addWidget(b)
        return box

    def _clear_ui(self):
        self.graph.setParent(None)
        while self.center.count():
            w = self.center.widget(0)
            self.center.removeWidget(w)
            w.deleteLater()
        while self.right_tabs.count():
            w = self.right_tabs.widget(0)
            self.right_tabs.removeTab(0)
            if w is not None:
                w.deleteLater()

    def _build_creator_ui(self):
        self._clear_ui()
        spec = self.spec
        self._build_steps()
        self._build_sidebar()
        self.iface = None
        self.fusion_bench = None
        self.preview = None
        self.mini_preview = None
        self.engine_editor = None
        self.parameter_panel = None
        self.native_module_surface = None
        self.preview_hint = None
        self.inspector_tab = None
        default_name = {"brush_engine": "Nouveau pinceau", "blend": "Nouveau mélange"}.get(self.creator_id, "Sans nom")
        if not spec.get("graph"):
            try:
                self.iface = load_creator_interface(spec["manifest"], self._host())
                default_name = getattr(self.iface, "default_name", default_name)
                self.iface.changed.connect(self._touch)
            except Exception as exc:  # noqa: BLE001
                self.iface = None
                self.toast(f"Interface du module indisponible : {exc}", 12000)
        self.definition_panel = DefinitionPanel(spec, default_name)
        self.definition_panel.changed.connect(self._touch)
        self.center.addWidget(self._page("Définition", f"{spec['label']} · {spec['description']}", self.definition_panel, self._nav(0)))
        if spec.get("graph"):
            self._build_graph_pages()
        else:
            self._build_module_pages()
        pub = QWidget()
        pl = QVBoxLayout(pub)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(SectionTitle("Vérifications"))
        self.issue_list = QListWidget()
        self.issue_list.setMaximumHeight(240)
        self.issue_list.itemDoubleClicked.connect(self._goto_issue)
        pl.addWidget(self.issue_list)
        self.summary = label("", "#C3D0EA", 12, wrap=True)
        pl.addWidget(self.summary)
        actions = QHBoxLayout()
        self.publish_btn = QPushButton("Publier dans Existence")
        self.publish_btn.setObjectName("primary")
        self.publish_btn.clicked.connect(self.publish)
        actions.addWidget(self.publish_btn)
        for text, fn in (("Enregistrer le fichier", self.save_document), ("Exporter la ressource…", self.export_resource)):
            b = QPushButton(text)
            b.setObjectName("secondary")
            b.clicked.connect(lambda _=False, f_=fn: f_())
            actions.addWidget(b)
        actions.addStretch()
        pl.addLayout(actions)
        pl.addStretch()
        last = len(self.steps) - 1
        self.center.addWidget(self._page("Publication", "Vérifie, puis publie ou exporte une nouvelle version.", pub, self._nav(last)))
        self.resources = ResourceDock(self.resource_registry, spec["kind"], self._payload, spec["module"] or "brush_engine_creator")
        self.right_tabs.addTab(self.resources, "Ressources")
        self.publish_btn.setText("Publier dans les Ressources")
        self.publish_btn.setToolTip("Dépose l'outil dans la bibliothèque centrale d'Existence : "
                                    "il devient utilisable dans toutes les applications étiquetées.")
        if spec.get("graph"):
            self.core_label.setText("Moteur natif ✓" if self.core is not None else "Moteur natif absent · secours")
        else:
            self.core_label.setText(f"Module {spec['manifest'].get('name', '')} {'✓' if self.iface else '✕'}")
        self._apply_creator_state(self.state_all.get("creators", {}).get(self.creator_id))
        history = getattr(self.iface, "history", None)
        if history is not None:
            history.reset()
        self._update_history_buttons()
        self._refresh_file_menus()

    def _build_graph_pages(self):
        blend = self.creator_id == "blend"
        self.graph.creator_id = self.creator_id
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        for text, tip, fn in (("＋ Nœud", "Tab / Espace", lambda: self.graph.open_search(self.graph.viewport().rect().center())),
                              ("Organiser", "Ctrl+L", self.graph.auto_layout), ("Tout afficher", "F", self.graph.fit),
                              ("−", "Zoom arrière", lambda: self.graph.zoom(1 / 1.2)), ("+", "Zoom avant", lambda: self.graph.zoom(1.2))):
            b = QPushButton(text)
            b.setObjectName("secondary")
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f_=fn: f_())
            tools.addWidget(b)
        tools.addStretch()
        self.graph_status = label("", C["muted"], 11)
        tools.addWidget(self.graph_status)
        wl.addLayout(tools)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.graph)
        if not blend:
            side = QWidget()
            sl = QVBoxLayout(side)
            sl.setContentsMargins(8, 0, 0, 0)
            head = QHBoxLayout()
            head.addWidget(label("ESSAI DIRECT", C["muted"], 10, True))
            head.addStretch()
            clr = QPushButton("Effacer")
            clr.setObjectName("secondary")
            head.addWidget(clr)
            sl.addLayout(head)
            self.mini_preview = LivePreview(self.creator_id, compact=True)
            clr.clicked.connect(self.mini_preview.clear)
            sl.addWidget(self.mini_preview, 1)
            sl.addWidget(label("Pendant que tu dessines, les vumètres jaunes des nœuds montrent le signal.", C["dim"], 10, wrap=True))
            split.addWidget(side)
            split.setSizes([900, 280])
        wl.addWidget(split, 1)
        self.center.addWidget(self._page("Construction", "Relie des signaux à une Sortie. Réglages principaux sur les nœuds, le reste dans l'onglet Nœud.",
                                         wrap, self._nav(1)))
        self.parameter_panel = ParameterOrganizationPanel(self.creator_id)
        self.parameter_panel.changed.connect(self._touch)
        self.center.addWidget(self._page("Paramètres exposés", "Ce que l'utilisateur final pourra modifier.", self.parameter_panel, self._nav(2)))
        test = QWidget()
        tl = QVBoxLayout(test)
        tl.setContentsMargins(0, 0, 0, 0)
        self.preview = LivePreview(self.creator_id)
        if blend:
            self.fusion_bench = FusionTestBench(self)
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
            sim.toggled.connect(self._set_simulated)
            bg = QCheckBox("Fond clair")
            bg.toggled.connect(self._toggle_bg)
            for w in (clear, color, sim, bg):
                bar.addWidget(w)
            bar.addStretch()
            self.preview_hint = label("", C["warn"], 11)
            bar.addWidget(self.preview_hint)
            tl.addLayout(bar)
            tl.addWidget(self.preview, 1)
        self.center.addWidget(self._page("Test", "Essaie l'outil en conditions réelles.", test, self._nav(3)))
        for p in (self.preview, self.mini_preview):
            if p is not None:
                p.settings_provider = self._compiled
                p.on_values = self._on_live_values
        self.inspector = Inspector(self.creator_id)
        self.inspector.node_parameter_changed.connect(lambda n, k, v: self.graph.set_node_parameter(n, k, v))
        self.inspector.node_renamed.connect(lambda n, t: self.graph.rename_node(n, t))
        self.inspector_tab = self._scroll(self.inspector)
        self.right_tabs.addTab(self.inspector_tab, "Nœud")
        self.engine_editor = CapabilityEditor(self.creator_id)
        self.engine_editor.changed.connect(self._touch)
        self.engine_editor.link_requested.connect(self.link_engine_param)
        self.inspector.capability_editor = self.engine_editor
        self.right_tabs.addTab(self.engine_editor, "Moteur")
        self.native_module_surface = self._native_module_surface(self.creator_id)
        if self.native_module_surface is not None:
            self.right_tabs.addTab(self.native_module_surface, "Module")

    def _build_module_pages(self):
        if self.iface is None:
            err = label("L'interface de ce module n'a pas pu être chargée depuis Existence.\n"
                        "Vérifie que Existence est à jour (modules/<module>/interface.py).", C["err"], 12, wrap=True)
            self.center.addWidget(self._page("Édition", "", err, self._nav(1)))
            self.center.addWidget(self._page("Test", "", QWidget(), self._nav(2)))
            return
        name = self.spec["manifest"].get("name", "")
        self.center.addWidget(self._page("Édition", f"Interface fournie par le module Existence « {name} ».",
                                         self.iface.edit_widget(), self._nav(1)))
        test = self.iface.test_widget() if hasattr(self.iface, "test_widget") else None
        self.center.addWidget(self._page("Test", "Aperçu du résultat.", test or label("Ce module n'a pas d'aperçu.", C["muted"], 12),
                                         self._nav(2)))

    @staticmethod
    def _scroll(w):
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QFrame.Shape.NoFrame)
        s.setWidget(w)
        return s

    # ── navigation ──
    def _select_step(self, step):
        step = max(0, min(int(step), len(self.steps) - 1))
        self.step = step
        self.center.setCurrentIndex(step)
        for i, b in getattr(self, "step_buttons", {}).items():
            b.setProperty("activeStep", i == step)
            b.style().unpolish(b)
            b.style().polish(b)
        name = self.steps[step]
        if name == "Construction":
            self.graph.setFocus()
            if not self._fitted:
                self._fitted = True
                QTimer.singleShot(30, self.graph.fit)
        if name == "Test" and self.fusion_bench:
            self.fusion_bench.apply_graph(self._compiled())
        if name == "Publication":
            self._revalidate()

    def _set_view(self, view):   # compat
        mapping = {"Graphe de conception": "Construction", "Prévisualisation": "Test", "Validation": "Publication", "Paramètres": "Paramètres"}
        name = mapping.get(view, "Construction")
        if name in self.steps:
            self._select_step(self.steps.index(name))

    def _select_creation_step(self, step):  # compat
        self._select_step(step)

    def undo(self):
        if self.spec.get("graph"):
            self.graph.undo()
        elif self.iface is not None:
            self.iface.undo()
        self._update_history_buttons()

    def redo(self):
        if self.spec.get("graph"):
            self.graph.redo()
        elif self.iface is not None:
            self.iface.redo()
        self._update_history_buttons()

    def _update_history_buttons(self):
        if self.spec.get("graph"):
            self.undo_btn.setEnabled(bool(self.graph.undo_stack))
            self.redo_btn.setEnabled(bool(self.graph.redo_stack))
            return
        h = getattr(self.iface, "history", None)
        self.undo_btn.setEnabled(bool(h.undo_stack) if h is not None else self.iface is not None)
        self.redo_btn.setEnabled(bool(h.redo_stack) if h is not None else self.iface is not None)

    # ── graphe ──
    def _compiled(self):
        return compile_graph(self.engine_editor.snapshot() if self.engine_editor else {}, self.graph.model())

    def _refresh_drive_marks(self):
        self._update_history_buttons()
        if not self.spec.get("graph") or self.engine_editor is None:
            return
        compiled = self._compiled()
        try:
            self.engine_editor.mark_driven(compiled["driven"])
            if self.preview_hint is not None:
                self.preview_hint.setText("" if compiled["has_output"] else "Aucune Sortie : tous les nœuds sont appliqués")
        except RuntimeError:
            pass

    def _on_live_values(self, values):
        self.graph.set_live(values)
        try:
            self.inspector.set_marker(values)
        except (RuntimeError, AttributeError):
            pass

    def _set_simulated(self, on):
        for p in (self.preview, self.mini_preview):
            if p is not None:
                p.simulate_pressure = on

    def _add_graph_node(self, node_type="Input"):
        if self.steps[self.step] != "Construction":
            self._select_step(1)
        if self.graph.add_node(node_type) is None:
            self.toast("StarDustCore a refusé ce nœud")

    def _on_node_selected(self, node):
        try:
            self.inspector.show_node(node)
            if node is not None and self.inspector_tab is not None:
                self.right_tabs.setCurrentWidget(self.inspector_tab)
        except (RuntimeError, AttributeError):
            return

    def _on_curve_requested(self, node, key):
        self.inspector.show_node(node)
        if self.inspector_tab is not None:
            self.right_tabs.setCurrentWidget(self.inspector_tab)
        self.inspector.focus_curve(key)

    def _on_engine_dropped(self, key, pos):
        self._drop_pos = pos
        self.engine_editor.link_menu(key, QCursor.pos())

    def _on_node_parameter_changed(self, node, key, value):  # compat
        self.graph.set_node_parameter(node, key, value)

    def _delete_graph_node(self):  # compat
        if not self.graph.delete_selected():
            self.toast("Sélectionne un nœud ou une liaison")

    def _validate_graph(self):  # compat
        self._select_step(len(self.steps) - 1)

    def link_engine_param(self, key, how):
        """Crée et relie les nœuds qui pilotent un paramètre du moteur."""
        self._select_step(1)
        g = self.graph
        fields = engine_fields()
        g.push_undo()
        out = next((n for n in g.nodes if n.node_type == "Output"), None)
        drop, self._drop_pos = self._drop_pos, None
        anchor = drop if drop is not None else (out.pos() - QPointF(290, 0) if out else None)
        name = fields.get(key, {}).get("label", key)
        if how == "fixed":
            node = g.add_node("EngineParam", anchor, {"key": key, "value": self.engine_editor.values.get(key, fields.get(key, {}).get("default", 0.0))},
                              f"Fixe {name}", record=False)
        else:
            inp = next((n for n in g.nodes if n.node_type == "Input" and n.config.get("source") == how), None)
            if inp is None:
                inp = g.add_node("Input", (anchor - QPointF(290, 0)) if anchor is not None else None, {"source": how},
                                 {"pressure": "Pression", "velocity": "Vitesse", "tilt": "Inclinaison", "random": "Aléatoire"}[how], record=False)
            node = g.add_node("Dynamics", anchor + QPointF(0, 40) if anchor is not None else None, {"target": key},
                              f"{name} ← {inp.title if inp else how}", record=False)
            if node and inp:
                g.connect_pair(inp, node, record=False, quiet=True)
        if node is not None and out is not None:
            g.connect_pair(node, out, record=False, quiet=True)
        if node is not None:
            g.scene().clearSelection()
            node.setSelected(True)
            self.toast(f"Lié au graphe : {field_label(key)}")

    def load_template(self):
        if self.creator_id == "blend":
            nodes = [dict(id="input", type="Input", title="Calque", config={"source": "layer"}, x=0, y=0),
                     dict(id="input_2", type="Input", title="Masque", config={"source": "mask"}, x=0, y=176),
                     dict(id="combine", type="Combine", config={"op": "multiplier"}, x=272, y=64),
                     dict(id="blend", type="Blend", config={"mode": "multiply", "contribution": 0.8}, x=544, y=48),
                     dict(id="output", type="Output", config={"resource_type": "blend_definition"}, x=816, y=48)]
            edges = [("input", "combine"), ("input_2", "combine"), ("combine", "blend"), ("blend", "output")]
        else:
            nodes = [dict(id="input", type="Input", title="Pression", config={"source": "pressure", "curve": [[0, 0], [0.5, 0.25], [1, 1]]}, x=0, y=0),
                     dict(id="input_2", type="Input", title="Vitesse", config={"source": "velocity", "gain": 1.5}, x=0, y=192),
                     dict(id="dynamics", type="Dynamics", title="Taille ← pression", config={"target": "size", "min": 0.15, "max": 1.0}, x=288, y=0),
                     dict(id="condition", type="Condition", title="Si rapide", config={"test": "au-dessus", "a": 0.35, "soft": 0.1}, x=288, y=224),
                     dict(id="dynamics_2", type="Dynamics", title="Dispersion ← vitesse", config={"target": "scatter", "mode": "remplacer", "min": 0.0, "max": 0.35}, x=576, y=224),
                     dict(id="shape", type="Shape", title="Pointe ovale", config={"roundness": 0.55, "angle": 35.0, "spacing": 0.08, "hardness": 0.6}, x=576, y=0),
                     dict(id="output", type="Output", config={"resource_type": "brush_engine"}, x=864, y=96)]
            edges = [("input", "dynamics"), ("dynamics", "shape"), ("shape", "output"), ("input_2", "condition"),
                     ("condition", "dynamics_2"), ("dynamics_2", "output")]
        if self.graph.nodes:
            self.graph.push_undo()
        self.graph.rebuild((nodes, edges))
        self.graph.fit()
        self.graph._changed()
        self._select_step(1)
        self.toast("Modèle chargé · dessine dans « Essai direct » à droite (Ctrl+Z pour revenir)")

    def _pick_color(self):
        c = QColorDialog.getColor(self.preview.color, self, "Couleur de test")
        if c.isValid():
            for p in (self.preview, self.mini_preview):
                if p is not None:
                    p.color = c

    def _toggle_bg(self, light):
        self.preview.background = QColor("#F1EEE6" if light else "#141E36")
        if light and self.preview.color == QColor("#EAF0FF"):
            self.preview.color = QColor("#1B1B24")
        elif not light and self.preview.color == QColor("#1B1B24"):
            self.preview.color = QColor("#EAF0FF")
        self.preview.update()

    # ── validation / publication ──
    def _issues(self):
        defn = self.definition_panel.snapshot()
        if self.spec.get("graph"):
            native = self.graph.native_validate()
            native_errors = [] if native.get("ok") else [e for e in native.get("result", []) if isinstance(e, str) and "at least one node" not in e]
            issues = graph_issues(self.graph.model(), native_errors, defn)
            if self.fusion_bench and not self.fusion_bench.validate():
                issues.append(("error", "Le banc de test de fusion n'a pas de résultat", None))
            return issues
        issues = [] if defn["name"] else [("error", "L'outil n'a pas de nom (étape Définition)", None)]
        if self.iface is None:
            return issues + [("error", "Interface du module indisponible", None)]
        try:
            issues += [(lvl, msg, None) for lvl, msg in self.iface.validate()]
        except Exception as exc:  # noqa: BLE001
            issues.append(("error", f"Validation du module impossible : {exc}", None))
        return issues

    def _revalidate(self):
        if not hasattr(self, "issue_list"):
            return
        try:
            issues = self._issues()
            self.issue_list.clear()
        except RuntimeError:
            return
        self.issues = issues
        if self.spec.get("graph"):
            self.graph.mark_issues(issues)
        errors = [i for i in issues if i[0] == "error"]
        if not issues:
            it = QListWidgetItem("✓  Tout est bon · prêt à publier")
            it.setForeground(QColor(C["ok"]))
            self.issue_list.addItem(it)
        for level, text, nid in issues:
            it = QListWidgetItem(("✕  " if level == "error" else "⚠  ") + text + ("   (double-clic pour voir)" if nid else ""))
            it.setForeground(QColor(C["err"] if level == "error" else C["warn"]))
            it.setData(Qt.ItemDataRole.UserRole, nid)
            self.issue_list.addItem(it)
        style = "padding:5px 10px; border-radius:11px; font-size:10px; font-weight:700;"
        if errors:
            self.badge.setText(f"  ✕ {len(errors)} problème(s)  ")
            self.badge.setStyleSheet(f"color:{C['err']}; background:#3A1C25; {style}")
        elif issues:
            self.badge.setText(f"  ⚠ {len(issues)} avertissement(s)  ")
            self.badge.setStyleSheet(f"color:{C['warn']}; background:#3A2D18; {style}")
        else:
            self.badge.setText("  ✓ Prêt  ")
            self.badge.setStyleSheet(f"color:{C['ok']}; background:#123A30; {style}")
        name = self.definition_panel.snapshot()["name"] or "Sans nom"
        detail = ""
        if self.spec.get("graph"):
            nodes, edges = self.graph.model()
            detail = f"{len(nodes)} nœud(s), {len(edges)} liaison(s), {len(self.parameter_panel.snapshot())} paramètre(s) exposé(s)"
            try:
                self.graph_status.setText(f"{len(nodes)} nœud(s) · {len(edges)} liaison(s)")
            except (RuntimeError, AttributeError):
                pass
        self.summary.setText(f"<b>{name}</b> · {self.spec['kind']} · prochaine version v{self.resources.next_version(name)}<br>{detail}")
        self.publish_btn.setEnabled(not errors)

    def _goto_issue(self, item):
        nid = item.data(Qt.ItemDataRole.UserRole)
        if nid:
            self._select_step(1)
            self.graph.select_node(nid)
        elif "nom" in item.text():
            self._select_step(0)
            self.definition_panel.name.setFocus()
        elif not self.spec.get("graph"):
            self._select_step(1)

    def _payload(self):
        payload = {"tool_definition": self.definition_panel.snapshot()}
        if self.spec.get("graph"):
            payload.update({"parameters": self.engine_editor.snapshot(), "graph": self.graph.native_snapshot(),
                            "exposed_parameters": self.parameter_panel.snapshot()})
            if self.fusion_bench:
                payload["test_bench"] = self.fusion_bench.snapshot()
        elif self.iface is not None:
            payload.update(self.iface.resource_payload())
        return payload

    def publish(self):
        self._revalidate()
        if any(i[0] == "error" for i in self.issues):
            self.toast("Publication bloquée : corrige les erreurs listées")
            self._select_step(len(self.steps) - 1)
            return
        defn = self.definition_panel.snapshot()
        written = self.send_to_library(quiet=True)
        ok, msg = self.resources.publish(defn["name"], defn["compatibility"])
        if written:
            apps = sorted({a for e in written for a in e["apps"]})
            version = max(int(e.get("version", 1)) for e in written)
            self.resources.add_resource(Resource(defn["name"], self.spec["kind"], "Dans les Ressources",
                                                 version, ", ".join(apps), written[0]["uri"]))
            msg = (f"Publié dans les Ressources (v{version}) · utilisable dans : {', '.join(apps)}"
                   + ("" if ok or self.resource_registry is None else f" — registre Existence : {msg}"))
        self.toast(msg)
        if ok or written:
            self.right_tabs.setCurrentWidget(self.resources)
            self.save_timer.start()
            self._revalidate()

    def export_resource(self):
        self._revalidate()
        name = self.definition_panel.snapshot()["name"] or "Sans nom"
        payload = {"protocol": "existence.resource.v1", "namespace": "resource://existence/stardust", "kind": self.spec["kind"],
                   "name": name, "created_at": datetime.now().isoformat(timespec="seconds"), "id": str(uuid.uuid4()),
                   "metadata": self.resources.metadata(name)}
        slug = "-".join(name.lower().split()) or "ressource"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la ressource", str(Path.home() / f"{slug}.{self.spec['kind']}.json"),
                                              "Ressource Existence (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError as exc:
            self.toast(f"Export impossible : {exc}")
            return
        self.resources.add_resource(Resource(name, self.spec["kind"], "Exporté", self.resources.next_version(name), "", f"file://{path}"))
        self.save_timer.start()
        written = self.send_to_library(quiet=True)
        where = f" · et ajouté aux Ressources ({', '.join(sorted({a for e in written for a in e['apps']}))})" if written else ""
        self.toast(f"Exporté → {path}{where}")

    # ── documents ──
    def _document(self):
        doc = {"format": DOC_FORMAT, "version": 1, "creator": self.creator_id, "module": self.spec["module"],
               "resource_kind": self.spec["kind"], "extension": self.spec["ext"], "app_build": STARDUST_BUILD_ID,
               "saved_at": datetime.now().isoformat(timespec="seconds"),
               "definition": self.definition_panel.snapshot(), "content": self._content()}
        if self.creator_id == "brush_engine":
            # Nebula sait ouvrir ce .csbr directement comme pinceau.
            doc["exports"] = {"nebula_brush_preset": self._nebula_preset()}
        return doc

    def _nebula_preset(self):
        name = self.definition_panel.snapshot()["name"] or "Pinceau StarDust"
        return nebula_brush_preset(self.engine_editor.snapshot() if self.engine_editor else {}, self.graph.model(), name)

    def _library_items(self):
        """(type, nom, contenu, apps, extension) à déposer dans la bibliothèque centrale."""
        name = self.definition_panel.snapshot()["name"] or "Sans nom"
        doc = self._document()
        if self.creator_id == "brush_engine":
            return [("brush_engines", name, doc, ["stardust", "nebula"], ".csbr"),
                    ("brushes", name, doc["exports"]["nebula_brush_preset"], ["nebula"], ".json")]
        if self.creator_id == "blend":
            return [("blends", name, doc, ["stardust", "nebula"], ".csbl")]
        items = []
        exporter = getattr(self.iface, "library_export", None)
        if callable(exporter):
            try:
                kind, payload, apps = exporter(name)
                items.append((kind, name, payload, list(apps), ".json"))
            except Exception:  # noqa: BLE001
                pass
        if not items:
            items.append((self.spec["kind"] + "s", name, doc, ["stardust"], f".{self.spec['ext']}"))
        return items

    def send_to_library(self, quiet=False):
        """Dépose l'outil dans la bibliothèque centrale : utilisable partout où il est étiqueté."""
        library = shared_library()
        if library is None:
            if not quiet:
                self.toast("Bibliothèque centrale introuvable (Existence absent)")
            return []
        written = []
        for kind, name, payload, apps, suffix in self._library_items():
            try:
                entry = library.add_json(kind, name, payload, apps=apps, owner="stardust", suffix=suffix)
                written.append(entry)
            except (OSError, ValueError) as exc:
                self.toast(f"Bibliothèque : échec pour {kind} ({exc})")
        if written and not quiet:
            apps = sorted({a for e in written for a in e["apps"]})
            self.toast(f"Ajouté aux Ressources · utilisable dans : {', '.join(apps)}")
        return written

    def _confirm_discard(self):
        if not self._dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Modifications non enregistrées")
        box.setText(f"Enregistrer « {self.definition_panel.snapshot()['name'] or 'sans titre'} » dans un fichier avant de continuer ?")
        box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        choice = box.exec()
        if choice == QMessageBox.StandardButton.Save:
            return self.save_document()
        return choice == QMessageBox.StandardButton.Discard

    def _remember(self, path):
        recent = [str(path)] + [p for p in self.state_all.get("recent", []) if p != str(path)]
        self.state_all["recent"] = recent[:10]
        self._refresh_file_menus()

    def save_document(self, as_new=False):
        path = self.doc_path
        if as_new or path is None or path.suffix.lstrip(".") != self.spec["ext"]:
            name = self.definition_panel.snapshot()["name"] or "sans-titre"
            start = str((path.parent if path else Path.home()) / f"{'-'.join(name.lower().split())}.{self.spec['ext']}")
            chosen, _ = QFileDialog.getSaveFileName(self, "Enregistrer", start, f"{self.spec['label']} (*.{self.spec['ext']})")
            if not chosen:
                return False
            path = Path(chosen)
            if path.suffix.lstrip(".") != self.spec["ext"]:
                path = path.with_suffix(f".{self.spec['ext']}")
        try:
            path.write_text(json.dumps(self._document(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", str(exc))
            return False
        self.doc_path = path
        self._dirty = False
        self._remember(path)
        self._update_title()
        self.save_state()
        self.toast(f"Enregistré → {path}")
        return True

    def save_current(self):   # compat
        return self.save_document()

    def _extensions(self):
        return {spec["ext"]: cid for cid, spec in self.all_creators().items()}

    def open_document(self, path=None):
        if not self._confirm_discard():
            return
        if not path:
            exts = self._extensions()
            filt = "Documents StarDust (" + " ".join(f"*.{e}" for e in exts) + ")"
            path, _ = QFileDialog.getOpenFileName(self, "Ouvrir", str(self.doc_path.parent if self.doc_path else Path.home()), filt + ";;Tous (*)")
            if not path:
                return
        path = Path(path)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("format inattendu")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Ouverture impossible", f"{path.name} : {exc}")
            return
        cid = creator_mode(doc.get("creator") or self._extensions().get(path.suffix.lstrip("."), ""))
        if cid not in self.all_creators():
            QMessageBox.warning(self, "Type inconnu", f"Aucun Creator ne sait ouvrir {path.name}.\n"
                                "S'il vient d'un module Existence, vérifie que ce module est installé.")
            return
        if not self.creator_available(cid):
            QMessageBox.information(self, "Module non branché",
                                    f"{path.name} a été créé avec {self.all_creators()[cid]['label']}, qui n'est pas branché sur StarDust.\n"
                                    "Branche le module dans Existence puis réessaie.")
            return
        previous = (self.state_all.get("creators", {}).get(cid) or {}).get("resources", [])
        self._switch(cid, {"definition": doc.get("definition") or {}, "content": doc.get("content") or {},
                           "doc_path": str(path), "dirty": False, "resources": previous})
        self._remember(path)
        self.toast(f"Ouvert : {path.name}")

    def new_document(self, cid):
        if not self.creator_available(cid) or not self._confirm_discard():
            return
        self._switch(cid, {"definition": {}, "content": {}, "doc_path": "", "dirty": False})
        self._select_step(0)
        self.toast(f"Nouveau document {self.all_creators()[cid]['label']} (.{self.all_creators()[cid]['ext']})")

    def _switch(self, cid, data):
        """Change de Creator et/ou de document ; l'état de l'ancien est gardé en session."""
        self.save_timer.stop()
        self.save_state()
        if data is not None:
            self.state_all.setdefault("creators", {})[cid] = data
        if cid != self.creator_id:
            if self.core is not None:
                self.core.close()
            self.core = self._create_core(cid)
            self.graph.core = self.core
        self.creator_id = cid
        self.graph.undo_stack.clear()
        self.graph.redo_stack.clear()
        self._fitted = False
        self._build_creator_ui()
        self._select_step(min(self.step, len(self.steps) - 1))
        self.save_state()

    def set_creator(self, creator_id):
        cid = creator_mode(creator_id)
        if cid == self.creator_id:
            return
        if not self.creator_available(cid):
            self.toast("Ce module n'est pas branché sur StarDust (voir Existence)")
            return
        self._switch(cid, None)
        self.toast(f"{self.spec['label']} ouvert")

    # ── Existence ──
    def refresh_existence_creators(self, plugged: dict):
        """Appelé par Existence quand un module est branché ou débranché."""
        before = dict(self.plugged)
        self.plugged.update({k: bool(v) for k, v in (plugged or {}).items()})
        self.connected_creators["fusion_creator"] = self.plugged.get("fusion_creator", False)
        if self.module_registry is not None:
            for mid in self.plugged:
                m = self.module_registry.manifest(mid)
                if m is not None:
                    self.module_manifests[mid] = m.to_dict()
        if not self.creator_available(self.creator_id):
            self._switch("brush_engine", None)
        else:
            self._build_sidebar()
            self._refresh_file_menus()
        for mid, on in self.plugged.items():
            if before.get(mid) != on:
                self.toast(f"{self.module_manifests.get(mid, {}).get('name', mid)} {'branché' if on else 'débranché'}")

    def refresh_creator_connection(self, connected: bool):   # compat
        self.refresh_existence_creators({"fusion_creator": connected})

    def _refresh_creator_context(self):   # compat
        self._build_sidebar()

    @staticmethod
    def _create_core(creator_id):
        if StarDustCore is None or creator_id not in ("brush_engine", "blend"):
            return None
        try:
            return StarDustCore(creator_id)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return None

    def _native_module_surface(self, creator_id):
        if creator_id != "blend" or not self.plugged.get("fusion_creator"):
            return None
        try:
            root = str(NEBULA_ROOT)
            if root not in sys.path:
                sys.path.insert(0, root)
            from UI.docks.blend_creator_dock import BlendCreatorDock
            surface = BlendCreatorDock(self)
            surface.setWindowFlags(Qt.WindowType.Widget)
            return surface
        except Exception:  # noqa: BLE001
            return None

    def toast(self, message, ms=6000):
        if self.statusBar() is not None:
            self.statusBar().showMessage(message, ms)

    def closeEvent(self, event):
        self.save_timer.stop()
        self.save_state()   # la session est toujours conservée, même sans fichier
        if self.core is not None:
            self.core.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = StarDust()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        QTimer.singleShot(0, lambda: window.open_document(sys.argv[1]))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
