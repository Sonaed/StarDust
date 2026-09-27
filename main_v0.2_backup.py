from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QPainterPath, QLinearGradient, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QFormLayout,
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsTextItem,
    QGraphicsLineItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QStatusBar, QFileDialog,
    QTextEdit,
    QToolButton, QVBoxLayout, QWidget,
)

try:
    from core_bridge import StellarDustCore
except ImportError:
    StellarDustCore = None


ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "stardust_state.json"
STARDUST_BUILD_ID = "0.2.1-native-graph"
CREATIVE_CORE_ROOT = Path("/home/deanos/Documents/CreativeSysteme v1.0")

# Les identifiants d'Existence sont désormais canoniques. StellarDust garde
# seulement "blend" comme mode d'affichage interne pour ne pas mélanger le
# nom du module avec le type de ressource produit.
CREATOR_MODE_ALIASES = {
    "blend": "blend",
    "blend_creator": "blend",
    "blend-creator": "blend",
    "fusion_creator": "blend",
    "fusion-creator": "blend",
    "brush_engine": "brush_engine",
    "brush-engine": "brush_engine",
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


def discover_existence_modules() -> dict[str, bool]:
    """Découvre les modules disponibles lorsque StellarDust est autonome."""
    config = Path.home() / ".config" / "existence" / "apps.json"
    try:
        apps = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fusion_creator": False}
    fusion = next((item for item in apps if item.get("id") == "fusion_creator"), None)
    connected = bool(
        fusion
        and fusion.get("orbit_of") == "stardust"
        and fusion.get("app_kind") == "orbital_module"
        and fusion.get("availability_state", "available") == "available"
        and fusion.get("lifecycle_state", "available") != "closed"
    )
    return {"fusion_creator": connected}


def creative_core_capabilities() -> dict:
    """Read the canonical Creative Core schemas used by Nebula."""
    if not CREATIVE_CORE_ROOT.exists():
        return {"available": False, "brush": {}, "blend": {}}
    root = str(CREATIVE_CORE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from TOOLS.brush_settings_state import DEFAULT_BRUSH_SETTINGS
        from UI.docks.brush_settings_dialog import FLOAT_GROUPS, BOOL_GROUPS
        brush = {
            "settings": dict(DEFAULT_BRUSH_SETTINGS),
            "float_groups": {key: list(value) for key, value in FLOAT_GROUPS.items()},
            "bool_groups": {key: list(value) for key, value in BOOL_GROUPS.items()},
            "parameter_count": len(DEFAULT_BRUSH_SETTINGS),
            "backend": "CreativeCore / BrushEngine",
        }
        from DOCUMENTS.blend_graph import backend_capabilities
        blend = backend_capabilities()
        return {"available": True, "brush": brush, "blend": blend}
    except (ImportError, OSError, ValueError, TypeError) as exc:
        return {"available": False, "brush": {}, "blend": {}, "error": str(exc)}


class CapabilityEditor(QFrame):
    """Live editor built from Creative Core's actual parameter schema."""

    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        self.creator_id = creator_id
        self.schema = creative_core_capabilities()
        self.values = {}
        self.controls = {}
        self.setObjectName("capabilityEditor")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 5, 0, 5)
        title = QLabel("CAPACITÉS DU BACKEND")
        title.setStyleSheet("color:#7182A7; font-size:10px; font-weight:700;")
        root.addWidget(title)
        if not self.schema.get("available"):
            label = QLabel("Creative Core indisponible")
            label.setStyleSheet("color:#F5C56B;")
            root.addWidget(label)
            return
        if creator_id == "blend":
            self._build_blend(root)
        else:
            self._build_brush(root)

    def _build_brush(self, root):
        brush = self.schema["brush"]
        self.values = dict(brush["settings"])
        summary = QLabel(f"CreativeCore / BrushEngine · {brush['parameter_count']} paramètres canoniques")
        summary.setStyleSheet("color:#5CE1B9; font-size:11px;")
        root.addWidget(summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(280)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 6, 0)
        for group, fields in brush["float_groups"].items():
            header = QLabel(group)
            header.setStyleSheet("color:#C3D0EA; font-weight:700; padding-top:5px;")
            form.addRow(header)
            for key, label, minimum, maximum, step in fields:
                control = QDoubleSpinBox()
                control.setRange(float(minimum), float(maximum))
                control.setSingleStep(float(step))
                control.setDecimals(3)
                control.setValue(float(brush["settings"].get(key, minimum)))
                control.valueChanged.connect(lambda value, name=key: self.values.__setitem__(name, value))
                self.controls[key] = control
                self.values[key] = control.value()
                form.addRow(label, control)
            for key, label in brush["bool_groups"].get(group, []):
                control = QCheckBox()
                control.setChecked(bool(brush["settings"].get(key, False)))
                control.toggled.connect(lambda value, name=key: self.values.__setitem__(name, value))
                self.controls[key] = control
                self.values[key] = control.isChecked()
                form.addRow(label, control)
        scroll.setWidget(content)
        root.addWidget(scroll)

    def _build_blend(self, root):
        blend = self.schema["blend"]
        modes = blend.get("blend_modes", [])
        summary = QLabel(f"CreativeCore · {len(modes)} modes · {len(blend.get('channels', []))} canaux")
        summary.setStyleSheet("color:#5CE1B9; font-size:11px;")
        root.addWidget(summary)
        mode = QComboBox()
        mode.addItems(modes)
        mode.currentTextChanged.connect(lambda value: self.values.__setitem__("mode", value))
        self.values["mode"] = mode.currentText()
        root.addWidget(mode)
        channel = QComboBox()
        channel.addItems(blend.get("channels", ["RGB"]))
        channel.currentTextChanged.connect(lambda value: self.values.__setitem__("channel", value))
        self.values["channel"] = channel.currentText()
        root.addWidget(channel)

    def snapshot(self) -> dict:
        return dict(self.values)


@dataclass
class Resource:
    name: str
    kind: str
    status: str = "Brouillon"
    version: int = 1
    consumers: str = "Nebula, Atlas"

    @property
    def uri(self) -> str:
        slug = self.name.lower().replace(" ", "-")
        return f"resource://existence/stardust/{self.kind}/{slug}"


class NodeItem(QGraphicsEllipseItem):
    def __init__(self, node_id: str, node_type: str, title: str, subtitle: str, color: str, x: float, y: float):
        super().__init__(0, 0, 178, 78)
        self.node_id, self.node_type = node_id, node_type
        self.config = {}
        self.title_item = QGraphicsTextItem(title, self)
        self.title_item.setDefaultTextColor(QColor("#F4F7FF"))
        self.title_item.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.title_item.setPos(30, 13)
        self.subtitle_item = QGraphicsTextItem(subtitle, self)
        self.subtitle_item.setDefaultTextColor(QColor("#94A6C9"))
        self.subtitle_item.setFont(QFont("Inter", 8))
        self.subtitle_item.setPos(30, 39)
        self.title, self.subtitle, self.color = title, subtitle, color
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setBrush(QBrush(QColor("#182442")))
        self.setPen(QPen(QColor(color), 2))

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.setBrush(QBrush(QColor("#182442")))
        painter.setPen(QPen(QColor(self.color), 2.2))
        painter.drawRoundedRect(rect, 14, 14)
        painter.setPen(QPen(QColor(self.color), 4))
        painter.drawLine(16, 16, 16, 62)
        painter.setBrush(QBrush(QColor("#0B1224")))
        painter.setPen(QPen(QColor(self.color), 2))
        painter.drawEllipse(QPointF(0, 39), 6, 6)
        painter.drawEllipse(QPointF(178, 39), 6, 6)
        if self.isSelected():
            painter.setPen(QPen(QColor("#FFFFFF"), 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 17, 17)

class GraphView(QGraphicsView):
    node_selected = Signal(object)
    graph_changed = Signal(object)
    interaction_message = Signal(str)

    def __init__(self, creator_id="brush_engine", core=None):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setSceneRect(0, 0, 900, 680)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setStyleSheet("border: 0; background: #0B1224;")
        self.nodes: list[NodeItem] = []
        self.node_by_id = {}
        self.edges = []
        self.edge_items = []
        self.pending_connection = None
        self._pressed_node = None
        self._pressed_position = None
        self.creator_id = creator_id
        self.core = core
        self.scene().selectionChanged.connect(self.emit_selected_node)
        self.rebuild()

    def emit_selected_node(self):
        selected = self.scene().selectedItems()
        if selected and isinstance(selected[0], NodeItem):
            self.node_selected.emit(selected[0])

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        self._pressed_node = item if isinstance(item, NodeItem) else None
        self._pressed_position = event.position()
        super().mousePressEvent(event)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#0B1224"))
        painter.setPen(QPen(QColor("#111D36"), 1))
        step = 32
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        for x in range(left, int(rect.right()) + step, step):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()) + step, step):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
        if not self.nodes:
            painter.setPen(QColor("#7182A7"))
            painter.setFont(QFont("Inter", 14, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 130, 900, 30), Qt.AlignmentFlag.AlignCenter, "Atelier vide")
            painter.setFont(QFont("Inter", 10))
            painter.drawText(QRectF(0, 165, 900, 26), Qt.AlignmentFlag.AlignCenter, "Ajoute une entrée ou un composant pour commencer la construction")

    def _default_model(self):
        return [], []

    def rebuild(self, model=None):
        self.scene().clear()
        self.nodes = []
        self.node_by_id = {}
        self.edge_items = []
        if model is None:
            nodes, edges = self._default_model()
        else:
            nodes, edges = model
        self.edges = list(edges)
        for data in nodes:
            node = NodeItem(data["id"], data["type"], data["title"], data["subtitle"], data["color"], data["x"], data["y"])
            self.scene().addItem(node)
            self.nodes.append(node)
            self.node_by_id[node.node_id] = node
        self.refresh_edges()

    def refresh_edges(self):
        for item in self.edge_items:
            self.scene().removeItem(item)
        self.edge_items = []
        for source_id, target_id in self.edges:
            source, target = self.node_by_id.get(source_id), self.node_by_id.get(target_id)
            if source is None or target is None:
                continue
            start = source.pos() + QPointF(178, 39)
            end = target.pos() + QPointF(0, 39)
            line = QGraphicsLineItem(start.x(), start.y(), end.x(), end.y())
            line.setPen(QPen(QColor("#40527A"), 2))
            line.setZValue(-1)
            self.scene().addItem(line)
            self.edge_items.append(line)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.refresh_edges()
        item = self.itemAt(event.position().toPoint())
        if not isinstance(item, NodeItem) or self._pressed_node is not item:
            self._pressed_node = None
            return
        if self._pressed_position is not None and (event.position() - self._pressed_position).manhattanLength() > 6:
            self._pressed_node = None
            return
        if self.pending_connection is None:
            self.pending_connection = item
            item.setSelected(True)
            self.interaction_message.emit(f"Source sélectionnée : {item.title} · clique une cible")
        elif self.pending_connection is item:
            self.pending_connection = None
            self.interaction_message.emit("Sélection annulée")
        else:
            source = self.pending_connection
            self.pending_connection = None
            if self.connect_pair(source, item):
                self.interaction_message.emit(f"Connexion créée : {source.title} → {item.title}")
            else:
                self.interaction_message.emit("Connexion impossible : déjà présente ou invalide")
        self._pressed_node = None

    def connect_pair(self, source, target):
        edge = (source.node_id, target.node_id)
        if source is target or edge in self.edges:
            return False
        if self.core is not None:
            response = self.core.command("connect", **{"from": source.node_id, "to": target.node_id})
            if not response.get("ok"):
                return False
        self.edges.append(edge)
        self.refresh_edges()
        self.graph_changed.emit(self.model())
        return True

    def set_node_parameter(self, node, key, value):
        if node is None or node.node_id not in self.node_by_id:
            return False
        node.config[key] = value
        if self.core is not None:
            response = self.core.command("set_parameter", key=f"node.{node.node_id}.{key}", value=str(value))
            if not response.get("ok"):
                return False
        self.graph_changed.emit(self.model())
        return True

    def add_node(self, node_type):
        names = {"Input": "Input", "Dynamics": "Dynamics", "Shape": "Shape", "Blend": "Blend", "Mask": "Mask", "Condition": "Condition", "Output": "Output"}
        base = node_type.lower()
        index = 1
        node_id = base
        while node_id in self.node_by_id:
            index += 1
            node_id = f"{base}_{index}"
        if self.core is not None:
            response = self.core.command("add_node", id=node_id, type=node_type)
            if not response.get("ok"):
                return None
        x = 250 + (index % 3) * 70
        y = 100 + (index % 5) * 70
        color = "#C596FF" if node_type in {"Blend", "Shape", "Condition"} else "#6CC8FF"
        if node_type == "Output":
            color = "#5CE1B9"
        node = NodeItem(node_id, node_type, names.get(node_type, node_type), "Nouveau nœud · configurable", color, x, y)
        self.scene().addItem(node)
        self.nodes.append(node)
        self.node_by_id[node_id] = node
        self.graph_changed.emit(self.model())
        return node

    def connect_selected(self):
        selected = [item for item in self.scene().selectedItems() if isinstance(item, NodeItem)]
        if len(selected) != 2:
            return False
        source, target = selected[0], selected[1]
        return self.connect_pair(source, target)

    def auto_layout(self):
        columns = {}
        for node in self.nodes:
            column = 0
            for source, target in self.edges:
                if target == node.node_id:
                    column = max(column, columns.get(source, 0) + 1)
            columns[node.node_id] = column
        rows = {}
        for node in self.nodes:
            column = columns.get(node.node_id, 0)
            row = rows.get(column, 0)
            node.setPos(90 + column * 250, 130 + row * 105)
            rows[column] = row + 1
        self.refresh_edges()
        self.graph_changed.emit(self.model())

    def delete_selected(self):
        selected = [item for item in self.scene().selectedItems() if isinstance(item, NodeItem)]
        if not selected:
            return False
        for node in selected:
            if self.core is not None:
                response = self.core.command("remove_node", id=node.node_id)
                if not response.get("ok"):
                    continue
            self.edges = [edge for edge in self.edges if node.node_id not in edge]
            self.node_by_id.pop(node.node_id, None)
            self.nodes.remove(node)
            self.scene().removeItem(node)
        self.refresh_edges()
        self.graph_changed.emit(self.model())
        return True

    def model(self):
        nodes = [{"id": node.node_id, "type": node.node_type, "title": node.title, "subtitle": node.subtitle, "config": dict(node.config), "color": node.color, "x": node.pos().x(), "y": node.pos().y()} for node in self.nodes]
        return nodes, list(self.edges)

    def native_snapshot(self):
        if self.core is not None:
            response = self.core.command("snapshot")
            if response.get("ok"):
                return response.get("result", {})
        nodes, edges = self.model()
        return {"format": "StellarDustGraph", "version": 1, "creator": self.creator_id, "nodes": nodes, "connections": [{"from": a, "to": b} for a, b in edges]}

    def native_validate(self):
        if self.core is not None:
            return self.core.command("validate")
        return {"ok": True, "result": []}


