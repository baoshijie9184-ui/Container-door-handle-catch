# 数据库脚本目录

按数据库类型组织建表、迁移、种子数据和工具脚本：

```text
sql/
├── db2
├── dm
├── highgo
├── kingbase
├── mysql
├── opengauss
├── oracle
├── postgresql
├── sqlserver
└── tools
```

约定：

- `mysql/` 保存当前生产数据库的 schema、migration 和 seed 脚本。
- 其他数据库目录用于后续适配，脚本命名与 MySQL 版本保持对应。
- `tools/` 只放数据库初始化、校验和转换工具，不放业务 SQL。
- 迁移脚本必须幂等或明确版本顺序，执行破坏性变更前先备份并校验目标数据库。
- 应用运行时兼容资源暂保留在 `doorhandle-server/src/main/resources/db`；新增 SQL 以 `sql/<database>` 为规范归档位置。
