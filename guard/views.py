"""Four native Qt pages sharing a quiet teal theme."""
from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,
    QScrollArea,QStackedWidget,QComboBox,QCheckBox,QLineEdit,QSpinBox,QSizePolicy,QListWidget)
from .common import VERSION
from .theme import *
from .route_table import RouteTable
from .config_picker import RuntimeConfigPicker
from .close_prompt import CLOSE_CHOICES


def scroll_page():
    scroll=QScrollArea();scroll.setWidgetResizable(True)
    body=QWidget();body.setObjectName('workspace');scroll.setWidget(body)
    layout=QVBoxLayout(body);layout.setContentsMargins(24,22,24,22);layout.setSpacing(16)
    return scroll,layout


def title(layout,text,description):
    layout.addWidget(label(text,26,bold=True));layout.addWidget(label(description,13,MUTED))


def spin(minimum,maximum,value):
    result=QSpinBox();result.setRange(minimum,maximum);result.setValue(value);return result


def build(app):
    app.setWindowTitle('v2rayN 分流助手');app.setWindowIcon(QIcon(str(icon_path())))
    available=app.screen().availableGeometry()
    app.resize(min(1260,int(available.width()*.92)),min(940,int(available.height()*.9)))
    app.setMinimumSize(min(940,int(available.width()*.85)),min(620,int(available.height()*.85)))
    center=QWidget();app.setCentralWidget(center);outer=QHBoxLayout(center);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
    sidebar=QFrame();sidebar.setObjectName('sidebar');sidebar.setFixedWidth(208);app.sidebar=sidebar;outer.addWidget(sidebar)
    shell=QVBoxLayout(sidebar);shell.setContentsMargins(0,0,0,0)
    side_scroll=QScrollArea();side_scroll.setWidgetResizable(True);side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    contents=QWidget();contents.setObjectName('sidebarContent');side_scroll.setWidget(contents);shell.addWidget(side_scroll)
    side=QVBoxLayout(contents);side.setContentsMargins(16,30,16,20);side.setSpacing(8)
    side.addWidget(label('分流助手',23,WHITE,True));side.addWidget(label('v2rayN · NETWORK',11,'#B6CCD2'));side.addSpacing(22)
    app.nav_buttons={}
    for index,(name,text) in enumerate([('overview','状态总览'),('restore','备份恢复'),('logs','诊断日志'),('settings','高级设置')]):
        item=button(text,lambda checked=False,i=index:app.navigate(i));item.setCheckable(True);item.setProperty('nav',True)
        item.setIcon(QIcon(str(resources()/'assets'/f'nav-{name}.svg')));item.setIconSize(QSize(20,20))
        side.addWidget(item);app.nav_buttons[text]=item
    side.addStretch(1)
    monitor=QFrame();monitor.setObjectName('monitorCard');app.monitor_panel=monitor
    box=QVBoxLayout(monitor);box.setContentsMargins(16,16,16,16);box.setSpacing(12)
    app.monitor=QCheckBox('后台监测');app.monitor.setChecked(True);app.monitor.setStyleSheet('color:white;');box.addWidget(app.monitor)
    interval=QHBoxLayout();interval.addWidget(label('每',12,'#C1D5DA'))
    app.interval=spin(5,3600,int(app.config.get('interval',15)));app.interval.setFixedWidth(70);interval.addWidget(app.interval)
    interval.addWidget(label('秒检查',12,'#C1D5DA'));box.addLayout(interval);side.addWidget(monitor)
    app.notification_button=button('提醒摘要',app.show_notifications);app.notification_button.setProperty('nav',True);side.addWidget(app.notification_button)
    app.version_label=label('VERSION '+VERSION,11,'#A5C0C7');side.addWidget(app.version_label)
    right=QVBoxLayout();right.setContentsMargins(0,0,0,0);right.setSpacing(0);outer.addLayout(right,1)
    app.pages=QStackedWidget();right.addWidget(app.pages,1)
    overview(app);backups(app);logs(app);settings(app)
    footer=QWidget();foot=QHBoxLayout(footer);foot.setContentsMargins(24,6,24,10)
    app.status=label('准备就绪',12,MUTED);foot.addWidget(app.status,1)
    app.auto_proxy=QCheckBox('每 60 秒测试代理');app.auto_proxy.setChecked(bool(app.config.get('auto_proxy')));foot.addWidget(app.auto_proxy)
    right.addWidget(footer);app.navigate(0)