class SectionTitle(QLabel):
    def __init__(self, text):
        super().__init__(text.upper())
        self.setStyleSheet("color:#7182A7; font-size:10px; font-weight:700; letter-spacing:1px; padding:8px 0 4px;")


class Inspector(QFrame):
    node_parameter_changed = Signal(object, str, object)

    def __init__(self, creator_id="brush_engine"):
        super().__init__()
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.addWidget(SectionTitle("Inspector"))
        self.title = QLabel("Fusion Creator" if creator_id == "blend" else "Brush Engine Creator")
        self.title.setStyleSheet("font-size:18px; font-weight:700; color:#F4F7FF;")
        layout.addWidget(self.title)
        self.meta = QLabel("Fusion avancée · v1.0 · non publié" if creator_id == "blend" else "Prototype · v0.8 · non publié")
        self.meta.setStyleSheet("color:#7F91B8; font-size:11px;")
        layout.addWidget(self.meta)
        layout.addSpacing(12)
        fields = [("Identifiant", "fusion.creator"), ("Entrées", "layer, mask, selection"), ("Sortie", "blend_definition")] if creator_id == "blend" else [("Identifiant", "brush-engine.creator"), ("Entrées", "pressure, tilt, velocity"), ("Sortie", "brush_engine")]
        for label, value in fields:
            layout.addWidget(SectionTitle(label))
            field = QLineEdit(value)
            field.setReadOnly(True)
            layout.addWidget(field)
        layout.addWidget(SectionTitle("Paramètres du nœud"))
        self.detail = QLabel("Sélectionne un nœud du graphe pour afficher ses propriétés.")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color:#94A6C9; line-height:1.4;")
        layout.addWidget(self.detail)
        layout.addWidget(SectionTitle("Propriétés du nœud"))
        self.node_editor = QWidget()
        self.node_editor_layout = QFormLayout(self.node_editor)
        self.node_editor_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.node_editor)
        layout.addWidget(SectionTitle("Paramètres exposés à l’utilisateur"))
        exposed = QHBoxLayout()
        exposed.setSpacing(3)
        for name in (["Taille", "Opacité", "Flow", "Espacement"] if creator_id != "blend" else ["Mode", "Canal", "Contribution"]):
            check = QCheckBox(name)
            check.setChecked(name in {"Taille", "Mode"})
            check.setStyleSheet("color:#C3D0EA; font-size:10px;")
            exposed.addWidget(check)
        layout.addLayout(exposed)
        layout.addWidget(SectionTitle("Paramètres internes du moteur"))
        self.capability_editor = CapabilityEditor(creator_id)
        layout.addWidget(self.capability_editor)
        self.slider_label = QLabel("Sensibilité     68%")
        self.slider_label.setStyleSheet("color:#D9E2F8; font-size:12px;")
        layout.addWidget(self.slider_label)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setValue(68)
        slider.valueChanged.connect(lambda v: self.slider_label.setText(f"Sensibilité     {v}%"))
        layout.addWidget(slider)
        layout.addStretch()
        validate = QPushButton("✓  Valider la configuration")
        validate.setObjectName("primary")
        layout.addWidget(validate)

    def show_node(self, node):
        self.detail.setText(f"{node.title}\n{node.subtitle}\n\nConnexion active · sorties compatibles détectées")
        while self.node_editor_layout.count():
            item = self.node_editor_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        identifier = QLabel(f"{node.node_type} · {node.node_id}")
        identifier.setStyleSheet("color:#5CE1B9; font-size:10px;")
        self.node_editor_layout.addRow(identifier)

        def add_number(key, label, value, minimum, maximum, step):
            control = QDoubleSpinBox()
            control.setRange(minimum, maximum)
            control.setSingleStep(step)
            control.setDecimals(3)
            control.setValue(float(node.config.get(key, value)))
            control.valueChanged.connect(lambda changed, k=key: self.node_parameter_changed.emit(node, k, changed))
            self.node_editor_layout.addRow(label, control)

        def add_choice(key, label, choices, value):
            control = QComboBox()
            control.addItems(choices)
            control.setCurrentText(str(node.config.get(key, value)))
            control.currentTextChanged.connect(lambda changed, k=key: self.node_parameter_changed.emit(node, k, changed))
            self.node_editor_layout.addRow(label, control)

        if node.node_type == "Input":
            add_choice("source", "Source", ["pointer", "pressure", "velocity", "tilt", "layer", "mask"], "pointer")
        elif node.node_type == "Dynamics":
            add_number("amount", "Intensité", 1.0, 0.0, 2.0, 0.01)
            add_choice("driving", "Piloté par", ["pressure", "velocity", "tilt", "random"], "pressure")
        elif node.node_type == "Shape":
            add_number("roundness", "Rondeur", 1.0, 0.01, 1.0, 0.01)
            add_number("spacing", "Espacement", 0.15, 0.001, 5.0, 0.01)
            add_number("angle", "Angle", 0.0, -360.0, 360.0, 1.0)
        elif node.node_type == "Blend":
            add_choice("mode", "Mode", ["normal", "multiply", "screen", "overlay", "darken", "lighten"], "normal")
            add_choice("channel", "Canal", ["RGB", "R", "G", "B", "Alpha"], "RGB")
            add_number("contribution", "Contribution", 1.0, 0.0, 1.0, 0.01)
        elif node.node_type == "Mask":
            add_number("amount", "Intensité", 1.0, 0.0, 1.0, 0.01)
            add_choice("source", "Source", ["layer", "selection", "texture", "curve"], "layer")
        elif node.node_type == "Output":
            add_choice("resource_type", "Produit", ["brush_engine", "blend_result", "effect", "resource"], "resource")
        else:
            add_number("value", "Valeur", 0.0, -1.0, 1.0, 0.01)


