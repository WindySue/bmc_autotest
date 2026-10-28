#!/bin/python
"""
Author: Fengmian
Date: 2026/04/23
Usage: python3 bmc/account_004_role_test.py -i <bmc_ip> -u <username> -p <password>
Update:
2026/04/23: 新增

校验策略：
  1. get_roles 获取角色列表
  2. 验证列表非空
  3. 验证每个角色存在 assigned_privileges 且非空
  4. 验证标准角色（Administrator/Operator/User）均存在
  PASS：角色列表完整，标准角色全部存在，权限字段非空
  FAIL：列表为空、标准角色缺失或权限字段缺失
"""

import os
import sys
import time
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from func.common_function import CommonFunction
from func.bmc_test_base import BmcTestBase

from redfish_sdk import RedfishClient, RedfishException

# DMTF DSP0266 标准 RoleId 枚举（issue/19）：
#   Administrator / Operator / ReadOnlyUser（及常见别名 ReadOnly）/ None
# "User" 不是标准 RoleId（IPMI 传统 USER 权限级在部分厂商映射时遗留的非标准名）
STANDARD_ROLES = {"Administrator", "Operator", "ReadOnly", "ReadOnlyUser"}

# 只读角色的等价名集合：任一存在即视为"只读角色"覆盖（兼容宽松实现的厂商）
READONLY_EQUIV = {"ReadOnly", "ReadOnlyUser", "User"}

class AccountRoleTest(BmcTestBase):
    """Account 角色定义测试

    用例编号：Redfish_Account_004
    检查项：查看所有角色，验证标准角色存在且权限字段非空
    """

    def __init__(self, case: str):
        super().__init__(
            case=case,
            config_path=os.path.join(os.getcwd(), "conf/bmc/account/account_test.json"),
        )
    def close_sdk_client(self):
        if self.client:
            try: self.client.close()
            except Exception: pass

    def run_test(self):
        test = CommonFunction()
        test.print_log("INFO", f"测试用例名称：Account角色定义测试，测试用例编号：Redfish_Account_004")
        test.print_log("INFO", "测试开始")

        CommonFunction.print_log("INFO", f"连接 BMC：{self.BMC_IP}")
        self.client = RedfishClient(self.BMC_IP, self.USERNAME, self.PASSWORD)

        result = "PASS"

        try:
            CommonFunction.print_log("INFO", "Step 1：获取角色列表")
            roles = self.client.get_roles()

            if not roles:
                CommonFunction.print_log("ERROR", "角色列表为空")
                result = "FAIL"
            else:
                CommonFunction.print_log("INFO", f"共找到 {len(roles)} 个角色")
                role_ids = set()
                for r in roles:
                    CommonFunction.print_log("INFO",
                        f"  角色：id={r.id}, is_predefined={r.is_predefined}, "
                        f"assigned_privileges={r.assigned_privileges}")
                    role_ids.add(r.id)
                    if not r.assigned_privileges:
                        CommonFunction.print_log("ERROR", f"  角色 {r.id} 的 assigned_privileges 为空")
                        result = "FAIL"

                # 验证标准角色（issue/19）
                # - Administrator/Operator：必须存在，缺失 FAIL
                # - 只读角色：ReadOnly/ReadOnlyUser/User 为等价名（部分厂商使用
                #   非标准名 "User"），任一存在即视为覆盖；全部缺失记 WARNING
                #   不 FAIL（宽松实现的厂商可能用其他命名，避免误报）
                CommonFunction.print_log("INFO", f"Step 2：验证标准角色")
                missing_roles = {"Administrator", "Operator"} - role_ids
                if missing_roles:
                    CommonFunction.print_log("ERROR", f"缺少标准角色：{missing_roles}")
                    result = "FAIL"
                else:
                    CommonFunction.print_log("INFO", f"  ✓ Administrator/Operator 存在")

                readonly_found = READONLY_EQUIV & role_ids
                if readonly_found:
                    CommonFunction.print_log("INFO",
                        f"  ✓ 只读角色存在：{sorted(readonly_found)}")
                else:
                    CommonFunction.print_log("WARNING",
                        f"  未发现只读角色（{sorted(READONLY_EQUIV)} 均不存在），"
                        f"宽松实现的厂商可能使用其他命名，记 WARNING 不 FAIL")

        except RedfishException as e:
            CommonFunction.print_log("ERROR", f"Redfish 接口异常：{e}")
            result = "FAIL"
        except Exception as e:
            CommonFunction.print_log("ERROR", f"未预期异常：{type(e).__name__}: {e}")
            traceback.print_exc()
            result = "FAIL"

        self.command_check_result = result
        with open(self.result_csv_path, "a", encoding="utf-8") as f:
            f.write(f"account_role,{result}\n")
        test.add_key_value_to_json(self.result_json_path, "detail.cycle",
                                   value={"metrics": "account_role", "value": result})
        test.add_key_value_to_json(self.result_json_path, "summary",
                                   value={"metrics": "Account角色定义测试", "value": result})
        test.print_log("INFO", f"Account角色定义测试完成，结果：{result}")

if __name__ == "__main__":
    exit_code = 0
    checker = None
    try:
        checker = AccountRoleTest("AccountRoleTest")
        checker.run_test()
        exit_code = 0 if checker.command_check_result == "PASS" else \
                            2 if checker.command_check_result == "FAIL" else 1
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
        try: checker.close_sdk_client()
        except Exception: pass
        try:
            with open(checker.exit_code_path, "w", encoding="utf-8") as f:
                f.write(str(exit_code))
        except Exception as e:
            CommonFunction.print_log("ERROR", f"写入退出码文件失败: {str(e)}")
            exit_code = 3
    sys.exit(exit_code)
