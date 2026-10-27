# 天空社区客户端签到测试

运行：

```bash
python -m pip install 'APScheduler>=3.10,<4'
python -m unittest discover -s tests/v3/hdskycommunitysign -p 'test_*.py' -v
```

共 **41 项测试**。测试进程提供最小 MP SDK 替身，使用真实标准库 CookieJar、urllib Request 和 APScheduler CronTrigger；仅替换 HTTP 传输，不连接社区、不发送验证码、不执行真实签到。

覆盖认证与 Cookie 持久化、客户端请求合同、已签到跳过、一次性操作复位、通知去重、历史上限、精确 CSRF 错误重试、超时与异常响应核对、重启防重、写请求前持久化意图、次日签到、限流冷却、Cron 时间计算、启停及过期回调、凭据脱敏。

这组测试验证离线协议与插件行为，不替代真实 MoviePilot V3 宿主和真实账号联调。APScheduler 由 MP 宿主提供，没有新增插件私有第三方依赖。
