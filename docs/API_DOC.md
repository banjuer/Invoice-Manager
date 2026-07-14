# 发票管理系统 - 接口文档

> 最后更新：2026-07-14  
> 服务地址：`http://localhost:18080`  
> 接口前缀：`/api`

---

## 目录

- [通用说明](#通用说明)
- [1. 健康检查](#1-健康检查)
- [2. 发票管理](#2-发票管理)
- [3. LLM 配置](#3-llm-配置)
- [附录：状态枚举](#附录状态枚举)

---

## 通用说明

### 数据格式

- 请求/响应均为 JSON
- 时间字段格式：`2025-01-15T10:30:00`
- 日期字段格式：`2025-01-15`
- 金额字段使用 `string` 表示 `Decimal`（避免浮点精度问题）

### 金额字段说明

所有金额以**元**为单位。涉及到金额的字段有：
- `amount` — 不含税金额
- `tax_amount` — 税额
- `total_with_tax` — 价税合计（含税总金额）

关系：`total_with_tax = amount + tax_amount`

### 分页

- 分页参数：`page`（页码，从 1 开始）、`page_size`（每页条数，1-100，默认 20）
- 响应体包含 `total`、`page`、`page_size`

### 限流说明

部分敏感接口有限流保护，超限返回 429。

| 接口 | 限制 |
|------|------|
| 上传发票 | 10次/分钟 |
| 批量更新 | 30次/分钟 |
| 批量删除 | 20次/分钟 |
| 批量重新解析 | 5次/分钟 |
| CSV/Excel 导出 | 10次/分钟 |
| 其他接口 | 100次/分钟（全局默认） |

---

## 1. 健康检查

### `GET /api/health`

检查后端服务和数据库连接状态。

**请求示例：**
```
GET /api/health
```

**响应示例：**
```json
{
  "status": "ok",
  "database": "healthy",
  "service": "发票管理系统"
}
```

---

## 2. 发票管理

所有发票接口前缀为 `/api/invoices`。

---

### 2.1 上传发票

**`POST /api/invoices/upload`**

支持一次上传多个文件（PDF / JPG / JPEG / PNG），单文件最大 10MB。上传后自动触发后台 OCR + LLM 解析。

> **限流**：10次/分钟

**请求：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | File[] | 是 | 发票文件列表 |

**响应：** `200` — `UploadResponse[]`

```json
[
  {
    "id": 1,                              // int — 发票ID（失败时为 0）
    "file_name": "发票001.pdf",            // string
    "status": "success",                  // "success" | "error"
    "message": "上传成功，等待解析"         // string
  }
]
```

**状态流转：**
```
已上传 → 解析中 → 待审核 / 已确认
                ↘ 失败 → 已上传（可重试）
```

---

### 2.2 发票列表

**`GET /api/invoices`**

获取发票列表，支持多条件筛选和分页。

**请求参数（Query）：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | `1` | 页码，≥1 |
| `page_size` | int | `20` | 每页条数，1-100 |
| `status` | string | — | 按状态筛选，见[附录：状态枚举](#附录状态枚举) |
| `owner` | string | — | 按归属人筛选 |
| `start_date` | string | — | 开票日期起始，格式 `YYYY-MM-DD` |
| `end_date` | string | — | 开票日期截止，格式 `YYYY-MM-DD` |
| `invoice_ids` | string | — | ID批量查询，逗号分隔，如 `1,2,3` |

**响应：** `200`

```json
{
  "items": [
    {
      "id": 1,
      "file_name": "发票.pdf",
      "file_type": "pdf",
      "status": "已确认",
      "owner": "张三",
      "invoice_number": "1234567890",
      "issue_date": "2025-01-15",
      "buyer_name": "某科技有限公司",
      "buyer_tax_id": "91110000XXXXXXXX",
      "seller_name": "某服务有限公司",
      "seller_tax_id": "91110000YYYYYYYY",
      "item_name": "*信息技术服务*软件开发",
      "total_with_tax": "11300.00",
      "specification": null,
      "unit": null,
      "quantity": null,
      "unit_price": null,
      "amount": "10000.00",
      "tax_rate": "13%",
      "tax_amount": "1300.00",
      "created_at": "2025-01-15T10:30:00",
      "updated_at": "2025-01-15T10:35:00"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

**示例：**
```
GET /api/invoices?status=待审核&owner=张三&page=1&page_size=10
GET /api/invoices?invoice_ids=1,2,3
GET /api/invoices?start_date=2025-01-01&end_date=2025-01-31
```

---

### 2.3 发票详情

**`GET /api/invoices/{invoice_id}`**

获取单张发票的完整信息，含 OCR 结果、LLM 结果、解析差异和字段来源映射。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `invoice_id` | int | 发票ID |

**响应：** `200`

```json
{
  // ... 包含 2.2 列表的所有字段 ...

  "ocr_result": {
    "id": 1,
    "invoice_id": 1,
    "raw_text": "发票号码 1234567890\n开票日期 2025年01月15日 ...",
    "invoice_number": "1234567890",
    "issue_date": "2025-01-15",
    "buyer_name": "某科技有限公司",
    "buyer_tax_id": "91110000XXXXXXXX",
    "seller_name": "某服务有限公司",
    "seller_tax_id": "91110000YYYYYYYY",
    "item_name": "*信息技术服务*软件开发",
    "total_with_tax": "11300.00",
    "amount": "10000.00",
    "tax_rate": "13%",
    "tax_amount": "1300.00",
    "specification": null,
    "unit": null,
    "quantity": null,
    "unit_price": null,
    "created_at": "2025-01-15T10:30:00"
  },
  "llm_result": {
    "id": 1,
    "invoice_id": 1,
    // 字段结构同 ocr_result（不含 raw_text）
    "created_at": "2025-01-15T10:31:00"
  },
  "parsing_diffs": [
    {
      "id": 1,
      "invoice_id": 1,
      "field_name": "total_with_tax",
      "ocr_value": "11300.00",
      "llm_value": "11300.00",
      "final_value": null,
      "source": null,
      "resolved": 0
    }
  ],
  "field_sources": {
    "invoice_number": "matched",    // OCR和LLM一致
    "issue_date": "conflict",       // OCR和LLM不一致，需要人工处理
    "buyer_name": "ocr",            // 只有OCR有值
    "seller_name": "llm",           // 只有LLM有值
    "amount": "manual",             // 人工编辑
    "tax_rate": "custom"            // diff被手动自定义值解决
  }
}
```

**`field_sources` 取值说明：**

| 值 | 含义 |
|----|------|
| `"matched"` | OCR 和 LLM 结果一致 |
| `"conflict"` | OCR 和 LLM 结果不一致（需人工决定） |
| `"ocr"` | 仅 OCR 有结果 |
| `"llm"` | 仅 LLM 有结果 |
| `"manual"` | 人工编辑（无 diff 记录但有值） |
| `"custom"` | diff 被手动自定义值解决 |
| `null` | 来源未知 |

---

### 2.4 通过发票号码查询

**`GET /api/invoices/by-number/{invoice_number}`**

通过发票号码获取发票详情。号码会经过 URL 解码，支持中文等特殊字符。

**响应：** 同 [2.3 发票详情](#23-发票详情)

---

### 2.5 获取发票文件

**`GET /api/invoices/{invoice_id}/file`**

下载或预览发票原始文件。

**Query 参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `inline` | bool | `false` | `true` 时浏览器内预览，`false` 时下载 |

**响应：** 二进制文件流

- `Content-Type`：根据文件类型返回 `application/pdf`、`image/jpeg`、`image/png`
- `Content-Disposition`：`inline` 或 `attachment`

> **404**：发票不存在

---

### 2.6 更新发票

**`PUT /api/invoices/{invoice_id}`**

更新单张发票的字段信息（状态、归属人、票面所有字段）。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `invoice_id` | int | 发票ID |

**请求体：** `application/json`（所有字段可选，传了哪个更新哪个）

```json
{
  "status": "已确认",
  "owner": "张三",
  "invoice_number": "1234567890",
  "issue_date": "2025-01-15",
  "buyer_name": "某科技有限公司",
  "buyer_tax_id": "91110000XXXXXXXX",
  "seller_name": "某服务有限公司",
  "seller_tax_id": "91110000YYYYYYYY",
  "item_name": "*信息技术服务*软件开发",
  "total_with_tax": "11300.00",
  "amount": "10000.00",
  "tax_rate": "13%",
  "tax_amount": "1300.00",
  "specification": null,
  "unit": null,
  "quantity": null,
  "unit_price": null
}
```

**响应：** 同 [2.2 列表项格式](#22-发票列表)

> **404**：发票不存在

---

### 2.7 批量更新

**`POST /api/invoices/batch-update`**

批量修改发票的状态和/或归属人。

> **限流**：30次/分钟

**请求体：**

```json
{
  "invoice_ids": [1, 2, 3],
  "status": "已报销",          // 可选，不传则不改状态
  "owner": "张三"               // 可选，不传则不改归属人
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `invoice_ids` | int[] | 是 | 发票ID列表 |
| `status` | string | 否 | 新状态 |
| `owner` | string | 否 | 新归属人 |

**响应：**

```json
{
  "message": "成功更新 3 张发票",
  "updated_count": 3
}
```

---

### 2.8 批量删除

**`POST /api/invoices/batch-delete`**

批量删除发票及其关联数据（OCR结果、LLM结果、差异记录）。

> **限流**：20次/分钟

**请求体：**

```json
{
  "invoice_ids": [1, 2, 3]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `invoice_ids` | int[] | 是 | 要删除的发票ID列表 |

**响应：**

```json
{
  "message": "成功删除 3 张发票",
  "deleted_count": 3
}
```

> **400**：`invoice_ids` 为空  
> **404**：未找到任何要删除的发票

---

### 2.9 删除单张发票

**`DELETE /api/invoices/{invoice_id}`**

删除单张发票。

**响应：**

```json
{
  "message": "删除成功"
}
```

---

### 2.10 手动触发解析

**`POST /api/invoices/{invoice_id}/process`**

手动触发指定发票的 OCR + LLM 解析流程。

**响应：**

```json
{
  "message": "解析成功",
  "invoice_id": 1
}
```

> **404**：发票不存在  
> **500**：解析失败

---

### 2.11 批量重新解析

**`POST /api/invoices/batch-reprocess`**

清除指定发票的旧解析结果（OCR、LLM、差异），重置发票字段后重新触发后台解析。

> **限流**：5次/分钟

**请求体：**

```json
{
  "invoice_ids": [1, 2, 3]
}
```

**响应：**

```json
{
  "message": "已清除 3 张发票的旧解析结果，正在重新解析",
  "count": 3
}
```

---

### 2.12 单独重新运行 OCR

**`POST /api/invoices/{invoice_id}/reprocess-ocr`**

保留现有 LLM 结果，仅重新运行 OCR 并重新比对。

> 常用场景：换用更高精度的 OCR 引擎后重新识别。

**响应：**

```json
{
  "message": "OCR重新解析完成",
  "invoice_id": 1
}
```

---

### 2.13 单独重新运行 LLM

**`POST /api/invoices/{invoice_id}/reprocess-llm`**

保留现有 OCR 结果，仅重新运行 LLM 解析并重新比对。

> 常用场景：切换 LLM 模型后重新提取。

**响应：**

```json
{
  "message": "LLM重新解析完成",
  "invoice_id": 1
}
```

---

### 2.14 解决解析差异

**`POST /api/invoices/{invoice_id}/diffs/{diff_id}/resolve`**

当 OCR 和 LLM 结果不一致时，人工选择一个值来消除冲突。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `invoice_id` | int | 发票ID |
| `diff_id` | int | 差异记录ID |

**请求体：**

```json
{
  "source": "ocr",           // "ocr" | "llm" | "custom"
  "custom_value": "自定义值"   // source="custom" 时必填
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | 选择来源：`"ocr"`、`"llm"`、`"custom"` |
| `custom_value` | string | 否 | `source="custom"` 时填入自定义值 |

**响应：**

```json
{
  "message": "差异已解决",
  "field_name": "buyer_name",
  "final_value": "某科技有限公司",
  "all_resolved": false     // 是否所有差异都已解决
}
```

> **当所有差异都解决后，发票状态自动变为 `已确认`。**

---

### 2.15 确认发票

**`POST /api/invoices/{invoice_id}/confirm`**

一键确认发票。将未解决的差异标记为已解决，并将状态改为 `已确认`。

**前置条件：** 必填关键字段（发票号码、开票日期、价税合计、购买方、销售方等）不能为空，否则返回 400。

**响应：**

```json
{
  "message": "发票已确认",
  "resolved_count": 2
}
```

> **400**：必填字段缺失，或缺少 OCR/LLM 比对结果

---

### 2.16 发票统计

**`GET /api/invoices/statistics`**

获取筛选条件下发票的数量和金额汇总。

**请求参数（Query）：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `invoice_ids` | string | ID批量筛选，逗号分隔 |
| `status` | string | 状态筛选 |
| `owner` | string | 归属人筛选 |

所有参数可选，不传则统计全部。

**响应：**

```json
{
  "count": 42,                // 发票数量
  "total_amount": "420000.00", // 金额合计（不含税）
  "total_tax": "54600.00",     // 税额合计
  "total_with_tax": "474600.00" // 价税合计
}
```

---

### 2.17 导出 CSV

**`GET /api/invoices/export/csv`**

将筛选后的发票列表导出为 CSV 文件（UTF-8 BOM，Excel 兼容中文）。

> **限流**：10次/分钟

**请求参数：** 同 [2.2 列表筛选参数](#22-发票列表)（status、owner、start_date、end_date、invoice_ids）

**响应：** `Content-Type: text/csv; charset=utf-8`

**CSV 列：** 发票号码、开票日期、购买方名称、购买方纳税人识别号、销售方名称、销售方纳税人识别号、项目名称、金额、税额、价税合计、税率、状态、归属人、文件名、创建时间

---

### 2.18 导出 Excel

**`GET /api/invoices/export/excel`**

将筛选后的发票列表导出为 Excel（`.xlsx`）文件。

> **限流**：10次/分钟

**请求参数：** 同上（[2.17 导出 CSV](#217-导出-csv)）

**响应：** `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

---

## 3. LLM 配置

所有 LLM 配置接口前缀为 `/api/settings`。

---

### 3.1 获取 LLM 状态

**`GET /api/settings/llm/status`**

查询当前 LLM 配置状态（哪些供应商已配置、哪个是当前激活的）。

**响应：**

```json
{
  "is_configured": true,
  "active_provider": "openai",
  "active_provider_display": "OpenAI (GPT)",
  "configured_providers": ["openai", "deepseek"],
  "available_providers": [
    {
      "name": "openai",
      "display_name": "OpenAI (GPT)",
      "is_configured": true,
      "model": "gpt-4o-mini",
      "base_url": null
    },
    {
      "name": "anthropic",
      "display_name": "Anthropic (Claude)",
      "is_configured": false,
      "model": "claude-3-haiku-20240307",
      "base_url": null
    }
    // ... 其他供应商
  ]
}
```

---

### 3.2 配置 LLM

**`POST /api/settings/llm/configure`**

配置指定 LLM 供应商，并持久化到 `.env` 文件。

> 如果配置了 `LLM_CONFIG_TOKEN` 环境变量，需要在请求头中传递对应 token。

**请求头（可选）：**

| 请求头 | 说明 |
|--------|------|
| `X-LLM-Config-Token` | 配置令牌（当 `LLM_CONFIG_TOKEN` 环境变量有值时必传） |
| `Authorization: Bearer xxx` | 备选鉴权方式 |

**请求体：**

```json
{
  "provider": "openai",
  "api_key": "sk-xxxxxxxx",
  "model": "gpt-4o-mini",
  "base_url": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `provider` | string | 是 | 供应商代码：`openai` / `anthropic` / `google` / `qwen` / `deepseek` / `zhipu` |
| `api_key` | string | 是 | API密钥 |
| `model` | string | 否 | 模型名称（不传用默认） |
| `base_url` | string | 否 | 自定义API地址（OpenAI兼容/代理） |

**各供应商默认模型：**

| provider | 默认模型 |
|----------|----------|
| `openai` | `gpt-4o-mini` |
| `anthropic` | `claude-3-haiku-20240307` |
| `google` | `gemini-1.5-flash` |
| `qwen` | `qwen-turbo` |
| `deepseek` | `deepseek-chat` |
| `zhipu` | `glm-4-flash` |

**响应：**

```json
{
  "success": true,
  "message": "已成功配置 OpenAI (GPT)",
  "provider": "openai"
}
```

> **400**：不支持该供应商  
> **401**：未授权（LLM_CONFIG_TOKEN 校验失败）  
> **500**：配置后验证失败

---

### 3.3 测试 LLM 配置（保存前）

**`POST /api/settings/llm/test-config`**

在保存到 `.env` 之前，先测试给定的 API 配置是否可用。

**请求体：** 格式同 [3.2 配置 LLM](#32-配置-llm)（不需要存盘，仅测试）

**响应：**

```json
{
  "success": true,
  "message": "连接成功，响应: OK",
  "response_time_ms": 1200
}
```

```json
{
  "success": false,
  "message": "API密钥无效或未授权",
  "response_time_ms": 500
}
```

---

### 3.4 测试已配置的 LLM 连接

**`POST /api/settings/llm/test`**

使用当前已保存的配置发送测试请求。

**响应：**

```json
{
  "success": true,
  "provider": "openai",
  "provider_display": "OpenAI (GPT)",
  "message": "LLM连接测试成功",
  "response": "OK"
}
```

> **400**：未配置 LLM  
> **500**：连接失败

---

### 3.5 获取可用模型列表

**`GET /api/settings/models`**

获取可用的 LLM 模型列表，可按供应商或视觉能力筛选。

**Query 参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider` | string | 供应商筛选（不传返回所有） |
| `vision_only` | bool | 仅返回支持图片输入的模型 |

**响应：**

```json
{
  "models": [
    {
      "id": "gpt-4o",
      "name": "GPT-4o",
      "vision": true,
      "context_length": 128000,
      "pricing": { "input": 5.0, "output": 15.0 }
    }
  ],
  "source": "openrouter"
}
```

---

## 附录：状态枚举

### InvoiceStatus

| 值 | 枚举名 | 含义 | 说明 |
|----|--------|------|------|
| `已上传` | `UPLOADED` | 文件已上传 | 等待 OCR 处理 |
| `解析中` | `PROCESSING` | 正在解析 | OCR/LLM 处理中 |
| `待处理` | `PENDING` | 待处理 | 遗留状态，当前流程不再使用 |
| `待审核` | `REVIEWING` | 待审核 | 有冲突或缺失字段，需人工介入 |
| `已确认` | `CONFIRMED` | 已确认 | 审核完成，可报销 |
| `已报销` | `REIMBURSED` | 已报销 | 报销已完成 |
| `未报销` | `NOT_REIMBURSED` | 未报销 | 已确认但尚未报销 |

**完整状态流转：**

```
                      批量重新解析
                    ┌──────────────┐
                    ↓              │
上传 → 已上传 → 解析中 ─┬→ 已确认 ─┴→ 已报销
                    │              └→ 未报销
                    ├→ 待审核 → (解决差异) → 已确认
                    └→ 失败 → 已上传（可重试）
```

### ParsingDiff 来源

| 值 | 含义 |
|----|------|
| `ocr` | 采用 OCR 结果 |
| `llm` | 采用 LLM 结果 |
| `matched` | OCR 和 LLM 一致 |
| `conflict` | OCR 和 LLM 不一致 |
| `custom` | 使用自定义值 |
| `manual` | 人工编辑（无 diff 记录） |

---

> **维护说明**：当后端接口发生变动（新增/修改/删除接口、参数变更、响应字段变更），请同步更新本文档。
