# Changelog

本文件记录 `bmc_autotest` 项目的所有重要变更。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

> 说明：**项目版本**与所依赖的 `redfish-python-sdk` **SDK 版本**相互独立。
> 每个项目版本均标注其锁定的 SDK 版本，便于追踪脚本与 SDK 的兼容关系。

## [Unreleased]

## [1.3.0] — 2026-10-26

真机验证反馈批量修复 + 上游 PR 可用点吸收（issue/9）。
基于多厂商真机验证（通算/存储/GPU 机型）反馈的 9 项脚本缺陷修复，
同时吸收上游多个未合入 PR 中经真机验证的有效改动。
共 58 个文件（+2241/-766），新增 3 个公共模块。

### Fixed — 真机验证反馈修复（9 项）

- `managers_003_ethernet_interfaces_check`：网口校验区分 Detect/Sharelink 口
  （`Oem.Public.NCSIModeSelect` 存在即为 Sharelink 口），Sharelink 口仅做 MAC
  格式校验，不再因统一要求 `InterfaceEnabled==True` 误判 FAIL。
- `managers_006b_port_enable_disable` / `managers_002_network_protocol_check`：
  移除 HTTP 检查项（业务侧明确不使用），仅保留 HTTPS。
- `managers_006_port_status_check`：KVM/IP 端口无 DMTF/IANA 标准，
  `==7578` 精确匹配改为「存在且合法（1-65535）」；HTTPS/SSH/IPMI 保留标准端口精确匹配。
- `systems_005_power_control_test` / `ipmi_001_power_status`：电源操作三级阈值
  持续轮询判定（≤120s PASS / 120~900s PASS+WARNING / >900s FAIL），
  仅真 FAIL 才触发 ForceOff 复位，避免残留状态污染下一步；
  ipmi_001 各操作独立阈值。
- `ipmi_010_user_delete`：删除判定改用 `priv=NO ACCESS`（IPMI Msg 列与 disable
  是协议语义上两个独立开关，原判定依据选错）；新增 `pre_safety_check` 前置步骤，
  目标槽位已有非预期用户名时中止测试，避免误删业务用户。
- `ipmi_013_user_session`：ipmitool 非零返回码为已知共性问题（各方认可），
  去掉 `rc != 0` 判定，仅以输出为空判失败。
- 用户名/密码规则全量整改（account + ipmi）：用户名 4~16 位全英文字母、
  密码 8~12 位四要素（大小写+数字+特殊字符，硬规定）；
  修正 conf 与脚本中所有违规用户名（含数字/下划线/长度不足）与超长密码。

### Changed — 测试用例重构

- `account_007_username_rule_test`：重写——正向 3×3 等价类×边界值矩阵（7 例）
  + user_name 原样保留校验（防截断/大小写规范化）+ 反向用例
  （长度越界→WARNING 不 FAIL，OEM 通用版本不强制定制；字符集违规→FAIL）
  + 逐用例「创建→验证→立即删除」防账号数上限误判。
- `account_003b/003c_password_modify_test`：正向 6 例（长度点×要素组合）
  + 旧密码失效双向校验（防假成功）；反向缺要素等价类 2→5 例
  + 长度越界宽松组 + 真实登录验证（防静默忽略假拦截）。
- `ipmi_012_user_disable`：废弃——唯一判定依据（IPMI Msg==false）不成立，
  业务认可现状；从 runner suite 移除，脚本保留废弃标注。

### Added — 机型差异适配与公共模块

- `bmc_runner`：新增 `--skip-no-gpu` / `--skip-no-storage` 机型差异跳过参数，
  跳过用例计入报告（`result='SKIPPED'`），三种报告格式同步展示；
  打通 exit_code=3 → SKIPPED 映射。
