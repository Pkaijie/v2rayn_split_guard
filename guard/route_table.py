"""Qt model/view route table. Geometry and text use Qt logical DPI units."""
from html import escape
from PySide6.QtCore import Qt,QAbstractTableModel,QModelIndex
from PySide6.QtGui import QColor,QFont,QGuiApplication,QAction
from PySide6.QtWidgets import QTableView,QAbstractItemView,QHeaderView,QMenu
from .theme import FG,RED

COLUMNS=(('节点地址',174),('网卡',90),('下一跳',154),('路由前缀',196),('活动',64),('持久',64),('网关',80))


class RouteModel(QAbstractTableModel):
    def __init__(self,parent=None):super().__init__(parent);self.rows=[]
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(COLUMNS)
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and orientation==Qt.Orientation.Horizontal:return COLUMNS[section][0]

    @staticmethod
    def values(row):
        chosen=row['chosen']
        return [row['ip'],', '.join(r['alias'] for r in chosen) or '无路由',
            ', '.join(r['gateway'] for r in chosen),', '.join(r['prefix'] for r in chosen),
            '有' if row['active'] else '无','有' if row['persistent'] else '无','一致' if row['gateway_match'] else '待更新']

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return
        record=self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            text=self.values(record)[index.column()]
            return '<qt><pre>'+escape(text)+'</pre></qt>' if role==Qt.ItemDataRole.ToolTipRole else text
        if role==Qt.ItemDataRole.ForegroundRole:return QColor(FG if record['ok'] else RED)
        if role==Qt.ItemDataRole.FontRole and index.column() in (0,2,3):
            font=QFont('Consolas');font.setPixelSize(13);return font

    def set_rows(self,rows):self.beginResetModel();self.rows=list(rows);self.endResetModel()


class RouteTable(QTableView):
    def __init__(self,parent=None):
        super().__init__(parent);self.route_model=RouteModel(self);self.setModel(self.route_model)
        self.setAlternatingRowColors(True);self.setWordWrap(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.verticalHeader().hide();self.verticalHeader().setDefaultSectionSize(38)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        for col,(_,width) in enumerate(COLUMNS):self.setColumnWidth(col,width)
        self.setMinimumHeight(140);self.setMaximumHeight(300)
        copy=QAction('复制选中内容',self);copy.setShortcut('Ctrl+C');copy.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy.triggered.connect(self.copy_selection);self.addAction(copy)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def menu(point):
            popup=QMenu(self);popup.addAction(copy);popup.exec(self.viewport().mapToGlobal(point))
        self.customContextMenuRequested.connect(menu)

    def set_rows(self,rows):
        selected=self.currentIndex()
        ip=self.route_model.rows[selected.row()]['ip'] if selected.isValid() else None
        position=(self.horizontalScrollBar().value(),self.verticalScrollBar().value())
        self.route_model.set_rows(rows)
        self.setFixedHeight(min(300,max(140,self.horizontalHeader().sizeHint().height()+38*len(rows)+16)))
        if ip:
            for i,record in enumerate(rows):
                if record['ip']==ip:self.setCurrentIndex(self.route_model.index(i,selected.column()));break
        self.horizontalScrollBar().setValue(position[0]);self.verticalScrollBar().setValue(position[1])

    def copy_selection(self):
        indexes=self.selectionModel().selectedIndexes()
        if not indexes:return
        rows=sorted({i.row() for i in indexes});cols=sorted({i.column() for i in indexes})
        chosen={(i.row(),i.column()) for i in indexes}
        text='\n'.join('\t'.join(str(self.model().data(self.model().index(r,c))) if (r,c) in chosen else '' for c in cols) for r in rows)
        QGuiApplication.clipboard().setText(text)