class ResourceDock(QFrame):
    resource_created = Signal(object)

    def __init__(self, resource_registry=None, creator_id="brush_engine", capability_provider=None, graph_provider=None, definition_provider=None, bench_provider=None):
        super().__init__()
        self.setObjectName("panel")
        self.resource_registry = resource_registry
        self.creator_id = creator_id
        self.capability_provider = capability_provider
        self.graph_provider = graph_provider
        self.definition_provider = definition_provider
        self.bench_provider = bench_provider
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        head = QHBoxLayout()
        head.addWidget(SectionTitle("Resource Dock"))
        head.addStretch()
        head.addWidget(QLabel("EXISTENCE  ↗"))
        layout.addLayout(head)
        label = QLabel("Ressources de l’atelier")
        label.setStyleSheet("font-size:16px; font-weight:700;")
        layout.addWidget(label)
        info = QLabel("Les sorties StellarDust deviennent des ressources versionnées et partageables dans Existence.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#94A6C9; font-size:11px;")
        layout.addWidget(info)
        used = QLabel("RESSOURCES UTILISÉES\nBrush tip   ✓   Texture   ✓   Curve   ✓   Mask   ✓")
        used.setStyleSheet("color:#AAB9D6; font-size:10px; padding:7px; background:#0E172B; border-radius:6px;")
        layout.addWidget(used)
        produced = QLabel("RESSOURCE PRODUITE")
        produced.setStyleSheet("color:#5CE1B9; font-size:10px; font-weight:700; padding-top:5px;")
        layout.addWidget(produced)
        self.list = QListWidget()
        self.list.setSpacing(4)
        samples = [Resource("Soft graphite", "brush_engine", "Publié", 3, "Nebula"), Resource("Ink pressure map", "brush_engine", "Brouillon", 1, "Nebula, Atlas"), Resource("Warm contrast", "blend_graph", "Synchronisé", 12, "Nebula, Cosmos")]
        if creator_id == "blend":
            samples = [Resource("Warm contrast", "blend_definition", "Brouillon", 1, "Nebula, Atlas"), Resource("Multiply shadows", "blend_definition", "Publié", 4, "Nebula"), Resource("Mask fusion", "blend_result", "Synchronisé", 2, "Nebula, Cosmos")]
        for r in samples:
            self.add_resource(r)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("+ Nouvelle ressource")
        add.clicked.connect(self.create_resource)
        add.setObjectName("secondary")
        row.addWidget(add)
        publish = QPushButton("Publier dans Existence")
        publish.setObjectName("primary")
        publish.clicked.connect(self.publish_selected)
        row.addWidget(publish)
        row.addStretch()
        layout.addLayout(row)

    def add_resource(self, resource):
        item = QListWidgetItem(f"{resource.name}\n{resource.kind} · v{resource.version} · {resource.status}")
        item.setData(Qt.ItemDataRole.UserRole, resource)
        self.list.addItem(item)

    def create_resource(self):
        resource = Resource("Untitled blend" if self.creator_id == "blend" else "Untitled brush engine", "blend_definition" if self.creator_id == "blend" else "brush_engine")
        self.add_resource(resource)
        self.resource_created.emit(resource)

    def publish_selected(self):
        item = self.list.currentItem()
        if item is None:
            item = self.list.item(0)
        if item is None:
            return
        resource = item.data(Qt.ItemDataRole.UserRole)
        if self.resource_registry is not None:
            metadata = {
                "name": resource.name,
                "creator": "fusion_creator" if self.creator_id == "blend" else "brush_engine_creator",
                "consumers": resource.consumers,
                "definition": {"nodes": 4, "validated": True},
            }
            if self.capability_provider is not None:
                metadata["parameters"] = self.capability_provider()
            if self.graph_provider is not None:
                graph = self.graph_provider()
                if isinstance(graph, dict):
                    metadata["graph"] = graph
                else:
                    nodes, edges = graph
                    metadata["graph"] = {"nodes": nodes, "edges": edges, "format": "StellarDustGraph", "version": 1}
            if self.definition_provider is not None:
                metadata["tool_definition"] = self.definition_provider()
            if self.bench_provider is not None:
                metadata["test_bench"] = self.bench_provider()
            stored = self.resource_registry.create("stardust", resource.kind, resource.name, metadata=metadata,
                                                   access={"read": ["*"], "write": ["stardust"], "reference": ["*"]})
            resource.status = "Publié dans Existence"
            resource.version = stored.get("version", 1)
            item.setText(f"{resource.name}\n{resource.kind} · v{resource.version} · {resource.status}")
            self.resource_created.emit(stored)


