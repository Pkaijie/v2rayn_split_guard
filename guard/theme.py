"""Local Qt Widgets theme; no remote fonts, assets or web content."""
from pathlib import Path
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPalette, QColor
from PySide6.QtWidgets import (QLabel,QPushButton,QFrame,QVBoxLayout,QHBoxLayout,QPlainTextEdit,QDialog,
                              QComboBox,QListView,QStyledItemDelegate,QProxyStyle,QStyle)
from PySide6.QtSvg import QSvgRenderer

BG='#F4F7F9';WHITE='#FFFFFF';FG='#142E35';MUTED='#526872'
GREEN='#147D64';AMBER='#946000';RED='#B12E40';LINE='#DCE5E9'
STYLE='''
QWidget {color:#142E35; font-size:14px;}
QMainWindow, QDialog, QWidget#workspace {background:#F4F7F9;}
QFrame#card {background:white; border:1px solid #DCE5E9; border-radius:12px;}
QFrame#proxyCard {background:#142E35; border-radius:12px;}
QFrame#sidebar {background:#142E35;}
QWidget#sidebarContent {background:#142E35;}
QFrame#monitorCard {background:#1D3E46; border-radius:10px;}
QLabel {background:transparent; border:0;}
QPushButton {background:white; border:1px solid #92A7B0; border-radius:7px; padding:7px 14px; min-height:20px;}
QPushButton:hover {background:#E8F0F2;}
QPushButton:focus {border:2px solid #147D64; padding:6px 13px;}
QPushButton:disabled {color:#76858A; background:#E7ECEE; border-color:#CCD6DB;}
QPushButton[primary="true"] {background:#147D64; color:white; border-color:#147D64;}
QPushButton[primary="true"]:hover {background:#0D6652;}
QPushButton[primary="true"]:disabled {background:#789E94; border-color:#789E94;}
QPushButton[nav="true"] {background:transparent; color:#E3EEF1; border:0; text-align:left; padding:12px 14px; border-radius:8px;}
QPushButton[nav="true"]:checked {background:#23444C; color:white;}
QPushButton[nav="true"]:hover {background:#2A5059;}
QPushButton[nav="true"]:focus {border:1px solid #81DFC6; padding:11px 13px;}
QLineEdit, QSpinBox, QComboBox {background:#F4F7F9; border:1px solid #92A7B0; border-radius:6px; padding:6px 8px; min-height:20px; selection-background-color:#147D64;}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {border:2px solid #147D64; padding:5px 7px;}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {color:#76858A; background:#E7ECEE;}
QComboBox QAbstractItemView {background:white; color:#142E35; selection-background-color:#DDEFE8; selection-color:#142E35; border:1px solid #7E929C; padding:0;}
QComboBox QAbstractItemView::item {min-height:30px; padding:2px 8px;}
QComboBox QAbstractItemView::item:selected {background:#DDEFE8; color:#142E35;}
QComboBox::drop-down {subcontrol-origin:padding; subcontrol-position:top right; width:26px; border:0; background:transparent;}
QComboBox::down-arrow {image:url("@DOWN@");width:12px;height:12px;}
QSpinBox::up-button {subcontrol-origin:border;subcontrol-position:top right;width:20px;border:0;background:transparent;}
QSpinBox::down-button {subcontrol-origin:border;subcontrol-position:bottom right;width:20px;border:0;background:transparent;}
QSpinBox::up-arrow {image:url("@UP@");width:10px;height:8px;}
QSpinBox::down-arrow {image:url("@DOWN@");width:10px;height:8px;}
QComboBox::drop-down:hover, QSpinBox::up-button:hover, QSpinBox::down-button:hover {background:#DDE8EC;}
QPlainTextEdit {background:white; border:1px solid #92A7B0; border-radius:8px; padding:10px; selection-background-color:#147D64;}
QTableView {background:white; alternate-background-color:#F5F8F9; border:0; gridline-color:#E2E9EC; selection-background-color:#DDEFE8; selection-color:#142E35;}
QTableView:focus {border:1px solid #147D64;}
QHeaderView::section {background:#F4F7F9; color:#526872; padding:8px; border:0; border-bottom:1px solid #DCE5E9;}
QCheckBox, QRadioButton {spacing:8px;}
QScrollArea {background:transparent; border:0;}
QScrollBar:vertical {width:10px; background:#F4F7F9; margin:0;}
QScrollBar::handle:vertical {background:#BDCDD2; border-radius:4px; min-height:28px;}
QScrollBar:horizontal {height:10px; background:#F4F7F9; margin:0;}
QScrollBar::handle:horizontal {background:#BDCDD2; border-radius:4px; min-width:28px;}
QScrollBar::add-line, QScrollBar::sub-line {width:0; height:0;}
QToolTip {background:#142E35; color:white; padding:6px; border:0;}
'''


