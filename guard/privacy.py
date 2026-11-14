"""Public diagnostic summaries never contain endpoint or device identifiers."""
import ipaddress


def public_diagnostic(report):
    def family(value):
        return ipaddress.ip_address(value).version
    node=report.get('node') or {}
    wlan=report.get('wlan') or {}
    result=dict(schema=1,redacted=True,time=report.get('time'),
        network=dict(wlan_connected=bool(wlan.get('connected')),company_connected=bool(report.get('company')),
                     ipv4_gateway_available=bool(wlan.get('gateway')),ipv6_gateway_available=bool(wlan.get('gateway6'))),
        node=dict(identified=bool(node),transport=node.get('transport') if node.get('transport') in ('TCP','UDP') else 'unknown',
                  resolved_addresses=len(report.get('addresses',[])),
                  address_families=sorted({family(ip) for ip in report.get('addresses',[])})),
        proxy_listener=bool(report.get('listener')),dns_failed=bool(report.get('dns_error')),
        fault_count=len(report.get('faults',[])),routes=[])
    for row in report.get('rows',[]):
        result['routes'].append(dict(family=family(row['ip']),via_wlan=bool(row['via_wlan']),
            active=bool(row['active']),persistent=bool(row['persistent']),gateway_match=bool(row['gateway_match']),ok=bool(row['ok'])))
    if report.get('proxy_test'):
        result['proxy_test']=dict(ok=bool(report['proxy_test']['ok']),public_ip_redacted=True)
    return result
