# 思齐餐厅（MoviePilot V3）

在 MoviePilot 插件详情页内经营 `https://si-qi.xyz/siqi_restaurant.php`。这是原生 Vue 联邦面板，由 MP 后端使用思齐登录凭据请求站点，不需要 iframe 或第三方 Cookie。

## 安装与设置

1. MoviePilot **V3 ≥ 3.0.0**，插件管理中使用“本地安装/上传插件”选择 `siqirestaurant_v1.0.0.zip`。安装包已包含 `dist`，不需要在 NAS 编译前端。
2. 在 MP 站点管理中添加思齐并维护有效 Cookie 和 User-Agent。
3. 进入插件配置，启用插件；按需开启 MP 系统代理。也可填写独立 Cookie，留空保留当前配置，勾选清除后回退到站点管理。
4. 保存后返回餐厅，刷新状态。先核对余额、库存、员工、当日营业状态，再开始经营。

Cookie 不会出现在面板响应、安装包或操作日志中；固定发往 `https://si-qi.xyz`，不跟随站点重定向。插件没有自动开店或其他后台定时任务。

## 支持功能

- 概览：魔力余额、欢迎值、顾客完成数、今日与累计净收益。
- 厨房：选择菜品、备齐食材和工具、按实际时长烹饪、选择餐位上菜、取消备菜、成品归位/丢弃。
- 经营：每日手动开业、顾客耐心计时、到时离席、10 秒清桌冷却。
- 商店：库存与厨房预留量、指定数量购买、购买金额确认。报价超出确认预算时拒绝提交。
- 员工：每次雇佣 1 人、分配/撤回厨师和服务员；显式打开“运行已雇员工”后按原网页的同编号餐位模式服务。
- 下馆子：用户名查询、随机推荐、手动到访、保留站点二次确认。
- 日志：站点返回的经营记录、7/30 天筛选，以及最近 100 条插件站点操作记录。

“运行已雇员工”仅在面板可见时通过页面心跳执行，默认关闭；关闭面板、切换页面或浏览器标签进入后台后停止。计时按服务器绝对时间继续，重新打开可恢复厨房进度。顾客仍按站点时间消耗耐心，因此不要在营业中长期离开。

厨房的选择/备菜/计时原本由网站浏览器维护，并没有对应的站点烹饪 API。本插件独立维护这部分状态，保存在 MP 插件数据中。网页与 MP 厨房互不共享，**建议只使用其中一端经营**。站点库存仍以服务器数据为准，取消备菜仅释放本地预留；成品“归位”和“丢弃”均调用网站的 `discard_dish`，会按网站规则扣除食材。

## 请求与故障处理

所有路由使用 MP Bearer 认证。页面操作串行执行；携带请求编号的操作会防止重复提交，最近 128 条编号跨 MP 重启保留。站点写请求不自动重试。

当超时、返回验证页面或响应结构异常而无法判断写入是否成功时，插件会持久化未确认请求并锁定后续写入。刷新不会自动解锁。请核对网站余额、库存、员工和顾客状态，再点击“已核对，解除锁定”。原请求不会被重发，不确定成品的本地预留会释放。

Cookie 发生变化时，本地厨房状态隔离重建；跨日时清空旧厨房和清桌状态。不要在烹饪途中更换账号或 Cookie。

## 为后续自动化保留的接口

基础路径：`/api/v1/plugin/SiqiRestaurant`（分身使用运行态插件 ID）。

| 路由 | 用途 |
| --- | --- |
| GET `/state` | 餐厅快照、厨房、清桌计时、操作日志 |
| POST `/refresh` | 强制刷新站点状态 |
| POST `/action` | 已验证的受限操作；参数为 `action`、`args`、唯一 `request_id` |
| POST `/tick` | 更新计时、处理到时离席；`run_staff: true` 执行已分配员工 |
| GET/POST `/config` | 安全读取/更新配置；GET 不返回 Cookie |
| POST `/resolve` | `acknowledged: true`，人工核对后解除不确定写入锁 |

本地厨房动作：`assign_dish`、`prepare`、`cook`、`cancel`、`return_stove`、`serve`、`discard`。使用从 1 开始的 `station_index`；上菜同时传 `customer_id`。

站点操作：`start_session`、`purchase_ingredient`、`hire_staff`、`update_staff_assignment`、`visit_restaurant`、`list_visitable_restaurants`、`inspect_restaurant_target`。购买与雇佣必须传 `max_cost`，不会自动补货、自动雇佣或自动下馆子。直接转发 `serve_customer` 等原始操作不开放，必须经过厨房状态校验。

示例（通过 MP 认证 API 调用）：

```json
{
  "action": "purchase_ingredient",
  "args": {"ingredient_key": "egg", "quantity": 2, "max_cost": 24},
  "request_id": "replace-with-a-unique-request-id"
}
```

后续可在这套接口上添加按日开店、补货预算、员工排班和策略任务。目前没有注册定时服务，也没有设置无人值守策略。

## 验证范围与当前限制

- 接口名称、参数、响应字段依据 2026-10-19 实际页面前端脚本核对。
- 已运行离线 FastAPI/状态机测试、Vue 组件交互测试、联邦构建及仓库版本/CSS 门禁。
- 当前浏览器拦截了数据接口直接导航，**尚未在真实 MP 环境安装和完成站点开业/购买/上菜联调**；此版本作为首个测试版交付。测试没有消耗账号魔力、每日开业或下馆子次数。
- 兼容标准 `seat-bound` 员工模式；如站点返回其他模式，暂停员工执行，保留手动操作。
- 厨房与请求锁为单个插件实例管理。请勿为同一账号运行多个插件分身或同时在网页经营。
- 日志日期筛选仅针对站点本次返回的记录，不承诺获取网站没有返回的历史。

## 开发

```bash
cd plugins.v3/siqirestaurant
npm ci
npm run build
cd ../..
python -m pytest -q tests/v3/siqirestaurant
node tests/v3/siqirestaurant/test_frontend.mjs
python .github/scripts/check_federation_css.py
```

Python 离线测试依赖 `pytest requests pydantic fastapi httpx`，不需要站点 Cookie。测试夹具为合成数据，不包含用户实际账号信息。前端依赖沿用仓库现有思齐农场构建方案，样式仅使用 `sr-` 前缀。