def resources():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
def icon_path():return resources()/'assets'/'app.ico'


class GuardStyle(QProxyStyle):
    def styleHint(self,hint,option=None,widget=None,returnData=None):
        # Use the standard list popup, avoiding menu scrollers over the last row.
        if hint==QStyle.StyleHint.SH_ComboBox_Popup:return 0
        return super().styleHint(hint,option,widget,returnData)


def configure_application(app):
    app.setApplicationName('V2rayNSplitGuard');app.setApplicationDisplayName('v2rayN 分流助手')
    app.setOrganizationName('V2rayNSplitGuard');app._guard_style=GuardStyle('Fusion');app.setStyle(app._guard_style);app.setQuitOnLastWindowClosed(False)
    palette=QPalette()
    for role,color in [(QPalette.ColorRole.Window,BG),(QPalette.ColorRole.WindowText,FG),
        (QPalette.ColorRole.Base,WHITE),(QPalette.ColorRole.AlternateBase,BG),(QPalette.ColorRole.Text,FG),
        (QPalette.ColorRole.Button,WHITE),(QPalette.ColorRole.ButtonText,FG),(QPalette.ColorRole.Highlight,GREEN),
        (QPalette.ColorRole.HighlightedText,WHITE),(QPalette.ColorRole.ToolTipBase,FG),(QPalette.ColorRole.ToolTipText,WHITE)]:palette.setColor(role,QColor(color))
    app.setPalette(palette)
    families=QFontDatabase.families()
    font=QFont('Microsoft YaHei UI') if 'Microsoft YaHei UI' in families else QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPixelSize(14);app.setFont(font)
    style=STYLE.replace('#92A7B0','#7E929C').replace('@DOWN@',(resources()/'assets/chevron-down.svg').as_posix()).replace('@UP@',(resources()/'assets/chevron-up.svg').as_posix())
    app.setStyleSheet(style);app.setWindowIcon(QIcon(str(icon_path())))


def label(text='',size=14,color=FG,bold=False):
    result=QLabel(text);result.setTextFormat(Qt.TextFormat.PlainText);result.setWordWrap(True)
    set_color(result,color,size,bold)
    result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return result


def set_color(widget,color,size=14,bold=False):
    widget.setStyleSheet(f'color:{color};font-size:{size}px;font-weight:{600 if bold else 400};')


def button(text,command,primary=False):
    result=QPushButton(text);result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.setProperty('primary',primary);result.clicked.connect(command);return result


def combo_box():
    result=QComboBox();view=QListView(result)
    result.setView(view);result.setItemDelegate(QStyledItemDelegate(view))
    return result


def card(parent=None,dark=False):
    frame=QFrame(parent);frame.setObjectName('proxyCard' if dark else 'card')
    layout=QVBoxLayout(frame);layout.setContentsMargins(20,16,20,16);layout.setSpacing(10)
    return frame,layout


def row(*widgets):
    layout=QHBoxLayout();layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
    for widget in widgets:layout.addWidget(widget)
    return layout


def text_box():
    edit=QPlainTextEdit();edit.setReadOnly(True);edit.setMaximumBlockCount(2500)
    edit.setStyleSheet('font-family:Consolas;font-size:13px;');return edit


def dialog(parent,title,width=880,height=600,modal=True):
    result=QDialog(parent);result.setWindowTitle(title);result.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    if modal:result.setWindowModality(Qt.WindowModality.WindowModal)
    screen=parent.screen().availableGeometry()
    result.resize(min(width,int(screen.width()*.9)),min(height,int(screen.height()*.9)))
    result.setMinimumSize(min(580,result.width()),min(360,result.height()))
    return result
