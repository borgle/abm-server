# abm-server 文档索引

这是开源的 core / 单用户版。托管版的多用户、套餐、审批、计费和用户管理不在本仓库。

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 系统目标、边界、组件、HTTP/MCP/WebSocket 契约、安全与部署 |
| [detailed-design.md](detailed-design.md) | 模块实现、事务、并发、失败处理 |
| [data-flow.md](data-flow.md) | 注册、登录、OAuth、工具调用、视频投递链路 |
| [scenarios.md](scenarios.md) | 典型操作、参数、预期结果与恢复 |
| [creation-module.md](creation-module.md) | 创作台产品、交互、数据与接口 |
| [creation-media-and-layout.md](creation-media-and-layout.md) | 图片生成、对象存储、公众号/小红书导出 |
| [mcp-agent-guide.md](mcp-agent-guide.md) | MCP 客户端接入 |
| [ui-design-system.md](ui-design-system.md) | 设计 token 与组件规范 |
| [local-mode.md](local-mode.md) | 本机单用户部署与扩展连接 |

## 范围说明

- 单用户版保留登录、扩展、MCP、创作台、本机模型配置和本地额度
- 多用户、注册审批、套餐、计费、审计后台属于托管版，不在本仓库
- 文档里出现「套餐 / 审批 / 用户管理」的段落，是 core 为托管版保留的扩展点说明；开源构建会把对应接口返回 404

## 维护规则

- 公开 API、MCP 工具 Schema、`abm/1` 消息、错误码、环境变量或数据库结构变化时更新 `architecture.md`
- 模块职责、事务边界、并发或失败处理变化时更新 `detailed-design.md`
- 端到端链路变化时更新 `data-flow.md` 和 `scenarios.md`
- 文档中的命令、路径、字段名必须与代码一致