- 新增 `func/sel_log_helper.py`：SEL LogService 跨 Systems/Managers 统一定位
  （严格 `\bSEL\b` 独立词匹配 + 排除并列 EventLog 服务 + LogId 显式配置），
  6 个 SEL 脚本委托公共助手消除逻辑漂移；managers_004a 保留 OR 判定语义。
- 新增 `func/redfish_event_compat.py`：Event 测试公共辅助
  （订阅 EventTypes 交集决策 / SubmitTestEvent legacy-modern 模式探测 /
  Base Registry MessageId 解析）。
- `common_function`：新增跨平台工具 `is_windows()` / `ping_cmd()` / `ping_once()` /
  `ipmitool_bin()`（Windows 与 Linux 的 ping 参数、ipmitool 可执行名差异统一收敛）。
- `systems_005_power_control_test`：新增 ResetType UNSUPPORTED 第三态
  （AllowableValues 预检 + POST 400 收紧判定，机型差异不影响整体结果）；
  GracefulShutdown 超时 FAIL 后追加 OS 可达性诊断（仅诊断不改判定）。
- `systems_007_sel_log_view`：新增 `EmptyLogPolicy`（FAIL/SKIP）配置，
  条目为空默认 FAIL（防误选空服务假 PASS）。
- `update_002/003`：新增 `--vendor` 显式指定 / VendorDetector 自动探测
  （失败终止）；conf 厂商分段结构（`vendors.{厂商}` + `default` 回退）；
  BIOS 下电升级前置开关（`PowerOffBeforeUpgrade`）；SDK 连接重试参数全覆盖。

### Changed — 上游 PR 可用点吸收（均未合入 upstream/main，手动移植避免冲突）

- `web_012_one_click_log` / `systems_011_log_download_test`：一键日志改用 SDK
  `collect_and_download_diagnostic_data()` 一站式采集+下载+文件非空校验，
  消除「触发成功即 PASS」误判；systems_011 补传 `output_path`（证据留存）、
  `DiagnosticDataType` 改 None（SDK 厂商自适应）。
- `systems_010a_sel_log_clear_positive`：Managers 侧清除改用 SDK `clear_manager_log()`。
- `event_004_get_subscription`：空订阅误 FAIL → 自动创建临时订阅
  （唯一 Context+uuid 归属）→ 查询 → 精确清理。
- `event_003/006_create/delete_subscription`：订阅 EventTypes 硬编码
  → 与 `EventTypesForSubscription` 求交集，空则 None（厂商默认）。
- `event_009_submit_test_event`：双路径提交（ActionInfo 探测 modern=MessageId
  自动从 Base Registry 解析 / legacy=EventType 循环）+ 响应 Message 结构校验
  （字段缺失 WARNING 不 FAIL）；非标准私有参数不做兼容。
- `update_002/003`：`simple_update()` 增加 vendor 路由与厂商私有参数透传
  （Targets/镜像源凭据/ImageType/PreserveConf 经 kwargs 交 SDK 策略消费，
  脚本层保持厂商无关）。

### Changed — 配套 conf 更新

- `bmc_runner_suites.json`：managers 补全 17 个脚本（11→28，与目录对齐）；
  ipmi 移除 ipmi_012；systems_005 超时 5400→8000s、ipmi_001 新增 1000s。
- systems_005/007、ipmi_001、event、update、web_012、account 各 conf
  同步新增配置项（均带注释说明）。

### 依赖
- 将 `redfish-python-sdk` 锁定至 **v1.3.0**（PyPI 最新发布版本，2026-10-12）。
- SDK 演进路径（增量）：
  - **v1.3.0**（2026-10-12）：新增 Manager 服务类接口（NTP/Syslog/SNMP/LLDP/DNS/VNC/
    KVM/Security/VirtualMedia/SOL）、Manager 重置与日志清理（`reset_manager()` /
    `clear_manager_log()`）、SecureBoot/NetworkInterface/MemoryDomain/MemoryMetrics、
    固件上传与 BMC 更新（`simple_update()` vendor 路由 + `VendorDetector`）、
    Telemetry/Composition 全套、`collect_and_download_diagnostic_data()` 一键日志
    采集下载、`UpdateStrategyRegistry` 厂商更新策略框架。
  - 完整接口变更见 [`docs/redfish_python_sdk_api.md`](docs/redfish_python_sdk_api.md)。

