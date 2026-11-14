"""Scoped, previewed route transactions. No writes occur during discovery."""
from __future__ import annotations
from copy import deepcopy
import ipaddress
from pathlib import Path
import time
import uuid
import re
from .common import DATA, save_json, read_json, run, timestamp,stage,check_cancelled
from .network import snapshot, route_key, wlan_info,read_routes


def identity(r):
    return (r['prefix'], int(r['index']), r['gateway'], int(r['metric']))


def signatures(rows):
    # A protocol-only replacement is still an external route change.
    return sorted(route_key(r)+(int(r.get('protocol',3)),) for r in rows)


def validate_route(r):
    n = ipaddress.ip_network(r['prefix'], strict=True)
    g = ipaddress.ip_address(r['gateway'])
    if n.prefixlen != n.max_prefixlen or n.version != g.version or g.is_unspecified or g.is_multicast or n.network_address.is_loopback or n.network_address.is_multicast or n.network_address.is_unspecified:
        raise ValueError('仅允许带真实下一跳的 /32 或 /128 节点路由')
    if not 1 <= int(r['index']) <= 2**32-1 or not 0 <= int(r['metric']) <= 65535:
        raise ValueError('路由接口索引或 metric 不合法')
    if r['store'] not in ('ActiveStore','PersistentStore'):
        raise ValueError('不支持的路由存储')


def plan_routes(report, config, managed, adopt=False, cleanup=False):
    if not report['node'] or not report['addresses']:
        raise ValueError('需要先识别并解析当前节点')
    wlan = report['wlan']
    if not wlan['connected'] or not wlan['index']:
        raise ValueError('WLAN 未连接，无法准备变更')
    desired = []
    for ip in report['addresses']:
        v6 = ':' in ip
        gw = config.get('gateway6' if v6 else 'gateway') or wlan['gateway6' if v6 else 'gateway']
        if not gw:
            raise ValueError(f'{ip} 缺少 WLAN {"IPv6" if v6 else "IPv4"} 网关；不能只修复部分地址后视为全部成功')
        for store in ('ActiveStore','PersistentStore'):
            r = dict(prefix=f'{ip}/{128 if v6 else 32}',index=wlan['index'],alias=config.get('wlan',wlan['alias']),gateway=gw,metric=1,ifmetric=0,store=store)
            validate_route(r)
            desired.append(r)
    prefixes = {r['prefix'] for r in desired}
    owned = {identity(r) for r in managed}
    if cleanup:
        prefixes.update(r['prefix'] for r in managed)
    before = [r for r in report['net']['routes'] if r['prefix'] in prefixes]
    wanted = {identity(r) for r in desired}
    removable = [r for r in before if r.get('protocol',3)==3 and (identity(r) in owned or (adopt and r['prefix'] in {x['prefix'] for x in desired}))]
    # Preserve every unmanaged entry. Adoption is explicit and visible in preview.
    after = [r for r in before if r not in removable]
    for d in desired:
        same = next((r for r in before if route_key(r)==route_key(d)), None)
        if not any(route_key(x)==route_key(d) for x in after):
            after.append(same or d)
    for d in desired:
        if any(r['prefix']==d['prefix'] and r['index']==d['index'] and r['gateway']==d['gateway'] and r['store']==d['store'] and r['metric']!=d['metric'] for r in after):
            raise ValueError('已有相同目标、网卡、下一跳但 metric 不同的路由。请核对后勾选接管，避免对象已存在错误。')
    creates = [r for r in after if route_key(r) not in {route_key(x) for x in before}]
    deletes = [r for r in before if route_key(r) not in {route_key(x) for x in after}]
    claims = [r for r in after if identity(r) in wanted and (adopt or identity(r) in owned or any(identity(c)==identity(r) for c in creates))]
    keep_owned = [r for r in managed if r['prefix'] not in prefixes]
    return dict(version=1,kind='apply',id=uuid.uuid4().hex,created=time.time(),time=timestamp(),
                wlan=wlan,alias=config.get('wlan',wlan['alias']),before=before,after=after,creates=creates,deletes=deletes,
                managed_before=managed,managed_after=keep_owned+claims,adopt=adopt,cleanup=cleanup,
                node_guard=dict(runtime=config.get('runtime'),manual=config.get('manual',False),node=report['node'],addresses=report['addresses']))


