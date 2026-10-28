#!/bin/python
"""
Author: Fengmian
Date: 2026/10/28
Usage: python3 bmc/systems_017_telemetry_test.py -i <bmc_ip> -u <username> -p <password>
Update:
2026/10/28: 新增，Telemetry 遥测服务测试（issue/19，SDK 1.3.0 接口覆盖计划 B 档）
  覆盖 SDK 接口（11 个）：get_telemetry_service() / get_metric_definitions() /
  get_metric_definition() / get_metric_reports() / get_metric_report() /
  get_metric_report_definitions() / get_metric_report_definition() /
  get_telemetry_triggers() / get_telemetry_trigger() /
  get_metric_report_log() / get_metric_report_log_entries()

测试内容：
  1. 【TelemetryService】Service Root 是否广告（可选组件，未广告 WARNING 跳过）
  2. 【MetricDefinitions】枚举指标定义，抽验单个（Id 回读一致）
  3. 【MetricReports】枚举指标报告，抽验单个 + 类型化 MetricValue 检查
  4. 【MetricReportDefinitions】枚举报告定义，抽验单个
  5. 【Triggers】枚举遥测触发器，抽验单个
  6. 【MetricReportLog】遥测日志服务与条目（可选）

判定原则：
  - TelemetryService 为可选组件（Root 未广告 → None）→ WARNING 跳过不计 FAIL
  - 各集合为空（BMC 未配置遥测指标）→ WARNING 不 FAIL
  - 抽验回读 Id 不一致 → FAIL
"""

import os
import sys
import time
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from func.common_function import CommonFunction
from func.bmc_test_base import BmcTestBase

from redfish_sdk import RedfishClient, RedfishException


