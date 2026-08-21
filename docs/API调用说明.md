# SAR Manager API 调用说明

本文档供其他前端系统调用 SAR Manager 查询接口使用。

## 1. 服务地址

当前服务器示例地址：

```text
http://192.168.5.232:8989
```

前端代码中建议将地址配置为变量，不要散落在业务代码中：

```javascript
const API_BASE = "http://192.168.5.232:8989";
```

可通过健康检查确认服务是否正常：

```http
GET /health
```

正常响应：

```json
{
  "status": "ok"
}
```

## 2. SAR 条件查询

```http
GET /api/v1/sar
```

### 查询参数

| 参数 | 是否必填 | 示例 | 说明 |
| --- | --- | --- | --- |
| `startTime` | 否 | `2022-01-01T00:00:00` | 获取时间大于或等于该时间的数据 |
| `endTime` | 否 | `2026-12-31T23:59:59` | 获取时间小于或等于该时间的数据 |
| `bbox` | 否 | `73,18,135,54` | 地图范围，顺序为最小经度、最小纬度、最大经度、最大纬度 |
| `source` | 否 | `GF3`、`STRIX`、`UMBRA`、`CAPELLA`、`ICEYE`、`LANHE` | 限制数据来源；不传表示全部来源 |
| `name` | 否 | `GF3_KRN` | 按影像名称或外部产品编号模糊查询，不区分大小写 |
| `includeNonReady` | 否 | `true` | 是否同时返回非 READY 数据，默认值为 `false` |
| `limit` | 否 | `20` | 每页最多返回多少条，默认 `100`，最大 `1000` |
| `offset` | 否 | `0`、`20` | 从第几条匹配数据开始返回，默认 `0`；下一页可加上上一页的 `limit` |

所有查询条件都可以不传。多个条件同时传入时，数据必须同时满足所有条件。

为避免一次传输或渲染过多数据，接口默认最多返回 100 条。响应中的 `has_more` 为 `true` 时，表示还有下一页；将 `offset` 增加一个 `limit` 即可继续查询。

### 时间规则

时间推荐使用：

```text
YYYY-MM-DDTHH:mm:ss
```

例如：

```text
2022-02-21T08:30:00
```

系统按不带时区的时间处理。开始时间不能晚于结束时间。

### 地图范围规则

`bbox` 固定使用以下顺序：

```text
最小经度,最小纬度,最大经度,最大纬度
```

也可以理解为：

```text
西,南,东,北
```

示例：

```text
73,18,135,54
```

表示查询大致覆盖中国区域的数据。查询采用空间相交规则，只要 SAR 覆盖范围与 bbox 相交，就会返回。

全球范围应填写：

```text
-180,-90,180,90
```

不能填写 `180,90,-180,-90`，因为最小值不能大于最大值。

## 3. 查询可用的 SAR 数据源类型

前端在生成“数据来源”筛选下拉框前，可先调用：

```http
GET /api/v1/sources
```

响应中的 `code` 可以直接作为 `/api/v1/sar` 的 `source` 参数；`count` 是该来源当前已入库的数据条数。即使当前数量是 `0`，只要系统已经支持该数据源，也会返回该项。

```json
{
  "sources": [
    {"code": "CAPELLA", "count": 0},
    {"code": "GF3", "count": 1},
    {"code": "ICEYE", "count": 1},
    {"code": "STRIX", "count": 1},
    {"code": "UMBRA", "count": 1}
  ]
}
```

JavaScript 示例：

```javascript
const response = await fetch(`${API_BASE}/api/v1/sources`);
const { sources } = await response.json();

// 下拉框 option 的 value 使用 source.code；查询时传给 source 参数。
sources.forEach((source) => {
  console.log(source.code, source.count);
});
```

## 4. 调用示例

### 浏览器直接访问

```text
http://192.168.5.232:8989/api/v1/sar?startTime=2022-01-01T00%3A00%3A00&endTime=2026-12-31T23%3A59%3A59&bbox=73%2C18%2C135%2C54&includeNonReady=true
```

### curl 调用

```bash
curl --get 'http://192.168.5.232:8989/api/v1/sar' \
  --data-urlencode 'startTime=2022-01-01T00:00:00' \
  --data-urlencode 'endTime=2026-12-31T23:59:59' \
  --data-urlencode 'bbox=73,18,135,54' \
  --data-urlencode 'limit=20' \
  --data-urlencode 'includeNonReady=true'
```

只查询 GF3：

```bash
curl --get 'http://192.168.5.232:8989/api/v1/sar' \
  --data-urlencode 'source=GF3' \
  --data-urlencode 'includeNonReady=true'
```

按影像名称查询（输入一部分名称即可）：

```bash
curl --get 'http://192.168.5.232:8989/api/v1/sar' \
  --data-urlencode 'name=GF3_KRN' \
  --data-urlencode 'limit=20'
```

