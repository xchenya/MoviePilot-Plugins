# 天空社区客户端签到

MoviePilot V3 插件，版本 **1.0.0**。使用 HDSky 社区 Windows 客户端的每日签到接口，支持站内信验证码登录、手动 Cookie、定时签到、结果通知和历史记录。

## 安装与使用

在 MoviePilot 的第三方插件市场加入 `https://github.com/xchenya/MoviePilot-Plugins`，刷新市场，搜索 **天空社区客户端签到** 并安装。要求 MoviePilot V3；插件版本 1.0.0 不表示支持 MoviePilot V1。

两种登录方式任选其一：

- **站内信登录**：启用插件，填写 HDSky 数字 UID，选择“1. 发送站内信验证码”并保存。收到站内信后重新打开配置页，输入六位验证码，选择“2. 提交验证码并登录”并保存。
- **手动 Cookie**：复制已登录社区页面中 `/api/portal/session` 请求的 Cookie 请求头，粘贴到“手动填写社区 Cookie”并保存。UID 可留空；填写时会核对账号一致性。需要 `hdsky.supertimi.de` 社区 Cookie，通常包含 `hdsky_portal_session`，不是 `hdsky.me` 主站 Cookie。

登录成功后，选择“立即签到（仅一次）”并保存，在插件详情页查看结果。开启“每日定时签到”后默认每天 **08:00** 执行，Cron 时区跟随 MP；也可在 MP 服务页运行已注册的签到服务。

每次保存都会清空一次性操作、验证码和手动 Cookie 输入框。输入框留空会保留已保存会话；取消启用只停止执行。配置页与详情页不显示 Cookie 或 CSRF Token。

## 签到行为

- 每次先查询服务器今日状态；已签到则跳过提交。
- 对未签到账号发送一次客户端签到请求，携带当前 Cookie、CSRF Token 和随机请求键。
- 仅在服务器明确返回已核实的 CSRF 过期错误时刷新会话并重试一次，复用同一请求键。
- 提交超时、服务器错误或响应无法确认时，只查询一次状态。仍无法确认就暂停该账号当天的重复提交；下次运行仍可查询并确认完成。
- 提交意图和结果持久化，重启后不会自动重放未知结果的请求。插件本地防重日期按北京时间划分，真实签到状态以服务器为准。
- HTTP 429 按 Retry-After 冷却，无有效值时默认 5 分钟；Cookie 失效需重新登录。
- 保存最近 60 条结果，详情页显示最近 30 条；可关闭通知。服务器提供数值时显示今日奖励和银元余额。
- 可选使用 MP 代理。默认直连，保留 TLS 证书验证，不跟随重定向转发凭据。

## 接口依据

来自官方 Windows 客户端 **0.8.27 / Build 67** 的调用约定。该版本为 .NET WPF 客户端。

| 用途 | 方法与路径 |
|---|---|
| 发送站内信验证码 | POST /api/portal/auth/start |
| 提交验证码 | POST /api/portal/auth/verify |
| 查询会话与今日签到状态 | GET /api/portal/session |
| 客户端签到 | POST /api/portal/daily-checkin |

接口基址：`https://hdsky.supertimi.de:8443`。

签到请求包含 `X-HDSky-Client: app`、`X-HDSky-Platform: windows`、`X-CSRF-Token` 和会话 Cookie；JSON 为 `{"requestKey":"32位十六进制随机值"}`。默认 User-Agent 使用该客户端主 API 中的 `HDSkyWindows/0.6.0-rc.1`，与安装包版本号不同。

只实现认证与每日签到，不包含兑换、游戏或其它社区操作。

## 验证与更新

已完成 **41 项离线测试**，使用真实 CookieJar 和 APScheduler CronTrigger，模拟 HTTP 传输及 MP SDK。覆盖协议、认证、Cookie 轮换、签到防重、CSRF、异常响应核对、重启、冷却、调度与凭据脱敏。详见 [测试说明](../../tests/v3/hdskycommunitysign/README.md)。

发布前未使用真实账号执行签到，也未完成真实 MP 宿主加载验证。首次安装请先登录并执行一次“立即签到”核对结果。

- **1.0.0**：首个正式发布版本，接入客户端签到；保留 UID/站内信登录和手动 Cookie，新增每日调度、通知、历史和重复提交保护。

作者：xchenya。许可证：GPL-3.0-only。
