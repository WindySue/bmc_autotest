#!/bin/python
"""
Author: Fengmian
Date: 2026/04/24
Usage: python3 bmc/account_003c_password_negative_test.py -i <bmc_ip> -u <username> -p <password>
Update:
2026/04/24: 新增
2026/06/09: 新增 guard 账号安全网机制 —— 仅作预防性告警。
            本脚本只修改测试账号（非 Admin）的密码，Admin session 不受影响。
            guard 账号的作用：若未来代码变更意外导致 Admin 密码被改，可快速定位
            并通过 guard 账号恢复。当前版本不触发 restore 逻辑（仅记录安全网状态）。
2026/10/26: 补全等价类与边界值覆盖（评审要求，密码为着重判定项）——
            密码规范（我方需求）：大小写字母 + 数字 + 特殊字符四要素组合，长度 8~12 位。
            「四要素组合」是硬规定（缺任一要素必须拦截，否则 FAIL）；
            「长度 8~12」按 OEM 通用版本策略处理（与用户名一致：包含我方规则即可，
            越界不强制定制，未拦截记 WARNING 不 FAIL）。
            反向补齐：
              - 缺要素等价类从 2 例扩到 4 例（缺大写/缺小写/缺数字/缺特殊字符各一例，
                原脚本漏了"缺小写"和"缺数字"两个等价类）；
              - 长度越界（7位过短/13位超长）单独归为宽松组，未拦截记 WARNING；
              - 新增"接口接受但密码实际未生效"的登录验证（不能只看接口返回码，
                防止 BMC 静默忽略非法密码却返回成功）。
            注：不测 9/11 位次边界——与 8/12 同属有效长度等价类，增量价值低。

校验策略（覆盖需求 RDSV_BMC_082 密码修改——反向部分）：

  反向-严格（四要素缺失，硬规定，必须拦截，否则 FAIL）：
    - 纯数字（缺大写/小写/特殊字符）：12345678
    - 纯小写+数字（缺大写/特殊字符）：abcde123
    - 纯大写+数字（缺小写/特殊字符）：ABCDE123
    - 大小写+数字（缺特殊字符）：Abcd1234
    - 大小写+特殊字符（缺数字）：Abcd@#$w

  反向-宽松（长度越界，OEM 通用版本不强制定制，未拦截记 WARNING 不 FAIL）：
    - 7位过短（低于下限8位）：Ab@1234
    - 13位超长（超过上限12位）：Ab@1234567890x

  判定依据（每个用例均做登录验证，不只看接口返回码）：
    - BMC 直接拒绝（抛异常）→ PASS
    - 接口接受但非法密码无法登录（内部拦截生效）→ WARNING（行为符合预期，接口不规范）
    - 接口接受且非法密码可登录 → 严格组 FAIL / 宽松组 WARNING

  PASS：严格组全部被拦截；宽松组不影响结果
  FAIL：四要素缺失的密码被 BMC 接受且可登录（违反硬规定）

  注：密码正向边界值验证见 account_003b_password_modify_test.py
  finally 回滚：删除测试账号
"""

import os
import time
import sys
import traceback
import random as _random

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from func.common_function import CommonFunction
from func.bmc_test_base import BmcTestBase
from func.bmc_account_function import (
    delete_account_safe,
    update_account_safe,
    setup_guard_account,
    teardown_guard_account,
)

from redfish_sdk import RedfishClient, RedfishException
from redfish_sdk.models import Account

# 反向-严格：四要素缺失（硬规定，必须拦截；接受且可登录 → FAIL）
# 等价类覆盖：4 个要素各缺一例 + 全缺（纯数字）一例
INVALID_MISSING_ELEMENT = [
    ("12345678",   "纯数字（缺大写/小写/特殊字符）"),
    ("abcde123",   "纯小写+数字（缺大写/特殊字符）"),
    ("ABCDE123",   "纯大写+数字（缺小写/特殊字符）"),
    ("Abcd1234",   "大小写+数字（缺特殊字符）"),
    ("Abcd@#$w",   "大小写+特殊字符（缺数字）"),
]

