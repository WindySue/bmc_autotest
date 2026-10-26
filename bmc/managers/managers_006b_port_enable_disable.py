#!/bin/python
"""
Author: Fengmian
Date: 2026/05/08
Usage: python3 bmc/managers_006b_port_enable_disable.py -i <bmc_ip> -u <username> -p <password>
Update:
2026/05/08: 新增，BMC 端口使能/禁用功能测试，在 managers_006 查询基础上补充设置能力验证
2026/05/08: 修复 - 移除 HTTP 测试项，禁用 HTTP 会导致 BMC Web 服务整体短暂重启（含 HTTPS），
           影响后续请求稳定性；改为只测 HTTPS/SSH/SNMP
2026/10/16: SDK 1.3.0 适配 - PATCH URI 改取自 NetworkProtocol 资源 @odata.id（issue/8）
2026/10/23: 修复真机验证反馈 - 业务侧明确不使用 HTTP，继续保留 HTTP 只读查询项
           没有意义，反而给 BMC 研发增加无谓的排查/修复工作量；移除 HTTP 检查项，
           只保留 HTTPS 只读查询。
"""

import os
import sys
import time
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from func.common_function import CommonFunction
from func.bmc_test_base import BmcTestBase

from redfish_sdk import RedfishClient, RedfishException

# 可测试的协议列表（协议名, 对应 JSON key, 默认端口）
# 注意：HTTPS 不在写测试列表 —— SDK 全程走 HTTPS，禁用 HTTPS 等同于切断自己的连接
# 只做读取验证；SSH/SNMP 可安全禁用/启用，不影响 Redfish 连接
TESTABLE_PROTOCOLS = [
    ("SSH", "SSH", 22),
    ("SNMP", "SNMP", 161),
]

# 只读验证的协议（仅查询 ProtocolEnabled 状态，不做写操作）
# 业务侧明确不使用 HTTP，故不再纳入检查范围，仅保留 HTTPS
READONLY_PROTOCOLS = [
    ("HTTPS", "HTTPS", 443),
]

