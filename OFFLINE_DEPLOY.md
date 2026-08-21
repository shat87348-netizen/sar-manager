# SAR Manager：CentOS 7 离线部署

本部署包适用于 **CentOS 7 x86_64**。包内已经包含 SAR Manager API、静态测试前端和 PostGIS 的 `linux/amd64` Docker 镜像，运行时不访问 Docker Hub、PyPI 或 npm。

## 服务器前置条件

- x86_64/amd64 服务器
- Docker Engine 20.10 或更高版本，且 Docker 服务已启动
- 以下任一种 Compose：
  - `docker compose` 插件
  - `docker-compose` 1.29 或更高版本
- SAR 数据已经位于服务器本地目录
- 至少预留约 3 GB 磁盘空间给镜像、数据库和日志；SAR 原始数据空间另计

CentOS 7 已停止官方维护。本部署包不包含 Docker 的 RPM 安装包，因为 RPM 依赖与服务器已安装的软件源、内核和 Docker 版本有关；请先在目标服务器准备好 Docker 环境。

## 安装

将整个 `.tar.gz` 文件复制到服务器，然后执行：

```bash
tar -xzf sar-manager-offline-0.2.4-centos7-amd64.tar.gz
cd sar-manager-offline-0.2.4-centos7-amd64
./install.sh
```

第一次运行会创建 `.env` 并提示停止。编辑 `.env`：

```dotenv
POSTGRES_PASSWORD=请替换为强密码
SAR_DATA_DIR=/实际的/SAR/数据目录
SAR_API_PORT=8000
```

`SAR_DATA_DIR` 可以指向包含普通目录、ZIP、TAR、TAR.GZ 或 TGZ 的上级目录。保存后再次安装：

```bash
./install.sh
./manage.sh health
./manage.sh scan
```

Compose 挂载会为 `SAR_DATA_DIR` 和 `SAR_UPLOAD_DIR` 使用共享 SELinux 容器标签，
以支持默认启用 SELinux enforcing 的 CentOS/RHEL 7 本地磁盘目录。API 对数据目录
仍保持只读，扫描器和定点入库容器按需使用读写挂载。

`scan` 会启动独立的低优先级扫描容器，默认最多使用 1 个 CPU；扫描期间 API 仍可查询。重复扫描会跳过描述文件内容未变化的数据。若描述文件未变、但 TIFF 或缩略图等关联文件有变更，执行完整重新归纳：

```bash
./manage.sh scan-force
```

从不含完整目录文件索引的旧版本升级后，也需要执行一次 `scan-force`，为已有产品建立
XML、JSON、KML、TIFF、PNG 等文件索引。

可在 `.env` 中按服务器性能调整扫描器限制：

```dotenv
SCANNER_CPUS=1.0
SCANNER_NICE=15
SCANNER_WRITE_DELAY_MS=20
PUBLIC_BASE_URL=http://服务器IP:8000
```

`PUBLIC_BASE_URL` 用于生成可直接转发给其他人的完整文件 URL。留空时使用调用接口时的
主机和端口。系统不会给文件 URL 增加访问令牌或有效期。

## 少量新增数据的定点入库

不要为新增一两个产品执行全量 `scan`。将待入库产品放在暂存目录的来源子目录中；默认暂存目录为 `/upload`，可在 `.env` 用 `SAR_UPLOAD_DIR` 修改。

```text
/upload/gf3/20260803/GF3_product.zip
/upload/strix/batch-01/product-directory/
```

执行定点入库：

```bash
./manage.sh ingest gf3/20260803/GF3_product.zip
./manage.sh ingest strix/batch-01/product-directory
```

系统会先校验 XML/JSON 识别出的来源与暂存目录名称一致，再把文件移动到 `SAR_DATA_DIR` 下对应的 `gf3`、`strix` 等最终目录，最后只扫描该产品。成功后暂存路径不再保留原文件。传入的路径只能位于 `/upload` 下，且不允许符号链接或 `..` 路径。

如 XML/JSON 未变化、但关联 TIFF 或缩略图发生变化，可使用：

```bash
./manage.sh ingest-force gf3/20260803/GF3_product.zip
```

请在复制完成后再执行入库；推荐先复制为临时名称、完成后改名，或使用批次目录作为入库目标。

如果安装时还不知道 SAR/TIFF 数据最终放在哪里，可以先保留默认值并启动服务。目录确定后随时执行：

```bash
./configure-data-dir.sh /实际的/SAR/数据目录
# 或者不传参数，按提示输入
./manage.sh set-data-dir
```

工具会检查目录、更新 `.env`，并在 API 已运行时自动重新创建 API 容器以应用新挂载。查看当前配置：

```bash
./manage.sh data-dir
```

扫描完成后访问：

```text
http://服务器IP:8000/
```

## 日常管理

```bash
./manage.sh status
./manage.sh logs
./manage.sh scan
./manage.sh scan-force
./manage.sh ingest gf3/batch-001/product.zip
./manage.sh data-dir
./manage.sh set-data-dir /新的/SAR/数据目录
./manage.sh restart
./manage.sh stop
./manage.sh start
```

数据库使用 Docker 命名卷持久化。`stop` 不会删除数据库；不要执行 `docker compose down -v`，否则会删除数据库卷。

## 从旧版升级并保留已扫描数据

新版包使用新的安装目录。若希望继续使用旧版已经扫描的数据库，请先停止旧服务，然后让新目录使用旧 Compose 项目名：

```bash
cd /opt/sar-manager-offline-0.2.0-centos7-amd64
sudo ./manage.sh stop

cd /opt/sar-manager-offline-0.2.4-centos7-amd64
cp /opt/sar-manager-offline-0.2.0-centos7-amd64/.env .env
```

编辑新目录的 `.env`，确认以下两项：

```dotenv
SAR_API_IMAGE=sar-manager-api:0.2.4
COMPOSE_PROJECT_NAME=sar-manager-offline-0.2.0-centos7-amd64
```

随后执行：

```bash
sudo ./install.sh
sudo ./manage.sh health
```

这会复用旧版的数据库卷；不要执行 `down -v`。如果无需保留旧数据，则不设置 `COMPOSE_PROJECT_NAME`，按全新安装操作即可。

## 防火墙

如果其他电脑无法访问，按服务器安全要求开放配置的端口，例如：

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

只在受信任内网开放接口。数据库端口没有映射到宿主机。

## 校验与排查

安装脚本会使用 `SHA256SUMS` 校验镜像包和部署文件。常用检查命令：

```bash
docker info
./manage.sh status
./manage.sh logs
curl http://127.0.0.1:8000/health
```
