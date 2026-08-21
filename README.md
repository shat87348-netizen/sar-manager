# SAR Manager

面向本地 Linux 环境的 SAR 元数据归纳、PostGIS 入库和 Cesium 查询接口。当前支持 GF3、StriX、Umbra、Capella、ICEYE、LANHE，以及普通目录、ZIP、TAR、TAR.GZ、TGZ 数据容器。

## 已实现范围

- 扫描约 15000 份本地 SAR 数据；重复扫描采用稳定 `external_id` 更新记录。
- 递归扫描任意层级目录，从普通目录或压缩包内直接读取 XML/JSON，扫描时不解压整包。
- GF3：读取 `CenterTime` 与四角坐标。
- StriX：读取 `sceneCenterDateTime` 与 GML `posList`，转换为经纬度顺序。
- Umbra：读取采集起止时间与 `footprintPolygonLla`。
- Capella：读取中心时间，并将 JSON 中的 UTM 影像范围转换为 WGS84 经纬度。
- ICEYE：使用 GRD STAC JSON 作为主产品描述，并以 QLK TIFF 作为缩略图。
- 时间统一保存为 `acquisition_time`，不做时区换算。
- 关联描述文件、原始 TIFF 和缩略图；没有单独缩略图时，原 TIFF 同时作为缩略图资产。
- 同一 ICEYE 产品目录中的 QLK、VID、CSI、SLC JSON 被视为辅助描述，不重复入库。
- PostgreSQL/PostGIS 保存覆盖多边形，并按时间、地图范围、来源筛选。
- API 返回 GeoJSON、缩略图 URL 和原始 TIFF URL，不暴露 Linux 绝对路径。
- 支持从压缩包流式读取缩略图或 TIFF 成员。

## 快速启动

1. 复制配置并修改密码和数据目录：

   ```bash
   cp .env.example .env
   ```

2. 启动 API 和 PostGIS：

   ```bash
   docker compose up -d --build
   ```

3. 扫描数据（独立扫描容器，默认不影响 API 容器的 CPU 配额）：

   ```bash
   docker compose run --rm scanner

   对少量新增产品，放入 `SAR_UPLOAD_DIR` 的来源子目录后可定点入库，例如：

   ```bash
   docker compose run --rm --entrypoint nice scanner -n 15 \
     python -m app.cli ingest gf3/batch-001/product.zip
   ```
   ```

4. 检查状态：

   ```bash
   curl http://127.0.0.1:8000/health
   curl http://127.0.0.1:8000/api/v1/stats
   ```

5. 打开简单接口测试页：

   ```text
   http://127.0.0.1:8000/web/
   ```

   页面不依赖外部 CDN 或前端构建工具，可在离线环境中直接使用。

## 前端查询接口

```http
GET /api/v1/sar?startTime=2022-01-01%2000:00:00&endTime=2025-12-31%2023:59:59&bbox=-180,-90,180,90&source=GF3&name=GF3_KRN
```

返回标准 GeoJSON `FeatureCollection`。为避免一次返回过多数据，默认最多返回 100 条；可通过 `limit`（最大 1000）和 `offset` 分页，响应的 `has_more` 表示是否还有下一页。每个 Feature 的 `properties` 包含：

- `external_id`、`source`、`acquisition_time`、`status`
- `thumbnail_url`
- `tiff_url`
- `data_directory`（服务器本地 SAR 数据目录，供排查和定位原始文件）
- XML/JSON 中提取的扩展元数据

其他接口：

- `GET /api/v1/sources`：返回本系统支持的数据源类型及其当前入库数量，供前端生成来源筛选项
- `GET /api/v1/sar/{id}`：单条详情
- `GET /api/v1/sar/{id}/files`：列出该产品目录内的 XML、JSON、KML、TIFF、PNG、JPEG、WEBP 文件及完整访问 URL
- `GET /api/v1/assets/{id}`：访问普通文件或压缩包内文件
- `GET /api/v1/stats`：来源和状态统计
- `POST /api/v1/admin/scan`：使用容器内 `/data` 执行同步扫描
- `GET /openapi.json`：OpenAPI 描述文件

默认只返回 `READY`。调试异常记录时增加 `includeNonReady=true`。

## 局域网文件搬运

SAR Manager 可以将一个或多个已挂载的局域网 SAR 产品复制（或在确认成功后移动）到临时入库区。
每个产品搬运完成后会立即执行已有的定向入库流程：校验数据源、移动到 `/data/{source}` 并扫描入库；
系统不会生成缩略图，只会登记产品中已经存在的影像和缩略图文件。

创建任务时系统会先读取远端产品的 XML/JSON 元数据并得到稳定产品编号；如果这些编号已经存在于
`sar_dataset`，该路径会标记为 `SKIPPED`，不会搬运，也不会在 `MOVE` 模式下删除远端文件。

先将允许访问的局域网共享目录挂载到宿主机，并配置为 API 容器的只读目录。例如：

```dotenv
SAR_TRANSFER_SOURCE_DIR=/mnt/sar-shares
TRANSFER_SOURCE_ROOTS={"sar-storage-01":"/transfer-sources/sar-storage-01"}
TRANSFER_DESTINATION_ROOT=/upload
```

