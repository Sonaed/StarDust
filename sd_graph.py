"""Éditeur de graphe de StellarDust : nœuds à contrôles intégrés, liaisons, inspecteur."""

from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QDrag, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGraphicsEllipseItem, QGraphicsItem,
    QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QSlider, QToolBox, QVBoxLayout, QWidget,
)

from sd_curves import CurveField, curve_path, normalize_curve
from sd_engine import NODE_TYPES, PALETTE, creative_core_capabilities, default_config, engine_fields, field_label
from sd_theme import C, label

MIME_NODE = "application/x-stardust-node"
MIME_ENGINE = "application/x-stardust-engine-key"
NODE_W, HEADER, ROW, CURVE_ROW = 212, 30, 22, 48
CTRL_X = 94
GRID = 16


# ─── Items ──────────────────────────────────────────────────────────────────
class PortItem(QGraphicsEllipseItem):
    def __init__(self, node, kind):
        super().__init__(-7, -7, 14, 14, node)
        self.node, self.kind = node, kind
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(2)
        self._style(False)
        self.setPos(NODE_W if kind == "out" else 0, HEADER / 2)
        self.setToolTip("Glisse vers un autre nœud pour relier" if kind == "out"
                        else "Entrée · accepte plusieurs liaisons · tire pour détacher")

    def _style(self, hot):
        self.setBrush(QBrush(QColor(self.node.color if hot else C["bg"])))
        self.setPen(QPen(QColor(self.node.color), 2))

    def hoverEnterEvent(self, e):
        self._style(True)
        self.setScale(1.35)

    def hoverLeaveEvent(self, e):
        self._style(False)
        self.setScale(1.0)