### 验证

- 全部改动文件 `py_compile` + JSON 校验通过；
- 关键逻辑 mock 自测：sel_log_helper 12 例、redfish_event_compat 14 例、
  systems_005 UNSUPPORTED 判定 8 例、update 参数优先级 6 例、
  用户名/密码规则静态校验全量——全部通过；
- 三项规范复查通过：无新增硬编码 URL、无绕过 SDK 的调用、无厂商名暴露
  （延续去厂商化惯例）。

## [1.0.0] — 2026-09-03

首个纳入 Git Tag 版本管控的基线版本。

### 依赖
- 将 `redfish-python-sdk` 锁定至 **v1.2.0**（PyPI 最新发布版本，2026-08-05）。
- SDK 演进路径：
  - **v1.0.0**（2026-07-21）：首个正式发布版本。
  - **v1.1.0**（2026-08-04）：新增 `#LogService.ClearLog`、现代 BootOptions、`#Drive.Reset` / IndicatorLED 写、
    进风口历史温度、`#EventService.SubmitTestEvent` 等类型化接口，并引入 `models/check.py` 声明式校验引擎；
    同批还新增 `subscribe()` 的 `http_headers` 等扩展参数、`get_subscription()`、日志路径动态发现等增强。
  - **v1.2.0**（2026-08-05）：完善 OEM 项目支持（新增 10 个 OEM Service 模型与 12 个对应 `Client` 方法，
    如 `get_ntp_service()` / `get_syslog_service()` / `get_snmp_service()` / `get_vnc_service()` 等）。
  - 完整接口变更见 [`docs/redfish_python_sdk_api.md`](docs/redfish_python_sdk_api.md)。

### Changed — 脚本迁移至 SDK 类型化接口
将原用 `client.get_raw()` + `[SDK-GAP]` 占位的脚本改写为类型化接口：
- `chassis_006a_uid_led_positive`：`set_indicator_led()` + `get_chassis().indicator_led`
- `chassis_007a_nvme_led_positive`：`set_drive_indicator_led()` + `get_drive()`（protocol/media_type/indicator_led 模型字段）
- `chassis_007b_nvme_led_negative`：读取改 `get_drive()`；**反向写非法值刻意保留 `client.patch()` 直达 BMC**，确保真正验证 BMC 服务端拒绝能力（避免 SDK 本地校验造成假 PASS）
- `chassis_011_nvme_power_test`：`get_drive()` + `drive_reset()`（`drive.actions` 按弱类型 dict 解析）
- `chassis_012_history_temp_test`：改用 `get_inlet_history_temperature()`；**测试目标由标准 ThermalSubsystem 调整为厂商扩展 InletHistoryTemperature 路径**（SDK 适配各厂商）
- `event_001_get_service`：`get_event_service()`（字段检查映射到模型属性）
- `event_009_submit_test_event`：`get_event_service()` + `submit_test_event()`
- `systems_003b_physical_drives_check`：`get_drive(odata_id)`（取代 get_raw + model_validate）
- `systems_004_boot_options_test`：新模型改用 `get_boot_options()` / `set_boot_option_enabled()`（旧 BootSourceOverride 模型保持不变）
- `systems_010a_sel_log_clear_positive`：Systems 侧 `get_system_log_service()` + `clear_system_log()`（Managers 侧 SDK 无封装，保留 get_raw + post）
- `managers_003_ethernet_interfaces_check`：由 `get_raw` 占位改用 `get_manager_ethernet_interfaces()` 类型化接口（保留数量/MAC/Enabled/IPv4/Speed/Status 六项检查）；**去除 `_` 前缀恢复执行**，加入 `bmc_runner_suites.json` managers 套件；原 EthernetInterface `NameServers=null` pydantic 解析 bug 随 SDK v1.1.0 修复（若仍解析失败则如实记 FAIL，不再静默绕过）。

