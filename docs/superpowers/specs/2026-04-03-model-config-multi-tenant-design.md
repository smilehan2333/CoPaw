# 模型配置多租户隔离设计

**日期**: 2026-04-03
**主题**: model-config-multi-tenant
**状态**: 已更新 - 部分实现已变更

---

> **重要更新 (2026-04-06)**:
>
> 本设计文档中描述的 `tenant_models.json` 方案已被 `unify-tenant-active-model-source` 变更取代。
>
> **当前状态**:
> - `tenant_models.json` 不再是运行时 active model 的事实来源
> - Active model 现在统一存储在 `~/.copaw.secret/{tenant}/providers/active_model.json`
> - `ProviderManager` 是 active model 的唯一读取入口
> - `tenant_models.json` 不再参与 active model 读取或自动迁移
>
> 本文档保留作为历史参考，但运行时行为已按新的统一方案实现。

---

## 1. 概述

### 1.1 背景

CoPaw 已实现多租户架构，支持基于 `tenant_id` 和 `workspace` 的隔离。当前模型配置存储在 Agent 级别的 `agent.json` 中，每个 Agent 独立配置 `active_model` 和 `llm_routing`。

### 1.2 目标

将模型配置从 Agent 级别提升到**租户级别**，实现：
- 同一租户下的所有 Agent 共享相同的模型配置
- 不同租户之间完全隔离模型配置
- Agent 不再单独配置模型，只配置业务相关选项

### 1.3 成功标准

- [ ] 每个租户拥有独立的模型配置文件
- [ ] Agent 自动使用所属租户的配置
- [ ] API 自动返回当前租户的 provider 列表
- [ ] 默认租户 "default" 兼容现有单租户部署
- [ ] AgentProfileConfig 移除模型相关字段

---

## 2. 架构设计

### 2.1 目录结构

```
~/.copaw/
├── tenants/
│   └── {tenant_id}/
│       ├── tenant_models.json      # 租户模型配置（新增）
│       └── workspaces/
│           └── {agent_id}/
│               └── agent.json      # 移除模型相关字段
├── workspaces/                      # default 租户（向后兼容）
│   └── default/
└── config.json                      # 移除 providers 配置
```

### 2.2 配置层级

```
┌─────────────────────────────────────┐
│          System (Global)            │
│     默认租户 fallback 配置          │
├─────────────────────────────────────┤
│           Tenant Level              │
│   tenant_models.json (每个租户)     │
│   - providers[]                     │
│   - routing_strategy                │
│   - local_slot                      │
│   - cloud_slot                      │
├─────────────────────────────────────┤
│           Agent Level               │
│   agent.json（移除模型配置）        │
│   - 仅保留业务配置                  │
└─────────────────────────────────────┘
```

---

## 3. 组件设计

### 3.1 配置文件结构 (tenant_models.json)

```json
{
  "version": "1.0",
  "providers": [
    {
      "id": "openai_tenant",
      "type": "openai",
      "api_key": "${ENV:OPENAI_API_KEY}",
      "base_url": "https://api.openai.com/v1",
      "models": ["gpt-5", "gpt-5.2"],
      "enabled": true
    },
    {
      "id": "anthropic_tenant",
      "type": "anthropic",
      "api_key": "${ENV:ANTHROPIC_API_KEY}",
      "enabled": true
    }
  ],
  "routing": {
    "mode": "local_first",
    "slots": {
      "local": {
        "provider_id": "openai_tenant",
        "model": "gpt-5"
      },
      "cloud": {
        "provider_id": "anthropic_tenant",
        "model": "claude-opus-4-6"
      }
    }
  }
}
```

### 3.2 核心类设计

