# v2rayN 分流助手 3.0.1 / v2rayN Split Guard 3.0.1

[中文](#chinese) | [English](#english)

<a id="chinese"></a>

## 中文

中文 Windows 网络诊断与节点路由维护工具。界面已迁移至 **PySide6 6.11.3 / Qt Widgets**，保留深青侧栏与浅色卡片；网络诊断、节点解析、备份和路由事务继续使用原有 Python 实现。

此 Git 仓库仅包含源码；下列 `dist/`、`release/` 和 `artifacts/` 为本机构建产物，不随 Git 分发。

### 直接启动

双击 `启动工具.cmd` 或 `dist/V2rayNSplitGuard.exe`。单个 EXE 内含 Python、Qt、PySide6、psutil、图标和所需运行库，接收方无需安装 Python、Conda、Qt 或 VC 运行库。首次启动会释放内置依赖到临时目录，退出后清理。

目标系统为 Windows 10/11 64 位。诊断仍使用系统自带 Windows PowerShell / NetTCPIP、netsh 和 curl.exe。v2rayN、节点和订阅由使用者自行准备。系统组件缺失或受策略限制时，相应检查可能不可用。

分发包为 `release/V2rayNSplitGuard-3.0.1-windows-x64.zip`，包含 EXE、说明、验证记录、第三方许可及 Qt/PySide6 对应源代码。`sources/` 和 `licenses/` 不参与常规启动；分享时请保留完整分发资料。本机设置、日志、路由备份不包含在包内。

上一版 `release/V2rayNSplitGuard-3.0.0-windows-x64.zip` 和 2.0.8 分发包保留用于回退。新旧版使用相同数据格式和目录，切换版本前先退出另一个版本。

3.0.1 改善路由操作等待：点击“应用 / 修复路由”或“核验 / 保存接管选择”后立即显示阶段、耗时及进度动画。只读阶段可取消；包含实际路由变更的任务会等待完成或回滚。没有变更时重新核对节点、DNS、WLAN 及两个路由存储，跳过重复的路由写入流程；有管理范围变更时仍先备份。诊断日志包含固定阶段名称及耗时，不增加凭证或完整配置记录。

### 四个独立页面

- **状态总览**：网络与代理监听、当前节点、路由和代理可用性。节点路由采用 Qt 表格，支持完整 IPv4/IPv6、纵横滚动、完整值提示和 Ctrl+C 复制选中内容。
- **备份恢复**：列出本工具的本机 JSON 备份，可额外选择备份文件。先重新检查网络，再显示恢复预览；确认后才执行。
- **诊断日志**：只读查看最近 100 KB 日志，使用等宽字体；不会将日志中的文本作为 HTML 执行。
- **高级设置**：顶部固定显示关闭行为选项，下方为配置检测、网卡名称、手动网关和提醒冷却。草稿跨页面保留，只有点击保存后生效，“放弃修改”恢复已保存值。

侧栏保留后台监测、检查间隔、提醒摘要和版本，不提供重复的最小化/退出按钮。窗口使用标准系统标题栏。界面与图标均为本地资源，不加载远程网页或字体。

### 首次配置

1. 启动已配置好节点的 v2rayN，连接需要使用的网络。
2. 在高级设置点击“自动检测”运行配置路径。优先识别本地 10808 监听核心的参数，其次识别 v2rayN 子进程，再检查程序目录。
3. 唯一且可确认的加载配置填入草稿；多实例、独立核心、目录候选或合并配置需选择并“采用所选”。也可手动浏览 `binConfigs/config.json`。
4. 设置该机实际的 WLAN 网卡名称和公司拨号连接名称，保存；网关留空即实时读取。
5. 立即检查，选择需要维护的代理出站；必要时勾选手动输入，填写节点地址、当前端口、协议及 TCP/UDP，再应用输入。
6. 需要路由维护时点击“应用 / 修复路由”，逐项核对变更预览并确认。

配置检测在后台执行，不全盘搜索，不探测 UNC 共享，不自动提权。检测期间手动编辑的路径不会被结果覆盖；放弃设置会使未完成检测的旧结果失效。不会复制或记录完整配置及进程命令行。

### 状态与提醒

监测默认开启，约每 15 秒检查一次（任务耗时另计），可调 5–3600 秒。WLAN 接口索引、本机地址、IPv4/IPv6 下一跳、运行节点及 DNS 地址均动态读取。公司拨号未连接时，普通默认路由经 WLAN 不因此报警。

“路由分流正常”仅表示系统对当前节点地址的选路经过 WLAN，专用主机路由与当前网关匹配，ActiveStore / PersistentStore 均存在。此结果是路由证据，不是抓包或实际网卡出口证明。

点击“测试代理”通过 `socks5h://127.0.0.1:10808` 发起 HTTPS 请求，连接超时 5 秒、总超时 12 秒，显示测试站点返回的公网 IP。默认不周期性请求公网；开启“每 60 秒测试代理”后才自动测试。配置、网络或路由变化会使旧测试结果失效，不把失效当成恢复。

后台故障和网关/节点/DNS 变化统一并入提醒摘要。未读批次最多发送一次系统提醒或打开一个非模态摘要窗口，后续只更新状态，不排队补弹。无托盘消息时自动摘要 20 秒收起并保留未读；手动查看取消自动收起。关闭摘要或点击“知道了”视为知晓当前提醒，持续故障仍显示但不重复提醒。确认恢复后再发生、新故障或新配置变化，受默认 120 秒全局冷却限制。最多保留 50 类记录，退出清空。

点击主窗口关闭按钮，默认询问直接退出或最小化。勾选“不再提示”并确定后记住选择，可在高级设置改回每次询问。托盘不可用时使用任务栏。托盘“退出”直接结束程序；有后台任务时等待完成或回滚。工具用于检测和维护，不提供流量阻断。

### 路由修改边界

只维护选中节点的 /32、/128 路由，不修改默认路由、接口 metric、DNS、MAC、网卡驱动、防火墙、TUN、节点或订阅，不重启 v2rayN，不编辑其生成的运行配置，不安装开机启动任务。

已有未接管静态路由默认保留。要更新旧网关或重复记录，需在预览中明确勾选接管；旧节点清理也仅限本工具管理范围。持久化采用 `netsh interface ipv4/ipv6 add route … store=persistent`，分别读取并核验 ActiveStore 和 PersistentStore。

修改前备份相关目标两个存储与管理清单。预览过期、节点/DNS/WLAN 变化或路由并发变更时拒绝执行；失败尽可能恢复，显示具体结果。存在 IPv6 时完整检查和维护，不只修复 IPv4 后显示全部成功。不能把 0.0.0.0 当作热点下一跳。

### 数据和回退

数据目录保持 `%LOCALAPPDATA%/V2rayNSplitGuard`：

| 项目 | 内容 |
|---|---|
| settings.json | 路径、网卡名称、手动节点/网关、关闭偏好与监测设置 |
| managed.json | 本工具创建或确认接管的精确节点路由 |
| diagnostics.log、.1–.3 | 必要诊断信息，每份最多 1 MB |
| backups/*.json | 路由修改前后记录及管理范围 |
| jobs/ | 提权临时请求与结果，任务结束后清理 |

日志不记录密码、认证、订阅、完整配置或访问内容。必要的节点域名/IP、网关及公网 IP 仍属于本机诊断信息，分享前应核对。迁移不会自动重写现有设置；前端选择改变也不会自动写路由。

回退：退出当前版本，解压 3.0.0 或 2.0.8 分发包到另一目录启动即可继续读取原数据。路由恢复通过备份恢复页选择 JSON、核对预览后执行；若当前记录与备份的操作后状态不同，会拒绝覆盖外部变更。

### 开发与构建

在 Windows 64 位 Conda Tools 环境中：

```powershell
conda run -n Tools python -m pip install -r requirements-build.txt
conda run -n Tools python app.py
conda run -n Tools python -m unittest discover -s tests -v
$env:PYTHONPATH = '.'
conda run -n Tools python tests/ui_smoke.py
conda run -n Tools python tests/exit_regression.py
conda run -n Tools python app.py --preview
conda run -n Tools python scripts/fetch_qt_sources.py
conda run -n Tools python scripts/build.py
```

开发下载如需 SOCKS，可向 `fetch_qt_sources.py` 显式传入 `--socks 127.0.0.1:10808`，不会改变系统代理或网络设置。源代码缓存位于被忽略的 build 目录。

Qt 使用 QThread 执行诊断/事务，信号在主线程更新界面；QTimer 负责轮询，退出先取消可停止任务并等待线程结束。使用 QSystemTrayIcon，无 Tk、CustomTkinter、pystray 或 WebView 运行时。

构建采用 PyInstaller onefile，限制为 QtCore、QtGui、QtWidgets、QtSvg 和必要 Windows/ICO/SVG 插件；排除无关 Qt 模块。随后仅复制 EXE 到中文/空格目录，清除开发环境路径，以空白数据目录验证完整页面、真实托盘、独立子进程、不同逻辑 DPI 和退出场景。大小、SHA-256、结果见 `artifacts/portable-build.json`。

`--diagnose` 只读输出经过字段白名单脱敏的状态，`--proxy-test` 才发起额外 HTTPS 请求。开发预览仅使用文档示例地址和模拟后台，禁止实际路由写入。未实测场景及限制见 VALIDATION.md。

### 第三方组件

本程序使用动态链接的 Qt/PySide6 社区组件，原始许可及对应源代码随分发包提供。可使用 `--qt-runtime` 指定兼容的用户修改版 Qt/PySide6 运行库；正常启动使用内置依赖。详细替换与重建方法见 `licenses/REBUILDING.txt`。本工具未修改第三方 Qt 源码，第三方组件许可见随附说明。

<a id="english"></a>

## English

A Windows network diagnostic and proxy-node route maintenance application with a Chinese interface. The frontend uses **PySide6 6.11.3 / Qt Widgets**, with a dark teal sidebar and light cards. Python handles network inspection, node parsing, backups, and route transactions.

### Run a packaged build

Double-click `启动工具.cmd` or `dist/V2rayNSplitGuard.exe`. The single-file executable bundles Python, Qt, PySide6, psutil, icons, and the required runtime libraries. Recipients do not need to install Python, Conda, Qt, or the VC runtime. Startup extracts the bundled dependencies to a temporary directory, which is cleaned up on exit.

The target platform is Windows 10/11 x64. Diagnostics use the system's Windows PowerShell / NetTCPIP, netsh, and curl.exe. Supply your own v2rayN installation, nodes, and subscriptions. Missing system components or restrictive policies may make individual checks unavailable.

This Git repository contains source code. The `dist/`, `release/`, and `artifacts/` directories below refer to local build outputs and are not included in Git.

The distribution archive is `release/V2rayNSplitGuard-3.0.1-windows-x64.zip`. It contains the EXE, instructions, validation record, third-party notices, and corresponding Qt/PySide6 sources. The `sources/` and `licenses/` materials are not needed during normal startup, but should be retained when redistributing the package. Personal settings, logs, and route backups are excluded.

Previously built 3.0.0 and 2.0.8 packages can be retained for rollback. The data format and directory remain compatible; exit one version before starting another.

In 3.0.1, route preview and verification display the current stage, elapsed time, and an activity indicator immediately. Read-only checks can be cancelled. Tasks containing route changes wait for completion or rollback. A no-change operation revalidates the node, DNS, WLAN, and both route stores without repeating the write workflow; management-record changes still receive a backup. Diagnostic logs add fixed stage names and timings without credentials or full configurations.

### Four pages

- **Overview / 状态总览:** network and proxy-listener status, the selected node, routes, and proxy availability. The Qt table supports full IPv4/IPv6 values, scrolling, full-value tooltips, and Ctrl+C for selected cells.
- **Backup and restore / 备份恢复:** list local JSON backups or choose another backup file. Recheck the network and review a restore preview before explicitly applying it.
- **Diagnostic logs / 诊断日志:** read the latest 100 KB in a monospaced view. Log text is not interpreted as HTML.
- **Advanced settings / 高级设置:** close behavior, runtime configuration detection, adapter names, manual gateways, and reminder cooldown. Drafts survive page switches; Save applies them, while Discard restores saved values.

The sidebar contains monitoring controls, the interval, reminder summary, and version. The window uses the system title bar. UI assets and icons are local; no remote web pages or fonts are loaded.

### First-time setup

1. Start v2rayN with a configured node and connect the networks you intend to use.
2. In Advanced settings, automatically detect the runtime configuration path. Detection prioritizes the core listening on local port 10808, then v2rayN child processes, then application directories.
3. A unique, confirmed loaded configuration is filled into the draft. Multiple instances, standalone cores, directory candidates, or merged configurations require reviewing a candidate and choosing Adopt selected. You can also browse to `binConfigs/config.json` manually.
4. Enter this computer's actual WLAN adapter name and company dial-up connection name, then save. Leave gateways blank to read them dynamically.
5. Run an immediate check and choose the proxy outbound to maintain. If necessary, enable manual input and enter the node address, current port, protocol, and TCP/UDP transport, then apply the input.
6. When maintenance is needed, choose Apply / repair routes, review each proposed change, and confirm explicitly.

Detection runs in the background. It does not search entire disks, probe UNC shares, or elevate automatically. Results do not overwrite paths edited during detection, and discarding settings invalidates pending results. Full configurations and process command lines are neither copied nor logged.

### Status, testing, and reminders

Monitoring is enabled by default and checks approximately every 15 seconds, plus task duration. The interval is adjustable from 5 to 3600 seconds. WLAN interface index, local addresses, IPv4/IPv6 next hops, runtime node, and DNS addresses are read dynamically. A normal default route through WLAN is not treated as a split-routing failure when the company dial-up connection is offline.

“路由分流正常” means the system selects WLAN for the current node addresses, the dedicated host routes match the current gateway, and both ActiveStore and PersistentStore entries exist. This is route evidence, not packet-capture proof of the physical egress interface.

Test proxy sends an HTTPS request through `socks5h://127.0.0.1:10808`, with a 5-second connection timeout and a 12-second total limit. It displays the public IP returned by the test service. Periodic public requests are off by default; enable the 60-second proxy test explicitly to use them. Configuration, network, or route changes invalidate old results without treating invalidation as recovery.

Background faults and gateway/node/DNS changes are merged into the reminder summary. An unread batch produces at most one system notification or one nonmodal summary window; later checks update it without queuing popups. When tray messages are unavailable, an automatic summary closes after 20 seconds while retaining unread state. Opening it manually cancels that timer. Closing or acknowledging the summary acknowledges the current reminders, so an ongoing fault remains visible without repeated alerts. A confirmed recovery followed by recurrence, a new fault, or a new configuration event can notify again, subject to the default 120-second global cooldown. At most 50 categories are retained; they are cleared on exit.

The window close button asks whether to exit or minimize by default. Confirming Remember this choice stores the preference; Advanced settings can restore Ask every time. If the tray is unavailable, minimizing uses the taskbar. The tray's Exit action exits directly, waiting for active work to complete or roll back. The tool diagnoses and maintains routes; it does not block traffic.

### Route-maintenance boundaries

Only selected-node `/32` and `/128` host routes are maintained. The application does not change default routes, interface metrics, DNS, MAC settings, drivers, firewall rules, TUN settings, nodes, or subscriptions. It does not restart v2rayN, edit its generated runtime configuration, or install a startup task.

Existing unmanaged static routes are preserved by default. Updating old gateways or duplicate records requires explicitly adopting them in the preview. Old-node cleanup is limited to the tool's management scope. Persistence uses `netsh interface ipv4/ipv6 add route … store=persistent`, followed by separate reads of ActiveStore and PersistentStore.

Before changes, the tool backs up the affected targets in both stores and the management ledger. It rejects expired previews, node/DNS/WLAN changes, and concurrent route changes. Failures trigger recovery where possible and report specific results. IPv6 addresses are checked and maintained as well; fixing IPv4 alone does not establish complete success. `0.0.0.0` must not replace the hotspot's real next hop.

### Local data and rollback

The data directory remains `%LOCALAPPDATA%/V2rayNSplitGuard`:

| Item | Content |
| --- | --- |
| `settings.json` | Paths, adapter names, manual node/gateway values, close behavior, and monitoring settings |
| `managed.json` | Exact node routes created or explicitly adopted by the tool |
| `diagnostics.log`, `.1`–`.3` | Necessary diagnostics, up to 1 MB per file |
| `backups/*.json` | Route and management-scope records before and after operations |
| `jobs/` | Temporary elevation requests and results, cleaned up after each task |

Logs exclude passwords, authentication data, subscriptions, full configurations, and visited content. Necessary node domains/IPs, gateways, and public IPs remain local diagnostic information and should be reviewed before sharing. The frontend migration does not automatically rewrite existing settings or apply route changes.

To roll back, exit the current version and run a previously built 3.0.0 or 2.0.8 package from another directory using the existing data. To restore routes, choose a JSON backup, review the preview, and confirm. If current records differ from the backup's post-operation state, the tool refuses to overwrite external changes.

### Develop and build

Run from the repository root in a Windows x64 Conda environment named `Tools`:

```powershell
conda run -n Tools python -m pip install -r requirements-build.txt
conda run -n Tools python app.py
conda run -n Tools python -m unittest discover -s tests -v
$env:PYTHONPATH = '.'
conda run -n Tools python tests/ui_smoke.py
conda run -n Tools python tests/exit_regression.py
conda run -n Tools python app.py --preview
conda run -n Tools python scripts/fetch_qt_sources.py
conda run -n Tools python scripts/build.py
```

If developer downloads need SOCKS, explicitly pass `--socks 127.0.0.1:10808` to `fetch_qt_sources.py`. This does not change the system proxy or network settings. Sources are cached in the ignored `build/` directory.

QThread performs diagnostics and transactions; queued signals update the interface on the main thread. QTimer handles polling. Exit cancels stoppable tasks and waits for threads to finish. The tray uses QSystemTrayIcon, without Tk, CustomTkinter, pystray, or a WebView runtime.

PyInstaller builds a single-file executable containing QtCore, QtGui, QtWidgets, QtSvg, and necessary Windows/ICO/SVG plugins while excluding unrelated Qt modules. Validation copies only the EXE into a new directory with Chinese characters and spaces, clears development-environment paths, and uses empty application data to exercise pages, the real tray, an independent child process, simulated DPI levels, and exit scenarios. Size, SHA-256, and results are recorded in `artifacts/portable-build.json`.

`--diagnose` exports only a redacted status allowlist; `--proxy-test` adds an explicit HTTPS test. The developer preview uses documentation-only addresses and simulated workers and forbids actual route writes. See [VALIDATION.md](VALIDATION.md) for tested scenarios and limitations.

### Third-party components

The application dynamically links community Qt/PySide6 components. Their original notices and corresponding sources accompany distribution packages. `--qt-runtime` can select a compatible user-modified Qt/PySide6 runtime; normal startup uses bundled dependencies. See [licenses/REBUILDING.txt](licenses/REBUILDING.txt) for replacement and rebuilding instructions. The tool does not modify third-party Qt source code.
