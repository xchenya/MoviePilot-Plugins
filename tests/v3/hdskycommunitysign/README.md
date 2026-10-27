# 天空社区客户端签到测试

运行：

```bash
python -m pip install 'APScheduler>=3.10,<4' 'pydantic>=2,<3'
python -m unittest discover -s tests/v3/hdskycommunitysign -p 'test_*.py' -v
```

共 **56 项后端测试**。测试进程提供最小 MP SDK 替身，使用真实标准库 CookieJar、urllib Request、APScheduler CronTrigger 和 Pydantic 模型；仅替换 HTTP 传输，不连接社区、不发送验证码、不执行真实签到。

覆盖原 41 项认证与 Cookie 持久化、客户端请求合同、已签到跳过、一次性操作复位、通知去重、历史上限、精确 CSRF 错误重试、超时与异常响应核对、重启防重、写请求前持久化意图、次日签到、限流冷却、Cron 时间计算、启停及过期回调、凭据脱敏；新增直接登录 API、连接设置应用、冷却回传、配置保存失败保护、宿主任务刷新、按账号日期聚合、未知奖励、旧历史幂等迁移及 30/90 天边界。

前端测试（Node.js 24+）：

```bash
cd plugins.v3/hdskycommunitysign
npm ci
npm test
npm run build
```

**11 个前端交互场景**，在 jsdom 中编译并挂载实际 Vue/Vuetify 组件，使用模拟的宿主认证 API。验证无需保存的验证码/登录操作、倒计时、快速重复点击、保留尚未保存设置与校验失败的输入、错误后不重发、输入清空、加载失败禁用操作、当前实例 API 路径、每日统计切换及启用边界。测试不是静态源码字符串匹配。

这组测试验证离线协议与插件行为，不替代真实 MoviePilot V3 宿主和真实账号联调。APScheduler、Pydantic 及调度 SDK 由 MP 宿主提供，没有新增插件私有 Python 第三方依赖；Vue/Vuetify 在运行时共享宿主实例。用户已确认 1.0.0 验证码登录可用，新页面和统计仍待宿主验证。