```python
# src/copaw/tenant_models/models.py

class TenantProviderConfig(BaseModel):
    """租户级别 Provider 配置"""
    id: str
    type: Literal["openai", "anthropic", "ollama", ...]
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: List[str] = []
    enabled: bool = True
    extra: Dict = {}

class ModelSlot(BaseModel):
    """模型槽位配置"""
    provider_id: str
    model: str

class RoutingConfig(BaseModel):
    """路由配置"""
    mode: Literal["local_first", "cloud_first"]
    slots: Dict[str, ModelSlot]  # "local" | "cloud"

class TenantModelConfig(BaseModel):
    """租户模型配置根模型"""
    version: str = "1.0"
    providers: List[TenantProviderConfig] = []
    routing: RoutingConfig

    def get_active_slot(self) -> ModelSlot:
        """根据 routing.mode 返回活跃槽位"""
        return self.routing.slots[self.routing.mode.replace("_first", "")]

    def get_other_slot(self) -> ModelSlot:
        """返回另一个槽位（用于降级）"""
        other = "cloud" if self.routing.mode == "local_first" else "local"
        return self.routing.slots[other]
```

```python
# src/copaw/tenant_models/manager.py

class TenantModelManager:
    """租户模型配置管理器"""

    _cache: Dict[str, TenantModelConfig] = {}

    @classmethod
    def get_config_path(cls, tenant_id: str) -> Path:
        """获取租户配置文件路径"""
        return Path(WORKING_DIR) / "tenants" / tenant_id / "tenant_models.json"

    @classmethod
    def load(cls, tenant_id: str) -> TenantModelConfig:
        """加载租户配置（带缓存）"""
        if tenant_id in cls._cache:
            return cls._cache[tenant_id]

        config_path = cls.get_config_path(tenant_id)
        if not config_path.exists():
            if tenant_id == "default":
                raise TenantModelNotFoundError(f"Default tenant config not found: {config_path}")
            # 降级到 default
            logger.warning(f"Tenant {tenant_id} config not found, falling back to default")
            return cls.load("default")

        with open(config_path) as f:
            data = json.load(f)

        config = TenantModelConfig(**data)
        cls._cache[tenant_id] = config
        return config

    @classmethod
    def save(cls, tenant_id: str, config: TenantModelConfig) -> None:
        """保存租户配置"""
        config_path = cls.get_config_path(tenant_id)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w") as f:
            json.dump(config.model_dump(), f, indent=2)

        cls._cache[tenant_id] = config

    @classmethod
    def invalidate_cache(cls, tenant_id: Optional[str] = None):
        """使缓存失效"""
        if tenant_id is None:
            cls._cache.clear()
        else:
            cls._cache.pop(tenant_id, None)

    @classmethod
    def get_chat_model(cls, tenant_id: str) -> ChatModelBase:
        """获取当前活跃槽位的 ChatModel 实例"""
        config = cls.load(tenant_id)
        slot = config.get_active_slot()
        provider_config = next(
            (p for p in config.providers if p.id == slot.provider_id and p.enabled),
            None
        )
        if not provider_config:
            raise TenantModelProviderError(f"Provider {slot.provider_id} not found or disabled")

        return instantiate_provider(provider_config, slot.model)
```

```python
# src/copaw/tenant_models/context.py

from contextvars import ContextVar

# 上下文变量存储当前租户的模型配置
current_tenant_model_config: ContextVar[Optional[TenantModelConfig]] = ContextVar(
    "current_tenant_model_config",
    default=None,
)

class TenantModelContext:
    """租户模型配置上下文管理"""

    @staticmethod
    def set_config(config: TenantModelConfig) -> Token:
        """设置当前租户的模型配置"""
        return current_tenant_model_config.set(config)

    @staticmethod
    def get_config() -> Optional[TenantModelConfig]:
        """获取当前租户的模型配置"""
        return current_tenant_model_config.get()

    @staticmethod
    def get_config_strict() -> TenantModelConfig:
        """获取配置，若未设置则抛出错误"""
        config = current_tenant_model_config.get()
        if config is None:
            raise TenantContextError("Tenant model config not set in context")
        return config

    @staticmethod
    def get_chat_model() -> ChatModelBase:
        """从当前上下文获取 ChatModel"""
        tenant_id = get_current_tenant_id()
        return TenantModelManager.get_chat_model(tenant_id)

    @staticmethod
    def reset_config(token: Token) -> None:
        """重置配置"""
        current_tenant_model_config.reset(token)
```