class LivePreview(QFrame):
    """Creator-specific test surface: a small real drawing area for brushes."""

    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        self.creator_id = creator_id
        self.stroke = []
        self.samples = []
        self.settings_provider = None
        self.setMinimumHeight(190)
        self.setObjectName("previewPanel")
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0E172B"))
        painter.setPen(QPen(QColor("#1D2B49"), 1))
        for x in range(0, self.width(), 32):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32):
            painter.drawLine(0, y, self.width(), y)
        painter.setPen(QColor("#7182A7"))
        painter.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        painter.drawText(16, 24, "LIVE PREVIEW")
        painter.setFont(QFont("Inter", 10))
        painter.setPen(QColor("#94A6C9"))
        hint = "Dessine ici pour tester le Brush Engine" if self.creator_id != "blend" else "Zone de test de fusion · aperçu du résultat"
        painter.drawText(16, 45, hint)
        if len(self.samples) > 1:
            for index in range(1, len(self.samples)):
                first, second, width, opacity = self.samples[index - 1], self.samples[index], self.samples[index][2], self.samples[index][3]
                color = QColor("#8C9EFF")
                color.setAlphaF(max(0.05, min(1.0, opacity)))
                painter.setPen(QPen(color, max(1.0, width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawLine(first[0], second[0])

    def mousePressEvent(self, event):
        if self.creator_id != "blend":
            self.stroke = [event.position()]
            settings = self.settings_provider() if self.settings_provider else {}
            pressure = max(0.15, min(1.0, 1.0 - event.position().y() / max(1, self.height())))
            self.samples = [(event.position(), pressure, float(settings.get("size", 10.0)) * pressure, float(settings.get("opacity", 1.0)))]
            self.update()

    def mouseMoveEvent(self, event):
        if self.stroke:
            self.stroke.append(event.position())
            settings = self.settings_provider() if self.settings_provider else {}
            pressure = max(0.15, min(1.0, 1.0 - event.position().y() / max(1, self.height())))
            previous = self.stroke[-2]
            velocity = ((event.position().x() - previous.x()) ** 2 + (event.position().y() - previous.y()) ** 2) ** 0.5
            size = float(settings.get("size", 10.0))
            size *= max(0.35, 1.0 - float(settings.get("velocitySize", 0.0)) * min(1.0, velocity / 45.0))
            self.samples.append((event.position(), pressure, size * pressure, float(settings.get("opacity", 1.0))))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.stroke:
            self.stroke.append(event.position())
            self.update()

    def clear(self):
        self.stroke.clear()
        self.samples.clear()
        self.update()


class DefinitionPanel(QFrame):
    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        self.setObjectName("modePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("DÉFINITION DE L’OUTIL")
        title.setStyleSheet("color:#7182A7; font-size:10px; font-weight:700; letter-spacing:1px;")
        layout.addWidget(title)
        self.name = QLineEdit("Blend Definition" if creator_id == "blend" else "Untitled Brush Engine")
        self.name.setPlaceholderText("Nom de la ressource")
        self.name.setStyleSheet("font-size:18px; padding:10px;")
        layout.addWidget(self.name)
        self.description = QTextEdit()
        self.description.setPlaceholderText("Décris ce que cet outil produit et dans quels univers il peut être utilisé…")
        self.description.setMaximumHeight(100)
        layout.addWidget(self.description)
        grid = QFormLayout()
        self.inputs = QLineEdit("layer, mask, selection" if creator_id == "blend" else "pointer, pressure, velocity, tilt")
        self.outputs = QLineEdit("blend_definition" if creator_id == "blend" else "brush_engine")
        self.compatibility = QLineEdit("Nebula · Atlas" if creator_id == "blend" else "Nebula")
        grid.addRow("Entrées", self.inputs)
        grid.addRow("Sortie", self.outputs)
        grid.addRow("Compatible avec", self.compatibility)
        layout.addLayout(grid)
        layout.addWidget(QLabel("Cette fiche décrit la ressource avant sa construction technique."))
        layout.addStretch()

    def snapshot(self):
        return {"name": self.name.text(), "description": self.description.toPlainText(), "inputs": self.inputs.text(), "outputs": self.outputs.text(), "compatibility": self.compatibility.text()}


class ParameterOrganizationPanel(QFrame):
    def __init__(self, creator_id="brush_engine", parent=None):
        super().__init__(parent)
        self.setObjectName("modePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("PARAMÈTRES EXPOSÉS")
        title.setStyleSheet("color:#7182A7; font-size:10px; font-weight:700; letter-spacing:1px;")
        layout.addWidget(title)
        intro = QLabel("Choisis les paramètres que l’utilisateur final pourra modifier. Les autres restent internes au moteur.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#94A6C9; font-size:12px;")
        layout.addWidget(intro)
        self.checks = {}
        names = ["Taille", "Opacité", "Flow", "Espacement", "Pression", "Vitesse", "Inclinaison"] if creator_id != "blend" else ["Mode de fusion", "Canal", "Contribution", "Masque", "Courbe"]
        for name in names:
            check = QCheckBox(name)
            check.setChecked(name in {"Taille", "Mode de fusion"})
            check.setStyleSheet("font-size:13px; color:#D9E2F8; padding:6px;")
            self.checks[name] = check
            layout.addWidget(check)
        layout.addStretch()

    def snapshot(self):
        return [name for name, check in self.checks.items() if check.isChecked()]


class FusionTestBench(QFrame):
    """Surface de test spécialisée de Fusion Creator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.image_a = self._sample_image(QColor("#E85D9E"), QColor("#6D5BEA"))
        self.image_b = self._sample_image(QColor("#F7C65D"), QColor("#22B8CF"))
        self.result = QImage()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        header = QHBoxLayout()
        title = QLabel("FUSION TEST BENCH")
        title.setStyleSheet("color:#F4F7FF;font-size:17px;font-weight:700;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("preuve fonctionnelle · blend_definition"))
        root.addLayout(header)
        description = QLabel("Teste la fusion sur deux entrées avant validation et publication.")
        description.setStyleSheet("color:#94A6C9;font-size:11px;")
        root.addWidget(description)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Mode"))
        self.mode = QComboBox()
        self.mode.addItems(["normal", "multiply", "screen", "overlay", "darken", "lighten"])
        self.mode.currentTextChanged.connect(self.render_result)
        controls.addWidget(self.mode)
        load_a = QPushButton("Charger A")
        load_a.clicked.connect(lambda: self._load_image("a"))
        controls.addWidget(load_a)
        load_b = QPushButton("Charger B")
        load_b.clicked.connect(lambda: self._load_image("b"))
        controls.addWidget(load_b)
        controls.addStretch()
        root.addLayout(controls)
        previews = QHBoxLayout()
        self.input_a = self._image_panel("IMAGE A")
        self.input_b = self._image_panel("IMAGE B")
        self.output = self._image_panel("RÉSULTAT")
        for panel, _ in (self.input_a, self.input_b, self.output):
            previews.addWidget(panel, 1)
        root.addLayout(previews, 1)
        self.status = QLabel()
        self.status.setStyleSheet("color:#5CE1B9;font-size:11px;")
        root.addWidget(self.status)
        self.render_result()

    @staticmethod
    def _sample_image(first: QColor, second: QColor) -> QImage:
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
    def _image_panel(title: str):
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        label = QLabel(title)
        label.setStyleSheet("color:#AAB9D6;font-size:10px;font-weight:700;")
        layout.addWidget(label)
        image = QLabel()
        image.setMinimumSize(220, 150)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setStyleSheet("background:#0B1224;border:1px solid #243251;border-radius:8px;")
        layout.addWidget(image, 1)
        return frame, image

    def _load_image(self, slot: str):
        path, _ = QFileDialog.getOpenFileName(self, "Charger une image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            return
        if slot == "a":
            self.image_a = image
        else:
            self.image_b = image
        self.render_result()

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
        painter.setCompositionMode(mode)
        painter.drawImage(0, 0, overlay)
        painter.end()
        self.result = result
        for image, panel in ((self.image_a, self.input_a[1]), (self.image_b, self.input_b[1]), (result, self.output[1])):
            panel.setPixmap(QPixmap.fromImage(image).scaled(panel.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                            Qt.TransformationMode.SmoothTransformation))
        self.status.setText(f"Résultat prêt · mode {self.mode.currentText()} · {result.width()}×{result.height()}")

    def validate(self) -> bool:
        valid = not self.result.isNull()
        self.status.setText("✓ Fusion valide · prête à publier" if valid else "Fusion invalide · résultat absent")
        return valid

    def snapshot(self) -> dict:
        return {
            "mode": self.mode.currentText(),
            "input_a": {"width": self.image_a.width(), "height": self.image_a.height()},
            "input_b": {"width": self.image_b.width(), "height": self.image_b.height()},
            "result": {"width": self.result.width(), "height": self.result.height(), "valid": not self.result.isNull()},
        }


class StellarDust(QMainWindow):
    def __init__(self, resource_registry=None, creator_id="brush_engine", connected_creators=None, module_manifests=None):
        super().__init__()
        creator_id = creator_mode(creator_id)
        self.setWindowTitle(f"StellarDust · Creation Universe · {STARDUST_BUILD_ID}")
        self.setProperty("stardustBuildId", STARDUST_BUILD_ID)
        self.resize(1480, 900)
        self.setMinimumSize(1100, 700)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.resource_registry = resource_registry
        self.creator_id = creator_id
        raw_connections = (dict(connected_creators)
                           if connected_creators is not None
                           else discover_existence_modules())
        self.connected_creators = {
            "fusion_creator": bool(
                raw_connections.get("fusion_creator", raw_connections.get("blend_creator", False))
            )
        }
        raw_manifests = dict(module_manifests or {})
        self.module_manifests = dict(raw_manifests)
        if "fusion_creator" not in self.module_manifests and "blend_creator" in raw_manifests:
            self.module_manifests["fusion_creator"] = raw_manifests["blend_creator"]
        self.connected_creators.setdefault("fusion_creator", False)
        self.creator_definitions = dict(CREATOR_DEFINITIONS)
        if self.creator_id == "blend" and not self.connected_creators["fusion_creator"]:
            self.creator_id = "brush_engine"
        self.core = self._create_core(self.creator_id)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.toolbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.sidebar())
        center = QVBoxLayout()
        center.setContentsMargins(24, 20, 24, 0)
        center.addLayout(self.workspace_header())
        center.addLayout(self.creation_steps())
        tabs = QHBoxLayout()
        self.view_buttons = {}
        for text in ["Graphe de conception", "Prévisualisation", "Validation"]:
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setChecked(text == "Graphe de conception")
            b.clicked.connect(lambda checked=False, view=text: self._set_view(view))
            self.view_buttons[text] = b
            tabs.addWidget(b)
        tabs.addStretch()
        zoom = QLabel("−   100%   +")
        zoom.setStyleSheet("color:#7182A7; font-size:12px;")
        tabs.addWidget(zoom)
        center.addLayout(tabs)
        self.graph_tools_host = QWidget()
        graph_tools = QHBoxLayout(self.graph_tools_host)
        graph_tools.setContentsMargins(0, 0, 0, 0)
        graph_tools.addWidget(QLabel("Ajouter :"))
        self.quick_node_buttons = []
        for node_type in ["Input", "Dynamics", "Shape", "Blend", "Mask", "Output"]:
            button = QPushButton(f"+ {node_type}")
            button.setObjectName("secondary")
            button.node_type = node_type
            button.clicked.connect(lambda checked=False, item=button: self._add_graph_node(item.node_type))
            graph_tools.addWidget(button)
            self.quick_node_buttons.append(button)
        delete_node = QPushButton("Supprimer")
        delete_node.setObjectName("secondary")
        graph_tools.addWidget(delete_node)
        auto_layout = QPushButton("Organiser")
        auto_layout.setObjectName("secondary")
        graph_tools.addWidget(auto_layout)
        self.graph_status = QLabel("Clique un nœud, puis un autre pour les relier")
        self.graph_status.setStyleSheet("color:#7182A7; font-size:11px;")
        graph_tools.addWidget(self.graph_status, 1)
        center.addWidget(self.graph_tools_host)
        self.graph = GraphView(self.creator_id, self.core)
        delete_node.clicked.connect(self._delete_graph_node)
        auto_layout.clicked.connect(self.graph.auto_layout)
        validate_graph = QPushButton("Vérifier")
        validate_graph.setObjectName("secondary")
        validate_graph.clicked.connect(self._validate_graph)
        graph_tools.addWidget(validate_graph)
        self.graph.interaction_message.connect(self.graph_status.setText)
        self.graph.graph_changed.connect(lambda model: self.graph_status.setText(f"Graphe modifié · {len(model[0])} nœud(s), {len(model[1])} liaison(s)"))
        workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        workspace_splitter.addWidget(self.graph)
        self.preview = LivePreview(self.creator_id)
        workspace_splitter.addWidget(self.preview)
        workspace_splitter.setSizes([520, 210])
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(workspace_splitter)
        self.definition_panel = DefinitionPanel(self.creator_id)
        self.parameter_panel = ParameterOrganizationPanel(self.creator_id)
        self.fusion_bench = FusionTestBench(self)
        self.workspace_stack.addWidget(self.definition_panel)
        self.workspace_stack.addWidget(self.parameter_panel)
        self.workspace_stack.addWidget(self.fusion_bench)
        self.workspace_stack.setCurrentIndex(0)
        self._restore_state()
        center.addWidget(self.workspace_stack, 1)
        body.addLayout(center, 1)
        right_panel = QWidget()
        right_panel.setMinimumWidth(360)
        right_panel.setMaximumWidth(460)
        right_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(0, 20, 20, 20)
        self.right_panel = right_panel
        self.right_layout = right
        self.inspector = Inspector(creator_id)
        self.preview.settings_provider = self.inspector.capability_editor.snapshot
        self.native_module_surface = self._native_module_surface(creator_id)
        if self.native_module_surface is not None:
            right.addWidget(self.native_module_surface, 2)
        right.addWidget(self.inspector, 1)
        self.resources = ResourceDock(resource_registry, self.creator_id, self.inspector.capability_editor.snapshot, self.graph.native_snapshot, lambda: {"definition": self.definition_panel.snapshot(), "exposed_parameters": self.parameter_panel.snapshot()}, self.fusion_bench.snapshot)
        right.addWidget(self.resources, 1)
        body.addWidget(right_panel)
        outer.addLayout(body, 1)
        self.graph.node_selected.connect(self.inspector.show_node)
        self.graph.graph_changed.connect(lambda _model: self.save_state())
        self.inspector.node_parameter_changed.connect(self._on_node_parameter_changed)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("StellarDustCore natif connecté" if self.core is not None else "StellarDustCore non compilé · interface de secours active")
        self.save_state()

    def _set_view(self, view):
        for name, button in self.view_buttons.items():
            button.setChecked(name == view)
        stage = {"Graphe de conception": 1, "Prévisualisation": 3, "Paramètres": 2}.get(view)
        if stage is not None:
            self._update_step_buttons(stage)
        if view == "Graphe de conception":
            self.workspace_stack.setCurrentIndex(0)
            self.graph.show()
            self.preview.show()
            self.graph_tools_host.show()
            self.statusBar().showMessage("Construction · le graphe décrit la logique de l’outil")
        elif view == "Prévisualisation":
            if self.creator_id == "blend":
                self.workspace_stack.setCurrentIndex(3)
                self.graph.hide()
                self.preview.hide()
                self.fusion_bench.show()
            else:
                self.workspace_stack.setCurrentIndex(0)
                self.graph.hide()
                self.preview.show()
            self.graph_tools_host.hide()
            self.statusBar().showMessage("Fusion Test Bench · compare les deux entrées" if self.creator_id == "blend" else "Test Bench · dessine dans la surface de test")
        elif view == "Validation":
            self.workspace_stack.setCurrentIndex(0)
            self.graph.show()
            self.preview.hide()
            self.graph_tools_host.show()
            self._validate_graph()
        else:
            self.workspace_stack.setCurrentIndex(2)
            self.graph.hide()
            self.preview.hide()
            self.graph_tools_host.hide()
            self.statusBar().showMessage("Paramètres · choisis ce qui sera exposé à l’utilisateur")

    def toolbar(self):
        bar = QFrame()
        bar.setObjectName("toolbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(22, 13, 22, 13)
        logo = QLabel("✦  STELLAR<span style='color:#8C9EFF'>DUST</span>")
        logo.setTextFormat(Qt.TextFormat.RichText)
        logo.setStyleSheet("font-size:15px; font-weight:800; letter-spacing:2px;")
        row.addWidget(logo)
        sep = QLabel("/  CREATION UNIVERSE")
        sep.setStyleSheet("color:#7182A7; font-size:11px;")
        row.addWidget(sep)
        row.addStretch()
        existence_state = "◉  Connecté à Existence" if self.resource_registry is not None else "○  Mode autonome"
        for text in ["⌘  Sauvegarder", "↗  Exporter", existence_state]:
            button = QPushButton(text)
            button.setObjectName("topButton")
            if "Sauvegarder" in text:
                button.clicked.connect(self.save_current)
            row.addWidget(button)
        return bar

    def sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(236)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(18, 20, 18, 20)
        layout.addWidget(SectionTitle("Atelier"))
        library_hint = QLabel("Bibliothèque de composants\nAjoute les briques qui composent ton outil.")
        library_hint.setWordWrap(True)
        library_hint.setStyleSheet("color:#8495BA; font-size:10px; padding:5px 0 8px;")
        layout.addWidget(library_hint)
        self.library_categories = {}
        for category, entries in [("Entrées", "Pinceau · Pression · Vitesse · Inclinaison"), ("Comportement", "Dynamics · Curve · Condition · Random"), ("Forme", "Shape · Texture · Tip"), ("Composition", "Blend · Mask · Mix"), ("Sorties", "Brush · Effect · Resource")]:
            category_label = QLabel(f"{category}\n{entries}")
            category_label.setWordWrap(True)
            category_label.setStyleSheet("color:#AAB9D6; font-size:10px; padding:5px 7px; background:#111B33; border-radius:6px;")
            layout.addWidget(category_label)
            self.library_categories[category] = category_label
        layout.addSpacing(8)
        fusion_label = "◌  Fusion Creator  ·  connecté" if self.connected_creators["fusion_creator"] else "◌  Fusion Creator  ·  non branché"
        self.fusion_button = None
        for text, active in [("⌂  Vue d’ensemble", False), ("◈  Brush Engine Creator", self.creator_id != "blend"), (fusion_label, self.creator_id == "blend"), ("＋  Ajouter un Creator", False)]:
            b = QPushButton(text)
            b.setProperty("active", active)
            if text.startswith("⌂"):
                b.clicked.connect(lambda: self.set_creator("brush_engine"))
            elif "Fusion Creator" in text and self.connected_creators["fusion_creator"]:
                b.clicked.connect(lambda: self.set_creator("blend"))
            elif "Fusion Creator" in text:
                b.setEnabled(False)
                b.setToolTip("Fusion Creator n’est pas branché sur StellarDust")
            if "Fusion Creator" in text:
                self.fusion_button = b
            elif "Brush Engine Creator" in text:
                b.clicked.connect(lambda: self.set_creator("brush_engine"))
            elif "Ajouter un Creator" in text:
                b.clicked.connect(lambda: self.statusBar().showMessage("Branche un module Existence pour l’ajouter à l’atelier"))
            layout.addWidget(b)
        layout.addSpacing(18)
        layout.addWidget(SectionTitle("Modules branchés"))
        fusion_manifest = self.module_manifests.get("fusion_creator", {})
        if self.connected_creators["fusion_creator"]:
            manifest_text = (
                f"✓ {fusion_manifest.get('name', 'Fusion Creator')}\n"
                f"v{fusion_manifest.get('version', '?')} · interface récupérée\n"
                f"sorties : {', '.join(fusion_manifest.get('emits', ['blend_definition']))}"
            )
        else:
            manifest_text = "○ Fusion Creator\nnon branché sur StellarDust"
        module_status = QLabel(manifest_text)
        self.module_status = module_status
        module_status.setWordWrap(True)
        module_status.setStyleSheet("color:#AAB9D6; font-size:11px; padding:9px 10px; background:#111B33; border-radius:8px;")
        layout.addWidget(module_status)
        layout.addSpacing(8)
        layout.addWidget(SectionTitle("Projet actuel"))
        project = QLabel("BRUSH ENGINE / ALPHA\n\nDernière modification\nà l’instant")
        self.project_label = project
        project.setStyleSheet("color:#AAB9D6; font-size:12px; padding:10px 12px; background:#111B33; border-radius:8px;")
        layout.addWidget(project)
        layout.addStretch()
        layout.addWidget(SectionTitle("Système"))
        layout.addWidget(QPushButton("▣  Resource Dock"))
        layout.addWidget(QPushButton("⚙  Préférences"))
        return side

    def workspace_header(self):
        row = QHBoxLayout()
        title = QVBoxLayout()
        h = QLabel("Fusion Creator" if self.creator_id == "blend" else "Brush Engine Creator")
        self.creator_title_label = h
        h.setStyleSheet("font-size:25px; font-weight:700; color:#F4F7FF;")
        title.addWidget(h)
        sub = QLabel("Concevoir les comportements de fusion utilisés par les univers créatifs" if self.creator_id == "blend" else "Concevoir les comportements et moteurs utilisés par les univers créatifs")
        self.creator_subtitle_label = sub
        sub.setStyleSheet("color:#8495BA; font-size:12px;")
        title.addWidget(sub)
        identity = QLabel("OUTIL EN COURS DE CRÉATION · ressource Existence")
        identity.setStyleSheet("color:#5CE1B9; font-size:10px; font-weight:700; letter-spacing:1px;")
        title.addWidget(identity)
        row.addLayout(title)
        row.addStretch()
        badge = QLabel("●  BROUILLON")
        badge.setStyleSheet("color:#F5C56B; background:#3A2D18; padding:7px 11px; border-radius:12px; font-size:10px; font-weight:700;")
        row.addWidget(badge)
        return row

    def creation_steps(self):
        row = QHBoxLayout()
        row.setSpacing(4)
        self.step_buttons = {}
        for index, label in enumerate(["① Définition", "② Construction", "③ Paramétrage", "④ Test", "⑤ Validation", "⑥ Publication"]):
            item = QPushButton(label)
            item.setObjectName("workflowStep")
            item.clicked.connect(lambda checked=False, step=index: self._select_creation_step(step))
            self.step_buttons[index] = item
            row.addWidget(item)
        row.addStretch()
        self._update_step_buttons(1)
        return row

    def _update_step_buttons(self, active):
        for index, button in getattr(self, "step_buttons", {}).items():
            button.setProperty("activeStep", index == active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _select_creation_step(self, step):
        self._update_step_buttons(step)
        if step == 0:
            self.workspace_stack.setCurrentIndex(1); self.graph_tools_host.hide()
            self.statusBar().showMessage("Définition · identité, description, entrées, sorties et compatibilité")
        elif step == 1:
            self._set_view("Graphe de conception")
        elif step == 2:
            self._set_view("Paramètres")
        elif step == 3:
            self._set_view("Prévisualisation")
        elif step == 4:
            self._validate_graph()
            self.workspace_stack.setCurrentIndex(0); self.graph.show(); self.preview.hide(); self.graph_tools_host.show()
        elif step == 5:
            self.save_current()
            self.statusBar().showMessage("Publication · la ressource est envoyée à Existence")

    def _add_graph_node(self, node_type="Input"):
        node = self.graph.add_node(node_type)
        if node is None:
            self.graph_status.setText("StellarDustCore a refusé ce nœud")
            return
        node.setSelected(True)
        self.graph_status.setText(f"Nœud ajouté : {node.title} · clique-le puis clique une cible")

    def _on_node_parameter_changed(self, node, key, value):
        if self.graph.set_node_parameter(node, key, value):
            self.graph_status.setText(f"{node.title} · {key} = {value}")

    def _delete_graph_node(self):
        if self.graph.delete_selected():
            self.graph_status.setText("Nœud supprimé · les liaisons associées ont été retirées")
        else:
            self.graph_status.setText("Sélectionne un nœud à supprimer")

    def _validate_graph(self):
        result = self.graph.native_validate()
        errors = result.get("result", [])
        bench_valid = self.fusion_bench.validate() if self.creator_id == "blend" else True
        if result.get("ok") and not errors:
            self.graph_status.setText("✓ Graphe valide · " + ("Fusion Test Bench valide · prêt à publier" if bench_valid else "Test Bench incomplet"))
        else:
            self.graph_status.setText("Graphe invalide · " + "; ".join(errors or ["erreur native"]))

    def set_creator(self, creator_id):
        creator_id = creator_mode(creator_id)
        if creator_id == self.creator_id:
            return
        if creator_id == "blend" and not self.connected_creators["fusion_creator"]:
            self.statusBar().showMessage("Fusion Creator n’est pas branché sur StellarDust")
            return
        self.creator_id = creator_id
        if self.core is not None:
            self.core.close()
        self.core = self._create_core(creator_id)
        self.graph.creator_id = creator_id
        self.graph.core = self.core
        self.graph.rebuild()
        self.preview.creator_id = creator_id
        self.preview.clear()
        self.workspace_stack.removeWidget(self.definition_panel)
        self.workspace_stack.removeWidget(self.parameter_panel)
        self.definition_panel.deleteLater()
        self.parameter_panel.deleteLater()
        self.definition_panel = DefinitionPanel(creator_id)
        self.parameter_panel = ParameterOrganizationPanel(creator_id)
        self.workspace_stack.addWidget(self.definition_panel)
        self.workspace_stack.addWidget(self.parameter_panel)
        while self.right_layout.count():
            item = self.right_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        # Creator switching keeps the same Existence session and registry.
        self.native_module_surface = self._native_module_surface(creator_id)
        if self.native_module_surface is not None:
            self.right_layout.addWidget(self.native_module_surface, 2)
        self.inspector = Inspector(creator_id)
        self.preview.settings_provider = self.inspector.capability_editor.snapshot
        self.resources = ResourceDock(self.resource_registry, creator_id, self.inspector.capability_editor.snapshot, self.graph.native_snapshot, lambda: {"definition": self.definition_panel.snapshot(), "exposed_parameters": self.parameter_panel.snapshot()}, self.fusion_bench.snapshot)
        self.graph.node_selected.connect(self.inspector.show_node)
        self.inspector.node_parameter_changed.connect(self._on_node_parameter_changed)
        self.right_layout.addWidget(self.inspector, 1)
        self.right_layout.addWidget(self.resources, 1)
        self._refresh_creator_context()
        if creator_id != "blend" and self.workspace_stack.currentIndex() == 3:
            self.workspace_stack.setCurrentIndex(0)
            self.graph.show()
            self.preview.show()
        self.statusBar().showMessage(f"{('Fusion Creator' if creator_id == 'blend' else 'Brush Engine Creator')} connecté à Existence")

    def _refresh_creator_context(self):
        blend = self.creator_id == "blend"
        definition = self.creator_definitions.get(
            "fusion_creator" if blend else "brush_engine",
            CREATOR_DEFINITIONS["brush_engine"],
        )
        if hasattr(self, "creator_title_label"):
            self.creator_title_label.setText(definition.label)
            self.creator_subtitle_label.setText(definition.description)
        if hasattr(self, "project_label"):
            self.project_label.setText(
                f"{definition.label.upper()} / ALPHA\n\nRessource produite\n{definition.output_kind}"
            )
        labels = {
            "Entrées": "Sources\nLayer · Mask · Selection" if blend else "Entrées\nPinceau · Pression · Vitesse · Inclinaison",
            "Comportement": "Logique\nCondition · Curve · Math · Random" if blend else "Comportement\nDynamics · Curve · Condition · Random",
            "Forme": "Transformations\nTransform · Combine · Channel" if blend else "Forme\nShape · Texture · Tip",
            "Composition": "Fusion\nBlend · Mask · Mix" if blend else "Composition\nBlend · Mask · Mix",
            "Sorties": "Sorties\nBlend result · Resource" if blend else "Sorties\nBrush · Effect · Resource",
        }
        for category, text in labels.items():
            if category in getattr(self, "library_categories", {}):
                self.library_categories[category].setText(f"{category}\n{text.split(chr(10), 1)[1]}")
        button_context = (
            [("+ Source", "Input"), ("+ Logic", "Condition"), ("+ Condition", "Condition"), ("+ Blend", "Blend"), ("+ Mask", "Mask"), ("+ Output", "Output")]
            if blend else
            [("+ Input", "Input"), ("+ Dynamics", "Dynamics"), ("+ Shape", "Shape"), ("+ Blend", "Blend"), ("+ Mask", "Mask"), ("+ Output", "Output")]
        )
        for button, (label, node_type) in zip(getattr(self, "quick_node_buttons", []), button_context):
            button.setText(label)
            button.node_type = node_type
        self.preview.creator_id = self.creator_id

    def refresh_creator_connection(self, connected: bool):
        """Apply an Existence orbit change to the live StellarDust UI."""
        self.connected_creators["fusion_creator"] = bool(connected)
        if self.fusion_button is not None:
            self.fusion_button.setEnabled(bool(connected))
            self.fusion_button.setText("◌  Fusion Creator  ·  connecté" if connected else "◌  Fusion Creator  ·  non branché")
            self.fusion_button.setToolTip("" if connected else "Fusion Creator n’est pas branché sur StellarDust")
        if hasattr(self, "module_status"):
            manifest = self.module_manifests.get("fusion_creator", {})
            self.module_status.setText(
                f"✓ {manifest.get('name', 'Fusion Creator')}\nv{manifest.get('version', '?')} · interface récupérée\nsorties : {', '.join(manifest.get('emits', ['blend_definition']))}"
                if connected else "○ Fusion Creator\nnon branché sur StellarDust"
            )
        if not connected and self.creator_id == "blend":
            self.set_creator("brush_engine")
        self.statusBar().showMessage("Fusion Creator connecté à StellarDust" if connected else "Fusion Creator débranché de StellarDust")

    @staticmethod
    def _create_core(creator_id):
        if StellarDustCore is None:
            return None
        try:
            return StellarDustCore(creator_id)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return None

    def _native_module_surface(self, creator_id):
        """Recover the real Creator UI when Existence has plugged the module."""
        if creator_id != "blend" or not self.connected_creators.get("fusion_creator"):
            return None
        try:
            root = str(CREATIVE_CORE_ROOT)
            if root not in sys.path:
                sys.path.insert(0, root)
            from UI.docks.blend_creator_dock import BlendCreatorDock
            surface = BlendCreatorDock(self)
            surface.setWindowFlags(Qt.WindowType.Widget)
            surface.setMinimumWidth(300)
            surface.setMaximumWidth(420)
            return surface
        except (ImportError, OSError, RuntimeError) as exc:
            self.statusBar().showMessage(f"Interface Fusion Creator indisponible : {exc}")
            return None

    def save_current(self):
        """Publie la ressource active dans le dock central d’Existence."""
        if self.creator_id == "blend" and not self.fusion_bench.validate():
            self.statusBar().showMessage("Publication bloquée · le Fusion Test Bench est incomplet")
            return
        if hasattr(self, "resources"):
            self.resources.publish_selected()

    def save_state(self):
        payload = {
            "application": "StellarDust",
            "state_version": 2,
            "creator": self.creator_id,
            "saved_at": datetime.now().isoformat(),
            "session_id": str(uuid.uuid4()),
            "graph": self.graph.native_snapshot() if hasattr(self, "graph") else {},
            "definition": self.definition_panel.snapshot() if hasattr(self, "definition_panel") else {},
            "parameters": self.parameter_panel.snapshot() if hasattr(self, "parameter_panel") else {},
            "fusion_test_bench": self.fusion_bench.snapshot() if hasattr(self, "fusion_bench") else {},
        }
        try:
            STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            # The host may expose the application directory as read-only.
            # The workspace remains usable; Existence can provide persistence later.
            self.statusBar().showMessage("Espace de travail prêt · sauvegarde locale indisponible")

    def _restore_state(self):
        """Recharge le graphe du creator courant sans avaler un état incompatible."""
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict) or payload.get("application") != "StellarDust":
            return
        if creator_mode(payload.get("creator", "")) != self.creator_id:
            return
        graph = payload.get("graph") or {}
        nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
        connections = graph.get("connections", []) if isinstance(graph, dict) else []
        if not isinstance(nodes, list) or not isinstance(connections, list):
            return
        model_nodes = [node for node in nodes if isinstance(node, dict) and node.get("id")]
        model_edges = [
            (edge.get("from"), edge.get("to"))
            for edge in connections
            if isinstance(edge, dict) and edge.get("from") and edge.get("to")
        ]
        if not model_nodes:
            return
        self.graph.rebuild((model_nodes, model_edges))
        # Le moteur natif est reconstruit avec le même modèle que la vue.
        if self.core is not None:
            for node in model_nodes:
                self.core.command("add_node", id=node["id"], type=node.get("type", "Input"))
                for key, value in (node.get("config") or {}).items():
                    self.core.command("set_parameter", key=f"node.{node['id']}.{key}", value=str(value))
            for source, target in model_edges:
                self.core.command("connect", **{"from": source, "to": target})
        bench = payload.get("fusion_test_bench") or {}
        if self.creator_id == "blend" and bench.get("mode"):
            index = self.fusion_bench.mode.findText(str(bench["mode"]))
            if index >= 0:
                self.fusion_bench.mode.setCurrentIndex(index)
        if hasattr(self, "graph_status"):
            self.graph_status.setText(f"Graphe restauré · {len(model_nodes)} nœud(s), {len(model_edges)} liaison(s)")

    def closeEvent(self, event):
        self.save_state()
        if self.core is not None:
            self.core.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        * { font-family: Inter, Arial; }
        #root { background:#0B1224; color:#EAF0FF; }
        #toolbar { background:#111A31; border-bottom:1px solid #243251; }
        #sidebar { background:#0E172B; border-right:1px solid #243251; }
        #panel { background:#111A31; border:1px solid #243251; border-radius:12px; }
        QPushButton, QToolButton { color:#A9B8D5; background:transparent; border:0; border-radius:7px; padding:9px 10px; text-align:left; font-size:12px; }
        QPushButton:hover, QToolButton:hover { background:#1A2947; color:#F4F7FF; }
        QPushButton[active="true"] { background:#24365B; color:#FFFFFF; }
        QPushButton[activeStep="true"] { background:#263862; color:#F4F7FF; border:1px solid #8C9EFF; }
        QPushButton[activeStep="false"] { background:#111B33; color:#7182A7; }
        #topButton { background:#182442; color:#C3D0EA; padding:7px 12px; margin-left:6px; }
        #primary { background:#7667E8; color:#FFFFFF; font-weight:700; text-align:center; padding:11px; }
        #secondary { background:#1A2947; color:#C9D5ED; text-align:center; }
        QLineEdit, QComboBox { background:#0B1224; border:1px solid #2A3A5A; border-radius:6px; color:#C7D4ED; padding:7px; font-size:11px; }
        QSlider::groove:horizontal { height:4px; background:#2A3A5A; }
        QSlider::handle:horizontal { width:12px; margin:-4px 0; border-radius:6px; background:#8C9EFF; }
        QListWidget { background:transparent; border:0; color:#AFC0DE; font-size:11px; }
        QListWidget::item { padding:8px; border-radius:6px; }
        QListWidget::item:selected { background:#1C2B4B; color:#FFFFFF; }
        QStatusBar { background:#111A31; color:#7182A7; border-top:1px solid #243251; font-size:10px; }
    """)
    window = StellarDust()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