class NodeItem(QGraphicsRectItem):
    """Nœud avec ses réglages principaux modifiables directement dessus :
    glisser sur une barre = régler (Maj = précis), clic sur un choix = menu,
    clic sur un interrupteur = basculer, clic sur une courbe = l'éditer."""

    def __init__(self, node_id, node_type, title=None, config=None, x=0.0, y=0.0):
        node_type = node_type if node_type in NODE_TYPES else "Combine"
        spec = NODE_TYPES[node_type]
        rows = [p for p in spec["params"] if p[0] in spec.get("inline", [])]
        height = HEADER + sum(CURVE_ROW if p[2] == "curve" else ROW for p in rows) + 10
        super().__init__(0, 0, NODE_W, height)
        self.spec, self.rows = spec, rows
        self.node_id, self.node_type = node_id, node_type
        self.title = title or spec["label"]
        self.color = spec["color"]
        self.config = default_config(node_type)
        for k, v in (config or {}).items():
            self.config[k] = v
        if node_type == "Condition" and "threshold" in self.config:   # migration v0.3
            self.config["a"] = self.config.pop("threshold")
        for key, _l, kind, _d, _e in spec["params"]:
            if kind == "curve":
                self.config[key] = normalize_curve(self.config.get(key))
        self._fine = False
        self.edges: list = []
        self.issue = None
        self.live = None
        self._slider = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.in_port = PortItem(self, "in") if spec["ins"] else None
        self.out_port = PortItem(self, "out") if spec["outs"] else None
        self.setPos(x, y)
        self.setToolTip(spec["help"])

    # compat
    @property
    def subtitle(self):
        return self.spec["label"]

    def port_pos(self, kind):
        return self.pos() + QPointF(NODE_W if kind == "out" else 0, HEADER / 2)

    def gv(self):
        views = self.scene().views() if self.scene() else []
        return views[0] if views else None

    def row_rects(self):
        y = HEADER + 4
        out = []
        for p in self.rows:
            h = CURVE_ROW if p[2] == "curve" else ROW
            out.append((p, QRectF(CTRL_X, y + 3, NODE_W - CTRL_X - 12, h - 6), QRectF(10, y, CTRL_X - 14, h)))
            y += h
        return out

    def _field_for(self, param):
        """Plage effective d'un paramètre (nombre, ou valeur moteur dynamique)."""
        key, _l, kind, _d, extra = param
        if kind == "number":
            lo, hi, step = extra
            return "number", lo, hi, step
        if kind == "engine_value":
            f = engine_fields().get(self.config.get("key"), {})
            if f.get("kind") == "bool":
                return "bool", 0, 1, 1
            return "number", f.get("lo", 0.0), f.get("hi", 1.0), f.get("step", 0.01)
        return kind, 0, 1, 1

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.gv() is not None \
                and QApplication_snap():
            return QPointF(round(value.x() / GRID) * GRID, round(value.y() / GRID) * GRID)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.edges:
                edge.update_path()
        return super().itemChange(change, value)

    # ── rendu ──
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        sel = self.isSelected()
        painter.setPen(QPen(QColor("#FFFFFF" if sel else "#2A3A5E"), 2 if sel else 1))
        painter.setBrush(QColor("#152039"))
        painter.drawRoundedRect(r, 10, 10)
        head = QPainterPath()
        head.addRoundedRect(QRectF(0, 0, NODE_W, HEADER), 10, 10)
        head.addRect(QRectF(0, HEADER - 10, NODE_W, 10))
        col = QColor(self.color)
        col.setAlpha(60)
        painter.fillPath(head.simplified(), col)
        painter.setPen(QColor(self.color))
        painter.drawLine(QPointF(1, HEADER), QPointF(NODE_W - 1, HEADER))
        painter.setPen(QColor("#F4F7FF"))
        painter.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        painter.drawText(QRectF(14, 0, NODE_W - 60, HEADER), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(self.title, Qt.TextElideMode.ElideRight, NODE_W - 64))
        painter.setPen(QColor(self.color))
        painter.setFont(QFont("Inter", 6, QFont.Weight.Bold))
        painter.drawText(QRectF(NODE_W - 80, 0, 66, HEADER), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         self.spec["label"].upper())
        if self.live is not None:   # vumètre du signal pendant les tests
            painter.fillRect(QRectF(1, HEADER - 3, (NODE_W - 2) * max(0.0, min(1.0, self.live)), 3), QColor(C["warn"]))
        for param, ctrl, lab in self.row_rects():
            key, text, kind, _d, extra = param
            painter.setPen(QColor("#94A6C9"))
            painter.setFont(QFont("Inter", 8))
            painter.drawText(lab, Qt.AlignmentFlag.AlignVCenter, text)
            value = self.config.get(key)
            fkind, lo, hi, _step = self._field_for(param)
            if fkind == "number":
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    v = lo
                frac = (v - lo) / ((hi - lo) or 1.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#0B1224"))
                painter.drawRoundedRect(ctrl, 4, 4)
                fill = QColor(self.color)
                fill.setAlpha(150)
                painter.setBrush(fill)
                painter.drawRoundedRect(QRectF(ctrl.left(), ctrl.top(), max(3.0, ctrl.width() * max(0.0, min(1.0, frac))), ctrl.height()), 4, 4)
                painter.setPen(QColor("#FFFFFF"))
                painter.setFont(QFont("Inter", 8, QFont.Weight.Bold))
                painter.drawText(ctrl, Qt.AlignmentFlag.AlignCenter, f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}")
            elif fkind == "bool":
                on = bool(value)
                pill = QRectF(ctrl.right() - 30, ctrl.top() + 1, 28, ctrl.height() - 2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.color if on else "#2A3A5A"))
                painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
                painter.setBrush(QColor("#FFFFFF"))
                d = pill.height() - 4
                painter.drawEllipse(QRectF(pill.right() - d - 2 if on else pill.left() + 2, pill.top() + 2, d, d))
            elif fkind == "curve":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#0B1224"))
                painter.drawRoundedRect(ctrl, 4, 4)
                painter.setPen(QPen(QColor(self.color), 1.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(curve_path(value, ctrl.adjusted(3, 3, -3, -3), 32))
            else:   # choice / engine_key
                painter.setPen(QPen(QColor("#2A3A5A"), 1))
                painter.setBrush(QColor("#0B1224"))
                painter.drawRoundedRect(ctrl, 4, 4)
                text_v = engine_fields().get(value, {}).get("label", str(value)) if fkind == "engine_key" else str(value)
                painter.setPen(QColor("#DCE4F7"))
                painter.setFont(QFont("Inter", 8))
                fm = painter.fontMetrics()
                painter.drawText(ctrl.adjusted(6, 0, -14, 0), Qt.AlignmentFlag.AlignVCenter,
                                 fm.elidedText(text_v, Qt.TextElideMode.ElideRight, int(ctrl.width() - 20)))
                painter.setPen(QColor(C["muted"]))
                painter.drawText(ctrl.adjusted(0, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "▾")
        if self.issue:
            painter.setBrush(QColor(C["err"] if self.issue[0] == "error" else C["warn"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(NODE_W - 8, 8), 4, 4)

    # ── contrôles intégrés ──
    def _hit(self, pos):
        for param, ctrl, _lab in self.row_rects():
            if ctrl.adjusted(-2, -2, 2, 2).contains(pos):
                return param, ctrl
        return None, None

    def hoverMoveEvent(self, e):
        param, _ctrl = self._hit(e.pos())
        if param is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self._field_for(param)[0] == "number":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set(self, key, value):
        gv = self.gv()
        if gv is not None:
            gv.set_node_parameter(self, key, value)

    def _slider_value(self, x):
        param, ctrl, start_x, start_v = self._slider
        _k, lo, hi, step = self._field_for(param)
        if self._fine:
            v = start_v + (x - start_x) / ctrl.width() * (hi - lo) * 0.1
        else:
            v = lo + (x - ctrl.left()) / ctrl.width() * (hi - lo)
            v = round(v / step) * step if step else v
        return round(max(lo, min(hi, v)), 4)

    def mousePressEvent(self, e):
        param, ctrl = self._hit(e.pos())
        if param is None or e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return
        if not self.isSelected():
            if not (e.modifiers() & Qt.KeyboardModifier.ControlModifier) and self.scene():
                self.scene().clearSelection()
            self.setSelected(True)
        key = param[0]
        fkind = self._field_for(param)[0]
        e.accept()
        if fkind == "number":
            self._fine = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            try:
                start_v = float(self.config.get(key))
            except (TypeError, ValueError):
                start_v = 0.0
            self._slider = (param, ctrl, e.pos().x(), start_v)
            if not self._fine:
                self._set(key, self._slider_value(e.pos().x()))
        elif fkind == "bool":
            self._set(key, not bool(self.config.get(key)))
        elif fkind == "curve":
            gv = self.gv()
            if gv is not None:
                gv.curve_requested.emit(self, key)
        else:
            self._choice_menu(param, e.screenPos())

    def mouseMoveEvent(self, e):
        if self._slider is not None:
            self._set(self._slider[0][0], self._slider_value(e.pos().x()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._slider is not None:
            self._slider = None
            gv = self.gv()
            if gv is not None:
                gv._param_key = None
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        param, _ctrl = self._hit(e.pos())
        if param is not None and self._field_for(param)[0] == "number":   # double-clic = valeur par défaut
            if param[2] == "engine_value":
                default = engine_fields().get(self.config.get("key"), {}).get("default", 0.0)
            else:
                default = param[3]
            self._set(param[0], default)
            return
        super().mouseDoubleClickEvent(e)

    def _choice_menu(self, param, screen_pos):
        key, _t, kind, _d, extra = param
        menu = QMenu()
        current = self.config.get(key)
        if kind == "engine_key":
            groups = {}
            for fk, f in engine_fields().items():
                if extra == "float" and f["kind"] != "float":
                    continue
                groups.setdefault(f["group"], []).append((fk, f))
            for g, items in groups.items():
                sub = menu.addMenu(g)
                for fk, f in items:
                    act = sub.addAction(f["label"])
                    act.setCheckable(True)
                    act.setChecked(fk == current)
                    act.setData(fk)
        else:
            for choice in extra:
                act = menu.addAction(str(choice))
                act.setCheckable(True)
                act.setChecked(choice == current)
                act.setData(choice)
        chosen = menu.exec(screen_pos.toPoint() if hasattr(screen_pos, "toPoint") else screen_pos)
        if chosen is not None and chosen.data() is not None:
            self._set(key, chosen.data())
            if kind == "engine_key" and self.node_type == "EngineParam":
                self._set("value", engine_fields().get(chosen.data(), {}).get("default", 0.0))


def QApplication_snap():
    """Aimantation à la grille : désactivée en maintenant Alt."""
    from PySide6.QtWidgets import QApplication
    return not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)


class EdgeItem(QGraphicsPathItem):
    def __init__(self, source: NodeItem, target: NodeItem):
        super().__init__()
        self.source, self.target = source, target
        self._hover = False
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setToolTip("Clic : sélectionner · Suppr : retirer · dépose un nœud dessus pour l'insérer")
        source.edges.append(self)
        target.edges.append(self)
        self.update_path()

    def update_path(self):
        self.setPath(bezier(self.source.port_pos("out"), self.target.port_pos("in")))
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


# ─── Recherche rapide ──────────────────────────────────────────────────────
class NodeSearch(QFrame):
    """Palette de commandes (Tab / Espace) : taper pour trouver un nœud."""
    chosen = Signal(str)

    def __init__(self, types, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("panel")
        self.setFixedWidth(280)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Ajouter un nœud… (tape pour filtrer)")
        self.list = QListWidget()
        self.list.setMinimumHeight(240)
        lay.addWidget(self.edit)
        lay.addWidget(self.list)
        for t in types:
            spec = NODE_TYPES[t]
            it = QListWidgetItem(f"{spec['label']}   ·  {spec['category']}")
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setToolTip(spec["help"])
            it.setForeground(QColor(spec["color"]))
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._accept)
        self.list.itemActivated.connect(lambda _i: self._accept())
        self.edit.installEventFilter(self)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.Type.KeyPress and ev.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            rows = [i for i in range(self.list.count()) if not self.list.item(i).isHidden()]
            if rows:
                cur = self.list.currentRow()
                idx = rows.index(cur) if cur in rows else 0
                idx = max(0, min(len(rows) - 1, idx + (1 if ev.key() == Qt.Key.Key_Down else -1)))
                self.list.setCurrentRow(rows[idx])
            return True
        return super().eventFilter(obj, ev)

    def _filter(self, text):
        t = text.casefold()
        first = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            hide = bool(t) and t not in it.text().casefold() and t not in str(it.data(Qt.ItemDataRole.UserRole)).casefold()
            it.setHidden(hide)
            if not hide and first is None:
                first = i
        if first is not None:
            self.list.setCurrentRow(first)

    def _accept(self):
        it = self.list.currentItem()
        if it is not None and not it.isHidden():
            self.chosen.emit(it.data(Qt.ItemDataRole.UserRole))
        self.close()

    def popup(self, global_pos):
        self.move(global_pos)
        self.show()
        self.edit.setFocus()


# ─── Vue ────────────────────────────────────────────────────────────────────
class GraphView(QGraphicsView):
    node_selected = Signal(object)
    graph_changed = Signal(object)
    interaction_message = Signal(str)
    history_changed = Signal()
    curve_requested = Signal(object, str)
    engine_dropped = Signal(str, QPointF)

    def __init__(self, creator_id="brush_engine", core=None):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(-5000, -5000, 10000, 10000)
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
        self.clipboard = None
        self.undo_stack: list[str] = []
        self.redo_stack: list[str] = []
        self.scene().selectionChanged.connect(self.emit_selected_node)
        self.centerOn(300, 200)

    @property
    def edges(self):
        return [(e.source.node_id, e.target.node_id) for e in self.edge_items]

    def emit_selected_node(self):
        try:
            sel = [i for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        except RuntimeError:
            return
        self.node_selected.emit(sel[0] if len(sel) == 1 else None)

    # ── moteur natif ──
    def _core(self, command, **payload):
        if self.core is None:
            return {"ok": True, "result": True}
        try:
            return self.core.command(command, **payload)
        except Exception as exc:  # noqa: BLE001
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
                self._core("set_parameter", key=f"node.{n.node_id}.{k}", value=json.dumps(v) if isinstance(v, list) else str(v))
        for e in self.edge_items:
            self._core("connect", **{"from": e.source.node_id, "to": e.target.node_id})

    # ── modèle ──
    def model(self):
        nodes = [{"id": n.node_id, "type": n.node_type, "title": n.title, "config": json.loads(json.dumps(n.config)),
                  "x": round(n.pos().x(), 1), "y": round(n.pos().y(), 1)} for n in self.nodes]
        return nodes, self.edges

    def rebuild(self, model=None):
        self.scene().clearSelection()
        self.scene().clear()
        self.nodes, self.node_by_id, self.edge_items = [], {}, []
        nodes, edges = model if model is not None else ([], [])
        for i, data in enumerate(nodes or []):
            if not isinstance(data, dict) or not data.get("id") or str(data["id"]) in self.node_by_id:
                continue
            node = NodeItem(str(data["id"]), data.get("type") if data.get("type") in NODE_TYPES else "Combine",
                            data.get("title"), data.get("config") or {},
                            float(data.get("x", 80 + (i % 4) * 260)), float(data.get("y", 80 + (i // 4) * 160)))
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

    def _remove_edge_item(self, e):
        e.detach()
        if e in self.edge_items:
            self.edge_items.remove(e)
        self.scene().removeItem(e)

    def _changed(self):
        self.graph_changed.emit(self.model())

    # ── historique ──
    def push_undo(self):
        self.undo_stack.append(json.dumps(self.model()))
        del self.undo_stack[:-100]
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

    def redo(self):
        if not self.redo_stack:
            self.interaction_message.emit("Rien à rétablir")
            return
        self.undo_stack.append(json.dumps(self.model()))
        self._restore_json(self.redo_stack.pop())
        self.history_changed.emit()

    # ── opérations ──
    def _new_id(self, node_type):
        base, index = node_type.lower(), 1
        node_id = base
        while node_id in self.node_by_id:
            index += 1
            node_id = f"{base}_{index}"
        return node_id

    def add_node(self, node_type, pos: QPointF | None = None, config=None, title=None, record=True):
        if node_type not in NODE_TYPES:
            return None
        node_id = self._new_id(node_type)
        if not self._core("add_node", id=node_id, type=node_type).get("ok"):
            return None
        if record:
            self.push_undo()
        if pos is None:
            pos = self.mapToScene(self.viewport().rect().center()) - QPointF(NODE_W / 2, 40)
            while any((n.pos() - pos).manhattanLength() < 30 for n in self.nodes):
                pos += QPointF(32, 32)
        node = NodeItem(node_id, node_type, title, config, round(pos.x() / GRID) * GRID, round(pos.y() / GRID) * GRID)
        for k, v in node.config.items():
            self._core("set_parameter", key=f"node.{node_id}.{k}", value=json.dumps(v) if isinstance(v, list) else str(v))
        self.scene().addItem(node)
        self.nodes.append(node)
        self.node_by_id[node_id] = node
        self.scene().clearSelection()
        node.setSelected(True)
        self._changed()
        return node

    def _reaches(self, start, goal):
        stack, seen = [start], set()
        edges = self.edges
        while stack:
            cur = stack.pop()
            if cur == goal:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(t for s, t in edges if s == cur)
        return False

    def connect_pair(self, source, target, record=True, quiet=False):
        def msg(m):
            if not quiet:
                self.interaction_message.emit(m)
        if source is target or not source.out_port or not target.in_port:
            msg("Liaison impossible : relie une sortie (droite) à une entrée (gauche)")
            return False
        if (source.node_id, target.node_id) in self.edges:
            msg("Ces nœuds sont déjà reliés")
            return False
        if self._reaches(target.node_id, source.node_id):
            msg("Liaison refusée : elle créerait une boucle")
            return False
        if not self._core("connect", **{"from": source.node_id, "to": target.node_id}).get("ok"):
            msg("StellarDustCore a refusé la liaison")
            return False
        if record:
            self.push_undo()
        self._add_edge_item(source, target)
        msg(f"Relié : {source.title} → {target.title}")
        self._changed()
        return True

    def set_node_parameter(self, node, key, value):
        if node is None or node.node_id not in self.node_by_id:
            return False
        if self._param_key != (node.node_id, key):
            self.push_undo()
            self._param_key = (node.node_id, key)
        node.config[key] = value
        self._core("set_parameter", key=f"node.{node.node_id}.{key}", value=json.dumps(value) if isinstance(value, list) else str(value))
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
            self._remove_edge_item(e)
        for n in nodes:
            self.nodes.remove(n)
            self.node_by_id.pop(n.node_id, None)
            self.scene().removeItem(n)
        self.resync_core()
        self.interaction_message.emit(f"Supprimé : {len(nodes)} nœud(s), {len(doomed)} liaison(s)")
        self._changed()
        return True

    def copy_selected(self):
        nodes = [i for i in self.scene().selectedItems() if isinstance(i, NodeItem)]
        if not nodes:
            return False
        ids = {n.node_id for n in nodes}
        all_nodes, edges = self.model()
        self.clipboard = ([d for d in all_nodes if d["id"] in ids], [e for e in edges if e[0] in ids and e[1] in ids])
        self.interaction_message.emit(f"{len(nodes)} nœud(s) copié(s)")
        return True

    def paste(self, offset=QPointF(40, 40)):
        if not self.clipboard:
            return False
        nodes, edges = self.clipboard
        self.push_undo()
        mapping = {}
        created = []
        for d in nodes:
            n = self.add_node(d["type"], QPointF(d["x"], d["y"]) + offset, json.loads(json.dumps(d["config"])), d.get("title"), record=False)
            if n:
                mapping[d["id"]] = n
                created.append(n)
        for a, b in edges:
            if a in mapping and b in mapping:
                self.connect_pair(mapping[a], mapping[b], record=False, quiet=True)
        self.scene().clearSelection()
        for n in created:
            n.setSelected(True)
        self.clipboard = ([dict(d, x=d["x"] + offset.x(), y=d["y"] + offset.y()) for d in nodes], edges)
        self._changed()
        return True

    def duplicate_selected(self):
        return self.copy_selected() and self.paste()

    def select_all(self):
        for n in self.nodes:
            n.setSelected(True)

    def auto_layout(self):
        if not self.nodes:
            return
        self.push_undo()
        depth = {}
        edges = self.edges

        def d(nid, guard=0):
            if nid in depth:
                return depth[nid]
            parents = [s for s, t in edges if t == nid]
            depth[nid] = 0 if not parents or guard > 60 else 1 + max(d(p, guard + 1) for p in parents)
            return depth[nid]
        for n in self.nodes:
            d(n.node_id)
        col_y = {}
        for n in sorted(self.nodes, key=lambda n: (depth[n.node_id], n.pos().y())):
            col = depth[n.node_id]
            y = col_y.get(col, 0)
            n.setPos(col * 272, y)
            col_y[col] = y + n.rect().height() + 32
        self.fit()
        self._changed()

    def fit(self):
        if not self.nodes:
            self.resetTransform()
            self.centerOn(300, 200)
            return
        rect = self.scene().itemsBoundingRect().adjusted(-80, -80, 80, 80)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1.15:
            self.resetTransform()
            self.scale(1.15, 1.15)
            self.centerOn(rect.center())

    def zoom(self, factor):
        s = self.transform().m11() * factor
        if 0.2 <= s <= 2.5:
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
        for level, text, nid in issues:
            node = self.node_by_id.get(nid)
            if node and (node.issue is None or level == "error"):
                node.issue = (level, text)
        for n in self.nodes:
            n.setToolTip(n.spec["help"] + (f"\n⚠ {n.issue[1]}" if n.issue else ""))
            n.update()

    def set_live(self, values):
        for n in self.nodes:
            v = values.get(n.node_id) if values else None
            if v != n.live:
                n.live = v
                n.update()

    # ── rendu ──
    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(C["bg"]))
        step = GRID * 2
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
        painter.drawText(vr.adjusted(0, -50, 0, -50), Qt.AlignmentFlag.AlignCenter, "Atelier vide")
        painter.setPen(QColor(C["muted"]))
        painter.setFont(QFont("Inter", 10))
        painter.drawText(vr.adjusted(0, 10, 0, 10), Qt.AlignmentFlag.AlignCenter,
                         "Tab ou Espace : chercher un nœud · glisser depuis la bibliothèque · clic droit\n"
                         "ou « Modèle de départ » pour un graphe prêt à l'emploi")
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

    def _edge_at(self, pos):
        for item in self.items(pos):
            if isinstance(item, EdgeItem):
                return item
        return None

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        self._param_key = None
        if event.button() == Qt.MouseButton.MiddleButton or (
                event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.AltModifier
                and self._node_at(pos) is None):
            self._panning = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            port = self._port_at(pos)
            if port is not None:
                if port.kind == "in":
                    existing = [e for e in port.node.edges if e.target is port.node]
                    if not existing:
                        return
                    edge = existing[-1]
                    src = edge.source
                    self.push_undo()
                    self._remove_edge_item(edge)
                    self.resync_core()
                    self._changed()
                    port = src.out_port
                self._drag_port = port
                self._temp = QGraphicsPathItem()
                self._temp.setPen(QPen(QColor(port.node.color), 2, Qt.PenStyle.DashLine))
                self._temp.setZValue(10)
                self.scene().addItem(self._temp)
                self._update_temp(self.mapToScene(pos))
                return
            self._press_positions = {n.node_id: QPointF(n.pos()) for n in self.nodes}
        super().mousePressEvent(event)

    def _update_temp(self, scene_pos):
        self._temp.setPath(bezier(self._drag_port.node.port_pos("out"), scene_pos))

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
                self.open_search(event.position().toPoint(), source)
            return
        super().mouseReleaseEvent(event)
        moved = [n for n in self.nodes if n.node_id in self._press_positions
                 and (n.pos() - self._press_positions[n.node_id]).manhattanLength() > 2]
        if moved:
            before = self._press_positions
            nodes, edges = self.model()
            for data in nodes:
                if data["id"] in before:
                    data["x"], data["y"] = before[data["id"]].x(), before[data["id"]].y()
            self.undo_stack.append(json.dumps((nodes, edges)))
            self.redo_stack.clear()
            self.history_changed.emit()
            # déposer un nœud isolé sur une liaison = l'insérer
            if len(moved) == 1 and not moved[0].edges:
                self._try_splice(moved[0], record=False)
            self._changed()
        self._press_positions = {}

    def _try_splice(self, node, record=True):
        if not (node.in_port and node.out_port):
            return False
        center = node.mapToScene(node.rect().center())
        for e in list(self.edge_items):
            if e.source is node or e.target is node:
                continue
            if e.shape().contains(center) or e.path().intersects(node.sceneBoundingRect()):
                a, b = e.source, e.target
                if self._reaches(node.node_id, a.node_id):
                    continue
                if record:
                    self.push_undo()
                self._remove_edge_item(e)
                self.resync_core()
                self.connect_pair(a, node, record=False, quiet=True)
                self.connect_pair(node, b, record=False, quiet=True)
                self.interaction_message.emit(f"{node.title} inséré entre {a.title} et {b.title}")
                return True
        return False

    def open_search(self, view_pos=None, connect_from=None):
        if view_pos is None:
            view_pos = self.mapFromGlobal(QCursor.pos())
        types = [t for t in PALETTE.get(self.creator_id, PALETTE["brush_engine"])
                 if connect_from is None or NODE_TYPES[t]["ins"]]
        popup = NodeSearch(types, self)
        scene_pos = self.mapToScene(view_pos)

        def create(t):
            offset = QPointF(0, 15) if connect_from else QPointF(NODE_W / 2, 20)
            node = self.add_node(t, scene_pos - offset)
            if node and connect_from is not None:
                self.connect_pair(connect_from, node, record=False)
        popup.chosen.connect(create)
        popup.popup(self.mapToGlobal(view_pos))
        self._search = popup

    def contextMenuEvent(self, event):
        node = self._node_at(event.pos())
        if node is None:
            edge = self._edge_at(event.pos())
            if edge is not None:
                self.scene().clearSelection()
                edge.setSelected(True)
                menu = QMenu(self)
                if menu.addAction("Supprimer la liaison") == menu.exec(event.globalPos()):
                    self.delete_selected()
                return
            menu = QMenu(self)
            add = menu.addMenu("Ajouter un nœud")
            cats = {}
            for t in PALETTE.get(self.creator_id, PALETTE["brush_engine"]):
                spec = NODE_TYPES[t]
                if spec["category"] not in cats:
                    cats[spec["category"]] = add.addMenu(spec["category"])
                cats[spec["category"]].addAction(spec["label"]).setData(t)
            menu.addSeparator()
            paste = menu.addAction("Coller  (Ctrl+V)")
            paste.setEnabled(bool(self.clipboard))
            lay = menu.addAction("Organiser le graphe")
            fit = menu.addAction("Tout afficher  (F)")
            chosen = menu.exec(event.globalPos())
            if chosen is None:
                return
            if chosen.data():
                self.add_node(chosen.data(), self.mapToScene(event.pos()) - QPointF(NODE_W / 2, 15))
            elif chosen == paste:
                nodes = self.clipboard[0]
                if nodes:
                    first = QPointF(nodes[0]["x"], nodes[0]["y"])
                    self.paste(self.mapToScene(event.pos()) - first)
            elif chosen == lay:
                self.auto_layout()
            elif chosen == fit:
                self.fit()
            return
        if not node.isSelected():
            self.scene().clearSelection()
            node.setSelected(True)
        menu = QMenu(self)
        dup = menu.addAction("Dupliquer  (Ctrl+D)")
        cp = menu.addAction("Copier  (Ctrl+C)")
        disc = menu.addAction("Déconnecter")
        disc.setEnabled(bool(node.edges))
        menu.addSeparator()
        dele = menu.addAction("Supprimer  (Suppr)")
        chosen = menu.exec(event.globalPos())
        if chosen == dup:
            self.duplicate_selected()
        elif chosen == cp:
            self.copy_selected()
        elif chosen == disc:
            self.push_undo()
            for e in list(node.edges):
                self._remove_edge_item(e)
            self.resync_core()
            self._changed()
        elif chosen == dele:
            self.delete_selected()

    def mouseDoubleClickEvent(self, event):
        if self._node_at(event.position().toPoint()) is None:
            self.open_search(event.position().toPoint())
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif key == Qt.Key.Key_F:
            self.fit()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Space):
            self.open_search()
        else:
            super().keyPressEvent(event)

    def focusNextPrevChild(self, _next):
        return False   # Tab ouvre la recherche au lieu de changer de widget

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_NODE) or event.mimeData().hasFormat(MIME_ENGINE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_NODE) or event.mimeData().hasFormat(MIME_ENGINE):
            event.acceptProposedAction()

    def dropEvent(self, event):
        pos = self.mapToScene(event.position().toPoint())
        md = event.mimeData()
        if md.hasFormat(MIME_ENGINE):
            self.engine_dropped.emit(bytes(md.data(MIME_ENGINE)).decode(), pos)
        else:
            node = self.add_node(bytes(md.data(MIME_NODE)).decode(), pos - QPointF(NODE_W / 2, 15))
            if node is not None:
                self._try_splice(node, record=False)
                self._changed()
        event.acceptProposedAction()

    # ── compat Existence ──
    def native_snapshot(self):
        nodes, edges = self.model()
        snap = {"format": "StellarDustGraph", "version": 3, "creator": self.creator_id,
                "nodes": nodes, "connections": [{"from": a, "to": b} for a, b in edges]}
        if self.core is not None:
            response = self._core("snapshot")
            if response.get("ok") and isinstance(response.get("result"), dict):
                snap["native"] = response["result"]
        return snap

    def native_validate(self):
        return self._core("validate") if self.core is not None else {"ok": True, "result": []}


# ─── Panneaux latéraux ─────────────────────────────────────────────────────
class PaletteButton(QPushButton):
    def __init__(self, node_type, on_click):
        spec = NODE_TYPES[node_type]
        super().__init__(f"  {spec['label']}")
        self.node_type = node_type
        self._press = None
        self.setObjectName("paletteButton")
        self.setStyleSheet(f"#paletteButton {{ border-left:3px solid {spec['color']}; }}")
        self.setToolTip(spec["help"] + "\nClic : ajouter · Glisser : déposer (sur une liaison pour l'insérer)")
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


class DragLabel(QLabel):
    """Libellé d'un paramètre moteur : glisser sur le graphe pour le piloter."""

    def __init__(self, text, key):
        super().__init__(text)
        self.key = key
        self._press = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position() - self._press).manhattanLength() > 8:
            self._press = None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(MIME_ENGINE, self.key.encode())
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)


class CapabilityEditor(QFrame):
    """Valeurs de base du moteur CreativeCore. Chaque paramètre peut être glissé
    sur le graphe ou piloté via clic droit."""
    changed = Signal()
    link_requested = Signal(str, str)

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
        root.addWidget(label("Valeurs de base. ◆ = modifié par le graphe. Glisse un nom sur le graphe, ou clic droit, "
                             "pour le piloter.", C["muted"], 10, wrap=True))
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
        lab = DragLabel(text, key)
        lab.setToolTip(f"{key}\nGlisser sur le graphe · clic droit : piloter")
        for w in (lab, control):
            w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda pos, k=key, ww=w: self.link_menu(k, ww.mapToGlobal(pos)))
        form.addRow(lab, control)
        self.controls[key] = control
        self.rows[key] = (lab, control, text)
        self.values[key] = value

    def _build_blend(self, root):
        blend = self.schema.get("blend") or {}
        form = QFormLayout()
        mode = QComboBox()
        mode.addItems(blend.get("blend_modes") or ["normal"])
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

    def link_menu(self, key, global_pos):
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

    def _apply_filter(self, text):
        text = text.casefold().strip()
        for key, (lab, control, name) in self.rows.items():
            visible = not text or text in name.casefold() or text in key.casefold()
            lab.setVisible(visible)
            control.setVisible(visible)

    def mark_driven(self, driven: dict):
        for key, (lab, control, text) in self.rows.items():
            who = driven.get(key)
            if who:
                lab.setText(f"◆ {text}")
                lab.setStyleSheet(f"color:{C['warn']}; font-weight:700;")
                lab.setToolTip(f"{key}\nPiloté par le graphe :\n• " + "\n• ".join(who))
            else:
                lab.setText(text)
                lab.setStyleSheet("")
                lab.setToolTip(f"{key}\nGlisser sur le graphe · clic droit : piloter")

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


class Inspector(QFrame):
    """Tous les réglages du nœud sélectionné (les principaux sont aussi sur le nœud)."""
    node_parameter_changed = Signal(object, str, object)
    node_renamed = Signal(object, str)

    def __init__(self, creator_id="brush_engine"):
        super().__init__()
        self.node = None
        self.curve_fields = {}
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(4, 4, 4, 4)
        self.body = QWidget()
        self.layout_.addWidget(self.body)
        self.layout_.addStretch()
        self.capability_editor = None
        self.show_node(None)

    def set_marker(self, values):
        """Affiche la position du signal courant sur les courbes ouvertes."""
        if self.node is None or not self.curve_fields:
            return
        v = values.get(self.node.node_id) if values else None
        for f in self.curve_fields.values():
            f.editor.set_marker(v)

    def focus_curve(self, key):
        f = self.curve_fields.get(key)
        if f is not None:
            f.editor.setFocus()
            f.setStyleSheet(f"border:1px solid {C['accent']}; border-radius:6px;")
            QTimer.singleShot(700, lambda: f.setStyleSheet(""))

    def show_node(self, node):
        self.node = node
        self.curve_fields = {}
        self.body.deleteLater()
        self.body = QWidget()
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        self.layout_.insertWidget(0, self.body)
        if node is None:
            lay.addWidget(label("Aucun nœud sélectionné", "#C3D0EA", 14, True))
            lay.addWidget(label(
                "Les réglages principaux se font directement sur les nœuds :\n"
                "• glisser sur une barre pour régler (Maj : précis, double-clic : défaut)\n"
                "• clic sur un choix ▾ pour le changer · clic sur une courbe pour l'éditer ici\n\n"
                "Graphe :\n• Tab / Espace : chercher un nœud\n"
                "• tirer depuis le rond de droite pour relier ; relâcher dans le vide = nouveau nœud relié\n"
                "• déposer un nœud sur une liaison l'insère · Alt : sans aimantation\n"
                "• Ctrl+C / Ctrl+V / Ctrl+D · Suppr · Ctrl+Z · F : tout afficher\n"
                "• molette : zoom · clic milieu / Alt+glisser : se déplacer", C["muted"], 11, wrap=True))
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
                combo.setMaxVisibleItems(22)
                group = None
                for fk, f in fields.items():
                    if extra == "float" and f["kind"] != "float":
                        continue
                    if f["group"] != group:
                        group = f["group"]
                        if combo.count():
                            combo.insertSeparator(combo.count())
                    combo.addItem(f"{f['group']} › {f['label']}", fk)
                combo.setCurrentIndex(max(0, combo.findData(value)))

                def on_key(_i, c=combo, k=key):
                    new = c.currentData()
                    self.node_parameter_changed.emit(node, k, new)
                    if node.node_type == "EngineParam":
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
            elif kind == "curve":
                field = CurveField(value, node.color)
                field.changed.connect(lambda pts, k=key: self.node_parameter_changed.emit(node, k, [list(p) for p in pts]))
                self.curve_fields[key] = field
                form.addRow(QLabel(text))
                form.addRow(field)
            else:
                check = QCheckBox()
                check.setChecked(bool(value))
                check.toggled.connect(lambda v, k=key: self.node_parameter_changed.emit(node, k, v))
                form.addRow(text, check)
        lay.addLayout(form)
        link = None
        if node.node_type == "Dynamics":
            f = fields.get(node.config.get("target"), {})
            link = (f"Pilote <b>{field_label(node.config.get('target'))}</b><br>"
                    "multiplier : base × (Min→Max) · ajouter : base + (Min→Max) × plage · remplacer : Min→Max de la plage"
                    + (f" [{f['lo']:g} – {f['hi']:g}]" if f.get("kind") == "float" else ""))
        elif node.node_type == "EngineParam":
            f = fields.get(node.config.get("key"), {})
            link = f"Remplace <b>{field_label(node.config.get('key'))}</b> (défaut moteur : {f.get('default', '?')})"
        elif node.node_type == "Combine":
            n_in = sum(1 for e in node.edges if e.target is node)
            link = f"{n_in} signal(aux) combiné(s). Relie plusieurs nœuds à son entrée."
        if link:
            info = QLabel(link)
            info.setWordWrap(True)
            info.setStyleSheet(f"color:{C['warn']}; font-size:11px; background:#221D12; border-radius:6px; padding:7px;")
            lay.addWidget(info)
        reset = QPushButton("Réinitialiser les réglages")
        reset.setObjectName("secondary")

        def do_reset():
            for k, v in default_config(node.node_type).items():
                self.node_parameter_changed.emit(node, k, v)
            self.show_node(node)
        reset.clicked.connect(do_reset)
        lay.addWidget(reset)
        ins = sum(1 for e in node.edges if e.target is node)
        outs = sum(1 for e in node.edges if e.source is node)
        lay.addWidget(label(f"{ins} entrée(s) · {outs} sortie(s) · id {node.node_id}", C["dim"], 10))
        if node.issue:
            lay.addWidget(label(f"⚠ {node.issue[1]}", C["err"] if node.issue[0] == "error" else C["warn"], 11, wrap=True))
