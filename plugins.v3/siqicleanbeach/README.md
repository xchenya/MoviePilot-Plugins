# 思齐自动收垃圾（SiQiCleanBeach）

本插件是 [bfjy2024/MoviePilot-Plugins](https://github.com/bfjy2024/MoviePilot-Plugins/tree/main/plugins.v2/siqicleanbeach)
中 V2 插件「思齐自动收垃圾」的 **MoviePilot V3 移植版**。

- 原作者：bfjy；V3 适配维护：xchenya。
- 插件版本：**2.0.0**；宿主要求：**MoviePilot >= 3.0.0**。
- 功能：自动进入思齐沙滩、收集垃圾、获取物品库存、展示近 20 次执行历史、发送消息通知。
- 调度方式：支持 5 段 Cron 或固定分钟间隔；支持保存配置后运行一次、/siqi_clean_beach 命令和带认证的手动运行 API。

## 安装

在 MoviePilot V3 中将 https://github.com/xchenya/MoviePilot-Plugins 加入第三方插件市场，刷新插件列表并找到「思齐自动收垃圾」。

配置「启用插件」、定时模式和通知。**Cookie 留空时会从 MoviePilot 站点管理读取域名 si-qi.xyz 的 Cookie**；也可以自行填写包含 c_secure_pass 的 Cookie。不要把 Cookie 粘贴到 Issue、截图、日志或公开配置中。

默认每 121 分钟执行一次，可通过「立即运行一次」单独测试。关闭定时开关不影响手动运行。

## API 与命令

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | /api/v1/plugin/SiQiCleanBeach/run | 后台启动一次收集任务 |
| GET | /api/v1/plugin/SiQiCleanBeach/stats | 获取执行记录与库存缓存 |

以上 API 均使用 MoviePilot 的 Bearer 鉴权，页面不包含独立公开操作链接。详情页展示已缓存的数据，任务结束后重新打开/刷新详情页可查看最新结果。

## V3 改动

- 换用 V3 原生 app.sdk.events、app.sdk.logging，以及宿主正式的 app.db.oper.site.SiteOper。
- 每个插件实例独立持有运行锁、历史和库存，避免分身或重载时状态交叉。
- 手动执行先抢占运行锁，再启动后台线程，防止并发重复启动。
- 所有 HTTPS 请求启用证书校验，不再全局关闭 urllib3 证书警告。
- 用 BeautifulSoup 解析库存 DOM，过滤「砖块」，保留站点 HTML 结构变化时的历史缓存。
- 保存失败、Cookie 失效等执行结果；声明 V3 API 返回模型。

## 注意事项与测试状态

**当前为 V3 兼容性测试版，尚未使用真实思齐账号完成宿主联调。** 原站点网页和接口可能变化，若收集动作失败，应检查站点登录状态及 HTML/JSON 响应。为安全考虑，不会自动忽略失效的 HTTPS 证书。

已提供不访问真实站点的解析、Cookie、安全和并发单元测试。请先手动执行一轮并核对站点侧结果，再启用定时任务。

## 版权与许可

原始代码与修改版沿用上游仓库的 [GPL-3.0 许可](https://github.com/bfjy2024/MoviePilot-Plugins/blob/main/LICENSE)。
保留原作者署名；此插件不是 bfjy 官方发布的 V3 版本。
