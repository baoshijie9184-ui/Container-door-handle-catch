package com.ruanzhu.doorhandle.module.ai.service;

import java.text.Normalizer;
import java.util.regex.Pattern;

/** Handles explicit credential-read requests before retrieval or model calls. The tool allowlist still applies to any phrasing. */
final class CredentialReadRequest {
    static final String REFUSAL = "当前请求涉及读取密码、密码哈希、密钥或访问令牌。Agent 无权读取这些凭据，人工确认也不能授予访问权限。";
    private static final String CREDENTIAL = "(?:密码(?!策略|规则|要求|格式|强度)|口令|密[钥鑰](?!类型|格式)|访问令牌|认证令牌|数据库连接串|"
            + "\\b(?:passwords?|passphrases?|api[ _-]*keys?|secret[ _-]*keys?|access[ _-]*tokens?|"
            + "refresh[ _-]*tokens?|private[ _-]*keys?|credentials?)\\b)";
    private static final String READ = "(?:读取|查看|查询|列出|显示|获取|提取|导出|打印|告诉我|发给我|给我|是什么|是多少|"
            + "\\b(?:read|show|reveal|retrieve|get|list|export|print|give me|what (?:is|are))\\b)";
    private static final Pattern REQUEST = Pattern.compile(
            READ + ".{0,60}" + CREDENTIAL + "|" + CREDENTIAL + ".{0,40}" + READ,
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
    private static final Pattern RESET_INSTRUCTIONS = Pattern.compile(
            "(?:如何|怎么|怎样)\\s*(?:修改|重置|找回|更换|更新)|\\bhow (?:to|do i) (?:reset|change|rotate|revoke)\\b",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);

    private CredentialReadRequest() {}

    static boolean matches(String text) {
        if (text == null || text.isBlank()) return false;
        for (String clause : Normalizer.normalize(text, Normalizer.Form.NFKC).split("[。；，、;\\r\\n]+")) {
            var reset = RESET_INSTRUCTIONS.matcher(clause);
            String candidate = reset.find() ? clause.substring(reset.end()) : clause;
            if (REQUEST.matcher(candidate).find()) return true;
        }
        return false;
    }
}