### Changed — Event 脚本优化
- `event_003_create_subscription.py`：将 ZTE 降级代码（BmcHttpClient 手动 POST，约 40 行）替换为 SDK `subscribe(..., http_headers={...})`，大幅简化代码。
- `event_006_delete_subscription.py`：同上，简化前置 subscribe 的 ZTE 降级代码。
- `event_004_get_subscription.py`：改用新增的 `get_subscription()` 方法直接查询单个订阅，替代从集合取第一个的方式；移除过时注释"SDK 无 get_subscription"。

### Changed — Managers 日志脚本优化
- `managers_004a_sel_log_check.py`：消除硬编码 `entries_url`，改用 SDK `get_manager_log_entries()` 动态获取 Entries 集合，移除 [SDK-GAP] 标记。
- `managers_004b_operatelog_check.py`：同上。
- `managers_004c_auditlog_check.py`：同上。

### Added — 接口测试覆盖补充
- `systems_004_boot_options_test`：新模型切换后改用 `get_boot_option(id)` 独立 GET 回读验证（覆盖单资源接口，较依赖写接口返回值更严格）。
- `systems_007_sel_log_view`：新增单 LogService 资源验证，用 `get_system_log_service(id)` 探测 `#LogService.ClearLog` Action 可发现性（只读；Action 缺失记 WARNING，仅获取失败计 FAIL；Managers 侧跳过）。
- 接口覆盖核查：核对 `docs/redfish_python_sdk_api.md` 接口在脚本中的调用情况，补齐 `get_boot_option` / `get_system_log_service` / `get_manager_ethernet_interfaces` 覆盖。`get_host_interfaces` 经调研为 BMC↔主机带内管理通道（多数 BMC 不暴露），暂不纳入。

### Added — 诊断增强
- 新增 HTTP 请求 DEBUG 日志开关 `BMC_HTTP_DEBUG`（`func/bmc_diag.py`）：设为 `1` 时控制台实时打印每次接口调用的 URL 与请求 body（GET=DEBUG URL、POST/PATCH=INFO URL+payload、失败=ERROR 响应体），便于 FAIL 定位；默认关闭，请求细节始终写入 `log/bmc/<用例>/<用例>.log`。

### Added — 版本管控
- `requirements.txt`：以版本号锁定 SDK 依赖，确保可重复构建。
- `bmc/__init__.py`：定义项目版本号 `__version__` 与适配的 SDK 版本 `__sdk_version__`。
- 新增本 `CHANGELOG.md`。

### Fixed
- 修正 `README.md` managers 表命名错位：实际 `managers_002` 为网络协议检查、`managers_003` 为以太网接口检查（原表头脚本名与功能错位）。

### Docs
- `docs/redfish_python_sdk_api.md`：补充 v1.1.0 / v1.1.1 接口文档（`subscribe()` 扩展、`get_subscription()`、`LogEntry` 新字段、`Subscription` 模型变更、声明式校验引擎等）。
- `README.md`：更新 SDK 版本引用为当前锁定的 v1.2.0；更新 event 脚本的 SDK 接入度描述；从「SDK 已知局限」表移除已解决项（仅余 `systems_014` KVM 等 OEM 扩展项）。

### Notes
- ⚠️ **破坏性变更提醒（SDK v1.0.x 起）**：`PowerSupply.line_input_voltage` 类型由 `int` → `float`（对齐 DMTF schema，BMC 可能返回 `220.5` 等小数）。经核查 `chassis_004_power_supplies_check` 未使用该字段、数值判断已兼容 float，无需改动；其余使用该字段的脚本需确认不存在整数类型假设。
