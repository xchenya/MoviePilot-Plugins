# MoviePilot-Plugins

xchenya 的 [MoviePilot](https://github.com/jxxghp/MoviePilot) 第三方插件库。

本仓库基于官方 [jxxghp/MoviePilot-Plugins](https://github.com/jxxghp/MoviePilot-Plugins) 初始化，仅用于维护本人开发、重构或长期维护的插件。

## 插件列表

| 插件 | 目录 | 版本 | 状态 |
|---|---|---|---|
| [癫影自动签到](./plugins.v3/dian115sign/README.md) | `plugins.v3/dian115sign` | `2.0.5` | V3 测试版；普通签已实测 |

癫影签到为独立重写测试版，要求 **MoviePilot V3**；插件版本 `2.0.5` 不代表支持 MoviePilot V2。已完成真实账号普通签到验证；首次安装仍建议先运行诊断。详见插件说明与[测试说明](./tests/v3/dian115sign/README.md)。

## 使用方法

### MoviePilot 插件市场

在 MoviePilot 的第三方插件市场配置中加入本仓库：

```text
https://github.com/xchenya/MoviePilot-Plugins
```

如通过环境变量配置，可将仓库地址加入 `PLUGIN_MARKET`；多个仓库地址使用逗号分隔。

MoviePilot 插件市场读取仓库的 `main` 分支。

## 目录结构

```text
MoviePilot-Plugins/
├── plugins/                    # V1 / 历史插件（按需使用）
├── plugins.v2/                 # MoviePilot V2 插件
├── plugins.v3/                 # MoviePilot V3 插件
├── icons/                      # 插件图标
├── tests/
│   └── v3/                     # V3 插件测试
├── docs/                       # 官方开发与迁移文档
├── scripts/                    # 官方辅助脚本
├── .github/                    # CI / Release 工作流
├── package.json                # V1 插件索引
├── package.v2.json             # V2 插件索引
├── package.v3.json             # V3 插件索引
└── README.md
```

## 开发约定

- V2 插件放在 `plugins.v2/<plugin_id_lower>/`。
- V3 新插件优先放在 `plugins.v3/<plugin_id_lower>/`。
- 插件目录名使用插件主类名的小写形式。
- 插件版本、索引版本及最新更新记录保持一致。
- V2 插件同步维护 `package.v2.json`；V3 插件同步维护 `package.v3.json`。
- 图标统一放在 `icons/`，或在插件索引中使用稳定的远程图标地址。
- V3 测试放在 `tests/v3/<plugin_id_lower>/`。
- 第三方插件依赖及实现应遵循当前 MoviePilot 对应版本的开发规范。

## 开发文档

- [V3 插件开发指南](./docs/Plugin_Development.md)
- [V2 插件开发指南](./docs/V2_Plugin_Development.md)
- [V2 → V3 迁移指南](./docs/V3_Plugin_Adaptation.md)
- [仓库与发布指南](./docs/Repository_Guide.md)
- [FAQ](./docs/FAQ.md)

## 说明

本仓库是个人维护的第三方插件仓库，并非 MoviePilot 官方插件市场。插件使用前请阅读对应说明，并根据自己的 MoviePilot 版本确认兼容性。

## 致谢

- [MoviePilot](https://github.com/jxxghp/MoviePilot)
- [MoviePilot-Plugins](https://github.com/jxxghp/MoviePilot-Plugins)
- [JinxJie/MoviePilot-Plugins](https://github.com/JinxJie/MoviePilot-Plugins)
