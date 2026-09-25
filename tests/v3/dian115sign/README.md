# Dian115Sign 测试说明

日期：2026-09-25。插件版本：2.0.0；目标宿主：MoviePilot V3。

## 已完成与未完成

| 检查 | 结果 |
| --- | --- |
| Python 语法编译 | 通过 |
| 离线逻辑与接口适配层回归 | 40 项通过 |
| Chromium + 内存模拟站点用例 | 16 项跳过；测试环境的导航策略阻止运行 |
| 真实 MoviePilot 加载、API 和调度注册 | 尚未验证 |
| 当前癫影页面、真实登录和签到 | 尚未验证 |

这些结果来自隔离开发环境，不是生产 MoviePilot 运行环境，也不是 GitHub Actions 成功报告。浏览器测试的跳过不算通过，离线测试通过也不能证明 HTTP 403 已解决。

## 离线测试

在独立开发环境、仓库根目录运行：

```bash
DIAN115_OFFLINE_TEST=1 python -m pytest \
  --confcutdir=tests/v3/dian115sign \
  -q tests/v3/dian115sign/test_plugin.py

python -m compileall -q plugins.v3/dian115sign
```

需要 pytest 与 Pydantic 2。使用干净的独立进程，不能与已加载 MoviePilot 的测试进程混用；不要为离线测试修改生产环境依赖。

本目录的 `conftest.py` 仅在 `DIAN115_OFFLINE_TEST=1` 时安装宿主基类、事件、存储和调度器的测试替身；未显式启用时不收集这两份离线测试文件。没有替换仓库根级测试配置。测试采用 `app.plugins.dian115sign` 命名空间，但不代表使用真实宿主。

40 项用例覆盖 Cookie 解析、目标域限制、敏感信息处理、403 与认证失败区分、模式校验、重复提交、状态写入失败、取消、配置重载、一次性任务声明、缓存页面、API 合同、分身 ID、并发拦截、配置与浏览器错误分类。

## 可选浏览器测试

安装开发环境所需的 Playwright，并用 `DIAN115_CHROMIUM` 指向已经安装的 Chromium：

```bash
DIAN115_OFFLINE_TEST=1 DIAN115_CHROMIUM=/实际路径/chromium \
  python -m pytest --confcutdir=tests/v3/dian115sign \
  -q tests/v3/dian115sign -r s
```

`test_browser.py` 使用真实 Chromium 与内存模拟网页，拦截请求，不使用真实癫影账号。覆盖诊断不签到、两种签到模式、403 停止、密码登录、跨域跳转、已签到、409 区分、响应丢失、待确认保护、模式不符和缓存失败。

原测试环境存在 Chromium，但本地拦截网页也被托管策略阻止，返回 `ERR_BLOCKED_BY_ADMINISTRATOR`，因此跳过 16 项。没有修改或绕过策略。即使这些模拟站点测试全部通过，仍需在真实 V3 宿主与站点执行一次诊断、一次受控普通签到，再启用定时任务。