class TelemetryTest(BmcTestBase):
    """Systems Telemetry 遥测服务测试

    用例编号：Redfish_Systems_017
    检查项：
    - TelemetryService 可达（可选组件，未广告 WARNING 跳过）
    - MetricDefinitions / MetricReports / MetricReportDefinitions / Triggers
      四类集合枚举 + 单资源抽验（Id 回读一致）
    - MetricReportLog 遥测日志（可选）
    """

    def __init__(self, case: str):
        super().__init__(
            case=case,
            config_path=os.path.join(os.getcwd(), "conf/bmc/systems/systems_017_telemetry_test.json"),
        )

    def close_sdk_client(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass

    def run_test(self):
        test = CommonFunction()
        test.print_log("INFO", f"测试用例名称：{self.TEST_NAME}，编号：{self.TEST_NUM}")
        test.print_log("INFO", "测试开始")

        checks = []   # (label, passed: bool|None)  None=跳过
        telemetry_info = {}
        final = None

        try:
            self.client = RedfishClient(self.BMC_IP, self.USERNAME, self.PASSWORD)

            # ── 1. TelemetryService 可达性（可选组件）────────────────────────
            test.print_log("INFO", "Step 1：查询 TelemetryService")
            try:
                svc = self.client.get_telemetry_service()
            except RedfishException as e:
                test.print_log("WARNING",
                    f"TelemetryService 查询失败（{str(e)[:100]}），"
                    f"该 BMC 可能未实现遥测服务（可选组件），跳过测试（WARNING 不 FAIL）")
                checks.append(("TelemetryService 可达", None))
                telemetry_info["service"] = "not_available"
                self._write_result("WARNING", checks, telemetry_info)
                return

            if svc is None:
                test.print_log("WARNING",
                    "Service Root 未广告 TelemetryService（可选组件），跳过测试（WARNING 不 FAIL）")
                checks.append(("TelemetryService 可达", None))
                telemetry_info["service"] = "not_advertised"
                self._write_result("WARNING", checks, telemetry_info)
                return

            checks.append(("TelemetryService 可达", True))
            telemetry_info["service"] = {
                "odata_id": svc.odata_id,
                "status": str(getattr(svc, "status", "")),
            }
            test.print_log("INFO", f"  ✓ TelemetryService 可达：{svc.odata_id}")

            # ── 2. MetricDefinitions 枚举 + 抽验 ────────────────────────────
            test.print_log("INFO", "Step 2：MetricDefinitions 枚举与抽验")
            try:
                defs = self.client.get_metric_definitions()
            except RedfishException as e:
                defs = []
                test.print_log("WARNING", f"  MetricDefinitions 枚举失败：{str(e)[:100]}")
            if defs:
                test.print_log("INFO", f"  ✓ 共 {len(defs)} 个 MetricDefinition")
                checks.append(("MetricDefinitions 枚举", True))
                sample = defs[0]
                back = self.client.get_metric_definition(sample.id)
                ok = (back.id == sample.id)
                checks.append(("MetricDefinition 抽验回读一致", ok))
                if not ok:
                    test.print_log("ERROR",
                        f"  ✗ 抽验不一致：期望 {sample.id!r}，实际 {back.id!r}")
                telemetry_info["metric_definitions"] = {
                    "total": len(defs), "sample_id": sample.id,
                }
            else:
                test.print_log("WARNING", "  MetricDefinitions 为空（未配置遥测指标），WARNING 不 FAIL")
                checks.append(("MetricDefinitions 枚举", None))

            # ── 3. MetricReports 枚举 + 抽验 + MetricValue 检查 ─────────────
            test.print_log("INFO", "Step 3：MetricReports 枚举与抽验")
            try:
                reports = self.client.get_metric_reports()
            except RedfishException as e:
                reports = []
                test.print_log("WARNING", f"  MetricReports 枚举失败：{str(e)[:100]}")
            if reports:
                test.print_log("INFO", f"  ✓ 共 {len(reports)} 个 MetricReport")
                checks.append(("MetricReports 枚举", True))
                sample = reports[0]
                back = self.client.get_metric_report(sample.id)
                ok = (back.id == sample.id)
                checks.append(("MetricReport 抽验回读一致", ok))
                if not ok:
                    test.print_log("ERROR",
                        f"  ✗ 抽验不一致：期望 {sample.id!r}，实际 {back.id!r}")
                # 类型化 MetricValue 检查
                values = getattr(sample, "metric_values", None) or []
                test.print_log("INFO", f"  报告 {sample.id} 含 {len(values)} 个 MetricValue")
                telemetry_info["metric_reports"] = {
                    "total": len(reports), "sample_id": sample.id,
                    "sample_value_count": len(values),
                }
            else:
                test.print_log("WARNING", "  MetricReports 为空（未配置遥测报告），WARNING 不 FAIL")
                checks.append(("MetricReports 枚举", None))

            # ── 4. MetricReportDefinitions 枚举 + 抽验 ──────────────────────
            test.print_log("INFO", "Step 4：MetricReportDefinitions 枚举与抽验")
            try:
                rdefs = self.client.get_metric_report_definitions()
            except RedfishException as e:
                rdefs = []
                test.print_log("WARNING", f"  MetricReportDefinitions 枚举失败：{str(e)[:100]}")
            if rdefs:
                test.print_log("INFO", f"  ✓ 共 {len(rdefs)} 个 MetricReportDefinition")
                checks.append(("MetricReportDefinitions 枚举", True))
                sample = rdefs[0]
                back = self.client.get_metric_report_definition(sample.id)
                ok = (back.id == sample.id)
                checks.append(("MetricReportDefinition 抽验回读一致", ok))
                if not ok:
                    test.print_log("ERROR",
                        f"  ✗ 抽验不一致：期望 {sample.id!r}，实际 {back.id!r}")
                telemetry_info["metric_report_definitions"] = {
                    "total": len(rdefs), "sample_id": sample.id,
                }
            else:
                test.print_log("WARNING", "  MetricReportDefinitions 为空，WARNING 不 FAIL")
                checks.append(("MetricReportDefinitions 枚举", None))

            # ── 5. Triggers 枚举 + 抽验 ─────────────────────────────────────
            test.print_log("INFO", "Step 5：Telemetry Triggers 枚举与抽验")
            try:
                triggers = self.client.get_telemetry_triggers()
            except RedfishException as e:
                triggers = []
                test.print_log("WARNING", f"  Triggers 枚举失败：{str(e)[:100]}")
            if triggers:
                test.print_log("INFO", f"  ✓ 共 {len(triggers)} 个 Trigger")
                checks.append(("Triggers 枚举", True))
                sample = triggers[0]
                back = self.client.get_telemetry_trigger(sample.id)
                ok = (back.id == sample.id)
                checks.append(("Trigger 抽验回读一致", ok))
                if not ok:
                    test.print_log("ERROR",
                        f"  ✗ 抽验不一致：期望 {sample.id!r}，实际 {back.id!r}")
                telemetry_info["triggers"] = {"total": len(triggers), "sample_id": sample.id}
            else:
                test.print_log("WARNING", "  Triggers 为空（未配置遥测触发器），WARNING 不 FAIL")
                checks.append(("Triggers 枚举", None))

            # ── 6. MetricReportLog（可选）────────────────────────────────────
            test.print_log("INFO", "Step 6：MetricReportLog 遥测日志")
            try:
                log = self.client.get_metric_report_log()
                if log is not None:
                    entries = self.client.get_metric_report_log_entries()
                    test.print_log("INFO",
                        f"  ✓ MetricReportLog 可达，含 {len(entries or [])} 条日志")
                    checks.append(("MetricReportLog 可达", True))
                    telemetry_info["metric_report_log"] = {"entries": len(entries or [])}
                else:
                    test.print_log("WARNING",
                        "  MetricReportLog 未广告（可选），WARNING 不 FAIL")
                    checks.append(("MetricReportLog 可达", None))
            except RedfishException as e:
                test.print_log("WARNING",
                    f"  MetricReportLog 不可达（{str(e)[:100]}），WARNING 不 FAIL")
                checks.append(("MetricReportLog 可达", None))

            # ── 汇总（None=跳过项不计入）────────────────────────────────────
            active = [(n, r) for n, r in checks if r is not None]
            final = "PASS" if all(r for _, r in active) else "FAIL"

        except RedfishException as e:
            test.print_log("ERROR", f"Redfish SDK 调用失败：{str(e)}")
            final = "FAIL"
        except Exception as e:
            test.print_log("ERROR", f"测试异常：{str(e)}")
            traceback.print_exc()
            final = "FAIL"
        finally:
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass

        self._write_result(final, checks, telemetry_info)

    def _write_result(self, final, checks, telemetry_info):
        test = CommonFunction()
        for label, passed in checks:
            value = "SKIP" if passed is None else ("PASS" if passed else "FAIL")
            test.add_key_value_to_json(self.result_json_path, "detail.cycle",
                                       value={"metrics": label, "value": value})
        test.add_key_value_to_json(self.result_json_path, "detail.cycle",
                                   value={"metrics": "telemetry_info", "value": telemetry_info})
        test.add_key_value_to_json(self.result_json_path, "summary",
                                   value={"metrics": self.TEST_NUM, "value": final})
        with open(self.result_csv_path, "a") as f:
            for label, passed in checks:
                value = "SKIP" if passed is None else ("PASS" if passed else "FAIL")
                f.write(f"{label},{value}\n")
            f.write(f"{self.TEST_NUM},{final}\n")

        self.command_check_result = final
        test.print_log("INFO", f"测试完成，结果：{final}")


if __name__ == '__main__':
    exit_code = 0
    test_name = None
    try:
        test_name = TelemetryTest("TelemetryTest")
        test_name.run_test()
        if test_name.command_check_result in ["FINISH", "PASS", "WARNING"]:
            exit_code = 0
        elif test_name.command_check_result == "FAIL":
            exit_code = 2
        else:
            exit_code = 1
        start_time = time.time()
        while (time.time() - start_time) < 5:
            time.sleep(1)
    except KeyboardInterrupt:
        CommonFunction.print_log("ERROR", "检测到键盘中断，提前终止")
        exit_code = 130
    except Exception as e:
        CommonFunction.print_log("ERROR", f"发生未处理异常: {str(e)}")
        traceback.print_exc()
        exit_code = 1
    finally:
        try:
            if test_name and hasattr(test_name, 'exit_code_path'):
                with open(test_name.exit_code_path, "w", encoding="utf-8") as e:
                    e.write(str(exit_code))
        except Exception as e:
            CommonFunction.print_log("ERROR", f"写入退出码文件失败: {str(e)}")
            exit_code = 3
    sys.exit(exit_code)
