# macOS / Linux 运行说明

Windows 原有的 PowerShell 启动方式保留。新增的 `app/cli.py` 用 Python 管理热点模式的三个服务：443 反向代理、DNS 重定向和 8900 看板。

## 安装依赖

从 macOS/Linux Release 包解压后，在项目目录运行安装脚本；它会创建 `.venv` 并安装 Python 依赖：

```sh
./install.sh
```

也可以手动执行 `python3 -m venv .venv` 和 `.venv/bin/python -m pip install -r app/requirements.txt`。

## 配置网络

先用系统的网络管理工具创建 Wi-Fi 热点，并开启上行网络共享。确认热点接口有固定 IPv4 地址；热点客户端的 DNS 请求需要发往这台电脑。Linux 可用 NetworkManager 或 hostapd，macOS 可在系统设置中配置互联网共享。热点接口和上行接口由各操作系统管理，`cli.py` 不会改写网络、路由或防火墙配置。

## 启动服务

把命令里的 `10.42.0.1` 换成热点接口的 IPv4 地址。443 和 53 是特权端口，因此 macOS/Linux 需要以管理员权限运行服务；启动、查看和停止都使用同一权限级别：

```sh
./fsd-mitm start --ip 10.42.0.1
./fsd-mitm status
./fsd-mitm stop
```

`fsd-mitm` 会通过 `sudo` 运行服务管理命令。Windows Release 包保留 `install.ps1` 和“一键安装.cmd”。

如果车机 IP 固定，可补充 `--car-ip 10.42.0.20`，看板会用它显示二层连通状态和 443 连接。默认端口为 TCP 443、UDP 53、看板 TCP 8900；可用 `--https-port`、`--dns-port` 和 `--dashboard-port` 调整。

服务日志和进程记录放在 `app/logs/`。`stop` 只停止 CLI 记录且命令行仍匹配本项目服务标记的进程。

## Python 代码入口

- `app/cli.py`：`argparse` 子命令、虚拟环境程序路径解析、子进程启动与状态记录。
- `app/dns_sink.py`：`--bind` 让 DNS 只监听热点接口地址；默认仍监听所有 IPv4 网卡。
- `app/web/fsd_panel.py`：按 Windows、Linux、macOS 选择连接状态和 `ping` 命令；车机 IP/MAC 可通过环境变量配置。
- `app/requirements.txt`：Windows 专用依赖用 `sys_platform` 条件标记，避免在 macOS/Linux 安装。

这个入口负责应用服务，不负责自动创建热点，也不自动开放系统防火墙。使用前需要自行配置热点、共享、客户端 DNS 和入站访问规则。

Release 包不携带仓库中的预生成 mitmproxy CA 私钥；首次启动时会在本机生成 CA。需要在车机上信任新生成的 CA 后，TLS 拦截才能正常工作。

当前 macOS/Linux 入口只覆盖热点模式的应用服务；Windows 的 `start_all.ps1` 路由模式、ARP 引流和 Windows 热点管理仍由原有脚本负责。

## GitHub Actions

`.github/workflows/platform-smoke.yml` 在 `ubuntu-latest` 和 `macos-latest`、Python 3.12 上安装依赖并运行 `app/tests/platform_smoke.py`。冒烟测试使用回环地址和临时高端口，不需要管理员权限，也不会改系统网络设置；它验证服务启动、DNS 回答、看板 API、状态查询和停止清理。修改 `app/` 或本说明时会在 push / pull request 运行，也可以手动触发。

`.github/workflows/release-packages.yml` 会为 Windows 生成 ZIP，为 macOS 和 Linux 各生成 TAR.GZ。推送 `v*` 标签时会自动创建 GitHub Release 并附上三个包；手动运行该工作流只生成可下载的 Actions artifact。
