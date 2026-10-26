#!/bin/python
"""
Author: Fengmian
Date: 2026/04/24
Usage: python3 bmc/account_003b_password_modify_test.py -i <bmc_ip> -u <username> -p <password>
Update:
2026/04/24: 新增（从 account_003_privilege_test.py 拆分）
2026/10/26: 补全等价类与边界值覆盖（评审要求，密码为着重判定项）——
            密码规范（我方需求）：大小写字母 + 数字 + 特殊字符四要素组合，长度 8~12 位。
            其中「四要素组合」是硬规定（必须拦截违规项）；「长度 8~12」按 OEM 通用
            版本策略处理（与用户名一致：包含我方规则即可，越界不强制定制）。
            正向：原 3 例缺少「全大写主导」「特殊字符种类差异」「12位混合」等组合，
                  补齐为 3 个长度点（下边界8/中间10/上边界12）× 要素组合差异，
                  共 6 例；并新增"修改后旧密码失效 + 新密码可登录"双向校验
                  （原脚本只验证新密码可登录，未验证旧密码已失效，无法发现
                  "接口返回成功但密码实际未变"的假成功）。
            注：不测 9/11 位次边界——与 8/12 同属有效长度等价类，增量价值低。

校验策略（覆盖需求 RDSV_BMC_082 密码修改——正向部分）：

  正向（有效等价类 × 边界值，四要素齐全，应修改成功 + 新密码可登录 + 旧密码失效）：
    - 8位（长度下边界）：Ab@12345
    - 10位（中间长度）：Ab@1234567
    - 12位（长度上边界）：Ab@123456789
    - 8位大写主导：AB@a12345
    - 9位多特殊字符：Ab@#$1234
    - 12位大小写混合强化：AbCdEf@12345

  PASS：所有合法密码修改成功、新密码可登录、旧密码已失效
  FAIL：任意合法密码修改失败 / 新密码无法登录 / 旧密码仍可登录（假成功）

  注：密码负向边界值验证见 account_003c_password_negative_test.py
  finally 回滚：删除测试账号
"""

import os
import sys
import time
import traceback
import random as _random

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from func.common_function import CommonFunction
from func.bmc_test_base import BmcTestBase
from func.bmc_account_function import delete_account_safe, update_account_safe

from redfish_sdk import RedfishClient, RedfishException
from redfish_sdk.models import Account

# 正向密码测试集（有效等价类 × 边界值，四要素齐全：大写+小写+数字+特殊字符，8~12位）
VALID_PASSWORDS = [
    ("Ab@12345",         "8位（长度下边界，四要素齐全）"),
    ("Ab@1234567",       "10位（中间长度，四要素齐全）"),
    ("Ab@123456789",     "12位（长度上边界，四要素齐全）"),
    ("AB@a12345",        "8位大写主导（大写等价类强化，含小写满足四要素）"),
    ("Ab@#$1234",        "9位含多种特殊字符（特殊字符等价类强化）"),
    ("AbCdEf@12345",     "12位大小写混合强化（混合等价类强化）"),
]