# 反向-宽松：长度越界（OEM 通用版本不强制定制，未拦截记 WARNING 不 FAIL）
INVALID_LEN_WARN = [
    ("Ab@1234",        "7位过短（低于下限8位）"),
    ("Ab@1234567890x", "13位超长（超过上限12位）"),
]

class AccountPasswordNegativeTest(BmcTestBase):
    """Account 密码修改反向测试

    用例编号：Redfish_Account_003c
    检查项：
    - 反向-严格：四要素缺失的密码必须被 BMC 拦截（硬规定）
    - 反向-宽松：长度越界的密码未拦截记 WARNING（OEM 通用版本，不强制定制）
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

    def _try_invalid_password(self, pw: str, strict: bool) -> tuple:
        """尝试设置非法密码并做登录验证（不只看接口返回码）。

        Parameters:
            pw:     非法密码
            strict: True=四要素缺失（严格，接受且可登录 → FAIL）；
                    False=长度越界（宽松，接受且可登录 → WARNING）

        Returns:
            (level, detail) — level ∈ {"PASS", "WARNING", "FAIL"}
        """
        try:
            update_account_safe(self.client, self.test_username, Account(Password=pw))
        except RedfishException as e:
            return "PASS", f"BMC 拒绝非法密码（符合预期）：{str(e)[:80]}"

        # 接口未报错，进一步验证非法密码是否真的可登录（防静默忽略却返回成功）
        if self._try_login(pw):
            if strict:
                return ("FAIL",
                        "非法密码被接受且可登录，违反密码复杂度硬规定！")
            return ("WARNING",
                    "长度越界密码被接受且可登录（OEM 通用版本按通用定义开发，"
                    "未按我方 8~12 位定制拦截，记 WARNING 不 FAIL，避免要求二次开发）")

        # 接口接受但无法登录：内部拦截生效，但接口行为不规范
        # 注意：此时密码可能已被 BMC 内部改为其他值或保持原值，回滚 current_password
        if not self._try_login(self.current_password):
            # 原密码也登录不了了——密码状态未知，尝试用非法密码继续（已可登录）
            self.current_password = pw
        return ("WARNING",
                "接口未报错但非法密码无法登录（内部拦截生效，接口行为不规范，记WARNING）")

    def run_test(self):
        test = CommonFunction()
        test.print_log("INFO", "测试用例名称：Account密码修改反向测试，测试用例编号：Redfish_Account_003c")
        test.print_log("INFO", "测试开始")

        CommonFunction.print_log("INFO", f"连接 BMC：{self.BMC_IP}")
        self.client = RedfishClient(self.BMC_IP, self.USERNAME, self.PASSWORD)

        result = "PASS"
        guard = None
        rows = []  # (label, level, detail) — 逐用例记录，便于定位失败项

        try:
            # ── 前置：建立 guard 安全网（预防性，本脚本只改测试账号密码）────────
            CommonFunction.print_log("INFO",
                "前置步骤：建立 guard 账号安全网（预防性，本脚本不修改 Admin 凭据）")
            guard = setup_guard_account(self.client, self.BMC_IP, self.USERNAME)
            if guard is None:
                CommonFunction.print_log("WARNING",
                    "  ✗ guard 账号建立失败（账号数已满或 BMC 权限不足），"
                    "无安全网情况下禁止执行密码反向测试，本次测试跳过 → WARNING")
                result = "WARNING"
                raise RuntimeError("guard_not_ready")   # 跳至 finally 清理，不执行测试
            else:
                CommonFunction.print_log("INFO",
                    "  guard 安全网就绪（本脚本正常不会触发恢复逻辑）")

            # Step 0：预检查
            CommonFunction.print_log("INFO", "Step 0：预检查测试账号是否已存在")
            existing = self.client.get_accounts()
            if any(a.user_name == self.TEST_ACCOUNT_USER for a in existing):
                delete_account_safe(self.client, self.TEST_ACCOUNT_USER)

            # Step 1：创建测试账号（合法密码）
            CommonFunction.print_log("INFO", f"Step 1：创建测试账号 {self.TEST_ACCOUNT_USER}")
            self.client.add_account(Account(
                UserName=self.TEST_ACCOUNT_USER,
                Password=self.TEST_ACCOUNT_PASS,
                RoleId="Operator",
                Enabled=True
            ))
            self.test_username = self.TEST_ACCOUNT_USER
            self.current_password = self.TEST_ACCOUNT_PASS

            # Step 2：反向-严格（四要素缺失，硬规定）
            CommonFunction.print_log("INFO", "=== Step 2：反向-严格（四要素缺失，必须拦截）===")
            for pw, desc in INVALID_MISSING_ELEMENT:
                CommonFunction.print_log("INFO", f"  尝试修改密码 → [{desc}]（期望被拒）")
                level, detail = self._try_invalid_password(pw, strict=True)
                if level == "FAIL":
                    result = "FAIL"
                    self.current_password = pw   # 非法密码已生效，记录以便清理
                    CommonFunction.print_log("ERROR", f"    ✗ {detail}")
                elif level == "WARNING":
                    CommonFunction.print_log("WARNING", f"    ⚠ {detail}")
                else:
                    CommonFunction.print_log("INFO", f"    ✓ {detail}")
                rows.append((f"strict_len{len(pw)}", level, f"{desc} | {detail}"))

            # Step 3：反向-宽松（长度越界，WARNING 不 FAIL）
            CommonFunction.print_log("INFO",
                "=== Step 3：反向-宽松（长度越界，OEM 通用版本不强制定制，记 WARNING）===")
            for pw, desc in INVALID_LEN_WARN:
                CommonFunction.print_log("INFO", f"  尝试修改密码 → [{desc}]")
                level, detail = self._try_invalid_password(pw, strict=False)
                if level == "FAIL":
                    result = "FAIL"
                    self.current_password = pw
                    CommonFunction.print_log("ERROR", f"    ✗ {detail}")
                elif level == "WARNING":
                    CommonFunction.print_log("WARNING", f"    ⚠ {detail}")
                else:
                    CommonFunction.print_log("INFO", f"    ✓ {detail}")
                rows.append((f"len_warn_len{len(pw)}", level, f"{desc} | {detail}"))

        except RedfishException as e:
            CommonFunction.print_log("ERROR", f"Redfish 接口异常：{e}")
            result = "FAIL"
        except RuntimeError as e:
            if str(e) == "guard_not_ready":
                pass   # 已在上方记录 WARNING，result 已置 WARNING，正常流程
            else:
                CommonFunction.print_log("ERROR", f"未预期 RuntimeError：{e}")
                traceback.print_exc()
                result = "FAIL"
        except Exception as e:
            CommonFunction.print_log("ERROR", f"未预期异常：{type(e).__name__}: {e}")
            traceback.print_exc()
            result = "FAIL"

        finally:
            # ── teardown：清理临时 guard 账号 ─────────────────────────────────
            if guard and guard.created_by_us:
                CommonFunction.print_log("INFO", "teardown：清理临时 guard 账号...")
                teardown_guard_account(guard, self.client)

        self.command_check_result = result
        with open(self.result_csv_path, "a", encoding="utf-8") as f:
            for label, level, detail in rows:
                f.write(f"{label},{level}\n")
            f.write(f"password_modify_negative,{result}\n")
        for label, level, detail in rows:
            test.add_key_value_to_json(self.result_json_path, "detail.cycle",
                                       value={"metrics": label,
                                              "value": {"result": level, "detail": detail}})
        test.add_key_value_to_json(self.result_json_path, "summary",
                                   value={"metrics": "Account密码修改反向测试", "value": result})
        test.print_log("INFO", f"Account密码修改反向测试完成，结果：{result}")

if __name__ == "__main__":
    exit_code = 0
    checker = None
    try:
        checker = AccountPasswordNegativeTest("AccountPasswordNegativeTest")
        checker.run_test()
        exit_code = 0 if checker.command_check_result in ("PASS", "WARNING") else \
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