### 3.3 Agent 配置变更

**AgentProfileConfig 变更（config.py）**

```python
# 移除的字段
- active_model: Optional[ModelSlotConfig]
- llm_routing: AgentsLLMRoutingConfig

# 保留的字段
- id, name, description
- channels: ChannelConfig
- mcp: MCPConfig
- heartbeat: HeartbeatConfig
- running: AgentsRunningConfig
- tools: ToolsConfig
- security: SecurityConfig
- ... 其他业务配置
```

---

## 4. 数据流设计

### 4.1 请求处理流程

```
HTTP Request
    ↓
TenantWorkspaceMiddleware.dispatch()
    ↓
1. 获取 tenant_id from request.state
2. 加载 TenantModelConfig: TenantModelManager.load(tenant_id)
3. 绑定配置到上下文: TenantModelContext.set_config(config)
    ↓
AgentRunner / 其他组件
    ↓
获取模型: TenantModelContext.get_chat_model()
    ↓
返回响应
    ↓
清理上下文: TenantModelContext.reset_config(token)
```

### 4.2 Provider 实例化流程

```python
def instantiate_provider(config: TenantProviderConfig, model: str) -> ChatModelBase:
    """根据配置实例化 Provider"""
    provider_class = PROVIDER_REGISTRY[config.type]

    # 处理环境变量引用 ${ENV:XXX}
    api_key = resolve_env_vars(config.api_key)

    return provider_class(
        api_key=api_key,
        base_url=config.base_url,
        model=model,
        **config.extra
    )
```

### 4.3 API 端点变更

```python
# /api/providers - 自动返回当前租户配置
@app.get("/api/providers")
async def get_providers(
    tenant_id: str = Depends(get_current_tenant_id)
):
    config = TenantModelManager.load(tenant_id)
    return {
        "tenant_id": tenant_id,
        "providers": [p.model_dump() for p in config.providers],
        "routing": config.routing.model_dump(),
        "active_mode": config.routing.mode,
    }

# /api/providers/test - 测试 Provider 连接
@app.post("/api/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    tenant_id: str = Depends(get_current_tenant_id)
):
    config = TenantModelManager.load(tenant_id)
    provider = next((p for p in config.providers if p.id == provider_id), None)
    if not provider:
        raise HTTPException(404, "Provider not found")

    # 测试连接...
```

---

## 5. 错误处理与降级

### 5.1 错误场景

| 错误场景 | 行为 | HTTP 状态码 |
|---------|------|------------|
| 租户配置不存在 | 降级到 default 租户 | 200/503 |
| default 配置也不存在 | 返回 503 服务不可用 | 503 |
| 配置解析失败 | 记录错误，返回 500 | 500 |
| 活跃的 provider 已禁用 | 尝试另一个 slot，若都失败则 503 | 503 |
| 缺少必需的 API Key | 返回明确的错误消息 | 400 |
| 租户隔离冲突 | 记录安全日志，拒绝请求 | 403 |

### 5.2 降级策略

```python
class TenantModelManager:
    @classmethod
    def get_chat_model_with_fallback(cls, tenant_id: str) -> ChatModelBase:
        """带降级策略的模型获取"""
        try:
            config = cls.load(tenant_id)
        except TenantModelNotFoundError:
            if tenant_id != "default":
                logger.warning(f"Falling back to default tenant")
                return cls.get_chat_model_with_fallback("default")
            raise

        # 尝试活跃 slot
        try:
            slot = config.get_active_slot()
            return cls._instantiate_from_slot(config, slot)
        except TenantModelProviderError as e:
            logger.warning(f"Primary slot failed: {e}")

            # 尝试另一个 slot
            try:
                slot = config.get_other_slot()
                return cls._instantiate_from_slot(config, slot)
            except TenantModelProviderError:
                raise TenantModelError("All slots failed")
```

