#!/bin/python
"""
Author: Fengmian
Date: 2026/05/13
Usage: python3 bmc/ipmi_power_001.py -i <bmc_ip> -u <username> -p <password>
Update:
2026/05/13: 新增
2026/10/26: 修复真机验证反馈 - 原逻辑为"sleep 固定时长后查一次状态"，对非通算机型
            （存储/GPU 机型电源状态翻转或 OS 相关动作耗时可能更长）会产生误判 FAIL。
            逻辑同 systems_005_power_control_test.py，改为三级阈值持续轮询判定：
              - 实际耗时 <= WarningThreshold（通算机型标准）：PASS，无提示
              - WarningThreshold < 耗时 <= HardTimeout：PASS 但记 WARNING（需人工关注）
              - 耗时 > HardTimeout：FAIL（才认为操作确实未生效）
            不同操作的默认阈值不同（On/Reset 较快，Cycle 涉及断电重开耗时更长）。

IPMI 带外电源状态查看与操作测试（RDSV_BMC_182）

测试步骤：
  1. 查询初始电源状态（chassis power status）
  2. 执行 power on，验证状态为 on
  3. 执行 power reset，验证状态保持 on（重启不断电）
  4. 执行 power cycle，验证状态最终回到 on
  5. 执行 power off，验证状态为 off
  6. 执行 power on，验证状态恢复为 on（恢复现场）

校验策略：
  PASS：各操作命令成功（rc=0，返回含 "Chassis Power Control"），
         持续轮询等待期望状态，实际耗时 <= WarningThreshold
  PASS（含 WARNING）：实际耗时在 WarningThreshold ~ HardTimeout 之间（非通算机型可接受）
  FAIL：命令失败 / 持续轮询超过 HardTimeout 仍未达到期望状态

注意：
  - power cycle 中间会有短暂 off 状态，持续轮询等待最终回到 on
  - power reset 不断电，直接重启，正常应很快回到 on
  - 每步操作之间等待 WaitBetweenOpsSec 秒，避免 BMC 命令冲突
"""

import os
import time
import subprocess
import sys
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from func.common_function import CommonFunction
from func.bmc_test_base import BmcTestBase