### JavaScript 调用

```javascript
const API_BASE = "http://192.168.5.232:8989";

async function searchSar({
  startTime,
  endTime,
  west,
  south,
  east,
  north,
  source,
  name,
  includeNonReady = false,
}) {
  const params = new URLSearchParams();

  if (startTime) params.set("startTime", startTime);
  if (endTime) params.set("endTime", endTime);
  if (source) params.set("source", source);
  if (name) params.set("name", name);

  const hasCompleteBbox = [west, south, east, north].every(
    (value) => value !== undefined && value !== null && value !== "",
  );

  if (hasCompleteBbox) {
    params.set("bbox", [west, south, east, north].join(","));
  }

  if (includeNonReady) {
    params.set("includeNonReady", "true");
  }
  params.set("limit", "100");

  const response = await fetch(
    `${API_BASE}/api/v1/sar?${params.toString()}`,
  );

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `查询失败：HTTP ${response.status}`);
  }

  return payload;
}
```

调用函数：

```javascript
const result = await searchSar({
  startTime: "2022-01-01T00:00:00",
  endTime: "2026-12-31T23:59:59",
  west: 73,
  south: 18,
  east: 135,
  north: 54,
  source: "GF3",
  includeNonReady: true,
});

console.log(result.features);
```

## 5. Cesium 当前地图范围查询

Cesium 的矩形坐标使用弧度，传给接口前需要转换为角度：

```javascript
const rectangle = viewer.camera.computeViewRectangle();

if (rectangle) {
  const result = await searchSar({
    startTime: "2022-01-01T00:00:00",
    endTime: "2026-12-31T23:59:59",
    west: Cesium.Math.toDegrees(rectangle.west),
    south: Cesium.Math.toDegrees(rectangle.south),
    east: Cesium.Math.toDegrees(rectangle.east),
    north: Cesium.Math.toDegrees(rectangle.north),
    includeNonReady: true,
  });

  console.log("当前地图范围内的 SAR 数据：", result.features);
}
```

当前接口要求 `west <= east`。如果地图视口跨越了国际日期变更线（经度 180 度），前端需要拆成两个 bbox 分别查询，再合并并去重。

## 6. 返回结构