class AccountPasswordModifyTest(BmcTestBase):
    """Account 密码修改正向测试

    用例编号：Redfish_Account_003b
    检查项：合法密码修改成功、新密码可登录、旧密码已失效（正向等价类/边界值）
    """

    def __init__(self, case: str):
        super().__init__(
            case=case,
            config_path=os.path.join(os.getcwd(), "conf/bmc/account/account_test.json"),
        )

    def _load_extra_config(self, conf_section: dict) -> None:
        ta = conf_section["TestAccount"]
        self.TEST_ACCOUNT_USER = ta["UserName"] + "".join(_random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(2))
        self.TEST_ACCOUNT_PASS = ta["Password"]
        self.test_username    = None  # 预初始化，run_test 中实际赋值
        self.current_password = None  # 预初始化，run_test 中实际赋值

    def close_sdk_client(self):
        if self.client:
            try: self.client.close()
            except Exception: pass

    def _cleanup(self):
        if self.test_username and self.client:
            try:
                delete_account_safe(self.client, self.test_username)
            except Exception as e:
                CommonFunction.print_log("WARNING", f"[清理] 删除测试账号失败（可忽略）：{e}")

    def _try_login(self, password: str) -> bool:
        try:
            c = RedfishClient(self.BMC_IP, self.test_username, password)
            c.get_accounts()
            try: c.close()
            except Exception: pass
            return True
        except RedfishException:
            return False

    def run_test(self):
        test = CommonFunction()
        test.print_log("INFO", "测试用例名称：Account密码修改正向测试，测试用例编号：Redfish_Account_003b")
        test.print_log("INFO", "测试开始")

        CommonFunction.print_log("INFO", f"连接 BMC：{self.BMC_IP}")
        self.client = RedfishClient(self.BMC_IP, self.USERNAME, self.PASSWORD)

        result = "PASS"
        rows = []  # (label, level, detail) — 逐用例记录，便于定位失败项

        try:
            # Step 0：预检查
            CommonFunction.print_log("INFO", "Step 0：预检查测试账号是否已存在")
            existing = self.client.get_accounts()
            if any(a.user_name == self.TEST_ACCOUNT_USER for a in existing):
                delete_account_safe(self.client, self.TEST_ACCOUNT_USER)

            # Step 1：创建测试账号
            CommonFunction.print_log("INFO", f"Step 1：创建测试账号 {self.TEST_ACCOUNT_USER}")
            self.client.add_account(Account(
                UserName=self.TEST_ACCOUNT_USER,
                Password=self.TEST_ACCOUNT_PASS,
                RoleId="Operator",
                Enabled=True
            ))
            self.test_username = self.TEST_ACCOUNT_USER
            self.current_password = self.TEST_ACCOUNT_PASS

            # Step 2：正向等价类/边界值逐一验证
            CommonFunction.print_log("INFO", "=== Step 2：正向密码等价类/边界值验证 ===")
            for pw, desc in VALID_PASSWORDS:
                CommonFunction.print_log("INFO", f"  修改密码 → [{desc}]")
                old_password = self.current_password
                try:
                    update_account_safe(self.client, self.test_username,
                                        Account(Password=pw))
                except RedfishException as e:
                    CommonFunction.print_log("ERROR",
                        f"    ✗ 合法密码 [{desc}] 修改被拒：{str(e)[:100]}")
                    result = "FAIL"
                    rows.append((f"valid_len{len(pw)}", "FAIL", f"{desc} | 修改被拒：{str(e)[:100]}"))
                    continue

                # 2a. 新密码可登录
                if not self._try_login(pw):
                    CommonFunction.print_log("ERROR",
                        f"    ✗ 密码修改接口成功，但新密码无法登录（{desc}）")
                    result = "FAIL"
                    rows.append((f"valid_len{len(pw)}", "FAIL",
                                 f"{desc} | 接口成功但新密码无法登录"))
                    continue

                # 2b. 旧密码必须失效（防"接口返回成功但密码实际未变"的假成功）
                if old_password != pw and self._try_login(old_password):
                    CommonFunction.print_log("ERROR",
                        f"    ✗ 密码修改接口成功且新密码可登录，但旧密码仍可登录"
                        f"（{desc}）——疑似假成功，密码实际未变更")
                    result = "FAIL"
                    rows.append((f"valid_len{len(pw)}", "FAIL",
                                 f"{desc} | 旧密码仍可登录，疑似假成功"))
                    # 旧密码仍有效，回滚 current_password 保持环境一致
                    self.current_password = old_password
                    continue

                CommonFunction.print_log("INFO",
                    f"    ✓ 修改成功：新密码可登录，旧密码已失效")
                self.current_password = pw
                rows.append((f"valid_len{len(pw)}", "PASS",
                             f"{desc} | 新密码可登录，旧密码已失效"))

        except RedfishException as e:
            CommonFunction.print_log("ERROR", f"Redfish 接口异常：{e}")
            result = "FAIL"
        except Exception as e:
            CommonFunction.print_log("ERROR", f"未预期异常：{type(e).__name__}: {e}")
            traceback.print_exc()
            result = "FAIL"

        self.command_check_result = result
        with open(self.result_csv_path, "a", encoding="utf-8") as f:
            for label, level, detail in rows:
                f.write(f"{label},{level}\n")
            f.write(f"password_modify_positive,{result}\n")
        for label, level, detail in rows:
            test.add_key_value_to_json(self.result_json_path, "detail.cycle",
                                       value={"metrics": label,
                                              "value": {"result": level, "detail": detail}})
        test.add_key_value_to_json(self.result_json_path, "summary",
                                   value={"metrics": "Account密码修改正向测试", "value": result})
        test.print_log("INFO", f"Account密码修改正向测试完成，结果：{result}")

if __name__ == "__main__":
    exit_code = 0
    checker = None
    try:
        checker = AccountPasswordModifyTest("AccountPasswordModifyTest")
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
        try:
            checker._cleanup()
            checker.close_sdk_client()
        except Exception: pass
        try:
            with open(checker.exit_code_path, "w", encoding="utf-8") as f:
                f.write(str(exit_code))
        except Exception as e:
            CommonFunction.print_log("ERROR", f"写入退出码文件失败: {str(e)}")
            exit_code = 3
    sys.exit(exit_code)
