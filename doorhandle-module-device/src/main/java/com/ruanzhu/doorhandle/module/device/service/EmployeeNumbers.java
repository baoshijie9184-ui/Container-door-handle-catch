package com.ruanzhu.doorhandle.module.device.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import java.util.Map;
import java.util.regex.Pattern;

public final class EmployeeNumbers {
    private static final Map<String, String> PREFIXES = Map.of(
            "SUPERVISOR", "SUP", "DETECTION", "DET", "COLLECTION", "COL", "MAINTENANCE", "MNT");
    private static final Pattern PREFIX = Pattern.compile("^(?:EMP|SUP|DET|COL|MNT)-", Pattern.CASE_INSENSITIVE);

    private EmployeeNumbers() {}

    public static String forPosition(String position, String number) {
        String prefix = position == null ? null : PREFIXES.get(position);
        if (prefix == null) {
            throw new BusinessException(400, "请选择有效的人员岗位");
        }
        String suffix = number == null ? "" : PREFIX.matcher(number.strip()).replaceFirst("");
        if (suffix.isBlank()) {
            throw new BusinessException(400, "请填写员工编号的序号");
        }
        String result = prefix + "-" + suffix;
        if (result.codePointCount(0, result.length()) > 50) {
            throw new BusinessException(400, "员工编号最多 50 个字符");
        }
        return result;
    }
}