`server` 只能使用 `TRANSFER_SOURCE_ROOTS` 中预配置的名称，传入的 `files` 必须是其目录下的相对路径，
因此接口不会接受任意 IP、网络凭据或可越界的绝对路径。

创建异步搬运任务：

```http
POST /api/v1/transfer-jobs
Content-Type: application/json

{
  "source": "GF3",
  "server": "sar-storage-01",
  "files": ["gf3/2026/product-001.zip", "gf3/2026/product-002.zip"],
  "mode": "COPY"
}
```

未传 `destination_subdirectory` 时，系统根据 `source` 自动搬到 `/upload/{source}`；
例如 `source=LANHE` 默认进入 `/upload/lanhe`。如需按批次分目录，可以显式传入
`destination_subdirectory`，例如 `2026-08-21`。系统始终把它限制在对应数据源目录内。

返回 `202 Accepted` 和 `job_id`。调用方通过 `GET /api/v1/transfer-jobs/{job_id}` 每 3 秒查询总进度和逐文件进度；
`phase=TRANSFERRING` 表示正在搬运，`phase=INGESTING` 表示已搬完并正在入库，`phase=INGESTED` 表示该文件已入库。
也可使用 `GET /api/v1/transfer-jobs?status=RUNNING` 查看运行中的任务；
`POST /api/v1/transfer-jobs/{job_id}/cancel` 取消尚未完成的任务。

Web 页面使用 `GET /api/v1/transfer-jobs?limit=500&offset=0` 分页读取全部历史任务，
每 3 秒刷新一次。任务列表响应中的每个任务均包含 `files`，因此搬运中的字节进度也能直接显示。

状态为 `QUEUED`、`RUNNING`、`COMPLETED`、`PARTIAL_FAILED`、`FAILED` 或 `CANCELLED`。`MOVE` 模式仅在单个文件完整复制到目标目录后才删除源文件，推荐默认使用 `COPY`。

## 扫描与接口性能

请使用 `docker compose run --rm scanner`（离线包中为 `./manage.sh scan`）执行大批量扫描，不要将 `POST /api/v1/admin/scan` 用于 15000 份数据这类长任务。扫描器是独立的一次性容器，默认最多使用 1 个 CPU，并以较低调度优先级运行；每次写库后默认等待 20ms，让数据库优先处理查询；API 可以继续提供查询服务。

重复扫描会自动跳过描述文件内容未变化的已入库数据，减少数据库写入。若描述文件未变但 TIFF、缩略图等关联文件发生了变更，使用强制扫描重新归纳：

```bash
docker compose run --rm --entrypoint nice scanner -n 15 python -m app.cli scan /data --force
```

从旧版本升级后首次使用目录文件列表时也要执行一次强制扫描，以便为已有产品建立完整文件索引。
文件 URL 默认根据请求的主机和端口生成；通过反向代理或固定地址对外提供服务时，可在 `.env`
设置 `PUBLIC_BASE_URL=http://服务器地址:端口`。

当前 `tiff` 样例扫描报告应为：发现 3 个 XML、7 个 JSON；导入 6 个主产品；
忽略 4 个 ICEYE 辅助 JSON。GF3 和 LANHE 样例缺少部分影像资产，因此是 `PARTIAL`，
其余主产品是 `READY`。

## 完全离线部署

在一台能够联网、并且与目标 Linux 架构一致的机器上执行：

```bash
chmod +x scripts/*.sh
./scripts/build-offline-bundle.sh
```

会生成 `sar-manager-offline-0.2.4-centos7-amd64.tar.gz`，其中包含 API 镜像、PostGIS 镜像、Compose 文件、校验文件和管理脚本。

把压缩包复制到离线 Linux 服务器后：

```bash
tar -xzf sar-manager-offline-0.2.4-centos7-amd64.tar.gz
cd sar-manager-offline-0.2.4-centos7-amd64
./install.sh
```

第一次运行会生成 `.env` 并停止。修改其中的 `SAR_DATA_DIR` 和 `POSTGRES_PASSWORD` 后再次运行 `./install.sh`。

当前离线包默认并正式支持 `linux/amd64`。所选的 `postgis/postgis:16-3.5`
镜像没有 ARM64 清单；如果目标服务器是 ARM64，需要先换成支持 ARM64 的 PostGIS
镜像并完成同架构验证，不能只修改 `DOCKER_PLATFORM`。

离线服务器运行时不需要访问 PyPI、npm 或 Docker Hub。目标 CentOS 7 服务器需要预先安装 Docker Engine 20.10+，以及 Docker Compose 插件或 `docker-compose` 1.29+。详细说明见 `OFFLINE_DEPLOY.md`。

## 压缩包说明

扫描 ZIP/TAR 时只读取 XML/JSON 内容，并记录 `archive_path + member_path`。缩略图可以直接流式返回。大型 TIFF 位于压缩包内时虽然能够访问，但不支持高效的随机 Range 读取；如果后续需要在线浏览大型 TIFF，建议增加按需解压缓存服务。

## 开发测试

解析器测试只依赖 Python 标准库：

```bash
python3 -m unittest discover -s tests -v
```

容器配置检查：

```bash
docker compose config
```