def overview(app):
    page,layout=scroll_page();app.pages.addWidget(page)
    heading=QHBoxLayout();names=QVBoxLayout();names.addWidget(label('网络分流',28,bold=True));names.addWidget(label('代理节点走 WLAN，默认流量交给系统路由',13,MUTED));heading.addLayout(names,1)
    app.check_button=button('立即检查',app.do_check);app.repair_button=button('应用 / 修复路由',app.prepare_routes,True)
    heading.addWidget(app.check_button);heading.addWidget(app.repair_button);layout.addLayout(heading)
    cards=QHBoxLayout();route,body=card();body.addWidget(label('01  系统路由',12,MUTED))
    app.route_label=label('正在等待检查',24,MUTED,True);body.addWidget(app.route_label)
    app.route_detail=label('读取节点选路、活动与持久路由',13,MUTED);body.addWidget(app.route_detail);cards.addWidget(route,3)
    proxy,body=card(dark=True);body.addWidget(label('02  代理可用性',12,'#C1D5DA'))
    app.proxy_label=label('尚未测试',24,WHITE,True);body.addWidget(app.proxy_label)
    app.proxy_detail=label('SOCKS5h · HTTPS',12,'#C1D5DA');app.proxy_button=button('测试代理',app.do_proxy)
    body.addLayout(row(app.proxy_detail,app.proxy_button));cards.addWidget(proxy,2);layout.addLayout(cards)
    network,body=card();head=QHBoxLayout();head.addWidget(label('网络连接',16,bold=True));head.addStretch()
    app.gateway_button=button('自动读取网关',app.auto_gateway);head.addWidget(app.gateway_button);body.addLayout(head)
    grid=QGridLayout();app.wlan_title=label('WLAN',16,GREEN,True);app.company_title=label(app.config['company'],16,bold=True)
    app.network_text=label('等待读取接口、地址和网关…',13,MUTED);app.default_label=label('等待读取普通默认路由…',13,MUTED)
    grid.addWidget(app.wlan_title,0,0);grid.addWidget(app.company_title,0,1);grid.addWidget(app.network_text,1,0);grid.addWidget(app.default_label,1,1)
    grid.setColumnStretch(0,1);grid.setColumnStretch(1,1);body.addLayout(grid);layout.addWidget(network)
    node,body=card();head=QHBoxLayout();head.addWidget(label('代理节点',16,bold=True));head.addStretch()
    app.listener_label=label('本地代理监听待检查',12,MUTED);head.addWidget(app.listener_label);body.addLayout(head)
    app.listener_label.setWordWrap(False)
    app.combo=combo_box();app.combo.addItem('自动读取运行出站');app.combo.activated.connect(app.select_node)
    app.manual=QCheckBox('手动输入节点');app.manual.setChecked(bool(app.config['manual']));body.addLayout(row(app.combo,app.manual))
    fields=QGridLayout();app.host=QLineEdit(app.config['host']);app.port=spin(1,65535,int(app.config['port']))
    app.protocol=QLineEdit(app.config['protocol']);app.transport=combo_box();app.transport.addItems(['TCP','UDP']);app.transport.setCurrentText(app.config['transport'])
    for i,(title_,field) in enumerate([('域名 / IP',app.host),('端口',app.port),('协议',app.protocol),('传输',app.transport)]):
        field.setAccessibleName(title_);fields.addWidget(label(title_,12,MUTED),0,i);fields.addWidget(field,1,i)
    fields.setColumnStretch(0,1);app.port.setMaximumWidth(90);app.protocol.setMaximumWidth(145);app.transport.setMaximumWidth(90)
    app.apply_input_button=button('应用输入',app.changed);fields.addWidget(app.apply_input_button,1,4);body.addLayout(fields)
    app.node_hint=label('从运行配置读取当前端点',12,MUTED);body.addWidget(app.node_hint);layout.addWidget(node)
    route,body=card();head=QHBoxLayout();head.addWidget(label('节点路由',16,bold=True));head.addStretch()
    app.route_count=label('IPv4 / IPv6',12,MUTED);head.addWidget(app.route_count);body.addLayout(head)
    app.route_count.setWordWrap(False)
    app.table=RouteTable();body.addWidget(app.table);layout.addWidget(route)
    app.notice=label('等待读取路由状态',13,MUTED);layout.addWidget(app.notice);layout.addStretch()