接口返回标准 GeoJSON `FeatureCollection`：

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "数据 UUID",
      "geometry": {
        "type": "Polygon",
        "coordinates": []
      },
      "properties": {
        "external_id": "SAR 唯一编号",
        "source": "GF3",
        "name": "数据名称",
        "acquisition_time": "2022-02-21 08:30:00",
        "status": "READY",
        "metadata": {},
        "assets": {},
        "data_directory": "/data/gf3/batch-001/product-001",
        "thumbnail_url": "http://192.168.5.232:8989/api/v1/assets/缩略图 UUID",
        "tiff_url": "http://192.168.5.232:8989/api/v1/assets/TIFF文件 UUID",
        "metadata_url": "http://192.168.5.232:8989/api/v1/assets/描述文件 UUID",
        "error_message": null
      }
    }
  ]
}
```

`data_directory` 是该 SAR 产品在服务器本地数据盘中的目录。它优先依据原始 TIFF 的位置计算；若 TIFF 缺失，则回退到缩略图或 XML/JSON 描述文件所在目录。对于压缩包数据，它表示压缩包所在目录。该字段用于服务器侧排查或在资产 UUID 无法访问时定位原始数据；不要将包含服务器目录信息的接口直接暴露到不受信任的公网。

`geometry` 可以直接交给支持 GeoJSON 的地图库显示。

缩略图、TIFF 和描述文件地址是可直接访问的完整 URL。默认使用当前请求的主机和端口生成；
如果服务位于反向代理之后，建议在 `.env` 设置固定对外地址：

```dotenv
PUBLIC_BASE_URL=http://192.168.5.232:8989
```

部分来源没有单独的缩略图，此时 `thumbnail_url` 与原 TIFF 对应同一个文件。前端若不能直接显示 GeoTIFF，可以先显示占位图，并保留该 URL 给支持 TIFF 的地图组件使用。

`metadata_url` 指向该数据入库时使用的原始描述文件（XML 或 JSON 二选一，取决于数据来源），可直接下载或在浏览器中预览；无法识别或解析失败的数据没有对应资产时，该字段为 `null`。

## 7. 查询产品目录内全部文件

```http
GET /api/v1/sar/{dataset_id}/files
```

接口列出该产品目录或压缩包产品目录中的全部允许文件。目前包含 XML、JSON、KML、
TIFF、PNG、JPEG 和 WEBP；同一类型可以返回多条。每个文件都有稳定 UUID，强制重新扫描
后只要文件位置没有变化，URL 就不会变化。

```json
{
  "dataset_id": "数据 UUID",
  "external_id": "GF3:示例产品编号",
  "name": "示例产品",
  "files": [
    {
      "id": "文件 UUID",
      "kind": "KML",
      "file_name": "footprint.kml",
      "path": "gf3/example/footprint.kml",
      "container_type": "FILE",
      "mime_type": "application/vnd.google-earth.kml+xml",
      "size_bytes": 1234,
      "url": "http://192.168.5.232:8989/api/v1/assets/文件 UUID"
    }
  ]
}
```

`url` 不包含访问令牌，也没有有效期；只要接收方能够访问该服务器地址，就可以直接使用。
从不含完整文件索引的旧版本升级后，需要执行一次 `./manage.sh scan-force`，为已有记录建立索引。

## 8. 数据状态

| 状态 | 含义 |
| --- | --- |
| `READY` | 时间、坐标、TIFF 和缩略图等必要信息完整 |
| `PARTIAL` | 数据已识别，但缺少部分必要信息 |
| `INVALID_METADATA` | XML 元数据无效 |
| `UNKNOWN_SOURCE` | 无法识别数据来源 |
| `DUPLICATE` | 唯一编号重复，但内容不一致 |

不传 `includeNonReady=true` 时，接口只返回 `READY` 数据。当前测试数据 `READY` 数量为 0，因此测试阶段需要设置：

```text
includeNonReady=true
```

当查询包含时间条件时，没有获取时间的数据不会返回；当查询包含 bbox 条件时，没有坐标范围的数据不会返回。

## 9. 常见错误

### bbox 顺序错误

响应：

```text
bbox minimums must not exceed maximums
```

检查是否按 `西,南,东,北` 输入，并确认西小于东、南小于北。

### bbox 数量错误

响应：

```text
bbox must be minLon,minLat,maxLon,maxLat
```

检查 bbox 是否包含四个用英文逗号分隔的数字。

### 时间顺序错误

响应：

```text
startTime must not exceed endTime
```

开始时间不能晚于结束时间。

### 浏览器跨域错误

Docker 配置默认允许跨域调用。如果部署时修改过 `CORS_ORIGINS`，需要把其他前端的来源地址加入该配置，例如：

```text
CORS_ORIGINS=http://192.168.5.100:8080
```

修改配置后需要重启服务。

## 10. 其他接口

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/health` | GET | 服务健康检查 |
| `/api/v1/stats` | GET | 获取数据总数及状态统计 |
| `/api/v1/sar/{dataset_id}` | GET | 获取单条 SAR 详情 |
| `/api/v1/sar/{dataset_id}/files` | GET | 获取产品目录内全部允许文件及完整 URL |
| `/api/v1/assets/{asset_id}` | GET | 访问 XML、JSON、KML、TIFF、PNG 等文件 |

## 11. 局域网文件搬运

SAR Manager 的搬运接口复制或移动 SAR 产品后，会立即执行定向扫描和数据库入库；
不会生成缩略图，只登记产品中已经存在的缩略图和影像文件。
创建任务前会解析远端产品编号；数据库中已存在的产品返回 `SKIPPED`，不会产生网络搬运。
局域网共享必须先由部署人员挂载并配置为受控的 `server` 标识，调用者不能提交任意服务器地址、账号或绝对路径。

```http
POST /api/v1/transfer-jobs
```

```json
{
  "source": "GF3",
  "server": "sar-storage-01",
  "files": ["gf3/2026/GF3_001.zip", "gf3/2026/GF3_002.zip"],
  "mode": "COPY"
}
```

`source` 必须是系统已注册的数据源。未传 `destination_subdirectory` 时默认搬到
`/upload/{source小写}`；例如 `source=LANHE` 会搬到 `/upload/lanhe`。自定义子目录也会被限制在该数据源目录中。

成功时返回 HTTP `202` 与任务编号。使用以下接口查询 Web 所需的进度：

```http
GET /api/v1/transfer-jobs/{job_id}
```

响应中的 `progress.transferred_bytes`、`progress.total_bytes` 与 `progress.percent` 表示搬运进度，`files` 数组包含每个文件的状态和已传输字节数。`phase` 用于区分 `TRANSFERRING`、`INGESTING` 和 `INGESTED`。只有入库成功的文件才会变为 `COMPLETED`；入库失败会返回具体错误。Web 每 3 秒轮询一次。任务列表和取消接口分别为：

```http
GET  /api/v1/transfer-jobs?status=RUNNING
POST /api/v1/transfer-jobs/{job_id}/cancel
```

任务列表支持 `limit`（最大 500）和 `offset` 分页，并返回 `has_more`。每个任务都包含逐文件记录，
包括 `QUEUED`、`TRANSFERRING`、`INGESTING`、`INGESTED`、`SKIPPED`、`FAILED` 和 `CANCELLED` 阶段。
内置 Web 页面会自动读取全部分页并每 3 秒刷新进度条。