class IpmiPowerStatus(BmcTestBase):
    """IPMI 带外电源状态查看与管理测试（含 on/off/cycle/reset）

    用例编号：IPMI_Power_001
    """

    def __init__(self, case: str):
        super().__init__(
            case=case,
            config_path=os.path.join(os.getcwd(), "conf/bmc/ipmi/ipmi_001_power_status.json"),
        )
    def _load_extra_config(self, conf_section: dict) -> None:
        self.IPMI_IFACE          = conf_section.get("IpmiInterface", "lanplus")
        self.QUERY_TIMEOUT       = conf_section.get("QueryTimeoutSec", 30)
        self.WAIT_BETWEEN_OPS    = conf_section.get("WaitBetweenOpsSec", 3)
        self.POLL_INTERVAL       = conf_section.get("PollIntervalSec", 3)

        # 三级阈值：<=WarningThreshold 达标线（通算标准，无提示）；
        # WarningThreshold~HardTimeout 之间 PASS 但记 WARNING；超 HardTimeout 判 FAIL。
        # On/Reset 不涉及断电，耗时短；Cycle 涉及断电重开，耗时更长；Off 最快。
        self.ON_WARN_SEC    = conf_section.get("OnWarningThresholdSec",    conf_section.get("WaitAfterOnSec", 5))
        self.ON_HARD_SEC    = conf_section.get("OnHardTimeoutSec",    120)
        self.RESET_WARN_SEC = conf_section.get("ResetWarningThresholdSec", conf_section.get("WaitAfterResetSec", 5))
        self.RESET_HARD_SEC = conf_section.get("ResetHardTimeoutSec", 120)
        self.CYCLE_WARN_SEC = conf_section.get("CycleWarningThresholdSec", conf_section.get("WaitAfterCycleSec", 15))
        self.CYCLE_HARD_SEC = conf_section.get("CycleHardTimeoutSec", 300)
        self.OFF_WARN_SEC   = conf_section.get("OffWarningThresholdSec",   conf_section.get("WaitAfterOffSec", 5))
        self.OFF_HARD_SEC   = conf_section.get("OffHardTimeoutSec",   60)

        # 各操作对应的阈值映射（供 _check_step 查表使用）
        self._THRESHOLDS = {
            "on":    (self.ON_WARN_SEC,    self.ON_HARD_SEC),
            "reset": (self.RESET_WARN_SEC, self.RESET_HARD_SEC),
            "cycle": (self.CYCLE_WARN_SEC, self.CYCLE_HARD_SEC),
            "off":   (self.OFF_WARN_SEC,   self.OFF_HARD_SEC),
        }

    def _run_ipmi(self, sub_cmd: list, timeout: int = 30) -> tuple:
        """运行 ipmitool 带外命令，返回 (rc, stdout, stderr)"""
        cmd = [
            "ipmitool", "-I", self.IPMI_IFACE,
            "-H", self.BMC_IP,
            "-U", self.USERNAME,
            "-P", self.PASSWORD,
        ] + sub_cmd
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"命令执行超时（>{timeout}s）"
        except Exception as e:
            return -1, "", str(e)

    def _get_power_status(self) -> str:
        """查询当前电源状态，返回 'on' / 'off' / 'unknown'"""
        rc, stdout, _ = self._run_ipmi(["chassis", "power", "status"], self.QUERY_TIMEOUT)
        if rc != 0:
            return "unknown"
        if "on" in stdout.lower():
            return "on"
        if "off" in stdout.lower():
            return "off"
        return "unknown"

    def _do_power_op(self, op: str) -> tuple:
        """执行 chassis power <op>，返回 (success, stdout)"""
        rc, stdout, stderr = self._run_ipmi(["chassis", "power", op], self.QUERY_TIMEOUT)
        success = rc == 0 and "Chassis Power Control" in stdout
        if success:
            CommonFunction.print_log("INFO", f"chassis power {op} 成功：{stdout}")
        else:
            CommonFunction.print_log("ERROR", f"chassis power {op} 失败，rc={rc}，stdout={stdout}，stderr={stderr}")
        return success, stdout

    def _wait_state_graded(self, expected: str, warn_threshold: int, hard_timeout: int) -> tuple:
        """持续轮询等待电源状态变为 expected，三级阈值判定（不在中间点截断）。

        :return: (level, elapsed, actual_state) — level ∈ {"PASS", "WARNING", "FAIL"}
        """
        elapsed = 0
        while elapsed <= hard_timeout:
            state = self._get_power_status()
            if state == expected:
                if elapsed <= warn_threshold:
                    return "PASS", elapsed, state
                CommonFunction.print_log(
                    "WARNING",
                    f"  状态变为 {expected} 耗时 {elapsed}s，超过通算机型标准 {warn_threshold}s，"
                    f"但未超硬超时 {hard_timeout}s（非通算机型可接受，PASS 但需人工关注）"
                )
                return "WARNING", elapsed, state
            time.sleep(self.POLL_INTERVAL)
            elapsed += self.POLL_INTERVAL
        final_state = self._get_power_status()
        CommonFunction.print_log(
            "ERROR", f"  等待状态变为 {expected} 超过硬超时 {hard_timeout}s，实际={final_state}，判定 FAIL"
        )
        return "FAIL", elapsed, final_state

    def _check_step(self, step: int, op: str, expected: str) -> dict:
        """执行一个电源操作步骤并三级阈值验证结果"""
        warn_threshold, hard_timeout = self._THRESHOLDS.get(op, (self.ON_WARN_SEC, self.ON_HARD_SEC))
        CommonFunction.print_log(
            "INFO",
            f"[Step {step}] 执行 power {op}，持续轮询验证状态（期望：{expected}，"
            f"达标线 {warn_threshold}s，硬超时 {hard_timeout}s）"
        )
        op_ok, op_out = self._do_power_op(op)
        if not op_ok:
            return {
                "step": step, "operation": op,
                "expected_state": expected, "actual_state": "cmd_failed",
                "check_result": "FAIL", "level": "FAIL", "detail": op_out,
            }

        level, elapsed, actual = self._wait_state_graded(expected, warn_threshold, hard_timeout)
        # WARNING 仍计为 PASS（不影响整体结果，只是耗时超出通算标准需人工关注）
        check_result = "FAIL" if level == "FAIL" else "PASS"
        CommonFunction.print_log(
            "INFO" if level != "FAIL" else "ERROR",
            f"[Step {step}] power {op} 验证：期望={expected}，实际={actual}，耗时={elapsed}s → {level}"
        )
        return {
            "step": step, "operation": op,
            "expected_state": expected, "actual_state": actual,
            "check_result": check_result, "level": level,
            "detail": f"{op_out}（耗时{elapsed}s）",
        }

    def power_ops_check(self) -> tuple:
        steps = []
        all_results = []

        # 1. 查询初始状态
        CommonFunction.print_log("INFO", "[Step 0] 查询初始电源状态")
        init_state = self._get_power_status()
        CommonFunction.print_log("INFO", f"初始电源状态：{init_state}")
        steps.append({
            "step": 0, "operation": "status",
            "expected_state": "on/off", "actual_state": init_state,
            "check_result": "PASS" if init_state in ("on", "off") else "FAIL",
            "level": "PASS" if init_state in ("on", "off") else "FAIL",
        })
        all_results.append(init_state in ("on", "off"))

        time.sleep(self.WAIT_BETWEEN_OPS)

        # 确保当前是 on（后续步骤依赖），如果 off 先 on 起来
        if init_state != "on":
            CommonFunction.print_log("INFO", "当前状态为 off，先执行 power on 恢复")
            self._do_power_op("on")
            self._wait_state_graded("on", self.ON_WARN_SEC, self.ON_HARD_SEC)

        # 2. power on（已开机状态，应仍返回成功）
        step = self._check_step(1, "on", "on")
        steps.append(step)
        all_results.append(step["check_result"] == "PASS")
        time.sleep(self.WAIT_BETWEEN_OPS)

        # 3. power reset（重启，应仍在 on）
        step = self._check_step(2, "reset", "on")
        steps.append(step)
        all_results.append(step["check_result"] == "PASS")
        time.sleep(self.WAIT_BETWEEN_OPS)

        # 4. power cycle（断电再上电，中间会 off，持续轮询等待回到 on）
        step = self._check_step(3, "cycle", "on")
        steps.append(step)
        all_results.append(step["check_result"] == "PASS")
        time.sleep(self.WAIT_BETWEEN_OPS)

        # 5. power off
        step = self._check_step(4, "off", "off")
        steps.append(step)
        all_results.append(step["check_result"] == "PASS")
        time.sleep(self.WAIT_BETWEEN_OPS)

        # 6. power on（恢复现场）
        step = self._check_step(5, "on", "on")
        steps.append(step)
        all_results.append(step["check_result"] == "PASS")

        final = "PASS" if all(all_results) else "FAIL"
        warn_steps = [s["operation"] for s in steps if s.get("level") == "WARNING"]
        if final == "PASS" and warn_steps:
            CommonFunction.print_log(
                "WARNING",
                f"电源操作测试全部通过，但以下步骤耗时超过通算机型标准（未超硬超时）："
                f"{warn_steps}，需人工关注是否符合被测机型预期"
            )
        CommonFunction.print_log("INFO" if final == "PASS" else "ERROR", f"电源操作测试完成，结果：{final}")
        return final, steps

    def run_test(self):
        test = CommonFunction()
        test.print_log("INFO", f"测试用例名称：{self.TEST_NAME}，测试用例编号：{self.TEST_NUM}")
        test.print_log("INFO", "测试开始")

        check_result, steps = self.power_ops_check()
        self.command_check_result = check_result

        with open(self.result_csv_path, "a", encoding="utf-8") as f:
            for s in steps:
                f.write(
                    f'"{s["step"]}",'
                    f'"{s["operation"]}",'
                    f'"{s["expected_state"]}",'
                    f'"{s["actual_state"]}",'
                    f'"{s["check_result"]}"\n'
                )

        for s in steps:
            test.add_key_value_to_json(
                self.result_json_path, "detail.cycle",
                value={"metrics": f'step_{s["step"]}_{s["operation"]}', "value": s}
            )
        test.add_key_value_to_json(
            self.result_json_path, "summary",
            value={"metrics": self.TEST_NAME, "value": self.command_check_result}
        )
        test.print_log("INFO", f"{self.TEST_NAME}测试完成，结果：{self.command_check_result}")

if __name__ == "__main__":
    exit_code = 0
    checker = None
    try:
        checker = IpmiPowerStatus("IpmiPowerStatus")
        checker.run_test()
        exit_code = 0 if checker.command_check_result == "PASS" else 2
        time.sleep(5)
    except KeyboardInterrupt:
        CommonFunction.print_log("ERROR", "键盘中断")
        exit_code = 130
    except Exception as e:
        CommonFunction.print_log("ERROR", f"未处理异常: {e}")
        traceback.print_exc()
        exit_code = 1
    finally:
        if checker:
            try:
                with open(checker.exit_code_path, "w") as f:
                    f.write(str(exit_code))
            except Exception as e:
                CommonFunction.print_log("ERROR", f"写入退出码失败: {e}")
    sys.exit(exit_code)
