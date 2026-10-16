#!/bin/python
"""
Author: Fengmian
Date: 2026/05/11
Usage: python3 bmc/managers_024_snmp_trap_test.py -i <bmc_ip> -u <username> -p <password>
Update:
2026/05/11: 新增，BMC SNMP Trap 测试告警触发测试
2026/10/16: SDK 1.3.0 适配 - 改用 get_snmp_service() 类型化接口，URI 由 SDK 自动发现（issue/8）

测试内容：
  1. 查询 SNMP 服务配置，获取 TrapServer 列表
  2. 若存在已配置的 TrapServer，对 MemberId=1 发送 SubmitTestEvent 测试告警
  3. 若无 TrapServer，记录 WARNING 并跳过（仅只读校验，仍 PASS）
  4. 验证 POST 返回成功（2xx），无需验证告警实际送达（无接收端）

PASS 标准：
  - SNMP 服务查询成功，结构字段完整
  - 若有 TrapServer 配置：POST SubmitTestEvent 返回成功
  - 若无 TrapServer：记录 WARNING，查询校验通过即 PASS

注意：
  被测固件 SNMP PATCH 接口存在 ComplexPwdEnable 格式校验 bug（返回 400），
  本脚本仅测只读查询 + Trap 触发，不做 PATCH 操作。
"""

import os
import sys
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from func.common_function import CommonFunction
from func.bmc_test_base import BmcTestBase

from redfish_sdk import RedfishClient, RedfishException


class Managers024SnmpTrapTest(BmcTestBase):
    """BMC SNMP Trap 测试告警触发测试"""

    def __init__(self, case: str):
        super().__init__(
            case=case,
            config_path=os.path.join(os.getcwd(), "conf/bmc/managers/managers_024_snmp_trap_test.json"),
        )
        self.command_check_result = "FAIL"
    def run_test(self):
        test = CommonFunction()
        test.print_log("INFO", f"测试用例名称：{self.TEST_NAME}，编号：{self.TEST_NUM}")
        test.print_log("INFO", "测试开始")

        checks = []
        detail = {}
        final  = "FAIL"

        try:
            self.client = RedfishClient(
                host=self.BMC_IP, username=self.USERNAME, password=self.PASSWORD
            )

            # ── 1. 查询 SNMP 服务配置（SDK 1.3.0 类型化接口，URI 由 SDK 自动发现）──
            snmp_data = self.client.get_snmp_service()
            # SnmpServiceEnable/SnmpServicePort 为 OEM 扩展字段，经 extra 保留可属性访问
            svc_enabled  = getattr(snmp_data, "SnmpServiceEnable", None)
            svc_port     = getattr(snmp_data, "SnmpServicePort", None)
            trap_notify  = snmp_data.snmp_trap_notification
            trap_enabled = getattr(trap_notify, "snmpTrapEnable", None) if trap_notify else None
            trap_servers = (trap_notify.trap_server if trap_notify else None) or []
            trap_version = trap_notify.trap_version if trap_notify else None

            test.print_log("INFO",
                f"SNMP 配置：ServiceEnabled={svc_enabled}, Port={svc_port}, "
                f"TrapEnabled={trap_enabled}, TrapVersion={trap_version}, "
                f"TrapServers 数量={len(trap_servers) if isinstance(trap_servers, list) else 'N/A'}")

            detail["initial"] = {
                "SnmpServiceEnable": svc_enabled,
                "SnmpServicePort":   svc_port,
                "TrapEnabled":       trap_enabled,
                "TrapVersion":       trap_version,
                "TrapServerCount":   len(trap_servers) if isinstance(trap_servers, list) else 0,
            }

            checks.append(("SNMP 服务查询成功", True))
            checks.append(("SnmpServiceEnable 字段存在", svc_enabled is not None))
            checks.append(("SnmpTrapNotification 结构存在", trap_notify is not None))

            # ── 2. 触发 Trap 测试告警 ─────────────────────────────────────
            # TrapServerAddress 为 OEM 字段（SDK TrapServer 模型为 Destination），经 extra 保留
            active_servers = []
            if isinstance(trap_servers, list):
                active_servers = [
                    s for s in trap_servers
                    if getattr(s, "TrapServerAddress", "") or (s.destination or "")
                ]

            if not active_servers:
                test.print_log("WARNING",
                    "未配置 TrapServer 地址，跳过 SubmitTestEvent（无接收端）")
                detail["trap_test"] = {"skipped": True, "reason": "no_trap_server_configured"}
            else:
                # 对第一个有效 TrapServer 触发测试
                # SubmitTestEvent action SDK 未封装，target 从资源 Actions 元数据动态获取
                first = active_servers[0]
                member_id = getattr(first, "MemberId", None) or first.id or "1"
                actions = getattr(snmp_data, "Actions", None) or {}
                submit_action = actions.get("#SnmpService.SubmitTestEvent", {})
                submit_target = submit_action.get("target", "") if isinstance(submit_action, dict) else ""
                if not submit_target:
                    raise RedfishException("SnmpService 响应中无 #SnmpService.SubmitTestEvent target")
                test.print_log("INFO",
                    f"对 MemberId={member_id} 发送 SNMP Trap 测试告警...")
                try:
                    self.client.post(submit_target, {"MemberId": str(member_id)})
                    test.print_log("INFO", "SNMP SubmitTestEvent POST 成功")
                    checks.append(("SNMP Trap 测试告警触发成功", True))
                    detail["trap_test"] = {"member_id": member_id, "result": "PASS"}
                except RedfishException as e:
                    test.print_log("ERROR", f"SNMP SubmitTestEvent POST 失败：{e}")
                    checks.append(("SNMP Trap 测试告警触发成功", False))
                    detail["trap_test"] = {"member_id": member_id, "result": "FAIL", "error": str(e)}

        except RedfishException as e:
            test.print_log("ERROR", f"Redfish 异常：{e}")
        except Exception as e:
            test.print_log("ERROR", f"异常：{e}")
            traceback.print_exc()
        finally:
            try:
                self.client.close()
            except Exception:
                pass

        final = "PASS" if checks and all(r for _, r in checks) else "FAIL"
        for label, ok in checks:
            test.print_log("INFO" if ok else "ERROR", f"{'✓' if ok else '✗'} {label}")
        test.print_log("INFO" if final == "PASS" else "ERROR", f"测试结束，结果：{final}")

        detail["checks"] = [{"label": l, "result": "PASS" if r else "FAIL"} for l, r in checks]
        test.add_key_value_to_json(self.result_json_path, "detail.cycle", value=detail)
        test.add_key_value_to_json(self.result_json_path, "summary",
                                   value={"metrics": self.TEST_NAME, "value": final})
        with open(self.result_csv_path, "a", encoding="utf-8") as f:
            f.write(f"{self.TEST_NUM},{final}\n")
        self.command_check_result = final

if __name__ == "__main__":
    exit_code = 0
    obj = None
    try:
        obj = Managers024SnmpTrapTest("Managers024SnmpTrapTest")
        obj.run_test()
        exit_code = 0 if obj.command_check_result == "PASS" else 2
    except KeyboardInterrupt:
        exit_code = 130
    except Exception as e:
        CommonFunction.print_log("ERROR", f"异常：{e}")
        traceback.print_exc()
        exit_code = 1
    finally:
        if obj and hasattr(obj, "exit_code_path"):
            with open(obj.exit_code_path, "w", encoding="utf-8") as f:
                f.write(str(exit_code))
    sys.exit(exit_code)
