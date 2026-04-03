# 贡献指南 & 开发规范

本文档说明如何向 streamstack-labs 贡献代码，以及如何在 StreamStack 项目中开发和集成实验室模块。

---

## 架构原则

```
┌─────────────────────────────────┐
│   streamstack-labs (开源/GPL-3)  │
│   纯工具逻辑，零 ORM 依赖        │
│   config 通过函数参数传入        │
└──────────────┬──────────────────┘
               │ pip install / git submodule / 直接 import
┌──────────────▼──────────────────┐
│   StreamStack (私有/商业)        │
│   API 路由 + 鉴权 + ORM 读写    │
│   从 DB 读 config 后传入 labs   │
└─────────────────────────────────┘
```

**核心约束**：`streamstack-labs` 中的每个模块必须是独立可运行的纯工具库，不依赖 StreamStack 的 ORM 模型、数据库 Session、FastAPI 路由等内部基础设施。

---

## 开发新实验室模块的标准流程

### 第一步：在 streamstack-labs 中写纯逻辑

新建模块目录，遵循以下结构：

```
my_module/
├── __init__.py       # 导出公开 API
└── core.py           # 核心逻辑
```

**规则**：

1. 所有配置通过函数参数传入，不读取数据库或环境变量
2. 不 import 任何 StreamStack 内部模块（models、outbound_log、services 等）
3. 不使用 FastAPI 的 HTTPException，失败时返回含 `error` 键的 dict 或抛出标准 Python 异常
4. 每个模块必须可以通过 `python -m my_module.core` 独立运行（方便调试）
5. 异步函数使用 `asyncio.run()` 包装命令行入口

**示例骨架**：

```python
# my_module/core.py
"""
my_module.core
~~~~~~~~~~~~~~
简短的模块说明。

使用方法：
    from my_module import do_something
    result = asyncio.run(do_something(config={"key": "value"}))
"""
from __future__ import annotations
from typing import Optional
import httpx

async def do_something(config: dict, proxy_url: Optional[str] = None) -> dict:
    """做某件事。config 由调用方从数据库读取后传入。"""
    ...

if __name__ == "__main__":
    import asyncio, sys
    asyncio.run(do_something(config={}))
```

### 第二步：在 StreamStack 中封装 API 路由

StreamStack 的 `api_xxx.py` 只做三件事：

```python
# StreamStack: backend/api_my_feature.py
from my_module import do_something

@router.post("/my_feature/")
async def my_feature_endpoint(db: Session = Depends(get_db), ...):
    # 1. 从数据库读取配置
    cfg = {c.key: c.value for c in db.query(AppConfig).filter(...).all()}
    # 2. 调用 labs 函数（传入 config，不传 db）
    result = await do_something(config=cfg, proxy_url=cfg.get("PROXY_URL"))
    # 3. 写回结果（如需要）
    return result
```

---

## 模块耦合度判断

在决定是否提取到 streamstack-labs 时，参考以下标准：

| 可以提取 | 不适合提取 |
|---|---|
| 只需要 httpx / 标准库 | 依赖 SQLAlchemy Session 或 ORM 模型 |
| 配置可以通过参数传入 | 需要实时查询数据库（如 Account115） |
| 可以独立运行和测试 | 与 Emby / 115 网盘 API 深度绑定 |
| 逻辑通用，与 StreamStack 无关 | 需要 StreamStack 特有的文件系统结构 |

---

## 提交规范

### Commit Message 格式

```
<type>: <短描述>（< 50 字符）

<可选：详细说明>
```

`type` 枚举：
- `feat`：新增模块或功能
- `fix`：修复 bug
- `refactor`：重构（不改变功能）
- `docs`：文档更新
- `test`：测试相关

示例：
```
feat: 新增 hdhive_checkin 模块（签到 + 积分查询）
fix: tmdb_hosts 修复 IPv6 地址被误判为公网 IP 的问题
docs: 更新 README 中 ep_rules 的使用示例
```

### Pull Request 要求

1. 每个 PR 专注一件事（单模块、单功能）
2. 新模块须包含 `__main__` 入口可运行演示
3. 更新 README.md 中对应模块的说明和示例

---

## 本地开发环境

```bash
# 克隆仓库
git clone https://github.com/streamstack-cn/streamstack-labs.git
cd streamstack-labs

# 安装依赖
pip install httpx pyyaml

# 验证各模块可独立运行
python -m tmdb_hosts.resolver
python -m ep_rules.rules "测试标题" 5
python -m hdhive_checkin.checkin --help
```

---

## 许可证

本项目采用 **GPL-3.0** 协议。提交 PR 即表示你同意将贡献以相同协议开源。