def preview_text(plan):
    lines = ['修改范围：仅以下节点主机路由；不修改默认路由、接口优先级或 DNS。',
             f'WLAN 当前接口索引：{plan.get("wlan",{}).get("index", "恢复任务")}',
             '接管现有路由：'+('是（仅本预览所列目标）' if plan.get('adopt') else '否'), '']
    for verb, key in [('移除旧记录','deletes'),('写入新记录','creates')]:
        for r in plan[key]:
            lines.append(f'{verb}  {r["prefix"]}  网卡 {r.get("alias", "")} (#{r["index"]})  网关 {r["gateway"]}  metric={r["metric"]}  持久化={"是" if r["store"]=="PersistentStore" else "否"}')
    if not plan['creates'] and not plan['deletes']:
        lines.append('路由记录已符合预期；无需写入。仅在勾选接管时记录管理范围。')
    lines.extend(['', '变更前 → 变更后（包含保留的其他路由）：'])
    for r in plan['before']:
        lines.append('旧  '+str(route_key(r)))
    for r in plan['after']:
        lines.append('新  '+str(route_key(r)))
    lines.extend(['', '执行前会重新读取 WLAN 和两个路由存储；预览已过期或状态变化将拒绝执行。',
                  '备份在任何修改前写入；失败后尽可能恢复，恢复失败会保留详细结果。'])
    return '\n'.join(lines)


class WindowsRoutes:
    def __init__(self,prefixes=None):self.prefixes=prefixes

    def read(self):
        return read_routes(self.prefixes)

    def add(self, r):
        validate_route(r)
        if route_key(r) in {route_key(x) for x in self.read()}:
            return
        if int(r.get('protocol',3))!=3:
            raise ValueError('拒绝写入非 NetMgmt 静态路由')
        family = 'ipv6' if ':' in r['gateway'] else 'ipv4'
        store = 'persistent' if r['store']=='PersistentStore' else 'active'
        run(['netsh.exe','interface',family,'add','route',f'prefix={r["prefix"]}',
             f'interface={int(r["index"])}',f'nexthop={r["gateway"]}',
             f'metric={int(r["metric"])}',f'store={store}'], 20)

    def remove(self, r):
        validate_route(r)
        matches=[x for x in self.read() if route_key(x)==route_key(r)]
        if not matches:
            return
        if int(r.get('protocol',3))!=3 or any(int(x.get('protocol',3))!=3 for x in matches):
            raise ValueError('路由协议已变化或不是 NetMgmt 静态路由，拒绝删除')
        family = 'ipv6' if ':' in r['gateway'] else 'ipv4'
        store = 'persistent' if r['store']=='PersistentStore' else 'active'
        run(['netsh.exe','interface',family,'delete','route',f'prefix={r["prefix"]}',
             f'interface={int(r["index"])}',f'nexthop={r["gateway"]}',f'store={store}'],20)


def reconcile(backend, expected, target, allowed):
    """Touch exact authorized identities, with PersistentStore before ActiveStore.

    netsh may mirror persistent operations to ActiveStore; reread after each step.
    """
    prefixes = {r['prefix'] for r in expected+target}
    target_keys = {route_key(r) for r in target}
    # Persistent first, then active: restores active-only and persistent-only snapshots.
    for store in ('PersistentStore','ActiveStore'):
        current = [r for r in backend.read() if r['prefix'] in prefixes]
        for r in current:
            if r['store']==store and route_key(r) not in target_keys:
                if identity(r) not in allowed:
                    raise RuntimeError('发现未经授权或并发改变的路由，拒绝删除：'+str(route_key(r)))
                if int(r.get('protocol',3))!=3:
                    raise RuntimeError('发现非 NetMgmt 路由，拒绝删除：'+str(route_key(r)))
                backend.remove(r)
                current=[x for x in backend.read() if x['prefix'] in prefixes]
        for r in target:
            if r['store']==store and route_key(r) not in {route_key(x) for x in current}:
                backend.add(r)
                current=[x for x in backend.read() if x['prefix'] in prefixes]
    current = [r for r in backend.read() if r['prefix'] in prefixes]
    if signatures(current) != signatures(target):
        raise RuntimeError('ActiveStore/PersistentStore 核验不一致；不会显示修复成功')