---

## 6. 测试策略

### 6.1 单元测试

```python
# tests/unit/tenant_models/test_models.py
def test_tenant_model_config_validation():
    """测试配置模型验证"""
    ...

def test_get_active_slot():
    """测试活跃槽位选择"""
    config = TenantModelConfig(
        routing=RoutingConfig(mode="local_first", slots={...})
    )
    assert config.get_active_slot().provider_id == "local_provider"

# tests/unit/tenant_models/test_manager.py
def test_load_config_creates_default():
    """测试配置加载创建默认配置"""
    ...

def test_load_config_fallback():
    """测试降级到 default 租户"""
    ...

def test_cache_invalidation():
    """测试缓存失效"""
    ...
```

### 6.2 集成测试

```python
# tests/integration/test_tenant_model_api.py
def test_api_returns_tenant_scoped_providers(client):
    """测试 API 返回租户限定的 providers"""
    response = client.get(
        "/api/providers",
        headers={"X-Tenant-Id": "tenant1"}
    )
    assert response.json()["tenant_id"] == "tenant1"

def test_agent_uses_tenant_config(client):
    """测试 Agent 使用租户配置"""
    # 创建租户配置
    # 启动 Agent
    # 验证 Agent 使用租户配置的模型
```

### 6.3 E2E 测试

```python
# tests/e2e/test_tenant_model_isolation.py
def test_tenant_model_isolation():
    """测试不同租户模型配置隔离"""
    # 1. 创建两个租户，配置不同的模型
    # 2. 启动各自的 Agent
    # 3. 验证调用不同的 provider
```

---

## 7. 迁移计划

### 7.1 向后兼容

- 现有单租户部署：使用 "default" 租户
- Agent 配置：保留字段但标记为废弃，从租户配置自动填充
- Provider 配置：从 `providers.json` 迁移到 `tenants/default/tenant_models.json`

### 7.2 迁移脚本

```python
# scripts/migrate_to_tenant_models.py
def migrate_providers_json():
    """从旧的 providers.json 迁移到租户配置"""
    old_config = load_providers_json()

    tenant_config = TenantModelConfig(
        providers=[migrate_provider(p) for p in old_config.providers],
        routing=RoutingConfig(
            mode=old_config.routing_mode,
            slots={"local": ..., "cloud": ...}
        )
    )

    TenantModelManager.save("default", tenant_config)
```

---

## 8. 附录

### 8.1 术语表

| 术语 | 定义 |
|------|------|
| Tenant | 租户，独立的配置和资源空间 |
| Model Slot | 模型槽位，分为 local 和 cloud |
| Routing Mode | 路由策略，local_first 或 cloud_first |
| Provider | LLM 服务提供商（OpenAI、Anthropic 等） |

### 8.2 文件列表

| 文件 | 描述 |
|------|------|
| `tenant_models.json` | 租户模型配置文件 |
| `models.py` | 配置数据模型 |
| `manager.py` | 配置管理器 |
| `context.py` | 上下文绑定工具 |
| `exceptions.py` | 自定义异常 |

### 8.3 设计决策记录

| 决策 | 原因 |
|------|------|
| 配置文件而非数据库 | 满足用户需求，易于备份迁移 |
| 租户级别而非工作空间级别 | Agent 共享租户配置，简化管理 |
| default 租户作为 fallback | 向后兼容现有部署 |
| Agent 无权切换模型 | 由租户配置统一管理 |
| 支持 local/cloud 双槽位 | 提供降级能力 |

---

## 9. 审批记录

| 审批人 | 日期 | 备注 |
|--------|------|------|
| Winchester-Yi | 2026-04-03 | 方案确认，进入实现阶段 |
