# HDSky 空论坛掷骰子（拟人）· MoviePilot V3

此插件移植自 [Kuanghom/MoviePilot-Plugins · hdskydicebetnatural](https://github.com/Kuanghom/MoviePilot-Plugins/tree/main/plugins.v2/hdskydicebetnatural)，原作者 **Kuanghom**，上游 V2 版本 1.0.3。

- **当前版本**：2.0.0（MoviePilot V3 专用）
- **宿主要求**：MoviePilot >= 3.0.0
- **V3 适配维护**：xchenya，保留原作者署名和原插件类名 HdskyDiceBetNatural
- **状态**：仅静态与模拟环境测试，尚未进行真实 HDSky 账号登录、下注或开奖联调

## 功能

保留上游 V2 原有能力：

- 固定、随机、智能与倍投四种下注模式；可分别配置大、小、顺子、豹子的金额与加注策略。
- 扫描 HDSky 论坛掷骰主题，读取开奖历史、识别锁定帖和本人已有下注。
- 模拟人工的扫描抖动、进帖停顿、开奖时间窗、随机跳过、金额微抖及假浏览。
- 每日下注次数、观影券次数及当日止盈/止损保护。
- 当日/本周/本月/累计盈亏、待结算记录、当前魔力及消息通知。
- 自动处理论坛评分短讯；保留上游可配置的短讯归档间隔。
- MoviePilot 原生 Cron 调度，以及配置保存后仅运行一次。

## 安装与配置

在 MoviePilot V3 的第三方插件市场中添加或保留：

https://github.com/xchenya/MoviePilot-Plugins

刷新插件列表，安装「空论坛掷骰子（拟人）」，选择站点管理中的 HDSky（hdsky.me）。Cookie、User-Agent 与代理选项从站点管理读取，不需要在本插件中另存 Cookie。

**首次安装建议先不开启自动下注。** 先确认已正确选择站点、Cron、下注策略、魔力余额和每日次数上限。建议设置当日止盈、止损并从最小允许下注金额开始；自动下注不会保证正收益，倍投同样存在风险。

## V3 迁移说明

| 模块 | V3 处理 |
|---|---|
| 导入与平台 | 使用 V3 的 app.sdk.config、app.sdk.logging、app.sdk.network、app.sdk.plugin 和正式 SiteOper |
| 任务调度 | 去除插件自建 BackgroundScheduler；由 MoviePilot 宿主管理 Cron 和单次 DateTrigger |
| 配置 | 保留原配置字段；一次性开关保存复位失败时，不执行下注 |
| 状态隔离 | 线程锁、可变配置和运行上下文绑定插件实例；旧一代任务取消后不会因重载重新发起写入 |
| 认证与网络 | 限定 HTTPS 的 hdsky.me / www.hdsky.me；禁用请求自动重定向，避免 Cookie 意外传到非目标域 |
| 下注确认 | 必须在目标帖解析出本人的对应类型及金额，才能记录成功；返回不明确时停止本轮后续下注 |
| UI | 使用 V3 原生 VCronField；继续保留 V2 的历史统计与详情页结构 |
| 测试 | 采用 mock 检查调度、旧配置、隔离、跨域拦截及未确认下注，不发送真实网络请求 |

旧版是较大型的单文件插件，部分论坛页面和回复格式可能发生变化；V3 迁移不等于已验证站点业务结果。**遇到“下注结果未确认”时，先到论坛核对该主题是否已有自己的回复，不要立即手动重试。**

## 来源与许可注意

截至本次迁移检查，原作者仓库没有发现明确的 LICENSE 文件。保留原作者 Kuanghom 及其源代码地址，不把 V3 移植视为取得原作者授权。公开分发或继续发布前，建议向原作者确认许可；如对方提出保留、调整或删除要求，应按其许可处理。