class Managers006bPortEnableDisable(BmcTestBase):
    """BMC 端口使能/禁用功能测试

    用例编号：Redfish_Managers_006b
    测试内容：
    - 查询各协议当前状态
    - 逐个协议：禁用 → 验证 → 启用 → 验证
    - 恢复原始状态
    """

    def __init__(self, case: str):
        super().__init__(
            case=case,
            config_path=os.path.join(os.getcwd(), "conf/bmc/managers/managers_006b_port_enable_disable.json"),
        )

    def run_test(self):
        test = CommonFunction()
        test.print_log("INFO", f"测试用例名称：{self.TEST_NAME}，编号：{self.TEST_NUM}")
        test.print_log("INFO", "测试开始")

        checks = []
        port_info = {}
        try:
            self.client = RedfishClient(
                host=self.BMC_IP,
                username=self.USERNAME,
                password=self.PASSWORD
            )

            # 1. 查询当前网络协议配置（SDK get_network_protocol()）
            np = self.client.get_network_protocol()
            np_uri = np.odata_id
            test.print_log("INFO", "当前网络协议配置已获取")
            checks.append(("查询 NetworkProtocol 成功", True))

            # proto_key → SDK 属性名映射
            _sdk_attr = {"HTTPS": "https", "SSH": "ssh", "SNMP": "snmp"}

            # 1b. HTTPS 只读验证（禁用会断开 Redfish 连接，只做状态查询；HTTP 业务不使用，不再检查）
            for proto_name, proto_key, _ in READONLY_PROTOCOLS:
                proto_obj = getattr(np, _sdk_attr[proto_key], None)
                enabled = getattr(proto_obj, "protocol_enabled", None) if proto_obj else None
                port    = getattr(proto_obj, "port", None) if proto_obj else None
                test.print_log("INFO", f"  {proto_name}（只读）: ProtocolEnabled={enabled}, Port={port}")
                test.print_log("WARNING", f"  {proto_name} 禁用/启用测试跳过 - 禁用该协议会断开 Redfish 连接，无法通过 Redfish 自身验证")
                checks.append((f"{proto_name} 状态查询成功", enabled is not None))
                port_info[proto_name] = {"read_only": True, "ProtocolEnabled": enabled, "Port": port}

            # 2. 可写协议（SSH/SNMP）逐个进行 禁用→验证→启用→验证
            for proto_name, proto_key, default_port in TESTABLE_PROTOCOLS:
                proto_obj      = getattr(np, _sdk_attr[proto_key], None)
                original_enabled = getattr(proto_obj, "protocol_enabled", True) if proto_obj else True
                original_port    = getattr(proto_obj, "port", default_port) if proto_obj else default_port
                test.print_log("INFO", f"  {proto_name}: 原始状态 ProtocolEnabled={original_enabled}, Port={original_port}")

                # 2a. 禁用协议
                test.print_log("INFO", f"  禁用 {proto_name}...")
                patch_body = {proto_key: {"ProtocolEnabled": False}}
                try:
                    self.client.patch(np_uri, patch_body)
                    time.sleep(2)
                    checks.append((f"{proto_name} 禁用 PATCH 成功", True))
                except RedfishException as e:
                    test.print_log("ERROR", f"  {proto_name} 禁用失败: {str(e)}")
                    checks.append((f"{proto_name} 禁用 PATCH 成功", False))
                    continue

                # 2b. 验证已禁用（可能需要等待 BMC 重启）
                np = self.client.get_network_protocol()
                proto_obj = getattr(np, _sdk_attr[proto_key], None)
                disabled  = getattr(proto_obj, "protocol_enabled", None) if proto_obj else None
                test.print_log("INFO", f"  验证 {proto_name} 禁用: ProtocolEnabled={disabled}")
                checks.append((f"{proto_name} ProtocolEnabled=False 验证", disabled is False))

                # 2c. 重新启用
                test.print_log("INFO", f"  重新启用 {proto_name}...")
                patch_body = {proto_key: {"ProtocolEnabled": True}}
                try:
                    self.client.patch(np_uri, patch_body)
                    time.sleep(2)
                    checks.append((f"{proto_name} 启用 PATCH 成功", True))
                except RedfishException as e:
                    test.print_log("ERROR", f"  {proto_name} 启用失败: {str(e)}")
                    checks.append((f"{proto_name} 启用 PATCH 成功", False))
                    continue

                # 2d. 验证已启用
                np = self.client.get_network_protocol()
                proto_obj = getattr(np, _sdk_attr[proto_key], None)
                enabled   = getattr(proto_obj, "protocol_enabled", None) if proto_obj else None
                test.print_log("INFO", f"  验证 {proto_name} 启用: ProtocolEnabled={enabled}")
                checks.append((f"{proto_name} ProtocolEnabled=True 验证", enabled is True))

                port_info[proto_name] = {
                    "original_enabled": original_enabled,
                    "original_port": original_port,
                }

            final = "PASS" if all(r for _, r in checks) else "FAIL"

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

        for label, passed in checks:
            test.add_key_value_to_json(self.result_json_path, "detail.cycle",
                                       value={"metrics": label, "value": "PASS" if passed else "FAIL"})
        test.add_key_value_to_json(self.result_json_path, "detail.cycle",
                                   value={"metrics": "port_original_state", "value": port_info})

        self.command_check_result = final
        test.add_key_value_to_json(self.result_json_path, "summary",
                                   value={"metrics": self.TEST_NUM, "value": final})
        with open(self.result_csv_path, "a") as f:
            f.write(f"{self.TEST_NUM},{final}\n")
        test.print_log("INFO", f"测试完成，结果：{final}")

if __name__ == '__main__':
    exit_code = 0
    test_name = None
    try:
        test_name = Managers006bPortEnableDisable("Managers006bPortEnableDisable")
        test_name.run_test()
        if test_name.command_check_result in ["FINISH", "PASS"]:
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
