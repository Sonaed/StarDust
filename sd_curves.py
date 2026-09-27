"""Courbes de réponse : évaluation (Qt-free) + éditeur interactif."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

CURVE_PRESETS = {
    "Linéaire": [[0, 0], [1, 1]],
    "Douce (ease-in)": [[0, 0], [0.55, 0.2], [1, 1]],
    "Forte (ease-out)": [[0, 0], [0.45, 0.8], [1, 1]],
    "En S": [[0, 0], [0.3, 0.1], [0.7, 0.9], [1, 1]],
    "Inversée": [[0, 1], [1, 0]],
    "Plateau": [[0, 0], [0.3, 1], [1, 1]],
    "Seuil doux": [[0, 0], [0.45, 0.05], [0.55, 0.95], [1, 1]],
    "Cloche": [[0, 0], [0.5, 1], [1, 0]],
    "Vallée": [[0, 1], [0.5, 0], [1, 1]],
}
LEGACY = {"linéaire": "Linéaire", "douce (ease-in)": "Douce (ease-in)", "forte (ease-out)": "Forte (ease-out)",
          "en S": "En S", "inversée": "Inversée"}


def normalize_curve(value):
    """Accepte une liste de points ou un ancien nom de courbe."""
    if isinstance(value, str):
        value = CURVE_PRESETS.get(LEGACY.get(value, value), CURVE_PRESETS["Linéaire"])
    pts = []
    for p in value or []:
        try:
            pts.append([max(0.0, min(1.0, float(p[0]))), max(0.0, min(1.0, float(p[1])))])
        except (TypeError, ValueError, IndexError):
            continue
    pts.sort(key=lambda p: p[0])
    if len(pts) < 2:
        pts = [list(p) for p in CURVE_PRESETS["Linéaire"]]
    pts[0][0], pts[-1][0] = 0.0, 1.0
    return pts


def _tangents(pts):
    n = len(pts)
    d = [(pts[i + 1][1] - pts[i][1]) / max(1e-9, pts[i + 1][0] - pts[i][0]) for i in range(n - 1)]
    m = [d[0]] + [(d[i - 1] + d[i]) / 2 if d[i - 1] * d[i] > 0 else 0.0 for i in range(1, n - 1)] + [d[-1]]
    for i in range(n - 1):   # Fritsch–Carlson : pas de dépassement
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9:
            t = 3 / s ** 0.5
            m[i], m[i + 1] = t * a * d[i], t * b * d[i]
    return m


def eval_curve(points, x):
    pts = points if points and isinstance(points[0], list) and len(points) >= 2 else normalize_curve(points)
    x = max(0.0, min(1.0, x))
    if len(pts) == 2:
        (x0, y0), (x1, y1) = pts
        return y0 + (y1 - y0) * (x - x0) / max(1e-9, x1 - x0)
    m = _tangents(pts)
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x <= x1 or i == len(pts) - 2:
            h = max(1e-9, x1 - x0)
            t = (x - x0) / h
            t2, t3 = t * t, t * t * t
            y = ((2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * m[i]
                 + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * m[i + 1])
            return max(0.0, min(1.0, y))
    return pts[-1][1]


def curve_path(points, rect: QRectF, steps=48) -> QPainterPath:
    pts = normalize_curve(points)
    path = QPainterPath()
    for i in range(steps + 1):
        x = i / steps
        pt = QPointF(rect.left() + x * rect.width(), rect.bottom() - eval_curve(pts, x) * rect.height())
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    return path


class CurveEditor(QWidget):
    """Éditeur de courbe : clic = ajouter un point, glisser = déplacer,
    double-clic ou clic droit sur un point = le retirer."""
    changed = Signal(list)       # fin d'édition
    live = Signal(list)          # pendant le glissement

    def __init__(self, points=None, color="#8C9EFF", parent=None):
        super().__init__(parent)
        self.points = normalize_curve(points or CURVE_PRESETS["Linéaire"])
        self.color = color
        self.marker = None
        self._drag = None
        self.setMinimumSize(200, 170)
        self.setMouseTracking(True)
        self.setToolTip("Clic : ajouter un point · glisser : déplacer · double-clic / clic droit : retirer")

    def area(self):
        return QRectF(10, 10, self.width() - 20, self.height() - 20)

    def to_px(self, p):
        a = self.area()
        return QPointF(a.left() + p[0] * a.width(), a.bottom() - p[1] * a.height())

    def from_px(self, pt):
        a = self.area()
        return [max(0.0, min(1.0, (pt.x() - a.left()) / a.width())), max(0.0, min(1.0, (a.bottom() - pt.y()) / a.height()))]

    def hit(self, pt):
        for i, p in enumerate(self.points):
            if (self.to_px(p) - pt).manhattanLength() < 12:
                return i
        return -1

    def set_points(self, points):
        self.points = normalize_curve(points)
        self.update()

    def set_marker(self, x):
        self.marker = x
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a = self.area()
        p.fillRect(self.rect(), QColor("#0B1224"))
        p.setPen(QPen(QColor("#1B2848"), 1))
        for i in range(1, 4):
            p.drawLine(QPointF(a.left() + a.width() * i / 4, a.top()), QPointF(a.left() + a.width() * i / 4, a.bottom()))
            p.drawLine(QPointF(a.left(), a.top() + a.height() * i / 4), QPointF(a.right(), a.top() + a.height() * i / 4))
        p.setPen(QPen(QColor("#2A3A5A"), 1, Qt.PenStyle.DashLine))
        p.drawLine(a.bottomLeft(), a.topRight())
        p.setPen(QPen(QColor("#2A3A5A"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(a)
        p.setPen(QPen(QColor(self.color), 2.4))
        p.drawPath(curve_path(self.points, a, 96))
        if self.marker is not None:
            x = a.left() + self.marker * a.width()
            y = a.bottom() - eval_curve(self.points, self.marker) * a.height()
            p.setPen(QPen(QColor("#F5C56B"), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, a.bottom()), QPointF(x, y))
            p.drawLine(QPointF(a.left(), y), QPointF(x, y))
        for i, pt in enumerate(self.points):
            c = self.to_px(pt)
            p.setPen(QPen(QColor("#FFFFFF"), 1.5))
            p.setBrush(QColor(self.color if i == self._drag else "#0B1224"))
            p.drawEllipse(c, 5.5, 5.5)
        p.setPen(QColor("#56678C"))
        p.setFont(QFont("Inter", 7))
        p.drawText(QRectF(a.left(), a.bottom() - 12, 60, 12), "entrée →")
        p.end()

    def mousePressEvent(self, e):
        i = self.hit(e.position())
        if e.button() == Qt.MouseButton.RightButton:
            self._remove(i)
            return
        if i < 0:
            new = self.from_px(e.position())
            self.points.append(new)
            self.points.sort(key=lambda q: q[0])
            i = self.points.index(new)
        self._drag = i
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        i = self._drag
        x, y = self.from_px(e.position())
        if i == 0:
            x = 0.0
        elif i == len(self.points) - 1:
            x = 1.0
        else:
            x = max(self.points[i - 1][0] + 0.01, min(self.points[i + 1][0] - 0.01, x))
        self.points[i] = [round(x, 4), round(y, 4)]
        self.update()
        self.live.emit(self.points)

    def mouseReleaseEvent(self, _e):
        if self._drag is not None:
            self._drag = None
            self.update()
            self.changed.emit([list(p) for p in self.points])

    def mouseDoubleClickEvent(self, e):
        self._remove(self.hit(e.position()))

    def _remove(self, i):
        if 0 < i < len(self.points) - 1:
            self.points.pop(i)
            self.update()
            self.changed.emit([list(p) for p in self.points])


class CurveField(QWidget):
    """Éditeur + préréglages + inverser, pour l'inspecteur."""
    changed = Signal(list)

    def __init__(self, points, color="#8C9EFF"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.editor = CurveEditor(points, color)
        lay.addWidget(self.editor)
        row = QHBoxLayout()
        self.presets = QComboBox()
        self.presets.addItem("Préréglage…")
        self.presets.addItems(list(CURVE_PRESETS))
        self.presets.activated.connect(self._preset)
        row.addWidget(self.presets, 1)
        for text, fn in (("⇅", self._flip_y), ("⇆", self._flip_x)):
            b = QPushButton(text)
            b.setObjectName("secondary")
            b.setFixedWidth(34)
            b.setToolTip("Inverser verticalement" if text == "⇅" else "Inverser horizontalement")
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.editor.changed.connect(self.changed)

    def _preset(self, i):
        if i > 0:
            self.editor.set_points(CURVE_PRESETS[self.presets.itemText(i)])
            self.presets.setCurrentIndex(0)
            self.changed.emit(self.editor.points)

    def _flip_y(self):
        self.editor.set_points([[x, 1 - y] for x, y in self.editor.points])
        self.changed.emit(self.editor.points)

    def _flip_x(self):
        self.editor.set_points([[1 - x, y] for x, y in self.editor.points])
        self.changed.emit(self.editor.points)
