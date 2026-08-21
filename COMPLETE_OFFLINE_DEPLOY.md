# SAR Manager 0.2.4：CentOS 7 x86-64 完整离线部署

`offline` 目录包含在一台空的 CentOS 7 x86-64 服务器上部署所需的全部资源，
运行时不需要访问 Docker Hub、PyPI、npm 或 CentOS 软件源。

## 包含内容

- Docker CE 20.10.24、Docker CLI 和 containerd
- Docker Compose 插件 2.27.1
- Docker 所需的 CentOS 7 RPM 依赖和本地 Yum 仓库元数据
- SAR Manager 0.2.4 API、测试前端和 PostGIS 的 linux/amd64 镜像
- CentOS/Docker RPM 签名密钥
- SHA-256 完整性清单和一键安装脚本

目标机器仍须预先安装可启动的 CentOS 7 操作系统。此目录不是操作系统安装盘，
不包含 Linux 内核、引导程序或硬件驱动。

## 复制与校验

将完整 `offline` 目录复制到服务器，例如 `/root/offline`。不要单独复制
`install-all.sh`。

可先校验：

```bash
cd /root/offline
sha256sum -c SHA256SUMS
```

## 全新安装

```bash
cd /root/offline
chmod +x install-all.sh
sudo ./install-all.sh
```

如果 `/opt/sar-manager-offline-0.2.4-centos7-amd64` 已存在，脚本会更新其中的应用包文件并保留原 `.env`，
因此同版本重新打包后也能正确升级，不会继续使用旧镜像文件。

完成后编辑：

```bash
vi /opt/sar-manager-offline-0.2.4-centos7-amd64/.env
```

至少设置：

```dotenv
POSTGRES_PASSWORD=请替换为强密码
SAR_DATA_DIR=/实际的/SAR/数据目录
SAR_UPLOAD_DIR=/upload
SAR_API_PORT=8000
SAR_TRANSFER_SOURCE_DIR=/mnt/sar-shares
TRANSFER_SOURCE_ROOTS={"sar-storage-01":"/transfer-sources/sar-storage-01"}
```

随后启动并扫描：

```bash
cd /opt/sar-manager-offline-0.2.4-centos7-amd64
sudo ./install.sh
sudo ./manage.sh health
sudo ./manage.sh data-dir
sudo ./manage.sh scan
```

少量新增产品请放在 `/upload/gf3`、`/upload/strix` 等来源子目录中，再执行：

```bash
sudo ./manage.sh ingest gf3/批次目录/产品目录或压缩包
```

系统会将该产品移动到最终数据目录并只扫描这一项。完整规则见应用目录的 `README.md`。

若需从局域网已挂载共享搬运数据，`SAR_TRANSFER_SOURCE_DIR` 是宿主机的共享挂载点；Docker 会将其只读挂载为 `/transfer-sources`。`TRANSFER_SOURCE_ROOTS` 用 JSON 为可调用的服务器名称映射容器内目录。搬运完成后系统会自动将产品定向入库到 `SAR_DATA_DIR/{source}`，但不生成缩略图。确保 `SAR_DATA_DIR` 对 API 容器可写；修改 `.env` 后执行 `sudo ./manage.sh restart`。
创建任务前会按产品编号检查数据库，已存在的数据标记为 `SKIPPED` 并跳过网络搬运；Web 页面每 3 秒刷新全部任务和逐文件进度。

浏览器访问：

```text
http://服务器IP:8000/web/
```

## 从旧版升级并保留数据

先停止旧服务，再在新目录的 `.env` 中设置旧项目名，以复用旧数据库卷：

```bash
cd /opt/sar-manager-offline-0.2.0-centos7-amd64
sudo ./manage.sh stop

cd /opt/sar-manager-offline-0.2.4-centos7-amd64
cp /opt/sar-manager-offline-0.2.0-centos7-amd64/.env .env
```

编辑 `.env`，确认：

```dotenv
SAR_API_IMAGE=sar-manager-api:0.2.4
COMPOSE_PROJECT_NAME=sar-manager-offline-0.2.0-centos7-amd64
```

随后运行 `sudo ./install.sh`。不要执行 `docker compose down -v`。

## 常用命令

```bash
cd /opt/sar-manager-offline-0.2.1-centos7-amd64
sudo ./manage.sh status
sudo ./manage.sh logs
sudo ./manage.sh scan
sudo ./manage.sh restart
```

如果其他电脑无法访问，按内网安全要求开放实际 API 端口。PostgreSQL 端口没有映射
到宿主机。