def execute(plan, backend=None, backup_dir=None, check_wlan=True, ledger_path=None,*,stop=None,progress=None):
    if not isinstance(plan.get('id'),str) or not re.fullmatch(r'[0-9a-f]{32}',plan['id']):
        raise ValueError('路由计划编号无效')
    native=backend is None
    for r in plan['before']+plan['after']:
        validate_route(r)
    if any(r.get('protocol',3)!=3 for r in plan['creates']+plan['deletes']):
        raise ValueError('拒绝修改非 NetMgmt 静态路由')
    if not 0 <= time.time()-plan['created'] < 180:
        raise ValueError('变更预览已超过 3 分钟，请重新检查')
    prefixes = {r['prefix'] for r in plan['before']+plan['after']}
    backend = backend if backend is not None else WindowsRoutes(prefixes)
    noop=not plan['creates'] and not plan['deletes']
    if noop and signatures(plan['before'])!=signatures(plan['after']):raise ValueError('路由计划差异不一致')
    net=None
    if check_wlan and plan['kind']=='apply':
        from .nodes import read_nodes, resolve
        guard=plan.get('node_guard',{})
        if guard.get('runtime'):
            if not guard['manual']:
                nodes,_=stage('重新确认运行节点',lambda:read_nodes(guard['runtime']),stop,progress)
                selected=next((n.to_dict() for n in nodes if n.tag==guard['node']['tag']),None)
                if selected!=guard['node']:
                    raise ValueError('运行节点配置在预览后变化，请重新检查')
        if guard.get('node') and sorted(stage('重新确认节点 A / AAAA 地址',lambda:resolve(guard['node']['host'],stop),stop,progress))!=sorted(guard['addresses']):
            raise ValueError('节点 DNS 地址在预览后变化，请重新检查')
        net=stage('核对 WLAN、网关及两个路由存储',lambda:snapshot(stop),stop,progress)
        current = wlan_info(net, plan['alias'])
        if current != plan['wlan']:
            raise ValueError('WLAN 状态或网关已变化，请重新检查并生成预览')
    current = [r for r in (net['routes'] if native and net is not None else stage('核对路由是否发生并发变化',backend.read,stop,progress)) if r['prefix'] in prefixes]
    if signatures(current)!=signatures(plan['before']):
        raise ValueError('路由自预览后已变化，已停止；请重新检查')
    check_cancelled(stop)
    if not 0 <= time.time()-plan['created'] < 180:raise ValueError('变更预览已超过 3 分钟，请重新检查')
    ledger_changed=plan['managed_before']!=plan['managed_after']
    if noop and not ledger_changed:
        return dict(ok=True,message='核验通过；ActiveStore / PersistentStore 与预览一致，未修改路由，无需更新管理记录。',backup='',route_changed=False)
    allowed = {identity(r) for r in plan['creates']+plan['deletes']}
    path = Path(backup_dir or DATA/'backups') / f'{time.strftime("%Y%m%d-%H%M%S")}-{plan["id"]}.json'
    backup = deepcopy(plan)
    backup.update(status='prepared', backup_time=timestamp())
    if progress:progress('备份变更前记录')
    save_json(path, backup)  # Failure to write the backup aborts before mutation.
    try:
        # Cancellation ends at the transaction boundary. Never interrupt writes/rollback.
        if not noop:stage('应用差异并核验两个路由存储',lambda:reconcile(backend, plan['before'], plan['after'], allowed),progress=progress)
        elif progress:progress('保存已确认的管理范围')
        save_json(ledger_path or DATA/'managed.json', plan['managed_after'])
        backup.update(status='committed',completed=timestamp())
        save_json(path, backup)
        return dict(ok=True,message='核验通过；未修改路由，已保存管理范围。' if noop else '路由已写入并分别核验 ActiveStore / PersistentStore',backup=str(path),route_changed=not noop)
    except Exception as e:
        rollback_error = ''
        try:
            if progress:progress('操作失败，正在恢复本次变更')
            if not noop:reconcile(backend, plan['after'], plan['before'], allowed)
            save_json(ledger_path or DATA/'managed.json', plan['managed_before'])
        except Exception as rollback_exception:
            rollback_error = str(rollback_exception)
        backup.update(status='rollback_failed' if rollback_error else 'rolled_back',
                      error=str(e),rollback_error=rollback_error,completed=timestamp())
        save_json(path, backup)
        return dict(ok=False,message=f'修改失败：{e}\n'+(f'自动恢复未完成：{rollback_error}' if rollback_error else '本次变更已恢复至备份状态'),backup=str(path),route_changed=not noop)


def restore_plan(path, current):
    b = read_json(path)
    if not b or b.get('version')!=1 or b.get('status') not in ('committed','rollback_failed','prepared'):
        raise ValueError('请选择本工具的有效备份；已自动恢复的备份无需重复恢复')
    prefixes = {r['prefix'] for r in b['before']+b['after']}
    now = [r for r in current if r['prefix'] in prefixes]
    if signatures(now)!=signatures(b['after']):
        raise ValueError('当前路由与备份的操作后状态不一致（可能有外部修改）。为避免覆盖，已拒绝自动恢复；可根据备份人工核对。')
    p = deepcopy(b)
    p.update(kind='restore',id=uuid.uuid4().hex,created=time.time(),time=timestamp(),
             before=now,after=b['before'],managed_before=b['managed_after'],managed_after=b['managed_before'])
    p['creates']=[r for r in p['after'] if route_key(r) not in {route_key(x) for x in now}]
    p['deletes']=[r for r in now if route_key(r) not in {route_key(x) for x in p['after']}]
    return p