def backups(app):
    page,layout=scroll_page();app.pages.addWidget(page)
    title(layout,'备份恢复','恢复前会重新检查网络并展示变更预览；仅管理本工具创建或确认接管的路由。')
    pane,body=card();actions=QHBoxLayout();actions.addWidget(button('刷新备份列表',app.refresh_backups))
    app.choose_backup_button=button('选择备份文件…',app.choose_backup);actions.addWidget(app.choose_backup_button);actions.addStretch();body.addLayout(actions)
    app.backup_list=QListWidget();app.backup_list.setMinimumHeight(180);app.backup_list.currentItemChanged.connect(app.backup_selected);body.addWidget(app.backup_list)
    app.backup_path=QLineEdit();app.backup_path.setReadOnly(True);app.backup_path.setPlaceholderText('从列表或文件选择器指定本工具的备份');body.addWidget(app.backup_path)
    app.restore_button=button('检查并预览恢复',app.prepare_restore,True);body.addWidget(app.restore_button,0,Qt.AlignmentFlag.AlignRight);layout.addWidget(pane)
    layout.addWidget(label('修改前备份位于本机应用数据目录。备份可能含节点和网络信息，分享前请核对。',13,MUTED));layout.addStretch()


def logs(app):
    page=QWidget();page.setObjectName('workspace');layout=QVBoxLayout(page);layout.setContentsMargins(24,22,24,22);layout.setSpacing(16);app.pages.addWidget(page)
    title(layout,'诊断日志','显示本机最近 100 KB 诊断内容。日志不会记录节点密码、订阅链接或完整代理配置。')
    app.log_text=text_box();layout.addWidget(app.log_text,1);layout.addWidget(button('刷新日志',app.refresh_log),0,Qt.AlignmentFlag.AlignRight)


def settings(app):
    page=QWidget();page.setObjectName('workspace');layout=QVBoxLayout(page);layout.setContentsMargins(24,22,24,22);layout.setSpacing(16);app.pages.addWidget(page)
    title(layout,'高级设置','修改先保留为草稿，保存后生效；保存设置不会直接修改任何路由。')
    pane,body=card();close=QHBoxLayout();close.addWidget(label('点击主窗口关闭按钮时',15,bold=True),1)
    app.close_action_menu=combo_box();app.close_action_menu.addItems(list(CLOSE_CHOICES));close.addWidget(app.close_action_menu);body.addLayout(close)
    app.close_action_menu.setMinimumWidth(220)
    body.addWidget(label('可选择每次询问、直接退出或最小化。托盘不可用时使用任务栏。',12,MUTED));layout.addWidget(pane)
    scroll,form=scroll_page();scroll.widget().layout().setContentsMargins(0,0,0,0);layout.addWidget(scroll,1)
    pane,body=card();body.addWidget(label('运行配置路径',13,MUTED))
    app.runtime_picker=RuntimeConfigPicker(pane,start_task=lambda work,done:app.task('正在检测运行配置路径',work,done),stop=app.stop)
    body.addWidget(app.runtime_picker);form.addWidget(pane)
    pane,body=card();fields=QFormLayout();fields.setSpacing(14);fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    app.settings_fields={}
    for key,name in [('wlan','WLAN 网卡名称'),('company','公司连接名称'),('gateway','手动 IPv4 网关'),('gateway6','手动 IPv6 网关'),('cooldown','提醒冷却 / 秒')]:
        field=spin(15,86400,int(app.config.get(key,120))) if key=='cooldown' else QLineEdit(str(app.config.get(key,'')))
        if key.startswith('gateway'):field.setPlaceholderText('留空自动读取 WLAN 当前网关')
        field.setAccessibleName(name);app.settings_fields[key]=field;fields.addRow(name,field)
    app.proxy_port = spin(0, 65535, int(app.config.get('proxy_port', 0)))
    app.proxy_port.setSpecialValueText('自动')
    app.proxy_port.setAccessibleName('本地 SOCKS5 / 混合端口')
    fields.addRow('本地 SOCKS5 / 混合端口', app.proxy_port)
    body.addWidget(label('自动读取运行配置中的监听端口，也可填写本机 SOCKS5 或混合端口。',12,MUTED))
    body.addLayout(fields);form.addWidget(pane);form.addStretch()
    app.settings_hint=label('已有配置可直接继续使用。',12,MUTED);layout.addWidget(app.settings_hint)
    controls=QHBoxLayout();controls.addWidget(button('关于与组件许可',app.about));controls.addStretch();controls.addWidget(button('放弃修改',app.reset_settings))
    app.save_settings_button=button('保存设置',app.save_settings,True);controls.addWidget(app.save_settings_button);layout.addLayout(controls)
